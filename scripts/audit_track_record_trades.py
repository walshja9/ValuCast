"""Measure the traded-season double count in track-record inputs. Aggregates and already-public floors only: this repo's logs are public."""

import copy
import json
import statistics
from collections import Counter

import mlb.track_record as tr


def load(path):
    return json.load(open(path, encoding="utf-8"))


projections = load("data/projections/current.json")
cache = load("data/mlb/mlb_track_record_cache.json")
stored = load("data/models/valucast_mlb_track_record.json")


def build():
    return tr.build_mlb_track_record(
        projections,
        generated_at=stored["generated_at"],
        season=stored["season"],
        cache=copy.deepcopy(cache),
        refresh_missing=False,
        debut_fetcher=lambda ids: {},
    )["profiles"]


def keyed(profiles):
    return {(str(p["mlbam_id"]), p["role"]): p for p in profiles}


def find(row, key):
    if key in row:
        return row[key]
    for value in row.values():
        if isinstance(value, dict):
            found = find(value, key)
            if found is not None:
                return found
    return None


stored_rows = keyed(stored["profiles"])
before = keyed(build())
print("profiles stored", len(stored_rows), "rebuilt", len(before))
print("rebuilt floor differs from stored", sum(
    1 for k, p in before.items()
    if k in stored_rows and p["track_record_floor_score"] != stored_rows[k]["track_record_floor_score"]
))

original = tr._stats_bucket


def one_row_per_season(raw, group, type_name):
    splits = original(raw, group, type_name)
    if type_name != "yearByYear":
        return splits
    counts = Counter(s.get("season") for s in splits)
    return [s for s in splits if counts[s.get("season")] == 1 or s.get("team") is None]


tr._stats_bucket = one_row_per_season
after = keyed(build())

changed = [k for k in before if before[k]["volume"]["prior_mlb"] != after[k]["volume"]["prior_mlb"]]
ratios = [before[k]["volume"]["prior_mlb"] / after[k]["volume"]["prior_mlb"] for k in changed if after[k]["volume"]["prior_mlb"]]
deltas = [before[k]["track_record_floor_score"] - after[k]["track_record_floor_score"] for k in before]
moved = [d for d in deltas if abs(d) >= 0.01]
print("profiles with inflated prior volume", len(changed), "of", len(before))
if ratios:
    print("inflation ratio median", round(statistics.median(ratios), 3), "max", round(max(ratios), 3))
print("floor moved", len(moved), "by 1+", sum(abs(d) >= 1 for d in moved), "by 3+", sum(abs(d) >= 3 for d in moved),
      "up", sum(d > 0 for d in moved), "max abs", round(max(map(abs, moved), default=0), 2))
print("experience band changes", sum(before[k]["experience_band"] != after[k]["experience_band"] for k in before))
print("certainty crosses 40", sum(
    (before[k]["track_record_certainty"] >= 40) != (after[k]["track_record_certainty"] >= 40) for k in before
))

floored = [r for r in load("data/models/valucast_mlb_dynasty_layer.json")["players"] if find(r, "track_record_floor_applied")]
print("floor-set dynasty rows", len(floored))
for row in sorted(floored, key=lambda r: r["rank"]):
    key = (str(row["mlbam_id"]), row["role"])
    if key not in before:
        continue
    old, new = before[key]["track_record_floor_score"], after[key]["track_record_floor_score"]
    if abs(old - new) >= 0.01:
        print("floor", row["name"], "rank", row["rank"], "floor", old, "->", new)
