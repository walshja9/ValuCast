"""Fixed-horizon validation for the ValuCast Universal Prospect Index."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.dynasty_backtest import (
    OUTCOME_COMPLETE_THROUGH,
    OUTCOME_HORIZON_YEARS,
    PROBABILITY_TARGETS,
    _actual_distribution,
    _horizon_seasons,
    _predicted_distribution,
    build_backtest as build_dynasty_backtest,
)
from prospects.gate import decide_gate
from prospects.index import INDEX_NAME, INDEX_VERSION, index_score
from prospects.model import _rank_concordance
from prospects.universal import (
    INPUT_PATH,
    MODEL_NAME,
    MODEL_VERSION,
    _base_historical_rows,
    load_input_contract,
    train_target,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = (
    ROOT / "data" / "models" / "valucast_universal_prospect_index_backtest.json"
)
BACKTEST_VERSION = "0.1.0"
MIN_GATE_SAMPLE = 500
MIN_GATE_IMPROVEMENT_PCT = 2.0
MIN_FOLD_COUNT = 2


def _top_quartile_star_precision(predictions: list[float], actual: list[float]) -> float | None:
    """Tie-aware star precision in the predicted top quartile."""
    if not predictions:
        return None
    quota = max(1, len(predictions) // 4)
    groups = {}
    for index, prediction in enumerate(predictions):
        groups.setdefault(prediction, []).append(index)
    remaining = float(quota)
    stars = 0.0
    for prediction in sorted(groups, reverse=True):
        indices = groups[prediction]
        weight = min(1.0, remaining / len(indices))
        stars += weight * sum(actual[index] == 100.0 for index in indices)
        remaining -= weight * len(indices)
        if remaining <= 0:
            break
    return stars / quota


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


def _score_fold(candidate: list[float], baseline: list[float], actual: list[float]) -> dict:
    return {
        "sample_size": len(actual),
        "candidate_rank_concordance": _rank_concordance(candidate, actual),
        "baseline_rank_concordance": _rank_concordance(baseline, actual),
        "candidate_top_quartile_star_precision": _top_quartile_star_precision(
            candidate, actual
        ),
        "baseline_top_quartile_star_precision": _top_quartile_star_precision(
            baseline, actual
        ),
        "factual_star_count": sum(value == 100.0 for value in actual),
    }


def _temporal_stability_guard(folds: list[dict]) -> dict:
    rank_non_regression = all(
        fold["candidate_rank_concordance"] >= fold["baseline_rank_concordance"]
        for fold in folds
    )
    top_quartile_non_regression = all(
        fold["candidate_top_quartile_star_precision"]
        >= fold["baseline_top_quartile_star_precision"]
        for fold in folds
    )
    active = (
        len(folds) >= MIN_FOLD_COUNT
        and rank_non_regression
        and top_quartile_non_regression
    )
    return {
        "status": "active" if active else "hold",
        "minimum_fold_count": MIN_FOLD_COUNT,
        "fold_count": len(folds),
        "rank_non_regression_every_fold": rank_non_regression,
        "top_quartile_star_non_regression_every_fold": top_quartile_non_regression,
    }


def _combined_backtest(contract: dict, now: str) -> dict:
    historical = contract["historical"]["rows"]
    horizon_seasons = _horizon_seasons(contract)
    rows = sorted(
        [
            {**row, "role": role}
            for role in ("hitter", "pitcher")
            for row in _base_historical_rows(
                historical,
                role,
                mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS,
            )
        ],
        key=lambda row: (row["cohort_year"], row["role"], row["mlbam_id"]),
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
            role: {
                target_name: train_target(
                    role,
                    target_name,
                    training_rows,
                    horizon_seasons,
                    now=now,
                )
                for target_name in PROBABILITY_TARGETS
            }
            for role in ("hitter", "pitcher")
        }
        candidate = [
            index_score(_predicted_distribution(row, models[row["role"]], "selected"))
            for row in test_rows
        ]
        baseline = [
            index_score(
                _predicted_distribution(row, models[row["role"]], "level_age_prior")
            )
            for row in test_rows
        ]
        actual = [
            index_score(_actual_distribution(row, row["role"], horizon_seasons))
            for row in test_rows
        ]
        fold = _score_fold(candidate, baseline, actual)
        role_diagnostics = {}
        for role in ("hitter", "pitcher"):
            indices = [
                index for index, row in enumerate(test_rows) if row["role"] == role
            ]
            role_diagnostics[role] = _score_fold(
                [candidate[index] for index in indices],
                [baseline[index] for index in indices],
                [actual[index] for index in indices],
            )
        folds.append(
            {
                "test_cohort": test_year,
                "train_cohort_max": train_through,
                "candidate_sources": {
                    role: {
                        target: model["prediction_source"] or "level_age_prior"
                        for target, model in role_models.items()
                    }
                    for role, role_models in models.items()
                },
                "role_diagnostics": role_diagnostics,
                **{
                    key: round(value, 6) if isinstance(value, float) else value
                    for key, value in fold.items()
                },
            }
        )

    sample_size = sum(fold["sample_size"] for fold in folds)
    candidate_rank = _weighted_fold_metric(folds, "candidate_rank_concordance")
    baseline_rank = _weighted_fold_metric(folds, "baseline_rank_concordance")
    candidate_top = _weighted_fold_metric(
        folds, "candidate_top_quartile_star_precision"
    )
    baseline_top = _weighted_fold_metric(
        folds, "baseline_top_quartile_star_precision"
    )
    rank_gate = decide_gate(
        metric="universal_prospect_index_rank_concordance",
        model_score=candidate_rank,
        baselines={"level_age_outcome_index": baseline_rank},
        sample_size=sample_size,
        cv_method="nested_fixed_horizon_combined_cohort_walk_forward",
        validated_through=str(OUTCOME_COMPLETE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=False,
        now=now,
    )
    top_quartile_guard = decide_gate(
        metric="universal_prospect_index_top_quartile_star_precision",
        model_score=candidate_top,
        baselines={"level_age_outcome_index": baseline_top},
        sample_size=sample_size,
        cv_method="nested_fixed_horizon_combined_cohort_walk_forward",
        validated_through=str(OUTCOME_COMPLETE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=0.0,
        lower_is_better=False,
        now=now,
    )
    temporal_stability_guard = _temporal_stability_guard(folds)
    active = (
        rank_gate["status"] == "active"
        and top_quartile_guard["status"] == "active"
        and temporal_stability_guard["status"] == "active"
    )
    return {
        "combined_research_gate": "active" if active else "hold",
        "rank_gate": rank_gate,
        "top_quartile_guard": top_quartile_guard,
        "temporal_stability_guard": temporal_stability_guard,
        "sample_size": sample_size,
        "fold_count": len(folds),
        "candidate_rank_concordance": (
            round(candidate_rank, 6) if candidate_rank is not None else None
        ),
        "baseline_rank_concordance": (
            round(baseline_rank, 6) if baseline_rank is not None else None
        ),
        "candidate_top_quartile_star_precision": (
            round(candidate_top, 6) if candidate_top is not None else None
        ),
        "baseline_top_quartile_star_precision": (
            round(baseline_top, 6) if baseline_top is not None else None
        ),
        "folds": folds,
    }


def build_backtest(
    contract: dict,
    dynasty_backtest: dict | None = None,
    now: str | None = None,
) -> dict:
    now = now or contract.get("generated_at") or datetime.now(timezone.utc).isoformat()
    dynasty_backtest = dynasty_backtest or build_dynasty_backtest(contract, now=now)
    role_evidence_matches = (
        dynasty_backtest.get("universal_model_version") == MODEL_VERSION
        and dynasty_backtest.get("generated_at") == now
    )
    role_prerequisite = (
        (dynasty_backtest.get("promotion") or {}).get("dynasty_layer_research_gate")
        if role_evidence_matches
        else "hold"
    )
    combined = _combined_backtest(contract, now)
    active = (
        role_prerequisite == "active"
        and combined["combined_research_gate"] == "active"
    )
    return {
        "status": "shadow_only",
        "backtest_version": BACKTEST_VERSION,
        "index_name": INDEX_NAME,
        "index_version": INDEX_VERSION,
        "universal_model_name": MODEL_NAME,
        "universal_model_version": MODEL_VERSION,
        "generated_at": now,
        "validation_contract": {
            "method": "nested_fixed_horizon_combined_cohort_walk_forward",
            "outcome_horizon_years": OUTCOME_HORIZON_YEARS,
            "outcome_complete_through": OUTCOME_COMPLETE_THROUGH,
            "candidate": (
                "Gate-selected factual bust/role/star probabilities translated "
                "to the transparent Universal Prospect Index."
            ),
            "baseline": (
                "Role-specific factual level-age bust/role/star priors translated "
                "to the same index."
            ),
            "actual": "Factual bust=0, established role=50, star=100 inside the fixed horizon.",
            "primary_metric": "combined hitter/pitcher rank concordance",
            "top_of_board_guard": "tie-aware factual-star precision in the predicted top quartile",
            "temporal_stability_guard": (
                "Combined ordering and top-quartile star precision cannot regress "
                "in any eligible cohort."
            ),
            "role_distribution_prerequisite": (
                "The independent dynasty outcome-distribution backtest must pass "
                "for hitters and pitchers."
            ),
        },
        "combined": combined,
        "promotion": {
            "universal_index_research_gate": "active" if active else "hold",
            "role_distribution_prerequisite": role_prerequisite or "hold",
            "reason": (
                "Role distributions and the combined universal ordering passed all historical guards."
                if active
                else "The role-distribution prerequisite or a combined-board historical guard failed."
            ),
            "next_allowed_step": (
                "dated_forward_shadow_observation"
                if active
                else "improve_model_or_historical_evidence"
            ),
            "live_consumer": "blocked",
            "feeds_live_valucast_rank": False,
            "feeds_live_dd_value": False,
        },
    }


def run_backtest(
    input_path: Path = INPUT_PATH,
    dynasty_backtest_path: Path | None = None,
    artifact_path: Path = ARTIFACT_PATH,
    now: str | None = None,
) -> dict:
    dynasty_backtest = (
        json.loads(dynasty_backtest_path.read_text(encoding="utf-8"))
        if dynasty_backtest_path and dynasty_backtest_path.exists()
        else None
    )
    payload = build_backtest(
        load_input_contract(input_path),
        dynasty_backtest=dynasty_backtest,
        now=now,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "research_gate": payload["promotion"]["universal_index_research_gate"],
        "combined_gate": payload["combined"]["combined_research_gate"],
        "sample_size": payload["combined"]["sample_size"],
        "fold_count": payload["combined"]["fold_count"],
    }
