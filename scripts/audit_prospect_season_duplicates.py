"""Count duplicate player-season rows in the prospect MLB-season cache. Counts only: this repo's logs are public."""

import json
from collections import Counter

from prospects.raw_input_builder import MLB_SEASONS_PATH

seasons = json.load(open(MLB_SEASONS_PATH, encoding="utf-8"))
players = players_with_duplicates = duplicate_seasons = 0
for key, rows in seasons.items():
    if not key.endswith(("_hitter", "_pitcher")) or not isinstance(rows, list):
        continue
    counts = Counter(row.get("year") for row in rows)
    repeated = sum(1 for count in counts.values() if count > 1)
    players += 1
    players_with_duplicates += bool(repeated)
    duplicate_seasons += repeated
print("cache players", players, "with a repeated season", players_with_duplicates, "repeated seasons", duplicate_seasons)
