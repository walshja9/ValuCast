"""Percentile context, captions, movers, and identity lines for prospect cards.

Pool = feed prospects with a stat_line and pa >= MIN_PA ("ValuCast prospect pool").
Pure functions over DynastyRankingRow; no I/O. Built once at app startup.
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right

METRICS = ("avg", "obp", "slg", "ops", "iso", "k_pct", "bb_pct")
LOWER_IS_BETTER = frozenset({"k_pct"})
MIN_PA = 100
CAPTION_METRICS = ("ops", "k_pct", "iso")

# Percentile here is ALWAYS quality-direction: high percentile = good,
# so k_pct values are inverted before banding.
_CAPTIONS = {
    "ops": ((90, "Elite all-around production"), (75, "Strong production for the level"),
            (10, "Bat has been overmatched"), (25, "Production lags the level")),
    "k_pct": ((90, "Elite bat-to-ball — rarely strikes out"), (75, "Advanced contact skills"),
              (10, "Serious swing-and-miss risk"), (25, "Swing-and-miss concerns")),
    "iso": ((90, "Elite raw power output"), (75, "Real power in the profile"),
            (10, "Minimal power impact"), (25, "Light power so far")),
}

_STANDOUT_NOUN = {
    "ops": "production", "iso": "power", "slg": "power",
    "k_pct": "bat-to-ball skills", "bb_pct": "plate discipline",
    "avg": "hit ability", "obp": "on-base skills",
}


def _eligible(row) -> bool:
    line = row.stat_line or {}
    pa = line.get("pa")
    return bool(row.is_prospect and line and isinstance(pa, (int, float)) and pa >= MIN_PA)


def build_pool(rows) -> dict[str, list[float]]:
    """Sorted per-metric value arrays over eligible prospects."""
    pool: dict[str, list[float]] = {m: [] for m in METRICS}
    for row in rows:
        if not _eligible(row):
            continue
        for m in METRICS:
            v = (row.stat_line or {}).get(m)
            if isinstance(v, (int, float)):
                pool[m].append(float(v))
    return {m: sorted(vs) for m, vs in pool.items() if vs}


def percentile_for(pool: dict, metric: str, value) -> int | None:
    """Midrank percentile of value within the pool, quality-direction, clamped 1..99."""
    values = pool.get(metric)
    if not values or not isinstance(value, (int, float)):
        return None
    v = float(value)
    below = bisect_left(values, v)
    ties = bisect_right(values, v) - below
    pct = 100.0 * (below + 0.5 * ties) / len(values)
    if metric in LOWER_IS_BETTER:
        pct = 100.0 - pct
    return max(1, min(99, round(pct)))


def card_percentiles(pool: dict, row) -> dict[str, int]:
    """{metric: percentile} for an eligible prospect; {} otherwise."""
    if not _eligible(row):
        return {}
    out = {}
    for m in METRICS:
        pct = percentile_for(pool, m, (row.stat_line or {}).get(m))
        if pct is not None:
            out[m] = pct
    return out


def caption_for(metric: str, pct: int | None) -> str | None:
    """Threshold-banded caption; None in the neutral band or for non-headline metrics."""
    if pct is None or metric not in _CAPTIONS:
        return None
    bands = _CAPTIONS[metric]
    if pct >= bands[0][0]:
        return bands[0][1]
    if pct >= bands[1][0]:
        return bands[1][1]
    if pct <= bands[2][0]:
        return bands[2][1]
    if pct <= bands[3][0]:
        return bands[3][1]
    return None


def top_movers(rows, limit: int = 5, min_change: int = 5, max_rank: int = 200) -> list[dict]:
    """Largest |breakout_rank_change| among visible-board prospects. [] when quiet."""
    candidates = [
        r for r in rows
        if r.is_prospect
        and isinstance(r.breakout_rank_change, int)
        and abs(r.breakout_rank_change) >= min_change
        and r.prospect_rank is not None
        and r.prospect_rank <= max_rank
    ]
    candidates.sort(key=lambda r: (-abs(r.breakout_rank_change), r.prospect_rank))
    return [
        {"id": r.id, "name": r.name, "prospect_rank": r.prospect_rank,
         "change": r.breakout_rank_change}
        for r in candidates[:limit]
    ]


def identity_line(row, percentiles: dict) -> str | None:
    """One deterministic sentence from feed fields. None for non-prospects."""
    if not row.is_prospect:
        return None
    pos = row.positions[0] if row.positions else None
    if not pos:
        return None
    base = f"{row.age}-year-old {pos}" if row.age is not None else pos
    head = f"{base} at P#{row.prospect_rank}" if row.prospect_rank is not None else base

    bits = []
    consensus = row.public_source_consensus
    if consensus is not None and row.prospect_rank is not None:
        diff = consensus - row.prospect_rank
        if abs(diff) <= 10:
            bits.append("the public boards see it the same way")
        elif diff > 10:
            bits.append(f"we're higher than the boards (P#{row.prospect_rank} vs ~P#{consensus})")
        else:
            bits.append(f"we're lower than the boards (P#{row.prospect_rank} vs ~P#{consensus})")

    if percentiles:
        metric, pct = max(percentiles.items(), key=lambda kv: kv[1])
        if pct >= 90:
            bits.append(f"carried by elite {_STANDOUT_NOUN[metric]}")
        elif pct >= 75:
            bits.append(f"standout {_STANDOUT_NOUN[metric]}")

    return head + (" — " + "; ".join(bits) if bits else "")
