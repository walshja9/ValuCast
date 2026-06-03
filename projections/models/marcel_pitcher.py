"""Role-routed Marcel pitcher projector: per-BF skill rates with a leakage-safe
SP/RP role-shift, separate SP/RP usage, blended by SP-probability, reconstructed
into engine pitching categories (primary-pool export)."""
from __future__ import annotations

from collections.abc import Sequence

from projections.constants import PITCHER_SKILL_RATES
from projections.models.pitcher_params import PitcherMarcelParams
from projections.models.pitcher_role import historical_role_mix, project_p_sp, is_mixed


def compute_pitcher_league_rates(
    prior_snapshots: Sequence[Sequence[dict]],
    weights: Sequence[float],
    bf_floor: float,
) -> dict[str, float]:
    """Weighted per-BF league rates (leakage-safe; pre-target snapshots only)."""
    totals = {c: 0.0 for c in PITCHER_SKILL_RATES}
    bf_total = 0.0
    for snap, w in zip(prior_snapshots, weights):
        for row in snap:
            if float(row.get("BF", 0)) < bf_floor:
                continue
            bf_total += w * float(row.get("BF", 0))
            for c in PITCHER_SKILL_RATES:
                totals[c] += w * float(row.get(c, 0))
    if bf_total <= 0:
        return {c: 0.0 for c in PITCHER_SKILL_RATES}
    return {c: totals[c] / bf_total for c in PITCHER_SKILL_RATES}


def compute_role_factors(
    prior_snapshots: Sequence[Sequence[dict]],
    bf_floor: float,
) -> dict[str, float]:
    """f[c] = league RP-context per-BF rate / SP-context per-BF rate (leakage-safe).
    Split each pitcher-season by role_share>=0.5. f>1 means relievers post more of
    that component per BF (e.g. K); f<1 for ER/H. A zero on EITHER side neutralizes
    to 1.0 so f^(negative exponent) can't blow up."""
    sp_tot = {c: 0.0 for c in PITCHER_SKILL_RATES}; sp_bf = 0.0
    rp_tot = {c: 0.0 for c in PITCHER_SKILL_RATES}; rp_bf = 0.0
    for snap in prior_snapshots:
        for row in snap:
            bf = float(row.get("BF", 0))
            if bf < bf_floor:
                continue
            g = float(row.get("G", 0)); gs = float(row.get("GS", 0))
            is_sp = (gs / g) >= 0.5 if g > 0 else False
            if is_sp:
                sp_bf += bf
                for c in PITCHER_SKILL_RATES:
                    sp_tot[c] += float(row.get(c, 0))
            else:
                rp_bf += bf
                for c in PITCHER_SKILL_RATES:
                    rp_tot[c] += float(row.get(c, 0))
    f = {}
    for c in PITCHER_SKILL_RATES:
        sp_rate = sp_tot[c] / sp_bf if sp_bf > 0 else 0.0
        rp_rate = rp_tot[c] / rp_bf if rp_bf > 0 else 0.0
        f[c] = (rp_rate / sp_rate) if (sp_rate > 0 and rp_rate > 0) else 1.0
    return f


def project_pitcher_rates(
    prior_seasons: Sequence[dict | None],
    league_rates: dict[str, float],
    role_factors: dict[str, float],
    h_sp: float,
    p_sp: float,
    params: PitcherMarcelParams,
) -> dict[str, float]:
    """Per-BF skill rates: weighted + regressed (Marcel), then role-shifted by
    f[c]^(h_sp - p_sp). Age is neutral in v1 (no curve)."""
    # Offset-aligned: prior_seasons[i] may be None (missed year). zip with the full
    # season_weights pins each PRESENT season to its true offset weight — do NOT
    # compress (a pitcher who missed T-1 but pitched T-2 keeps the T-2 weight).
    pairs = [(s, w) for s, w in zip(prior_seasons, params.season_weights) if s is not None]
    weighted_bf = sum(w * float(s.get("BF", 0)) for s, w in pairs)
    out: dict[str, float] = {}
    for c in PITCHER_SKILL_RATES:
        wtot = sum(w * float(s.get(c, 0)) for s, w in pairs)
        regressed = (wtot + params.n_reg * league_rates.get(c, 0.0)) / (weighted_bf + params.n_reg)
        shift = role_factors.get(c, 1.0) ** (h_sp - p_sp)
        out[c] = max(0.0, regressed * shift)
    return out
