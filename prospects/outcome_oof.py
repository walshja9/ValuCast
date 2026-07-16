"""Serialized per-player OOF for the outcome-score layer (audit repair R6).

The pooled outcome-score MAE gate (``board_gate`` in
``prospects.model.build_shadow_model``) is the headline "model beats the
neighbors baseline by ~6.36% out-of-sample" claim. Its per-player OOF
predictions were popped from ``_validation`` and thrown away before the model
artifact was serialized, so the claim could not be independently re-derived from
the committed public repository. This module rebuilds the identical
walk-forward validation and commits the per-player, per-fold predictions
(``valucast_outcome_oof_scores.json``) so the gate can be CI-checked.

Contract (mirrors ``valucast_ordinal_oof_scores.json`` in style):
- research_only, never consumed by any live score, rank, or value.
- No consensus / third-party ranks are stored (nothing outside the factual
  model's own OOF predictions and realized targets).
- Rows carry only ``model``/``prior``/``neighbor`` predictions and the realized
  ordinal outcome target, keyed by ``(mlbam_id, role, test_cohort)``.

Reproducing the served gate from these rows: pool all rows, take
``mean(|model - target|)`` and ``mean(|neighbor - target|)``; the neighbors
baseline is the one the gate selects (lower pooled MAE), and the reported
``combined_mae_delta_pct`` equals the served ``board_gate.improvement_pct``.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.model import outcome_oof_rows
from prospects.universal import INPUT_PATH, load_input_contract

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_outcome_oof_scores.json"
SCHEMA_VERSION = "1.0.0"
ROLES = ("hitter", "pitcher")
ROW_FIELDS = {
    "mlbam_id",
    "role",
    "test_cohort",
    "train_cohort_max",
    "model_prediction",
    "prior_prediction",
    "neighbor_prediction",
    "target",
}
TOP_LEVEL_FIELDS = {
    "artifact",
    "schema_version",
    "status",
    "generated_at",
    "input",
    "prediction_policy",
    "layer",
    "folds",
    "rows",
    "validation",
}
_HORIZON = "expanding_window_outcome_score"


def _generated_at(value: str | None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _identity_hash(rows: list[dict]) -> str:
    identities = sorted(
        f"{row['mlbam_id']}|{row['role']}|{row['test_cohort']}" for row in rows
    )
    return hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()


def _finite(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def build_outcome_oof_artifact(
    role_rows: dict[str, list[dict]],
    *,
    input_sha256: str,
    generated_at: str | None = None,
) -> dict:
    rows: list[dict] = []
    for role in ROLES:
        rows.extend(role_rows.get(role, []))
    cohorts = sorted({row["test_cohort"] for row in rows})
    folds = []
    for cohort in cohorts:
        fold_rows = [row for row in rows if row["test_cohort"] == cohort]
        train_maxes = {row["train_cohort_max"] for row in fold_rows}
        roles = {}
        for role in ROLES:
            role_rows_fold = [row for row in fold_rows if row["role"] == role]
            roles[role] = {
                "row_count": len(role_rows_fold),
                "identity_sha256": _identity_hash(role_rows_fold),
            }
        folds.append(
            {
                "test_cohort": cohort,
                "train_cohort_max": (
                    train_maxes.pop() if len(train_maxes) == 1 else None
                ),
                "row_count": len(fold_rows),
                "identity_sha256": _identity_hash(fold_rows),
                "roles": roles,
            }
        )
    return {
        "artifact": "valucast_outcome_oof_scores",
        "schema_version": SCHEMA_VERSION,
        "status": "research_only",
        "generated_at": _generated_at(generated_at),
        "input": {
            "path": "data/prospects/prospect_model_inputs.json",
            "sha256": input_sha256,
        },
        "prediction_policy": {
            "fold_trained_out_of_fold": True,
            "in_sample_predictions_used": False,
            "todays_model_used": False,
            "consensus_or_third_party_ranks_used": False,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
        },
        "layer": {
            "name": "outcome_score",
            "model_kind": "hurdle_ridge",
            "target": "ordinal forward MLB outcome tier (bust=0, role=0.5, star=1)",
            "validation": _HORIZON,
            "gate_metric": "outcome_score_mae",
            "gate_baselines": [
                "level_age_prior",
                "historical_neighbors_25",
            ],
        },
        "folds": folds,
        "rows": rows,
        "validation": {"problems": []},
    }


def validate_outcome_oof_artifact(payload: dict) -> list[str]:
    problems: list[str] = []
    unexpected = sorted(set(payload) - TOP_LEVEL_FIELDS)
    if unexpected:
        problems.append(f"unexpected top-level fields: {', '.join(unexpected)}")
    if payload.get("artifact") != "valucast_outcome_oof_scores":
        problems.append("artifact must be valucast_outcome_oof_scores")
    if payload.get("status") != "research_only":
        problems.append("status must be research_only")
    if payload.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version is invalid")
    policy = payload.get("prediction_policy") or {}
    expected_policy = {
        "fold_trained_out_of_fold": True,
        "in_sample_predictions_used": False,
        "todays_model_used": False,
        "consensus_or_third_party_ranks_used": False,
        "feeds_model_score": False,
        "feeds_public_rank": False,
        "feeds_buy_score": False,
    }
    if policy != expected_policy:
        problems.append("prediction_policy violates the research-only OOF contract")
    input_sha = (payload.get("input") or {}).get("sha256")
    if not isinstance(input_sha, str) or len(input_sha) != 64:
        problems.append("input.sha256 must be a 64-character digest")

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        problems.append("rows must be a non-empty list")
        rows = []
    identities: set[tuple] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            problems.append(f"rows[{index}] fields are invalid")
            continue
        identity = (row["test_cohort"], row["mlbam_id"], row["role"])
        if identity in identities:
            problems.append(f"rows[{index}] duplicates an OOF identity")
        identities.add(identity)
        if row["role"] not in {"hitter", "pitcher"}:
            problems.append(f"rows[{index}].role is invalid")
        if not isinstance(row["test_cohort"], int) or not isinstance(
            row["train_cohort_max"], int
        ):
            problems.append(f"rows[{index}] cohort fields must be integers")
        elif row["train_cohort_max"] >= row["test_cohort"]:
            problems.append(f"rows[{index}] trains on or after its test cohort")
        if row["target"] not in {0.0, 0.5, 1.0}:
            problems.append(f"rows[{index}].target is not an ordinal outcome tier")
        for key in ("model_prediction", "prior_prediction", "neighbor_prediction"):
            if not _finite(row[key]):
                problems.append(f"rows[{index}].{key} is not finite")

    folds = payload.get("folds")
    if not isinstance(folds, list) or not folds:
        problems.append("folds must be a non-empty list")
        folds = []
    fold_cohorts = [fold.get("test_cohort") for fold in folds]
    if fold_cohorts != sorted({row.get("test_cohort") for row in rows}):
        problems.append("folds do not cover exactly the cohorts present in rows")
    for fold in folds:
        cohort = fold.get("test_cohort")
        fold_rows = [row for row in rows if row.get("test_cohort") == cohort]
        if fold.get("row_count") != len(fold_rows):
            problems.append(f"fold {cohort} row_count does not match rows")
        if fold.get("identity_sha256") != _identity_hash(fold_rows):
            problems.append(f"fold {cohort} identity_sha256 does not match rows")
        for role in ROLES:
            role_rows = [row for row in fold_rows if row.get("role") == role]
            summary = (fold.get("roles") or {}).get(role) or {}
            if summary.get("row_count") != len(role_rows):
                problems.append(f"fold {cohort} {role} row_count does not match rows")
            if summary.get("identity_sha256") != _identity_hash(role_rows):
                problems.append(
                    f"fold {cohort} {role} identity_sha256 does not match rows"
                )
    return problems


def run_outcome_oof_artifact(
    *,
    input_path: Path = INPUT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    generated_at: str | None = None,
) -> dict:
    input_bytes = input_path.read_bytes()
    contract = load_input_contract(input_path)
    dataset_rows = contract["historical"]["rows"]
    role_rows = {role: outcome_oof_rows(role, dataset_rows) for role in ROLES}
    payload = build_outcome_oof_artifact(
        role_rows,
        input_sha256=hashlib.sha256(input_bytes).hexdigest(),
        generated_at=generated_at,
    )
    problems = validate_outcome_oof_artifact(payload)
    if problems:
        raise ValueError("; ".join(problems))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "row_count": len(payload["rows"]),
        "folds": [fold["test_cohort"] for fold in payload["folds"]],
    }
