import copy
import json
import os
import shlex
import subprocess
import threading
import time
import traceback
from typing import Callable, Dict, Optional

from kivy.utils import platform

from katrain.core.game_node import GameNode
from katrain.core.lang import i18n
from katrain.core.utils import find_package_resource


class EngineDiedException(Exception):
    pass


class KataGoEngine:
    """Starts and communicates with the KataGO analysis engine"""
    def __init__(self, config):
        self.queries = {}  # outstanding query id -> start time and callback
        self.config = config
        self.query_counter = 0
        self.katago_process = None
        self.base_priority = 0
        self.override_settings = {"reportAnalysisWinratesAs": "BLACK"}  # force these settings
        self._lock = threading.Lock()
        self.analysis_thread = None
        self.stderr_thread = None
        self.shell = False

        exe = config.get("katago", "").strip()
        if config.get("altcommand", ""):
            self.command = config["altcommand"]
            self.shell = True
        else:
            if not exe:
                if platform == "win":
                    exe = "katrain/KataGo/katago.exe"
                elif platform == "linux":
                    exe = "katrain/KataGo/katago"
                else:  # e.g. MacOS after brewing
                    exe = "katago"

            model = find_package_resource(config["model"])
            cfg = find_package_resource(config["config"])
            if exe.startswith("katrain"):
                exe = find_package_resource(exe)

            exepath, exename = os.path.split(exe)
            if exepath and not os.path.isfile(exe):
                print(f"Katago exe ({exe}) not found.")
                return  # don't start
            elif not exepath and not any(
                os.path.isfile(os.path.join(path, exe)) for path in os.environ.get("PATH", "").split(os.pathsep)
            ):
                print(f"Katago exe ({exe}) not found in path.")
                return  # don't start
            elif not os.path.isfile(model):
                print(f"Katago model ({model}) not found in path.")
                return  # don't start
            elif not os.path.isfile(cfg):
                print(f"Katago config ({cfg}) not found.")
                return  # don't start
            self.command = shlex.split(
                f'"{exe}" analysis -model "{model}" -config "{cfg}" -analysis-threads {config["threads"]}'
            )
        self.start()

    def start(self):
        try:
            print(f"Starting KataGo with {self.command}")
            startupinfo = None # stop command box popups on windows/pyinstaller
            if hasattr(subprocess, "STARTUPINFO"):
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            self.katago_process = subprocess.Popen(
                self.command,
                startupinfo=startupinfo,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=self.shell,
            )
        except (FileNotFoundError, PermissionError, OSError) as e:
            print(f"Starting katago failed: {e}")
            return  # don't start
        self.analysis_thread = threading.Thread(target=self._analysis_read_thread, daemon=True).start()
        self.stderr_thread = threading.Thread(target=self._read_stderr_thread, daemon=True).start()

    def restart(self):
        self.queries = {}
        self.shutdown(finish=False)
        self.start()

    def check_alive(self, os_error="", exception_if_dead=False):
        ok = self.katago_process and self.katago_process.poll() is None
        if not ok and exception_if_dead:
            if self.katago_process:
                code = self.katago_process and self.katago_process.poll()
                if code == 3221225781:
                    died_msg = i18n._("Engine missing DLL")
                else:
                    os_error += f"status {code}"
                    died_msg = i18n._("Engine died unexpectedly").format(error=os_error)
                print(died_msg)
                self.katago_process = None
            else:
                died_msg = i18n._("Engine died unexpectedly").format(error=os_error)
            raise EngineDiedException(died_msg)
        return ok

    def shutdown(self, finish=False):
        process = self.katago_process
        if finish and process:
            while self.queries and process.poll() is None:
                time.sleep(0.1)
        if process:
            self.katago_process = None
            process.terminate()
        if self.stderr_thread:
            self.stderr_thread.join()
        if self.analysis_thread:
            self.analysis_thread.join()

    def is_idle(self):
        return not self.queries

    def _read_stderr_thread(self):
        while self.katago_process is not None:
            try:
                line = self.katago_process.stderr.readline()
                if line:
                    try:
                        print(line.decode(errors="ignore").strip())
                    except Exception as e:
                        print("ERROR in processing KataGo stderr:", line, "Exception", e)
                elif self.katago_process:
                    self.check_alive(exception_if_dead=True)
            except Exception as e:
                print(f"Exception in reading stdout {e}")
                return

    def _analysis_read_thread(self):
        while self.katago_process is not None:
            try:
                line = self.katago_process.stdout.readline().strip()
                if self.katago_process and not line:
                    self.check_alive(exception_if_dead=True)
            except OSError as e:
                self.check_alive(os_error=str(e), exception_if_dead=True)
                return

            if b"Uncaught exception" in line:
                print(f"KataGo Engine Failed: {line.decode(errors='ignore')}")
                return
            if not line:
                continue
            try:
                analysis = json.loads(line)
                if "id" not in analysis:
                    print(f"Error without ID {analysis} received from KataGo")
                    continue
                query_id = analysis["id"]
                if query_id not in self.queries:
                    print(f"Query result {query_id} discarded -- recent new game?")
                    continue
                callback, error_callback, start_time, next_move = self.queries[query_id]
                if "error" in analysis:
                    del self.queries[query_id]
                    if error_callback:
                        error_callback(analysis)
                    elif not (next_move and "Illegal move" in analysis["error"]):  # sweep
                        print(f"{analysis} received from KataGo")
                elif "warning" in analysis:
                    print(f"{analysis} received from KataGo")
                else:
                    del self.queries[query_id]
                    time_taken = time.time() - start_time
                    print(
                        f"[{time_taken:.1f}][{query_id}] KataGo Analysis Received: {analysis.keys()}"
                    )
                    print(line)
                    try:
                        callback(analysis)
                    except Exception as e:
                        print(f"Error in engine callback for query {query_id}: {e}")
            except Exception as e:
                print(f"Unexpected exception {e} while processing KataGo output {line}")
                traceback.print_exc()

    def send_query(self, query, callback, error_callback, next_move=None):
        with self._lock:
            self.query_counter += 1
            if "id" not in query:
                query["id"] = f"QUERY:{str(self.query_counter)}"
            self.queries[query["id"]] = (callback, error_callback, time.time(), next_move)
        if self.katago_process:
            print(f"Sending query {query['id']}: {json.dumps(query)}")
            try:
                self.katago_process.stdin.write((json.dumps(query) + "\n").encode())
                self.katago_process.stdin.flush()
            except OSError as e:
                self.check_alive(os_error=str(e), exception_if_dead=True)
                return  # do not raise, since there's nothing to catch it
