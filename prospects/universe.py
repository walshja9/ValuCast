"""ValuCast-owned prospect universe for candidate ranking artifacts.

The universe is model-owned membership. DD rows may add comparison/display
context by MLBAM ID plus role, but DD never decides whether a prospect is in
this artifact.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.dynasty import ARTIFACT_PATH as DYNASTY_LAYER_PATH
from prospects.universal import ARTIFACT_PATH as UNIVERSAL_MODEL_PATH

ROOT = Path(__file__).resolve().parents[1]
DD_FEED_PATH = ROOT / "data" / "dd" / "dd_dynasty_feed.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_universe.json"

SCHEMA_VERSION = "1.0"
PITCHER_POSITIONS = {"P", "SP", "RP"}
MINOR_TEAM_MLB_AFFILIATES = {
    "Amarillo Sod Poodles": "ARI",
    "Biloxi Shuckers": "MIL",
    "Bowling Green Hot Rods": "TBR",
    "Charleston RiverDogs": "TBR",
    "Chesapeake Baysox": "BAL",
    "Columbus Clingstones": "ATL",
    "Columbus Clippers": "CLE",
    "Harrisburg Senators": "WSN",
    "Hudson Valley Renegades": "NYY",
    "Iowa Cubs": "CHC",
    "Montgomery Biscuits": "TBR",
    "Reading Fightin Phils": "PHI",
    "Reno Aces": "ARI",
    "Somerset Patriots": "NYY",
    "Tampa Tarpons": "NYY",
    "Toledo Mud Hens": "DET",
    "Wilmington Blue Rocks": "WSN",
    "Wilson Warbirds": "MIL",
}


def infer_role(positions: list[str] | tuple[str, ...] | None) -> str:
    normalized = [str(position).upper() for position in positions or [] if position]
    if normalized and all(position in PITCHER_POSITIONS for position in normalized):
        return "pitcher"
    return "hitter"


def identity_key(mlbam_id: Any, role: str | None) -> tuple[str, str] | None:
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return str(mlbam_id), role


def _positions(profile: dict) -> list[str]:
    raw = profile.get("positions")
    if isinstance(raw, list):
        return [str(position) for position in raw if position]
    position = profile.get("position")
    if position:
        return [str(position)]
    return []


def _context_role(row: dict) -> str:
    role = row.get("role")
    if role in {"hitter", "pitcher"}:
        return role
    return infer_role(row.get("positions"))


def _dd_context_lookup(dd_feed: dict | None) -> dict[tuple[str, str], dict]:
    if not dd_feed:
        return {}
    lookup = {}
    for row in dd_feed.get("players") or []:
        if row.get("player_type") != "prospect":
            continue
        key = identity_key(row.get("mlbam_id"), _context_role(row))
        if key and key not in lookup:
            lookup[key] = row
    return lookup


def _dd_context(row: dict) -> dict:
    return {
        "dd_id": row.get("id"),
        "dd_dynasty_rank": row.get("dynasty_rank"),
        "dd_dynasty_value": row.get("dynasty_value"),
        "dd_prospect_rank": row.get("prospect_rank"),
        "source_ranks": row.get("source_ranks"),
        "breakout_label": row.get("breakout_label"),
        "breakout_rank_change": row.get("breakout_rank_change"),
        "value_history_points": len(row.get("value_history") or []),
        "stat_line": row.get("stat_line"),
        "stat_line_translated": row.get("stat_line_translated"),
        "mlb_stat_line": row.get("mlb_stat_line"),
        "mlb_team": row.get("mlb_team"),
        "eta": row.get("eta"),
    }


def _mlb_team(profile: dict, context: dict | None) -> str | None:
    if context and context.get("mlb_team"):
        return context.get("mlb_team")
    if profile.get("mlb_team"):
        return profile.get("mlb_team")
    team = profile.get("team")
    if isinstance(team, str):
        return MINOR_TEAM_MLB_AFFILIATES.get(team)
    return None


def _universal_keys(universal_model: dict | None) -> set[tuple[str, str]]:
    return {
        key
        for row in (universal_model or {}).get("profiles") or []
        if (key := identity_key(row.get("mlbam_id"), row.get("role")))
    }


def build_universe(
    dynasty_layer: dict,
    universal_model: dict | None = None,
    dd_feed: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    """Build the ValuCast-owned prospect candidate universe."""
    dd_context = _dd_context_lookup(dd_feed)
    universal_keys = _universal_keys(universal_model)
    generated_at = (
        generated_at
        or dynasty_layer.get("generated_at")
        or (universal_model or {}).get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )

    seen: set[tuple[str, str]] = set()
    duplicate_keys: list[tuple[str, str]] = []
    missing_identity_count = 0
    missing_universal_count = 0
    players = []

    for profile in dynasty_layer.get("profiles") or []:
        role = profile.get("role")
        key = identity_key(profile.get("mlbam_id"), role)
        if key is None:
            missing_identity_count += 1
            continue
        if key in seen:
            duplicate_keys.append(key)
            continue
        seen.add(key)
        if universal_keys and key not in universal_keys:
            missing_universal_count += 1

        context = dd_context.get(key)
        player = {
            "mlbam_id": int(profile["mlbam_id"]),
            "role": role,
            "name": profile.get("name"),
            "normalized_name": profile.get("normalized_name"),
            "positions": _positions(profile),
            "position": profile.get("position"),
            "team": profile.get("team"),
            "mlb_team": _mlb_team(profile, context),
            "level": profile.get("level"),
            "age": profile.get("age"),
            "sample": profile.get("sample"),
            "sample_unit": profile.get("sample_unit"),
            "sample_reliability": profile.get("sample_reliability"),
            "universe_source": "valucast_prospect_dynasty_layer",
            "universal_model_profile_present": not universal_keys or key in universal_keys,
        }
        if context:
            player["context_only"] = _dd_context(context)
            player["eta"] = context.get("eta")
        players.append(player)

    if missing_identity_count or duplicate_keys:
        pieces = []
        if missing_identity_count:
            pieces.append(f"missing identities: {missing_identity_count}")
        if duplicate_keys:
            pieces.append(f"duplicate identities: {len(duplicate_keys)}")
        raise ValueError("invalid ValuCast prospect universe (" + ", ".join(pieces) + ")")

    players.sort(
        key=lambda row: (
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            int(row.get("mlbam_id") or 0),
        )
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": "valucast_prospect_universe",
        "generated_at": generated_at,
        "source_policy": {
            "kind": "valucast_model_universe",
            "dd_feed_defines_membership": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "input_artifacts": {
            "dynasty_layer_version": dynasty_layer.get("layer_version"),
            "dynasty_layer_status": dynasty_layer.get("status"),
            "universal_model_version": (universal_model or {}).get("model_version"),
            "universal_model_status": (universal_model or {}).get("status"),
            "dd_feed_schema_version": (dd_feed or {}).get("schema_version"),
        },
        "candidate_count": len(players),
        "validation": {
            "profile_count": len(dynasty_layer.get("profiles") or []),
            "candidate_count": len(players),
            "missing_mlbam_count": 0,
            "duplicate_identity_count": 0,
            "missing_universal_profile_count": missing_universal_count,
            "dd_context_count": sum(1 for row in players if row.get("context_only")),
        },
        "players": players,
    }


def write_universe(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_universe(
    dynasty_layer_path: Path = DYNASTY_LAYER_PATH,
    universal_model_path: Path = UNIVERSAL_MODEL_PATH,
    dd_feed_path: Path = DD_FEED_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    dynasty_layer = json.loads(dynasty_layer_path.read_text(encoding="utf-8"))
    universal_model = (
        json.loads(universal_model_path.read_text(encoding="utf-8"))
        if universal_model_path.exists()
        else None
    )
    dd_feed = (
        json.loads(dd_feed_path.read_text(encoding="utf-8"))
        if dd_feed_path.exists()
        else None
    )
    payload = build_universe(dynasty_layer, universal_model, dd_feed)
    path = write_universe(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "candidate_count": payload["candidate_count"],
        "validation": payload["validation"],
    }
