"""Shared DD-feed validation. Used by the pre-deploy build check
(`scripts/validate_feed.py`) and the test suite (`tests/test_dd_feed_integrity.py`)
so the build and CI assert exactly the same invariants.

An invalid committed feed must fail the build — the candidate Render deploy then
fails while the prior healthy deploy stays live.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


def validate_dd_feed(path) -> list[str]:
    """Return a list of problems with the DD feed at `path` (empty == valid).

    Mirrors DDFeedStore's fail-closed contract: duplicate ids, declared/actual
    count mismatch, non-contiguous dynasty ranks, and loader rejection.
    """
    problems: list[str] = []
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - any read/parse error is a hard fail
        return [f"feed unreadable: {exc}"]

    players = data.get("players")
    if not isinstance(players, list) or not players:
        return ["feed has no players"]

    ids = [p.get("id") for p in players]
    dupes = sorted({i for i, c in Counter(ids).items() if c > 1})
    if dupes:
        problems.append(f"duplicate ids: {dupes}")

    mlb = sum(1 for p in players if p.get("player_type") == "mlb")
    pro = sum(1 for p in players if p.get("player_type") == "prospect")
    if data.get("player_count") != mlb or data.get("prospect_count") != pro:
        problems.append(
            f"count mismatch: declared {data.get('player_count')}/{data.get('prospect_count')}"
            f", actual {mlb}/{pro}"
        )

    ranks = sorted(p.get("dynasty_rank") for p in players)
    if ranks != list(range(1, len(players) + 1)):
        problems.append("dynasty_rank not contiguous 1..N")

    # The loader is the ultimate authority — if it would fail closed, so must we.
    try:
        from web.dd_feed_store import DDFeedStore

        if not DDFeedStore(str(path)).is_available:
            problems.append("DDFeedStore rejects the feed (is_available=False)")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"DDFeedStore raised loading the feed: {exc}")

    return problems
