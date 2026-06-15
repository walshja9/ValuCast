"""Validate the ValuCast pipeline observability artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OBSERVABILITY_PATH = ROOT / "data" / "models" / "valucast_pipeline_observability.json"


def validate_pipeline_observability(
    path: Path = OBSERVABILITY_PATH,
) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_pipeline_observability":
        problems.append("artifact must be valucast_pipeline_observability")
    if not payload.get("observability_version"):
        problems.append("observability_version is required")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    if not payload.get("expected_date"):
        problems.append("expected_date is required")
    validation = payload.get("validation")
    if not isinstance(validation, dict):
        problems.append("validation must be an object")
    else:
        if not isinstance(validation.get("ready_for_daily_publication"), bool):
            problems.append("validation.ready_for_daily_publication must be a boolean")
        for field in (
            "artifact_count",
            "date_mismatch_count",
            "missing_or_unreadable_count",
            "targeted_row_refresh_count",
        ):
            if not isinstance(validation.get(field), int):
                problems.append(f"validation.{field} must be an integer")
    if not isinstance(payload.get("schedule"), dict):
        problems.append("schedule must be an object")
    if not isinstance(payload.get("artifacts"), list) or not payload.get("artifacts"):
        problems.append("artifacts must be a non-empty list")
    if not isinstance(payload.get("date_mismatches"), list):
        problems.append("date_mismatches must be a list")
    if not isinstance(payload.get("missing_or_unreadable"), list):
        problems.append("missing_or_unreadable must be a list")
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
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=OBSERVABILITY_PATH)
    args = parser.parse_args()

    payload, problems = validate_pipeline_observability(args.path)
    if problems:
        print(f"PIPELINE OBSERVABILITY VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload.get("validation") or {}
    print(
        "pipeline observability: "
        f"status={payload.get('status')} "
        f"ready={validation.get('ready_for_daily_publication')} "
        f"date_mismatches={validation.get('date_mismatch_count')} "
        f"missing={validation.get('missing_or_unreadable_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
