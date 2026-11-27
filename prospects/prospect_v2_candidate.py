"""Frozen Prospect Model v0.8 candidate built from corrected labels only."""
from __future__ import annotations

from statistics import mean

import numpy as np

from prospects import impact_oof
from prospects.level_translation_challenger import (
    STRIKE_PCT_FEATURE_NAMES,
    strike_pct_extra,
)
from prospects.model import (
    NEIGHBOR_K,
    RIDGE_LAMBDA,
    _feature_vector,
    _fit_neighbors,
    _fit_prediction_model,
    _fit_prior,
    _historical_impact_rows,
    _historical_rows,
    _impact_references,
    _neighbor_predict,
    _outcome_feature_names,
    _outcome_feature_vector,
    _predict_model,
    _prior_predict,
    _rounded_prediction_model,
    _select_current_records,
)
from prospects.prospect_v2_target import canonical_sha256
from prospects.stage1_outcome_proof import _metric

MODEL_VERSION = "0.8.0"
SCORE_SOURCE = "prospect_model_v0_8"
DEVELOPMENT_FOLDS = (2018, 2019, 2021)
BLEND_GRID = tuple(i / 10 for i in range(11))


def choose_band_weight(rows: list[dict]) -> float:
    if not rows:
        raise ValueError("band weight selection has no rows")
    scored = []
    for weight in BLEND_GRID:
        values = [
            weight * row["hurdle"] + (1.0 - weight) * row["neighbor"]
            for row in rows
        ]
        rho = _metric("spearman_rho", values, [row["target"] for row in rows])
        scored.append((float(rho or 0.0), -weight, weight))
    return max(scored)[2]


def _pitcher_features(source: dict, base: list[float]) -> list[float]:
    pitches = source.get("pitches")
    strikes = source.get("strikes")
    if (
        isinstance(pitches, bool)
        or not isinstance(pitches, (int, float))
        or pitches <= 0
        or isinstance(strikes, bool)
        or not isinstance(strikes, (int, float))
        or not 0 <= strikes <= pitches
    ):
        raise ValueError("invalid pitch/strike counts")
    return [*base, *strike_pct_extra(source)]


