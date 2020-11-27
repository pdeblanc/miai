import datetime
import os
import random

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


def get_move(turn: int) -> str:
    while True:
        user_input = input(STONES[turn] + " ")
        parts = user_input.split("-")
        if len(parts) == 2:
            try:
                x = int(parts[0])
                y = int(parts[1])
                return ["bw"[turn], ALPHABET[x - 1] + str(20 - y)]
            except ValueError:
                pass
        print("Invalid input. Valid input is of the form `17-4`")


def get_ai_move(history) -> str:
    turn = len(history) % 2
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
    r = random.random() * sum([x for x in policy if x >= 0])
    for i in range(len(policy)):
        if r <= policy[i]:
            break
        r -= max(0, policy[i])
    x = i % 19
    y = i // 19
    color = "bw"[turn]
    print(STONES[turn] + " " + HANZI_NUMBERS[x] + "之" + HANZI_NUMBERS[y])
    return [color, ALPHABET[x] + str(19 - y)]


def play_opening(engine, num_moves: int):
    player = random.randint(0, 1)
    history = []
    while len(history) < num_moves:
        turn = len(history) % 2
        if turn == player:
            history.append(get_move(turn))
        else:
            history.append(get_ai_move(history))
    now = datetime.datetime.now()
    os.makedirs("out_sgf", exist_ok=True)
    filename = os.path.join(
        "out_sgf", now.strftime("%Y-%m-%d.%H.%M.%S") + ".sgf"
    )
    print(f"Saving as {filename}")
    game = sgf.Sgf_game(19)
    game.set_date(now.date())
    root_node = game.get_root()
    root_node.set("PB", "user" if player == 0 else "KataGo Policy")
    root_node.set("PW", "user" if player == 1 else "KataGo Policy")
    root_node.set("KM", 7)
    for color, coords in history:
        node = game.extend_main_sequence()
        x = ALPHABET.index(coords[0])
        y = int(coords[1:]) - 1
        node.set_move(color, (y, x))
    with open(filename, "wb") as f:
        f.write(game.serialise())


if __name__ == "__main__":
    engine = KataGoEngine()
    # Send a synchronous query to make sure engine is ready
    engine.query_synchronous({
        "moves": [],
        "komi": 7,
        "rules": "tromp-taylor",
        "boardXSize": 19,
        "boardYSize": 19,
        "analyzeTurns": [0],
        "maxVisits": 1,
    })
    play_opening(engine, 20)
