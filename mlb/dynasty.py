"""Shadow ValuCast MLB dynasty value layer.

This layer turns ValuCast's own MLB projection valuation into a versioned
artifact. It intentionally does not consume DD ranks, DD values, or public
market rankings.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from league_values.engine import ValuationEngine
from league_values.models import PlayerPool, PlayerProjection, ValuationResult
from league_values.playing_time import filter_by_playing_time
from league_values.post_processors import AgeCurve, VolumeMultiplier
from projections.data.identity import age_for, load_identity_store
from web.config_builder import build_config
from web.projection_store import ProjectionStore

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_PATH = ROOT / "data" / "projections" / "current.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_dynasty_layer"
IDENTITY_DATA_DIR = ROOT / "projections" / "data"

LAYER_NAME = "ValuCast MLB Dynasty Value Layer"
LAYER_VERSION = "0.3.0"
VALUE_SOURCE = "valucast_mlb_dynasty_horizon_v0_3"

MIN_HITTER_PA = 100
MIN_SP_IP = 40
MIN_RP_IP = 20

PRODUCTION_WEIGHT = 0.95
RELIABILITY_WEIGHT = 0.05
ROS_STABILITY_BASE_WEIGHT = 0.35
ROS_STABILITY_MAX_WEIGHT = 0.70
ROS_STABILITY_UNDERPERFORMANCE_WEIGHT = 0.25
ROS_STABILITY_GAP_TO_MAX = 12.0
MIN_AGE_COVERAGE_RATE = 0.95
TRUE_TALENT_FLOOR_SHARE = 0.72
ESTABLISHED_HITTER_MIN_PA = 250
ESTABLISHED_SP_MIN_IP = 60
YOUNG_SP_VOLATILITY_AGE_MAX = 24
YOUNG_SP_VOLATILITY_IP_MAX = 120.0
YOUNG_SP_VOLATILITY_GAP_START = 2.5
YOUNG_SP_VOLATILITY_MAX_DISCOUNT = 0.18
RELIEVER_DYNASTY_SCORE_CAP = 52.0
HORIZON_YEAR_WEIGHTS = (
    (0, 1.00),
    (1, 0.72),
    (2, 0.48),
)
FUTURE_RELIABILITY_FLOOR = 0.55

HITTER_AGE_CURVE = {
    22: 1.65,
    25: 1.42,
    27: 1.25,
    30: 0.97,
    32: 0.87,
    34: 0.77,
    37: 0.48,
}
PITCHER_AGE_CURVE = {
    22: 1.50,
    25: 1.30,
    27: 1.15,
    30: 0.88,
    32: 0.78,
    34: 0.65,
    37: 0.33,
}

PITCHER_POOLS = {PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER}
KEY_STATS = (
    "PA",
    "R",
    "HR",
    "RBI",
    "SB",
    "AVG",
    "OBP",
    "OPS",
    "IP",
    "W",
    "QS",
    "SV",
    "HLD",
    "K",
    "ERA",
    "WHIP",
)
ROS_RATE_STATS = {
    "AVG",
    "OBP",
    "SLG",
    "OPS",
    "ERA",
    "WHIP",
    "K_BB",
    "K_9",
    "BB_9",
}
TRUE_TALENT_TARGET_VOLUME = {
    PlayerPool.HITTER: 600.0,
    PlayerPool.STARTER: 180.0,
    PlayerPool.PITCHER: 160.0,
    PlayerPool.RELIEVER: 65.0,
}


def _finite_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _date_part(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _season_from_generated_at(value: str | None) -> int:
    date_part = _date_part(value)
    if date_part:
        try:
            return int(date_part[:4])
        except ValueError:
            pass
    return datetime.now(timezone.utc).year


def _generated_at(store: ProjectionStore, generated_at: str | None = None) -> str:
    if generated_at:
        return generated_at
    if store.as_of:
        return store.as_of
    return datetime.now(timezone.utc).isoformat()


def _role(player: PlayerProjection) -> str:
    return "pitcher" if player.pool in PITCHER_POOLS else "hitter"


def _coerce_age(value: Any) -> int | None:
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    if age < 16 or age > 55:
        return None
    return age


def _age_multiplier(player: PlayerProjection, age: int | None) -> float | None:
    if age is None:
        return None
    curve = PITCHER_AGE_CURVE if player.pool in PITCHER_POOLS else HITTER_AGE_CURVE
    ages = sorted(curve)
    if age <= ages[0]:
        return curve[ages[0]]
    if age >= ages[-1]:
        return curve[ages[-1]]
    for lower, upper in zip(ages, ages[1:]):
        if lower <= age <= upper:
            low_value = curve[lower]
            high_value = curve[upper]
            fraction = (age - lower) / (upper - lower)
            return low_value + fraction * (high_value - low_value)
    return 1.0


def _future_reliability_factor(reliability: float, offset: int) -> float:
    if offset <= 0:
        return 1.0
    stability = max(FUTURE_RELIABILITY_FLOOR, min(1.0, reliability / 100.0))
    return stability ** offset


def _horizon_profile(
    result: ValuationResult,
    start_season: int,
) -> dict[str, Any]:
    player = result.player
    current_age = _coerce_age(player.metadata.get("age"))
    current_age_multiplier = _age_multiplier(player, current_age)
    reliability = _playing_time_reliability(player)
    weighted_value = 0.0
    total_weight = 0.0
    years = []

    for offset, weight in HORIZON_YEAR_WEIGHTS:
        age = current_age + offset if current_age is not None else None
        future_age_multiplier = _age_multiplier(player, age)
        if current_age_multiplier and future_age_multiplier:
            age_factor = future_age_multiplier / current_age_multiplier
        else:
            age_factor = 1.0
        reliability_factor = _future_reliability_factor(reliability, offset)
        projected_value = result.total_value * age_factor * reliability_factor
        weighted_value += projected_value * weight
        total_weight += weight
        years.append(
            {
                "season": start_season + offset,
                "age": age,
                "weight": weight,
                "age_factor": round(age_factor, 4),
                "reliability_factor": round(reliability_factor, 4),
                "projected_value": round(projected_value, 4),
            }
        )

    return {
        "value": weighted_value / total_weight if total_weight else result.total_value,
        "years": years,
    }


def _player_age(
    player: PlayerProjection,
    identities: dict[str, dict],
    season: int,
) -> tuple[int | None, str]:
    metadata_age = _coerce_age(player.metadata.get("age"))
    if metadata_age is not None:
        return metadata_age, "projection_metadata"

    mlbam_id = player.metadata.get("mlbam_id")
    if mlbam_id in (None, ""):
        return None, "missing_mlbam_id"
    identity = identities.get(str(mlbam_id)) or {}
    identity_age = age_for(identity.get("birth_date"), season)
    if identity_age is not None:
        return identity_age, "valucast_identity_birth_date"
    return None, "missing_identity_birth_date"


def _attach_ages(
    players: Iterable[PlayerProjection],
    identities: dict[str, dict],
    season: int,
) -> list[PlayerProjection]:
    enriched = []
    for player in players:
        age, source = _player_age(player, identities, season)
        metadata = dict(player.metadata)
        metadata["age"] = age
        metadata["age_source"] = source
        enriched.append(replace(player, metadata=metadata))
    return enriched


def identity_key(player: PlayerProjection) -> tuple[str, str] | None:
    mlbam_id = player.metadata.get("mlbam_id")
    role = _role(player)
    if mlbam_id in (None, ""):
        return None
    return str(mlbam_id), role


def _volume(player: PlayerProjection) -> float:
    if player.pool is PlayerPool.HITTER:
        return player.stats.get("PA", 0.0) or player.stats.get("AB", 0.0)
    return player.stats.get("IP", 0.0)


def _playing_time_reliability(player: PlayerProjection) -> float:
    volume = _volume(player)
    if player.pool is PlayerPool.HITTER:
        regression = 150.0
    elif player.pool is PlayerPool.RELIEVER or (
        "RP" in player.positions and "SP" not in player.positions
    ):
        regression = 20.0
    else:
        regression = 45.0
    if volume <= 0:
        return 0.0
    return round(100.0 * volume / (volume + regression), 2)


def _confidence(player: PlayerProjection, reliability: float) -> str:
    has_ros = bool(player.metadata.get("has_ros"))
    if reliability >= 80 and has_ros:
        return "high"
    if reliability >= 60:
        return "medium"
    return "low"


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _scale_value(value: float, floor: float, ceiling: float) -> float:
    if ceiling <= floor:
        return 50.0
    return max(0.0, min(100.0, 100.0 * (value - floor) / (ceiling - floor)))


def _projection_stats(player: PlayerProjection) -> dict[str, float]:
    return {
        key: round(value, 3)
        for key in KEY_STATS
        if (value := _finite_float(player.stats.get(key))) is not None
    }


def _ros_projection_stats(player: PlayerProjection) -> dict[str, float]:
    return {
        key: value
        for key, raw in (player.metadata.get("stats_ros") or {}).items()
        if (value := _finite_float(raw)) is not None
    }


def _true_talent_target_volume(player: PlayerProjection) -> float:
    target = TRUE_TALENT_TARGET_VOLUME.get(player.pool, TRUE_TALENT_TARGET_VOLUME[PlayerPool.PITCHER])
    return max(target, _volume(player))


def _annualized_ros_projection_stats(player: PlayerProjection) -> tuple[dict[str, float], float]:
    stats = _ros_projection_stats(player)
    if not stats:
        return {}, 1.0
    ros_volume = stats.get("PA") if player.pool is PlayerPool.HITTER else stats.get("IP")
    ros_volume = _finite_float(ros_volume)
    target_volume = _true_talent_target_volume(player)
    if ros_volume is None or ros_volume <= 0 or target_volume <= 0:
        return stats, 1.0
    scale = target_volume / ros_volume
    annualized = {}
    for key, value in stats.items():
        annualized[key] = value if key in ROS_RATE_STATS else value * scale
    return annualized, round(scale, 4)


def _ros_players(players: Iterable[PlayerProjection]) -> list[PlayerProjection]:
    out = []
    for player in players:
        stats, scale = _annualized_ros_projection_stats(player)
        if stats:
            metadata = dict(player.metadata)
            metadata["ros_true_talent_annualization_scale"] = scale
            out.append(replace(player, stats=stats, metadata=metadata))
    return out


def _ros_lookup(
    engine: ValuationEngine,
    players: Iterable[PlayerProjection],
) -> dict[tuple[str, str], ValuationResult]:
    ros_results = engine.value_players(_ros_players(players), build_config(mode="categories"))
    return {
        key: result
        for result in ros_results
        if (key := identity_key(result.player))
    }


def _ros_stability_weight(current_value: float, ros_value: float | None) -> float:
    if ros_value is None:
        return 0.0
    gap = current_value - ros_value
    if gap <= 0:
        return ROS_STABILITY_UNDERPERFORMANCE_WEIGHT
    extra = min(1.0, gap / ROS_STABILITY_GAP_TO_MAX)
    return round(
        ROS_STABILITY_BASE_WEIGHT
        + extra * (ROS_STABILITY_MAX_WEIGHT - ROS_STABILITY_BASE_WEIGHT),
        4,
    )


def _stability_adjusted_result(
    result: ValuationResult,
    ros_by_key: dict[tuple[str, str], ValuationResult],
) -> tuple[ValuationResult, dict[str, Any]]:
    key = identity_key(result.player)
    ros_result = ros_by_key.get(key) if key else None
    ros_value = ros_result.total_value if ros_result is not None else None
    current_value = result.total_value
    ros_weight = _ros_stability_weight(current_value, ros_value)
    adjusted_value = (
        current_value
        if ros_value is None
        else current_value * (1.0 - ros_weight) + ros_value * ros_weight
    )
    reliability = _playing_time_reliability(result.player)
    floor_value = _established_true_talent_floor(result.player, ros_value, reliability)
    floor_applied = False
    if floor_value is not None and adjusted_value < floor_value:
        adjusted_value = floor_value
        floor_applied = True
    return (
        replace(result, total_value=adjusted_value),
        {
            "current_season_category_value": round(current_value, 4),
            "ros_category_value": _round(ros_value, 4),
            "ros_value_kind": "annualized_true_talent",
            "ros_true_talent_annualization_scale": (
                (ros_result.player.metadata or {}).get("ros_true_talent_annualization_scale")
                if ros_result is not None
                else None
            ),
            "ros_stability_weight": ros_weight,
            "stability_adjusted_category_value": round(adjusted_value, 4),
            "stability_adjustment": round(adjusted_value - current_value, 4),
            "true_talent_floor_value": _round(floor_value, 4),
            "true_talent_floor_applied": floor_applied,
        },
    )


def _is_reliever_only(player: PlayerProjection) -> bool:
    return player.pool is PlayerPool.RELIEVER or (
        "RP" in player.positions and "SP" not in player.positions
    )


def _is_starter(player: PlayerProjection) -> bool:
    return player.pool is PlayerPool.STARTER or "SP" in player.positions


def _actual_ip(player: PlayerProjection) -> float:
    actual = player.metadata.get("stats_actual") or {}
    return _finite_float(actual.get("IP")) or 0.0


def _established_true_talent_floor(
    player: PlayerProjection,
    ros_value: float | None,
    reliability: float,
) -> float | None:
    if ros_value is None or reliability < 70.0:
        return None
    age = _coerce_age(player.metadata.get("age"))
    if age is None:
        return None
    if player.pool is PlayerPool.HITTER:
        if age > 33 or _volume(player) < ESTABLISHED_HITTER_MIN_PA:
            return None
    elif _is_starter(player) and not _is_reliever_only(player):
        if age > 31 or _volume(player) < ESTABLISHED_SP_MIN_IP:
            return None
    else:
        return None
    return ros_value * TRUE_TALENT_FLOOR_SHARE


def _role_adjusted_score(
    player: PlayerProjection,
    score: float,
    stability: dict[str, Any] | None,
) -> tuple[float, dict[str, Any]]:
    adjustments: dict[str, Any] = {
        "reliever_score_cap": None,
        "young_sp_volatility_discount": 0.0,
    }
    adjusted = score
    if _is_reliever_only(player):
        adjustments["reliever_score_cap"] = RELIEVER_DYNASTY_SCORE_CAP
        adjusted = min(adjusted, RELIEVER_DYNASTY_SCORE_CAP)
    elif _is_starter(player):
        age = _coerce_age(player.metadata.get("age"))
        actual_ip = _actual_ip(player)
        projection_stability = stability or {}
        current_value = _finite_float(projection_stability.get("current_season_category_value"))
        ros_value = _finite_float(projection_stability.get("ros_category_value"))
        current_over_true_talent_gap = (
            current_value - ros_value
            if current_value is not None and ros_value is not None
            else 0.0
        )
        if (
            age is not None
            and age <= YOUNG_SP_VOLATILITY_AGE_MAX
            and actual_ip < YOUNG_SP_VOLATILITY_IP_MAX
            and current_over_true_talent_gap > YOUNG_SP_VOLATILITY_GAP_START
        ):
            gap_discount = min(
                YOUNG_SP_VOLATILITY_MAX_DISCOUNT,
                (current_over_true_talent_gap - YOUNG_SP_VOLATILITY_GAP_START) / 40.0,
            )
            track_record_discount = min(
                0.06,
                (YOUNG_SP_VOLATILITY_IP_MAX - actual_ip) / YOUNG_SP_VOLATILITY_IP_MAX * 0.06,
            )
            discount = round(
                min(YOUNG_SP_VOLATILITY_MAX_DISCOUNT, gap_discount + track_record_discount),
                4,
            )
            adjusted *= 1.0 - discount
            adjustments["young_sp_volatility_discount"] = discount
            adjustments["actual_mlb_ip"] = round(actual_ip, 3)
            adjustments["current_over_true_talent_gap"] = round(current_over_true_talent_gap, 4)
    adjustments["score_before_role_adjustment"] = round(score, 2)
    return adjusted, adjustments


def _category_drivers(result: ValuationResult) -> list[str]:
    drivers = []
    for category, value in sorted(
        result.category_values.items(),
        key=lambda item: abs(item[1]),
        reverse=True,
    ):
        if abs(value) < 0.05:
            continue
        drivers.append(f"{category} {value:+.2f}")
        if len(drivers) >= 4:
            break
    return drivers


def _dedupe_results(results: Iterable[ValuationResult]) -> tuple[list[ValuationResult], int, int]:
    by_key: dict[tuple[str, str], ValuationResult] = {}
    missing_identity_count = 0
    duplicate_identity_count = 0
    for result in results:
        key = identity_key(result.player)
        if key is None:
            missing_identity_count += 1
            continue
        previous = by_key.get(key)
        if previous is not None:
            duplicate_identity_count += 1
            if result.total_value <= previous.total_value:
                continue
        by_key[key] = result
    return list(by_key.values()), missing_identity_count, duplicate_identity_count


def _row(
    result: ValuationResult,
    score: float,
    production_score: float,
    horizon: dict[str, Any],
    rank: int,
    stability: dict[str, Any] | None = None,
    role_adjustments: dict[str, Any] | None = None,
) -> dict:
    player = result.player
    role = _role(player)
    mlbam_id = str(player.metadata.get("mlbam_id"))
    age = _coerce_age(player.metadata.get("age"))
    age_multiplier = _age_multiplier(player, age)
    reliability = _playing_time_reliability(player)
    drivers = _category_drivers(result)
    drivers.append(f"playing time reliability {reliability:.0f}")
    return {
        "id": f"vc_mlb_{mlbam_id}_{role}",
        "player_type": "mlb",
        "name": player.name,
        "mlbam_id": int(mlbam_id) if mlbam_id.isdigit() else mlbam_id,
        "role": role,
        "pool": player.pool.value,
        "positions": list(player.positions),
        "team": player.metadata.get("team") or "",
        "mlb_team": player.metadata.get("team") or "",
        "age": age,
        "rank": rank,
        "score": round(score, 2),
        "value": round(score, 2),
        "value_scale": "0_100_valucast_mlb_shadow_dynasty_score",
        "value_source": VALUE_SOURCE,
        "confidence": _confidence(player, reliability),
        "projection_value": round(result.total_value, 4),
        "dynasty_horizon_value": round(horizon["value"], 4),
        "components": {
            "production_score": round(production_score, 2),
            "playing_time_reliability": reliability,
            "season_category_value": round(result.total_value, 4),
            "dynasty_horizon_value": round(horizon["value"], 4),
            "projection_stability": stability or {},
            "role_adjustments": role_adjustments or {},
            "horizon_years": horizon["years"],
            "age_adjustment": _round(age_multiplier, 4),
            "age_adjustment_status": (
                "applied" if age_multiplier is not None else "missing_age"
            ),
            "age_source": player.metadata.get("age_source"),
        },
        "stat_line": {
            "source": "valucast_current_projection",
            "stats": _projection_stats(player),
            "category_values": {
                category: round(value, 4)
                for category, value in result.category_values.items()
            },
            "raw_values": {
                category: _round(value, 4)
                for category, value in result.raw_values.items()
            },
        },
        "drivers": drivers[:5],
    }


def build_mlb_dynasty_layer(
    players: Iterable[PlayerProjection],
    generated_at: str,
    identities: dict[str, dict] | None = None,
) -> dict:
    season = _season_from_generated_at(generated_at)
    players = _attach_ages(players, identities or {}, season)
    eligible = filter_by_playing_time(
        players,
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
    )
    engine = ValuationEngine(
        post_processors=[
            AgeCurve(
                hitter_curve=HITTER_AGE_CURVE,
                pitcher_curve=PITCHER_AGE_CURVE,
            ),
            VolumeMultiplier(),
        ]
    )
    league = build_config(mode="categories")
    results = engine.value_players(eligible, league)
    ros_by_key = _ros_lookup(engine, eligible)
    stability_by_player_id: dict[str, dict[str, Any]] = {}
    adjusted_results = []
    for result in results:
        adjusted, stability = _stability_adjusted_result(result, ros_by_key)
        adjusted_results.append(adjusted)
        stability_by_player_id[adjusted.player.id] = stability
    deduped, missing_identity_count, duplicate_identity_count = _dedupe_results(adjusted_results)
    horizon_rows = [
        (result, _horizon_profile(result, season))
        for result in deduped
    ]
    values = [horizon["value"] for _, horizon in horizon_rows]
    floor = _percentile(values, 0.05)
    ceiling = max(values) if values else floor

    rows = []
    for result, horizon in horizon_rows:
        production_score = _scale_value(horizon["value"], floor, ceiling)
        reliability = _playing_time_reliability(result.player)
        score = (
            PRODUCTION_WEIGHT * production_score
            + RELIABILITY_WEIGHT * reliability
        )
        score, role_adjustments = _role_adjusted_score(
            result.player,
            score,
            stability_by_player_id.get(result.player.id),
        )
        rows.append((score, production_score, horizon, result, role_adjustments))

    rows.sort(
        key=lambda item: (
            -item[0],
            -item[2]["value"],
            str(item[3].player.name),
            str(item[3].player.metadata.get("mlbam_id") or ""),
        )
    )
    board = [
        _row(
            result,
            score,
            production_score,
            horizon,
            rank,
            stability_by_player_id.get(result.player.id),
            role_adjustments,
        )
        for rank, (score, production_score, horizon, result, role_adjustments) in enumerate(rows, 1)
    ]
    age_coverage_count = sum(1 for row in board if row.get("age") is not None)
    age_coverage_rate = round(age_coverage_count / len(board), 4) if board else 0.0
    blockers = []
    if age_coverage_rate < MIN_AGE_COVERAGE_RATE:
        blockers.append(
            "ValuCast MLB age coverage is below the promotion threshold.",
        )
    ready_for_live_consumers = not blockers
    return {
        "status": "shadow_only",
        "layer_name": LAYER_NAME,
        "layer_version": LAYER_VERSION,
        "generated_at": generated_at,
        "source_policy": {
            "kind": "valucast_mlb_projection_value",
            "projection_source": "data/projections/current.json",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
        },
        "value_contract": {
            "score_range": [0.0, 100.0],
            "value_kind": "multi_year_dynasty_horizon",
            "horizon_years": len(HORIZON_YEAR_WEIGHTS),
            "horizon_year_weights": [
                {"offset": offset, "weight": weight}
                for offset, weight in HORIZON_YEAR_WEIGHTS
            ],
            "score_weights": {
                "horizon_production_score": PRODUCTION_WEIGHT,
                "playing_time_reliability": RELIABILITY_WEIGHT,
            },
            "horizon_production_score": "Three-year ValuCast MLB dynasty horizon scaled between p05 and max of eligible MLB projection rows after ROS stability adjustment.",
            "horizon_model": "Carries the current ValuCast category projection forward through age-curve ratios and reliability decay.",
            "projection_stability": (
                "Blends current-season category value with the same player's ROS "
                "true-talent annualized category value; extreme current-over-ROS outliers receive the "
                "largest pullback before dynasty-horizon scaling."
            ),
            "true_talent_floor": (
                "Established high-reliability MLB hitters and starters cannot fall below "
                f"{TRUE_TALENT_FLOOR_SHARE:.0%} of their annualized ROS true-talent category value."
            ),
            "role_adjustments": {
                "young_sp_volatility_age_max": YOUNG_SP_VOLATILITY_AGE_MAX,
                "young_sp_volatility_ip_max": YOUNG_SP_VOLATILITY_IP_MAX,
                "young_sp_volatility_gap_start": YOUNG_SP_VOLATILITY_GAP_START,
                "young_sp_volatility_max_discount": YOUNG_SP_VOLATILITY_MAX_DISCOUNT,
                "reliever_dynasty_score_cap": RELIEVER_DYNASTY_SCORE_CAP,
            },
            "ros_stability_weights": {
                "base_ros_weight": ROS_STABILITY_BASE_WEIGHT,
                "max_ros_weight": ROS_STABILITY_MAX_WEIGHT,
                "underperformance_ros_weight": ROS_STABILITY_UNDERPERFORMANCE_WEIGHT,
                "gap_to_max_weight": ROS_STABILITY_GAP_TO_MAX,
            },
            "playing_time_reliability": "PA/IP volume shrinkage score from the same projection artifact.",
            "age_adjustment": "ValuCast identity birth-date age curve applied as of April 1 of the projection season when age is available.",
            "age_source": "projection metadata first, else projections/data/identity.json birth_date by MLBAM ID.",
        },
        "validation": {
            "ready_for_live_consumers": ready_for_live_consumers,
            "row_count": len(board),
            "eligible_projection_count": len(eligible),
            "missing_mlbam_count": missing_identity_count,
            "duplicate_identity_count": duplicate_identity_count,
            "horizon_year_count": len(HORIZON_YEAR_WEIGHTS),
            "age_coverage_count": age_coverage_count,
            "age_coverage_rate": age_coverage_rate,
            "age_coverage_threshold": MIN_AGE_COVERAGE_RATE,
            "ranks_contiguous": [row["rank"] for row in board] == list(range(1, len(board) + 1)),
            "generated_date": _date_part(generated_at),
            "blockers": blockers,
        },
        "promotion": {
            "live_consumer": "candidate_ready" if ready_for_live_consumers else "blocked",
            "feeds_live_valucast_snapshot": ready_for_live_consumers,
            "next_allowed_step": "add_multi_year_dynasty_horizon_and_cross_universe_calibration",
            "reason": (
                "MLB layer passes standalone multi-year horizon gates."
                if ready_for_live_consumers
                else blockers[0]
            ),
        },
        "limitations": blockers,
        "players": board,
    }


def archive_layer(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "layer_version": payload["layer_version"],
        "generated_at": payload["generated_at"],
        "validation": payload["validation"],
        "players": payload["players"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_mlb_dynasty_layer(
    projection_path: Path = PROJECTION_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    identity_data_dir: Path = IDENTITY_DATA_DIR,
) -> dict:
    store = ProjectionStore(projection_path)
    identities = load_identity_store(identity_data_dir)
    payload = build_mlb_dynasty_layer(
        store.get_all(),
        _generated_at(store),
        identities=identities,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)

    date_str = _date_part(payload["generated_at"]) or datetime.now(
        timezone.utc
    ).date().isoformat()
    archive_path, archive_changed = archive_layer(payload, date_str, archive_dir)
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "row_count": payload["validation"]["row_count"],
        "missing_mlbam_count": payload["validation"]["missing_mlbam_count"],
        "ready_for_live_consumers": payload["validation"]["ready_for_live_consumers"],
    }
