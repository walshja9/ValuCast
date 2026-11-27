"""Gate-aligned Prospect Model v0.9 pitcher blend candidate."""
from __future__ import annotations

from statistics import mean

from prospects.prospect_v2_candidate import (
    BLEND_GRID,
    _blend,
    _fit_candidate_model,
    _neighbor_predictions,
    _prepared_rows,
    _score_candidate_profiles,
)
from prospects.prospect_v2_target import canonical_sha256
from prospects.stage1_outcome_proof import _metric
from prospects.model import RIDGE_LAMBDA, _fit_prediction_model, _predict_model

MODEL_VERSION = "0.9.0"
SCORE_SOURCE = "prospect_model_v0_9"
SCHEMA = "valucast_prospect_model_v0_9"


class NoGateAlignedBlend(ValueError):
    """Raised when no inner-OOF pitcher blend clears every raw gate."""


def select_gate_aligned_weight_receipt(receipts: list[dict]) -> dict:
    eligible = [
        row for row in receipts
        if row["spearman_delta"] > 0
        and row["kendall_delta"] > 0
        and row["auc_delta"] > 0
        and row["mae_delta"] <= 0
    ]
    if not eligible:
        raise NoGateAlignedBlend("no gate-aligned pitcher blend")
    return max(
        eligible,
        key=lambda row: (
            min(row["spearman_delta"], row["kendall_delta"], row["auc_delta"]),
            -row["mae_delta"],
            -(row["zero_weight"] + row["positive_weight"]),
            -row["zero_weight"],
            -row["positive_weight"],
        ),
    )


def _metric_delta(
    name: str,
    predictions: list[float],
    neighbors: list[float],
    targets: list[float],
) -> float:
    candidate = _metric(name, predictions, targets)
    baseline = _metric(name, neighbors, targets)
    return float("nan") if candidate is None or baseline is None else candidate - baseline


def _strict_inner_weight_selection_rows(train: list[dict]) -> list[dict]:
    selected = []
    cohorts = sorted({row["cohort_year"] for row in train})
    for test_cohort in cohorts[2:]:
        inner_train = [row for row in train if row["cohort_year"] < test_cohort]
        inner_test = [row for row in train if row["cohort_year"] == test_cohort]
        model = _fit_prediction_model(inner_train, "hurdle_ridge", RIDGE_LAMBDA)
        if model is None:
            continue
        neighbors, _ = _neighbor_predictions(inner_train, inner_test)
        selected.extend(
            {
                "cohort": test_cohort,
                "hurdle": _predict_model(model, row["features"]),
                "neighbor": neighbor,
                "target": row["target"],
            }
            for row, neighbor in zip(inner_test, neighbors)
        )
    return selected


def _gate_aligned_weight_receipt_from_rows(rows: list[dict]) -> dict:
    cohorts = sorted({int(row["cohort"]) for row in rows})
    if not rows:
        return {
            "zero_weight": 0.5,
            "positive_weight": 0.5,
            "selection_cohorts": cohorts,
            "row_count": 0,
            "row_sha256": canonical_sha256(rows),
        }
    targets = [float(row["target"]) for row in rows]
    neighbors = [float(row["neighbor"]) for row in rows]
    receipts = []
    for zero_weight in BLEND_GRID:
        for positive_weight in BLEND_GRID:
            weights = {"zero": zero_weight, "positive": positive_weight}
            predictions = [
                _blend(float(row["hurdle"]), float(row["neighbor"]), weights)
                for row in rows
            ]
            receipts.append(
                {
                    "zero_weight": zero_weight,
                    "positive_weight": positive_weight,
                    "spearman_delta": _metric_delta(
                        "spearman_rho", predictions, neighbors, targets
                    ),
                    "kendall_delta": _metric_delta(
                        "kendall_tau_b", predictions, neighbors, targets
                    ),
                    "auc_delta": _metric_delta("roc_auc", predictions, neighbors, targets),
                    "mae_delta": mean(
                        abs(prediction - target)
                        for prediction, target in zip(predictions, targets)
                    ) - mean(abs(neighbor - target) for neighbor, target in zip(neighbors, targets)),
                }
            )
    selected = select_gate_aligned_weight_receipt(receipts)
    return {
        **selected,
        "selection_cohorts": cohorts,
        "row_count": len(rows),
        "row_sha256": canonical_sha256(rows),
    }


def gate_aligned_weight_receipt(train: list[dict]) -> dict:
    return _gate_aligned_weight_receipt_from_rows(
        _strict_inner_weight_selection_rows(train)
    )


def gate_aligned_band_weights(train: list[dict]) -> tuple[dict[str, float], list[int]]:
    receipt = gate_aligned_weight_receipt(train)
    return (
        {"zero": receipt["zero_weight"], "positive": receipt["positive_weight"]},
        receipt["selection_cohorts"],
    )


def fit_v09_model(contract: dict) -> dict:
    model = _fit_candidate_model(
        contract,
        model_version=MODEL_VERSION,
        score_source=SCORE_SOURCE,
        schema=SCHEMA,
        band_weight_selector=gate_aligned_band_weights,
    )
    prepared = _prepared_rows(contract, "pitcher")
    receipts = {}
    for cohort in sorted(
        {row["test_cohort"] for row in model["oof_rows"] if row["role"] == "pitcher"}
    ):
        train = [row for row in prepared if row["cohort_year"] < cohort]
        receipt = gate_aligned_weight_receipt(train)
        if receipt["row_count"]:
            receipts[str(cohort)] = receipt
    model["weight_selection_by_fold"] = receipts
    model["artifact_sha256"] = canonical_sha256(
        {key: value for key, value in model.items() if key != "artifact_sha256"}
    )
    return model


def score_v09_profiles(rows: list[dict], model: dict) -> list[dict]:
    return _score_candidate_profiles(
        rows,
        model,
        model_version=MODEL_VERSION,
        score_source=SCORE_SOURCE,
    )
