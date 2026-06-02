"""Marcel-style hitter projector. Projects per-PA component rates, then
composes counting stats under strict invariants (see spec §4)."""
from __future__ import annotations

from collections.abc import Sequence

from projections.constants import (
    AGE_ADJUSTED_RATES, PEAK_AGE, PROJECTED_RATES,
)
from projections.models.marcel_params import MarcelParams


def _age_mult(age: int | None, params: MarcelParams) -> float:
    if age is None:
        return 1.0
    if age < PEAK_AGE:
        return 1.0 + params.k_young * (PEAK_AGE - age)
    return 1.0 + params.k_old * (PEAK_AGE - age)  # (PEAK-age) negative -> decline


def project_hitter(
    prior_seasons: Sequence[dict | None],
    league_rates: dict[str, float],
    age: int | None,
    params: MarcelParams,
) -> dict:
    """prior_seasons is OFFSET-ALIGNED: index 0 = season T-1, 1 = T-2, 2 = T-3.
    A missing season is None and KEEPS its slot, so each present season gets the
    weight and PA role of its true offset (a player who missed T-1 but played T-2
    must not get T-1's weight). Returns a full stat dict."""
    pairs = [
        (s, w) for s, w in zip(prior_seasons, params.season_weights) if s is not None
    ]

    weighted_pa = sum(w * float(s.get("PA", 0)) for s, w in pairs)
    regressed: dict[str, float] = {}
    for c in PROJECTED_RATES:
        wtot = sum(w * float(s.get(c, 0)) for s, w in pairs)
        regressed[c] = (wtot + params.n_reg * league_rates.get(c, 0.0)) / (
            weighted_pa + params.n_reg
        )

    def _pa(i: int) -> float:
        if i < len(prior_seasons) and prior_seasons[i] is not None:
            return float(prior_seasons[i].get("PA", 0))
        return 0.0

    pa_proj = params.pa_w1 * _pa(0) + params.pa_w2 * _pa(1) + params.pa_base

    mult = _age_mult(age, params)
    counts: dict[str, float] = {}
    for c in PROJECTED_RATES:
        v = regressed[c] * pa_proj
        if c in AGE_ADJUSTED_RATES:
            v *= mult
        counts[c] = max(0.0, v)

    bb, hbp, sf = counts["BB"], counts["HBP"], counts["SF"]
    ab = max(0.0, pa_proj - bb - hbp - sf)
    h = counts["1B"] + counts["2B"] + counts["3B"] + counts["HR"]
    tb = counts["1B"] + 2 * counts["2B"] + 3 * counts["3B"] + 4 * counts["HR"]
    nsb = counts["SB"] - counts["CS"]

    pa_denom = ab + bb + hbp + sf
    avg = round(h / ab, 3) if ab > 0 else 0.0
    obp = round((h + bb + hbp) / pa_denom, 3) if pa_denom > 0 else 0.0
    slg = round(tb / ab, 3) if ab > 0 else 0.0

    out = dict(counts)
    out.update({
        "PA": pa_proj, "AB": ab, "H": h, "TB": tb, "NSB": nsb,
        "AVG": avg, "OBP": obp, "SLG": slg, "OPS": round(obp + slg, 3),
    })
    return out
