"""Statcast input de-noising bridge: blend historical hit components toward
xBA/xSLG, redistribute into 1B/2B/3B/HR by the player's own extra-base mix,
with feasibility guards. alpha=0 is an exact passthrough (classic)."""
from __future__ import annotations

from collections.abc import Sequence


def league_xbh_mix(rows: Sequence[dict]) -> tuple[tuple[float, float, float], float] | None:
    """League-average extra-base shape from a season's rows:
    ((2B_share, 3B_share, HR_share), m) where m = total bases per XB hit.
    None if the league has no extra-base hits (degenerate)."""
    d = sum(float(r.get("2B", 0)) for r in rows)
    t = sum(float(r.get("3B", 0)) for r in rows)
    hr = sum(float(r.get("HR", 0)) for r in rows)
    xb = d + t + hr
    if xb <= 0:
        return None
    m = (2 * d + 3 * t + 4 * hr) / xb
    return ((d / xb, t / xb, hr / xb), m)
