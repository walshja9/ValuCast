"""ValuCast-owned MLB active-roster status layer.

This contract uses official MLBAM-keyed team roster endpoints to identify
players currently on active MLB rosters. It exists specifically to keep the
prospect board from retaining players who have already crossed into the MLB
public dynasty board.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
METADATA_PATH = ROOT / "data" / "projections" / "metadata.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
CACHE_PATH = ROOT / "data" / "mlb" / "mlb_roster_status_cache.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_roster_status"

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "ValuCast MLB roster-status builder"
CONTRACT_NAME = "ValuCast MLB Roster Status Contract"
CONTRACT_VERSION = "0.1.0"

# MLB active rosters carry 26 players. A refetch below this floor is treated
# as a partial/truncated statsapi response, not a real roster.
PER_TEAM_ROSTER_FLOOR = 15


def _date_part(value: Any) -> str | None:
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


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _fetch_teams(season: int) -> list[dict]:
    query = urlencode({"sportId": 1, "activeStatus": "Y", "season": season})
    request = Request(
        f"{MLB_API_BASE}/teams?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    teams = payload.get("teams") or []
    return teams if isinstance(teams, list) else []


def _fetch_active_roster(team_id: int | str) -> list[dict]:
    request = Request(
        f"{MLB_API_BASE}/teams/{team_id}/roster?rosterType=active",
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    roster = payload.get("roster") or []
    return roster if isinstance(roster, list) else []


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": "1.0", "queries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": "1.0", "queries": {}}
    if not isinstance(payload, dict):
        return {"schema_version": "1.0", "queries": {}}
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("queries", {})
    return payload


def _save_cache(cache: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(cache, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _load_or_fetch(
    *,
    key: str,
    cache: dict,
    fetcher: Callable[[], list[dict]],
    refresh: bool,
    fetched_at: str,
) -> tuple[list[dict], bool]:
    queries = cache.setdefault("queries", {})
    if not refresh and key in queries:
        return list(queries[key].get("rows") or []), False
    rows = fetcher()
    queries[key] = {"fetched_at": fetched_at, "rows": rows}
    return rows, True


def _team_profile(team: dict) -> dict:
    return {
        "team_id": team.get("id"),
        "team_name": team.get("name"),
        "team_abbreviation": team.get("abbreviation"),
    }


def _row_profile(row: dict, team: dict) -> dict | None:
    person = row.get("person") or {}
    mlbam_id = person.get("id")
    if mlbam_id in (None, ""):
        return None
    position = row.get("position") or {}
    status = row.get("status") or {}
    team_info = _team_profile(team)
    return {
        "mlbam_id": _clean_int(mlbam_id) or mlbam_id,
        "name": person.get("fullName"),
        **team_info,
        "position": position.get("abbreviation"),
        "position_name": position.get("name"),
        "status_code": status.get("code"),
        "status_description": status.get("description"),
        "active_mlb_roster": True,
        "source": "official_mlb_statsapi_active_roster",
    }


def active_roster_lookup(payload: dict | None) -> dict[str, dict]:
    lookup = {}
    for row in (payload or {}).get("profiles") or []:
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            continue
        if row.get("active_mlb_roster") is True:
            lookup[str(mlbam_id)] = row
    return lookup


def build_mlb_roster_status(
    *,
    generated_at: str,
    teams: list[dict],
    rosters_by_team: dict[str, list[dict]],
    season: int | None = None,
) -> dict:
    season = season or _season_from_generated_at(generated_at)
    profiles = []
    for team in teams:
        team_id = str(team.get("id") or "")
        if not team_id:
            continue
        for row in rosters_by_team.get(team_id) or []:
            profile = _row_profile(row, team)
            if profile:
                profiles.append(profile)

    profiles.sort(
        key=lambda row: (
            str(row.get("team_abbreviation") or ""),
            str(row.get("name") or ""),
            str(row.get("mlbam_id") or ""),
        )
    )
    ids = [str(row.get("mlbam_id")) for row in profiles if row.get("mlbam_id") not in (None, "")]
    duplicate_count = len(ids) - len(set(ids))
    blockers = []
    if duplicate_count:
        blockers.append("Duplicate MLBAM identities exist in the active MLB roster artifact.")
    if not profiles:
        blockers.append("Active MLB roster artifact has no player profiles.")
    return {
        "artifact": "valucast_mlb_roster_status",
        "contract_name": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "season": season,
        "source_policy": {
            "kind": "official_mlb_active_roster_status",
            "identity_key": "MLBAM ID",
            "official_mlb_rosters_used": True,
            "name_matching_used": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
            "public_prospect_ranks_used": False,
        },
        "contract": {
            "identity_key": "MLBAM ID",
            "inputs": ["official MLB Stats API active team roster endpoints"],
            "roster_type": "active",
            "use": "Graduates current MLB active-roster identities out of public prospect boards when a ValuCast MLB row exists.",
        },
        "validation": {
            "ready_for_public_snapshot": not blockers,
            "team_count": len(teams),
            "active_roster_profile_count": len(profiles),
            "duplicate_identity_count": duplicate_count,
            "blockers": blockers,
        },
        "profiles": profiles,
    }


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def archive_mlb_roster_status(payload: dict, archive_dir: Path = ARCHIVE_DIR) -> tuple[Path, bool]:
    generated_date = _date_part(payload.get("generated_at")) or datetime.now(
        timezone.utc
    ).date().isoformat()
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{generated_date}.json"
    archive_payload = {
        "generated_at": payload.get("generated_at"),
        "contract_version": payload.get("contract_version"),
        "validation": payload.get("validation") or {},
    }
    text = json.dumps(archive_payload, indent=2, sort_keys=True)
    changed = not archive_path.exists() or archive_path.read_text(encoding="utf-8") != text
    if changed:
        archive_path.write_text(text, encoding="utf-8")
    return archive_path, changed


def run_mlb_roster_status(
    metadata_path: Path = METADATA_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    cache_path: Path = CACHE_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    *,
    generated_at: str | None = None,
    season: int | None = None,
    teams_fetcher: Callable[[int], list[dict]] | None = None,
    roster_fetcher: Callable[[int | str], list[dict]] | None = None,
    refresh: bool = True,
) -> dict:
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    generated_at = generated_at or metadata.get("as_of") or datetime.now(timezone.utc).isoformat()
    season = season or _season_from_generated_at(generated_at)
    cache = _load_cache(cache_path)
    teams, fetched_teams = _load_or_fetch(
        key=f"teams:{season}:sportId=1:activeStatus=Y",
        cache=cache,
        fetcher=lambda: (teams_fetcher or _fetch_teams)(season),
        refresh=refresh,
        fetched_at=generated_at,
    )
    fetch_roster = roster_fetcher or _fetch_active_roster
    rosters_by_team = {}
    fetched_rosters = 0
    degraded_teams: list[str] = []
    for team in teams:
        team_id = team.get("id")
        if team_id in (None, ""):
            continue
        key = f"team:{team_id}:rosterType=active"
        prior_entry = (cache.get("queries", {}).get(key) or {})
        prior_rows = list(prior_entry.get("rows") or [])
        rows, fetched = _load_or_fetch(
            key=key,
            cache=cache,
            fetcher=lambda team_id=team_id: fetch_roster(team_id),
            refresh=refresh,
            fetched_at=generated_at,
        )
        # A statsapi 200-with-empty-or-truncated roster would otherwise overwrite
        # a good cached roster with a partial one. When a refetch comes back below
        # PER_TEAM_ROSTER_FLOOR (an active roster carries 26 players) and prior_rows
        # has more rows than the refetch, keep the prior roster (and preserve its
        # fetched_at) rather than publish a silently-degraded team. This also
        # covers the fully-empty-refetch case.
        if fetched and len(rows) < PER_TEAM_ROSTER_FLOOR and len(prior_rows) > len(rows):
            rows = prior_rows
            cache["queries"][key] = {
                "fetched_at": prior_entry.get("fetched_at") or generated_at,
                "rows": prior_rows,
            }
            degraded_teams.append(str(team_id))
        rosters_by_team[str(team_id)] = rows
        fetched_rosters += int(fetched)
    _save_cache(cache, cache_path)

    if len(degraded_teams) > 5:
        raise RuntimeError(
            f"roster refetch returned empty for {len(degraded_teams)} teams "
            "(> 5) -- likely a league-wide statsapi outage; refusing to publish"
        )
    if degraded_teams:
        print(
            "WARNING: kept prior cached roster for "
            f"{len(degraded_teams)} team(s) that refetched empty: "
            + ", ".join(degraded_teams)
        )

    payload = build_mlb_roster_status(
        generated_at=generated_at,
        season=season,
        teams=teams,
        rosters_by_team=rosters_by_team,
    )
    _write_json(payload, artifact_path)
    archive_path, archive_changed = archive_mlb_roster_status(payload, archive_dir)
    validation = payload["validation"]
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "active_roster_profile_count": validation["active_roster_profile_count"],
        "team_count": validation["team_count"],
        "ready_for_public_snapshot": validation["ready_for_public_snapshot"],
        "fetched_teams": fetched_teams,
        "fetched_rosters": fetched_rosters,
    }
