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


def historical_role_mix(prior_seasons: Sequence[dict], weights: Sequence[float]) -> float:
    """(season-weight x BF)-weighted role share of the seasons the pitcher's rates
    came from (h_SP) — the role CONTEXT of the observed rates, used by the role-shift.
    Must use the SAME offset-aligned 5/4/3 weights as project_pitcher_rates pools the
    rates, or a role-converter's shift exponent disagrees with its actual rate context."""
    pairs = [(s, w) for s, w in zip(prior_seasons, weights) if s is not None]
    denom = sum(w * float(s.get("BF", 0)) for s, w in pairs)
    if denom <= 0:
        return 0.0
    return sum(w * float(s.get("BF", 0)) * role_share(s) for s, w in pairs) / denom
