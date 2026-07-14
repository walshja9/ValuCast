"""Validate the ValuCast gaps claim lifecycle ledger (plan 017).

Standalone validator (mirrors validate_ahead_of_consensus.py): reads the committed
artifact, asserts shape + every claim resolves into the taxonomy, and that no
terminal outcome is missing its resolution field. Exits non-zero on any problem.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.gaps_claim_ledger import (  # noqa: E402
    ALL_OUTCOMES,
    ARTIFACT_NAME,
    ARTIFACT_PATH,
    EXPIRY_DAYS,
    SIDES,
    SIGNAL_VERSION,
)
from prospects.call_up_receipts import LAUNCH_DATE  # noqa: E402


def _days_between(start: str, end: str) -> int | None:
    try:
        from datetime import date

        return (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
    except (TypeError, ValueError):
        return None


def validate_gaps_claim_ledger(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
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
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used",
        "market_values_used",
        "scored_by_frozen_aotc_scorecard",
    ):
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    claims = payload.get("claims")
    if not isinstance(claims, list):
        problems.append("claims must be a list")
        return payload, problems

    summary = payload.get("summary") or {}
    per_side_count = {side: 0 for side in SIDES}
    seen: set[tuple] = set()
    for index, claim in enumerate(claims, 1):
        if not isinstance(claim, dict):
            problems.append(f"claim {index} must be an object")
            continue
        side = claim.get("side")
        if side not in SIDES:
            problems.append(f"claim {index} side must be one of {SIDES}")
        else:
            per_side_count[side] += 1
        key = (claim.get("identity_key"), claim.get("claim_date"), side)
        if None in key:
            problems.append(f"claim {index} missing identity_key/claim_date/side")
        elif key in seen:
            problems.append(f"claim {index} duplicate (identity_key, claim_date, side)")
        seen.add(key)

        claim_date = str(claim.get("claim_date") or "")
        if claim_date and claim_date < LAUNCH_DATE:
            problems.append(f"claim {index} claim_date {claim_date} predates LAUNCH_DATE")

        outcome = claim.get("outcome")
        if outcome not in ALL_OUTCOMES:
            problems.append(f"claim {index} outcome {outcome!r} not in taxonomy")
            continue

        # Every terminal outcome must carry its resolution evidence.
        if outcome == "resolved_by_callup":
            resolved = claim.get("resolved_date")
            if not resolved:
                problems.append(f"claim {index} resolved_by_callup missing resolved_date")
            elif claim_date and resolved < claim_date:
                problems.append(f"claim {index} resolved_date precedes claim_date")
            if not isinstance(claim.get("lead_time_days"), int):
                problems.append(f"claim {index} resolved_by_callup missing lead_time_days")
        elif outcome == "expired_unresolved":
            age = _days_between(claim_date, claim.get("resolved_date") or "")
            if age is None or age < EXPIRY_DAYS:
                problems.append(
                    f"claim {index} expired_unresolved age {age} < EXPIRY_DAYS ({EXPIRY_DAYS})"
                )
        elif outcome in {"resolved_by_consensus_move", "retracted_by_model_move"}:
            if not claim.get("resolved_date"):
                problems.append(f"claim {index} {outcome} missing resolved_date")

    for side in SIDES:
        declared = (summary.get(side) or {}).get("total")
        if declared != per_side_count[side]:
            problems.append(
                f"summary.{side}.total ({declared}) != counted claims ({per_side_count[side]})"
            )

    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    payload, problems = validate_gaps_claim_ledger(args.path)
    if problems:
        print(f"GAPS CLAIM LEDGER VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    assert payload is not None
    summary = payload.get("summary") or {}
    print(
        "gaps claim ledger: "
        f"status={payload.get('status')} "
        f"higher={summary.get('higher', {}).get('total')} "
        f"lower={summary.get('lower', {}).get('total')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
