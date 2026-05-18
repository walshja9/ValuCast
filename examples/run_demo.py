from pathlib import Path

from league_values.config_loader import load_league_config
from league_values.engine import value_players


ROOT = Path(__file__).resolve().parent

PLAYERS = [
    {
        "id": "h1",
        "name": "Power Bat",
        "pool": "hitter",
        "positions": ["1B"],
        "stats": {
            "R": 86,
            "HR": 42,
            "RBI": 112,
            "SB": 4,
            "H": 158,
            "AB": 565,
            "1B": 86,
            "2B": 26,
            "3B": 4,
            "BB": 68,
            "CS": 2
        }
    },
    {
        "id": "h2",
        "name": "Speed Bat",
        "pool": "hitter",
        "positions": ["OF"],
        "stats": {
            "R": 94,
            "HR": 14,
            "RBI": 61,
            "SB": 46,
            "H": 166,
            "AB": 592,
            "1B": 122,
            "2B": 24,
            "3B": 6,
            "BB": 52,
            "CS": 8
        }
    },
    {
        "id": "p1",
        "name": "Workhorse Ace",
        "pool": "pitcher",
        "positions": ["SP"],
        "stats": {
            "W": 15,
            "SV": 0,
            "K": 212,
            "ER": 62,
            "IP": 188,
            "BB": 42,
            "H_ALLOWED": 151
        }
    },
    {
        "id": "p2",
        "name": "Lockdown Closer",
        "pool": "pitcher",
        "positions": ["RP"],
        "stats": {
            "W": 4,
            "SV": 36,
            "K": 89,
            "ER": 19,
            "IP": 67,
            "BB": 18,
            "H_ALLOWED": 48
        }
    }
]


def print_results(config_path: str) -> None:
    league = load_league_config(ROOT / config_path)
    print(f"\n{league.name}")
    for result in value_players(PLAYERS, league):
        print(f"{result.name:16} {result.total_value:8.2f}")


if __name__ == "__main__":
    print_results("categories_5x5.json")
    print_results("points_league.json")
