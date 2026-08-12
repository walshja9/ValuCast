"""Deterministic fold-trained calibration onto a shared factual target."""
from __future__ import annotations

import bisect
import copy
import hashlib
import json
import math
from collections.abc import Iterable, Sequence
from typing import Any


VERSION = "isotonic_piecewise_linear_v1"


class CalibrationError(ValueError):
    """Raised when calibration inputs violate the sealed evidence contract."""


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CalibrationError(f"{name} must be finite") from exc
    if not math.isfinite(number):
        raise CalibrationError(f"{name} must be finite")
    return number


def fit_isotonic(
    x: Sequence[float],
    y: Sequence[float],
    *,
    weights: Sequence[float] | None = None,
) -> dict:
    """Fit weighted nondecreasing PAV values at unique sorted x coordinates."""
    if not x or len(x) != len(y):
        raise CalibrationError("x and y must have equal positive length")
    weights = list(weights) if weights is not None else [1.0] * len(x)
    if len(weights) != len(x):
        raise CalibrationError("weights must match x and y")

    observations = []
    for raw_x, raw_y, raw_weight in zip(x, y, weights):
        x_value = _finite(raw_x, "x")
        y_value = _finite(raw_y, "y")
        weight = _finite(raw_weight, "weight")
        if weight <= 0:
            raise CalibrationError("weights must be positive")
        observations.append((x_value, y_value, weight))
    observations.sort(key=lambda row: (row[0], row[1], row[2]))

    unique: list[dict] = []
    for x_value, y_value, weight in observations:
        if unique and unique[-1]["x"] == x_value:
            unique[-1]["weighted_y"] += y_value * weight
            unique[-1]["weight"] += weight
        else:
            unique.append(
                {
                    "x": x_value,
                    "weighted_y": y_value * weight,
                    "weight": weight,
                }
            )

    blocks: list[dict] = []
    for index, point in enumerate(unique):
        blocks.append(
            {
                "start": index,
                "end": index,
                "weight": point["weight"],
                "weighted_y": point["weighted_y"],
            }
        )
        while len(blocks) >= 2:
            previous = blocks[-2]
            current = blocks[-1]
            previous_mean = previous["weighted_y"] / previous["weight"]
            current_mean = current["weighted_y"] / current["weight"]
            if previous_mean <= current_mean:
                break
            blocks[-2:] = [
                {
                    "start": previous["start"],
                    "end": current["end"],
                    "weight": previous["weight"] + current["weight"],
                    "weighted_y": previous["weighted_y"] + current["weighted_y"],
                }
            ]

    fitted = [0.0] * len(unique)
    for block in blocks:
        value = block["weighted_y"] / block["weight"]
        for index in range(block["start"], block["end"] + 1):
            fitted[index] = value
    return {
        "version": VERSION,
        "x": [float(point["x"]) for point in unique],
        "y": [float(value) for value in fitted],
        "observation_count": len(observations),
        "total_weight": float(sum(point["weight"] for point in unique)),
    }


def predict_isotonic(calibrator: dict, value: float) -> float:
    """Predict with clamped piecewise-linear interpolation between PAV knots."""
    if calibrator.get("version") != VERSION:
        raise CalibrationError("unknown calibrator version")
    knots_x = [_finite(item, "calibrator x") for item in calibrator.get("x", [])]
    knots_y = [_finite(item, "calibrator y") for item in calibrator.get("y", [])]
    if not knots_x or len(knots_x) != len(knots_y):
        raise CalibrationError("invalid calibrator knots")
    if any(left >= right for left, right in zip(knots_x, knots_x[1:])):
        raise CalibrationError("calibrator x knots must be strictly increasing")
    if any(left > right for left, right in zip(knots_y, knots_y[1:])):
        raise CalibrationError("calibrator y knots must be nondecreasing")
    target = _finite(value, "prediction")
    if len(knots_x) == 1 or target <= knots_x[0]:
        return knots_y[0]
    if target >= knots_x[-1]:
        return knots_y[-1]
    right = bisect.bisect_right(knots_x, target)
    left = right - 1
    width = knots_x[right] - knots_x[left]
    fraction = (target - knots_x[left]) / width
    return knots_y[left] + fraction * (knots_y[right] - knots_y[left])


