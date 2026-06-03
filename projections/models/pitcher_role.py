"""Continuous pitcher role: SP-probability (no hard SP/RP cliff)."""
from __future__ import annotations

from collections.abc import Sequence

MIXED_LO, MIXED_HI = 0.2, 0.8


def role_share(row: dict) -> float:
    """GS / G for a season; 0.0 if no appearances."""
    g = float(row.get("G", 0))
    return float(row.get("GS", 0)) / g if g > 0 else 0.0


def project_p_sp(prior_seasons: Sequence[dict], weights: Sequence[float]) -> float:
    """Projected target-season SP probability = weighted recent role share."""
    pairs = [(role_share(s), w) for s, w in zip(prior_seasons, weights) if s is not None]
    wsum = sum(w for _, w in pairs)
    return sum(rs * w for rs, w in pairs) / wsum if wsum > 0 else 0.0


def is_mixed(p_sp: float) -> bool:
    return MIXED_LO < p_sp < MIXED_HI


def historical_role_mix(prior_seasons: Sequence[dict]) -> float:
    """BF-weighted role share of the seasons the pitcher's rates came from (h_SP).
    This is the role CONTEXT of the observed rates, used by the role-shift."""
    bf_sum = sum(float(s.get("BF", 0)) for s in prior_seasons if s is not None)
    if bf_sum <= 0:
        return 0.0
    return sum(role_share(s) * float(s.get("BF", 0))
              for s in prior_seasons if s is not None) / bf_sum
