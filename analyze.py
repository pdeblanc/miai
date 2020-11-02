import json
import re

import pexpect  # type: ignore

GTP_COORDS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'

START_COMMAND = " ".join([
    "katago analysis -analysis-threads 12 -config analysis_config.cfg",
    "-model g170e-b20c256x2-s5303129600-d1228401921.bin.gz"
])

MOVE_REGEX = re.compile(r'= \w+')


def rough_value(initial_stones, initial_player, komi, katago_process, visits):
    query = json.dumps({
        "id": "foo",
        "initialStones": initial_stones,
        "initialPlayer": initial_player,
        "moves": [],
        "rules": "japanese",
        "komi": komi,
        "boardXSize": 19,
        "boardYSize": 19,
        "analyzeTurns": [0],
        "maxVisits": visits,
    })
    katago_process.sendline(query)
    katago_process.expect(r"\n")
    katago_process.expect(r"({.*})\r\n")
    response = katago_process.match[0]
    # print(response)
    response_data = json.loads(response)
    # I believe the scoreLead is always from black's perspective
    return response_data['rootInfo']['scoreLead']


def fine_value(stones, player, katago_process, visits):
    komi = 0
    delta = rough_value(stones, player, komi, katago_process, visits//4)
    komi += round(2 * delta) / 2
    delta = rough_value(stones, player, komi, katago_process, visits//4)
    komi += round(2 * delta) / 2
    delta = rough_value(stones, player, komi, katago_process, visits//2)
    komi += delta
    return komi


def mean_value(initial_stones, katago_process, visits=2**10):
    b_value = fine_value(initial_stones, "B", katago_process, visits//2)
    w_value = fine_value(initial_stones, "W", katago_process, visits//2)
    return (b_value + w_value) / 2


def analyze():
    child = pexpect.spawn(START_COMMAND, encoding='utf-8')
    child.expect('Started, ready to begin handling requests')
    child.expect(r"\n")
    print(mean_value([["B", "Q4"], ["W", "D4"]], child))


if __name__ == "__main__":
    analyze()
