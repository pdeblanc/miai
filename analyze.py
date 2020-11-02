import json
import random
import re

import pexpect  # type: ignore
from sgfmill import sgf, boards

GTP_COORDS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'

START_COMMAND = " ".join([
    "katago analysis -analysis-threads 12 -config analysis_config.cfg",
    "-model g170e-b20c256x2-s5303129600-d1228401921.bin.gz"
])

MOVE_REGEX = re.compile(r'= \w+')


ALPHABET = 'ABCDEFGHJKLMNOPQRST'


def sgf_to_kata(stones):
    return [
        [s[0].upper(), ALPHABET[s[1][0]] + str(s[1][1] + 1)]
        for s in stones
    ]


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


def stats(initial_stones, katago_process, visits=2**8):
    print(initial_stones)
    b_value = fine_value(initial_stones, "B", katago_process, visits//2)
    w_value = fine_value(initial_stones, "W", katago_process, visits//2)
    mean_value = (b_value + w_value) / 2
    temperature = b_value - w_value
    return mean_value, temperature


def get_process():
    child = pexpect.spawn(START_COMMAND, encoding='utf-8')
    child.expect('Started, ready to begin handling requests')
    child.expect(r"\n")
    return child


def analyze():
    child = get_process()
    print(stats([["B", "Q4"], ["W", "D4"]], child))


def annotate_sgf():
    with open("YoRHa2B-hakuseki.sgf", "rb") as f:
        game = sgf.Sgf_game.from_bytes(f.read())
    root = game.get_root()
    board = boards.Board(root.get_size())
    board.apply_setup(*root.get_setup_stones())
    process = get_process()
    mean, temp = stats(board.list_occupied_points(), process)
    root.set("C", f"Mean value: {mean}\nTemperature: {temp}")
    for child in root:
        annotate_subtree(child, board.copy(), mean, temp, process)
    open("out.sgf", "wb").write(game.serialise())


def annotate_subtree(node, board, prev_mean, prev_temp, process):
    print(board)
    color, coords = node.get_move()
    if color is not None and type(coords) is tuple:
        board.play(*coords, color)
    stones = sgf_to_kata(board.list_occupied_points())
    mean, temp = stats(stones, process)
    move_value = mean - prev_mean
    node.set("C", f"Move value: {move_value}\nMean value: {mean}\nTemperature: {temp}\nstones{stones}")
    if len(stones) < 10:
        for child in node:
            annotate_subtree(child, board.copy(), mean, temp, process)


if __name__ == "__main__":
    annotate_sgf()
