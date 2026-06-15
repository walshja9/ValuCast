"""Validate the shadow ValuCast Prospect Model v0.7 preview artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MODEL_PATH = ROOT / "data" / "models" / "valucast_prospect_model_v0_7.json"


def validate_model_v07(path: Path = MODEL_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_prospect_model_v0_7_preview":
        problems.append("artifact must be valucast_prospect_model_v0_7_preview")
    if not str(payload.get("model_version") or "").startswith("0.7.0"):
        problems.append("model_version must start with 0.7.0")
    if payload.get("status") != "shadow_preview":
        problems.append("status must be shadow_preview")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")

    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        problems.append("source_policy must be an object")
    else:
        for flag in (
            "dd_values_used",
            "dd_ranks_used",
            "external_rankings_used_for_score",
            "market_values_used_for_score",
            "feeds_live_rank",
            "feeds_live_value",
        ):
            if source_policy.get(flag) is not False:
                problems.append(f"source_policy.{flag} must be false")

    contract = payload.get("model_contract")
    if not isinstance(contract, dict):
        problems.append("model_contract must be an object")
    else:
        if contract.get("replaces_v0_6") is not False:
            problems.append("model_contract.replaces_v0_6 must be false")
        if contract.get("feeds_live_valucast_rank") is not False:
            problems.append("model_contract.feeds_live_valucast_rank must be false")
        if contract.get("score_mutation") != "none":
            problems.append("model_contract.score_mutation must be none")
        if contract.get("scored_challenger") is not True:
            problems.append("model_contract.scored_challenger must be true")

    validation = payload.get("validation")
    if not isinstance(validation, dict):
        problems.append("validation must be an object")
    else:
        if validation.get("ready_for_backtest") is not True:
            problems.append("validation.ready_for_backtest must be true")
        if validation.get("candidate_count", 0) <= 0:
            problems.append("validation.candidate_count must be positive")
        if validation.get("top200_factual_context_coverage", 0) < validation.get(
            "min_top200_factual_context_coverage", 1
        ):
            problems.append("top200 factual context coverage is below threshold")
        if "bucket_comparison_ready" not in validation:
            problems.append("validation.bucket_comparison_ready is required")
        if validation.get("scored_challenger_ready") is not True:
            problems.append("validation.scored_challenger_ready must be true")

    bucket_comparison = payload.get("bucket_comparison")
    if not isinstance(bucket_comparison, dict):
        problems.append("bucket_comparison must be an object")
    else:
        if bucket_comparison.get("live_score_mutation") != "none":
            problems.append("bucket_comparison.live_score_mutation must be none")
        if bucket_comparison.get("status") not in {"ready", "collecting"}:
            problems.append("bucket_comparison.status must be ready or collecting")
        if not isinstance(bucket_comparison.get("buckets"), list):
            problems.append("bucket_comparison.buckets must be a list")
        if bucket_comparison.get("promotion_delta_review_threshold") is None:
            problems.append(
                "bucket_comparison.promotion_delta_review_threshold is required"
            )

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        problems.append("candidates must be a non-empty list")
    else:
        for index, row in enumerate(candidates[:50], 1):
            coverage = row.get("feature_coverage")
            if not isinstance(coverage, dict):
                problems.append(f"candidate {index} feature_coverage is required")
                continue
            for key in (
                "factual_current_context",
                "availability_context",
                "sample_reliability",
            ):
                if key not in coverage:
                    problems.append(f"candidate {index} missing coverage key {key}")
            if not isinstance(row.get("candidate_features"), dict):
                problems.append(f"candidate {index} candidate_features is required")
            if row.get("v0_7_shadow_score") is None:
                problems.append(f"candidate {index} v0_7_shadow_score is required")
            if row.get("v0_7_delta_vs_rank_v1") is None:
                problems.append(
                    f"candidate {index} v0_7_delta_vs_rank_v1 is required"
                )

    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=MODEL_PATH)
    args = parser.parse_args()

    payload, problems = validate_model_v07(args.path)
    if problems:
        print(f"PROSPECT MODEL V0.7 VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload.get("validation") or {}
    print(
        "prospect model v0.7 preview: "
        f"candidates={validation.get('candidate_count')} "
        f"top200_factual_context_coverage="
        f"{validation.get('top200_factual_context_coverage')} "
        f"ready_for_backtest={validation.get('ready_for_backtest')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
