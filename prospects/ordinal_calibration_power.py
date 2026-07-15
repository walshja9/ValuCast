"""Registered ordinal-calibration OOF design and simulation power study."""

from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import chi2

from prospects.rank_backtest import _fold_board_scores
from prospects.universal import INPUT_PATH, load_input_contract

ROOT = Path(__file__).resolve().parents[1]
OOF_ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_ordinal_oof_scores.json"
RANK_ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
EFFECT_ANCHOR_ARTIFACT_PATH = (
    ROOT / "data" / "models" / "valucast_ordinal_effect_anchor.json"
)
POWER_ARTIFACT_PATH = (
    ROOT / "data" / "models" / "valucast_ordinal_calibration_power.json"
)
FOLD_YEARS = (2018, 2019, 2021)
REGISTRATION_COMMIT = "13c3730ada59f2441ecda06f187f2f5377a70535"
POWER_REGISTRATION_COMMIT = "f7eaf83fca1d12c19cb294d1130c1672ac9b5e33"
EFFECT_ANCHOR_REGISTRATION_COMMIT = "eecb96c131ab19608506947d45207ff9899a1091"
SIMULATION_SEED = 28015
N_SIMULATIONS = 1_000
LRT_DEGREES_OF_FREEDOM = 2
LRT_ALPHA = 0.05
POWER_FLOOR = 0.70
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
POWER_TOP_LEVEL_FIELDS = {
    "artifact",
    "design",
    "generated_at",
    "historical_fit",
    "oof_artifact",
    "promotion",
    "protocol",
    "registration",
    "registration_commit",
    "scenarios",
    "schema_version",
    "status",
    "validation",
}
EFFECT_ANCHOR_TOP_LEVEL_FIELDS = {
    "artifact",
    "derivation",
    "generated_at",
    "historical_fit",
    "inputs",
    "nuisance_fit",
    "registration",
    "registration_commit",
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


def _ordered_probabilities(params: np.ndarray, design: np.ndarray) -> np.ndarray:
    cut0 = float(params[0])
    cut1 = cut0 + math.exp(float(params[1]))
    eta = design @ params[2:]
    cumulative0 = expit(cut0 - eta)
    cumulative1 = expit(cut1 - eta)
    return np.column_stack(
        (cumulative0, cumulative1 - cumulative0, 1.0 - cumulative1)
    )


def _objective_and_gradient(
    params: np.ndarray, design: np.ndarray, outcomes: np.ndarray
) -> tuple[float, np.ndarray]:
    cut0 = float(params[0])
    gap = math.exp(float(params[1]))
    cut1 = cut0 + gap
    eta = design @ params[2:]
    cumulative0 = expit(cut0 - eta)
    cumulative1 = expit(cut1 - eta)
    q0 = cumulative0 * (1.0 - cumulative0)
    q1 = cumulative1 * (1.0 - cumulative1)

    probabilities = np.empty(len(outcomes), dtype=float)
    derivative_cut0 = np.empty(len(outcomes), dtype=float)
    derivative_log_gap = np.empty(len(outcomes), dtype=float)
    derivative_eta_factor = np.empty(len(outcomes), dtype=float)
    bust = outcomes == 0
    role = outcomes == 1
    star = outcomes == 2
    probabilities[bust] = cumulative0[bust]
    derivative_cut0[bust] = q0[bust]
    derivative_log_gap[bust] = 0.0
    derivative_eta_factor[bust] = -q0[bust]
    probabilities[role] = cumulative1[role] - cumulative0[role]
    derivative_cut0[role] = q1[role] - q0[role]
    derivative_log_gap[role] = q1[role] * gap
    derivative_eta_factor[role] = q0[role] - q1[role]
    probabilities[star] = 1.0 - cumulative1[star]
    derivative_cut0[star] = -q1[star]
    derivative_log_gap[star] = -q1[star] * gap
    derivative_eta_factor[star] = q1[star]

    probabilities = np.maximum(probabilities, 1e-12)
    inverse = 1.0 / probabilities
    gradient = np.concatenate(
        (
            np.array(
                [
                    -np.sum(derivative_cut0 * inverse),
                    -np.sum(derivative_log_gap * inverse),
                ]
            ),
            -(design.T @ (derivative_eta_factor * inverse)),
        )
    )
    return -float(np.log(probabilities).sum()), gradient


def _initial_parameters(outcomes: np.ndarray, column_count: int) -> np.ndarray:
    count = len(outcomes)
    cumulative0 = np.clip((np.count_nonzero(outcomes == 0) + 0.5) / (count + 1), 1e-6, 1 - 1e-6)
    cumulative1 = np.clip((np.count_nonzero(outcomes <= 1) + 0.5) / (count + 1), 1e-6, 1 - 1e-6)
    cut0 = math.log(cumulative0 / (1.0 - cumulative0))
    cut1 = math.log(cumulative1 / (1.0 - cumulative1))
    return np.concatenate(
        (np.array([cut0, math.log(max(cut1 - cut0, 0.1))]), np.zeros(column_count))
    )


def _fit_ordered_logit(
    design: np.ndarray,
    outcomes: np.ndarray,
    initial: np.ndarray | None = None,
) -> dict:
    initial = (
        np.asarray(initial, dtype=float)
        if initial is not None
        else _initial_parameters(outcomes, design.shape[1])
    )
    bounds = [(-12.0, 12.0), (-6.0, 4.0)] + [(-12.0, 12.0)] * design.shape[1]
    result = minimize(
        _objective_and_gradient,
        initial,
        args=(design, outcomes),
        method="L-BFGS-B",
        jac=True,
        bounds=bounds,
        options={"ftol": 1e-10, "gtol": 1e-6, "maxiter": 300},
    )
    if not result.success or not math.isfinite(float(result.fun)):
        raise RuntimeError(f"ordered-logit optimization failed: {result.message}")
    return {
        "params": np.asarray(result.x, dtype=float),
        "log_likelihood": -float(result.fun),
        "iterations": int(result.nit),
    }


def likelihood_ratio_test(
    blind_design: np.ndarray,
    pitcher: np.ndarray,
    outcomes: np.ndarray,
    *,
    blind_initial: np.ndarray | None = None,
) -> dict:
    blind_fit = _fit_ordered_logit(blind_design, outcomes, blind_initial)
    full_design = np.column_stack(
        (blind_design, pitcher, pitcher * blind_design[:, 0])
    )
    full_initial = np.concatenate(
        (blind_fit["params"][:2], blind_fit["params"][2:], np.zeros(2))
    )
    full_fit = _fit_ordered_logit(full_design, outcomes, full_initial)
    statistic = max(
        0.0,
        2.0 * (full_fit["log_likelihood"] - blind_fit["log_likelihood"]),
    )
    return {
        "statistic": statistic,
        "p_value": float(chi2.sf(statistic, LRT_DEGREES_OF_FREEDOM)),
        "degrees_of_freedom": LRT_DEGREES_OF_FREEDOM,
    }


def _expected_tier(probabilities: np.ndarray) -> np.ndarray:
    return 0.5 * probabilities[:, 1] + probabilities[:, 2]


def _expected_tier_gap(
    nuisance_params: np.ndarray,
    blind_design: np.ndarray,
    pitcher_intercept: float,
    pitcher_score_slope: float,
) -> np.ndarray:
    hitter = _expected_tier(_ordered_probabilities(nuisance_params, blind_design))
    pitcher_params = np.concatenate(
        (nuisance_params, [pitcher_intercept, pitcher_score_slope])
    )
    pitcher_design = np.column_stack(
        (
            blind_design,
            np.ones(len(blind_design)),
            blind_design[:, 0],
        )
    )
    pitcher = _expected_tier(_ordered_probabilities(pitcher_params, pitcher_design))
    return pitcher - hitter


def _relative_expected_tier_reduction(
    nuisance_params: np.ndarray,
    blind_support: np.ndarray,
    pitcher_intercept: float,
) -> float:
    hitter = _expected_tier(_ordered_probabilities(nuisance_params, blind_support))
    pitcher = hitter + _expected_tier_gap(
        nuisance_params, blind_support, pitcher_intercept, 0.0
    )
    hitter_mean = float(hitter.mean())
    if hitter_mean <= 0.0:
        raise ValueError("common-support hitter expected tier must be positive")
    return 1.0 - float(pitcher.mean()) / hitter_mean


def _calibrate_intercept_effect(
    nuisance_params: np.ndarray,
    blind_support: np.ndarray,
    target_relative_reduction: float | None = None,
) -> float:
    if target_relative_reduction is None:
        raise ValueError("Amendment 6 requires a committed relative-effect target")
    if not 0.0 < target_relative_reduction <= 1.0:
        raise ValueError("relative-effect target must be in (0, 1]")
    lower, upper = -20.0, 0.0
    if (
        _relative_expected_tier_reduction(nuisance_params, blind_support, lower)
        < target_relative_reduction
    ):
        raise ValueError("intercept search range cannot reach the registered target")
    for _ in range(80):
        midpoint = (lower + upper) / 2.0
        reduction = _relative_expected_tier_reduction(
            nuisance_params, blind_support, midpoint
        )
        if reduction < target_relative_reduction:
            upper = midpoint
        else:
            lower = midpoint
    return (lower + upper) / 2.0


def _calibrate_slope_effect(
    nuisance_params: np.ndarray, blind_support: np.ndarray
) -> float:
    lower, upper = 0.0, 20.0

    def rms(magnitude: float) -> float:
        gap = _expected_tier_gap(
            nuisance_params, blind_support, 0.0, -magnitude
        )
        return float(np.sqrt(np.mean(np.square(gap))))

    if rms(upper) < 0.10:
        raise ValueError("slope search range cannot reach the registered target")
    for _ in range(80):
        midpoint = (lower + upper) / 2.0
        if rms(midpoint) < 0.10:
            lower = midpoint
        else:
            upper = midpoint
    return -(lower + upper) / 2.0


def _design_from_oof(payload: dict) -> dict:
    rows = payload["rows"]
    score = np.array([(float(row["served_score"]) - 50.0) / 10.0 for row in rows])
    cohorts = np.array([row["test_cohort"] for row in rows])
    pitcher = np.array([row["role"] == "pitcher" for row in rows], dtype=float)
    outcomes = np.array([round(float(row["outcome_tier"]) * 2) for row in rows], dtype=int)
    blind_design = np.column_stack((score, cohorts == 2019, cohorts == 2021)).astype(float)
    support = np.zeros(len(rows), dtype=bool)
    support_ranges = {}
    for cohort in FOLD_YEARS:
        fold = cohorts == cohort
        hitter_scores = score[fold & (pitcher == 0)]
        pitcher_scores = score[fold & (pitcher == 1)]
        lower = max(float(hitter_scores.min()), float(pitcher_scores.min()))
        upper = min(float(hitter_scores.max()), float(pitcher_scores.max()))
        if lower > upper:
            raise ValueError(f"fold {cohort} has no cross-role score support")
        support |= fold & (score >= lower) & (score <= upper)
        support_ranges[str(cohort)] = {
            "normalized_score_min": lower,
            "normalized_score_max": upper,
        }
    return {
        "blind_design": blind_design,
        "pitcher": pitcher,
        "outcomes": outcomes,
        "support": support,
        "support_ranges": support_ranges,
    }


def _scenario_probabilities(
    nuisance_params: np.ndarray,
    blind_design: np.ndarray,
    pitcher: np.ndarray,
    intercept: float,
    slope: float,
) -> np.ndarray:
    full_design = np.column_stack(
        (blind_design, pitcher, pitcher * blind_design[:, 0])
    )
    full_params = np.concatenate((nuisance_params, [intercept, slope]))
    return _ordered_probabilities(full_params, full_design)


def _simulate_scenario(
    *,
    nuisance_params: np.ndarray,
    blind_design: np.ndarray,
    pitcher: np.ndarray,
    intercept: float,
    slope: float,
    rng: np.random.Generator,
    n_simulations: int,
    progress=None,
) -> int:
    probabilities = _scenario_probabilities(
        nuisance_params, blind_design, pitcher, intercept, slope
    )
    rejections = 0
    for simulation in range(1, n_simulations + 1):
        draws = rng.random(len(blind_design))
        outcomes = (draws > probabilities[:, 0]).astype(int)
        outcomes += (draws > probabilities[:, :2].sum(axis=1)).astype(int)
        result = likelihood_ratio_test(
            blind_design,
            pitcher,
            outcomes,
            blind_initial=nuisance_params,
        )
        rejections += int(result["p_value"] < LRT_ALPHA)
        if progress and (simulation % 100 == 0 or simulation == n_simulations):
            progress(simulation, n_simulations, rejections)
    return rejections


def _board_pitcher_count(
    rows: list[dict],
    expected_tiers: np.ndarray,
    relative_reduction: float,
    top_n: int,
) -> int:
    adjusted = np.asarray(expected_tiers, dtype=float).copy()
    for index, row in enumerate(rows):
        if row["role"] == "pitcher":
            adjusted[index] *= 1.0 - relative_reduction
    order = sorted(
        range(len(rows)),
        key=lambda index: (
            -float(adjusted[index]),
            rows[index]["rank"],
            rows[index]["mlbam_id"],
            rows[index]["role"],
        ),
    )[:top_n]
    return sum(rows[index]["role"] == "pitcher" for index in order)


def _derive_board_anchor(
    rows: list[dict],
    expected_tiers: np.ndarray,
    *,
    top_n: int = 25,
    max_pitchers: int = 7,
) -> dict:
    if len(rows) != len(expected_tiers) or len(rows) < top_n:
        raise ValueError("board rows and expected tiers must cover the requested top N")
    before = _board_pitcher_count(rows, expected_tiers, 0.0, top_n)
    fallback = 0.50
    if _board_pitcher_count(rows, expected_tiers, 1.0, top_n) > max_pitchers:
        selected = fallback
        fallback_used = True
    else:
        lower, upper = 0.0, 1.0
        for _ in range(80):
            midpoint = (lower + upper) / 2.0
            if (
                _board_pitcher_count(rows, expected_tiers, midpoint, top_n)
                <= max_pitchers
            ):
                upper = midpoint
            else:
                lower = midpoint
        selected = math.ceil(upper * 1_000_000_000_000) / 1_000_000_000_000
        fallback_used = False
    after = _board_pitcher_count(rows, expected_tiers, selected, top_n)
    return {
        "top_n": top_n,
        "max_pitchers": max_pitchers,
        "before_pitcher_count": before,
        "before_hitter_count": top_n - before,
        "after_pitcher_count": after,
        "after_hitter_count": top_n - after,
        "relative_reduction": selected,
        "fallback_relative_reduction": fallback,
        "fallback_used": fallback_used,
    }


def _parameter_sha256(params: np.ndarray) -> str:
    values = [round(float(value), 12) for value in params]
    encoded = json.dumps(values, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _derive_effect_anchor_inputs(oof_payload: dict, rank_payload: dict) -> dict:
    oof_problems = validate_oof_score_artifact(oof_payload)
    if oof_problems:
        raise ValueError("; ".join(oof_problems))
    design = _design_from_oof(oof_payload)
    nuisance = _fit_ordered_logit(
        design["blind_design"], design["outcomes"]
    )["params"]
    board = rank_payload.get("board")
    if not isinstance(board, list):
        raise ValueError("rank artifact board must be a list")
    rows = []
    scores = []
    for row in board:
        score = (row.get("components") or {}).get("model_score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
        ):
            continue
        if (
            row.get("role") not in {"hitter", "pitcher"}
            or not isinstance(row.get("rank"), int)
            or not isinstance(row.get("mlbam_id"), int)
        ):
            raise ValueError("rank artifact model-component row is invalid")
        rows.append(
            {
                "rank": row["rank"],
                "mlbam_id": row["mlbam_id"],
                "role": row["role"],
            }
        )
        scores.append((float(score) - 50.0) / 10.0)
    normalized_scores = np.asarray(scores, dtype=float)
    expected_tiers = np.zeros(len(rows), dtype=float)
    fold_weights = {}
    total = len(oof_payload["rows"])
    for cohort in FOLD_YEARS:
        count = sum(row["test_cohort"] == cohort for row in oof_payload["rows"])
        weight = count / total
        fold_design = np.column_stack(
            (
                normalized_scores,
                np.full(len(rows), cohort == 2019),
                np.full(len(rows), cohort == 2021),
            )
        ).astype(float)
        expected_tiers += weight * _expected_tier(
            _ordered_probabilities(nuisance, fold_design)
        )
        fold_weights[str(cohort)] = {
            "row_count": count,
            "weight": round(weight, 9),
        }
    derivation = _derive_board_anchor(rows, expected_tiers)
    if derivation["before_pitcher_count"] != 13:
        raise ValueError("outcome-blind derivation did not reproduce 13 pitchers")
    return {
        "oof_row_count": total,
        "rank_row_count": len(rows),
        "fold_weights": fold_weights,
        "nuisance_parameter_sha256": _parameter_sha256(nuisance),
        "derivation": derivation,
    }


def build_effect_anchor_artifact(
    *,
    oof_sha256: str,
    rank_sha256: str,
    oof_row_count: int,
    rank_row_count: int,
    fold_weights: dict,
    nuisance_parameter_sha256: str,
    derivation: dict,
    generated_at: str | None = None,
) -> dict:
    return {
        "artifact": "valucast_ordinal_effect_anchor",
        "schema_version": "1.0.0",
        "status": "registered_target",
        "generated_at": _generated_at(generated_at),
        "registration": "plans/028-pitcher-lean-model-fix.md#amendment-6",
        "registration_commit": EFFECT_ANCHOR_REGISTRATION_COMMIT,
        "inputs": {
            "oof_artifact": {
                "path": "data/models/valucast_ordinal_oof_scores.json",
                "sha256": oof_sha256,
                "row_count": oof_row_count,
            },
            "rank_artifact": {
                "path": "data/models/valucast_prospect_rank_v1.json",
                "sha256": rank_sha256,
                "model_component_field": "components.model_score",
                "eligible_row_count": rank_row_count,
            },
        },
        "nuisance_fit": {
            "model": "role_blind_proportional_odds_logit",
            "score_transform": "(score - 50) / 10",
            "fold_fixed_effects": [2019, 2021],
            "fold_weights": fold_weights,
            "parameter_sha256": nuisance_parameter_sha256,
            "role_conditional_outcomes_used": False,
        },
        "derivation": {
            **derivation,
            "metric": "relative_common_support_expected_tier_reduction",
            "ranking": (
                "adjusted_expected_tier_desc_then_served_rank_asc_then_"
                "mlbam_id_asc_then_role_asc"
            ),
        },
        "historical_fit": {
            "pitcher_intercept_fitted": False,
            "pitcher_score_slope_fitted": False,
            "historical_role_coefficients_reported": False,
        },
        "validation": {"problems": []},
    }


def validate_effect_anchor_artifact(
    payload: dict,
    *,
    oof_bytes: bytes | None = None,
    rank_bytes: bytes | None = None,
) -> list[str]:
    problems = []
    unexpected = sorted(set(payload) - EFFECT_ANCHOR_TOP_LEVEL_FIELDS)
    if unexpected:
        problems.append(f"unexpected top-level fields: {', '.join(unexpected)}")
    if payload.get("artifact") != "valucast_ordinal_effect_anchor":
        problems.append("artifact must be valucast_ordinal_effect_anchor")
    if payload.get("status") != "registered_target":
        problems.append("status must be registered_target")
    if payload.get("registration_commit") != EFFECT_ANCHOR_REGISTRATION_COMMIT:
        problems.append("registration_commit does not match Amendment 6")
    inputs = payload.get("inputs") or {}
    oof_input = inputs.get("oof_artifact") or {}
    rank_input = inputs.get("rank_artifact") or {}
    if oof_bytes is not None and oof_input.get("sha256") != hashlib.sha256(
        oof_bytes
    ).hexdigest():
        problems.append("oof_artifact.sha256 does not match the committed input")
    if rank_bytes is not None and rank_input.get("sha256") != hashlib.sha256(
        rank_bytes
    ).hexdigest():
        problems.append("rank_artifact.sha256 does not match the committed input")
    nuisance = payload.get("nuisance_fit") or {}
    if nuisance.get("role_conditional_outcomes_used") is not False:
        problems.append("anchor derivation must remain role-outcome blind")
    if nuisance.get("model") != "role_blind_proportional_odds_logit":
        problems.append("nuisance model is invalid")
    if nuisance.get("score_transform") != "(score - 50) / 10":
        problems.append("nuisance score transform is invalid")
    if nuisance.get("fold_fixed_effects") != [2019, 2021]:
        problems.append("nuisance fold fixed effects are invalid")
    parameter_sha = nuisance.get("parameter_sha256")
    if not isinstance(parameter_sha, str) or len(parameter_sha) != 64:
        problems.append("nuisance parameter_sha256 must be a 64-character digest")
    derivation = payload.get("derivation") or {}
    if derivation.get("top_n") != 25 or derivation.get("before_pitcher_count") != 13:
        problems.append("derivation must start from the committed 13-pitcher top 25")
    if derivation.get("max_pitchers") != 7:
        problems.append("derivation must target the seven-pitcher limit")
    reduction = derivation.get("relative_reduction")
    if (
        isinstance(reduction, bool)
        or not isinstance(reduction, (int, float))
        or not 0.0 <= reduction <= 1.0
    ):
        problems.append("relative_reduction must be in [0, 1]")
    if derivation.get("metric") != "relative_common_support_expected_tier_reduction":
        problems.append("derivation metric is invalid")
    historical = payload.get("historical_fit") or {}
    if historical != {
        "pitcher_intercept_fitted": False,
        "pitcher_score_slope_fitted": False,
        "historical_role_coefficients_reported": False,
    }:
        problems.append("historical pitcher terms must remain unfit and unreported")
    if oof_bytes is not None and rank_bytes is not None and not problems:
        expected = _derive_effect_anchor_inputs(
            json.loads(oof_bytes), json.loads(rank_bytes)
        )
        if nuisance.get("fold_weights") != expected["fold_weights"]:
            problems.append("fold_weights do not match the committed OOF rows")
        if parameter_sha != expected["nuisance_parameter_sha256"]:
            problems.append("nuisance parameter hash does not match the committed fit")
        expected_derivation = {
            **expected["derivation"],
            "metric": "relative_common_support_expected_tier_reduction",
            "ranking": (
                "adjusted_expected_tier_desc_then_served_rank_asc_then_"
                "mlbam_id_asc_then_role_asc"
            ),
        }
        if derivation != expected_derivation:
            problems.append("derivation does not match the committed inputs")
    return problems


def run_effect_anchor_artifact(
    *,
    oof_path: Path = OOF_ARTIFACT_PATH,
    rank_path: Path = RANK_ARTIFACT_PATH,
    artifact_path: Path = EFFECT_ANCHOR_ARTIFACT_PATH,
    generated_at: str | None = None,
) -> dict:
    oof_bytes = oof_path.read_bytes()
    rank_bytes = rank_path.read_bytes()
    derived = _derive_effect_anchor_inputs(
        json.loads(oof_bytes), json.loads(rank_bytes)
    )
    payload = build_effect_anchor_artifact(
        oof_sha256=hashlib.sha256(oof_bytes).hexdigest(),
        rank_sha256=hashlib.sha256(rank_bytes).hexdigest(),
        generated_at=generated_at,
        **derived,
    )
    problems = validate_effect_anchor_artifact(
        payload, oof_bytes=oof_bytes, rank_bytes=rank_bytes
    )
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
        "derivation": payload["derivation"],
        "nuisance_fit": payload["nuisance_fit"],
    }


def build_power_artifact(
    *,
    oof_sha256: str,
    row_count: int,
    common_support_count: int,
    scenario_results: dict,
    support_ranges: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    scenarios = {}
    for name in ("intercept_penalty", "slope_interaction"):
        result = scenario_results[name]
        power = result["rejections"] / N_SIMULATIONS
        scenarios[name] = {
            **result,
            "simulations": N_SIMULATIONS,
            "power": round(power, 6),
            "power_floor": POWER_FLOOR,
            "passed": power >= POWER_FLOOR,
        }
    authorized = all(row["passed"] for row in scenarios.values())
    return {
        "artifact": "valucast_ordinal_calibration_power",
        "schema_version": "1.0.0",
        "status": "powered" if authorized else "underpowered",
        "generated_at": _generated_at(generated_at),
        "registration": "plans/028-pitcher-lean-model-fix.md#amendment-5",
        "registration_commit": POWER_REGISTRATION_COMMIT,
        "oof_artifact": {
            "path": "data/models/valucast_ordinal_oof_scores.json",
            "sha256": oof_sha256,
            "row_count": row_count,
        },
        "protocol": {
            "seed": SIMULATION_SEED,
            "simulations_per_scenario": N_SIMULATIONS,
            "lrt_degrees_of_freedom": LRT_DEGREES_OF_FREEDOM,
            "alpha": LRT_ALPHA,
            "power_floor": POWER_FLOOR,
            "score_transform": "(served_score - 50) / 10",
            "scenario_order": ["intercept_penalty", "slope_interaction"],
        },
        "design": {
            "row_count": row_count,
            "common_support_count": common_support_count,
            "common_support": "fold_role_range_intersection_pooled_equal_weight",
            "support_ranges": support_ranges or {},
        },
        "scenarios": scenarios,
        "historical_fit": {
            "role_blind_nuisance_fitted": True,
            "pitcher_intercept_fitted": False,
            "pitcher_score_slope_fitted": False,
            "historical_role_coefficients_reported": False,
        },
        "promotion": {
            "historical_look_authorized": authorized,
            "next_step": (
                "request_separate_look_approval" if authorized else "stop_underpowered"
            ),
        },
        "validation": {"problems": []},
    }


def validate_power_artifact(payload: dict, *, oof_bytes: bytes | None = None) -> list[str]:
    problems = []
    unexpected = sorted(set(payload) - POWER_TOP_LEVEL_FIELDS)
    if unexpected:
        problems.append(f"unexpected top-level fields: {', '.join(unexpected)}")
    if payload.get("artifact") != "valucast_ordinal_calibration_power":
        problems.append("artifact must be valucast_ordinal_calibration_power")
    if payload.get("registration_commit") != POWER_REGISTRATION_COMMIT:
        problems.append("registration_commit does not match the pre-result commit")
    expected_protocol = {
        "seed": SIMULATION_SEED,
        "simulations_per_scenario": N_SIMULATIONS,
        "lrt_degrees_of_freedom": LRT_DEGREES_OF_FREEDOM,
        "alpha": LRT_ALPHA,
        "power_floor": POWER_FLOOR,
        "score_transform": "(served_score - 50) / 10",
        "scenario_order": ["intercept_penalty", "slope_interaction"],
    }
    if payload.get("protocol") != expected_protocol:
        problems.append("protocol does not match the registered simulation")
    oof = payload.get("oof_artifact") or {}
    if oof_bytes is not None and oof.get("sha256") != hashlib.sha256(oof_bytes).hexdigest():
        problems.append("oof_artifact.sha256 does not match the committed input")
    scenarios = payload.get("scenarios") or {}
    if set(scenarios) != {"intercept_penalty", "slope_interaction"}:
        problems.append("scenarios do not match the registered pair")
        scenarios = {}
    for name, expected_target in (
        ("intercept_penalty", -0.10),
        ("slope_interaction", 0.10),
    ):
        row = scenarios.get(name) or {}
        rejections = row.get("rejections")
        if row.get("target") != expected_target:
            problems.append(f"{name}.target is invalid")
        if row.get("simulations") != N_SIMULATIONS:
            problems.append(f"{name}.simulations is invalid")
        if not isinstance(rejections, int) or not 0 <= rejections <= N_SIMULATIONS:
            problems.append(f"{name}.rejections is invalid")
            continue
        power = rejections / N_SIMULATIONS
        if row.get("power") != round(power, 6):
            problems.append(f"{name}.power does not match rejections")
        if row.get("passed") is not (power >= POWER_FLOOR):
            problems.append(f"{name}.passed does not match the power floor")
    historical = payload.get("historical_fit") or {}
    if historical != {
        "role_blind_nuisance_fitted": True,
        "pitcher_intercept_fitted": False,
        "pitcher_score_slope_fitted": False,
        "historical_role_coefficients_reported": False,
    }:
        problems.append("historical pitcher terms must remain unfit and unreported")
    authorized = bool(scenarios) and all(row.get("passed") is True for row in scenarios.values())
    expected_status = "powered" if authorized else "underpowered"
    if payload.get("status") != expected_status:
        problems.append("status does not match scenario power")
    if (payload.get("promotion") or {}).get("historical_look_authorized") is not authorized:
        problems.append("historical_look_authorized does not match scenario power")
    return problems


def run_power_artifact(
    *,
    oof_path: Path = OOF_ARTIFACT_PATH,
    artifact_path: Path = POWER_ARTIFACT_PATH,
    generated_at: str | None = None,
    progress=None,
) -> dict:
    oof_bytes = oof_path.read_bytes()
    oof_payload = json.loads(oof_bytes)
    oof_problems = validate_oof_score_artifact(oof_payload)
    if oof_problems:
        raise ValueError("; ".join(oof_problems))
    design = _design_from_oof(oof_payload)
    blind_design = design["blind_design"]
    pitcher = design["pitcher"]
    nuisance = _fit_ordered_logit(blind_design, design["outcomes"])["params"]
    blind_support = blind_design[design["support"]]
    intercept = _calibrate_intercept_effect(nuisance, blind_support)
    slope = _calibrate_slope_effect(nuisance, blind_support)
    intercept_gap = _expected_tier_gap(nuisance, blind_support, intercept, 0.0)
    slope_gap = _expected_tier_gap(nuisance, blind_support, 0.0, slope)
    rng = np.random.default_rng(SIMULATION_SEED)

    def run_one(name: str, intercept_effect: float, slope_effect: float) -> int:
        return _simulate_scenario(
            nuisance_params=nuisance,
            blind_design=blind_design,
            pitcher=pitcher,
            intercept=intercept_effect,
            slope=slope_effect,
            rng=rng,
            n_simulations=N_SIMULATIONS,
            progress=(
                (lambda done, total, rejected: progress(name, done, total, rejected))
                if progress
                else None
            ),
        )

    scenario_results = {
        "intercept_penalty": {
            "target": -0.10,
            "achieved": round(float(intercept_gap.mean()), 9),
            "injected_effect": round(intercept, 9),
            "rejections": run_one("intercept_penalty", intercept, 0.0),
        },
        "slope_interaction": {
            "target": 0.10,
            "achieved": round(
                float(np.sqrt(np.mean(np.square(slope_gap)))), 9
            ),
            "injected_effect": round(slope, 9),
            "rejections": run_one("slope_interaction", 0.0, slope),
        },
    }
    payload = build_power_artifact(
        oof_sha256=hashlib.sha256(oof_bytes).hexdigest(),
        row_count=len(oof_payload["rows"]),
        common_support_count=int(np.count_nonzero(design["support"])),
        scenario_results=scenario_results,
        support_ranges=design["support_ranges"],
        generated_at=generated_at,
    )
    problems = validate_power_artifact(payload, oof_bytes=oof_bytes)
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
        "status": payload["status"],
        "scenarios": payload["scenarios"],
        "historical_look_authorized": payload["promotion"][
            "historical_look_authorized"
        ],
    }
