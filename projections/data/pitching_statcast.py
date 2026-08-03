"""Pure, compact MLB pitcher-season aggregation for the research challenger."""

from __future__ import annotations

import copy
import math
from decimal import Decimal


MIN_INPUT_PITCHES = 500
MIN_PITCH_TYPE_PITCHES = 50
MIN_PITCH_TYPE_USAGE = 0.05

_ZONE_HALF_WIDTH_FT = 0.83
_EDGE_DISTANCE_FT = 3.0 / 12.0
_WASTE_DISTANCE_FT = 12.0 / 12.0
_INCHES_PER_FOOT = 12.0

_PITCH_TYPES = {
    "FF": "four_seam",
    "FA": "four_seam",
    "SI": "sinker",
    "FC": "cutter",
    "SL": "slider",
    "ST": "sweeper",
    "CU": "curveball",
    "KC": "curveball",
    "CS": "curveball",
    "CH": "changeup",
    "FS": "splitter",
    "FO": "splitter",
    "KN": "knuckleball",
}
_FASTBALL_TYPES = frozenset({"four_seam", "sinker", "cutter"})
_WHIFF_DESCRIPTIONS = frozenset(
    {
        "swinging_strike",
        "swinging_strike_blocked",
        "swinging_pitchout",
        "missed_bunt",
        "foul_tip",
        "bunt_foul_tip",
    }
)
_SWING_DESCRIPTIONS = frozenset(
    {"hit_into_play", "foul", "foul_bunt", "foul_pitchout"}
) | _WHIFF_DESCRIPTIONS
_SHAPE_FIELDS = {
    "velocity": ("release_speed", 1.0),
    "horizontal_movement": ("pfx_x", _INCHES_PER_FOOT),
    "induced_vertical_movement": ("pfx_z", _INCHES_PER_FOOT),
    "spin": ("release_spin_rate", 1.0),
    "extension": ("release_extension", 1.0),
    "release_pos_x": ("release_pos_x", 1.0),
    "release_pos_z": ("release_pos_z", 1.0),
}


def normalize_pitch_type(code: str | None) -> str:
    """Return the frozen normalized pitch family, routing unknowns to ``other``."""
    if not isinstance(code, str):
        return "other"
    return _PITCH_TYPES.get(code.strip().upper(), "other")


def _new_stat() -> dict:
    return {"count": 0, "missing": 0, "sum": "0", "sum_squares": "0"}


def _new_location() -> dict:
    return {
        "sample_count": 0,
        "missing_count": 0,
        "zone_count": 0,
        "heart_count": 0,
        "edge_count": 0,
        "waste_count": 0,
        "plate_x": _new_stat(),
        "plate_z": _new_stat(),
    }


def _new_pitch_type() -> dict:
    return {
        "pitch_count": 0,
        "location": _new_location(),
        "shape": {name: _new_stat() for name in _SHAPE_FIELDS},
    }


def _new_pitcher() -> dict:
    return {
        "pitch_count": 0,
        "swing_count": 0,
        "whiff_count": 0,
        "called_strike_count": 0,
        "location": _new_location(),
        "pitch_types": {},
    }


def _finite_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _add_stat(stat: dict, value, scale: float = 1.0) -> None:
    if not _finite_number(value):
        stat["missing"] += 1
        return
    number = Decimal(str(value)) * Decimal(str(scale))
    stat["count"] += 1
    stat["sum"] = _decimal_text(Decimal(stat["sum"]) + number)
    stat["sum_squares"] = _decimal_text(
        Decimal(stat["sum_squares"]) + number * number
    )


def _edge_distance_ft(px: float, pz: float, top: float, bottom: float) -> float:
    dx = abs(px) - _ZONE_HALF_WIDTH_FT
    dz = max(bottom - pz, pz - top)
    if dx <= 0.0 and dz <= 0.0:
        return min(-dx, -dz)
    return math.hypot(max(dx, 0.0), max(dz, 0.0))


def _add_location(location: dict, row: dict) -> None:
    px = row.get("plate_x")
    pz = row.get("plate_z")
    top = row.get("sz_top")
    bottom = row.get("sz_bot")
    _add_stat(location["plate_x"], px)
    _add_stat(location["plate_z"], pz)

    if not all(_finite_number(value) for value in (px, pz, top, bottom)):
        location["missing_count"] += 1
        return
    px, pz, top, bottom = map(float, (px, pz, top, bottom))
    if top <= bottom:
        location["missing_count"] += 1
        return

    location["sample_count"] += 1
    in_zone = abs(px) <= _ZONE_HALF_WIDTH_FT and bottom <= pz <= top
    if in_zone:
        location["zone_count"] += 1
        half_height = (top - bottom) / 4.0
        if (
            abs(px) <= _ZONE_HALF_WIDTH_FT / 2.0
            and bottom + half_height <= pz <= top - half_height
        ):
            location["heart_count"] += 1

    distance = _edge_distance_ft(px, pz, top, bottom)
    if distance <= _EDGE_DISTANCE_FT:
        location["edge_count"] += 1
    if not in_zone and distance >= _WASTE_DISTANCE_FT:
        location["waste_count"] += 1


