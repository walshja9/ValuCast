from __future__ import annotations

import math
from collections import defaultdict

import numpy as np
from scipy.stats import kendalltau, rankdata, spearmanr

BOOTSTRAP_SEED = 34041
BOOTSTRAP_RESAMPLES = 10_000
ROLES = ("hitter", "pitcher")
PREDICTIONS = {
    "model": "model_prediction",
    "level_age_prior": "prior_prediction",
    "historical_neighbors_25": "neighbor_prediction",
}


def _round(value):
    return None if value is None or not math.isfinite(float(value)) else round(float(value), 6)


def auc(scores: list[float], outcomes: list[int]) -> float | None:
    positives = sum(outcomes)
    negatives = len(outcomes) - positives
    if not positives or not negatives:
        return None
    ranks = rankdata(np.asarray(scores, dtype=float), method="average")
    positive_rank_sum = sum(rank for rank, outcome in zip(ranks, outcomes) if outcome)
    return float((positive_rank_sum - positives * (positives + 1) / 2) / (positives * negatives))


def _metric(name: str, predictions: list[float], targets: list[float]) -> float | None:
    if name == "roc_auc":
        return auc(predictions, [int(target > 0.0) for target in targets])
    if len(set(predictions)) < 2 or len(set(targets)) < 2:
        return None
    result = (
        spearmanr(predictions, targets).statistic
        if name == "spearman_rho"
        else kendalltau(predictions, targets, variant="b").statistic
    )
    return None if result is None or not math.isfinite(float(result)) else float(result)


def _draw_indices(rows: list[dict], rng: np.random.Generator) -> list[int]:
    groups = defaultdict(list)
    for index, row in enumerate(rows):
        groups[str(row["mlbam_id"])].append(index)
    ordered = [groups[key] for key in sorted(groups)]
    picks = rng.integers(0, len(ordered), len(ordered))
    return [index for pick in picks for index in ordered[int(pick)]]


def _interval(draws: list[float]) -> dict:
    if not draws:
        return {"low": None, "high": None}
    low, high = np.percentile(np.asarray(draws, dtype=float), [2.5, 97.5])
    return {"low": _round(low), "high": _round(high)}


def build_role_metrics(rows: list[dict], *, seed: int, resamples: int) -> dict:
    rows = sorted(rows, key=lambda row: (int(row["test_cohort"]), str(row["mlbam_id"])))
    targets = [float(row["target"]) for row in rows]
    points = {
        metric: {
            label: _metric(metric, [float(row[key]) for row in rows], targets)
            for label, key in PREDICTIONS.items()
        }
        for metric in ("spearman_rho", "kendall_tau_b", "roc_auc")
    }
    draws = {
        metric: {label: [] for label in PREDICTIONS}
        for metric in points
    }
    deltas = {
        metric: {label: [] for label in PREDICTIONS if label != "model"}
        for metric in points
    }
    rng = np.random.default_rng(seed)
    for _ in range(resamples):
        indices = _draw_indices(rows, rng)
        sample = [rows[index] for index in indices]
        sample_targets = [float(row["target"]) for row in sample]
        for metric in points:
            sampled = {
                label: _metric(metric, [float(row[key]) for row in sample], sample_targets)
                for label, key in PREDICTIONS.items()
            }
            for label, value in sampled.items():
                if value is not None:
                    draws[metric][label].append(value)
            for label in deltas[metric]:
                if sampled["model"] is not None and sampled[label] is not None:
                    deltas[metric][label].append(sampled["model"] - sampled[label])
    metrics = {}
    for metric, values in points.items():
        metrics[metric] = {
            label: {"point": _round(point), **_interval(draws[metric][label])}
            for label, point in values.items()
        }
        metrics[metric]["model_minus_baseline"] = {
            label: {
                "point": _round(values["model"] - values[label])
                if values["model"] is not None and values[label] is not None
                else None,
                **_interval(deltas[metric][label]),
            }
            for label in deltas[metric]
        }
        for comparison in metrics[metric]["model_minus_baseline"].values():
            comparison["historical_support"] = bool(
                len(rows) >= 250
                and len({int(row["test_cohort"]) for row in rows}) >= 3
                and comparison["low"] is not None
                and comparison["low"] > 0.0
            )
            comparison["evidence_status"] = (
                "supported_retrospective" if comparison["historical_support"] else "descriptive"
            )
    cohorts = {}
    for cohort in sorted({int(row["test_cohort"]) for row in rows}):
        cohort_rows = [row for row in rows if int(row["test_cohort"]) == cohort]
        cohort_targets = [float(row["target"]) for row in cohort_rows]
        cohorts[str(cohort)] = {
            "sample_size": len(cohort_rows),
            "contributor_base_rate": _round(
                sum(target > 0.0 for target in cohort_targets) / len(cohort_rows)
            ),
            "metrics": {
                metric: {
                    label: _round(
                        _metric(
                            metric,
                            [float(row[key]) for row in cohort_rows],
                            cohort_targets,
                        )
                    )
                    for label, key in PREDICTIONS.items()
                }
                for metric in points
            },
        }
    return {
        "sample_size": len(rows),
        "cohort_count": len({int(row["test_cohort"]) for row in rows}),
        "contributor_base_rate": _round(sum(target > 0.0 for target in targets) / len(rows)),
        "metrics": metrics,
        "cohorts": cohorts,
        "bootstrap": {"seed": seed, "resamples": resamples, "cluster": "mlbam_id"},
    }
