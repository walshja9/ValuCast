"""League-average per-PA component rates, computed ONLY from pre-target
seasons (leakage-safe)."""
from __future__ import annotations

from collections.abc import Sequence

from projections.constants import PROJECTED_RATES


def compute_league_rates(
    prior_snapshots: Sequence[Sequence[dict]],
    weights: Sequence[float],
    pa_floor: float,
) -> dict[str, float]:
    """prior_snapshots newest-first; weights aligned to it.

    Returns {component: weighted league total / weighted league PA}.
    """
    totals = {c: 0.0 for c in PROJECTED_RATES}
    pa_total = 0.0
    for snap, w in zip(prior_snapshots, weights):
        for row in snap:
            if float(row.get("PA", 0)) < pa_floor:
                continue
            pa_total += w * float(row.get("PA", 0))
            for c in PROJECTED_RATES:
                totals[c] += w * float(row.get(c, 0))
    if pa_total <= 0:
        return {c: 0.0 for c in PROJECTED_RATES}
    return {c: totals[c] / pa_total for c in PROJECTED_RATES}
