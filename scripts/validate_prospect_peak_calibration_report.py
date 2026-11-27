from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACT_NAME = "valucast_prospect_peak_projection_calibration"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_peak_projection_calibration.json"

REQUIRED_FALSE_FLAGS = (
    "dd_values_used",
    "dd_ranks_used",
    "external_rankings_used_for_score",
    "public_scouting_grades_used",
    "feeds_live_rank",
    "feeds_live_value",
)


def validate_peak_calibration_report(path: Path = ARTIFACT_PATH) -> tuple[dict, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"could not load peak calibration report: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy") or {}
    for flag in REQUIRED_FALSE_FLAGS:
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    summary = payload.get("summary") or {}
    buckets = payload.get("buckets")
    if not isinstance(buckets, list) or not buckets:
        problems.append("buckets must be a non-empty list")
    elif summary.get("bucket_count") != len(buckets):
        problems.append("summary.bucket_count must match buckets length")

    for index, row in enumerate(buckets or []):
        if not isinstance(row, dict):
            problems.append(f"buckets[{index}] must be an object")
            continue
        for field in ("role", "level_band", "risk", "confidence", "count"):
            if row.get(field) in (None, ""):
                problems.append(f"buckets[{index}].{field} is required")
        if not isinstance(row.get("count"), int) or row.get("count") <= 0:
            problems.append(f"buckets[{index}].count must be a positive integer")

    validation = payload.get("validation") or {}
    if validation.get("ready_for_review") is not True:
        problems.append("validation.ready_for_review must be true")
    if validation.get("blockers"):
        problems.append("validation.blockers must be empty")
    return payload, problems


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ARTIFACT_PATH
    _payload, problems = validate_peak_calibration_report(path)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}")
        return 1
    print(f"Peak calibration report valid: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
