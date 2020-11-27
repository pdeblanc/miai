import json
import os
import shlex
import subprocess
import threading
import time
import traceback
from functools import partial
from typing import Callable, Dict, Tuple

from kivy.utils import platform  # type: ignore

from katrain.core.utils import find_package_resource  # type: ignore


def get_result(func):
    done = False
    result = None

    def callback(data):
        nonlocal done, result
        done = True
        result = data

    def error_callback(data):
        raise RuntimeError

    func(callback, error_callback)
    while not done:
        time.sleep(0.001)
    return result


class EngineDiedException(Exception):
    pass


class KataGoEngine:
    """Starts and communicates with the KataGO analysis engine"""
    def __init__(
        self,
        exe: str = "katago",
        model: str = "g170e-b20c256x2-s5303129600-d1228401921.bin.gz",
        cfg: str = "analysis_config.cfg",
        threads: int = 4,
        silent: bool = True,
    ):
        self.silent = silent
        self.queries: Dict[str, Tuple[Callable, Callable, float]] = {}
        self.query_counter = 0
        self.katago_process = None
        self.base_priority = 0
        # force these settings:
        self.override_settings = {"reportAnalysisWinratesAs": "BLACK"}
        self._lock = threading.Lock()
        self.analysis_thread = None
        self.stderr_thread = None
        self.shell = False

        if not exe:
            if platform == "win":
                exe = "katrain/KataGo/katago.exe"
            elif platform == "linux":
                exe = "katrain/KataGo/katago"
            else:  # e.g. MacOS after brewing
                exe = "katago"

        if exe.startswith("katrain"):
            exe = find_package_resource(exe)

        exepath, exename = os.path.split(exe)
        if exepath and not os.path.isfile(exe):
            print(f"Katago exe ({exe}) not found.")
            return  # don't start
        elif not exepath and not any(
            os.path.isfile(os.path.join(path, exe))
            for path in os.environ.get("PATH", "").split(os.pathsep)
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
            f'"{exe}" analysis -model "{model}" -config "{cfg}" '
            f'-analysis-threads {threads}'
        )
        self.start()

    def start(self):
        try:
            if not self.silent:
                print(f"Starting KataGo with {self.command}")
            startupinfo = None  # stop popups on windows/pyinstaller
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
        self.analysis_thread = threading.Thread(
            target=self._analysis_read_thread, daemon=True
        ).start()
        self.stderr_thread = threading.Thread(
            target=self._read_stderr_thread, daemon=True
        ).start()

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
                    died_msg = "Engine missing DLL"
                else:
                    os_error += f"status {code}"
                    died_msg = f"Engine died unexpectedly: {os_error}"
                print(died_msg)
                self.katago_process = None
            else:
                died_msg = f"Engine died unexpectedly: {os_error}"
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
                        print(
                            "ERROR in processing KataGo stderr:",
                            line, "Exception", e
                        )
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
                    print(f"Query result {query_id} discarded")
                    continue
                callback, error_callback, start_time = self.queries[query_id]
                if "error" in analysis:
                    del self.queries[query_id]
                    if error_callback:
                        error_callback(analysis)
                    else:
                        if not self.silent:
                            print(f"{analysis} received from KataGo")
                elif "warning" in analysis:
                    print(f"{analysis} received from KataGo")
                else:
                    del self.queries[query_id]
                    time_taken = time.time() - start_time
                    if not self.silent:
                        print(
                            f"[{time_taken:.1f}][{query_id}] "
                            f"KataGo Analysis Received: {analysis.keys()}"
                        )
                        print(line)
                    try:
                        callback(analysis)
                    except Exception as e:
                        print(f"Error in callback for query {query_id}: {e}")
            except Exception as e:
                print(f"Exception {e} while processing KataGo output {line}")
                traceback.print_exc()

    def query_synchronous(self, query):
        return get_result(partial(self.send_query, query))

    def send_query(self, query, callback, error_callback):
        with self._lock:
            self.query_counter += 1
            if "id" not in query:
                query["id"] = f"QUERY:{str(self.query_counter)}"
            self.queries[query["id"]] = (callback, error_callback, time.time())
        if self.katago_process:
            if not self.silent:
                print(f"Sending query {query['id']}: {json.dumps(query)}")
            try:
                self.katago_process.stdin.write(
                    (json.dumps(query) + "\n").encode()
                )
                self.katago_process.stdin.flush()
            except OSError as e:
                self.check_alive(os_error=str(e), exception_if_dead=True)
                return  # do not raise, since there's nothing to catch it
