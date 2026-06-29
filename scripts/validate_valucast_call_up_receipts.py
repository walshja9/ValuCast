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
        if not isinstance(row, dict):
            problems.append(f"receipt {index} must be an object")
            continue
        for field in (
            "identity_key",
            "mlbam_id",
            "role",
            "name",
            "team",
            "pos",
            "level",
            "valucast_rank",
            "consensus_rank",
            "divergence",
            "call_up_date",
            "logged_at",
        ):
            if row.get(field) in (None, "", []):
                problems.append(f"receipt {index} missing {field}")
        if row.get("role") not in {"hitter", "pitcher"}:
            problems.append(f"receipt {index} role must be hitter or pitcher")
        expected_key = f"{row.get('mlbam_id')}_{row.get('role')}"
        if row.get("identity_key") != expected_key:
            problems.append(f"receipt {index} identity_key must be {expected_key}")
        if row.get("identity_key") in seen:
            problems.append(f"receipt {index} duplicate identity_key")
        seen.add(row.get("identity_key"))
        for field in ("valucast_rank", "consensus_rank", "divergence"):
            if not isinstance(row.get(field), int):
                problems.append(f"receipt {index} {field} must be an integer")
        if (
            isinstance(row.get("consensus_rank"), int)
            and isinstance(row.get("valucast_rank"), int)
            and isinstance(row.get("divergence"), int)
            and row["divergence"] != row["consensus_rank"] - row["valucast_rank"]
        ):
            problems.append(f"receipt {index} divergence must equal consensus_rank - valucast_rank")

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
        f"receipts={payload.get('summary', {}).get('receipt_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
