"""Validate the shadow ValuCast prospect buy signals artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BUY_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
PROHIBITED_TRUE_FLAGS = (
    "dd_values_used",
    "dd_ranks_used",
    "dd_context_used",
    "public_source_ranks_used",
    "external_rankings_used_for_score",
    "market_values_used_for_score",
)


def validate_payload(payload: dict) -> list[str]:
    problems = []
    if payload.get("status") != "shadow_only":
        problems.append("status must be shadow_only")
    if payload.get("signal_version") != "0.1.0":
        problems.append("unsupported signal_version")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy") or {}
    for flag in PROHIBITED_TRUE_FLAGS:
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    board = payload.get("board")
    if not isinstance(board, list) or not board:
        problems.append("board must be a non-empty list")
        return problems

    ids = []
    identities = []
    for index, row in enumerate(board):
        if not isinstance(row, dict):
            problems.append(f"board[{index}] must be an object")
            continue
        for field in ("id", "name", "mlbam_id", "role", "rank", "score", "terms"):
            if row.get(field) in (None, ""):
                problems.append(f"board[{index}].{field} is required")
        if row.get("role") not in {"hitter", "pitcher"}:
            problems.append(f"board[{index}].role must be hitter or pitcher")
        if not isinstance(row.get("rank"), int):
            problems.append(f"board[{index}].rank must be an integer")
        if not isinstance(row.get("score"), (int, float)):
            problems.append(f"board[{index}].score must be numeric")
        ids.append(row.get("id"))
        identities.append((str(row.get("mlbam_id")), row.get("role")))

    if len(ids) != len(set(ids)):
        problems.append("duplicate row ids")
    if len(identities) != len(set(identities)):
        problems.append("duplicate MLBAM+role identities")
    validation = payload.get("validation") or {}
    if validation.get("duplicate_identity_count", 0) != 0:
        problems.append("validation reports duplicate identities")
    if validation.get("ranks_contiguous") is False:
        problems.append("validation reports non-contiguous ranks")
    return problems


def validate_file(path: Path = BUY_PATH) -> tuple[dict | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return None, [f"{path} unreadable: {exc}"]
    return payload, validate_payload(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=BUY_PATH)
    args = parser.parse_args()

    payload, problems = validate_file(args.path)
    if problems:
        print(f"VALUCAST BUYS VALIDATION FAILED for {args.path}:")
        for problem in problems:
            print(f"  - {problem}")
        return 1

    assert payload is not None
    validation = payload.get("validation") or {}
    print(
        "valucast buys: "
        f"rows={validation.get('row_count')} "
        f"eligible={validation.get('eligible_count')} "
        f"history_limited={validation.get('history_limited_count')} "
        f"ready_for_live_consumers={validation.get('ready_for_live_consumers')}"
    )
    for blocker in validation.get("blockers") or []:
        print(f"  blocker: {blocker}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