def _validate_contract(contract: dict) -> None:
    rows = (contract.get("historical") or {}).get("rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("invalid development contract")
    if contract.get("cohort_max") != 2021 or any(
        int(row.get("cohort_year") or 9999) > 2021 for row in rows
    ):
        raise ValueError("development contract contains a post-2021 cohort")
    for row in rows:
        if row.get("role") == "pitcher":
            _pitcher_features(row, [])
    if not isinstance(contract.get("historical_mlb_seasons"), dict):
        raise ValueError("development contract is missing MLB season facts")


def _prepared_rows(contract: dict, role: str) -> list[dict]:
    source_rows = contract["historical"]["rows"]
    prepared = _historical_rows(source_rows, role, 2021)
    if role == "hitter":
        return prepared
    sources = {
        (int(row["mlbam_id"]), int(row["cohort_year"]), str(row["level"]).upper()): row
        for row in source_rows
        if row.get("role") == role
    }
    for row in prepared:
        key = (row["mlbam_id"], row["cohort_year"], row["level"])
        source = sources.get(key)
        if source is None:
            raise ValueError(f"missing pitch/strike source for {key}")
        row["features"] = _pitcher_features(source, row["features"])
    return prepared


def _neighbor_predictions(
    train: list[dict],
    query: list[dict],
    *,
    exclude_self: bool = False,
) -> tuple[list[float], list[list[int]]]:
    train_features = np.asarray([row["baseline_features"] for row in train], dtype=float)
    query_features = np.asarray([row["baseline_features"] for row in query], dtype=float)
    targets = np.asarray([row["target"] for row in train], dtype=float)
    centers = train_features.mean(axis=0)
    spreads = train_features.std(axis=0)
    spreads[spreads == 0] = 1.0
    distances = (
        ((query_features - centers)[:, None, :] - (train_features - centers)[None, :, :])
        / spreads
    ) ** 2
    distances = distances.sum(axis=2)
    if exclude_self:
        if len(query) != len(train):
            raise ValueError("leave-one-out neighbors require identical rows")
        np.fill_diagonal(distances, np.inf)
    indices = np.argsort(distances, axis=1, kind="stable")[:, : min(NEIGHBOR_K, len(train))]
    return (
        [float(targets[index].mean()) for index in indices],
        [[int(train[i]["mlbam_id"]) for i in index] for index in indices],
    )


def _weight_selection_rows(train: list[dict]) -> list[dict]:
    neighbor_predictions, _ = _neighbor_predictions(
        train, train, exclude_self=True
    )
    selected = []
    cohorts = sorted({row["cohort_year"] for row in train})
    for test_cohort in cohorts[2:]:
        inner_train = [row for row in train if row["cohort_year"] < test_cohort]
        inner_indices = [
            index for index, row in enumerate(train)
            if row["cohort_year"] == test_cohort
        ]
        model = _fit_prediction_model(inner_train, "hurdle_ridge", RIDGE_LAMBDA)
        if model is None:
            continue
        for index in inner_indices:
            row = train[index]
            selected.append(
                {
                    "cohort": test_cohort,
                    "hurdle": _predict_model(model, row["features"]),
                    "neighbor": neighbor_predictions[index],
                    "target": row["target"],
                }
            )
    return selected


def _band_weights(train: list[dict]) -> tuple[dict[str, float], list[int]]:
    rows = _weight_selection_rows(train)
    if not rows:
        return {"zero": 0.5, "positive": 0.5}, []
    weights = {
        band: choose_band_weight(selected) if selected else 0.0
        for band, selected in {
            "zero": [row for row in rows if row["hurdle"] == 0.0],
            "positive": [row for row in rows if row["hurdle"] > 0.0],
        }.items()
    }
    return weights, sorted({int(row["cohort"]) for row in rows})


def _blend(hurdle: float, neighbor: float, weights: dict[str, float]) -> float:
    weight = weights["zero" if hurdle == 0.0 else "positive"]
    return weight * hurdle + (1.0 - weight) * neighbor


def build_outcome_oof(
    contract: dict,
    *,
    score_source: str = SCORE_SOURCE,
    band_weight_selector=_band_weights,
) -> list[dict]:
    _validate_contract(contract)
    source_rows = contract["historical"]["rows"]
    seasons = contract["historical_mlb_seasons"]
    impact = {
        role: {
            (row["mlbam_id"], row["test_cohort"]): row
            for row in impact_oof.fold_local_impact_oof(
                source_rows, seasons, role, mature_through=2021
            )["rows"]
        }
        for role in ("hitter", "pitcher")
    }
    output = []
    for role in ("hitter", "pitcher"):
        rows = _prepared_rows(contract, role)
        for test_cohort in sorted({row["cohort_year"] for row in rows})[2:]:
            train = [row for row in rows if row["cohort_year"] < test_cohort]
            test = [row for row in rows if row["cohort_year"] == test_cohort]
            model = _fit_prediction_model(train, "hurdle_ridge", RIDGE_LAMBDA)
            if model is None or not test:
                raise ValueError(f"invalid {role} development fold {test_cohort}")
            prior = _fit_prior(train)
            neighbor_predictions, neighbor_ids = _neighbor_predictions(train, test)
            if role == "pitcher":
                weights, selection_cohorts = band_weight_selector(train)
            else:
                weights, selection_cohorts = None, []
            training_ids = [int(row["mlbam_id"]) for row in train]
            for row, neighbor, neighbors in zip(test, neighbor_predictions, neighbor_ids):
                hurdle = _predict_model(model, row["features"])
                candidate = _blend(hurdle, neighbor, weights) if weights else hurdle
                impact_row = impact[role].get((row["mlbam_id"], test_cohort))
                if impact_row is None:
                    raise ValueError("missing fold-local impact prediction")
                impact_prediction = float(impact_row["model_prediction"])
                output.append(
                    {
                        "mlbam_id": row["mlbam_id"],
                        "role": role,
                        "score_source": score_source,
                        "test_cohort": test_cohort,
                        "target": row["target"],
                        "outcome": {0.0: "bust", 0.5: "role", 1.0: "star"}[
                            row["target"]
                        ],
                        "raw_outcome_prediction": float(candidate),
                        "expected_outcome_score": float(candidate),
                        "hurdle_prediction": float(hurdle),
                        "prior_prediction": _prior_predict(prior, row),
                        "canonical_neighbor_prediction": float(neighbor),
                        "impact_prediction": impact_prediction,
                        "expected_category_impact_score": impact_prediction,
                        "raw_composite": float(
                            0.58 * candidate + 0.42 * impact_prediction
                        ),
                        "training_ids": training_ids,
                        "neighbor_ids": neighbors,
                        "weight_selection_cohorts": selection_cohorts,
                    }
                )
    return sorted(output, key=lambda row: (row["test_cohort"], row["role"], row["mlbam_id"]))


def _rounded_neighbors(model: dict) -> dict:
    return {
        "features": [[round(value, 8) for value in row] for row in model["features"]],
        "targets": [round(value, 8) for value in model["targets"]],
        "means": [round(value, 8) for value in model["means"]],
        "stds": [round(value, 8) for value in model["stds"]],
    }


def _fit_candidate_model(
    contract: dict,
    *,
    model_version: str,
    score_source: str,
    schema: str,
    band_weight_selector,
) -> dict:
    _validate_contract(contract)
    prepared = {role: _prepared_rows(contract, role) for role in ("hitter", "pitcher")}
    references = _impact_references(contract["historical_mlb_seasons"])
    outcome_models = {}
    impact_models = {}
    for role, rows in prepared.items():
        prediction = _fit_prediction_model(rows, "hurdle_ridge", RIDGE_LAMBDA)
        neighbors = _fit_neighbors(rows, "baseline_features")
        impact_rows = _historical_impact_rows(
            contract["historical"]["rows"],
            role,
            contract["historical_mlb_seasons"],
            references,
            2021,
        )
        impact_prediction = _fit_prediction_model(
            impact_rows, "hurdle_ridge", RIDGE_LAMBDA
        )
        if prediction is None or neighbors is None or impact_prediction is None:
            raise ValueError(f"could not fit v{model_version.rsplit('.', 1)[0]} {role} model")
        outcome_models[role] = {
            "prediction_model": _rounded_prediction_model(prediction),
            "canonical_neighbors": _rounded_neighbors(neighbors),
        }
        impact_models[role] = {
            "prediction_model": _rounded_prediction_model(impact_prediction),
        }
    pitcher_weights, _ = band_weight_selector(prepared["pitcher"])
    identities = {
        role: [
            {"mlbam_id": row["mlbam_id"], "cohort_year": row["cohort_year"]}
            for row in rows
        ]
        for role, rows in prepared.items()
    }
    artifact = {
        "schema": schema,
        "model_version": model_version,
        "score_source": score_source,
        "training_cohort_max": 2021,
        "release_contract": {
            "consumer": "prospect_rank_v2",
            "score_source": score_source,
            "feeds_live_valucast_rank": False,
        },
        "feature_names": {
            "hitter": list(_outcome_feature_names("hitter")),
            "pitcher": [*_outcome_feature_names("pitcher"), *STRIKE_PCT_FEATURE_NAMES],
        },
        "outcome_models": outcome_models,
        "impact_models": impact_models,
        "pitcher_band_weights": pitcher_weights,
        "training_identities": identities,
        "training_identity_sha256": canonical_sha256(identities),
        "oof_rows": build_outcome_oof(
            contract,
            score_source=score_source,
            band_weight_selector=band_weight_selector,
        ),
    }
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


def _score_candidate_profiles(
    rows: list[dict],
    model: dict,
    *,
    model_version: str,
    score_source: str,
) -> list[dict]:
    if (
        model.get("model_version") != model_version
        or model.get("score_source") != score_source
        or (model.get("release_contract") or {}).get("score_source") != score_source
    ):
        raise ValueError(f"invalid v{model_version.rsplit('.', 1)[0]} model contract")
    expected_hash = model.get("artifact_sha256")
    unsigned = {key: value for key, value in model.items() if key != "artifact_sha256"}
    if expected_hash != canonical_sha256(unsigned):
        raise ValueError(f"invalid v{model_version.rsplit('.', 1)[0]} model contract hash")
    current = {
        "hitters": [row for row in rows if row.get("role") == "hitter"],
        "pitchers": [row for row in rows if row.get("role") == "pitcher"],
    }
    selected = [
        *_select_current_records(current, "hitter"),
        *_select_current_records(current, "pitcher"),
    ]
    output = []
    seen = set()
    for source in selected:
        role = source.get("role")
        identity = (source.get("mlbam_id"), role)
        if role not in ("hitter", "pitcher") or not identity[0] or identity in seen:
            raise ValueError(
                f"invalid or duplicate v{model_version.rsplit('.', 1)[0]} scoring identity"
            )
        seen.add(identity)
        base = _outcome_feature_vector(source, role)
        baseline = _feature_vector(source, role)
        if base is None or baseline is None:
            raise ValueError(f"missing v{model_version.rsplit('.', 1)[0]} scoring feature")
        features = _pitcher_features(source, base) if role == "pitcher" else base
        outcome_model = model["outcome_models"][role]
        hurdle = _predict_model(outcome_model["prediction_model"], features)
        if role == "pitcher":
            neighbor = _neighbor_predict(
                outcome_model["canonical_neighbors"], baseline, k=NEIGHBOR_K
            )
            outcome = _blend(hurdle, neighbor, model["pitcher_band_weights"])
        else:
            outcome = hurdle
        impact = _predict_model(
            model["impact_models"][role]["prediction_model"], base
        )
        output.append(
            {
                **source,
                "score_source": score_source,
                "expected_outcome_score": float(outcome),
                "expected_category_impact_score": float(impact),
                "raw_composite": float(0.58 * outcome + 0.42 * impact),
            }
        )
    return output


def fit_v08_model(contract: dict) -> dict:
    return _fit_candidate_model(
        contract,
        model_version=MODEL_VERSION,
        score_source=SCORE_SOURCE,
        schema="valucast_prospect_model_v0_8",
        band_weight_selector=_band_weights,
    )


def score_v08_profiles(rows: list[dict], model: dict) -> list[dict]:
    return _score_candidate_profiles(
        rows,
        model,
        model_version=MODEL_VERSION,
        score_source=SCORE_SOURCE,
    )
