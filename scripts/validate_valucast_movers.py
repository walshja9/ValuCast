"""Validate the ValuCast prospect movers artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

MOVERS_PATH = ROOT / "data" / "models" / "valucast_prospect_movers.json"


def validate_file(path: Path = MOVERS_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]

    problems = []
    if payload.get("artifact") != "valucast_prospect_movers":
        problems.append("artifact must be valucast_prospect_movers")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    policy = payload.get("source_policy") or {}
    if policy.get("kind") != "valucast_prospect_movers":
        problems.append("source_policy.kind must be valucast_prospect_movers")
    for field in (
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "dd_values_used",
        "dd_ranks_used",
        "dd_context_used",
    ):
        if policy.get(field) is not False:
            problems.append(f"source_policy.{field} must be false")
    validation = payload.get("validation") or {}
    for field in ("rising_count", "cooling_count", "history_limited_count"):
        value = validation.get(field)
        if not isinstance(value, int) or value < 0:
            problems.append(f"validation.{field} must be a non-negative integer")
    if not isinstance(payload.get("rising"), list):
        problems.append("rising must be a list")
    if not isinstance(payload.get("cooling"), list):
        problems.append("cooling must be a list")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=MOVERS_PATH)
    args = parser.parse_args()

    payload, problems = validate_file(args.path)
    if problems:
        print(f"VALUCAST MOVERS VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload.get("validation") or {}
    print(
        "valucast movers: "
        f"rising={validation.get('rising_count')} "
        f"cooling={validation.get('cooling_count')} "
        f"history_limited={validation.get('history_limited_count')} "
        f"step_guard_excluded={validation.get('excluded_step_guard_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
