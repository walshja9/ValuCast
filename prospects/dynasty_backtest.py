"""Fixed-horizon validation for the prospect dynasty ceiling/risk layer."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import numpy as np

from prospects.dynasty import LAYER_NAME, LAYER_VERSION, coherent_distribution
from prospects.gate import decide_gate
from prospects.model import PRIOR_K, _age_bucket, _prior_predict, _rank_concordance
from prospects.model import _historical_rows as _outcome_historical_rows
from prospects.outcome_oof import ARTIFACT_PATH as OUTCOME_OOF_PATH
from prospects.outcome_oof import validate_outcome_oof_artifact
from prospects.universal import (
    INPUT_PATH,
    MODEL_NAME,
    MODEL_VERSION,
    _base_historical_rows,
    _raw_target,
    _selected_prediction,
    load_input_contract,
    train_target,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_dynasty_backtest.json"
# The served combined outcome-score MAE gate (build_shadow_model -> board_gate).
# FIX 1: the headline claims to certify THIS gate, so it must load the served
# baseline name + improvement_pct and refuse to publish on a silent divergence.
SERVED_MODEL_PATH = ROOT / "data" / "models" / "valucast_prospect_model.json"
BACKTEST_VERSION = "0.1.0"
OUTCOME_HORIZON_YEARS = 4
OUTCOME_COMPLETE_THROUGH = 2025
MIN_GATE_SAMPLE = 250
MIN_GATE_IMPROVEMENT_PCT = 2.0
MIN_FOLD_COUNT = 2
PROBABILITY_TARGETS = ("established_probability", "star_probability")

# R1/R2 (senior-mathematician audit): the per-role gate deltas and the combined
# outcome-score MAE delta ship as naked point estimates. Attach a paired case
# (player) bootstrap 95% CI so each headline delta is provable. Each player
# appears once in the walk-forward, so this is an ordinary nonparametric case
# bootstrap (no within-player correlation to preserve). Reporting-only: the
# bootstrap never touches a gate decision, a served score, or PRIOR_K. Seed is
# fixed and documented; the CI is two-sided percentile at 95%.
CI_BOOTSTRAP_SEED = 28014
CI_BOOTSTRAPS = 10_000
CI_ALPHA = 0.05
_LOAD_COMMITTED_OOF = object()  # sentinel: fall back to the committed OOF file
_LOAD_SERVED_GATE = object()  # sentinel: fall back to the committed served board_gate
_DIRECTIONAL_LABEL = "directional (CI includes 0)"
_SIGNIFICANT_LABEL = "significant"
_PRIOR_K_QUALIFIER = "vs un-tuned K=40 prior"


def _horizon_seasons(contract: dict) -> dict:
    cohort_by_key = {}
    for role in ("hitter", "pitcher"):
        for row in _base_historical_rows(
            contract["historical"]["rows"],
            role,
            mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS,
        ):
            cohort_by_key[f"{row['mlbam_id']}_{role}"] = row["cohort_year"]
    return {
        key: [
            season
            for season in seasons
            if int(season.get("year") or 0)
            <= cohort_by_key.get(key, -9999) + OUTCOME_HORIZON_YEARS
        ]
        for key, seasons in contract["historical_mlb_seasons"].items()
        if key in cohort_by_key
    }


def _predicted_distribution(row: dict, models: dict, source: str) -> dict:
    probabilities = {}
    for target_name in PROBABILITY_TARGETS:
        target_model = models[target_name]
        if source == "selected":
            prediction, _ = _selected_prediction(
                target_model,
                {"level": row["level"], "age": row["age"]},
                row["features"],
                row["baseline_features"],
            )
        elif source == "level_age_prior":
            prediction = _prior_predict(target_model["_runtime"]["prior"], row)
        else:
            raise ValueError(f"Unsupported dynasty backtest source {source!r}")
        probabilities[target_name] = prediction
    return coherent_distribution(
        probabilities["established_probability"],
        probabilities["star_probability"],
    )


def _actual_distribution(row: dict, role: str, seasons_by_player: dict) -> dict:
    established = _raw_target(
        row, role, "established_probability", seasons_by_player
    )
    star = _raw_target(row, role, "star_probability", seasons_by_player)
    return coherent_distribution(established, star)


def _expected_tier(distribution: dict) -> float:
    return distribution["role_probability"] + 2.0 * distribution["star_probability"]


def _multiclass_brier(predicted: list[dict], actual: list[dict]) -> float | None:
    if not actual:
        return None
    return mean(
        sum((prediction[key] - outcome[key]) ** 2 for key in outcome)
        for prediction, outcome in zip(predicted, actual)
    )


def _score_fold(candidate: list[dict], baseline: list[dict], actual: list[dict]) -> dict:
    candidate_tiers = [_expected_tier(distribution) for distribution in candidate]
    baseline_tiers = [_expected_tier(distribution) for distribution in baseline]
    actual_tiers = [_expected_tier(distribution) for distribution in actual]
    return {
        "sample_size": len(actual),
        "candidate_multiclass_brier": _multiclass_brier(candidate, actual),
        "baseline_multiclass_brier": _multiclass_brier(baseline, actual),
        "candidate_rank_concordance": _rank_concordance(candidate_tiers, actual_tiers),
        "baseline_rank_concordance": _rank_concordance(baseline_tiers, actual_tiers),
    }


def _weighted_fold_metric(folds: list[dict], metric: str) -> float | None:
    available = [
        (fold[metric], fold["sample_size"])
        for fold in folds
        if fold.get(metric) is not None and fold["sample_size"]
    ]
    if not available:
        return None
    return sum(value * sample for value, sample in available) / sum(
        sample for _, sample in available
    )


def _temporal_stability_guard(folds: list[dict]) -> dict:
    brier_non_regression = all(
        fold["candidate_multiclass_brier"] <= fold["baseline_multiclass_brier"]
        for fold in folds
    )
    ordering_non_regression = all(
        fold["candidate_rank_concordance"] >= fold["baseline_rank_concordance"]
        for fold in folds
    )
    active = (
        len(folds) >= MIN_FOLD_COUNT
        and brier_non_regression
        and ordering_non_regression
    )
    return {
        "status": "active" if active else "hold",
        "minimum_fold_count": MIN_FOLD_COUNT,
        "fold_count": len(folds),
        "distribution_non_regression_every_fold": brier_non_regression,
        "ordering_non_regression_every_fold": ordering_non_regression,
    }


def _delta_pct(candidate: np.ndarray, baseline: np.ndarray, lower_is_better: bool) -> float:
    """Percent improvement of candidate over baseline on a per-item error array.

    Mirrors gate.decide_gate: for a lower-is-better metric the improvement is
    (baseline - candidate) / |baseline| * 100 on the pooled means.
    """
    candidate_mean = float(candidate.mean())
    baseline_mean = float(baseline.mean())
    if baseline_mean == 0:
        return 0.0
    if lower_is_better:
        return (baseline_mean - candidate_mean) / abs(baseline_mean) * 100.0
    return (candidate_mean - baseline_mean) / abs(baseline_mean) * 100.0


def _cluster_bootstrap_delta_ci(
    candidate: np.ndarray,
    baseline: np.ndarray,
    cluster_ids: np.ndarray,
    *,
    lower_is_better: bool = True,
    seed: int = CI_BOOTSTRAP_SEED,
    n_bootstraps: int = CI_BOOTSTRAPS,
) -> dict:
    """Paired case (player) bootstrap 95% CI on the delta%.

    candidate/baseline: per-item metric contributions (e.g. per-player Brier or
    absolute error), paired index-for-index. cluster_ids: the player id per item.
    Each player appears exactly once in the walk-forward (sample_size ==
    cluster_count), so resampling the cluster ids with replacement is an ordinary
    nonparametric case (player) bootstrap -- there is no within-player
    correlation to preserve. Registered procedure: seed 28014, two-sided
    percentile 95%. Reporting-only -- no gate reads this.
    """
    point = _delta_pct(candidate, baseline, lower_is_better)
    unique, inverse = np.unique(cluster_ids, return_inverse=True)
    members = [np.flatnonzero(inverse == index) for index in range(len(unique))]
    cluster_count = len(unique)
    if cluster_count < 2:
        return {
            "point": round(point, 4),
            "ci_low": None,
            "ci_high": None,
            "n_bootstraps": n_bootstraps,
            "seed": seed,
            "cluster_count": cluster_count,
            "significance": _DIRECTIONAL_LABEL,
        }
    rng = np.random.default_rng(seed)
    deltas = np.empty(n_bootstraps)
    for draw in range(n_bootstraps):
        picks = rng.integers(0, cluster_count, cluster_count)
        index = np.concatenate([members[pick] for pick in picks])
        deltas[draw] = _delta_pct(candidate[index], baseline[index], lower_is_better)
    low, high = np.percentile(deltas, [100 * CI_ALPHA / 2, 100 * (1 - CI_ALPHA / 2)])
    significant = low > 0.0 or high < 0.0
    return {
        "point": round(point, 4),
        "ci_low": round(float(low), 4),
        "ci_high": round(float(high), 4),
        "n_bootstraps": n_bootstraps,
        "seed": seed,
        "cluster_count": cluster_count,
        "significance": _SIGNIFICANT_LABEL if significant else _DIRECTIONAL_LABEL,
    }


def _role_brier_delta_ci(
    test_rows: list[dict],
    candidate: list[dict],
    baseline: list[dict],
    actual: list[dict],
) -> dict:
    """Per-role multiclass-Brier delta CI, clustered by player (R1/R2)."""
    cand = np.array(
        [sum((c[k] - a[k]) ** 2 for k in a) for c, a in zip(candidate, actual)]
    )
    base = np.array(
        [sum((b[k] - a[k]) ** 2 for k in a) for b, a in zip(baseline, actual)]
    )
    cluster_ids = np.array([int(row["mlbam_id"]) for row in test_rows])
    ci = _cluster_bootstrap_delta_ci(cand, base, cluster_ids, lower_is_better=True)
    return {"metric": "dynasty_outcome_distribution_multiclass_brier", **ci}


_CERTIFY_IMPROVEMENT_TOL = 0.01  # pct points; served/headline agree to <0.01%


def _combined_mae_headline_from_oof(
    oof_payload: dict, served_gate: dict | None = None
) -> dict:
    """Combined outcome-score MAE delta + CI, sourced from the R6 OOF artifact.

    The pooled outcome-score MAE gate ('model beats the neighbors baseline OOS')
    is the citable headline. It lives in the outcome-score layer, whose committed
    per-player OOF (valucast_outcome_oof_scores.json) is the auditable source.

    FIX 1 (certification guard): the served board_gate (build_shadow_model)
    selects the lower-MAE baseline among THREE candidates -- level_age_prior,
    historical_neighbors_25, canonical_historical_neighbors_25. The OOF stores
    only prior + neighbor errors, so this re-selection is a min of TWO. Today both
    pick historical_neighbors_25, but nothing structural forces it. We therefore
    load the served baseline name + improvement_pct and set certifies_served_gate
    only when the headline's baseline and delta match the served gate. On a
    mismatch the headline is degraded (source_available=false) so the artifact can
    never publish a number that silently diverges from the served gate it claims
    to certify.
    """
    problems = validate_outcome_oof_artifact(oof_payload)
    if problems:
        raise ValueError("outcome OOF artifact invalid: " + "; ".join(problems))
    rows = oof_payload["rows"]
    target = np.array([row["target"] for row in rows])
    model_error = np.abs(np.array([row["model_prediction"] for row in rows]) - target)
    prior_error = np.abs(np.array([row["prior_prediction"] for row in rows]) - target)
    neighbor_error = np.abs(
        np.array([row["neighbor_prediction"] for row in rows]) - target
    )
    baselines = {
        "level_age_prior": prior_error,
        "historical_neighbors_25": neighbor_error,
    }
    # gate.pick_baseline chooses the lower pooled mean (lower MAE is better).
    baseline_name = min(baselines, key=lambda name: float(baselines[name].mean()))
    cluster_ids = np.array([f"{row['role']}:{row['mlbam_id']}" for row in rows])
    ci = _cluster_bootstrap_delta_ci(
        model_error, baselines[baseline_name], cluster_ids, lower_is_better=True
    )
    served_baseline = (served_gate or {}).get("baseline")
    served_improvement = (served_gate or {}).get("improvement_pct")
    certifies = (
        served_gate is not None
        and served_baseline == baseline_name
        and isinstance(served_improvement, (int, float))
        and abs(float(served_improvement) - ci["point"]) <= _CERTIFY_IMPROVEMENT_TOL
    )
    headline = {
        "source_available": bool(certifies),
        "metric": "outcome_score_mae",
        "layer": "outcome_score",
        "baseline": baseline_name,
        "prior_k_qualifier_applies": baseline_name == "level_age_prior",
        "source_artifact": "data/models/valucast_outcome_oof_scores.json",
        "sample_size": len(rows),
        # certification against the served board_gate (FIX 1)
        "served_gate_baseline": served_baseline,
        "served_gate_improvement_pct": served_improvement,
        "headline_baseline": baseline_name,
        "headline_improvement_pct": ci["point"],
        "certifies_served_gate": bool(certifies),
        **ci,
    }
    if not certifies:
        headline["certification_note"] = (
            "headline baseline/delta does not match the served board_gate "
            "(data/models/valucast_prospect_model.json); not certifying the "
            "served headline"
        )
    return headline


def _eb_optimal_prior_k(dataset_rows: list[dict]) -> dict:
    """Empirical-Bayes-optimal shrinkage K for the level-age prior (R5).

    _fit_prior shrinks a level-age cell rate toward the overall rate with
      p_hat = (sum + overall*K) / (n + K),
    i.e. a Beta(overall*K, (1-overall)*K) prior. The EB-optimal concentration
    K = alpha + beta matches the between-cell dispersion of the observed cell
    rates. We estimate it with a DerSimonian-Laird moment estimator of the
    intra-cell correlation rho on the binary 'reached role-or-better' outcome
    (target > 0), pooled across roles and cohorts, then K = (1 - rho) / rho.
    This is a DIAGNOSTIC ONLY: PRIOR_K is not changed.
    """
    counts: list[float] = []
    successes: list[float] = []
    for role in ("hitter", "pitcher"):
        cells: dict[str, list[int]] = {}
        for row in _outcome_historical_rows(dataset_rows, role):
            key = f"{role}|{row['level']}|{_age_bucket(row['age'])}"
            cells.setdefault(key, []).append(1 if row["target"] > 0 else 0)
        for values in cells.values():
            if len(values) >= 2:
                counts.append(len(values))
                successes.append(sum(values))
    if len(counts) < 2:
        return {
            "current": PRIOR_K,
            "eb_optimal_estimate": None,
            "note": (
                "prior baseline is un-tuned; prior-relative deltas overstate "
                "edge -- cite neighbors-baseline or combined numbers"
            ),
        }
    n = np.array(counts)
    k = np.array(successes)
    total = float(n.sum())
    pooled = float(k.sum() / total)
    rates = k / n
    cells_count = len(n)
    denom = pooled * (1.0 - pooled)
    estimate = None
    rho_value = None
    if denom > 0:
        statistic = float(np.sum(n * (rates - pooled) ** 2) / denom)
        spread = total - float(np.sum(n**2)) / total
        rho = (statistic - (cells_count - 1)) / max(spread - (cells_count - 1), 1e-9)
        rho = min(max(rho, 1e-6), 1.0 - 1e-6)
        rho_value = round(rho, 6)
        estimate = round((1.0 - rho) / rho, 3)
    return {
        "current": PRIOR_K,
        "eb_optimal_estimate": estimate,
        "estimator": "dersimonian_laird_intra_cell_correlation",
        "outcome": "reached_role_or_better",
        "cell_count": cells_count,
        "pooled_rate": round(pooled, 6),
        "intra_cell_correlation": rho_value,
        "note": (
            "prior baseline is un-tuned; prior-relative deltas overstate edge "
            "-- cite neighbors-baseline or combined numbers"
        ),
    }


def _role_backtest(contract: dict, horizon_seasons: dict, role: str, now: str) -> dict:
    historical = contract["historical"]["rows"]
    rows = _base_historical_rows(
        historical,
        role,
        mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS,
    )
    folds = []
    ci_rows: list[dict] = []
    ci_candidate: list[dict] = []
    ci_baseline: list[dict] = []
    ci_actual: list[dict] = []
    for test_year in sorted({row["cohort_year"] for row in rows}):
        train_through = test_year - OUTCOME_HORIZON_YEARS
        training_rows = [
            row
            for row in historical
            if int(row.get("cohort_year") or 9999) <= train_through
        ]
        test_rows = [row for row in rows if row["cohort_year"] == test_year]
        if not training_rows or not test_rows:
            continue
        models = {
            target_name: train_target(
                role,
                target_name,
                training_rows,
                horizon_seasons,
                now=now,
            )
            for target_name in PROBABILITY_TARGETS
        }
        candidate = [
            _predicted_distribution(row, models, "selected") for row in test_rows
        ]
        baseline = [
            _predicted_distribution(row, models, "level_age_prior")
            for row in test_rows
        ]
        actual = [
            _actual_distribution(row, role, horizon_seasons) for row in test_rows
        ]
        # Retain per-player paired distributions for the reporting-only CI
        # (R1/R2). This is the identical candidate/baseline/actual triple the
        # fold score consumes -- no separate scoring path.
        ci_rows.extend(test_rows)
        ci_candidate.extend(candidate)
        ci_baseline.extend(baseline)
        ci_actual.extend(actual)
        fold = _score_fold(candidate, baseline, actual)
        folds.append(
            {
                "test_cohort": test_year,
                "train_cohort_max": train_through,
                "candidate_sources": {
                    target: model["prediction_source"] or "level_age_prior"
                    for target, model in models.items()
                },
                **{
                    key: round(value, 6) if isinstance(value, float) else value
                    for key, value in fold.items()
                },
            }
        )

    sample_size = sum(fold["sample_size"] for fold in folds)
    candidate_brier = _weighted_fold_metric(folds, "candidate_multiclass_brier")
    baseline_brier = _weighted_fold_metric(folds, "baseline_multiclass_brier")
    candidate_rank = _weighted_fold_metric(folds, "candidate_rank_concordance")
    baseline_rank = _weighted_fold_metric(folds, "baseline_rank_concordance")
    gate = decide_gate(
        metric="dynasty_outcome_distribution_multiclass_brier",
        model_score=candidate_brier,
        baselines={"level_age_prior_distribution": baseline_brier},
        sample_size=sample_size,
        cv_method="nested_fixed_horizon_cohort_walk_forward",
        validated_through=str(OUTCOME_COMPLETE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=True,
        now=now,
    )
    ordering_guard = decide_gate(
        metric="dynasty_expected_outcome_tier_rank_concordance",
        model_score=candidate_rank,
        baselines={"level_age_prior_distribution": baseline_rank},
        sample_size=sample_size,
        cv_method="nested_fixed_horizon_cohort_walk_forward",
        validated_through=str(OUTCOME_COMPLETE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=0.0,
        lower_is_better=False,
        now=now,
    )
    temporal_stability_guard = _temporal_stability_guard(folds)
    active = (
        gate["status"] == "active"
        and ordering_guard["status"] == "active"
        and temporal_stability_guard["status"] == "active"
    )
    # R1/R2/R5: reporting-only CI on the per-role Brier delta. The gate's
    # baseline is the level-age (K=40) prior distribution, so this delta is
    # prior-relative and carries the un-tuned-K qualifier (R5). The CI never
    # feeds the gate decision above.
    brier_delta_ci = {
        **_role_brier_delta_ci(ci_rows, ci_candidate, ci_baseline, ci_actual),
        "baseline": "level_age_prior_distribution",
        "delta_baseline_qualifier": _PRIOR_K_QUALIFIER,
        "gate_point_improvement_pct": gate.get("improvement_pct"),
    }
    return {
        "role_research_gate": "active" if active else "hold",
        "gate": gate,
        "ordering_guard": ordering_guard,
        "temporal_stability_guard": temporal_stability_guard,
        "sample_size": sample_size,
        "fold_count": len(folds),
        "candidate_multiclass_brier": (
            round(candidate_brier, 6) if candidate_brier is not None else None
        ),
        "baseline_multiclass_brier": (
            round(baseline_brier, 6) if baseline_brier is not None else None
        ),
        "candidate_rank_concordance": (
            round(candidate_rank, 6) if candidate_rank is not None else None
        ),
        "baseline_rank_concordance": (
            round(baseline_rank, 6) if baseline_rank is not None else None
        ),
        "brier_delta_ci": brier_delta_ci,
        "folds": folds,
    }


def _combined_headline(
    outcome_oof: dict | None, served_gate: dict | None = None
) -> dict:
    """Citable combined outcome-score MAE headline (R2). Degrades gracefully.

    outcome_oof is the R6 per-player OOF payload. When it is missing (e.g. a
    synthetic unit-test contract with no committed OOF file) the headline still
    exists but carries nulls and source_available=False, so the artifact schema
    is stable without forcing every caller to have the committed OOF on disk.

    served_gate is the served board_gate (build_shadow_model) the headline claims
    to certify (FIX 1). When it is missing, or the headline's baseline/delta do
    not match it, the headline degrades (source_available=false) rather than
    publish a number that silently diverges from the served gate.
    """
    if outcome_oof is None:
        return {
            "source_available": False,
            "metric": "outcome_score_mae",
            "layer": "outcome_score",
            "point": None,
            "ci_low": None,
            "ci_high": None,
            "significance": _DIRECTIONAL_LABEL,
            "certifies_served_gate": False,
            "note": (
                "combined outcome-score MAE headline requires the committed "
                "outcome OOF artifact (data/models/valucast_outcome_oof_scores.json)"
            ),
        }
    return _combined_mae_headline_from_oof(outcome_oof, served_gate)


def _load_outcome_oof() -> dict | None:
    try:
        return json.loads(OUTCOME_OOF_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _load_served_board_gate() -> dict | None:
    """Load the served combined outcome-score MAE gate (board_gate) or None.

    The headline certifies THIS gate (FIX 1). Reading it from the committed
    served model keeps the certification honest and file-driven; a missing or
    malformed served model simply blocks certification (headline degrades).
    """
    try:
        served = json.loads(SERVED_MODEL_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    gate = served.get("board_gate")
    return gate if isinstance(gate, dict) else None


def build_backtest(
    contract: dict,
    now: str | None = None,
    *,
    outcome_oof: dict | None = None,
    served_gate: dict | None = None,
) -> dict:
    now = now or contract.get("generated_at") or datetime.now(timezone.utc).isoformat()
    horizon_seasons = _horizon_seasons(contract)
    roles = {
        role: _role_backtest(contract, horizon_seasons, role, now)
        for role in ("hitter", "pitcher")
    }
    active = all(result["role_research_gate"] == "active" for result in roles.values())
    combined_headline = _combined_headline(outcome_oof, served_gate)
    prior_k_diagnostic = _eb_optimal_prior_k(contract["historical"]["rows"])
    return {
        "status": "shadow_only",
        "backtest_version": BACKTEST_VERSION,
        "layer_name": LAYER_NAME,
        "layer_version": LAYER_VERSION,
        "universal_model_name": MODEL_NAME,
        "universal_model_version": MODEL_VERSION,
        "generated_at": now,
        "validation_contract": {
            "method": "nested_fixed_horizon_cohort_walk_forward",
            "outcome_horizon_years": OUTCOME_HORIZON_YEARS,
            "outcome_complete_through": OUTCOME_COMPLETE_THROUGH,
            "horizon_reason": (
                "Four years is the longest closed horizon currently supported "
                "with at least one prior training cohort."
            ),
            "candidate": (
                "Gate-selected factual establishment and star probabilities "
                "combined into a coherent bust/role/star distribution."
            ),
            "baseline": (
                "Factual level-age priors for establishment and star probability."
            ),
            "actual": (
                "One-hot factual bust/role/star outcome inside the fixed horizon."
            ),
            "primary_metric": "multiclass Brier score",
            "guard": "expected factual outcome tier rank concordance cannot regress",
            "temporal_stability_guard": (
                "At least two eligible test cohorts; distribution and ordering "
                "cannot regress in any fold."
            ),
        },
        "roles": roles,
        "combined_headline": combined_headline,
        "prior_k_diagnostic": prior_k_diagnostic,
        "reporting_only_statistics": {
            "note": (
                "combined_headline, per-role brier_delta_ci, and prior_k_diagnostic "
                "are additive reporting fields (senior-mathematician audit R1/R2/R5). "
                "They make the existing gate deltas provable and DO NOT feed any "
                "gate decision, served score, or PRIOR_K."
            ),
            "bootstrap_seed": CI_BOOTSTRAP_SEED,
            "bootstrap_draws": CI_BOOTSTRAPS,
            "ci_two_sided_alpha": CI_ALPHA,
            "cluster_unit": "player_mlbam_id",
        },
        "promotion": {
            "dynasty_layer_research_gate": "active" if active else "hold",
            "reason": (
                "Both role distributions beat level-age priors without aggregate "
                "or fold-level ordering/distribution regression."
                if active
                else "At least one role failed the distribution, ordering, or temporal-stability guard."
            ),
            "next_allowed_step": (
                "dated_forward_shadow_observation"
                if active
                else "improve_model_or_historical_evidence"
            ),
            "live_consumer": "blocked",
            "feeds_live_dd_value": False,
            "feeds_live_valucast_rank": False,
        },
    }


def run_backtest(
    input_path: Path = INPUT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    now: str | None = None,
    outcome_oof=_LOAD_COMMITTED_OOF,
    served_gate=_LOAD_SERVED_GATE,
) -> dict:
    if outcome_oof is _LOAD_COMMITTED_OOF:
        outcome_oof = _load_outcome_oof()
    if served_gate is _LOAD_SERVED_GATE:
        served_gate = _load_served_board_gate()
    payload = build_backtest(
        load_input_contract(input_path),
        now=now,
        outcome_oof=outcome_oof,
        served_gate=served_gate,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "research_gate": payload["promotion"]["dynasty_layer_research_gate"],
        "role_gates": {
            role: result["role_research_gate"]
            for role, result in payload["roles"].items()
        },
        "samples": {
            role: result["sample_size"] for role, result in payload["roles"].items()
        },
    }
