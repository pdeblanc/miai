import datetime
import os
import random
from typing import Sequence

from sgfmill import sgf

from katago_interface import KataGoEngine

ALPHABET = 'ABCDEFGHJKLMNOPQRST'
STONES = '⚫⚪'
HANZI_NUMBERS = [
    "一",
    "二",
    "三",
    "四",
    "五",
    "六",
    "七",
    "八",
    "九",
    "十",
    "十一",
    "十二",
    "十三",
    "十四",
    "十五",
    "十六",
    "十七",
    "十八",
    "十九"
]


def sgf_to_kata(stones):
    return [
        [s[0].upper(), ALPHABET[s[1][0]] + str(s[1][1] + 1)]
        for s in stones
    ]


def get_policy(engine, history) -> Sequence[float]:
    query = {
        "moves": history,
        "komi": 7,
        "rules": "tromp-taylor",
        "boardXSize": 19,
        "boardYSize": 19,
        "analyzeTurns": [len(history)],
        "maxVisits": 1,
        "includePolicy": True,
    }
    response_data = engine.query_synchronous(query)
    policy = response_data['policy']
    return policy


def get_ai_move(policy, history) -> str:
    turn = len(history) % 2
    r = random.random() * sum([x for x in policy if x >= 0])
    for i in range(len(policy)):
        if r <= policy[i]:
            break
        r -= max(0, policy[i])
    x = i % 19
    y = i // 19
    color = "bw"[turn]
    # print(STONES[turn] + " " + HANZI_NUMBERS[x] + "之" + HANZI_NUMBERS[y])
    return [color, ALPHABET[x] + str(19 - y)]


def write_sgf(filename, history, now):
    game = sgf.Sgf_game(19)
    game.set_date(now.date())
    root_node = game.get_root()
    root_node.set("PB", "KataGo Policy")
    root_node.set("PW", "KataGo Policy")
    root_node.set("KM", 7)
    for color, coords in history:
        node = game.extend_main_sequence()
        x = ALPHABET.index(coords[0])
        y = int(coords[1:]) - 1
        node.set_move(color, (y, x))
    with open(filename, "wb") as f:
        f.write(game.serialise())


def problem_search(engine, weak_engine, num_moves: int):
    now = datetime.datetime.now()
    now_string = now.strftime("%Y-%m-%d.%H.%M.%S")
    os.makedirs("out_sgf", exist_ok=True)
    history = []
    while len(history) < num_moves:
        policy = get_policy(engine, history)
        weak_policy = get_policy(weak_engine, history)
        best_move = max(range(len(policy)), key=policy.__getitem__)
        policy_p = policy[best_move]
        weak_policy_p = weak_policy[best_move]
        if policy_p > .9:
            print(policy_p, weak_policy_p)
            difficulty = round((1 - weak_policy_p) * 100)
            filename = f"gen_problems/{difficulty:03d}-{now_string}.sgf"
            print(f"Saving as {filename}")
            write_sgf(filename, history, now)
        history.append(get_ai_move(policy, history))


if __name__ == "__main__":
    engine = KataGoEngine()
    weak_engine = KataGoEngine(
        model="/Users/peter/repos/katrain/katrain/models/"
        "g170e-b15c192-s1672170752-d466197061.bin.gz"
    )
    for i in range(20):
        problem_search(engine, weak_engine, 120)
