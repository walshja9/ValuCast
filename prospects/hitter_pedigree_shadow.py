"""Shadow-only experiment: adds lean, high-coverage draft-pedigree signal
(draft-record-known presence flag + inverse draft pick) to the HITTER outcome
model's feature vector, and validates it through the exact same walk-forward
gate the live model uses.

Why these two features, not the full 8-field pitcher pedigree block: an
earlier pass found the full block has terrible hitter coverage (pick_value
15%, signing_bonus 24%, school_type 13%) and the ridge model overfits the
sparse spikes, making hitter accuracy WORSE. The lean pair (~68% coverage)
was the one variant that held up under the real walk-forward gate.

Feeds nothing live. rank_v1.py, valucast_prospect_model.json, and score_current
are untouched by this module -- it only imports read-only helpers from
prospects/model.py and writes its own artifact.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

from prospects.gate import decide_gate
from prospects.model import (
    MATURE_THROUGH,
    MIN_GATE_IMPROVEMENT_PCT,
    MIN_GATE_SAMPLE,
    OUTCOME_FEATURE_NAMES,
    OUTCOME_MODEL_KIND,
    RIDGE_LAMBDA,
    _fit_prediction_model,
    _fit_ridge,
    _historical_rows,
    _outcome_feature_vector,
    _predict_model,
    _regress_current_features,
    _rounded_prediction_model,
    _sample,
    _select_current_records,
    _service_index,
    _truthy,
    _walk_forward,
    _zero_num,
    load_input_contract,
    train_role,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_NAME = "valucast_hitter_pedigree_shadow"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_hitter_pedigree_shadow.json"

PEDIGREE_FEATURE_NAMES = ("draft_record_known", "inverse_draft_pick")
AUGMENTED_HITTER_FEATURE_NAMES = tuple(OUTCOME_FEATURE_NAMES["hitter"]) + PEDIGREE_FEATURE_NAMES


def _source_policy() -> dict:
    return {
        "kind": "valucast_hitter_pedigree_shadow",
        "feeds_model_score": False,
        "feeds_public_rank": False,
        "feeds_buy_score": False,
        "feeds_live_valucast_rank": False,
        "feeds_live_dd_value": False,
        "dd_values_used": False,
        "external_rankings_used": False,
        "market_values_used": False,
    }


def _pedigree_extra(record: dict) -> list[float]:
    draft_pick = _zero_num(record.get("draft_pick_number"))
    return [
        1.0 if _truthy(record.get("draft_record_known")) else 0.0,
        1.0 / (draft_pick or 999.0),
    ]


def _augment_rows(dataset_rows: list[dict]) -> list[dict]:
    """Reuses the real _historical_rows filter/dedup/sort for hitters exactly,
    then appends the 2 lean pedigree features onto each row's `features` using
    the raw record it was built from. `baseline_features` (the kNN input the
    model is measured against) is left untouched."""
    rows = _historical_rows(dataset_rows, "hitter")
    raw_by_id: dict[int, dict] = {}
    for record in dataset_rows:
        if record.get("role") != "hitter":
            continue
        mlbam_id = record.get("mlbam_id")
        if mlbam_id is not None and int(mlbam_id) not in raw_by_id:
            raw_by_id[int(mlbam_id)] = record
    augmented = []
    for row in rows:
        raw = raw_by_id.get(row["mlbam_id"])
        if raw is None:
            continue
        augmented.append({**row, "features": row["features"] + _pedigree_extra(raw)})
    return augmented


def _age_band(age: int) -> str:
    if age <= 19:
        return "age<=19"
    if age <= 21:
        return "age20-21"
    return "age22-24"


def _mae_by_band(rows: list[dict], predictions: list[float], targets: list[float]) -> dict:
    buckets: dict[str, list[tuple[float, float]]] = {}
    for row, pred, target in zip(rows, predictions, targets):
        buckets.setdefault(_age_band(row["age"]), []).append((pred, target))
    out = {}
    for band, pairs in buckets.items():
        out[band] = {
            "n": len(pairs),
            "mae": round(sum(abs(p - t) for p, t in pairs) / len(pairs), 6) if pairs else None,
        }
    return out


def validate_augmented_hitter(dataset_rows: list[dict], now: str | None = None) -> dict:
    """Runs the real _walk_forward on the augmented hitter feature set, pools
    with the REAL unmodified pitcher validation (train_role, untouched), and
    computes the gate the exact same way build_shadow_model's combined_gate
    does -- so this number is directly comparable to the shipped board_gate."""
    now = now or datetime.now(timezone.utc).isoformat()
    augmented_rows = _augment_rows(dataset_rows)
    hitter_validation = _walk_forward(
        augmented_rows, OUTCOME_MODEL_KIND["hitter"], RIDGE_LAMBDA,
        neighbor_feature_key="baseline_features",
    )
    pitcher_result = train_role("pitcher", dataset_rows, now)
    pitcher_validation = pitcher_result["_validation"]

    hitter_gate = decide_gate(
        metric="outcome_score_mae",
        model_score=hitter_validation["model_mae"],
        baselines={
            "level_age_prior": hitter_validation["prior_mae"],
            "historical_neighbors_25": hitter_validation["neighbor_mae"],
        },
        sample_size=len(hitter_validation["targets"]),
        cv_method="walk_forward",
        validated_through=str(MATURE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=True,
        now=now,
    )

    model_predictions = list(hitter_validation["model_predictions"]) + list(pitcher_validation["model_predictions"])
    prior_predictions = list(hitter_validation["prior_predictions"]) + list(pitcher_validation["prior_predictions"])
    neighbor_predictions = list(hitter_validation["neighbor_predictions"]) + list(pitcher_validation["neighbor_predictions"])
    targets = list(hitter_validation["targets"]) + list(pitcher_validation["targets"])

    def mae(predictions):
        if not targets:
            return None
        return round(sum(abs(p - t) for p, t in zip(predictions, targets)) / len(targets), 6)

    pooled_gate = decide_gate(
        metric="outcome_score_mae",
        model_score=mae(model_predictions),
        baselines={
            "level_age_prior": mae(prior_predictions),
            "historical_neighbors_25": mae(neighbor_predictions),
        },
        sample_size=len(targets),
        cv_method="walk_forward",
        validated_through=str(MATURE_THROUGH),
        min_sample=MIN_GATE_SAMPLE * 2,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=True,
        now=now,
    )

    return {
        "hitter_gate": hitter_gate,
        "hitter_model_mae": round(hitter_validation["model_mae"], 6),
        "hitter_neighbor_mae": round(hitter_validation["neighbor_mae"], 6),
        "hitter_n": len(hitter_validation["targets"]),
        "hitter_age_band_mae": _mae_by_band(
            augmented_rows, hitter_validation["model_predictions"], hitter_validation["targets"]
        ),
        "pooled_gate": pooled_gate,
        "pooled_model_mae": mae(model_predictions),
        "pooled_neighbor_mae": mae(neighbor_predictions),
        "pooled_n": len(targets),
    }


def _fit_augmented_hitter_model(dataset_rows: list[dict]) -> dict:
    """Mirrors train_role's live-serving refit exactly (fit prediction_model +
    a separate driver_model on ALL eligible rows), but on the augmented
    feature set. `means`/`stds` come from the driver_model fit, matching
    train_role's own shape -- _regress_current_features reads role_model["means"]
    directly, not prediction_model["arrival_model"]["means"]."""
    augmented_rows = _augment_rows(dataset_rows)
    prediction_model = _fit_prediction_model(augmented_rows, OUTCOME_MODEL_KIND["hitter"], RIDGE_LAMBDA)
    driver_model = _fit_ridge(augmented_rows)
    if prediction_model is None or driver_model is None:
        raise ValueError(f"Could not fit augmented hitter model from {len(augmented_rows)} rows")
    return {
        "feature_names": list(AUGMENTED_HITTER_FEATURE_NAMES),
        "prediction_model": _rounded_prediction_model(prediction_model),
        "means": [round(value, 8) for value in driver_model["means"]],
        "stds": [round(value, 8) for value in driver_model["stds"]],
    }


def preview_current_hitter_deltas(contract: dict, augmented_model: dict, live_role_model: dict) -> list[dict]:
    """Real preview of what promoting this would change: for every current,
    eligible hitter, compute expected_outcome_score under the augmented model
    vs. the live served model, using the SAME shrinkage
    (_regress_current_features) and prediction call as score_current."""
    current = contract["current"]
    service = _service_index(contract)
    live_runtime = {**live_role_model["prediction_model"]}
    augmented_runtime = {**augmented_model["prediction_model"]}
    rows = []
    for record in _select_current_records(current, "hitter"):
        service_fact = service.get((int(record["mlbam_id"]), "hitter"))
        if service_fact is None or service_fact.get("graduated"):
            continue
        outcome_raw = _outcome_feature_vector(record, "hitter")
        if outcome_raw is None:
            continue
        sample = _sample(record, "hitter")
        live_regressed, reliability = _regress_current_features(outcome_raw, live_role_model, "hitter", sample)
        augmented_raw = outcome_raw + _pedigree_extra(record)
        augmented_regressed, _ = _regress_current_features(augmented_raw, augmented_model, "hitter", sample)
        live_score = round(_predict_model(live_runtime, live_regressed), 4)
        augmented_score = round(_predict_model(augmented_runtime, augmented_regressed), 4)
        rows.append({
            "mlbam_id": int(record["mlbam_id"]),
            "name": record.get("name"),
            "level": record.get("level"),
            "age": record.get("age"),
            "sample": round(sample, 1),
            "sample_reliability": round(reliability, 3),
            "live_expected_outcome_score": live_score,
            "augmented_expected_outcome_score": augmented_score,
            "delta": round(augmented_score - live_score, 4),
        })
    return rows


def build_hitter_pedigree_shadow(*, generated_at: str | None = None) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    contract = load_input_contract()
    dataset_rows = contract["historical"].get("rows", [])

    validation = validate_augmented_hitter(dataset_rows, generated_at)
    augmented_model = _fit_augmented_hitter_model(dataset_rows)
    live_role_model = train_role("hitter", dataset_rows, generated_at)
    live_role_model.pop("_validation", None)

    deltas = preview_current_hitter_deltas(contract, augmented_model, live_role_model)
    abs_deltas = [abs(row["delta"]) for row in deltas]
    movers = sorted(deltas, key=lambda row: -abs(row["delta"]))[:25]

    return {
        "artifact": ARTIFACT_NAME,
        "generated_at": generated_at,
        "feature_names": list(AUGMENTED_HITTER_FEATURE_NAMES),
        "pedigree_features_added": list(PEDIGREE_FEATURE_NAMES),
        "source_policy": _source_policy(),
        "validation": validation,
        "current_preview": {
            "scored_count": len(deltas),
            "nontrivial_delta_count": sum(1 for value in abs_deltas if value >= 0.01),
            "median_abs_delta": round(median(abs_deltas), 4) if abs_deltas else 0.0,
            "largest_movers": movers,
        },
    }


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_hitter_pedigree_shadow(*, artifact_path: Path = ARTIFACT_PATH, generated_at: str | None = None) -> dict:
    payload = build_hitter_pedigree_shadow(generated_at=generated_at)
    path = _write_json(payload, artifact_path)
    return {"artifact_path": str(path), "payload": payload}
