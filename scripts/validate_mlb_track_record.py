"""Validate the ValuCast MLB track-record artifact shape."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TRACK_RECORD_PATH = ROOT / "data" / "models" / "valucast_mlb_track_record.json"


def validate_track_record(path: Path = TRACK_RECORD_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_mlb_track_record":
        problems.append("artifact must be valucast_mlb_track_record")
    if not payload.get("contract_version"):
        problems.append("contract_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        problems.append("profiles must be a non-empty list")
    validation = payload.get("validation") or {}
    if not validation.get("ready_for_mlb_dynasty_layer"):
        problems.extend(
            validation.get("blockers")
            or ["track-record artifact is not ready for MLB dynasty layer"]
        )
    seen = set()
    for index, row in enumerate(profiles or []):
        key = (str(row.get("mlbam_id")), row.get("role"))
        if key in seen:
            problems.append(f"duplicate MLBAM+role profile at index {index}: {key}")
        seen.add(key)
        if row.get("role") not in {"hitter", "pitcher"}:
            problems.append(f"profile {index} role must be hitter or pitcher")
        if row.get("track_record_certainty") is None:
            problems.append(f"profile {index} missing track_record_certainty")
        if row.get("track_record_floor_score") is None:
            problems.append(f"profile {index} missing track_record_floor_score")
        if not isinstance(row.get("volume"), dict):
            problems.append(f"profile {index} volume must be an object")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=TRACK_RECORD_PATH)
    args = parser.parse_args()

    payload, problems = validate_track_record(args.path)
    if problems:
        print(f"MLB TRACK RECORD VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload.get("validation") or {}
    print(
        "mlb track record: "
        f"profiles={validation.get('profile_count')} "
        f"coverage={validation.get('coverage_rate')} "
        f"ready={validation.get('ready_for_mlb_dynasty_layer')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
