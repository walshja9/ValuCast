"""Validate the ValuCast plate-discipline artifact schema.

Checks the committed artifact's keys, per-level splits, the zone_estimated flag,
sample-size fields, the min-sample floor, and (when the zone group shipped) the
calibration coefficients + quality. Fail-soft on a MISSING artifact: the layer is
allowed to not exist yet (the reader/card fail soft too), so an absent artifact is
OK (exit 0). A PRESENT but malformed artifact fails (exit 1).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_pitch_discipline.json"

EXACT = {"swing_pct", "whiff_pct", "swstr_pct"}
ESTIMATED = {"chase_pct", "z_swing_pct", "z_contact_pct", "zone_pct"}


def validate_file(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str], bool]:
    """Returns (payload, problems, present). An absent artifact is not a failure."""
    if not path.exists():
        return None, [], False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"], True

    problems: list[str] = []
    if payload.get("artifact") != "valucast_pitch_discipline":
        problems.append("artifact must be valucast_pitch_discipline")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if not payload.get("as_of"):
        problems.append("as_of is required")

    policy = payload.get("source_policy") or {}
    if policy.get("observe_only") is not True:
        problems.append("source_policy.observe_only must be true")
    for field in ("feeds_value", "feeds_rank", "exit_velocity"):
        if policy.get(field) is not False:
            problems.append(f"source_policy.{field} must be false")

    cohorts = payload.get("cohorts") or {}
    floor = cohorts.get("min_pitches")
    if not isinstance(floor, int) or floor <= 0:
        problems.append("cohorts.min_pitches must be a positive int")
    if not isinstance(cohorts.get("cohort_sizes"), dict):
        problems.append("cohorts.cohort_sizes must be a dict")

    zone_shipped = cohorts.get("zone_metrics_shipped")
    calib = cohorts.get("calibration") or {}
    if zone_shipped:
        for coef in ("a", "b", "c", "d"):
            if not isinstance(calib.get(coef), (int, float)):
                problems.append(f"calibration.{coef} required when zone metrics shipped")
        agree = calib.get("held_out_agreement_pct")
        floor_pct = calib.get("agreement_floor_pct")
        if isinstance(agree, (int, float)) and isinstance(floor_pct, (int, float)):
            if agree < floor_pct:
                problems.append(
                    f"zone metrics shipped but agreement {agree} < floor {floor_pct}"
                )

    players = payload.get("players")
    if not isinstance(players, dict):
        problems.append("players must be a dict keyed by mlbam id")
        players = {}

    for pid, levels in players.items():
        if not isinstance(levels, dict):
            problems.append(f"players[{pid}] must be a dict of level buckets")
            continue
        for level, bucket in levels.items():
            if not isinstance(bucket, dict):
                problems.append(f"players[{pid}][{level}] must be a dict")
                continue
            if not isinstance(bucket.get("pitches"), int):
                problems.append(f"players[{pid}][{level}].pitches must be an int")
            if not isinstance(bucket.get("zone_estimated"), bool):
                problems.append(f"players[{pid}][{level}].zone_estimated must be bool")
            rates = bucket.get("rates")
            if not isinstance(rates, dict):
                problems.append(f"players[{pid}][{level}].rates must be a dict")
                rates = {}
            for m in EXACT | ESTIMATED:
                if m in rates and rates[m] is not None and not isinstance(rates[m], (int, float)):
                    problems.append(f"players[{pid}][{level}].rates.{m} must be numeric or null")
            # Min-sample gate: a sub-floor bucket must carry NO non-empty percentiles.
            pcts = bucket.get("percentiles")
            if isinstance(floor, int):
                if isinstance(bucket.get("pitches"), int) and bucket["pitches"] < floor:
                    if pcts:
                        problems.append(
                            f"players[{pid}][{level}] below floor but has percentiles"
                        )
    return payload, problems, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()

    payload, problems, present = validate_file(args.path)
    if not present:
        print(f"plate-discipline artifact absent ({args.path}); OK (fail-soft)")
        return 0
    if problems:
        print(f"PLATE-DISCIPLINE VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    qualifying = sum(
        1
        for levels in (payload.get("players") or {}).values()
        for b in levels.values()
        if b.get("qualifies")
    )
    print(
        f"OK plate-discipline: players={len(payload.get('players') or {})} "
        f"qualifying={qualifying} "
        f"zone_shipped={(payload.get('cohorts') or {}).get('zone_metrics_shipped')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
