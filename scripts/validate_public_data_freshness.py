#!/usr/bin/env python3
"""Fail unless every daily public ValuCast data artifact is current."""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DD_FEED = ROOT / "data" / "dd" / "dd_dynasty_feed.json"
REDRAFT_METADATA = ROOT / "data" / "projections" / "metadata.json"
REDRAFT_CURRENT = ROOT / "data" / "projections" / "current.json"
REDRAFT_ROS = ROOT / "data" / "projections" / "ros.json"
ACTUALS = ROOT / "data" / "actuals" / "current.json"
STATCAST = ROOT / "data" / "statcast" / "percentiles.json"
MLB_DYNASTY_LAYER = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
MLB_TRACK_RECORD = ROOT / "data" / "models" / "valucast_mlb_track_record.json"
VALUCAST_BUYS = ROOT / "data" / "models" / "valucast_prospect_buys.json"
VALUCAST_QUALITY_GOVERNOR = ROOT / "data" / "models" / "valucast_quality_governor.json"
PROSPECT_AVAILABILITY = (
    ROOT / "data" / "models" / "valucast_prospect_availability.json"
)
PROSPECT_CALIBRATION_REPORT = (
    ROOT / "data" / "models" / "valucast_prospect_calibration_report.json"
)
PROSPECT_COVERAGE_AUDIT = (
    ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"
)
PUBLIC_SNAPSHOT = ROOT / "data" / "public" / "public_dynasty_snapshot.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_date(value) -> str:
    return str(value or "")[:10]


def validate_public_data(expected_date: str) -> list[str]:
    problems: list[str] = []

    dated_artifacts = [
        (DD_FEED, "generated_at"),
        (MLB_TRACK_RECORD, "generated_at"),
        (MLB_DYNASTY_LAYER, "generated_at"),
        (PROSPECT_AVAILABILITY, "generated_at"),
        (PROSPECT_CALIBRATION_REPORT, "generated_at"),
        (PROSPECT_COVERAGE_AUDIT, "generated_at"),
        (VALUCAST_BUYS, "generated_at"),
        (VALUCAST_QUALITY_GOVERNOR, "generated_at"),
        (PUBLIC_SNAPSHOT, "generated_at"),
        (REDRAFT_METADATA, "as_of"),
        (STATCAST, "as_of"),
    ]
    for path, field in dated_artifacts:
        try:
            payload = _load(path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{path.relative_to(ROOT)} unreadable: {exc}")
            continue
        actual = _iso_date(payload.get(field))
        if actual != expected_date:
            problems.append(
                f"{path.relative_to(ROOT)} {field}={actual or 'missing'}, "
                f"expected {expected_date}"
            )

    list_artifacts = [REDRAFT_CURRENT, REDRAFT_ROS, ACTUALS]
    for path in list_artifacts:
        try:
            payload = _load(path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{path.relative_to(ROOT)} unreadable: {exc}")
            continue
        if not isinstance(payload, list) or not payload:
            problems.append(f"{path.relative_to(ROOT)} has no player rows")

    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    args = parser.parse_args()

    problems = validate_public_data(args.date)
    if problems:
        print("PUBLIC DATA FRESHNESS FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"All daily public data artifacts are current for {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
