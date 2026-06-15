"""Validate the ValuCast front-office readiness report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "data" / "models" / "valucast_front_office_report.json"


def validate_front_office_report(path: Path = REPORT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_front_office_report":
        problems.append("artifact must be valucast_front_office_report")
    if payload.get("status") != "front_office_track_active":
        problems.append("status must be front_office_track_active")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy") or {}
    for flag in (
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used",
        "market_values_used",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")
    overall = payload.get("overall") or {}
    if not isinstance(overall.get("score"), int):
        problems.append("overall.score must be an integer")
    if not overall.get("grade"):
        problems.append("overall.grade is required")
    pillars = payload.get("pillars")
    if not isinstance(pillars, list) or len(pillars) != 5:
        problems.append("pillars must contain five readiness pillars")
    else:
        names = {pillar.get("name") for pillar in pillars}
        for required in (
            "Product readiness",
            "Data pipeline readiness",
            "Independence",
            "Prospect credibility",
            "MLB front-office track",
        ):
            if required not in names:
                problems.append(f"missing pillar {required}")
    if not isinstance(payload.get("next_build_order"), list):
        problems.append("next_build_order must be a list")
    failure_watchlist = payload.get("failure_watchlist")
    if not isinstance(failure_watchlist, dict):
        problems.append("failure_watchlist must be an object")
    else:
        if not failure_watchlist.get("status"):
            problems.append("failure_watchlist.status is required")
        for field in (
            "blocking_finding_count",
            "front_office_risk_count",
            "v0_7_disagreement_count",
        ):
            if not isinstance(failure_watchlist.get(field), int):
                problems.append(f"failure_watchlist.{field} must be an integer")
        if not isinstance(failure_watchlist.get("blocking_findings"), list):
            problems.append("failure_watchlist.blocking_findings must be a list")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    payload, problems = validate_front_office_report(args.path)
    if problems:
        print(f"FRONT OFFICE REPORT VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    overall = payload.get("overall") or {}
    print(
        "front office report: "
        f"grade={overall.get('grade')} score={overall.get('score')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
