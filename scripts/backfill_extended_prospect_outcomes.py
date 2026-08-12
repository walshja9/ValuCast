"""Internal outcome acquisition helper for the registered sealed runner.

This module intentionally has no command-line or file-writing entry point.  The
registered runner owns reservation validation, source acquisition, and final
result publication.  Keeping this helper pure prevents a second executable path
from reading outcomes or leaving a readable pre-result cache behind.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from prospects.extended_history import canonicalize_mlb_seasons


OutcomeFetcher = Callable[[int, str], list[dict] | None]


def _target_keys(rows: Iterable[Mapping[str, Any]]) -> list[tuple[str, int, str]]:
    targets = {}
    for row in rows:
        role = str(row.get("role") or "")
        if role not in {"hitter", "pitcher"}:
            raise ValueError(f"invalid prepared role: {role!r}")
        mlbam_id = int(row["mlbam_id"])
        key = f"{mlbam_id}_{role}"
        if key in targets:
            raise ValueError(f"duplicate prepared outcome identity: {key}")
        targets[key] = (mlbam_id, role)
    return [(key, *targets[key]) for key in sorted(targets)]


def backfill_outcomes(
    rows: Iterable[Mapping[str, Any]],
    source_cache: Mapping[str, Any],
    *,
    fetcher: OutcomeFetcher,
    max_workers: int = 10,
) -> dict[str, Any]:
    """Return target-filtered outcomes in memory for the sealed runner.

    The fetcher is mandatory: there is deliberately no reachable default that
    can spend the registered look outside the hard-wired runner.
    """
    targets = _target_keys(rows)
    cache = {}
    for key, _mlbam_id, role in targets:
        if key not in source_cache:
            continue
        seasons = source_cache[key]
        if not isinstance(seasons, list):
            raise ValueError(f"cached outcome value is not a list: {key}")
        cache[key] = canonicalize_mlb_seasons(seasons, role)
    missing = [target for target in targets if target[0] not in cache]

    def fetch(
        target: tuple[str, int, str]
    ) -> tuple[str, str, list[dict] | None]:
        key, mlbam_id, role = target
        return key, role, fetcher(mlbam_id, role)

    workers = max(1, int(max_workers))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for key, role, seasons in executor.map(fetch, missing):
            if seasons is None:
                continue
            if not isinstance(seasons, list):
                raise ValueError(f"fetcher returned non-list outcome value: {key}")
            cache[key] = canonicalize_mlb_seasons(seasons, role)
    remaining = sorted(key for key, _mlbam_id, _role in targets if key not in cache)
    return {
        "status": "ready" if not remaining else "blocked",
        "target_count": len(targets),
        "cached_before": len(targets) - len(missing),
        "requested": len(missing),
        "resolved": len(cache),
        "remaining": remaining,
        "cache": cache,
    }
