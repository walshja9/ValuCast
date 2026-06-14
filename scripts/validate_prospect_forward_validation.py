"""Validate the ValuCast prospect forward-validation artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

REPORT_PATH = ROOT / "data" / "models" / "valucast_prospect_forward_validation.json"


def validate_report(path: Path = REPORT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_prospect_forward_validation":
        problems.append("artifact must be valucast_prospect_forward_validation")
    if payload.get("status") not in {"collecting", "review_ready"}:
        problems.append("status must be collecting or review_ready")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        problems.append("source_policy must be an object")
    else:
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

    contract = payload.get("observation_contract") or {}
    if contract.get("is_realized_outcome_accuracy_evidence") is not False:
        problems.append("observation_contract must not claim realized outcome accuracy")
    if contract.get("uses_valucast_archives_only") is not True:
        problems.append("observation_contract must use ValuCast archives only")

    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics must be an object")
    else:
        if not isinstance(metrics.get("rank_comparison_count"), int):
            problems.append("metrics.rank_comparison_count must be an integer")
        if not isinstance(metrics.get("buy_comparison_count"), int):
            problems.append("metrics.buy_comparison_count must be an integer")

    latest = payload.get("latest_rank_comparison")
    if metrics and metrics.get("rank_comparison_count", 0) > 0:
        if not isinstance(latest, dict):
            problems.append("latest_rank_comparison is required when comparisons exist")
        elif not isinstance(latest.get("buckets"), list):
            problems.append("latest_rank_comparison.buckets must be a list")

    if not isinstance(payload.get("recommendations"), list):
        problems.append("recommendations must be a list")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=REPORT_PATH)
    args = parser.parse_args()

    payload, problems = validate_report(args.path)
    if problems:
        print(f"PROSPECT FORWARD VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    metrics = payload.get("metrics") or {}
    print(
        "prospect forward validation: "
        f"status={payload.get('status')} "
        f"rank_comparisons={metrics.get('rank_comparison_count')} "
        f"buy_comparisons={metrics.get('buy_comparison_count')} "
        f"span_days={metrics.get('observation_span_days')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
