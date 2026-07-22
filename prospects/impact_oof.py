"""Research-only fold-local audit for the prospect impact model.

This module deliberately does not participate in model fitting for serving, rank
construction, value calculation, publication, or promotion decisions.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from statistics import mean

import numpy as np

from prospects.model import (
    HITTER_IMPACT_RIDGE_LAMBDA,
    IMPACT_CATEGORIES,
    MATURE_THROUGH,
    IMPACT_REFERENCE_MIN,
    NEIGHBOR_K,
    OUTCOME_HORIZON_YEARS,
    RIDGE_LAMBDA,
    _active_impact_categories,
    _fit_neighbors,
    _fit_prediction_model,
    _fit_prior,
    _historical_impact_rows,
    _impact_references,
    _neighbor_predict,
    _predict_model,
    _prior_predict,
)

SCHEMA_VERSION = "valucast_impact_oof_audit_v1"
DEFAULT_BOOTSTRAP_SEED = 72127
DEFAULT_BOOTSTRAP_RESAMPLES = 5000
BASELINES = {
    "level_age_prior": "prior_error",
    "historical_neighbors_25": "neighbor_error",
    "canonical_historical_neighbors_25": "canonical_neighbor_error",
}


def _canonical_sha256(payload) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _round(value: float) -> float:
    return round(float(value), 12)


def _eligible_templates(dataset_rows: list[dict], role: str) -> list[dict]:
    empty_references = _impact_references({})
    return _historical_impact_rows(
        dataset_rows,
        role,
        seasons_by_player={},
        references=empty_references,
    )


def _fold_reference_contract(
    templates: list[dict],
    role: str,
    seasons_by_player: dict,
    test_year: int,
) -> dict:
    training = [row for row in templates if row["cohort_year"] < test_year]
    filtered = {}
    sample_key = "pa" if role == "hitter" else "ip"
    minimum_sample = IMPACT_REFERENCE_MIN[role]
    for row in training:
        key = f"{row['mlbam_id']}_{role}"
        cohort_year = int(row["cohort_year"])
        seasons = []
        for season in seasons_by_player.get(key, []):
            try:
                season_year = int(season.get("year") or 0)
                sample = float(season.get(sample_key) or 0.0)
            except (TypeError, ValueError):
                continue
            if (
                cohort_year < season_year <= cohort_year + OUTCOME_HORIZON_YEARS
                and sample >= minimum_sample
            ):
                seasons.append(season)
        filtered[key] = seasons

    references = _impact_references(filtered)
    reference_ids = sorted(
        int(row["mlbam_id"])
        for row in training
        if filtered[f"{row['mlbam_id']}_{role}"]
    )
    return {
        "references": references,
        "reference_ids": reference_ids,
        "reference_player_count": sum(bool(seasons) for seasons in filtered.values()),
        "reference_season_count": sum(len(seasons) for seasons in filtered.values()),
        "reference_sha256": _canonical_sha256(references),
        "reference_source_sha256": _canonical_sha256(filtered),
        "reference_category_counts": {
            category: len(references[role][category])
            for category in IMPACT_CATEGORIES[role]
        },
        "available_categories": list(_active_impact_categories(references, role)),
    }


def fold_local_impact_oof(
    dataset_rows: list[dict],
    seasons_by_player: dict,
    role: str,
) -> dict:
    """Return player-aligned OOF evidence with training-only target references."""
    templates = _eligible_templates(dataset_rows, role)
    cohorts = sorted({row["cohort_year"] for row in templates})
    model_kind = "hurdle_ridge"
    ridge_lambda = (
        HITTER_IMPACT_RIDGE_LAMBDA if role == "hitter" else RIDGE_LAMBDA
    )
    evidence_rows = []
    folds = []

    for test_year in cohorts[2:]:
        reference_contract = _fold_reference_contract(
            templates,
            role,
            seasons_by_player,
            test_year,
        )
        fold_rows = _historical_impact_rows(
            dataset_rows,
            role,
            seasons_by_player,
            reference_contract["references"],
        )
        train = [row for row in fold_rows if row["cohort_year"] < test_year]
        test = [row for row in fold_rows if row["cohort_year"] == test_year]
        model = _fit_prediction_model(train, model_kind, ridge_lambda)
        neighbors = _fit_neighbors(train)
        canonical_train = [
            {**row, "features": row.get("baseline_features", row["features"])}
            for row in train
        ]
        canonical_neighbors = _fit_neighbors(canonical_train)
        fold = {
            "role": role,
            "test_cohort": int(test_year),
            "train_cohort_max": (
                max(row["cohort_year"] for row in train) if train else None
            ),
            "train_ids": sorted(int(row["mlbam_id"]) for row in train),
            "test_ids": sorted(int(row["mlbam_id"]) for row in test),
            **{
                key: reference_contract[key]
                for key in (
                    "reference_ids",
                    "reference_player_count",
                    "reference_season_count",
                    "reference_sha256",
                    "reference_source_sha256",
                    "reference_category_counts",
                    "available_categories",
                )
            },
        }
        if not model or not neighbors or not canonical_neighbors or not test:
            fold["status"] = "insufficient_fold"
            folds.append(fold)
            continue

        prior = _fit_prior(train)
        fold["status"] = "scored"
        folds.append(fold)
        for row in test:
            model_prediction = _round(_predict_model(model, row["features"]))
            prior_prediction = _round(_prior_predict(prior, row))
            neighbor_prediction = _round(
                _neighbor_predict(neighbors, row["features"], k=NEIGHBOR_K)
            )
            canonical_neighbor_prediction = _round(
                _neighbor_predict(
                    canonical_neighbors,
                    row.get("baseline_features", row["features"]),
                    k=NEIGHBOR_K,
                )
            )
            target = _round(row["target"])
            evidence_rows.append(
                {
                    "mlbam_id": int(row["mlbam_id"]),
                    "role": role,
                    "test_cohort": int(test_year),
                    "train_cohort_max": int(fold["train_cohort_max"]),
                    "model_prediction": model_prediction,
                    "prior_prediction": prior_prediction,
                    "neighbor_prediction": neighbor_prediction,
                    "canonical_neighbor_prediction": canonical_neighbor_prediction,
                    "target": target,
                    "model_error": _round(abs(model_prediction - target)),
                    "prior_error": _round(abs(prior_prediction - target)),
                    "neighbor_error": _round(abs(neighbor_prediction - target)),
                    "canonical_neighbor_error": _round(
                        abs(canonical_neighbor_prediction - target)
                    ),
                }
            )

    return {"role": role, "rows": evidence_rows, "folds": folds}


def cohort_player_bootstrap(
    rows: list[dict],
    *,
    baseline_error_key: str,
    seed: int,
    resamples: int,
) -> dict:
    """Equal-weight cohorts, then resample players within each selected cohort."""
    by_cohort = {}
    for row in rows:
        delta = float(row[baseline_error_key]) - float(row["model_error"])
        by_cohort.setdefault(int(row["test_cohort"]), []).append(delta)
    cohorts = [
        np.asarray(by_cohort[year], dtype=float)
        for year in sorted(by_cohort)
        if by_cohort[year]
    ]
    if not cohorts:
        return {
            "point": None,
            "low": None,
            "high": None,
            "cohorts": 0,
            "players": 0,
            "seed": int(seed),
            "resamples": int(resamples),
        }

    point = mean(float(values.mean()) for values in cohorts)
    low = high = None
    if len(cohorts) >= 2 and resamples > 0:
        rng = np.random.default_rng(seed)
        draws = np.empty(resamples)
        for draw in range(resamples):
            cohort_picks = rng.integers(0, len(cohorts), len(cohorts))
            sampled_means = []
            for pick in cohort_picks:
                values = cohorts[pick]
                player_picks = rng.integers(0, len(values), len(values))
                sampled_means.append(float(values[player_picks].mean()))
            draws[draw] = mean(sampled_means)
        low, high = (float(value) for value in np.percentile(draws, [2.5, 97.5]))

    return {
        "point": _round(point),
        "low": _round(low) if low is not None else None,
        "high": _round(high) if high is not None else None,
        "cohorts": len(cohorts),
        "players": sum(len(values) for values in cohorts),
        "seed": int(seed),
        "resamples": int(resamples),
    }


def _summary(
    rows: list[dict],
    *,
    seed: int,
    resamples: int,
) -> dict:
    comparisons = {}
    model_mae = _round(mean(row["model_error"] for row in rows)) if rows else None
    for baseline_name, error_key in BASELINES.items():
        comparisons[baseline_name] = {
            "model_mae": model_mae,
            "baseline_mae": (
                _round(mean(row[error_key] for row in rows)) if rows else None
            ),
            "baseline_minus_model": cohort_player_bootstrap(
                rows,
                baseline_error_key=error_key,
                seed=seed,
                resamples=resamples,
            ),
        }
    return {
        "players": len(rows),
        "cohorts": len({row["test_cohort"] for row in rows}),
        "comparisons": comparisons,
    }


def _report_summary(
    rows: list[dict],
    *,
    seed: int,
    resamples: int,
) -> dict:
    return {
        "combined": _summary(rows, seed=seed, resamples=resamples),
        "roles": {
            role: _summary(
                [row for row in rows if row["role"] == role],
                seed=seed,
                resamples=resamples,
            )
            for role in ("hitter", "pitcher")
        },
    }


def build_impact_oof_report(
    contract: dict,
    *,
    generated_at: str | None = None,
    bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
    source_file_sha256: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    dataset_rows = contract["historical"]["rows"]
    seasons_by_player = contract["historical_mlb_seasons"]
    role_results = [
        fold_local_impact_oof(dataset_rows, seasons_by_player, role)
        for role in ("hitter", "pitcher")
    ]
    rows = sorted(
        [row for result in role_results for row in result["rows"]],
        key=lambda row: (row["test_cohort"], row["role"], row["mlbam_id"]),
    )
    folds = sorted(
        [fold for result in role_results for fold in result["folds"]],
        key=lambda fold: (fold["test_cohort"], fold["role"]),
    )
    contract_hash = _canonical_sha256(
        {
            "historical": contract["historical"],
            "historical_mlb_seasons": seasons_by_player,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "research_only": True,
        "claim_authorized": False,
        "public_claim_eligible": False,
        "affects_live_outputs": False,
        "serving_import": None,
        "model_freeze_preserved": True,
        "evaluation": {
            "kind": "fold_local_training_identity_impact_oof",
            "model_kind": "incumbent_hurdle_ridge",
            "mature_through": MATURE_THROUGH,
            "outcome_horizon_years": OUTCOME_HORIZON_YEARS,
            "primary_error": "absolute_error",
            "bootstrap": "equal_weight_cohort_then_player",
            "seed": int(bootstrap_seed),
            "resamples": int(bootstrap_resamples),
        },
        "source": {
            "contract_sha256": contract_hash,
            "source_file_sha256": source_file_sha256 or contract_hash,
        },
        "served_impact_gate_certification": {
            "status": "uncertified",
            "reason": (
                "The served gate used full-store percentile references; this "
                "training-only replay is descriptive and changes no live output."
            ),
        },
        "limitations": [
            (
                "This is a cohort-generalization audit using matured outcomes "
                "for earlier cohorts, not a point-in-time deployment replay."
            ),
            (
                "The impact target uses only historical categories with adequate "
                "coverage and is not direct 7x7 realized fantasy value."
            ),
            "Hitter and pitcher evidence must be interpreted separately.",
        ],
        "folds": folds,
        "rows": rows,
        "summary": _report_summary(
            rows,
            seed=bootstrap_seed,
            resamples=bootstrap_resamples,
        ),
    }


_BOUNDARY_FLAGS = {
    "affects_live_outputs",
    "claim_authorized",
    "public_claim_eligible",
    "serving_import",
    "serving_enabled",
    "production_import",
    "rank_input",
    "value_input",
    "publication_input",
}


def _has_enabled_boundary_flag(value) -> bool:
    if isinstance(value, dict):
        return any(
            (key in _BOUNDARY_FLAGS and item not in (None, False))
            or _has_enabled_boundary_flag(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_enabled_boundary_flag(item) for item in value)
    return False


def validate_impact_oof_report(
    report: dict,
    *,
    source_file_sha256: str | None = None,
) -> list[str]:
    errors = []
    if report.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version_mismatch")
    if source_file_sha256 is not None and (
        report.get("source") or {}
    ).get("source_file_sha256") != source_file_sha256:
        errors.append("source_file_hash_mismatch")

    if report.get("research_only") is not True or report.get(
        "model_freeze_preserved"
    ) is not True or _has_enabled_boundary_flag(report):
        errors.append("research_boundary_violation")

    seen = set()
    row_index = {}
    for row in report.get("rows") or []:
        identity = (
            int(row["mlbam_id"]),
            str(row["role"]),
            int(row["test_cohort"]),
        )
        if identity in seen:
            errors.append("duplicate_oof_identity")
        seen.add(identity)
        row_index.setdefault((identity[1], identity[2]), set()).add(identity[0])
        checks = {
            "model_error": abs(row["model_prediction"] - row["target"]),
            "prior_error": abs(row["prior_prediction"] - row["target"]),
            "neighbor_error": abs(row["neighbor_prediction"] - row["target"]),
            "canonical_neighbor_error": abs(
                row["canonical_neighbor_prediction"] - row["target"]
            ),
        }
        if any(
            abs(float(row[key]) - _round(value)) > 1e-10
            for key, value in checks.items()
        ):
            if "row_error_mismatch" not in errors:
                errors.append("row_error_mismatch")

    for fold in report.get("folds") or []:
        test_ids = {int(value) for value in fold.get("test_ids") or []}
        reference_ids = {int(value) for value in fold.get("reference_ids") or []}
        if int(fold.get("reference_player_count") or 0) != len(reference_ids):
            errors.append("reference_identity_count_mismatch")
        if test_ids & reference_ids:
            errors.append("fold_reference_leak")
        test_cohort = int(fold["test_cohort"])
        train_max = fold.get("train_cohort_max")
        if train_max is not None and int(train_max) >= test_cohort:
            errors.append("fold_boundary_violation")
        if fold.get("status") == "scored" and row_index.get(
            (fold["role"], test_cohort), set()
        ) != test_ids:
            errors.append("fold_identity_mismatch")
        for hash_key in ("reference_sha256", "reference_source_sha256"):
            value = str(fold.get(hash_key) or "")
            if len(value) != 64:
                errors.append("invalid_reference_hash")

    evaluation = report.get("evaluation") or {}
    expected_summary = _report_summary(
        report.get("rows") or [],
        seed=int(evaluation.get("seed") or 0),
        resamples=int(evaluation.get("resamples") or 0),
    )
    if report.get("summary") != expected_summary:
        errors.append("summary_mismatch")

    return list(dict.fromkeys(errors))
