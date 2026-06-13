"""Shadow ValuCast MLB dynasty value layer.

This layer turns ValuCast's own MLB projection valuation into a versioned
artifact. It intentionally does not consume DD ranks, DD values, or public
market rankings.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from league_values.engine import ValuationEngine
from league_values.models import PlayerPool, PlayerProjection, ValuationResult
from league_values.playing_time import filter_by_playing_time
from league_values.post_processors import VolumeMultiplier
from web.config_builder import build_config
from web.projection_store import ProjectionStore

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_PATH = ROOT / "data" / "projections" / "current.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_dynasty_layer"

LAYER_NAME = "ValuCast MLB Dynasty Value Layer"
LAYER_VERSION = "0.1.0"
VALUE_SOURCE = "valucast_mlb_projection_index_v0_1"

MIN_HITTER_PA = 100
MIN_SP_IP = 40
MIN_RP_IP = 20

PRODUCTION_WEIGHT = 0.95
RELIABILITY_WEIGHT = 0.05

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


def _generated_at(store: ProjectionStore, generated_at: str | None = None) -> str:
    if generated_at:
        return generated_at
    if store.as_of:
        return store.as_of
    return datetime.now(timezone.utc).isoformat()


def _role(player: PlayerProjection) -> str:
    return "pitcher" if player.pool in PITCHER_POOLS else "hitter"


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
    rank: int,
) -> dict:
    player = result.player
    role = _role(player)
    mlbam_id = str(player.metadata.get("mlbam_id"))
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
        "age": None,
        "rank": rank,
        "score": round(score, 2),
        "value": round(score, 2),
        "value_scale": "0_100_valucast_mlb_shadow_dynasty_score",
        "value_source": VALUE_SOURCE,
        "confidence": _confidence(player, reliability),
        "projection_value": round(result.total_value, 4),
        "components": {
            "production_score": round(production_score, 2),
            "playing_time_reliability": reliability,
            "season_category_value": round(result.total_value, 4),
            "age_adjustment": None,
            "age_adjustment_status": "unavailable_in_valucast_projection_artifact",
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
) -> dict:
    eligible = filter_by_playing_time(
        players,
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
    )
    engine = ValuationEngine(post_processors=[VolumeMultiplier()])
    results = engine.value_players(eligible, build_config(mode="categories"))
    deduped, missing_identity_count, duplicate_identity_count = _dedupe_results(results)
    values = [result.total_value for result in deduped]
    floor = _percentile(values, 0.05)
    ceiling = max(values) if values else floor

    rows = []
    for result in deduped:
        production_score = _scale_value(result.total_value, floor, ceiling)
        reliability = _playing_time_reliability(result.player)
        score = (
            PRODUCTION_WEIGHT * production_score
            + RELIABILITY_WEIGHT * reliability
        )
        rows.append((score, production_score, result))

    rows.sort(
        key=lambda item: (
            -item[0],
            -item[2].total_value,
            str(item[2].player.name),
            str(item[2].player.metadata.get("mlbam_id") or ""),
        )
    )
    board = [
        _row(result, score, production_score, rank)
        for rank, (score, production_score, result) in enumerate(rows, 1)
    ]
    age_coverage_count = sum(1 for row in board if row.get("age") is not None)
    blockers = [
        "Current ValuCast projection artifacts do not include age, so no MLB age curve is applied yet.",
        "This is a one-season projection value layer, not a fully calibrated multi-year dynasty horizon.",
    ]
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
            "score_weights": {
                "production_score": PRODUCTION_WEIGHT,
                "playing_time_reliability": RELIABILITY_WEIGHT,
            },
            "production_score": "ValuCast default 5x5 category value scaled between p05 and p99 of eligible MLB projection rows.",
            "playing_time_reliability": "PA/IP volume shrinkage score from the same projection artifact.",
            "age_adjustment": "not applied until ValuCast owns a current age source.",
        },
        "validation": {
            "ready_for_live_consumers": False,
            "row_count": len(board),
            "eligible_projection_count": len(eligible),
            "missing_mlbam_count": missing_identity_count,
            "duplicate_identity_count": duplicate_identity_count,
            "age_coverage_count": age_coverage_count,
            "age_coverage_rate": round(age_coverage_count / len(board), 4) if board else 0.0,
            "ranks_contiguous": [row["rank"] for row in board] == list(range(1, len(board) + 1)),
            "generated_date": _date_part(generated_at),
            "blockers": blockers,
        },
        "promotion": {
            "live_consumer": "blocked",
            "feeds_live_valucast_snapshot": False,
            "next_allowed_step": "add_owned_age_source_and_multi_year_dynasty_horizon",
            "reason": blockers[0],
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
) -> dict:
    store = ProjectionStore(projection_path)
    payload = build_mlb_dynasty_layer(store.get_all(), _generated_at(store))
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
