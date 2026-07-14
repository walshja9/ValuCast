"""Validate the ValuCast AAA-Statcast feature artifact schema.

Mirrors scripts/validate_pitch_discipline.py's posture: fail-soft on a MISSING
artifact (the layer is allowed to not exist until the first backfill lands; the
reader/card fail soft too, so absent == OK, exit 0). A PRESENT but malformed
artifact fails (exit 1).

Checks the envelope (artifact/schema_version/generated_at/as_of/source), the
observe-only source policy (measured=True, feeds_value/feeds_rank=False), the sample
gates block, and the per-player structure of the pitchers/hitters tables.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_aaa_statcast_features.json"

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
        for k in _HITTER_KEYS:
            if k in record and not _num_ok(record.get(k)):
                problems.append(f"hitters[{bid}].{k} must be numeric or null")

    return payload, problems, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()

    payload, problems, present = validate_file(args.path)
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