def add_pitch(acc: dict, row: dict, eligible_ids: set[str]) -> None:
    """Add one in-memory pitch row when its string MLBAM ID is eligible."""
    pitcher = row.get("pitcher")
    if pitcher is None:
        return
    pitcher_id = str(pitcher)
    if pitcher_id not in eligible_ids:
        return

    pitchers = acc.setdefault("pitchers", {})
    pitcher_acc = pitchers.setdefault(pitcher_id, _new_pitcher())
    pitch_type = normalize_pitch_type(row.get("pitch_type"))
    type_acc = pitcher_acc["pitch_types"].setdefault(pitch_type, _new_pitch_type())

    pitcher_acc["pitch_count"] += 1
    type_acc["pitch_count"] += 1
    description = row.get("description")
    description = description.strip().lower() if isinstance(description, str) else ""
    if description in _SWING_DESCRIPTIONS:
        pitcher_acc["swing_count"] += 1
    if description in _WHIFF_DESCRIPTIONS:
        pitcher_acc["whiff_count"] += 1
    if description == "called_strike":
        pitcher_acc["called_strike_count"] += 1

    _add_location(pitcher_acc["location"], row)
    _add_location(type_acc["location"], row)
    for output_name, (input_name, scale) in _SHAPE_FIELDS.items():
        _add_stat(type_acc["shape"][output_name], row.get(input_name), scale)


def _merge_stat(left: dict, right: dict) -> dict:
    return {
        "count": left["count"] + right["count"],
        "missing": left["missing"] + right["missing"],
        "sum": _decimal_text(Decimal(left["sum"]) + Decimal(right["sum"])),
        "sum_squares": _decimal_text(
            Decimal(left["sum_squares"]) + Decimal(right["sum_squares"])
        ),
    }


def _merge_location(left: dict, right: dict) -> dict:
    return {
        key: left[key] + right[key]
        for key in (
            "sample_count",
            "missing_count",
            "zone_count",
            "heart_count",
            "edge_count",
            "waste_count",
        )
    } | {
        "plate_x": _merge_stat(left["plate_x"], right["plate_x"]),
        "plate_z": _merge_stat(left["plate_z"], right["plate_z"]),
    }


def _merge_pitch_type(left: dict, right: dict) -> dict:
    return {
        "pitch_count": left["pitch_count"] + right["pitch_count"],
        "location": _merge_location(left["location"], right["location"]),
        "shape": {
            name: _merge_stat(left["shape"][name], right["shape"][name])
            for name in _SHAPE_FIELDS
        },
    }


def _merge_pitcher(left: dict, right: dict) -> dict:
    pitch_types = {}
    for name in sorted(set(left["pitch_types"]) | set(right["pitch_types"])):
        if name not in left["pitch_types"]:
            pitch_types[name] = copy.deepcopy(right["pitch_types"][name])
        elif name not in right["pitch_types"]:
            pitch_types[name] = copy.deepcopy(left["pitch_types"][name])
        else:
            pitch_types[name] = _merge_pitch_type(
                left["pitch_types"][name], right["pitch_types"][name]
            )
    return {
        "pitch_count": left["pitch_count"] + right["pitch_count"],
        "swing_count": left["swing_count"] + right["swing_count"],
        "whiff_count": left["whiff_count"] + right["whiff_count"],
        "called_strike_count": (
            left["called_strike_count"] + right["called_strike_count"]
        ),
        "location": _merge_location(left["location"], right["location"]),
        "pitch_types": pitch_types,
    }


def merge_accumulators(left: dict, right: dict) -> dict:
    """Return a non-mutating, associative merge of two compact accumulators."""
    left_pitchers = left.get("pitchers", {})
    right_pitchers = right.get("pitchers", {})
    pitchers = {}
    for pitcher_id in sorted(set(left_pitchers) | set(right_pitchers)):
        if pitcher_id not in left_pitchers:
            pitchers[pitcher_id] = copy.deepcopy(right_pitchers[pitcher_id])
        elif pitcher_id not in right_pitchers:
            pitchers[pitcher_id] = copy.deepcopy(left_pitchers[pitcher_id])
        else:
            pitchers[pitcher_id] = _merge_pitcher(
                left_pitchers[pitcher_id], right_pitchers[pitcher_id]
            )
    return {"pitchers": pitchers}


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _finalize_stat(stat: dict) -> dict:
    count = stat["count"]
    total = Decimal(stat["sum"])
    total_squares = Decimal(stat["sum_squares"])
    if count:
        mean = total / count
        variance = max(total_squares / count - mean * mean, Decimal(0))
        mean_out = float(mean)
        stddev = math.sqrt(float(variance))
    else:
        mean_out = None
        stddev = None
    return {
        "sample_count": count,
        "missing_count": stat["missing"],
        "sum": float(total),
        "sum_squares": float(total_squares),
        "mean": mean_out,
        "stddev": stddev,
    }


