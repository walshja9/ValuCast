"""Validate the ValuCast front-office failure report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "data" / "models" / "valucast_front_office_failures.json"


def validate_front_office_failures(
    path: Path = REPORT_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_front_office_failures":
        problems.append("artifact must be valucast_front_office_failures")
    if payload.get("status") != "watchlist_active":
        problems.append("status must be watchlist_active")
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
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        problems.append("summary must be an object")
    else:
        for field in (
            "blocking_finding_count",
            "evidence_gate_count",
            "front_office_risk_count",
            "v0_7_disagreement_count",
        ):
            if not isinstance(summary.get(field), int):
                problems.append(f"summary.{field} must be an integer")
    for field in (
        "blocking_findings",
        "evidence_gates",
        "latest_rank_bucket_watchlist",
        "latest_buy_largest_movers",
        "front_office_risks",
        "v0_7_disagreements",
    ):
        if not isinstance(payload.get(field), list):
            problems.append(f"{field} must be a list")
    progress = payload.get("forward_archive_progress")
    if not isinstance(progress, dict):
        problems.append("forward_archive_progress must be an object")
    else:
        for field in (
            "rank_comparison_count",
            "buy_comparison_count",
            "observation_span_days",
            "remaining_rank_comparisons",
            "remaining_buy_comparisons",
            "remaining_span_days",
        ):
            if not isinstance(progress.get(field), int):
                problems.append(f"forward_archive_progress.{field} must be an integer")
    if not isinstance(payload.get("forward_archive_thresholds"), dict):
        problems.append("forward_archive_thresholds must be an object")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    payload, problems = validate_front_office_failures(args.path)
    if problems:
        print(f"FRONT OFFICE FAILURES VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    summary = payload.get("summary") or {}
    print(
        "front office failures: "
        f"blocking={summary.get('blocking_finding_count')} "
        f"evidence_gates={summary.get('evidence_gate_count')} "
        f"risks={summary.get('front_office_risk_count')} "
        f"v07_disagreements={summary.get('v0_7_disagreement_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
