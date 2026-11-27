"""Validate the ValuCast AAA-Statcast feature artifact schema.

Mirrors scripts/validate_pitch_discipline.py's posture: fail-soft on a MISSING
artifact (the layer is allowed to not exist until the first backfill lands; the
reader/card fail soft too, so absent == OK, exit 0). A PRESENT but malformed
artifact fails (exit 1).

Checks the envelope (artifact/schema_version/generated_at/as_of/source), the
observe-only source policy (measured=True, feeds_value/feeds_rank=False), the sample
gates block, the per-player structure of the pitchers/hitters tables, and a bounded
self-arming staleness gate on as_of (see the transition comment below).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_aaa_statcast_features.json"

# --- Bounded staleness gate (self-arming; F4 remediation 2026-07-30) --------
# The refresh/build pair deliberately keeps the last artifact on transient
# failures (cold cache, missing readiness marker, budget exceeded, tiny-refresh
# guard) and exits 0, so without a bound the artifact can stay stale
# indefinitely with every gate green — it served as_of 2026-07-14 for 16 days
# before this gate landed. Mirrors validate_pitch_discipline._staleness_problem.
#
# SELF-ARMING TRANSITION: the committed artifact predates the cache-persistence
# fix and cannot be rebuilt locally (the pitch cache is uncommitted and needs a
# bulk network backfill), so a tight bound applied unconditionally would turn CI
# red TODAY. Instead build_aaa_statcast_features.py stamps
# "freshness_regime": "cache_bootstrap_v1" into every artifact built after the
# fix, and this validator:
#   * applies the TIGHT bound (default 3 days; VALUCAST_AAA_STATCAST_MAX_AGE_DAYS
#     env or --max-age-days override) ONLY when that stamp is present — the gate
#     arms itself at the first fresh rebuild and stays armed from then on;
#   * applies an unconditional HARD bound of 30 days regardless of the stamp, so
#     a pipeline that never recovers (bootstrap never runs, stamp never appears)
#     still fails closed instead of serving arbitrarily old data forever.
DEFAULT_MAX_AGE_DAYS = 3
HARD_MAX_AGE_DAYS = 30
FRESHNESS_REGIME = "cache_bootstrap_v1"


def _staleness_problem(payload: dict, today: str, max_age_days: int) -> str | None:
    as_of = str(payload.get("as_of") or "")[:10]
    if not as_of:
        return None  # "as_of is required" already reported by validate_file
    try:
        age = (date.fromisoformat(today) - date.fromisoformat(as_of)).days
    except ValueError:
        return f"as_of={as_of!r} is not an ISO date"
    if age < 0:
        return f"as_of={as_of} is in the future (today {today})"
    armed = payload.get("freshness_regime") == FRESHNESS_REGIME
    if armed and age > max_age_days:
        return (
            f"as_of={as_of} is {age} days old (today {today}, allowed "
            f"{max_age_days}) -- the keep-stale refresh/build paths have been "
            "masking a broken refresh; check the daily AAA-Statcast cache "
            "restore/save steps, or dispatch the aaa-statcast-bootstrap "
            "workflow (scripts/refresh_aaa_statcast.py --backfill) and rerun "
            "scripts/build_aaa_statcast_features.py"
        )
    if age > HARD_MAX_AGE_DAYS:
        return (
            f"as_of={as_of} is {age} days old (today {today}, hard limit "
            f"{HARD_MAX_AGE_DAYS} even for legacy pre-cache-bootstrap "
            "artifacts) -- the pipeline never recovered; dispatch the "
            "aaa-statcast-bootstrap workflow (scripts/refresh_aaa_statcast.py "
            "--backfill) and rerun scripts/build_aaa_statcast_features.py"
        )
    return None

_PITCHER_OUTCOMES = {"whiff_pct", "csw_pct", "chase_pct", "zone_pct", "gb_pct"}
_PITCH_SHAPE_KEYS = {"velo", "ivb", "hb", "spin", "ext"}
_HITTER_KEYS = {
    "avg_ev", "max_ev", "hardhit_pct", "avg_la", "whiff_pct", "chase_pct", "gb_pct",
}


def _num_ok(value) -> bool:
    return value is None or isinstance(value, (int, float))


def validate_file(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str], bool]:
    """Returns (payload, problems, present). An absent artifact is not a failure."""
    if not path.exists():
        return None, [], False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"], True

    problems: list[str] = []
    if payload.get("artifact") != "valucast_aaa_statcast_features":
        problems.append("artifact must be valucast_aaa_statcast_features")
    if not isinstance(payload.get("schema_version"), int):
        problems.append("schema_version must be an int")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if not payload.get("as_of"):
        problems.append("as_of is required")
    if not payload.get("source"):
        problems.append("source is required")

    policy = payload.get("source_policy") or {}
    if policy.get("observe_only") is not True:
        problems.append("source_policy.observe_only must be true")
    if policy.get("measured") is not True:
        problems.append("source_policy.measured must be true")
    for field in ("feeds_value", "feeds_rank"):
        if policy.get(field) is not False:
            problems.append(f"source_policy.{field} must be false")
    if policy.get("level") != "AAA":
        problems.append("source_policy.level must be AAA")

    if not isinstance(payload.get("gates"), dict):
        problems.append("gates must be a dict")

    pitchers = payload.get("pitchers")
    if not isinstance(pitchers, dict):
        problems.append("pitchers must be a dict keyed by mlbam id")
        pitchers = {}
    hitters = payload.get("hitters")
    if not isinstance(hitters, dict):
        problems.append("hitters must be a dict keyed by mlbam id")
        hitters = {}

    for pid, record in pitchers.items():
        if not isinstance(record, dict):
            problems.append(f"pitchers[{pid}] must be a dict")
            continue
        if not isinstance(record.get("n_pitches"), int):
            problems.append(f"pitchers[{pid}].n_pitches must be an int")
        overall = record.get("overall")
        if overall is not None:
            if not isinstance(overall, dict):
                problems.append(f"pitchers[{pid}].overall must be a dict")
            else:
                for k, v in overall.items():
                    if k in _PITCHER_OUTCOMES and not _num_ok(v):
                        problems.append(f"pitchers[{pid}].overall.{k} must be numeric")
        types = record.get("pitch_types")
        if types is not None:
            if not isinstance(types, dict):
                problems.append(f"pitchers[{pid}].pitch_types must be a dict")
            else:
                for pt, row in types.items():
                    if not isinstance(row, dict):
                        problems.append(f"pitchers[{pid}].pitch_types[{pt}] must be a dict")
                        continue
                    if not isinstance(row.get("n"), int):
                        problems.append(f"pitchers[{pid}].pitch_types[{pt}].n must be an int")
                    for k in _PITCH_SHAPE_KEYS:
                        if not _num_ok(row.get(k)):
                            problems.append(
                                f"pitchers[{pid}].pitch_types[{pt}].{k} must be numeric or null"
                            )

    for bid, record in hitters.items():
        if not isinstance(record, dict):
            problems.append(f"hitters[{bid}] must be a dict")
            continue
        if not isinstance(record.get("n_pitches"), int):
            problems.append(f"hitters[{bid}].n_pitches must be an int")
        # ev_n (EV-tracked BBE count) is optional: legacy artifacts built before
        # 2026-07-30 lack it. When present it must be an int.
        if "ev_n" in record and not isinstance(record.get("ev_n"), int):
            problems.append(f"hitters[{bid}].ev_n must be an int")
        for k in _HITTER_KEYS:
            if k in record and not _num_ok(record.get(k)):
                problems.append(f"hitters[{bid}].{k} must be numeric or null")

    return payload, problems, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=int(
            os.environ.get(
                "VALUCAST_AAA_STATCAST_MAX_AGE_DAYS", str(DEFAULT_MAX_AGE_DAYS)
            )
        ),
    )
    args = parser.parse_args()

    payload, problems, present = validate_file(args.path)
    if payload is not None:
        stale = _staleness_problem(payload, args.date, args.max_age_days)
        if stale:
            problems.append(stale)
    if not present:
        print(f"AAA-statcast artifact absent ({args.path}); OK (fail-soft)")
        return 0
    if problems:
        print(f"AAA-STATCAST VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(
        f"OK AAA-statcast: pitchers={len(payload.get('pitchers') or {})} "
        f"hitters={len(payload.get('hitters') or {})}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
