"""Validate the ValuCast same-day call-up pulse."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_call_up_pulse import ARTIFACT_NAME, ARTIFACT_PATH, SIGNAL_VERSION  # noqa: E402


def validate_call_up_pulse(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    problems: list[str] = []
    if payload.get("artifact") != ARTIFACT_NAME:
        problems.append(f"artifact must be {ARTIFACT_NAME}")
    if payload.get("signal_version") != SIGNAL_VERSION:
        problems.append(f"signal_version must be {SIGNAL_VERSION}")
    try:
        datetime.fromisoformat(str(payload.get("generated_at")).replace("Z", "+00:00"))
    except ValueError:
        problems.append("generated_at must be ISO-8601 parseable")
    if payload.get("status") not in {"blocked", "candidate_ready"}:
        problems.append("status must be blocked or candidate_ready")
    source_policy = payload.get("source_policy") or {}
    for flag in (
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "external_rankings_used",
        "market_values_used",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")
    by_identity = payload.get("by_identity")
    if not isinstance(by_identity, dict):
        problems.append("by_identity must be an object")
    else:
        for key, row in list(by_identity.items())[:50]:
            if not isinstance(row, dict):
                problems.append(f"by_identity[{key}] must be an object")
                continue
            if row.get("role") not in {"hitter", "pitcher"}:
                problems.append(f"by_identity[{key}] role must be hitter or pitcher")
            if row.get("usage") != "call_up_pulse_context_not_live_rank_or_value":
                problems.append(f"by_identity[{key}] invalid usage")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_call_up_pulse(args.path)
    if problems:
        print(f"CALL-UP PULSE VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    print(
        "call-up pulse: "
        f"status={payload.get('status')} "
        f"call_ups={payload.get('summary', {}).get('call_up_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
