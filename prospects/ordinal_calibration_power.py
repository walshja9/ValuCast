"""Registered ordinal-calibration OOF design and simulation power study."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.rank_backtest import _fold_board_scores
from prospects.universal import INPUT_PATH, load_input_contract

ROOT = Path(__file__).resolve().parents[1]
OOF_ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_ordinal_oof_scores.json"
FOLD_YEARS = (2018, 2019, 2021)
REGISTRATION_COMMIT = "13c3730ada59f2441ecda06f187f2f5377a70535"
ROW_FIELDS = {
    "mlbam_id",
    "outcome_tier",
    "role",
    "served_score",
    "test_cohort",
    "train_cohort_max",
}
TOP_LEVEL_FIELDS = {
    "artifact",
    "folds",
    "generated_at",
    "input",
    "prediction_policy",
    "registration",
    "registration_commit",
    "rows",
    "schema_version",
    "status",
    "validation",
}


def _generated_at(value: str | None) -> str:
    return value or datetime.now(timezone.utc).isoformat()


def _identity_hash(rows: list[dict]) -> str:
    identities = sorted(f"{row['mlbam_id']}|{row['role']}" for row in rows)
    return hashlib.sha256("\n".join(identities).encode("utf-8")).hexdigest()


def build_oof_score_artifact(
    fold_results: list[tuple[int, dict, dict]],
    *,
    input_sha256: str,
    generated_at: str | None = None,
) -> dict:
    rows = []
    folds = []
    for cohort, data, diagnostics in sorted(fold_results):
        fold_rows = [
            {
                "test_cohort": cohort,
                "train_cohort_max": cohort - 4,
                "mlbam_id": mlbam_id,
                "role": role,
                "served_score": float(score),
                "outcome_tier": float(data["tiers"][(mlbam_id, role)]),
            }
            for (mlbam_id, role), score in sorted(data["scores"].items())
        ]
        roles = {}
        for role in ("hitter", "pitcher"):
            role_rows = [row for row in fold_rows if row["role"] == role]
            roles[role] = {
                "row_count": len(role_rows),
                "identity_sha256": _identity_hash(role_rows),
            }
        folds.append(
            {
                "test_cohort": cohort,
                "train_cohort_max": cohort - 4,
                "row_count": len(fold_rows),
                "identity_sha256": _identity_hash(fold_rows),
                "roles": roles,
                "diagnostics": diagnostics,
            }
        )
        rows.extend(fold_rows)
    payload = {
        "artifact": "valucast_ordinal_oof_scores",
        "schema_version": "1.0.0",
        "status": "research_only",
        "generated_at": _generated_at(generated_at),
        "registration": "plans/028-pitcher-lean-model-fix.md#amendment-3",
        "registration_commit": REGISTRATION_COMMIT,
        "input": {
            "path": "data/prospects/prospect_model_inputs.json",
            "sha256": input_sha256,
        },
        "prediction_policy": {
            "fold_trained_out_of_fold": True,
            "in_sample_predictions_used": False,
            "todays_model_used": False,
            "current_board_rows_used": False,
            "historical_role_terms_fitted": False,
        },
        "folds": folds,
        "rows": rows,
        "validation": {"problems": []},
    }
    return payload


def validate_oof_score_artifact(payload: dict) -> list[str]:
    problems = []
    unexpected = sorted(set(payload) - TOP_LEVEL_FIELDS)
    if unexpected:
        problems.append(f"unexpected top-level fields: {', '.join(unexpected)}")
    if payload.get("artifact") != "valucast_ordinal_oof_scores":
        problems.append("artifact must be valucast_ordinal_oof_scores")
    if payload.get("status") != "research_only":
        problems.append("status must be research_only")
    if payload.get("registration_commit") != REGISTRATION_COMMIT:
        problems.append("registration_commit does not match the pre-result commit")
    policy = payload.get("prediction_policy") or {}
    expected_policy = {
        "fold_trained_out_of_fold": True,
        "in_sample_predictions_used": False,
        "todays_model_used": False,
        "current_board_rows_used": False,
        "historical_role_terms_fitted": False,
    }
    if policy != expected_policy:
        problems.append("prediction_policy violates the registered OOF contract")
    input_sha = (payload.get("input") or {}).get("sha256")
    if not isinstance(input_sha, str) or len(input_sha) != 64:
        problems.append("input.sha256 must be a 64-character digest")

    rows = payload.get("rows")
    if not isinstance(rows, list):
        problems.append("rows must be a list")
        rows = []
    identities = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != ROW_FIELDS:
            problems.append(f"rows[{index}] fields are invalid")
            continue
        identity = (row["test_cohort"], row["mlbam_id"], row["role"])
        if identity in identities:
            problems.append(f"rows[{index}] duplicates an OOF identity")
        identities.add(identity)
        if row["test_cohort"] not in FOLD_YEARS:
            problems.append(f"rows[{index}].test_cohort is not registered")
        if row["train_cohort_max"] != row["test_cohort"] - 4:
            problems.append(f"rows[{index}] is not trained through cohort-4")
        if row["role"] not in {"hitter", "pitcher"}:
            problems.append(f"rows[{index}].role is invalid")
        if row["outcome_tier"] not in {0.0, 0.5, 1.0}:
            problems.append(f"rows[{index}].outcome_tier is invalid")
        if not isinstance(row["served_score"], (int, float)) or not math.isfinite(
            row["served_score"]
        ):
            problems.append(f"rows[{index}].served_score is invalid")

    folds = payload.get("folds")
    if not isinstance(folds, list) or [row.get("test_cohort") for row in folds] != list(
        FOLD_YEARS
    ):
        problems.append("folds must contain exactly 2018, 2019, and 2021")
        folds = []
    for fold in folds:
        cohort = fold["test_cohort"]
        fold_rows = [row for row in rows if row.get("test_cohort") == cohort]
        if fold.get("train_cohort_max") != cohort - 4:
            problems.append(f"fold {cohort} train_cohort_max is invalid")
        if fold.get("row_count") != len(fold_rows):
            problems.append(f"fold {cohort} row_count does not match rows")
        if fold.get("identity_sha256") != _identity_hash(fold_rows):
            problems.append(f"fold {cohort} identity_sha256 does not match rows")
        for role in ("hitter", "pitcher"):
            role_rows = [row for row in fold_rows if row.get("role") == role]
            role_summary = (fold.get("roles") or {}).get(role) or {}
            if role_summary.get("row_count") != len(role_rows):
                problems.append(f"fold {cohort} {role} row_count does not match rows")
            if role_summary.get("identity_sha256") != _identity_hash(role_rows):
                problems.append(
                    f"fold {cohort} {role} identity_sha256 does not match rows"
                )
        diagnostics = fold.get("diagnostics") or {}
        if not all(
            diagnostics.get(key) == len(fold_rows)
            for key in ("pseudo_universe", "board_rows", "scored_and_labeled")
        ):
            problems.append(f"fold {cohort} diagnostics lost OOF rows")
        if diagnostics.get("score_source_counts") != {
            "prospect_model_v0_6": len(fold_rows)
        }:
            problems.append(f"fold {cohort} contains a non-model score source")
    return problems


def run_oof_score_artifact(
    *,
    input_path: Path = INPUT_PATH,
    artifact_path: Path = OOF_ARTIFACT_PATH,
    generated_at: str | None = None,
) -> dict:
    input_bytes = input_path.read_bytes()
    contract = load_input_contract(input_path)
    fold_results = []
    for cohort in FOLD_YEARS:
        data, diagnostics = _fold_board_scores(contract, cohort, None)
        fold_results.append((cohort, data, diagnostics))
    payload = build_oof_score_artifact(
        fold_results,
        input_sha256=hashlib.sha256(input_bytes).hexdigest(),
        generated_at=generated_at,
    )
    problems = validate_oof_score_artifact(payload)
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
        "folds": payload["folds"],
    }
