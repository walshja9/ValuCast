"""Fixed, fold-local MLB pitcher skill residual challenger.

This module is research-only.  It corrects only K/BF and BB/BF and has no
import path into production projections, ranks, values, roles, or publication.
"""

from __future__ import annotations

import copy
import math
from dataclasses import asdict, dataclass
from statistics import median, pstdev


_SHAPE_FIELDS = (
    "velocity",
    "ivb",
    "horizontal_movement",
    "spin",
    "extension",
)
_SHAPE_SOURCE_FIELDS = {
    "velocity": "velocity",
    "ivb": "induced_vertical_movement",
    "horizontal_movement": "horizontal_movement",
    "spin": "spin",
    "extension": "extension",
}
_SCALAR_FEATURES = (
    "whiff_rate",
    "csw_rate",
    "called_strike_rate",
    "zone_rate",
    "heart_rate",
    "edge_rate",
    "waste_rate",
    "horizontal_location_dispersion",
    "vertical_location_dispersion",
    "arsenal_count",
    "usage_hhi",
    "fastball_share",
    "max_velocity_separation",
    "max_movement_separation",
)

FEATURE_ORDER = (
    "control_k_bf",
    "control_bb_bf",
    "control_p_sp",
    *tuple(f"{field}_deviation" for field in _SHAPE_FIELDS),
    *_SCALAR_FEATURES,
    *tuple(f"{field}_known" for field in _SHAPE_FIELDS),
)


@dataclass(frozen=True)
class PitcherSkillChallengerParams:
    ridge_lambda: float = 10.0
    minimum_input_pitches: int = 500
    residual_clip_quantiles: tuple[float, float] = (0.05, 0.95)


