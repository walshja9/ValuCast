"""Fixed-horizon validation for the prospect dynasty ceiling/risk layer."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

from prospects.dynasty import LAYER_NAME, LAYER_VERSION, coherent_distribution
from prospects.gate import decide_gate
from prospects.model import _prior_predict, _rank_concordance
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
BACKTEST_VERSION = "0.1.0"
OUTCOME_HORIZON_YEARS = 4
OUTCOME_COMPLETE_THROUGH = 2025
MIN_GATE_SAMPLE = 250
MIN_GATE_IMPROVEMENT_PCT = 2.0
MIN_FOLD_COUNT = 2
PROBABILITY_TARGETS = ("established_probability", "star_probability")


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


def _role_backtest(contract: dict, horizon_seasons: dict, role: str, now: str) -> dict:
    historical = contract["historical"]["rows"]
    rows = _base_historical_rows(
        historical,
        role,
        mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS,
    )
    folds = []
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
        fold = _score_fold(
            [
                _predicted_distribution(row, models, "selected")
                for row in test_rows
            ],
            [
                _predicted_distribution(row, models, "level_age_prior")
                for row in test_rows
            ],
            [_actual_distribution(row, role, horizon_seasons) for row in test_rows],
        )
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
        "folds": folds,
    }


def build_backtest(contract: dict, now: str | None = None) -> dict:
    now = now or contract.get("generated_at") or datetime.now(timezone.utc).isoformat()
    horizon_seasons = _horizon_seasons(contract)
    roles = {
        role: _role_backtest(contract, horizon_seasons, role, now)
        for role in ("hitter", "pitcher")
    }
    active = all(result["role_research_gate"] == "active" for result in roles.values())
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
                "Four years is the longest closed horizon supported by the current "
                "2015-2022 historical cohort coverage with at least one prior "
                "training cohort."
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
) -> dict:
    payload = build_backtest(load_input_contract(input_path), now=now)
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
