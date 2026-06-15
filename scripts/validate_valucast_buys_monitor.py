"""Validate the ValuCast prospect Buys v1 monitor artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MONITOR_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_monitor.json"


def validate_buys_monitor(path: Path = MONITOR_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems: list[str] = []
    if payload.get("artifact") != "valucast_prospect_buys_monitor":
        problems.append("artifact must be valucast_prospect_buys_monitor")
    if payload.get("status") not in {"collecting", "review_ready", "blocked"}:
        problems.append("status must be collecting, review_ready, or blocked")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")

    source_policy = payload.get("source_policy")
    if not isinstance(source_policy, dict):
        problems.append("source_policy must be an object")
    else:
        for flag in (
            "feeds_model_score",
            "feeds_buy_score",
            "feeds_public_rank",
            "dd_values_used",
            "dd_ranks_used",
            "external_rankings_used",
            "market_values_used",
        ):
            if source_policy.get(flag) is not False:
                problems.append(f"source_policy.{flag} must be false")

    contract = payload.get("monitor_contract")
    if not isinstance(contract, dict):
        problems.append("monitor_contract must be an object")
    else:
        if contract.get("monitors_live_buys_v1") is not True:
            problems.append("monitor_contract.monitors_live_buys_v1 must be true")
        if contract.get("mutates_buy_scores") is not False:
            problems.append("monitor_contract.mutates_buy_scores must be false")
        if contract.get("uses_valucast_archives_only") is not True:
            problems.append("monitor_contract.uses_valucast_archives_only must be true")

    monitoring = payload.get("monitoring")
    if not isinstance(monitoring, dict):
        problems.append("monitoring must be an object")
    else:
        if monitoring.get("feeds_live_buys") is not True:
            problems.append("monitoring.feeds_live_buys must be true")
        if monitoring.get("ready_for_live_consumers") is not True:
            problems.append("monitoring.ready_for_live_consumers must be true")
        if not isinstance(monitoring.get("buy_comparison_count"), int):
            problems.append("monitoring.buy_comparison_count must be an integer")
        if not isinstance(monitoring.get("observation_span_days"), int):
            problems.append("monitoring.observation_span_days must be an integer")

    validation = payload.get("validation")
    if not isinstance(validation, dict):
        problems.append("validation must be an object")
    else:
        if payload.get("status") != "blocked" and validation.get(
            "ready_for_monitoring"
        ) is not True:
            problems.append("non-blocked monitor must be ready_for_monitoring")
        if not isinstance(validation.get("blockers"), list):
            problems.append("validation.blockers must be a list")

    input_artifacts = payload.get("input_artifacts") or {}
    if input_artifacts.get("buy_signal_version") != "1.0.0":
        problems.append("input_artifacts.buy_signal_version must be 1.0.0")
    if not isinstance(payload.get("recommendations"), list):
        problems.append("recommendations must be a list")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=MONITOR_PATH)
    args = parser.parse_args()

    payload, problems = validate_buys_monitor(args.path)
    if problems:
        print(f"VALUCAST BUYS MONITOR VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    monitoring = payload.get("monitoring") or {}
    print(
        "valucast buys monitor: "
        f"status={payload.get('status')} "
        f"buy_comparisons={monitoring.get('buy_comparison_count')} "
        f"span_days={monitoring.get('observation_span_days')} "
        f"next_action={monitoring.get('next_action')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
