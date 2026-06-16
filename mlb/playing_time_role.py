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
PROJECTION_PATH = ROOT / "projections" / "runs" / "valucast_hp_2026_v1" / "projections.json"
ROSTER_STATUS_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
AVAILABILITY_PATH = ROOT / "data" / "models" / "valucast_mlb_availability.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_playing_time_role_tracker.json"

ARTIFACT_NAME = "valucast_playing_time_role_tracker"
TRACKER_VERSION = "0.1.0"


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _clean_float(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    return numeric if numeric == numeric else 0.0


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


def _hitter_role(stats: dict) -> tuple[str, float, str]:
    pa = _clean_float(stats.get("PA"))
    if pa >= 560:
        return "everyday_regular", pa, "600 PA pace"
    if pa >= 430:
        return "regular", pa, "regular-volume plate appearances"
    if pa >= 260:
        return "part_time_or_strong_side", pa, "part-time plate appearances"
    return "bench_or_depth", pa, "thin projected plate appearances"


def _pitcher_role(pool: str, stats: dict) -> tuple[str, float, str]:
    ip = _clean_float(stats.get("IP"))
    starts = _clean_float(stats.get("GS"))
    sv_hld = _clean_float(stats.get("SV_HLD")) or (
        _clean_float(stats.get("SV")) + _clean_float(stats.get("HLD"))
    )
    if pool == "starter" or starts >= 18 or ip >= 125:
        if ip >= 150 or starts >= 24:
            return "rotation_workhorse", ip, "starter volume"
        return "rotation_starter", ip, "starter-leaning volume"
    if pool == "reliever" or sv_hld >= 12:
        if sv_hld >= 22:
            return "leverage_reliever", ip, "save/hold leverage"
        return "middle_relief", ip, "relief volume"
    if ip >= 75:
        return "swingman_or_bulk", ip, "bulk innings"
    return "depth_arm", ip, "thin projected innings"


def _role_profile(row: dict) -> tuple[str, float, str, str]:
    pool = str(row.get("pool") or "").lower()
    stats = row.get("stats") or {}
    if pool == "hitter":
        role, volume, basis = _hitter_role(stats)
        return role, round(volume, 1), "PA", basis
    role, volume, basis = _pitcher_role(pool, stats)
    return role, round(volume, 1), "IP", basis


def _row_profile(row: dict, roster_lookup: dict[str, dict], availability_lookup: dict[str, dict]) -> dict | None:
    mlbam_id = _mlbam_id(row)
    if not mlbam_id:
        return None
    role_label, volume, unit, basis = _role_profile(row)
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
        "active_mlb_roster": active is True,
        "availability_status": availability_status,
        "active_injury_risk": availability.get("active_injury_risk") is True,
        "availability_source": availability.get("source"),
        "roster_status_source": roster.get("source"),
        "usage": "role_context_not_live_rank_or_value",
    }


def build_playing_time_role_tracker(
    *,
    projections: list[dict],
    roster_status: dict | None = None,
    availability: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    roster_by_id = _roster_lookup(roster_status)
    availability_by_id = _availability_lookup(availability)
    profiles = [
        profile
        for row in projections
        if (profile := _row_profile(row, roster_by_id, availability_by_id))
    ]
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
            "projection_source": "projections/runs/valucast_hp_2026_v1/projections.json",
            "roster_status_artifact": (roster_status or {}).get("artifact"),
            "roster_status_generated_at": (roster_status or {}).get("generated_at"),
            "availability_artifact": (availability or {}).get("artifact"),
            "availability_generated_at": (availability or {}).get("generated_at"),
        },
        "summary": {
            "profile_count": len(profiles),
            "active_mlb_roster_count": active_count,
            "active_injury_risk_count": injury_risk_count,
            "role_counts": role_counts,
        },
        "validation": {
            "ready_for_role_context": not blockers,
            "profile_count": len(profiles),
            "duplicate_identity_count": duplicate_identity_count,
            "blockers": blockers,
        },
        "profiles": profiles,
    }


def run_playing_time_role_tracker(
    *,
    projection_path: Path = PROJECTION_PATH,
    roster_status_path: Path = ROSTER_STATUS_PATH,
    availability_path: Path = AVAILABILITY_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    projections = _load_json(projection_path)
    roster_status = _load_json(roster_status_path) if roster_status_path.exists() else None
    availability = _load_json(availability_path) if availability_path.exists() else None
    payload = build_playing_time_role_tracker(
        projections=projections,
        roster_status=roster_status,
        availability=availability,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "ready_for_role_context": payload["validation"]["ready_for_role_context"],
        "profile_count": payload["validation"]["profile_count"],
    }
