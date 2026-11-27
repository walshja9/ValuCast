"""Outcome-grounded, comparison-only head-to-head benchmark helpers."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import isfinite
from statistics import mean

import numpy as np

from prospects.model import _rank_concordance


MINIMUM_INDUSTRY_CLAIM_PLAYERS = 150


def _hash(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "content_sha256"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _by_id(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for row in rows:
        key = str(row.get("mlbam_id") or "")
        rank = row.get("rank")
        if not key or not isinstance(rank, (int, float)):
            continue
        prior = out.get(key)
        if prior is None or float(rank) < float(prior["rank"]):
            out[key] = row
    return out


def build_cohort(
    *,
    cohort_id: str,
    registered_at: str,
    track: str,
    valucast_rows: list[dict],
    competitor_rows: list[dict],
    sources: dict,
) -> dict:
    """Freeze the common-player intersection of two dated ranked lists."""
    valucast = _by_id(valucast_rows)
    competitor = _by_id(competitor_rows)
    common = valucast.keys() & competitor.keys()
    rows = [
        {
            "mlbam_id": key,
            "name": valucast[key].get("name") or competitor[key].get("name"),
            "role": valucast[key].get("role") or competitor[key].get("role"),
            "valucast_rank": float(valucast[key]["rank"]),
            "competitor_rank": float(competitor[key]["rank"]),
        }
        for key in common
    ]
    rows.sort(key=lambda row: (row["valucast_rank"], row["mlbam_id"]))
    payload = {
        "cohort_id": cohort_id,
        "registered_at": registered_at,
        "track": track,
        "sources": sources,
        "counts": {
            "valucast": len(valucast),
            "competitor": len(competitor),
            "matched": len(common),
            "valucast_only": len(valucast.keys() - competitor.keys()),
            "competitor_only": len(competitor.keys() - valucast.keys()),
        },
        "rows": rows,
        "content_sha256": "",
    }
    payload["content_sha256"] = _hash(payload)
    return payload


def append_cohort(registry: dict, cohort: dict) -> dict:
    """Append a sealed cohort; an existing ID is immutable."""
    cohort_id = cohort["cohort_id"]
    if cohort.get("content_sha256") != _hash(cohort):
        raise ValueError(
            f"cohort {cohort_id} is immutable: invalid content seal"
        )
    cohorts = registry.setdefault("cohorts", {})
    existing = cohorts.get(cohort_id)
    if existing and existing.get("content_sha256") != cohort.get("content_sha256"):
        raise ValueError(f"cohort {cohort_id} is immutable")
    if existing is None:
        cohorts[cohort_id] = deepcopy(cohort)
    return registry


def _percentile_ranks(values: list[float], *, higher_is_better: bool) -> list[float]:
    if len(values) < 2:
        return [0.0] * len(values)
    order = sorted(
        range(len(values)), key=lambda index: values[index], reverse=higher_is_better
    )
    result = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        percentile = ((start + end - 1) / 2) / (len(values) - 1)
        for position in range(start, end):
            result[order[position]] = percentile
        start = end
    return result


def _regression_pct(candidate: float, comparator: float) -> float:
    if comparator == 0:
        return 0.0 if candidate == 0 else float("inf")
    return (candidate - comparator) / comparator * 100.0


def _relative_improvement_pct(candidate: float, baseline: float) -> float | None:
    if baseline == 0:
        return 0.0 if candidate == 0 else None
    return (baseline - candidate) / baseline * 100.0


def _claim_decision(
    *,
    evidence_ready: bool,
    ci_low: float | None,
    ci_high: float | None,
    relative_improvement_pct: float | None,
    cohort_regressions: list[float],
    segment_regressions: list[float],
    top_k_non_regression: bool,
    claim_eligible: bool,
    criteria: dict,
) -> tuple[str, bool, str]:
    def regression_cap(key: str) -> float | None:
        value = criteria.get(key, 5.0)
        if isinstance(value, bool):
            return None
        try:
            limit = float(value)
        except (TypeError, ValueError):
            return None
        if not isfinite(limit) or limit < 0:
            return None
        return min(limit, 5.0)

    if not evidence_ready:
        return "collecting", False, "collecting"
    valid_ci = (
        ci_low is not None
        and ci_high is not None
        and isfinite(ci_low)
        and isfinite(ci_high)
        and ci_low <= ci_high
    )
    if not valid_ci:
        return "no_significant_difference", False, "no_significant_difference"
    if ci_high < 0:
        return (
            "validated_underperformance",
            False,
            "validated_underperformance",
        )
    minimum_improvement = max(
        5.0,
        float(criteria.get("minimum_relative_improvement_pct", 5.0)),
    )
    practical_win = (
        relative_improvement_pct is not None
        and isfinite(relative_improvement_pct)
        and relative_improvement_pct >= minimum_improvement
    )
    cohort_cap = regression_cap("maximum_single_cohort_regression_pct")
    segment_cap = regression_cap("maximum_segment_regression_pct")
    clean_cohorts = bool(cohort_regressions) and all(
        isfinite(value) and cohort_cap is not None and value <= cohort_cap
        for value in cohort_regressions
    )
    clean_segments = bool(segment_regressions) and all(
        isfinite(value) and segment_cap is not None and value <= segment_cap
        for value in segment_regressions
    )
    if (
        ci_low is not None
        and ci_low > 0
        and practical_win
        and clean_cohorts
        and clean_segments
        and top_k_non_regression
    ):
        if claim_eligible:
            return "validated_superiority", True, "validated_superiority"
        return "research_only", False, "validated_superiority"
    return "no_significant_difference", False, "no_significant_difference"


def _cohort_bootstrap_error_delta(
    cohort_deltas: list[np.ndarray],
    *,
    seed: int,
    resamples: int,
) -> dict:
    point = mean(float(values.mean()) for values in cohort_deltas)
    if len(cohort_deltas) < 2:
        return {"point": point, "low": None, "high": None}
    rng = np.random.default_rng(seed)
    draws = np.empty(resamples)
    for draw in range(resamples):
        cohort_picks = rng.integers(0, len(cohort_deltas), len(cohort_deltas))
        sampled_means = []
        for pick in cohort_picks:
            values = cohort_deltas[pick]
            player_picks = rng.integers(0, len(values), len(values))
            sampled_means.append(float(values[player_picks].mean()))
        draws[draw] = mean(sampled_means)
    low, high = np.percentile(draws, [2.5, 97.5])
    return {"point": point, "low": float(low), "high": float(high)}


def build_track(cohorts: list[dict], outcomes: dict[str, float], criteria: dict) -> dict:
    """Grade registered cohorts; missing evidence can never authorize a claim."""
    registered = sum(len(cohort.get("rows") or []) for cohort in cohorts)
    observed = 0
    resolved = []
    cohort_metrics = []
    completed_cohort_metrics = []
    completed_registered = 0
    cohort_error_deltas = []
    top_k_valucast = []
    top_k_competitor = []
    minimum_coverage = float(criteria["minimum_outcome_coverage"])

    for cohort in cohorts:
        scored = []
        for row in cohort.get("rows") or []:
            outcome_key = f"{cohort['cohort_id']}:{row['mlbam_id']}"
            outcome = outcomes.get(outcome_key)
            if isinstance(outcome, (int, float)):
                scored.append((row, float(outcome)))
        observed += len(scored)
        if not scored:
            continue

        cohort_registered = len(cohort.get("rows") or [])
        raw_coverage = len(scored) / cohort_registered
        cohort_metric = {
            "cohort_id": cohort["cohort_id"],
            "registered": cohort_registered,
            "resolved": len(scored),
            "coverage": round(raw_coverage, 4),
        }
        cohort_metrics.append(cohort_metric)
        if raw_coverage < minimum_coverage:
            continue

        actual = [value for _, value in scored]
        valucast_pct = _percentile_ranks(
            [float(row["valucast_rank"]) for row, _ in scored],
            higher_is_better=False,
        )
        competitor_pct = _percentile_ranks(
            [float(row["competitor_rank"]) for row, _ in scored],
            higher_is_better=False,
        )
        actual_pct = _percentile_ranks(actual, higher_is_better=True)
        valucast_errors = [abs(left - right) for left, right in zip(valucast_pct, actual_pct)]
        competitor_errors = [
            abs(left - right) for left, right in zip(competitor_pct, actual_pct)
        ]
        cohort_error_deltas.append(
            np.asarray(competitor_errors) - np.asarray(valucast_errors)
        )
        cohort_metric.update(
            {
                "valucast_error": mean(valucast_errors),
                "competitor_error": mean(competitor_errors),
                "regression_pct": _regression_pct(
                    mean(valucast_errors), mean(competitor_errors)
                ),
            }
        )
        completed_cohort_metrics.append(cohort_metric)
        completed_registered += cohort_registered
        top_k = min(int(criteria["top_k"]), len(scored))
        oracle_mean = mean(sorted(actual, reverse=True)[:top_k])
        valucast_selected = sorted(
            scored, key=lambda pair: (pair[0]["valucast_rank"], pair[0]["mlbam_id"])
        )[:top_k]
        competitor_selected = sorted(
            scored, key=lambda pair: (pair[0]["competitor_rank"], pair[0]["mlbam_id"])
        )[:top_k]
        top_k_valucast.append(oracle_mean - mean(value for _, value in valucast_selected))
        top_k_competitor.append(
            oracle_mean - mean(value for _, value in competitor_selected)
        )
        for index, (row, value) in enumerate(scored):
            resolved.append(
                {
                    "mlbam_id": row["mlbam_id"],
                    "role": row.get("role"),
                    "cohort_id": cohort["cohort_id"],
                    "actual": value,
                    "valucast_pct": valucast_pct[index],
                    "competitor_pct": competitor_pct[index],
                    "actual_pct": actual_pct[index],
                    "valucast_error": valucast_errors[index],
                    "competitor_error": competitor_errors[index],
                }
            )

    coverage = observed / registered if registered else 0.0
    completed_cohorts = len(completed_cohort_metrics)
    unique_players = len({row["mlbam_id"] for row in resolved})
    evidence_coverage = (
        len(resolved) / completed_registered if completed_registered else 0.0
    )
    minimum_players = max(
        MINIMUM_INDUSTRY_CLAIM_PLAYERS,
        int(criteria["minimum_unique_players"]),
    )
    evidence_ready = (
        completed_cohorts >= int(criteria["minimum_cohorts"])
        and unique_players >= minimum_players
        and evidence_coverage >= minimum_coverage
    )
    segments = []
    for role in sorted({row["role"] for row in resolved if row.get("role")}):
        role_rows = [row for row in resolved if row.get("role") == role]
        role_valucast = mean(row["valucast_error"] for row in role_rows)
        role_baseline = mean(row["competitor_error"] for row in role_rows)
        segments.append(
            {
                "role": role,
                "resolved": len(role_rows),
                "valucast_error": round(role_valucast, 6),
                "competitor_error": round(role_baseline, 6),
                "regression_pct": _regression_pct(role_valucast, role_baseline),
            }
        )
    base = {
        "status": "collecting",
        "statistical_status": "collecting",
        "claim_authorized": False,
        "coverage": {
            "registered": registered,
            "resolved": observed,
            "rate": round(coverage, 4),
            "completed_cohorts": completed_cohorts,
            "unique_players": unique_players,
        },
        "criteria": criteria,
        "primary": None,
        "confirmers": None,
        "cohorts": cohort_metrics,
        "segments": [],
    }
    if not resolved:
        return base

    valucast_primary_error = mean(
        row["valucast_error"] for row in completed_cohort_metrics
    )
    competitor_primary_error = mean(
        row["competitor_error"] for row in completed_cohort_metrics
    )
    ci = _cohort_bootstrap_error_delta(
        cohort_error_deltas,
        seed=int(criteria["bootstrap_seed"]),
        resamples=int(criteria["bootstrap_resamples"]),
    )
    relative_improvement_pct = _relative_improvement_pct(
        valucast_primary_error, competitor_primary_error
    )
    primary = {
        "metric": "ordinal_rank_error",
        "valucast_error": round(valucast_primary_error, 6),
        "competitor_error": round(competitor_primary_error, 6),
        "competitor_minus_valucast_error": round(ci["point"], 6),
        "relative_improvement_pct": (
            round(relative_improvement_pct, 6)
            if relative_improvement_pct is not None
            else None
        ),
        "error_delta_ci_low": (
            round(ci["low"], 6) if ci["low"] is not None else None
        ),
        "error_delta_ci_high": (
            round(ci["high"], 6) if ci["high"] is not None else None
        ),
        "bootstrap_cohorts": len(cohort_error_deltas),
        "bootstrap_players": unique_players,
    }
    confirmers = {
        "valucast_pairwise_concordance": _rank_concordance(
            [-row["valucast_pct"] for row in resolved],
            [row["actual"] for row in resolved],
        ),
        "competitor_pairwise_concordance": _rank_concordance(
            [-row["competitor_pct"] for row in resolved],
            [row["actual"] for row in resolved],
        ),
        "valucast_top_k_regret": round(mean(top_k_valucast), 6),
        "competitor_top_k_regret": round(mean(top_k_competitor), 6),
    }
    base["primary"] = primary
    base["confirmers"] = confirmers
    status, claim_authorized, statistical_status = _claim_decision(
        evidence_ready=evidence_ready,
        ci_low=ci["low"],
        ci_high=ci["high"],
        relative_improvement_pct=relative_improvement_pct,
        cohort_regressions=[
            row["regression_pct"] for row in completed_cohort_metrics
        ],
        segment_regressions=[row["regression_pct"] for row in segments],
        top_k_non_regression=(
            confirmers["valucast_top_k_regret"]
            <= confirmers["competitor_top_k_regret"]
        ),
        # This evaluator emits ordinal rank error, which is not an approved public
        # primary metric. Track-specific future evaluators call the same gate with
        # claim_eligible=True only for realized-value regret or forward rate error.
        claim_eligible=False,
        criteria=criteria,
    )
    base["segments"] = segments
    base["status"] = status
    base["claim_authorized"] = claim_authorized
    base["statistical_status"] = statistical_status
    return base
