"""Validate the Ahead-of-the-Curve track-record scorecard."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_ahead_of_consensus_scorecard import (  # noqa: E402
    ARTIFACT_NAME,
    ARTIFACT_PATH,
    SIGNAL_VERSION,
)


def validate_scorecard(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
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
    gate = payload.get("gate") or {}
    if not isinstance(gate.get("publishable"), bool):
        problems.append("gate.publishable must be boolean")
    summary = payload.get("summary") or {}
    rate = summary.get("catch_up_hit_rate")
    if rate is not None and not (0.0 <= rate <= 1.0):
        problems.append("summary.catch_up_hit_rate must be in [0, 1] or null")
    if not isinstance(payload.get("calls"), list):
        problems.append("calls must be a list")
    # Catch-up arithmetic spot-check.
    for c in (payload.get("calls") or [])[:50]:
        if not isinstance(c, dict):
            continue
        ct, cn, cu = c.get("consensus_then"), c.get("consensus_now"), c.get("consensus_catch_up")
        if all(isinstance(v, int) for v in (ct, cn, cu)) and cu != ct - cn:
            problems.append(f"{c.get('identity_key')} catch_up != consensus_then - consensus_now")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_scorecard(args.path)
    if problems:
        print(f"AHEAD-OF-CONSENSUS SCORECARD VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    s = payload.get("summary", {})
    print(
        "ahead-of-consensus scorecard: "
        f"publishable={payload.get('gate', {}).get('publishable')} "
        f"resolved={s.get('resolved_count')} hit_rate={s.get('catch_up_hit_rate')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
