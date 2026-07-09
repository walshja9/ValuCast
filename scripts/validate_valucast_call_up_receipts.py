"""Validate the ValuCast permanent call-up receipts artifact."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.ahead_of_consensus import _public_source_ranks  # noqa: E402
from prospects.call_up_receipts import (  # noqa: E402
    ARTIFACT_NAME,
    ARTIFACT_PATH,
    RANK_ARCHIVE_DIR,
    SIGNAL_VERSION,
    _archive_by_date_key,
    _archive_payloads,
    _latest_source_row,
    _source_ranks,
)

# "field outside top 100" / "outside the top 100" -> the claimed field ceiling.
_OUTSIDE_TOP_RE = re.compile(r"outside (?:the )?top\s+(\d+)", re.IGNORECASE)


def _field_label_contradictions(
    receipts: list, archive_by_date_key: dict[str, dict[str, dict]]
) -> list[str]:
    """Fail any seed whose typed field_label claims "outside top N" while a public
    board in the ranked archive actually ranks the identity at <= N.

    This is the honesty backstop: a hand-typed label can never survive the build if
    the archive disproves it. Only fires on the "outside top N" phrasing (the one that
    makes a falsifiable claim); derived labels ("1 board, ~#512") carry no such claim
    and are left alone. No archive row / no in-cap board => nothing to contradict."""
    problems: list[str] = []
    for index, row in enumerate(receipts, 1):
        if not isinstance(row, dict):
            continue
        match = _OUTSIDE_TOP_RE.search(str(row.get("field_label") or ""))
        key = row.get("identity_key")
        if not match or not key:
            continue
        ceiling = int(match.group(1))
        source_row = _latest_source_row(key, archive_by_date_key)
        if source_row is None:
            continue
        for board, rank in _public_source_ranks(_source_ranks(source_row)).items():
            if rank <= ceiling:
                problems.append(
                    f"receipt {index} ({row.get('name') or key}) field_label claims "
                    f"'outside top {ceiling}' but board '{board}' ranks him #{round(rank)}"
                )
    return problems


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

    # Honesty backstop: a typed "outside top N" field_label can't survive if a public
    # board in the ranked archive actually ranks the player at <= N. Best-effort -- if
    # the archive can't be read (e.g. a CI checkout without it), skip rather than error.
    try:
        archive_index = _archive_by_date_key(_archive_payloads(RANK_ARCHIVE_DIR))
    except Exception:  # noqa: BLE001
        archive_index = {}
    if archive_index:
        problems.extend(_field_label_contradictions(receipts, archive_index))

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
