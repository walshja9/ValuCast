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


def _descend(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    axes: list[tuple[str, tuple[float, ...]]],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Coordinate descent from classic Marcel over the given (field, values) axes.
    Objective: minimize tuning-block mean_mae_ratio vs persistence. Starting at
    classic means it can never do worse than classic on the tuning block."""
    best = MarcelParams()
    best_score = rolling_origin(tuning_seasons, data_dir, best, identities)["mean_mae_ratio"]
    for _ in range(max_rounds):
        improved = False
        for field, values in axes:
            for v in values:
                cand = replace(best, **{field: v})
                score = rolling_origin(tuning_seasons, data_dir, cand, identities)["mean_mae_ratio"]
                if score < best_score:
                    best, best_score, improved = cand, score, True
        if not improved:
            break
    return best, best_score


def coordinate_descent(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    n_reg_values: tuple[float, ...],
    gamma_values: tuple[float, ...],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Rung 2: tune (gamma, n_reg_base)."""
    return _descend(tuning_seasons, data_dir, identities,
                    [("gamma", gamma_values), ("n_reg", n_reg_values)], max_rounds)


def coordinate_descent_alpha(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    ac_values: tuple[float, ...],
    ap_values: tuple[float, ...],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Rung 3: tune (alpha_contact, alpha_power), gamma/n_reg held classic."""
    return _descend(tuning_seasons, data_dir, identities,
                    [("alpha_contact", ac_values), ("alpha_power", ap_values)], max_rounds)
