"""Historical validation for ValuCast prospect league adapters.

The replay uses a fixed three-year outcome horizon. A test cohort is projected
only from cohorts whose entire three-year outcome window had closed before the
test year, preventing later MLB results from leaking into the fitted adapter.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.adapters import PRESETS, project_categories
from prospects.gate import decide_gate
from prospects.model import _prior_predict, _rank_concordance
from prospects.universal import (
    INPUT_PATH,
    MODEL_NAME,
    MODEL_VERSION,
    ROLE_THRESHOLDS,
    TARGET_SPECS,
    _base_historical_rows,
    _inverse_transform,
    _representative_season,
    _selected_prediction,
    load_input_contract,
    train_target,
)
from projections.league_adapter import projection_row, rank_projection_rows

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_adapter_backtest.json"
BACKTEST_VERSION = "0.1.0"
OUTCOME_HORIZON_YEARS = 3
OUTCOME_COMPLETE_THROUGH = 2025
MIN_GATE_SAMPLE = 250
MIN_GATE_IMPROVEMENT_PCT = 2.0


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


def _profile_from_models(
    row: dict,
    role: str,
    models: dict,
    source: str,
) -> dict:
    outcomes = {}
    for target_name, target_model in models.items():
        if source == "selected":
            normalized, prediction_source = _selected_prediction(
                target_model,
                {"level": row["level"], "age": row["age"]},
                row["features"],
                row["baseline_features"],
            )
        elif source == "level_age_prior":
            normalized = _prior_predict(target_model["_runtime"]["prior"], row)
            prediction_source = source
        else:
            raise ValueError(f"Unsupported backtest prediction source {source!r}")
        outcomes[target_name] = {
            "prediction": _inverse_transform(
                normalized, TARGET_SPECS[role][target_name]
            ),
            "prediction_source": prediction_source,
        }
    return {
        "mlbam_id": row["mlbam_id"],
        "role": role,
        "level": row["level"],
        "age": row["age"],
        "outcomes": outcomes,
    }


def _projected_row(profile: dict) -> dict:
    projected = project_categories(profile)
    role = profile["role"]
    volume = "PA" if role == "hitter" else "IP"
    return projection_row(
        player_id=profile["mlbam_id"],
        role=role,
        projected_volume=projected.get(volume, 0.0),
        categories={key: value for key, value in projected.items() if key != volume},
        mlbam_id=profile["mlbam_id"],
    )


def _actual_row(row: dict, role: str, seasons_by_player: dict) -> dict | None:
    season = _representative_season(row, role, seasons_by_player)
    sample_key = "pa" if role == "hitter" else "ip"
    sample = float((season or {}).get(sample_key) or 0.0)
    established = bool(season) and sample >= ROLE_THRESHOLDS[role]["established"]
    if not established:
        categories = {category: 0.0 for category in PRESETS["dd_7x7"][role]}
        return projection_row(
            player_id=row["mlbam_id"],
            role=role,
            projected_volume=0.0,
            categories=categories,
            mlbam_id=row["mlbam_id"],
        )
    if role == "hitter":
        fields = {
            "R": "r",
            "HR": "hr",
            "RBI": "rbi",
            "SB": "sb",
            "AVG": "avg",
            "OPS": "ops",
            "SO": "so",
        }
        categories = {
            category: season.get(field) for category, field in fields.items()
        }
    else:
        required = {
            "K": season.get("so"),
            "QS": season.get("qs"),
            "ERA": season.get("era"),
            "WHIP": season.get("whip"),
            "K/BB": season.get("k_bb"),
            "L": season.get("l"),
        }
        saves, holds = season.get("sv"), season.get("hld")
        required["SV+HLD"] = (
            None if saves is None or holds is None else float(saves) + float(holds)
        )
        categories = required
    if any(value is None for value in categories.values()):
        return None
    return projection_row(
        player_id=row["mlbam_id"],
        role=role,
        projected_volume=sample,
        categories=categories,
        mlbam_id=row["mlbam_id"],
    )


def _top_quartile_precision(predicted: list[float], actual: list[float]) -> float | None:
    if not predicted:
        return None
    size = max(1, len(predicted) // 4)
    predicted_top = set(
        sorted(range(len(predicted)), key=lambda index: predicted[index], reverse=True)[
            :size
        ]
    )
    actual_top = set(
        sorted(range(len(actual)), key=lambda index: actual[index], reverse=True)[
            :size
        ]
    )
    return len(predicted_top & actual_top) / size


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


def _score_fold(
    candidate_rows: list[dict],
    baseline_rows: list[dict],
    actual_rows: list[dict],
    role: str,
    *,
    include_category_diagnostics: bool = True,
) -> dict:
    config = PRESETS["dd_7x7"][role]
    actual_ids = {row["player_id"] for row in actual_rows}
    candidate_rows = [row for row in candidate_rows if row["player_id"] in actual_ids]
    baseline_rows = [row for row in baseline_rows if row["player_id"] in actual_ids]
    actual_rows = [row for row in actual_rows if row["player_id"] in actual_ids]

    def score_variant(variant: dict) -> dict:
        ranked = {
            "candidate": rank_projection_rows(candidate_rows, role, variant)["players"],
            "baseline": rank_projection_rows(baseline_rows, role, variant)["players"],
            "actual": rank_projection_rows(actual_rows, role, variant)["players"],
        }
        score_maps = {
            key: {row["player_id"]: row["adapter_score"] for row in rows}
            for key, rows in ranked.items()
        }
        ids = sorted(actual_ids)
        candidate = [score_maps["candidate"][player_id] for player_id in ids]
        baseline = [score_maps["baseline"][player_id] for player_id in ids]
        actual = [score_maps["actual"][player_id] for player_id in ids]
        return {
            "candidate_scores": candidate,
            "baseline_scores": baseline,
            "actual_scores": actual,
            "candidate_rank_concordance": _rank_concordance(candidate, actual),
            "baseline_rank_concordance": _rank_concordance(baseline, actual),
            "candidate_top_quartile_precision": _top_quartile_precision(
                candidate, actual
            ),
            "baseline_top_quartile_precision": _top_quartile_precision(
                baseline, actual
            ),
        }

    full = score_variant(config)
    diagnostics = {}
    if include_category_diagnostics:
        for category, weight in config.items():
            single = score_variant({category: weight})
            without = score_variant(
                {
                    other: other_weight
                    for other, other_weight in config.items()
                    if other != category
                }
            )
            diagnostics[category] = {
                "single_category": {
                    key: value
                    for key, value in single.items()
                    if not key.endswith("_scores")
                },
                "without_category": {
                    key: value
                    for key, value in without.items()
                    if not key.endswith("_scores")
                },
            }
    return {
        "sample_size": len(actual_ids),
        "category_diagnostics": diagnostics,
        **full,
    }


def _aggregate_category_diagnostics(folds: list[dict], role: str) -> dict:
    if not folds:
        return {}
    diagnostics = {}
    for category in PRESETS["dd_7x7"][role]:
        diagnostics[category] = {}
        for variant in ("single_category", "without_category"):
            diagnostics[category][variant] = {}
            for metric in (
                    "candidate_rank_concordance",
                    "baseline_rank_concordance",
                    "candidate_top_quartile_precision",
                    "baseline_top_quartile_precision",
            ):
                available = [
                    (
                        fold["category_diagnostics"][category][variant][metric],
                        fold["sample_size"],
                    )
                    for fold in folds
                    if fold["category_diagnostics"][category][variant][metric]
                    is not None
                ]
                diagnostics[category][variant][metric] = (
                    round(
                        sum(value * sample for value, sample in available)
                        / sum(sample for _, sample in available),
                        6,
                    )
                    if available
                    else None
                )
    return diagnostics


def _aggregate_target_ablation_diagnostics(
    folds: list[dict], role: str, full_metrics: dict
) -> dict:
    if not folds:
        return {}
    diagnostics = {}
    for target in TARGET_SPECS[role]:
        diagnostics[target] = {}
        for metric in (
            "candidate_rank_concordance",
            "candidate_top_quartile_precision",
        ):
            available = [
                (
                    fold["target_ablation_diagnostics"][target][metric],
                    fold["sample_size"],
                )
                for fold in folds
                if fold["target_ablation_diagnostics"][target][metric] is not None
            ]
            value = (
                sum(value * sample for value, sample in available)
                / sum(sample for _, sample in available)
                if available
                else None
            )
            diagnostics[target][metric] = (
                round(value, 6) if value is not None else None
            )
            diagnostics[target][f"{metric}_delta_vs_full"] = (
                round(value - full_metrics[metric], 6)
                if value is not None and full_metrics[metric] is not None
                else None
            )
    return diagnostics


def _role_backtest(contract: dict, horizon_seasons: dict, role: str, now: str) -> dict:
    historical = contract["historical"]["rows"]
    all_rows = _base_historical_rows(
        historical,
        role,
        mature_through=OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS,
    )
    cohorts = sorted({row["cohort_year"] for row in all_rows})
    folds = []
    for test_year in cohorts:
        train_through = test_year - OUTCOME_HORIZON_YEARS
        training_rows = [
            row
            for row in historical
            if int(row.get("cohort_year") or 9999) <= train_through
        ]
        test_rows = [row for row in all_rows if row["cohort_year"] == test_year]
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
            for target_name in TARGET_SPECS[role]
        }
        candidate_profiles = [
            _profile_from_models(row, role, models, "selected")
            for row in test_rows
        ]
        baseline_profiles = [
            _profile_from_models(row, role, models, "level_age_prior")
            for row in test_rows
        ]
        candidate_rows = [_projected_row(profile) for profile in candidate_profiles]
        baseline_rows = [_projected_row(profile) for profile in baseline_profiles]
        actual_rows = [
            actual
            for row in test_rows
            if (actual := _actual_row(row, role, horizon_seasons)) is not None
        ]
        fold = _score_fold(candidate_rows, baseline_rows, actual_rows, role)
        if not fold["sample_size"]:
            continue
        target_ablation_diagnostics = {}
        for target_name in TARGET_SPECS[role]:
            hybrid_rows = [
                _projected_row(
                    {
                        **candidate,
                        "outcomes": {
                            **candidate["outcomes"],
                            target_name: baseline["outcomes"][target_name],
                        },
                    }
                )
                for candidate, baseline in zip(
                    candidate_profiles, baseline_profiles
                )
            ]
            hybrid = _score_fold(
                hybrid_rows,
                baseline_rows,
                actual_rows,
                role,
                include_category_diagnostics=False,
            )
            target_ablation_diagnostics[target_name] = {
                "candidate_rank_concordance": hybrid[
                    "candidate_rank_concordance"
                ],
                "candidate_top_quartile_precision": hybrid[
                    "candidate_top_quartile_precision"
                ],
            }
        fold.pop("candidate_scores")
        fold.pop("baseline_scores")
        fold.pop("actual_scores")
        folds.append(
            {
                "test_cohort": test_year,
                "train_cohort_max": train_through,
                "candidate_sources": {
                    target: model["prediction_source"] or "level_age_prior"
                    for target, model in models.items()
                },
                "target_ablation_diagnostics": target_ablation_diagnostics,
                **{
                    key: round(value, 6) if isinstance(value, float) else value
                    for key, value in fold.items()
                },
            }
        )
    sample_size = sum(fold["sample_size"] for fold in folds)
    candidate_concordance = _weighted_fold_metric(
        folds, "candidate_rank_concordance"
    )
    baseline_concordance = _weighted_fold_metric(
        folds, "baseline_rank_concordance"
    )
    candidate_top_quartile = _weighted_fold_metric(
        folds, "candidate_top_quartile_precision"
    )
    baseline_top_quartile = _weighted_fold_metric(
        folds, "baseline_top_quartile_precision"
    )
    full_metrics = {
        "candidate_rank_concordance": candidate_concordance,
        "candidate_top_quartile_precision": candidate_top_quartile,
    }
    category_diagnostics = _aggregate_category_diagnostics(folds, role)
    target_ablation_diagnostics = _aggregate_target_ablation_diagnostics(
        folds, role, full_metrics
    )
    for fold in folds:
        fold.pop("category_diagnostics")
        fold.pop("target_ablation_diagnostics")
    gate = decide_gate(
        metric="dd_7x7_adapter_rank_concordance",
        model_score=candidate_concordance,
        baselines={"level_age_prior_adapter": baseline_concordance},
        sample_size=sample_size,
        cv_method="nested_fixed_horizon_cohort_walk_forward",
        validated_through=str(OUTCOME_COMPLETE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=False,
        now=now,
    )
    top_quartile_guard = decide_gate(
        metric="dd_7x7_adapter_top_quartile_precision",
        model_score=candidate_top_quartile,
        baselines={"level_age_prior_adapter": baseline_top_quartile},
        sample_size=sample_size,
        cv_method="nested_fixed_horizon_cohort_walk_forward",
        validated_through=str(OUTCOME_COMPLETE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=0.0,
        lower_is_better=False,
        now=now,
    )
    role_gate_active = (
        gate["status"] == "active" and top_quartile_guard["status"] == "active"
    )
    return {
        "role_research_gate": "active" if role_gate_active else "hold",
        "gate": gate,
        "top_quartile_guard": top_quartile_guard,
        "sample_size": sample_size,
        "fold_count": len(folds),
        "candidate_rank_concordance": (
            round(candidate_concordance, 6) if candidate_concordance is not None else None
        ),
        "baseline_rank_concordance": (
            round(baseline_concordance, 6) if baseline_concordance is not None else None
        ),
        "candidate_top_quartile_precision": (
            round(candidate_top_quartile, 6)
            if candidate_top_quartile is not None
            else None
        ),
        "baseline_top_quartile_precision": (
            round(baseline_top_quartile, 6)
            if baseline_top_quartile is not None
            else None
        ),
        "category_diagnostics": category_diagnostics,
        "target_ablation_diagnostics": target_ablation_diagnostics,
        "folds": folds,
    }


def build_backtest(contract: dict, now: str | None = None) -> dict:
    now = (
        now
        or contract.get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    horizon_seasons = _horizon_seasons(contract)
    roles = {
        role: _role_backtest(contract, horizon_seasons, role, now)
        for role in ("hitter", "pitcher")
    }
    adapter_gate_active = all(
        result["role_research_gate"] == "active" for result in roles.values()
    )
    return {
        "status": "shadow_only",
        "backtest_version": BACKTEST_VERSION,
        "universal_model_name": MODEL_NAME,
        "universal_model_version": MODEL_VERSION,
        "adapter_preset": "dd_7x7",
        "generated_at": now,
        "validation_contract": {
            "method": "nested_fixed_horizon_cohort_walk_forward",
            "outcome_horizon_years": OUTCOME_HORIZON_YEARS,
            "outcome_complete_through": OUTCOME_COMPLETE_THROUGH,
            "training_rule": (
                "A test cohort may use only training cohorts whose full outcome "
                "horizon closed before the test cohort."
            ),
            "candidate": (
                "Each target uses the method selected by gates fitted only inside "
                "the eligible training cohorts."
            ),
            "baseline": "Every target uses the factual level-age prior.",
            "actual": "DD 7x7 impact from the highest-volume MLB season inside the horizon.",
        },
        "roles": roles,
        "promotion": {
            "adapter_research_gate": (
                "active" if adapter_gate_active else "hold"
            ),
            "next_allowed_step": (
                "separate_dd_shadow_comparison"
                if adapter_gate_active
                else "improve_model_or_historical_evidence"
            ),
            "live_dd_value_influence": "blocked",
            "live_block_reason": (
                "Historical adapter evidence must pass for both roles, then dated "
                "forward archives must demonstrate stability before any capped influence."
            ),
            "feeds_live_dd_value": False,
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
        "adapter_research_gate": payload["promotion"]["adapter_research_gate"],
        "role_gates": {
            role: result["role_research_gate"]
            for role, result in payload["roles"].items()
        },
        "samples": {
            role: result["sample_size"] for role, result in payload["roles"].items()
        },
    }