def _finite(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (OverflowError, TypeError, ValueError):
        return False


def _required_number(mapping: dict, key: str) -> float:
    if not isinstance(mapping, dict) or not _finite(mapping.get(key)):
        raise ValueError(f"missing or invalid {key}")
    return float(mapping[key])


def _required_mapping(mapping: dict, key: str) -> dict:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(value, dict):
        raise ValueError(f"malformed {key} mapping")
    return value


def _validate_finite_payload(value, path: str = "payload") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _validate_finite_payload(item, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_finite_payload(item, f"{path}[{index}]")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            raise ValueError(f"non-finite derived value at {path}")


def _control_rates(control: dict) -> dict[str, float]:
    bf = _required_number(control, "BF")
    if bf <= 0:
        raise ValueError("Control BF must be positive")
    k_bf = _required_number(control, "K") / bf
    bb_bf = _required_number(control, "BB") / bf
    if not all(0.0 <= value <= 1.0 for value in (k_bf, bb_bf)):
        raise ValueError("Control rates must be in [0, 1]")
    return {"k_bf": k_bf, "bb_bf": bb_bf}


def _hand(feature_row: dict) -> str:
    hand = str(feature_row.get("pitcher_hand") or "").upper()
    if hand not in {"L", "R"}:
        raise ValueError("pitcher_hand must be L or R")
    return hand


def _shape_value(type_row: dict, field: str, hand: str) -> tuple[float, int] | None:
    shape = _required_mapping(type_row, "shape")
    shape = _required_mapping(shape, _SHAPE_SOURCE_FIELDS[field])
    value = shape.get("mean")
    count = shape.get("sample_count")
    if not _finite(value) or not _finite(count) or float(count) <= 0:
        return None
    value = float(value)
    if field == "horizontal_movement" and hand == "L":
        value = -value
    return value, int(count)


def _fit_shape_references(rows: list[dict]) -> dict:
    totals: dict[str, dict[str, list[float]]] = {}
    for row in rows:
        feature = row["feature_row"]
        hand = _hand(feature)
        pitch_types = _required_mapping(feature, "pitch_types")
        for pitch_type, type_row in sorted(pitch_types.items()):
            if not isinstance(type_row, dict):
                raise ValueError("malformed pitch type mapping")
            key = f"{pitch_type}|{hand}"
            fields = totals.setdefault(key, {})
            for field in _SHAPE_FIELDS:
                observed = _shape_value(type_row, field, hand)
                if observed is None:
                    continue
                value, count = observed
                total, prior_count = fields.get(field, [0.0, 0])
                fields[field] = [total + value * count, prior_count + count]
    return {
        key: {
            field: {
                "mean": values[0] / values[1],
                "sample_count": int(values[1]),
            }
            for field, values in sorted(fields.items())
        }
        for key, fields in sorted(totals.items())
    }


def _shape_deviations(feature_row: dict, references: dict) -> dict[str, float | None]:
    hand = _hand(feature_row)
    weighted = {field: [0.0, 0.0] for field in _SHAPE_FIELDS}
    pitch_types = _required_mapping(feature_row, "pitch_types")
    for pitch_type, type_row in sorted(pitch_types.items()):
        if not isinstance(type_row, dict):
            raise ValueError("malformed pitch type mapping")
        usage = type_row.get("usage")
        if not _finite(usage) or float(usage) <= 0:
            continue
        reference = references.get(f"{pitch_type}|{hand}", {})
        for field in _SHAPE_FIELDS:
            observed = _shape_value(type_row, field, hand)
            center = reference.get(field, {}).get("mean")
            if observed is None or not _finite(center):
                continue
            weight = float(usage)
            weighted[field][0] += (observed[0] - float(center)) * weight
            weighted[field][1] += weight
    return {
        f"{field}_deviation": total / weight if weight else None
        for field, (total, weight) in weighted.items()
    }


def _scalar_features(feature_row: dict) -> dict[str, float]:
    outcomes = _required_mapping(feature_row, "outcomes")
    location = _required_mapping(feature_row, "location")
    arsenal = _required_mapping(feature_row, "arsenal")
    plate_x = _required_mapping(location, "plate_x")
    plate_z = _required_mapping(location, "plate_z")
    values = {
        "whiff_rate": outcomes.get("whiff_rate"),
        "csw_rate": outcomes.get("csw_rate"),
        "called_strike_rate": outcomes.get("called_strike_rate"),
        "zone_rate": location.get("zone_rate"),
        "heart_rate": location.get("heart_rate"),
        "edge_rate": location.get("edge_rate"),
        "waste_rate": location.get("waste_rate"),
        "horizontal_location_dispersion": plate_x.get("stddev"),
        "vertical_location_dispersion": plate_z.get("stddev"),
        "arsenal_count": arsenal.get("count"),
        "usage_hhi": arsenal.get("usage_hhi"),
        "fastball_share": arsenal.get("fastball_share"),
        "max_velocity_separation": arsenal.get("max_velocity_separation"),
        "max_movement_separation": arsenal.get("max_movement_separation"),
    }
    if not all(_finite(value) for value in values.values()):
        raise ValueError("missing or invalid registered scalar feature")
    return {key: float(value) for key, value in values.items()}


def _row_parts(row: dict, minimum_pitches: int) -> tuple[dict, dict, dict]:
    if not isinstance(row, dict):
        raise ValueError("training row must be a mapping")
    pitcher_id = str(row.get("mlbam_id") or "")
    if not pitcher_id:
        raise ValueError("training row lacks MLBAM identity")
    feature = row.get("feature_row")
    control = row.get("control")
    outcome = row.get("outcome")
    if not all(isinstance(value, dict) for value in (feature, control, outcome)):
        raise ValueError("training row lacks joined mappings")
    try:
        feature_season = int(row["feature_season"])
        outcome_season = int(row["outcome_season"])
        fold_target_season = int(row["fold_target_season"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("training row lacks joined seasons") from exc
    if feature_season != outcome_season - 1:
        raise ValueError("feature season must equal outcome season T-1")
    if outcome_season >= fold_target_season:
        raise ValueError("outcome season must be before fold target")
    identities = {
        pitcher_id,
        str(feature.get("mlbam_id") or ""),
        str(control.get("mlbam_id") or ""),
        str(outcome.get("mlbam_id") or ""),
    }
    try:
        seasons = {feature_season, int(feature.get("season", -1))}
        outcome_seasons = {
            outcome_season,
            int(control.get("season", -1)),
            int(outcome.get("season", -1)),
        }
    except (TypeError, ValueError) as exc:
        raise ValueError("malformed season join") from exc
    if len(identities) != 1 or "" in identities:
        raise ValueError("mismatched MLBAM identity join")
    if len(seasons) != 1 or len(outcome_seasons) != 1:
        raise ValueError("mismatched season join")
    if _required_number(feature, "pitch_count") < minimum_pitches:
        raise ValueError("training feature row is below pitch floor")
    _hand(feature)
    _control_rates(control)
    outcome_bf = _required_number(outcome, "BF")
    if outcome_bf <= 0:
        raise ValueError("outcome BF must be positive")
    for key in ("K", "BB"):
        rate = _required_number(outcome, key) / outcome_bf
        if not 0.0 <= rate <= 1.0:
            raise ValueError("outcome rates must be in [0, 1]")
    return control, feature, outcome


def _raw_features(
    control: dict,
    feature_row: dict,
    references: dict,
    medians: dict,
) -> list[float]:
    rates = _control_rates(control)
    p_sp = _required_number(control, "p_sp")
    if not 0.0 <= p_sp <= 1.0:
        raise ValueError("Control p_sp must be in [0, 1]")
    deviations = _shape_deviations(feature_row, references)
    scalars = _scalar_features(feature_row)
    values = {
        "control_k_bf": rates["k_bf"],
        "control_bb_bf": rates["bb_bf"],
        "control_p_sp": p_sp,
        **scalars,
    }
    for field in _SHAPE_FIELDS:
        key = f"{field}_deviation"
        known = deviations[key] is not None
        values[key] = float(deviations[key]) if known else medians[key]
        values[f"{field}_known"] = 1.0 if known else 0.0
    return [values[key] for key in FEATURE_ORDER]


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    augmented = [list(row) + [value] for row, value in zip(matrix, vector)]
    for column in range(len(vector)):
        pivot = max(
            range(column, len(vector)),
            key=lambda row: abs(augmented[row][column]),
        )
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("invalid fold: singular ridge system")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(len(vector)):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor:
                augmented[row] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(
                        augmented[row], augmented[column]
                    )
                ]
    return [augmented[row][-1] for row in range(len(vector))]


def _fit_ridge(design: list[list[float]], targets: list[float], ridge: float) -> list[float]:
    width = len(design[0]) + 1
    matrix = [[0.0] * width for _ in range(width)]
    vector = [0.0] * width
    for features, target in zip(design, targets):
        x = [1.0, *features]
        for left in range(width):
            vector[left] += x[left] * target
            for right in range(width):
                matrix[left][right] += x[left] * x[right]
    for index in range(1, width):
        matrix[index][index] += ridge
    return _solve(matrix, vector)


def _type7(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def fit_fold(training_rows: list[dict], params: PitcherSkillChallengerParams) -> dict:
    if params != PitcherSkillChallengerParams():
        raise ValueError("challenger requires fixed registered parameters")
    if not training_rows:
        raise ValueError("invalid fold: no training rows")
    for row in training_rows:
        _row_parts(row, params.minimum_input_pitches)
    fold_targets = {int(row["fold_target_season"]) for row in training_rows}
    if len(fold_targets) != 1:
        raise ValueError("training rows must share a common fold target")
    rows = sorted(
        training_rows,
        key=lambda row: (int(row.get("outcome_season", -1)), str(row.get("mlbam_id", ""))),
    )
    seen = set()
    for row in rows:
        key = (str(row.get("mlbam_id") or ""), row.get("outcome_season"))
        if key in seen:
            raise ValueError("duplicate pitcher outcome-season training row")
        seen.add(key)

    references = _fit_shape_references(rows)
    _validate_finite_payload(references, "shape_references")
    deviations = [_shape_deviations(row["feature_row"], references) for row in rows]
    _validate_finite_payload(deviations, "shape_deviations")
    medians = {}
    for field in _SHAPE_FIELDS:
        key = f"{field}_deviation"
        known = [row[key] for row in deviations if row[key] is not None]
        if not known:
            raise ValueError(f"invalid fold: no training median for {field}")
        medians[key] = float(median(known))

    raw_design = [
        _raw_features(row["control"], row["feature_row"], references, medians)
        for row in rows
    ]
    _validate_finite_payload(raw_design, "raw_design")
    columns = list(zip(*raw_design))
    means = [sum(column) / len(column) for column in columns]
    stds = [pstdev(column) or 1.0 for column in columns]
    design = [
        [
            (value - center) / spread
            for value, center, spread in zip(features, means, stds)
        ]
        for features in raw_design
    ]
    _validate_finite_payload(
        {"means": means, "stds": stds, "design": design}, "fold_scaling"
    )
    residuals = {"k_bf": [], "bb_bf": []}
    for row in rows:
        control, _, outcome = _row_parts(row, params.minimum_input_pitches)
        control_rates = _control_rates(control)
        outcome_bf = float(outcome["BF"])
        residuals["k_bf"].append(float(outcome["K"]) / outcome_bf - control_rates["k_bf"])
        residuals["bb_bf"].append(float(outcome["BB"]) / outcome_bf - control_rates["bb_bf"])
    lower, upper = params.residual_clip_quantiles
    payload = {
        "research_only": True,
        "params": {
            **asdict(params),
            "residual_clip_quantiles": list(params.residual_clip_quantiles),
        },
        "feature_order": list(FEATURE_ORDER),
        "training_row_count": len(rows),
        "shape_references": references,
        "shape_medians": medians,
        "scalers": {"means": means, "stds": stds},
        "coefficients": {
            endpoint: _fit_ridge(design, values, params.ridge_lambda)
            for endpoint, values in residuals.items()
        },
        "residual_clip_bounds": {
            endpoint: [_type7(values, lower), _type7(values, upper)]
            for endpoint, values in residuals.items()
        },
        "quantile_convention": "type7_linear",
    }
    _validate_finite_payload(payload)
    return payload


def _prediction(coefficients: list[float], features: list[float]) -> float:
    value = coefficients[0] + sum(
        weight * feature for weight, feature in zip(coefficients[1:], features)
    )
    return value


def predict_rates(model: dict, control: dict, feature_row: dict | None) -> dict:
    control_rates = _control_rates(control)
    if not isinstance(feature_row, dict):
        return control_rates
    try:
        if _required_number(feature_row, "pitch_count") < model["params"]["minimum_input_pitches"]:
            return control_rates
        control_id = str(control.get("mlbam_id") or "")
        feature_id = str(feature_row.get("mlbam_id") or "")
        if not control_id or not feature_id or feature_id != control_id:
            return control_rates
        if int(feature_row.get("season", -1)) != int(control.get("season", -1)) - 1:
            return control_rates
        raw = _raw_features(
            control,
            feature_row,
            model["shape_references"],
            model["shape_medians"],
        )
    except (AttributeError, TypeError, ValueError):
        return control_rates
    standardized = [
        (value - center) / spread
        for value, center, spread in zip(
            raw, model["scalers"]["means"], model["scalers"]["stds"]
        )
    ]
    output = {}
    for endpoint in ("k_bf", "bb_bf"):
        correction = _prediction(model["coefficients"][endpoint], standardized)
        low, high = model["residual_clip_bounds"][endpoint]
        if not math.isfinite(correction):
            correction = high if correction > 0 else low
        correction = max(low, min(high, correction))
        output[endpoint] = max(0.0, min(1.0, control_rates[endpoint] + correction))
    return output


def apply_rates_to_control(control: dict, k_bf: float, bb_bf: float) -> dict:
    if not all(_finite(value) and 0.0 <= float(value) <= 1.0 for value in (k_bf, bb_bf)):
        raise ValueError("corrected rates must be finite and in [0, 1]")
    bf = _required_number(control, "BF")
    ip = _required_number(control, "IP")
    if bf <= 0 or ip <= 0:
        raise ValueError("Control BF and IP must be positive")
    for key in ("K", "BB", "HR", "HBP", "H_ALLOWED", "ERA"):
        _required_number(control, key)

    result = copy.deepcopy(control)
    cfip = _required_number(control, "cFIP")
    result["K"] = round(float(k_bf) * bf, 4)
    result["BB"] = round(float(bb_bf) * bf, 4)
    corrected_raw_fip = (
        13.0 * float(result["HR"])
        + 3.0 * (float(result["BB"]) + float(result["HBP"]))
        - 2.0 * float(result["K"])
    ) / ip
    era = max(0.0, corrected_raw_fip + cfip)
    result["ER"] = round(era * ip / 9.0, 4)
    result["ERA"] = round(era, 3)
    result["WHIP"] = round((float(result["BB"]) + float(result["H_ALLOWED"])) / ip, 3)
    result["K_9"] = round(9.0 * float(result["K"]) / ip, 3)
    result["BB_9"] = round(9.0 * float(result["BB"]) / ip, 3)
    result["K_BB"] = round(float(result["K"]) / float(result["BB"]), 3) if result["BB"] else 0.0
    return result
