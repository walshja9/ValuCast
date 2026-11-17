"""THROWAWAY probe: the preseason age path under the flipped target season.

Counts go to stdout (public log). Player names go only to the report file.
"""
import json
import os
from collections import Counter
from pathlib import Path

import mlb.dynasty as d
from league_values.playing_time import filter_by_playing_time
from scraper import season as season_config
from web.projection_store import ProjectionStore

out_dir = Path(os.environ["AGE_PROBE_OUT"])
out_dir.mkdir(parents=True, exist_ok=True)
lines: list[str] = []


def say(text: str, public: bool = True) -> None:
    lines.append(text)
    if public:
        print(text)


def blank(value) -> bool:
    return value in (None, "")


store = ProjectionStore(d.PROJECTION_PATH)
players = store.get_all()
identities = d.load_identity_store(d.IDENTITY_DATA_DIR)
target = season_config.TARGET_SEASON

say(f"target_season {target} context_season {season_config.CONTEXT_SEASON} preseason {season_config.is_preseason()}")
say(
    f"projection_rows {len(players)} "
    f"with_row_age {sum(1 for p in players if p.metadata.get('age') is not None)} "
    f"without_mlbam {sum(1 for p in players if blank(p.metadata.get('mlbam_id')))}"
)

# Same eligibility floors and the same age attachment the dynasty layer uses.
eligible = filter_by_playing_time(players, hitter_pa=d.MIN_HITTER_PA, sp_ip=d.MIN_SP_IP, rp_ip=d.MIN_RP_IP)
row_age = {p.id: p.metadata.get("age") for p in eligible}
aged = d._attach_ages(eligible, identities, target)
say(f"eligible_rows {len(eligible)} by_pool {dict(Counter(p.pool.value for p in eligible))}")
say(f"eligible_age_source {dict(Counter(p.metadata['age_source'] for p in aged))}")

missing = [p for p in aged if p.metadata["age"] is None]
with_row_age = with_record = with_birth_text = 0
say("", public=False)
say("## Eligible players with no usable age", public=False)
for p in sorted(missing, key=lambda item: item.name):
    identity = identities.get(str(p.metadata.get("mlbam_id"))) or {}
    has_row_age = row_age.get(p.id) is not None
    with_row_age += has_row_age
    with_record += bool(identity)
    with_birth_text += not blank(identity.get("birth_date"))
    say(
        f"- {p.name} | {p.pool.value} | {p.metadata['age_source']} | row_age {has_row_age} | "
        f"identity_record {bool(identity)} | birth_date_text {not blank(identity.get('birth_date'))}",
        public=False,
    )
say(
    f"eligible_without_age {len(missing)} with_row_age {with_row_age} "
    f"with_identity_record {with_record} with_unusable_birth_date_text {with_birth_text}"
)

# The real layer on this feed. Track record and availability are the committed
# (pre-flip) artifacts, so ranks here are approximate; age coverage is exact.
track = json.loads(d.TRACK_RECORD_PATH.read_text(encoding="utf-8")) if d.TRACK_RECORD_PATH.exists() else None
avail = json.loads(d.MLB_AVAILABILITY_PATH.read_text(encoding="utf-8")) if d.MLB_AVAILABILITY_PATH.exists() else None
payload = d.build_mlb_dynasty_layer(
    players, d._generated_at(store), identities=identities, track_record=track, availability=avail
)
board = payload["players"]
validation = payload["validation"]
say(
    f"layer_rows {len(board)} age_coverage_count {validation.get('age_coverage_count')} "
    f"age_coverage_rate {validation.get('age_coverage_rate')} threshold {validation.get('age_coverage_threshold')}"
)
say(f"layer_age_source {dict(Counter((r.get('components') or {}).get('age_source') for r in board))}")
say(f"layer_age_blockers {sum(1 for b in validation.get('blockers') or [] if 'age' in str(b).lower())}")
without = sorted((r for r in board if r.get("age") is None), key=lambda r: r.get("rank") or 10**9)
say(
    f"layer_rows_without_age {len(without)} "
    f"top_100 {sum(1 for r in without if (r.get('rank') or 10**9) <= 100)} "
    f"top_300 {sum(1 for r in without if (r.get('rank') or 10**9) <= 300)} "
    f"top_500 {sum(1 for r in without if (r.get('rank') or 10**9) <= 500)}"
)
ages = [r["age"] for r in board if r.get("age") is not None]
if ages:
    say(f"layer_age_range {min(ages)}-{max(ages)}")
say("", public=False)
say("## Layer rows with no age (rank is approximate, MLB-only)", public=False)
for r in without:
    say(
        f"- rank {r.get('rank')} | {r.get('name')} | {r.get('role')} | value {r.get('value')} | "
        f"{(r.get('components') or {}).get('age_source')}",
        public=False,
    )

(out_dir / "age_path.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
