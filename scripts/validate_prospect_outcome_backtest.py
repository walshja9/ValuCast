"""Validate the ValuCast prospect outcome evidence artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUTCOME_PATH = ROOT / "data" / "models" / "valucast_prospect_outcome_backtest.json"


def validate_outcome_backtest(path: Path = OUTCOME_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_prospect_outcome_backtest":
        problems.append("artifact must be valucast_prospect_outcome_backtest")
    if payload.get("status") not in {"evidence_ready", "needs_work"}:
        problems.append("status must be evidence_ready or needs_work")
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
    evidence = payload.get("evidence") or {}
    for key in ("dynasty_fixed_horizon", "adapter_fixed_horizon", "forward_observation"):
        if key not in evidence:
            problems.append(f"evidence.{key} is required")
    if (evidence.get("forward_observation") or {}).get(
        "is_realized_outcome_accuracy_evidence"
    ) is not False:
        problems.append("forward observation must not claim realized outcome accuracy")
    track = payload.get("front_office_track") or {}
    if not isinstance(track.get("score"), int):
        problems.append("front_office_track.score must be an integer")
    if not track.get("grade"):
        problems.append("front_office_track.grade is required")
    validation = payload.get("validation") or {}
    if validation.get("realized_outcome_sample_size", 0) <= 0:
        problems.append("validation.realized_outcome_sample_size must be positive")
    if not isinstance(validation.get("blockers"), list):
        problems.append("validation.blockers must be a list")
    if not isinstance(validation.get("evidence_gates"), list):
        problems.append("validation.evidence_gates must be a list")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=OUTCOME_PATH)
    args = parser.parse_args()

    payload, problems = validate_outcome_backtest(args.path)
    if problems:
        print(f"PROSPECT OUTCOME BACKTEST VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    track = payload.get("front_office_track") or {}
    print(
        "prospect outcome backtest: "
        f"status={payload.get('status')} "
        f"grade={track.get('grade')} "
        f"score={track.get('score')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
