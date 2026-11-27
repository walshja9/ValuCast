"""Common-outcome calibration for Prospect Rank v2."""
from __future__ import annotations

import math

import numpy as np

from prospects.ordinal_calibration_power import (
    _expected_tier,
    _fit_ordered_logit,
    _ordered_probabilities,
)
from prospects.prospect_v2_target import canonical_sha256

CALIBRATOR_VERSION = "2.0.0"
FORBIDDEN_FIELDS = {
    "current_rank",
    "governor",
    "market_rank",
    "market_value",
    "dynasty_value",
}
OUTCOMES = {"bust": 0, "role": 1, "star": 2}


def fit_calibrators(rows: list[dict]) -> dict:
    if not rows:
        raise ValueError("calibrator requires rows")
    if any(FORBIDDEN_FIELDS & set(row) for row in rows):
        raise ValueError("forbidden calibrator field")
    if any(row.get("role") not in ("hitter", "pitcher") for row in rows):
        raise ValueError("invalid calibrator role")
    try:
        raw = np.asarray([float(row["raw_composite"]) for row in rows], dtype=float)
        outcomes = np.asarray([OUTCOMES[row["outcome"]] for row in rows], dtype=int)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid calibrator row") from exc
    if not np.isfinite(raw).all():
        raise ValueError("invalid calibrator row")
    center = float(raw.mean())
    scale = float(raw.std()) or 1.0
    z = (raw - center) / scale
    pitcher = np.asarray([float(row["role"] == "pitcher") for row in rows])
    aware = _fit_ordered_logit(
        np.column_stack((z, pitcher, pitcher * z)), outcomes
    )
    blind = _fit_ordered_logit(z.reshape(-1, 1), outcomes)
    aware_params = [float(value) for value in aware["params"]]
    hitter_slope = aware_params[2]
    pitcher_slope = hitter_slope + aware_params[4]
    if not all(
        math.isfinite(value) and value > 0
        for value in (hitter_slope, pitcher_slope)
    ):
        raise ValueError("role slope must be positive")
    artifact = {
        "schema": "valucast_prospect_cross_role_calibrator_v2",
        "version": CALIBRATOR_VERSION,
        "design": [
            "standardized_raw_composite",
            "is_pitcher",
            "is_pitcher_x_standardized_raw_composite",
        ],
        "raw_composite": {"outcome_weight": 0.58, "impact_weight": 0.42},
        "standardization": {"mean": center, "std": scale},
        "params": aware_params,
        "role_blind_comparator": {
            "params": [float(value) for value in blind["params"]],
            "log_likelihood": float(blind["log_likelihood"]),
            "iterations": int(blind["iterations"]),
        },
        "log_likelihood": float(aware["log_likelihood"]),
        "iterations": int(aware["iterations"]),
        "role_slopes": {"hitter": hitter_slope, "pitcher": pitcher_slope},
    }
    artifact["artifact_sha256"] = canonical_sha256(artifact)
    return artifact


def score_profiles(rows: list[dict], calibrator: dict) -> list[dict]:
    expected_hash = calibrator.get("artifact_sha256")
    unsigned = {
        key: value for key, value in calibrator.items() if key != "artifact_sha256"
    }
    if expected_hash != canonical_sha256(unsigned):
        raise ValueError("calibrator hash mismatch")
    if (
        calibrator.get("schema") != "valucast_prospect_cross_role_calibrator_v2"
        or calibrator.get("version") != CALIBRATOR_VERSION
    ):
        raise ValueError("invalid calibrator contract")
    center = float(calibrator["standardization"]["mean"])
    scale = float(calibrator["standardization"]["std"])
    params = np.asarray(calibrator["params"], dtype=float)
    if scale <= 0 or params.shape != (5,) or not np.isfinite(params).all():
        raise ValueError("invalid calibrator contract")
    output = []
    for row in rows:
        if row.get("role") not in ("hitter", "pitcher"):
            raise ValueError("invalid calibrator role")
        z = (float(row["raw_composite"]) - center) / scale
        pitcher = float(row["role"] == "pitcher")
        probability = _ordered_probabilities(
            params,
            np.asarray([[z, pitcher, pitcher * z]], dtype=float),
        )[0]
        output.append(
            {
                **row,
                "tier_probabilities": {
                    "bust": float(probability[0]),
                    "role": float(probability[1]),
                    "star": float(probability[2]),
                },
                "calibrated_expected_tier": float(
                    _expected_tier(probability.reshape(1, 3))[0]
                ),
                "calibrator_version": calibrator["version"],
                "calibrator_sha256": expected_hash,
            }
        )
    return output
