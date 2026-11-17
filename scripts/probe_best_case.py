"""THROWAWAY probe: does the rank at the most favourable age bound a true rank?

For sampled players, rebuild the real layer with that one player's age set to
each age in turn and record the rank. Counts go to stdout; names only to the CSV.
PROBE_MODE=inseason patches the target season back to the context season first.
"""
import csv
import json
import os
import time
from pathlib import Path

import mlb.dynasty as d
from scraper import season as season_config
from web.projection_store import ProjectionStore

MODE = os.environ.get("PROBE_MODE", "preseason")
if MODE == "inseason":
    season_config.TARGET_SEASON = season_config.CONTEXT_SEASON
AGES = list(range(17, 44))
SAMPLE_STEP = int(os.environ.get("PROBE_SAMPLE_STEP", "20"))
SAMPLE_TOP = int(os.environ.get("PROBE_SAMPLE_TOP", "600"))
FULL_PASS = os.environ.get("PROBE_FULL_PASS", "1") == "1" and MODE == "preseason"
CUTOFFS = (100, 200, 300)

out_dir = Path(os.environ["AGE_PROBE_OUT"])
out_dir.mkdir(parents=True, exist_ok=True)

store = ProjectionStore(d.PROJECTION_PATH)
players = store.get_all()
identities = d.load_identity_store(d.IDENTITY_DATA_DIR)
track = json.loads(d.TRACK_RECORD_PATH.read_text(encoding="utf-8")) if d.TRACK_RECORD_PATH.exists() else None
avail = json.loads(d.MLB_AVAILABILITY_PATH.read_text(encoding="utf-8")) if d.MLB_AVAILABILITY_PATH.exists() else None
generated_at = d._generated_at(store)
season = season_config.TARGET_SEASON if season_config.is_preseason() else d._season_from_generated_at(generated_at)


def build(identity_map):
    return d.build_mlb_dynasty_layer(
        players, generated_at, identities=identity_map, track_record=track, availability=avail
    )["players"]


def key(row):
    return (str(row.get("mlbam_id")), row.get("role"))


def with_age(mlbam_id, age):
    changed = dict(identities)
    record = dict(changed.get(str(mlbam_id)) or {})
    record["birth_date"] = f"{season - age}-01-01"
    changed[str(mlbam_id)] = record
    return changed


def rank_at(row, age):
    hit = next((r for r in build(with_age(row["mlbam_id"], age)) if key(r) == key(row)), None)
    return (hit["rank"], hit.get("age")) if hit else (None, None)


started = time.time()
base = sorted(build(identities), key=lambda r: r["rank"])
print(
    f"mode {MODE} preseason {season_config.is_preseason()} season {season} "
    f"layer_rows {len(base)} seconds_per_build {time.time() - started:.1f}"
)

sample = [r for r in base[:SAMPLE_TOP:SAMPLE_STEP] if r.get("age") is not None]
rows_out = []
reproduced = non_monotone = youngest_not_best = bound_violations = 0
worst_gap = 0
for row in sample:
    usable = {}
    for age in AGES:
        rank, seen_age = rank_at(row, age)
        if rank is not None and seen_age == age:
            usable[age] = rank
    if not usable:
        continue
    true_age = row["age"]
    reproduced += usable.get(true_age) == row["rank"]
    ordered = [usable[a] for a in sorted(usable)]
    monotone = all(later >= earlier for earlier, later in zip(ordered, ordered[1:]))
    non_monotone += not monotone
    best = min(usable.values())
    youngest = usable[min(usable)]
    youngest_not_best += youngest != best
    worst_gap = max(worst_gap, youngest - best)
    bound_violations += best > row["rank"]
    rows_out.append({
        "name": row.get("name"), "role": row.get("role"), "true_age": true_age, "true_rank": row["rank"],
        "rank_at_true_age": usable.get(true_age), "best_rank": best,
        "best_at_age": min(a for a, r in usable.items() if r == best),
        "rank_at_youngest": youngest, "monotone": monotone,
        "ranks_by_age": " ".join(f"{a}:{usable[a]}" for a in sorted(usable)),
    })
print(
    f"sampled {len(rows_out)} ages {AGES[0]}-{AGES[-1]} "
    f"true_rank_reproduced {reproduced} rank_not_monotone_in_age {non_monotone} "
    f"youngest_is_not_best {youngest_not_best} largest_gap_youngest_vs_best {worst_gap} "
    f"best_case_worse_than_true_rank {bound_violations}"
)
with (out_dir / f"best_case_sample_{MODE}.csv").open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows_out[0].keys()) if rows_out else ["name"])
    writer.writeheader()
    writer.writerows(rows_out)

if FULL_PASS:
    youngest_age = AGES[0]
    flagged = {c: 0 for c in CUTOFFS}
    true_inside = {c: 0 for c in CUTOFFS}
    violations = 0
    tested = 0
    for row in base:
        if time.time() - started > 3000:
            break
        rank, seen_age = rank_at(row, youngest_age)
        if rank is None or seen_age != youngest_age:
            continue
        tested += 1
        violations += rank > row["rank"]
        for cutoff in CUTOFFS:
            flagged[cutoff] += rank <= cutoff
            true_inside[cutoff] += row["rank"] <= cutoff
    print(f"full_pass tested {tested} of {len(base)} rank_at_youngest_worse_than_true_rank {violations}")
    for cutoff in CUTOFFS:
        print(f"cutoff {cutoff}: truly_inside {true_inside[cutoff]} would_be_flagged_if_ageless {flagged[cutoff]}")
