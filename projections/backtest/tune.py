"""Leakage-safe Marcel tuning. Grid search scored ONLY on the seasons passed in
(callers must keep tuning seasons disjoint from the seasons they later score)."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from projections.backtest.harness import rolling_origin
from projections.models.marcel_params import MarcelParams


def default_grid() -> list[MarcelParams]:
    grid: list[MarcelParams] = []
    for n_reg in (600.0, 900.0, 1200.0, 1500.0):
        for pa_base in (150.0, 200.0, 250.0):
            grid.append(MarcelParams(n_reg=n_reg, pa_base=pa_base))
    return grid


def grid_search(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    grid: list[MarcelParams],
) -> tuple[MarcelParams, float]:
    """Return (best_params, best_mean_mae_ratio) over the tuning seasons."""
    best_params: MarcelParams | None = None
    best_score: float | None = None
    for params in grid:
        score = rolling_origin(tuning_seasons, data_dir, params, identities)["mean_mae_ratio"]
        if best_score is None or score < best_score:
            best_params, best_score = params, score
    return best_params, best_score


def coordinate_descent(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    n_reg_values: tuple[float, ...],
    gamma_values: tuple[float, ...],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Alternately optimize gamma then n_reg_base (objective: minimize the
    candidate's tuning-block mean_mae_ratio vs persistence). Starts from classic
    Marcel, so it can never do worse than classic on the tuning block. Avoids the
    combinatorial blowup of a dense per-component grid."""
    best = MarcelParams()
    best_score = rolling_origin(tuning_seasons, data_dir, best, identities)["mean_mae_ratio"]
    for _ in range(max_rounds):
        improved = False
        for g in gamma_values:
            cand = replace(best, gamma=g)
            score = rolling_origin(tuning_seasons, data_dir, cand, identities)["mean_mae_ratio"]
            if score < best_score:
                best, best_score, improved = cand, score, True
        for n in n_reg_values:
            cand = replace(best, n_reg=n)
            score = rolling_origin(tuning_seasons, data_dir, cand, identities)["mean_mae_ratio"]
            if score < best_score:
                best, best_score, improved = cand, score, True
        if not improved:
            break
    return best, best_score
