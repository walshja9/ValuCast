"""Role-standardized joint ordered-logit calibrator for prospect ladders."""
from __future__ import annotations

import math
import re

import numpy as np

from prospects.ordinal_calibration_power import (
    _expected_tier,
    _fit_ordered_logit,
    _ordered_probabilities,
)
from prospects.prospect_v2_target import canonical_sha256

FIT_KEYS = {
    "mlbam_id",
    "role",
    "source_ladder_position",
    "ladder_score",
    "outcome",
    "target",
    "test_cohort",
}
_FOLDS = (2018, 2019, 2021)
_ROLES = ("hitter", "pitcher")
_OUTCOMES = {"bust": 0, "role": 1, "star": 2}
_TARGETS = {"bust": 0.0, "role": 0.5, "star": 1.0}
_DESIGN = [
    "role_standardized_ladder_score:hitter",
    "role_standardized_ladder_score:pitcher",
    "is_pitcher",
]
_TOP_LEVEL_KEYS = {
    "schema",
    "version",
    "design",
    "params",
    "thresholds",
    "role_slopes",
    "pitcher_offset",
    "role_standardization",
    "row_count",
    "row_count_by_role",
    "training_rows_sha256",
    "iterations",
    "log_likelihood",
    "artifact_sha256",
}


def _number(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def _fit_sort_key(row: dict) -> tuple[int, int, int, int]:
    return (
        _FOLDS.index(row["test_cohort"]),
        _ROLES.index(row["role"]),
        row["source_ladder_position"],
        int(row["mlbam_id"]),
    )


def _sorted_fit_rows(rows: list[dict]) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("role-slope joint fit requires rows")
    projected = []
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != FIT_KEYS:
            raise ValueError("role-slope joint fitting rows must have exact keys")
        try:
            if not isinstance(row["mlbam_id"], int) or isinstance(row["mlbam_id"], bool):
                raise ValueError
            mlbam_id = row["mlbam_id"]
            position = row["source_ladder_position"]
            if isinstance(position, bool):
                raise ValueError
            if mlbam_id < 0 or position <= 0 or int(position) != position:
                raise ValueError
            if row["role"] not in _ROLES or row["outcome"] not in _OUTCOMES:
                raise ValueError
            if row["test_cohort"] not in _FOLDS:
                raise ValueError
            ladder_score = _number(row["ladder_score"])
            target = _number(row["target"])
            if target != _TARGETS[row["outcome"]]:
                raise ValueError
        except (TypeError, ValueError):
            raise ValueError("invalid role-slope joint fitting row") from None
        identity = (mlbam_id, row["role"])
        if identity in identities:
            raise ValueError("duplicate role-slope joint identity")
        identities.add(identity)
        projected.append(
            {
                "mlbam_id": mlbam_id,
                "role": row["role"],
                "source_ladder_position": int(position),
                "ladder_score": ladder_score,
                "outcome": row["outcome"],
                "target": target,
                "test_cohort": row["test_cohort"],
            }
        )
    if set(row["role"] for row in projected) != set(_ROLES):
        raise ValueError("role-slope joint fit requires both roles")
    if set(row["outcome"] for row in projected) != set(_OUTCOMES):
        raise ValueError("role-slope joint fit requires all outcomes")
    return sorted(projected, key=_fit_sort_key)


def _map_problems(mapping: object, rows: list[dict] | None = None) -> list[str]:
    if not isinstance(mapping, dict) or set(mapping) != _TOP_LEVEL_KEYS:
        return ["top-level keys are invalid"]
    problems = []
    if mapping["schema"] != "valucast_prospect_role_slope_joint_ladder_map_v1":
        problems.append("schema is invalid")
    if mapping["version"] != "1.0.0" or mapping["design"] != _DESIGN:
        problems.append("version or design is invalid")
    params = mapping["params"]
    if (
        not isinstance(params, list)
        or len(params) != 5
        or any(type(value) is not float or not math.isfinite(value) for value in params)
    ):
        problems.append("params are invalid")
        params = None
    thresholds = mapping["thresholds"]
    slopes = mapping["role_slopes"]
    standardization = mapping["role_standardization"]
    counts = mapping["row_count_by_role"]
    if (
        not isinstance(thresholds, dict)
        or set(thresholds) != {"bust_role", "role_star"}
        or any(
            type(thresholds.get(key)) is not float or not math.isfinite(thresholds[key])
            for key in ("bust_role", "role_star")
        )
    ):
        problems.append("thresholds are invalid")
    if not isinstance(slopes, dict) or set(slopes) != set(_ROLES):
        problems.append("role slopes are invalid")
    if not isinstance(standardization, dict) or set(standardization) != set(_ROLES):
        problems.append("role standardization is invalid")
    if not isinstance(counts, dict) or set(counts) != set(_ROLES):
        problems.append("role counts are invalid")
    if params is not None:
        try:
            role_star = params[0] + math.exp(params[1])
        except OverflowError:
            problems.append("role-star threshold overflows")
        else:
            if not isinstance(thresholds, dict) or thresholds.get("bust_role") != params[0] or thresholds.get("role_star") != role_star:
                problems.append("thresholds do not match params")
        if not isinstance(slopes, dict) or slopes.get("hitter") != params[2] or slopes.get("pitcher") != params[3]:
            problems.append("role slopes do not match params")
        if mapping["pitcher_offset"] != params[4]:
            problems.append("pitcher offset does not match params")
    if not isinstance(slopes, dict) or any(
        type(slopes.get(role)) is not float or not math.isfinite(slopes[role]) or slopes[role] <= 0
        for role in _ROLES
    ):
        problems.append("role slopes must be positive")
    if type(mapping["pitcher_offset"]) is not float or not math.isfinite(mapping["pitcher_offset"]):
        problems.append("pitcher offset is invalid")
    if not isinstance(standardization, dict):
        pass
    else:
        for role in _ROLES:
            values = standardization.get(role)
            if not isinstance(values, dict) or set(values) != {"mean", "std"} or any(
                type(values.get(key)) is not float or not math.isfinite(values[key])
                for key in ("mean", "std")
            ) or values["std"] <= 0:
                problems.append(f"{role} standardization is invalid")
    if not isinstance(mapping["row_count"], int) or isinstance(mapping["row_count"], bool) or mapping["row_count"] <= 0:
        problems.append("row count is invalid")
    counts_are_valid = (
        isinstance(counts, dict)
        and set(counts) == set(_ROLES)
        and all(
            isinstance(counts[role], int)
            and not isinstance(counts[role], bool)
            and counts[role] > 0
            for role in _ROLES
        )
    )
    if not counts_are_valid or mapping["row_count"] != sum(counts.values()):
        problems.append("role counts do not match row count")
    if not isinstance(mapping["training_rows_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", mapping["training_rows_sha256"]):
        problems.append("training row hash is invalid")
    if not isinstance(mapping["iterations"], int) or isinstance(mapping["iterations"], bool) or mapping["iterations"] < 0:
        problems.append("iterations are invalid")
    if type(mapping["log_likelihood"]) is not float or not math.isfinite(mapping["log_likelihood"]):
        problems.append("log likelihood is invalid")
    unsigned = {key: value for key, value in mapping.items() if key != "artifact_sha256"}
    if not isinstance(mapping["artifact_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", mapping["artifact_sha256"]) or mapping["artifact_sha256"] != canonical_sha256(unsigned):
        problems.append("artifact hash is invalid")
    if rows is not None:
        sorted_rows = _sorted_fit_rows(rows)
        if mapping.get("training_rows_sha256") != canonical_sha256(sorted_rows):
            problems.append("training row hash does not match fitting rows")
    return problems


def fit_role_slope_joint_map(rows: list[dict]) -> dict:
    """Fit the registered five-parameter role-slope ordered-logit map."""
    sorted_rows = _sorted_fit_rows(rows)
    standardization = {}
    design = []
    outcomes = []
    for role in _ROLES:
        role_scores = np.asarray(
            [row["ladder_score"] for row in sorted_rows if row["role"] == role], dtype=float
        )
        mean = float(role_scores.mean())
        std = float(role_scores.std(ddof=0))
        if std <= 0:
            raise ValueError("role-slope joint scale must be positive")
        standardization[role] = {"mean": mean, "std": std}
    for row in sorted_rows:
        role = row["role"]
        z = (row["ladder_score"] - standardization[role]["mean"]) / standardization[role]["std"]
        design.append([z, 0.0, 0.0] if role == "hitter" else [0.0, z, 1.0])
        outcomes.append(_OUTCOMES[row["outcome"]])
    try:
        fitted = _fit_ordered_logit(
            np.asarray(design, dtype=float), np.asarray(outcomes, dtype=int)
        )
    except RuntimeError as error:
        raise ValueError(str(error)) from error
    params = [float(value) for value in fitted["params"]]
    if params[2] <= 0 or params[3] <= 0:
        raise ValueError("role-slope joint slopes must be positive")
    mapping = {
        "schema": "valucast_prospect_role_slope_joint_ladder_map_v1",
        "version": "1.0.0",
        "design": _DESIGN,
        "params": params,
        "thresholds": {"bust_role": params[0], "role_star": params[0] + math.exp(params[1])},
        "role_slopes": {"hitter": params[2], "pitcher": params[3]},
        "pitcher_offset": params[4],
        "role_standardization": standardization,
        "row_count": len(sorted_rows),
        "row_count_by_role": {role: sum(row["role"] == role for row in sorted_rows) for role in _ROLES},
        "training_rows_sha256": canonical_sha256(sorted_rows),
        "iterations": int(fitted["iterations"]),
        "log_likelihood": float(fitted["log_likelihood"]),
    }
    mapping["artifact_sha256"] = canonical_sha256(mapping)
    problems = _map_problems(mapping, sorted_rows)
    if problems:
        raise ValueError("invalid role-slope joint map: " + "; ".join(problems))
    return mapping


def _score_ladder(rows: list[dict], role: str, mapping: dict) -> list[dict]:
    if not isinstance(rows, list):
        raise ValueError("role-slope joint ladder must be a list")
    standardization = mapping["role_standardization"][role]
    params = np.asarray(mapping["params"], dtype=float)
    scored = []
    identities = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("role") != role:
            raise ValueError("role-slope joint ladder role is invalid")
        try:
            if not isinstance(row["mlbam_id"], int) or isinstance(row["mlbam_id"], bool):
                raise ValueError
            identity = row["mlbam_id"]
            position = row["source_ladder_position"]
            if isinstance(position, bool) or identity < 0 or position <= 0 or int(position) != position:
                raise ValueError
            score = _number(row["ladder_score"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("role-slope joint ladder row is invalid") from None
        if identity in identities:
            raise ValueError("duplicate role-slope joint ladder identity")
        identities.add(identity)
        z = (score - standardization["mean"]) / standardization["std"]
        design = [z, 0.0, 0.0] if role == "hitter" else [0.0, z, 1.0]
        probability = _ordered_probabilities(params, np.asarray([design], dtype=float))[0]
        if not np.isfinite(probability).all() or np.any(probability < 0) or np.any(probability > 1) or not math.isclose(float(probability.sum()), 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("role-slope joint probabilities are invalid")
        expected = float(_expected_tier(probability.reshape(1, 3))[0])
        if not math.isfinite(expected):
            raise ValueError("role-slope joint expected tier is invalid")
        scored.append(
            {
                **row,
                "tier_probabilities": {"bust": float(probability[0]), "role": float(probability[1]), "star": float(probability[2])},
                "calibrated_expected_tier": expected,
                "calibrator_version": mapping["version"],
                "calibrator_sha256": mapping["artifact_sha256"],
                "final_score": expected,
            }
        )
    ordered = sorted(scored, key=lambda row: (row["source_ladder_position"], row["mlbam_id"]))
    if any(
        left["calibrated_expected_tier"] < right["calibrated_expected_tier"]
        for left, right in zip(ordered, ordered[1:])
    ):
        raise ValueError("role-slope joint ladder inversion")
    return scored


def score_role_slope_joint_ladders(
    hitters: list[dict], pitchers: list[dict], mapping: dict
) -> list[dict]:
    """Score source ladders and return their deterministic combined board order."""
    problems = _map_problems(mapping)
    if problems:
        raise ValueError("invalid role-slope joint map: " + "; ".join(problems))
    scored = [*_score_ladder(hitters, "hitter", mapping), *_score_ladder(pitchers, "pitcher", mapping)]
    keys = [(int(row["mlbam_id"]), row["role"]) for row in scored]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate role-slope joint identity")
    scored.sort(key=lambda row: (-row["calibrated_expected_tier"], row["source_ladder_position"], int(row["mlbam_id"])))
    return [{**row, "rank": rank} for rank, row in enumerate(scored, 1)]