def _sha256(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_role_calibrator(
    rows: Iterable[dict],
    *,
    role: str,
    prediction_field: str,
    target_field: str,
    before_cohort: int,
    min_rows: int = 250,
    min_source_folds: int = 4,
) -> dict:
    """Fit one role calibrator from prior, unique out-of-fold predictions only."""
    if role not in {"hitter", "pitcher"}:
        raise CalibrationError("role must be hitter or pitcher")
    selected = [dict(row) for row in rows if row.get("role") == role]
    identities: set[tuple[int, str]] = set()
    predictions, targets = [], []
    source_folds: set[int] = set()
    for row in selected:
        if row.get("is_out_of_fold") is not True:
            raise CalibrationError("all calibration rows must be out-of-fold")
        cohort_year = int(row.get("cohort_year") or 0)
        source_fold = int(row.get("source_fold") or 0)
        if cohort_year >= int(before_cohort) or source_fold >= int(before_cohort):
            raise CalibrationError("future cohort or source fold in calibration rows")
        identity = (int(row["mlbam_id"]), role)
        if identity in identities:
            raise CalibrationError(f"duplicate calibration identity: {identity}")
        identities.add(identity)
        source_folds.add(source_fold)
        predictions.append(_finite(row.get(prediction_field), prediction_field))
        targets.append(_finite(row.get(target_field), target_field))
    if len(selected) < int(min_rows):
        raise CalibrationError(
            f"insufficient calibration rows: {len(selected)} < {int(min_rows)}"
        )
    if len(source_folds) < int(min_source_folds):
        raise CalibrationError(
            "insufficient source folds: "
            f"{len(source_folds)} < {int(min_source_folds)}"
        )
    calibrator = fit_isotonic(predictions, targets)
    payload = {
        "version": "common_target_role_calibrator_v1",
        "role": role,
        "prediction_field": prediction_field,
        "target_field": target_field,
        "before_cohort": int(before_cohort),
        "row_count": len(selected),
        "source_folds": sorted(source_folds),
        "calibrator": calibrator,
    }
    return {**payload, "sha256": _sha256(payload)}


def apply_common_target_calibrators(
    rows: Iterable[dict],
    calibrators: dict[str, dict[str, dict]],
) -> list[dict]:
    """Add common-target score fields while preserving every incumbent field."""
    output = []
    for source in rows:
        row = copy.deepcopy(source)
        role = str(row.get("role") or "")
        role_calibrators = calibrators.get(role) or {}
        outcome = role_calibrators.get("outcome") or {}
        impact = role_calibrators.get("impact") or {}
        if outcome.get("role") != role or impact.get("role") != role:
            raise CalibrationError(f"missing role-matched calibrators for {role}")
        if not outcome.get("sha256") or not impact.get("sha256"):
            raise CalibrationError("calibrator hash is required")
        raw_outcome = _finite(row.get("expected_outcome_score"), "outcome score")
        raw_impact = _finite(
            row.get("expected_category_impact_score"), "impact score"
        )
        row["expected_outcome_score_common_target"] = predict_isotonic(
            outcome["calibrator"], raw_outcome
        )
        row["expected_category_impact_score_common_target"] = predict_isotonic(
            impact["calibrator"], raw_impact
        )
        audit = {
            "version": "common_target_application_v1",
            "role": role,
            "outcome_calibrator_sha256": outcome["sha256"],
            "impact_calibrator_sha256": impact["sha256"],
        }
        row["common_target_calibration"] = {
            **audit,
            "sha256": _sha256(audit),
        }
        output.append(row)
    return output
