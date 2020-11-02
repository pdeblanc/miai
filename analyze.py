import json
import re

import pexpect  # type: ignore

GTP_COORDS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'

START_COMMAND = " ".join([
    "katago analysis -analysis-threads 12 -config analysis_config.cfg",
    "-model g170e-b20c256x2-s5303129600-d1228401921.bin.gz"
])

MOVE_REGEX = re.compile(r'= \w+')


def rough_value(initial_stones, initial_player, komi, katago_process):
    query = json.dumps({
        "id": "foo",
        "initialStones": initial_stones,
        "initialPlayer": initial_player,
        "moves": [],
        "rules": "japanese",
        "komi": komi,
        "boardXSize": 19,
        "boardYSize": 19,
        "analyzeTurns": [0]
    })
    katago_process.sendline(query)
    katago_process.expect(r"\n")
    katago_process.expect(r"({.*})\r\n")
    response = katago_process.match[0]
    # print(response)
    response_data = json.loads(response)
    # I believe the scoreLead is always from black's perspective
    return response_data['rootInfo']['scoreLead']


def fine_value(initial_stones, initial_player, katago_process):
    komi = 0
    delta = rough_value(initial_stones, initial_player, komi, katago_process)
    print("komi", komi, "delta", delta)
    komi += round(2 * delta) / 2
    delta = rough_value(initial_stones, initial_player, komi, katago_process)
    print("komi", komi, "delta", delta)
    komi += delta
    return komi


def analyze():
    child = pexpect.spawn(START_COMMAND, encoding='utf-8')
    child.expect('Started, ready to begin handling requests')
    child.expect(r"\n")
    print(rough_value([["W", "Q4"], ["W", "C4"]], "B", 0.0, child))
    print(fine_value([["W", "Q4"], ["W", "C4"]], "B", child))


if __name__ == "__main__":
    analyze()