def _finalize_location(location: dict) -> dict:
    denominator = location["sample_count"]
    return {
        "sample_count": denominator,
        "missing_count": location["missing_count"],
        "zone_count": location["zone_count"],
        "heart_count": location["heart_count"],
        "edge_count": location["edge_count"],
        "waste_count": location["waste_count"],
        "zone_rate": _rate(location["zone_count"], denominator),
        "heart_rate": _rate(location["heart_count"], denominator),
        "edge_rate": _rate(location["edge_count"], denominator),
        "waste_rate": _rate(location["waste_count"], denominator),
        "plate_x": _finalize_stat(location["plate_x"]),
        "plate_z": _finalize_stat(location["plate_z"]),
    }


def _pitcher_sort_key(pitcher_id: str):
    return (0, int(pitcher_id)) if pitcher_id.isdigit() else (1, pitcher_id)


def _separation(values: list[float]) -> float | None:
    return max(values) - min(values) if len(values) >= 2 else None


def _movement_separation(pitch_types: dict) -> float | None:
    points = []
    for row in pitch_types.values():
        horizontal = row["shape"]["horizontal_movement"]["mean"]
        vertical = row["shape"]["induced_vertical_movement"]["mean"]
        if horizontal is not None and vertical is not None:
            points.append((horizontal, vertical))
    if len(points) < 2:
        return None
    return max(
        math.hypot(x1 - x2, y1 - y2)
        for index, (x1, y1) in enumerate(points)
        for x2, y2 in points[index + 1 :]
    )


def finalize_season(acc: dict, season: int) -> list[dict]:
    """Finalize qualified pitcher rows in deterministic MLBAM/pitch-type order."""
    rows = []
    for pitcher_id in sorted(acc.get("pitchers", {}), key=_pitcher_sort_key):
        pitcher = acc["pitchers"][pitcher_id]
        total = pitcher["pitch_count"]
        if total < MIN_INPUT_PITCHES:
            continue

        pitch_type_counts = {
            name: pitcher["pitch_types"][name]["pitch_count"]
            for name in sorted(pitcher["pitch_types"])
        }
        minimum_type_pitches = max(
            MIN_PITCH_TYPE_PITCHES, total * MIN_PITCH_TYPE_USAGE
        )
        pitch_types = {}
        for name in sorted(pitcher["pitch_types"]):
            type_acc = pitcher["pitch_types"][name]
            if type_acc["pitch_count"] < minimum_type_pitches:
                continue
            pitch_types[name] = {
                "pitch_count": type_acc["pitch_count"],
                "usage": type_acc["pitch_count"] / total,
                "location": _finalize_location(type_acc["location"]),
                "shape": {
                    field: _finalize_stat(type_acc["shape"][field])
                    for field in _SHAPE_FIELDS
                },
            }

        velocity_means = [
            row["shape"]["velocity"]["mean"]
            for row in pitch_types.values()
            if row["shape"]["velocity"]["mean"] is not None
        ]
        rows.append(
            {
                "mlbam_id": pitcher_id,
                "season": int(season),
                "pitch_count": total,
                "outcomes": {
                    "swing_count": pitcher["swing_count"],
                    "whiff_count": pitcher["whiff_count"],
                    "called_strike_count": pitcher["called_strike_count"],
                    "whiff_rate": _rate(
                        pitcher["whiff_count"], pitcher["swing_count"]
                    ),
                    "csw_rate": _rate(
                        pitcher["called_strike_count"] + pitcher["whiff_count"],
                        total,
                    ),
                    "called_strike_rate": _rate(
                        pitcher["called_strike_count"], total
                    ),
                },
                "location": _finalize_location(pitcher["location"]),
                "pitch_type_counts": pitch_type_counts,
                "pitch_types": pitch_types,
                "arsenal": {
                    "count": len(pitch_types),
                    "usage_hhi": sum((count / total) ** 2 for count in pitch_type_counts.values()),
                    "fastball_share": sum(
                        count
                        for name, count in pitch_type_counts.items()
                        if name in _FASTBALL_TYPES
                    )
                    / total,
                    "max_velocity_separation": _separation(velocity_means),
                    "max_movement_separation": _movement_separation(pitch_types),
                },
            }
        )
    return rows
