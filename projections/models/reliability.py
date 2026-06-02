"""Per-component year-to-year reliability for stat-specific regression.

Season-level data only: reliability = PA-weighted year-to-year predictive
correlation of a component's per-PA rate, NOT a within-season stabilization
study (that would need game logs). Leakage-safe: caller passes only seasons
strictly before the target."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from projections.constants import PROJECTED_RATES

R_FLOOR = 0.05      # min reliability (avoids explosive n_reg for noisy stats)
N_REG_MIN = 300     # clamp floor for derived per-component n_reg
N_REG_MAX = 3000    # clamp ceiling for derived per-component n_reg


def _harmonic(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return 2 * a * b / (a + b)


def _weighted_corr(triples: Sequence[tuple[float, float, float]]) -> float:
    """triples = (x, y, w). Weighted Pearson correlation; 0.0 if degenerate."""
    if len(triples) < 2:
        return 0.0
    wsum = sum(w for _, _, w in triples)
    if wsum <= 0:
        return 0.0
    mx = sum(w * x for x, _, w in triples) / wsum
    my = sum(w * y for _, y, w in triples) / wsum
    cov = sum(w * (x - mx) * (y - my) for x, y, w in triples) / wsum
    vx = sum(w * (x - mx) ** 2 for x, _, w in triples) / wsum
    vy = sum(w * (y - my) ** 2 for _, y, w in triples) / wsum
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


def compute_reliability(
    season_to_rows: Mapping[int, Sequence[dict]],
    pa_floor: float,
) -> dict[str, float]:
    """Return {component: clamped year-to-year reliability} over all consecutive
    season pairs in season_to_rows. Both seasons of a pair must have the player
    with PA >= pa_floor."""
    seasons = sorted(season_to_rows)
    # Accumulate (earlier_rate, later_rate, weight) per component across pairs.
    triples: dict[str, list[tuple[float, float, float]]] = {c: [] for c in PROJECTED_RATES}
    for y in seasons:
        if (y + 1) not in season_to_rows:
            continue
        early = {r["mlbam_id"]: r for r in season_to_rows[y]
                 if float(r.get("PA", 0)) >= pa_floor}
        late = {r["mlbam_id"]: r for r in season_to_rows[y + 1]
                if float(r.get("PA", 0)) >= pa_floor}
        for pid in early.keys() & late.keys():
            e, l = early[pid], late[pid]
            pa_e, pa_l = float(e["PA"]), float(l["PA"])
            w = _harmonic(pa_e, pa_l)
            for c in PROJECTED_RATES:
                triples[c].append((float(e.get(c, 0)) / pa_e,
                                   float(l.get(c, 0)) / pa_l, w))
    rel: dict[str, float] = {}
    for c in PROJECTED_RATES:
        r = _weighted_corr(triples[c])
        rel[c] = min(max(r, R_FLOOR), 1.0)
    return rel
