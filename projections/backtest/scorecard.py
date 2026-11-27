"""Backtest metrics. Mixed-scale stats are never summed as raw MAE; compare
via normalized error ratio vs a baseline."""
from __future__ import annotations

from collections.abc import Sequence
from statistics import mean, pstdev


def mae(pred: Sequence[float], actual: Sequence[float]) -> float:
    return mean(abs(p - a) for p, a in zip(pred, actual))


def rmse(pred: Sequence[float], actual: Sequence[float]) -> float:
    return (mean((p - a) ** 2 for p, a in zip(pred, actual))) ** 0.5


def correlation(pred: Sequence[float], actual: Sequence[float]) -> float:
    sp, sa = pstdev(pred), pstdev(actual)
    if sp == 0 or sa == 0:
        return 0.0
    mp, ma = mean(pred), mean(actual)
    cov = mean((p - mp) * (a - ma) for p, a in zip(pred, actual))
    return cov / (sp * sa)


def normalized_ratio(model_mae: float, baseline_mae: float) -> float:
    """<1.0 means the model beats the baseline on this stat."""
    if baseline_mae == 0:
        return float("inf") if model_mae > 0 else 0.0
    return model_mae / baseline_mae
