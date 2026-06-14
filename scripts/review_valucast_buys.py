"""Compare ValuCast-owned Buy signals against the current DD-backed /buys page."""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web import buy_score  # noqa: E402
from web.dd_feed_store import DDFeedStore  # noqa: E402
from web.valucast_buy_store import ValuCastBuyStore  # noqa: E402

DD_FEED_PATH = ROOT / "data" / "dd" / "dd_dynasty_feed.json"
VALUCAST_BUYS_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
OUTPUT_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_review.json"

MIN_TOP40_NAME_OVERLAP = 5
MAX_HISTORY_LIMITED_RATE = 0.50


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

    blockers = []
    if top40_name_overlap_count < MIN_TOP40_NAME_OVERLAP:
        blockers.append(
            "ValuCast Buy top-40 overlap with the current DD-backed /buys board is below review threshold."
        )
    if history_limited_rate > MAX_HISTORY_LIMITED_RATE:
        blockers.append(
            "ValuCast Buy momentum is history-limited until more dated ValuCast score archives accumulate."
        )
    if not manual_approval:
        blockers.append(
            "Human review is still required before changing the public /buys source."
        )
    review_status = "candidate_ready" if not blockers else "blocked"

    return {
        "artifact": "valucast_prospect_buys_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "review_status": review_status,
        "source_policy": {
            "kind": "comparison_only",
            "feeds_buy_score": False,
            "dd_values_used_for_valucast_score": False,
            "dd_ranks_used_for_valucast_score": False,
            "manual_approval_required_for_candidate_ready": True,
            "manual_approval_recorded": manual_approval,
        },
        "metrics": {
            "dd_top40_count": len(dd_board),
            "valucast_top40_count": len(valucast_board),
            "top40_name_overlap_count": top40_name_overlap_count,
            "top40_name_overlap_rate": round(top40_name_overlap_count / 40, 4),
            "history_limited_count": history_limited_count,
            "history_limited_rate": round(history_limited_rate, 4),
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


def main() -> None:
    dd_store = DDFeedStore(DD_FEED_PATH)
    buy_store = ValuCastBuyStore(VALUCAST_BUYS_PATH)
    if not dd_store.is_available:
        raise SystemExit("DD feed unavailable; cannot review ValuCast buys")
    if not buy_store.is_available:
        raise SystemExit("ValuCast buys unavailable; cannot review ValuCast buys")

    dd_board = buy_score.build_board(dd_store.get_all())
    valucast_board = buy_score.build_valucast_board(buy_store.get_all())
    payload = build_review(
        dd_board,
        valucast_board,
        buy_store,
        manual_approval=os.environ.get("VALUCAST_BUYS_REVIEW_APPROVED") == "1",
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
