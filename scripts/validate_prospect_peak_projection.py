"""Validate the ValuCast Prospect Peak Projection v1 artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_peak_projection_v1.json"
CARD_VISUAL_VERSION = "2.0.0"


def validate_peak_projection(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_prospect_peak_projection_v1":
        problems.append("artifact must be valucast_prospect_peak_projection_v1")
    if payload.get("projection_version") != "1.0.0":
        problems.append("projection_version must be 1.0.0")
    if payload.get("status") != "candidate_ready":
        problems.append("status must be candidate_ready")
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
            "public_scouting_grades_used",
        ):
            if source_policy.get(flag) is not False:
                problems.append(f"source_policy.{flag} must be false")

    contract = payload.get("projection_contract")
    if not isinstance(contract, dict):
        problems.append("projection_contract must be an object")
    else:
        if contract.get("projection_kind") != "peak_role_and_skill_shape_not_full_stat_forecast":
            problems.append("projection_contract.projection_kind is invalid")
        if contract.get("card_visual_version") != CARD_VISUAL_VERSION:
            problems.append("projection_contract.card_visual_version is invalid")
        if contract.get("feeds_live_rank") is not False:
            problems.append("projection_contract.feeds_live_rank must be false")
        if contract.get("feeds_live_value") is not False:
            problems.append("projection_contract.feeds_live_value must be false")
        if contract.get("score_mutation") != "none":
            problems.append("projection_contract.score_mutation must be none")

    validation = payload.get("validation")
    if not isinstance(validation, dict):
        problems.append("validation must be an object")
    else:
        if validation.get("ready_for_card_v2") is not True:
            problems.append("validation.ready_for_card_v2 must be true")
        if validation.get("projection_count", 0) <= 0:
            problems.append("validation.projection_count must be positive")
        if validation.get("top200_projection_coverage", 0) < validation.get(
            "min_top200_projection_coverage", 1
        ):
            problems.append("top200 projection coverage is below threshold")
        if validation.get("duplicate_identity_count", 0) != 0:
            problems.append("duplicate_identity_count must be zero")
        if validation.get("missing_shape_count", 0) != 0:
            problems.append("missing_shape_count must be zero")
        if validation.get("missing_card_v2_count", 0) != 0:
            problems.append("missing_card_v2_count must be zero")

    projections = payload.get("projections")
    if not isinstance(projections, list) or not projections:
        problems.append("projections must be a non-empty list")
    else:
        seen: set[tuple[str, str]] = set()
        for index, row in enumerate(projections[:100], 1):
            key = (str(row.get("mlbam_id")), str(row.get("role")))
            if key in seen:
                problems.append(f"projection {index} duplicate identity")
            seen.add(key)
            for field in (
                "mlbam_id",
                "name",
                "role",
                "rank_v1_rank",
                "rank_v1_score",
                "peak_score",
                "peak_role",
                "ceiling_band",
                "floor_band",
                "risk_band",
                "confidence",
                "shape",
                "summary",
            ):
                if row.get(field) in (None, "", []):
                    problems.append(f"projection {index} missing {field}")
            if row.get("usage") != "card_visual_context_not_live_rank_or_value":
                problems.append(f"projection {index} has invalid usage")
            card_v2 = row.get("card_v2")
            if not isinstance(card_v2, dict):
                problems.append(f"projection {index} missing card_v2")
            else:
                if card_v2.get("visual_version") != CARD_VISUAL_VERSION:
                    problems.append(f"projection {index} has invalid card_v2 visual_version")
                if not isinstance(card_v2.get("role_probabilities"), dict):
                    problems.append(f"projection {index} missing role probabilities")
                if not card_v2.get("card_copy"):
                    problems.append(f"projection {index} missing card_v2 card_copy")
            shape = row.get("shape")
            if not isinstance(shape, list) or len(shape) < 4:
                problems.append(f"projection {index} shape must have at least four items")
            else:
                for shape_item in shape:
                    grade = shape_item.get("grade") if isinstance(shape_item, dict) else None
                    if not isinstance(grade, int) or not 20 <= grade <= 80:
                        problems.append(f"projection {index} has invalid shape grade")

    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()

    payload, problems = validate_peak_projection(args.path)
    if problems:
        print(f"PROSPECT PEAK PROJECTION VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload["validation"]
    print(
        "prospect peak projection v1: "
        f"projections={validation.get('projection_count')} "
        f"top200_projection_coverage={validation.get('top200_projection_coverage')} "
        f"ready_for_card_v2={validation.get('ready_for_card_v2')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
