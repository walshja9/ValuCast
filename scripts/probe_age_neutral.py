"""THROWAWAY probe: where would each top player rank if their birth date were missing?

Rebuilds the real layer once per player with that one identity removed.
Counts go to stdout (public log). Names go only to the CSV report.
"""
import csv
import json
import os
import time
from pathlib import Path

import mlb.dynasty as d
from web.projection_store import ProjectionStore

TOP = int(os.environ.get("AGE_NEUTRAL_TOP", "450"))
BUDGET_SECONDS = int(os.environ.get("AGE_NEUTRAL_BUDGET", "1500"))
CUTOFFS = (100, 200, 300)

out_dir = Path(os.environ["AGE_PROBE_OUT"])
out_dir.mkdir(parents=True, exist_ok=True)

store = ProjectionStore(d.PROJECTION_PATH)
players = store.get_all()
identities = d.load_identity_store(d.IDENTITY_DATA_DIR)
track = json.loads(d.TRACK_RECORD_PATH.read_text(encoding="utf-8")) if d.TRACK_RECORD_PATH.exists() else None
avail = json.loads(d.MLB_AVAILABILITY_PATH.read_text(encoding="utf-8")) if d.MLB_AVAILABILITY_PATH.exists() else None
generated_at = d._generated_at(store)


def build(identity_map):
    return d.build_mlb_dynasty_layer(
        players, generated_at, identities=identity_map, track_record=track, availability=avail
    )["players"]


def key(row):
    return (str(row.get("mlbam_id")), row.get("role"))


started = time.time()
base = build(identities)
one_build = time.time() - started
print(f"layer_rows {len(base)} seconds_per_build {one_build:.1f} top {TOP} budget_seconds {BUDGET_SECONDS}")

results = []
for row in sorted(base, key=lambda r: r["rank"])[:TOP]:
    if time.time() - started > BUDGET_SECONDS:
        break
    reduced = dict(identities)
    reduced.pop(str(row.get("mlbam_id")), None)
    neutral = next((r for r in build(reduced) if key(r) == key(row)), None)
    results.append({
        "name": row.get("name"), "role": row.get("role"), "age": row.get("age"),
        "rank": row["rank"], "value": row.get("value"),
        "neutral_rank": neutral["rank"] if neutral else None,
        "neutral_value": neutral.get("value") if neutral else None,
        "neutral_age": neutral.get("age") if neutral else None,
    })

done = [r for r in results if r["neutral_rank"] is not None]
print(f"players_tested {len(results)} matched {len(done)} still_aged_after_removal {sum(1 for r in done if r['neutral_age'] is not None)}")
for cutoff in CUTOFFS:
    inside = [r for r in done if r["rank"] <= cutoff]
    fell_out = [r for r in inside if r["neutral_rank"] > cutoff]
    came_in = [r for r in done if r["rank"] > cutoff and r["neutral_rank"] <= cutoff]
    worst = max((r["neutral_rank"] for r in fell_out), default=None)
    print(
        f"cutoff {cutoff}: tested_inside {len(inside)} fall_outside_when_ageless {len(fell_out)} "
        f"deepest_ageless_rank {worst} enter_when_ageless {len(came_in)}"
    )
for lo, hi in ((0, 22), (23, 25), (26, 28), (29, 31), (32, 34), (35, 99)):
    band = [r for r in done if r["age"] is not None and lo <= r["age"] <= hi]
    if band:
        moves = sorted(r["neutral_rank"] - r["rank"] for r in band)
        print(f"age {lo}-{hi}: n {len(band)} median_rank_change_when_ageless {moves[len(moves) // 2]} min {moves[0]} max {moves[-1]}")

with (out_dir / "age_neutral.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(results[0].keys()) if results else ["name"])
    writer.writeheader()
    writer.writerows(results)
