"""Validate the ValuCast permanent call-up receipts artifact."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.call_up_receipts import ARTIFACT_NAME, ARTIFACT_PATH, SIGNAL_VERSION  # noqa: E402


def _validate_call_up(row, index, label, seen, *, require_consensus, negative=False) -> list[str]:
    """Validate one call-up row (a receipt/hit or a miss).

    A scored row carries an integer consensus_rank + divergence. A field-unranked
    seed receipt has no consensus (field outside the public boards) and instead must
    carry a field_label. Misses are always scored and must diverge negative.
    """
    problems: list[str] = []
    if not isinstance(row, dict):
        return [f"{label} {index} must be an object"]
    for field in (
        "identity_key", "mlbam_id", "role", "name", "team",
        "pos", "level", "valucast_rank", "call_up_date", "logged_at",
    ):
        if row.get(field) in (None, "", []):
            problems.append(f"{label} {index} missing {field}")
    if row.get("role") not in {"hitter", "pitcher"}:
        problems.append(f"{label} {index} role must be hitter or pitcher")
    expected_key = f"{row.get('mlbam_id')}_{row.get('role')}"
    if row.get("identity_key") != expected_key:
        problems.append(f"{label} {index} identity_key must be {expected_key}")
    if row.get("identity_key") in seen:
        problems.append(f"{label} {index} duplicate identity_key")
    seen.add(row.get("identity_key"))
    if not isinstance(row.get("valucast_rank"), int):
        problems.append(f"{label} {index} valucast_rank must be an integer")

    consensus = row.get("consensus_rank")
    scored = isinstance(consensus, int)
    if require_consensus and not scored:
        problems.append(f"{label} {index} consensus_rank must be an integer")
    if scored:
        if not isinstance(row.get("divergence"), int):
            problems.append(f"{label} {index} divergence must be an integer")
        else:
            if isinstance(row.get("valucast_rank"), int) and row["divergence"] != consensus - row["valucast_rank"]:
                problems.append(f"{label} {index} divergence must equal consensus_rank - valucast_rank")
            if negative and row["divergence"] >= 0:
                problems.append(f"{label} {index} divergence must be negative (field ahead of us)")
    elif not row.get("field_label"):
        # field-unranked seed receipt: needs a label since there's no consensus to show
        problems.append(f"{label} {index} missing consensus_rank or field_label")
    return problems


def validate_file(path: Path = ARTIFACT_PATH) -> tuple[dict | None, list[str]]:
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

    summary = payload.get("summary") or {}
    receipts = payload.get("receipts")
    if not isinstance(receipts, list):
        problems.append("receipts must be a list")
        receipts = []
    if not isinstance(summary.get("receipt_count"), int):
        problems.append("summary.receipt_count must be an integer")
    elif summary.get("receipt_count") != len(receipts):
        problems.append("summary.receipt_count must equal len(receipts)")
    if not isinstance(summary.get("archive_dates_scanned"), list):
        problems.append("summary.archive_dates_scanned must be a list")

    seen = set()
    for index, row in enumerate(receipts, 1):
        problems.extend(_validate_call_up(row, index, "receipt", seen, require_consensus=False))

    misses = payload.get("misses")
    if not isinstance(misses, list):
        problems.append("misses must be a list")
        misses = []
    if not isinstance(summary.get("miss_count"), int):
        problems.append("summary.miss_count must be an integer")
    elif summary.get("miss_count") != len(misses):
        problems.append("summary.miss_count must equal len(misses)")
    miss_seen = set()
    for index, row in enumerate(misses, 1):
        problems.extend(_validate_call_up(row, index, "miss", miss_seen, require_consensus=True, negative=True))

    policy = payload.get("source_policy") or {}
    for flag in (
        "name_matching_used",
        "feeds_model_score",
        "feeds_public_rank",
        "feeds_buy_score",
        "dd_values_used",
        "dd_ranks_used",
        "external_rankings_used",
        "market_values_used",
    ):
        if policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")
    return payload, problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()

    payload, problems = validate_file(args.path)
    if problems:
        print(f"VALUCAST CALL-UP RECEIPTS VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    print(
        "valucast call-up receipts: "
        f"status={payload.get('status')} "
        f"receipts={payload.get('summary', {}).get('receipt_count')} "
        f"misses={payload.get('summary', {}).get('miss_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
