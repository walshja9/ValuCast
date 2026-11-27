"""Review ValuCast-owned Buy signals before public promotion.

DD overlap is reported as comparison context only. A ValuCast Buy board should
not be blocked just because it disagrees with the legacy DD-backed buy board.
"""
from __future__ import annotations

import json
import os
import re
import sys
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web import buy_score  # noqa: E402
from web.valucast_buy_store import ValuCastBuyStore  # noqa: E402
from prospects.buy_approval import (  # noqa: E402
    APPROVAL_SCHEMA_VERSION,
    APPROVAL_SCOPE,
    qualified_approval_receipt,
)

VALUCAST_BUYS_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
OUTPUT_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_review.json"

MAX_HISTORY_LIMITED_RATE = 0.50
BOARD_REVIEW_SIZE = 40


def _norm_name(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def _top_rows(rows: list[dict], limit: int = 15) -> list[dict]:
    return [
        {
            "rank": row.get("rank"),
            "name": row.get("name"),
            "score": row.get("score"),
            "level": row.get("level"),
            "age": row.get("age"),
            "reason": row.get("reason"),
        }
        for row in rows[:limit]
    ]


def _distribution(rows: list[dict], field: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(field)) for row in rows).items()))


def build_review(
    dd_board: list[dict],
    valucast_board: list[dict],
    buy_store,
    manual_approval: bool = False,
    prior_review: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    dd_names = {_norm_name(row.get("name")): row for row in dd_board}
    valucast_names = {_norm_name(row.get("name")): row for row in valucast_board}
    overlap_names = sorted(
        set(dd_names) & set(valucast_names),
        key=lambda key: valucast_names[key].get("rank") or 999999,
    )
    top40_name_overlap_count = len(overlap_names)
    validation = buy_store.validation or {}
    history_limited_count = validation.get("history_limited_count", 0)
    buy_row_count = validation.get("row_count") or len(valucast_board)
    history_limited_rate = (
        history_limited_count / max(buy_row_count, 1)
    )

    manual_approval = manual_approval is True
    prior_review = prior_review if isinstance(prior_review, dict) else {}
    prior_policy = prior_review.get("source_policy") or {}
    prior_policy = prior_policy if isinstance(prior_policy, dict) else {}
    prior_decision = prior_review.get("promotion_decision") or {}
    prior_decision = prior_decision if isinstance(prior_decision, dict) else {}
    prior_receipt = prior_review.get("approval_receipt")
    qualified_prior = qualified_approval_receipt(prior_receipt)
    legacy_origin_unknown = (
        prior_policy.get("legacy_approval_origin_unknown") is True
        or (prior_policy.get("manual_approval_recorded") is True and not qualified_prior)
    )
    approval_receipt = dict(prior_receipt) if qualified_prior else None
    if manual_approval:
        approval_receipt = {
            "schema_version": APPROVAL_SCHEMA_VERSION,
            "origin": "explicit_manual_input",
            "scope": APPROVAL_SCOPE,
            "approved_at": datetime.now(timezone.utc).isoformat(),
        }
    approval_recorded = approval_receipt is not None
    neutral_momentum_approval = qualified_prior and (
        prior_policy.get("history_launch_approved") is True
        or prior_decision.get("neutral_momentum_launch_approved") is True
    )
    neutral_momentum_launch = (
        history_limited_rate > MAX_HISTORY_LIMITED_RATE
        and (
            neutral_momentum_approval
            or manual_approval
        )
    )
    blockers = []
    if history_limited_rate > MAX_HISTORY_LIMITED_RATE:
        if not neutral_momentum_launch:
            blockers.append(
                "ValuCast Buy momentum is history-limited until review approves neutral-momentum launch or more dated ValuCast score archives accumulate."
            )
    if not approval_recorded:
        if legacy_origin_unknown:
            blockers.append(
                "Saved Buy approval origin is unverified; explicit continuation or independently bound authorization is required."
            )
        else:
            blockers.append(
                "Human review is still required before changing the public /buys source."
            )
    review_status = "candidate_ready" if not blockers else "blocked"

    return {
        "artifact": "valucast_prospect_buys_review",
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "review_status": review_status,
        "approval_receipt": approval_receipt,
        "source_policy": {
            "kind": "comparison_only",
            "feeds_buy_score": False,
            "dd_values_used_for_valucast_score": False,
            "dd_ranks_used_for_valucast_score": False,
            "manual_approval_required_for_candidate_ready": True,
            "manual_approval_recorded": approval_recorded,
            "prior_approval_reused": qualified_prior and not manual_approval,
            "legacy_approval_origin_unknown": legacy_origin_unknown,
            "dd_overlap_required_for_candidate_ready": False,
            "history_launch_approved": neutral_momentum_launch,
            "approval_kind": (
                "neutral_momentum_launch"
                if neutral_momentum_launch
                else "human_review"
                if approval_recorded
                else None
            ),
        },
        "promotion_decision": {
            "status": review_status,
            "neutral_momentum_launch_approved": neutral_momentum_launch,
            "dd_overlap_is_context_only": True,
            "history_limited_rate": round(history_limited_rate, 4),
            "requires_route_gate": True,
        },
        "metrics": {
            "dd_top40_count": len(dd_board),
            "valucast_top40_count": len(valucast_board),
            "top40_name_overlap_count": top40_name_overlap_count,
            "top40_name_overlap_rate": round(top40_name_overlap_count / 40, 4),
            "dd_overlap_context_only": True,
            "history_limited_count": history_limited_count,
            "history_limited_rate": round(history_limited_rate, 4),
            "max_history_limited_rate": MAX_HISTORY_LIMITED_RATE,
            "dd_level_distribution": _distribution(dd_board, "level"),
            "valucast_level_distribution": _distribution(valucast_board, "level"),
            "dd_age_distribution": _distribution(dd_board, "age"),
            "valucast_age_distribution": _distribution(valucast_board, "age"),
        },
        "blockers": blockers,
        "overlap": [
            {
                "name": valucast_names[key].get("name"),
                "valucast_rank": valucast_names[key].get("rank"),
                "dd_rank": dd_names[key].get("rank"),
                "valucast_score": valucast_names[key].get("score"),
                "dd_score": dd_names[key].get("score"),
            }
            for key in overlap_names
        ],
        "dd_top": _top_rows(dd_board),
        "valucast_top": _top_rows(valucast_board),
    }


def write_review(payload: dict, path: Path = OUTPUT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _load_prior_approval(path: Path = OUTPUT_PATH) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--approve-neutral-momentum-launch",
        action="store_true",
        help=(
            "Record explicit review approval to launch ValuCast-owned Buys "
            "while score-history momentum is still launch-limited."
        ),
    )
    args = parser.parse_args()
    buy_store = ValuCastBuyStore(VALUCAST_BUYS_PATH)
    if not buy_store.is_available:
        raise SystemExit("ValuCast buys unavailable; cannot review ValuCast buys")

    explicit_approval = (
        args.approve_neutral_momentum_launch
        or os.environ.get("VALUCAST_BUYS_REVIEW_APPROVED") == "1"
    )
    prior_review = _load_prior_approval()
    valucast_board = buy_score.build_valucast_board(
        buy_store.get_all(),
        n=BOARD_REVIEW_SIZE,
    )
    payload = build_review(
        [],
        valucast_board,
        buy_store,
        manual_approval=explicit_approval,
        prior_review=prior_review,
        generated_at=buy_store.generated_at,
    )
    path = write_review(payload)
    metrics = payload["metrics"]
    print(
        "ValuCast buys review: "
        f"overlap={metrics['top40_name_overlap_count']}/40 "
        f"history_limited={metrics['history_limited_count']} "
        f"status={payload['review_status']} -> {path}"
    )
    for blocker in payload["blockers"]:
        print(f"  blocker: {blocker}")


if __name__ == "__main__":
    main()
