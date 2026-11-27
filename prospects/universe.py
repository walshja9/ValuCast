"""ValuCast-owned prospect universe for candidate ranking artifacts.

The universe is model-owned membership.
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
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_universe.json"
# Fetched current-org cache (scripts/refresh_prospect_orgs.py, nightly). The
# affiliate-name fallback below labels a player with the org his stat line was
# EARNED under, which goes stale on trades; this cache is org-as-of-today.
CURRENT_ORG_PATH = ROOT / "data" / "prospects" / "raw" / "prospect_current_org.json"

SCHEMA_VERSION = "1.0"
AFFILIATE_MAP_VERSION = "2026-06-14.mlb-statsapi-parent-orgs"
MAX_PROSPECT_AGE = 25
PITCHER_POSITIONS = {"P", "SP", "RP"}
# Current affiliated MiLB teams from MLB Stats API parent-org metadata, plus
# legacy affiliate names still present in historical/current factual inputs.
MINOR_TEAM_MLB_AFFILIATES = {
    "Aberdeen IronBirds": "BAL",
    "Akron RubberDucks": "CLE",
    "Albuquerque Isotopes": "COL",
    "Altoona Curve": "PIT",
    "Amarillo Sod Poodles": "ARI",
    "Arkansas Travelers": "SEA",
    "Asheville Tourists": "HOU",
    "Augusta GreenJackets": "ATL",
    "Beloit Sky Carp": "MIA",
    "Biloxi Shuckers": "MIL",
    "Binghamton Rumble Ponies": "NYM",
    "Birmingham Barons": "CHW",
    "Bowling Green Hot Rods": "TBR",
    "Bradenton Marauders": "PIT",
    "Brooklyn Cyclones": "NYM",
    "Buffalo Bisons": "TOR",
    "Carolina Mudcats": "MIL",
    "Cedar Rapids Kernels": "MIN",
    "Charleston RiverDogs": "TBR",
    "Charlotte Knights": "CHW",
    "Chattanooga Lookouts": "CIN",
    "Chesapeake Baysox": "BAL",
    "Clearwater Threshers": "PHI",
    "Columbia Fireflies": "KC",
    "Columbus Clingstones": "ATL",
    "Columbus Clippers": "CLE",
    "Corpus Christi Hooks": "HOU",
    "Dayton Dragons": "CIN",
    "Daytona Tortugas": "CIN",
    "Delmarva Shorebirds": "BAL",
    "Down East Wood Ducks": "TEX",
    "Dunedin Blue Jays": "TOR",
    "Durham Bulls": "TBR",
    "El Paso Chihuahuas": "SDP",
    "Erie SeaWolves": "DET",
    "Eugene Emeralds": "SFG",
    "Everett AquaSox": "SEA",
    "Fayetteville Woodpeckers": "HOU",
    "Fort Myers Mighty Mussels": "MIN",
    "Fort Wayne TinCaps": "SDP",
    "Frederick Keys": "BAL",
    "Fredericksburg Nationals": "WSN",
    "Fresno Grizzlies": "COL",
    "Frisco RoughRiders": "TEX",
    "Great Lakes Loons": "LAD",
    "Greensboro Grasshoppers": "PIT",
    "Greenville Drive": "BOS",
    "Gwinnett Stripers": "ATL",
    "Harrisburg Senators": "WSN",
    "Hartford Yard Goats": "COL",
    "Hickory Crawdads": "TEX",
    "Hill City Howlers": "CLE",
    "Hillsboro Hops": "ARI",
    "Hub City Spartanburgers": "TEX",
    "Hudson Valley Renegades": "NYY",
    "Indianapolis Indians": "PIT",
    "Inland Empire 66ers": "SEA",
    "Iowa Cubs": "CHC",
    "Jacksonville Jumbo Shrimp": "MIA",
    "Jersey Shore BlueClaws": "PHI",
    "Jupiter Hammerheads": "MIA",
    "Kannapolis Cannon Ballers": "CHW",
    "Knoxville Smokies": "CHC",
    "Lake County Captains": "CLE",
    "Lake Elsinore Storm": "SDP",
    "Lakeland Flying Tigers": "DET",
    "Lansing Lugnuts": "ATH",
    "Las Vegas Aviators": "ATH",
    "Lehigh Valley IronPigs": "PHI",
    "Louisville Bats": "CIN",
    "Memphis Redbirds": "STL",
    "Midland RockHounds": "ATH",
    "Mississippi Braves": "ATL",
    "Montgomery Biscuits": "TBR",
    "Myrtle Beach Pelicans": "CHC",
    "Nashville Sounds": "MIL",
    "New Hampshire Fisher Cats": "TOR",
    "Norfolk Tides": "BAL",
    "Northwest Arkansas Naturals": "KC",
    "Oklahoma City Baseball Club": "LAD",
    "Oklahoma City Comets": "LAD",
    "Oklahoma City Dodgers": "LAD",
    "Omaha Storm Chasers": "KC",
    "Ontario Tower Buzzers": "LAD",
    "Palm Beach Cardinals": "STL",
    "Pensacola Blue Wahoos": "MIA",
    "Peoria Chiefs": "STL",
    "Portland Sea Dogs": "BOS",
    "Quad Cities River Bandits": "KC",
    "Rancho Cucamonga Quakes": "LAA",
    "Reading Fightin Phils": "PHI",
    "Reno Aces": "ARI",
    "Richmond Flying Squirrels": "SFG",
    "Rochester Red Wings": "WSN",
    "Rocket City Trash Pandas": "LAA",
    "Rome Emperors": "ATL",
    "Round Rock Express": "TEX",
    "Sacramento River Cats": "SFG",
    "Salem Red Sox": "BOS",
    "Salem RidgeYaks": "BOS",
    "Salt Lake Bees": "LAA",
    "San Antonio Missions": "SDP",
    "San Jose Giants": "SFG",
    "Scranton/Wilkes-Barre RailRiders": "NYY",
    "Somerset Patriots": "NYY",
    "South Bend Cubs": "CHC",
    "Spokane Indians": "COL",
    "Springfield Cardinals": "STL",
    "St. Lucie Mets": "NYM",
    "St. Paul Saints": "MIN",
    "Stockton Ports": "ATH",
    "Sugar Land Space Cowboys": "HOU",
    "Syracuse Mets": "NYM",
    "Tacoma Rainiers": "SEA",
    "Tampa Tarpons": "NYY",
    "Tennessee Smokies": "CHC",
    "Toledo Mud Hens": "DET",
    "Tri-City Dust Devils": "LAA",
    "Tulsa Drillers": "LAD",
    "Vancouver Canadians": "TOR",
    "Visalia Rawhide": "ARI",
    "West Michigan Whitecaps": "DET",
    "Wichita Wind Surge": "MIN",
    "Wilmington Blue Rocks": "WSN",
    "Wilson Warbirds": "MIL",
    "Winston-Salem Dash": "CHW",
    "Wisconsin Timber Rattlers": "MIL",
    "Worcester Red Sox": "BOS",
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


def _load_current_orgs() -> dict:
    """mlbam_id (str) -> current MLB org. Missing/invalid cache -> {} (fallback)."""
    try:
        payload = json.loads(Path(CURRENT_ORG_PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    orgs = payload.get("orgs")
    return orgs if isinstance(orgs, dict) else {}


def _mlb_team(profile: dict, current_orgs: dict) -> str | None:
    org = current_orgs.get(str(profile.get("mlbam_id") or ""))
    if org:
        return org
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
    generated_at: str | None = None,
    *,
    current_orgs: dict | None = None,
) -> dict:
    """Build the ValuCast-owned prospect candidate universe."""
    universal_keys = _universal_keys(universal_model)
    generated_at = (
        generated_at
        or dynasty_layer.get("generated_at")
        or (universal_model or {}).get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )

    current_orgs = _load_current_orgs() if current_orgs is None else dict(current_orgs)
    seen: set[tuple[str, str]] = set()
    duplicate_keys: list[tuple[str, str]] = []
    missing_identity_count = 0
    missing_universal_count = 0
    age_excluded = []
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
        try:
            age = float(profile.get("age"))
        except (TypeError, ValueError):
            age = None
        if age is not None and age > MAX_PROSPECT_AGE:
            age_excluded.append(
                {
                    "mlbam_id": int(profile["mlbam_id"]),
                    "role": role,
                    "name": profile.get("name"),
                    "age": profile.get("age"),
                    "level": profile.get("level"),
                }
            )
            continue

        player = {
            "mlbam_id": int(profile["mlbam_id"]),
            "role": role,
            "name": profile.get("name"),
            "normalized_name": profile.get("normalized_name"),
            "positions": _positions(profile),
            "position": profile.get("position"),
            "team": profile.get("team"),
            "mlb_team": _mlb_team(profile, current_orgs),
            "level": profile.get("level"),
            "age": profile.get("age"),
            "sample": profile.get("sample"),
            "sample_unit": profile.get("sample_unit"),
            "sample_reliability": profile.get("sample_reliability"),
            "universe_source": "valucast_prospect_dynasty_layer",
            "universal_model_profile_present": not universal_keys or key in universal_keys,
        }
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
            "affiliate_map_version": AFFILIATE_MAP_VERSION,
            "max_prospect_age": MAX_PROSPECT_AGE,
        },
        "candidate_count": len(players),
        "validation": {
            "profile_count": len(dynasty_layer.get("profiles") or []),
            "candidate_count": len(players),
            "missing_mlbam_count": 0,
            "duplicate_identity_count": 0,
            "age_excluded_count": len(age_excluded),
            "age_excluded_sample": age_excluded[:12],
            "missing_universal_profile_count": missing_universal_count,
            "mlb_team_backfill_count": sum(
                1
                for row in players
                if row.get("mlb_team")
                and row.get("team")
            ),
            "missing_mlb_team_count": sum(1 for row in players if not row.get("mlb_team")),
            "current_org_cache_count": sum(
                1
                for row in players
                if current_orgs.get(str(row.get("mlbam_id")))
            ),
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
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    dynasty_layer = json.loads(dynasty_layer_path.read_text(encoding="utf-8"))
    universal_model = (
        json.loads(universal_model_path.read_text(encoding="utf-8"))
        if universal_model_path.exists()
        else None
    )
    payload = build_universe(dynasty_layer, universal_model)
    path = write_universe(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "candidate_count": payload["candidate_count"],
        "validation": payload["validation"],
    }
