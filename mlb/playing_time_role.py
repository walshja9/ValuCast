"""ValuCast playing-time and role tracker.

The tracker summarizes role shape from the ValuCast H+P projection run and
joins only MLBAM-keyed availability/active-roster artifacts. It is a context
layer for cards and reports, not an input back into player value.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_PATH = ROOT / "projections" / "runs" / "valucast_hp_2026_v2" / "projections.json"
ROSTER_STATUS_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
AVAILABILITY_PATH = ROOT / "data" / "models" / "valucast_mlb_availability.json"
DYNASTY_LAYER_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_playing_time_role_tracker.json"

ARTIFACT_NAME = "valucast_playing_time_role_tracker"
TRACKER_VERSION = "0.2.0"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / ARTIFACT_NAME

# Role Tracker v2 (shadow, observe-only): re-expresses the coarse v1 PA/IP bucket
# as a volume forecast with a range + a soft role probability distribution, shrunk
# by playing-time reliability and injury risk from the dynasty layer. It does NOT
# replace the v1 fields the card reads; it accrues alongside them for grading.
ROLE_V2_VERSION = "2.0.0"
DEFAULT_RELIABILITY = 50.0
DEFAULT_CERTAINTY = 40.0
ROLE_WATCH_EXCLUDED_STATUSES = {
    "injured", "rehab", "inactive", "stale_or_inactive", "unknown", ""
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if numeric == numeric else 0.0


def _opt_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _mlbam_id(row: dict) -> str | None:
    metadata = row.get("metadata") or {}
    value = metadata.get("mlbam_id") or row.get("mlbam_id")
    if value in (None, ""):
        return None
    return str(value)


def _identity_key(row: dict) -> tuple[str, str] | None:
    mlbam_id = _mlbam_id(row)
    pool = str(row.get("pool") or "").lower()
    if not mlbam_id or not pool:
        return None
    return mlbam_id, pool


def _roster_lookup(roster_status: dict | None) -> dict[str, dict]:
    lookup = {}
    for row in (roster_status or {}).get("profiles") or []:
        value = row.get("mlbam_id")
        if value not in (None, ""):
            lookup[str(value)] = row
    return lookup


def _availability_lookup(availability: dict | None) -> dict[str, dict]:
    lookup = {}
    for row in (availability or {}).get("profiles") or []:
        value = row.get("mlbam_id")
        if value not in (None, ""):
            lookup[str(value)] = row
    return lookup


# Role thresholds are FULL-SEASON volumes, but the projection source is
# REST-OF-SEASON — without annualization every player in the league decays
# toward bench_or_depth as the calendar advances (found 7/2: Bobby Witt Jr.
# at 257 ROS PA labeled "bench_or_depth"). Thresholds are applied to
# season-pace volume; displayed volumes stay honest ROS numbers.
MLB_2026_REGULAR_SEASON_START = "2026-03-26"
MLB_2026_REGULAR_SEASON_END = "2026-09-27"
MAX_PACE_FACTOR = 4.0  # late-season ROS volumes are tiny + noisy; cap the blowup


def _season_pace_factor(as_of: str | None) -> float:
    from datetime import date as _date

    try:
        current = _date.fromisoformat(str(as_of)[:10])
    except (TypeError, ValueError):
        return 1.0
    start = _date.fromisoformat(MLB_2026_REGULAR_SEASON_START)
    end = _date.fromisoformat(MLB_2026_REGULAR_SEASON_END)
    total = (end - start).days
    if current <= start or total <= 0:
        return 1.0
    remaining = max((end - current).days, 1)
    return _clamp(total / remaining, 1.0, MAX_PACE_FACTOR)


def _hitter_role(stats: dict, pace: float = 1.0) -> tuple[str, float, str]:
    pa = _clean_float(stats.get("PA"))
    season_pa = pa * pace
    if season_pa >= 560:
        return "everyday_regular", pa, "600 PA pace"
    if season_pa >= 430:
        return "regular", pa, "regular-volume plate appearances"
    if season_pa >= 260:
        return "part_time_or_strong_side", pa, "part-time plate appearances"
    return "bench_or_depth", pa, "thin projected plate appearances"


def _pitcher_role(pool: str, stats: dict, pace: float = 1.0) -> tuple[str, float, str]:
    ip = _clean_float(stats.get("IP"))
    starts = _clean_float(stats.get("GS")) * pace
    sv_hld = (_clean_float(stats.get("SV_HLD")) or (
        _clean_float(stats.get("SV")) + _clean_float(stats.get("HLD"))
    )) * pace
    season_ip = ip * pace
    if pool == "starter" or starts >= 18:
        if season_ip >= 150 or starts >= 24:
            return "rotation_workhorse", ip, "starter volume"
        return "rotation_starter", ip, "starter-leaning volume"
    if pool == "reliever" or sv_hld >= 12:
        if sv_hld >= 22:
            return "leverage_reliever", ip, "save/hold leverage"
        return "middle_relief", ip, "relief volume"
    if season_ip >= 75:
        return "swingman_or_bulk", ip, "bulk innings"
    return "depth_arm", ip, "thin projected innings"


def _role_profile(row: dict, pace: float = 1.0) -> tuple[str, float, str, str]:
    pool = str(row.get("pool") or "").lower()
    stats = row.get("stats") or {}
    if pool == "hitter":
        role, volume, basis = _hitter_role(stats, pace)
        return role, round(volume, 1), "PA", basis
    role, volume, basis = _pitcher_role(pool, stats, pace)
    return role, round(volume, 1), "IP", basis


def _role_contract_fields(row: dict) -> dict:
    pool = str(row.get("pool") or "").lower()
    metadata = row.get("metadata") or {}
    blockers = []
    if metadata.get("remaining_opportunity_clamped") is True:
        blockers.append("remaining_opportunity_clamped")
    if pool == "hitter":
        return {
            "source_pool": pool,
            "starter_probability": None,
            "projected_starts_ros": None,
            "projected_innings_ros": None,
            "role_context_status": "blocked" if blockers else "ready",
            "role_context_blockers": blockers,
        }
    stats = row.get("stats") or {}
    raw_probability = metadata.get("p_sp")
    probability = _opt_float(raw_probability)
    starts = _clean_float(stats.get("GS"))
    innings = _clean_float(stats.get("IP"))
    if raw_probability not in (None, "") and (
        probability is None or not 0.0 <= probability <= 1.0
    ):
        blockers.append("starter_probability_out_of_range")
    if starts < 0:
        blockers.append("negative_projected_starts")
    if innings < 0:
        blockers.append("negative_projected_innings")
    if starts >= 0.5 and innings == 0:
        blockers.append("projected_starts_without_innings")
    return {
        "source_pool": pool,
        "starter_probability": round(probability, 4) if probability is not None else None,
        "projected_starts_ros": round(starts, 4),
        "projected_innings_ros": round(innings, 1),
        "role_context_status": "blocked" if blockers else "ready",
        "role_context_blockers": blockers,
    }


def role_watch_rows(profiles: list[dict]) -> list[dict]:
    rows = []
    for profile in profiles:
        status = str(profile.get("availability_status") or "").strip().lower()
        probability = _opt_float(profile.get("starter_probability"))
        starts = _clean_float(profile.get("projected_starts_ros"))
        innings = _clean_float(profile.get("projected_innings_ros"))
        if (
            profile.get("source_pool") != "reliever"
            or profile.get("role_context_status") != "ready"
            or profile.get("active_mlb_roster") is not True
            or profile.get("active_injury_risk") is True
            or status in ROLE_WATCH_EXCLUDED_STATUSES
            or probability is None
            or starts < 1.0
            or innings <= 0.0
        ):
            continue
        display_status = status.replace("_", " ").replace("mlb", "MLB")
        row = dict(profile)
        row["opportunity_explanation"] = (
            f"Projected for {starts:.1f} starts and {innings:.1f} innings the rest "
            f"of the season while the source role remains relief. Starter "
            f"probability is {probability:.0%}. Roster status is "
            f"{display_status}."
        )
        rows.append(row)
    return sorted(
        rows,
        key=lambda row: (
            -_clean_float(row.get("projected_starts_ros")),
            str(row.get("name") or "").casefold(),
        ),
    )


def _row_profile(
    row: dict,
    roster_lookup: dict[str, dict],
    availability_lookup: dict[str, dict],
    pace: float = 1.0,
) -> dict | None:
    mlbam_id = _mlbam_id(row)
    if not mlbam_id:
        return None
    role_label, volume, unit, basis = _role_profile(row, pace)
    contract = _role_contract_fields(row)
    roster = roster_lookup.get(mlbam_id) or {}
    availability = availability_lookup.get(mlbam_id) or {}
    active = roster.get("active_mlb_roster")
    availability_status = availability.get("status") or (
        "active_mlb_roster" if active is True else "unknown"
    )
    return {
        "mlbam_id": mlbam_id,
        "identity_key": f"{mlbam_id}_{row.get('pool')}",
        "name": row.get("name"),
        "team": row.get("team") or ((row.get("metadata") or {}).get("team")),
        "pool": row.get("pool"),
        "positions": row.get("positions") or [],
        "projected_role": role_label,
        "projected_volume": volume,
        "projected_volume_unit": unit,
        "role_basis": basis,
        "remaining_opportunity_clamped": (
            (row.get("metadata") or {}).get("remaining_opportunity_clamped") is True
        ),
        **contract,
        "active_mlb_roster": active is True,
        "availability_status": availability_status,
        "active_injury_risk": availability.get("active_injury_risk") is True,
        "availability_source": availability.get("source"),
        "roster_status_source": roster.get("source"),
        "usage": "role_context_not_live_rank_or_value",
    }


# --- Role Tracker v2 (shadow, observe-only) --------------------------------

def _dynasty_lookup(dynasty_layer: dict | None) -> dict[str, dict]:
    """MLBAM-keyed playing-time signals from the dynasty layer."""
    lookup: dict[str, dict] = {}
    for row in (dynasty_layer or {}).get("players") or []:
        value = row.get("mlbam_id")
        if value in (None, ""):
            continue
        components = row.get("components") or {}
        role_adj = components.get("role_adjustments") or {}
        track = components.get("track_record") or {}
        certainty = role_adj.get("track_record_certainty")
        if certainty is None:
            certainty = track.get("track_record_certainty")
        lookup[str(value)] = {
            "reliability": _opt_float(components.get("playing_time_reliability")),
            "track_record_certainty": _opt_float(certainty),
            "availability_risk_discount": _clean_float(
                components.get("availability_risk_discount")
            ),
            "experience_band": track.get("experience_band")
            or role_adj.get("track_record_experience_band")
            or "unknown",
        }
    return lookup


def _volume_forecast(base: float, unit: str, signals: dict, injury: bool) -> dict:
    reliability = signals.get("reliability")
    rel = _clamp((reliability if reliability is not None else DEFAULT_RELIABILITY) / 100.0, 0.0, 1.0)
    risk = _clamp(signals.get("availability_risk_discount", 0.0), 0.0, 1.0)
    uncertainty = _clamp((1.0 - rel) * 0.30 + risk * 0.50 + (0.06 if injury else 0.0), 0.06, 0.55)
    point = base * (1.0 - 0.5 * risk - (0.04 if injury else 0.0))
    return {
        "unit": unit,
        "base": round(base, 1),
        "point": round(point, 1),
        "low": round(point * (1.0 - uncertainty), 1),
        # Upside is capped tighter than downside: a player rarely beats a full-season
        # projection by much, but injury can erase most of it.
        "high": round(point * (1.0 + uncertainty * 0.55), 1),
        "basis": "projection_volume_shrunk_by_reliability_and_injury_risk",
    }


def _hitter_bucket(pa: float) -> str:
    if pa >= 560:
        return "everyday_regular"
    if pa >= 430:
        return "regular"
    if pa >= 260:
        return "part_time_or_strong_side"
    return "bench_or_depth"


def _starter_bucket(ip: float) -> str:
    # v1 keeps a pool=="starter" arm in {workhorse, rotation_starter} only.
    return "rotation_workhorse" if ip >= 150 else "rotation_starter"


# Quantile fan over the volume range -> a soft role distribution. Weights sum to 1.
_FAN = ((-1.0, 0.1), (-0.5, 0.2), (0.0, 0.4), (0.5, 0.2), (1.0, 0.1))


def _role_distribution(pool: str, vf: dict, v1_role: str, pace: float = 1.0) -> tuple[dict, str]:
    if pool == "reliever":
        # Reliever role (leverage vs middle) is SV/HLD-driven, not forecastable from
        # an innings range, so keep the v1 label. ponytail: soft only where volume rules.
        return {v1_role: 1.0}, "save_hold_driven_v1_label"
    bucket_fn = _hitter_bucket if pool == "hitter" else _starter_bucket
    point, low, high = vf["point"], vf["low"], vf["high"]
    down = point - low
    up = high - point
    dist: dict[str, float] = {}
    for offset, weight in _FAN:
        vol = point + (offset * down if offset < 0 else offset * up)
        bucket = bucket_fn(vol * pace)
        dist[bucket] = dist.get(bucket, 0.0) + weight
    total = sum(dist.values()) or 1.0
    return {k: round(v / total, 3) for k, v in dist.items()}, "volume_fan"


def _role_confidence(signals: dict, injury: bool) -> tuple[str, float]:
    reliability = signals.get("reliability")
    certainty = signals.get("track_record_certainty")
    rel = reliability if reliability is not None else DEFAULT_RELIABILITY
    cert = certainty if certainty is not None else DEFAULT_CERTAINTY
    score = 0.55 * _clamp(rel, 0.0, 100.0) + 0.45 * _clamp(cert, 0.0, 100.0)
    if injury:
        score -= 8.0
    score = _clamp(score, 0.0, 100.0)
    band = "high" if score >= 70 else "moderate" if score >= 45 else "low"
    return band, round(score, 1)


def _role_v2(profile: dict, dynasty_lookup: dict[str, dict], pace: float = 1.0) -> dict:
    pool = str(profile.get("pool") or "").lower()
    base = _clean_float(profile.get("projected_volume"))
    unit = profile.get("projected_volume_unit") or ("PA" if pool == "hitter" else "IP")
    injury = profile.get("active_injury_risk") is True
    v1_role = profile.get("projected_role")
    matched = dynasty_lookup.get(str(profile.get("mlbam_id")))
    signals = matched or {}
    vf = _volume_forecast(base, unit, signals, injury)
    dist, source = _role_distribution(pool, vf, v1_role, pace)
    most_likely = max(dist, key=dist.get) if dist else v1_role
    band, score = _role_confidence(signals, injury)
    delta = "match" if most_likely == v1_role else f"shift:{v1_role}->{most_likely}"
    return {
        "model_version": ROLE_V2_VERSION,
        "status": "shadow_observe_only",
        "feeds_card": False,
        "volume_forecast": vf,
        "role_probabilities": dist,
        "role_probability_source": source,
        "most_likely_role": most_likely,
        "role_confidence": band,
        "confidence_score": score,
        "signals": {
            "reliability": signals.get("reliability"),
            "track_record_certainty": signals.get("track_record_certainty"),
            "availability_risk_discount": signals.get("availability_risk_discount", 0.0),
            "active_injury_risk": injury,
            "experience_band": signals.get("experience_band", "unknown"),
            "dynasty_layer_matched": matched is not None,
        },
        "delta_vs_v1_role": delta,
    }


def _v2_summary(profiles: list[dict]) -> dict:
    blocks = [profile.get("role_v2") or {} for profile in profiles]
    confidence_counts = {"low": 0, "moderate": 0, "high": 0}
    for block in blocks:
        band = block.get("role_confidence")
        if band in confidence_counts:
            confidence_counts[band] += 1
    return {
        "model_version": ROLE_V2_VERSION,
        "status": "shadow_observe_only",
        "feeds_card": False,
        "feeds_live_rank": False,
        "feeds_live_value": False,
        "profile_count": len(blocks),
        "volume_fan_role_count": sum(
            1 for block in blocks if block.get("role_probability_source") == "volume_fan"
        ),
        "save_hold_label_count": sum(
            1
            for block in blocks
            if block.get("role_probability_source") == "save_hold_driven_v1_label"
        ),
        "dynasty_layer_matched_count": sum(
            1 for block in blocks if (block.get("signals") or {}).get("dynasty_layer_matched")
        ),
        "role_shift_vs_v1_count": sum(
            1 for block in blocks if str(block.get("delta_vs_v1_role")).startswith("shift")
        ),
        "confidence_counts": confidence_counts,
    }


# ---------------------------------------------------------------------------

def build_playing_time_role_tracker(
    *,
    projections: list[dict],
    roster_status: dict | None = None,
    availability: dict | None = None,
    dynasty_layer: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    pace = _season_pace_factor(generated_at)
    roster_by_id = _roster_lookup(roster_status)
    availability_by_id = _availability_lookup(availability)
    dynasty_by_id = _dynasty_lookup(dynasty_layer)
    profiles = [
        profile
        for row in projections
        if (profile := _row_profile(row, roster_by_id, availability_by_id, pace))
    ]
    for profile in profiles:
        profile["season_pace_factor"] = round(pace, 2)
        profile["role_v2"] = _role_v2(profile, dynasty_by_id, pace)
    identity_keys = [row["identity_key"] for row in profiles]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    active_count = sum(1 for row in profiles if row["active_mlb_roster"])
    injury_risk_count = sum(1 for row in profiles if row["active_injury_risk"])
    role_counts: dict[str, int] = {}
    for row in profiles:
        role = row["projected_role"]
        role_counts[role] = role_counts.get(role, 0) + 1
    blockers = []
    if not profiles:
        blockers.append("Playing-time tracker has no profiles.")
    if duplicate_identity_count:
        blockers.append("Playing-time tracker has duplicate MLBAM identities.")
    return {
        "artifact": ARTIFACT_NAME,
        "tracker_version": TRACKER_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "source_policy": {
            "kind": "valucast_playing_time_role_tracker",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "public_rankings_used": False,
            "market_values_used": False,
            "name_based_joins_used": False,
            "feeds_live_rank": False,
            "feeds_live_value": False,
        },
        "input_artifacts": {
            "projection_source": "projections/runs/valucast_hp_2026_v2/projections.json",
            "roster_status_artifact": (roster_status or {}).get("artifact"),
            "roster_status_generated_at": (roster_status or {}).get("generated_at"),
            "availability_artifact": (availability or {}).get("artifact"),
            "availability_generated_at": (availability or {}).get("generated_at"),
            "dynasty_layer_artifact": (dynasty_layer or {}).get("layer_name"),
            "dynasty_layer_generated_at": (dynasty_layer or {}).get("generated_at"),
        },
        "summary": {
            "profile_count": len(profiles),
            "active_mlb_roster_count": active_count,
            "active_injury_risk_count": injury_risk_count,
            "role_counts": role_counts,
        },
        "v2": _v2_summary(profiles),
        "validation": {
            "ready_for_role_context": not blockers,
            "profile_count": len(profiles),
            "duplicate_identity_count": duplicate_identity_count,
            "blockers": blockers,
        },
        "profiles": profiles,
    }


def archive_playing_time_role_tracker(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    """Persist the day's role tracker so v2 role/volume forecasts can later be graded
    against realized PA/IP (the accountability harness builds on this). Content-deduped
    + atomic, mirroring rank_v1.archive_rank — v1 shipped without an archive."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "tracker_version": payload["tracker_version"],
        "generated_at": payload["generated_at"],
        "profile_count": payload["validation"]["profile_count"],
        "summary": payload["summary"],
        "v2": payload.get("v2"),
        "profiles": payload["profiles"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_playing_time_role_tracker(
    *,
    projection_path: Path = PROJECTION_PATH,
    roster_status_path: Path = ROSTER_STATUS_PATH,
    availability_path: Path = AVAILABILITY_PATH,
    dynasty_layer_path: Path = DYNASTY_LAYER_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    projections = _load_json(projection_path)
    roster_status = _load_json(roster_status_path) if roster_status_path.exists() else None
    availability = _load_json(availability_path) if availability_path.exists() else None
    dynasty_layer = _load_json(dynasty_layer_path) if dynasty_layer_path.exists() else None
    payload = build_playing_time_role_tracker(
        projections=projections,
        roster_status=roster_status,
        availability=availability,
        dynasty_layer=dynasty_layer,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    date_str = str(payload["generated_at"])[:10]
    archive_path, archive_changed = archive_playing_time_role_tracker(
        payload, date_str, archive_dir=archive_dir
    )
    return {
        "artifact_path": str(artifact_path),
        "ready_for_role_context": payload["validation"]["ready_for_role_context"],
        "profile_count": payload["validation"]["profile_count"],
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
    }
