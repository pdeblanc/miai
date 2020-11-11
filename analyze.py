import json
import re
import sys

import pexpect  # type: ignore
from sgfmill import sgf, boards, ascii_boards

GTP_COORDS = 'ABCDEFGHJKLMNOPQRSTUVWXYZ'

START_COMMAND = " ".join([
    "katago analysis -analysis-threads 1 -config analysis_config.cfg",
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
        "rules": "tromp-taylor",
        "komi": komi,
        "boardXSize": 19,
        "boardYSize": 19,
        "analyzeTurns": [0],
        "maxVisits": visits,
    })
    katago_process.sendline(query)
    katago_process.expect(r"\n", timeout=30)
    katago_process.expect(r"({.*})\r\n", timeout=30)
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


def stats(initial_stones, katago_process, visits=2**10):
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


def annotate_sgf(filename):
    assert filename.endswith(".sgf")
    with open(filename, "rb") as f:
        game = sgf.Sgf_game.from_bytes(f.read())
    root = game.get_root()
    board = boards.Board(root.get_size())
    board.apply_setup(*root.get_setup_stones())
    process = get_process()
    mean, temp = stats(board.list_occupied_points(), process)
    root.set("C", f"Board value: {mean:.2f}\nTemp: {temp:.2f}")
    for child in root:
        annotate_subtree(child, board.copy(), mean, temp, process)
    outf = filename[:-4] + "__miai_values.sgf"
    open(outf, "wb").write(game.serialise())


def annotate_subtree(node, board, prev_mean, prev_temp, process):
    color, coords = node.get_move()
    if color is not None and type(coords) is tuple:
        board.play(*coords, color)
    print(ascii_boards.render_board(board))
    stones = sgf_to_kata(board.list_occupied_points())
    mean, temp = stats(stones, process)
    move_value = mean - prev_mean
    if color == 'w':
        move_value *= -1
    # Want territory score, but used area scoring to avoid tracking captures
    move_value -= 1
    temp_increment = temp - prev_temp
    text = f"Move value: {move_value:.2f}\n\nBoard: {mean:.2f}\nTemp: {temp:.2f} ({temp_increment:+.2f})"
    print(text.replace("\n", "    "))
    node.set("C", text)
    if len(stones) < 60:
        for child in node:
            annotate_subtree(child, board.copy(), mean, temp, process)


if __name__ == "__main__":
    annotate_sgf(sys.argv[1])
