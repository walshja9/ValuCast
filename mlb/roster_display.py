"""Read and timestamp qualified official roster evidence for display only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.client import HTTPException
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from web.roster_event_display import (
    APPEARANCE_SOURCE, OFFICIAL_SOURCE, mlb_date, qualified_appearance_display,
    roster_id, season_dates,
)

_API = "https://statsapi.mlb.com/api/v1"


def _fetch(path, **query):
    suffix = "?" + urlencode(query) if query else ""
    request = Request(_API + path + suffix, headers={"User-Agent": "ValuCast roster display"})
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.load(response)
    except (OSError, ValueError, HTTPException):
        return {}
    return payload if isinstance(payload, dict) else {}


def _roster_ids(payload, roster_type, team_id):
    if (payload.get("rosterType") != roster_type
            or roster_id(payload.get("teamId")) != team_id
            or not isinstance(payload.get("roster"), list)):
        return None
    ids = {}
    for row in payload["roster"]:
        if not isinstance(row, dict) or not isinstance(row.get("person"), dict):
            return None
        player_id = roster_id(row["person"].get("id"))
        if not player_id:
            return None
        status = row.get("status")
        status = status.get("code") if isinstance(status, dict) else None
        if not isinstance(status, str) or not status or status.strip() != status:
            return None
        if player_id in ids and ids[player_id] != status:
            return None
        ids[player_id] = status
    return ids


def collect_appearance_display(player_ids, *, fetch=_fetch, clock=lambda: datetime.now(timezone.utc)):
    """Official debut dates include appearances with no PA or pitching outs."""
    player_ids = sorted({player_id for value in player_ids if (player_id := roster_id(value))})
    by_mlbam = {}
    for offset in range(0, len(player_ids), 100):
        batch = player_ids[offset:offset + 100]
        payload = fetch("/people", personIds=",".join(batch))
        people = payload.get("people") if isinstance(payload, dict) else None
        if not isinstance(people, list):
            continue
        observed = clock().astimezone(timezone.utc).isoformat()
        ambiguous = set()
        for person in people:
            if not isinstance(person, dict) or (player_id := roster_id(person.get("id"))) not in batch:
                continue
            row = {"mlb_debut_date": person.get("mlbDebutDate"), "observed_at": observed}
            if player_id in by_mlbam and by_mlbam[player_id] != row:
                ambiguous.add(player_id)
            by_mlbam[player_id] = row
        for player_id in ambiguous:
            by_mlbam.pop(player_id, None)
    evidence = {"source": APPEARANCE_SOURCE, "by_mlbam": by_mlbam}
    return {**evidence, "by_mlbam": qualified_appearance_display(evidence, now=clock())}


def collect_roster_display(*, fetch=_fetch, clock=lambda: datetime.now(timezone.utc)):
    """Fail closed on unverified calendar, roster type, or unusable team rows."""
    day = mlb_date(clock())
    if day is None:
        return {}
    season = str(day.year)
    seasons = fetch(f"/seasons/{season}", sportId=1).get("seasons")
    if not isinstance(seasons, list):
        return {}
    seasons = [row for row in seasons if isinstance(row, dict) and row.get("seasonId") == season]
    if len(seasons) != 1:
        return {}
    start, end = season_dates(seasons[0].get("regularSeasonStartDate"), seasons[0].get("regularSeasonEndDate"))
    if not start or not start <= day <= end:
        return {}
    teams = fetch("/teams", sportId=1, season=season, activeStatus="Y").get("teams")
    if not isinstance(teams, list):
        return {}
    team_ids = {roster_id(row.get("id")) for row in teams if isinstance(row, dict) and isinstance(row.get("sport"), dict) and row["sport"].get("id") == 1}
    if len(team_ids) != 30 or None in team_ids:
        return {}

    def observe(team_id):
        effective_date = day.isoformat()
        path = f"/teams/{team_id}/roster"
        # Keep observation time separate from the date that was requested.
        observed = clock()
        if mlb_date(observed) != day:
            return {}
        forty = _roster_ids(fetch(path, rosterType="40Man", date=effective_date), "40Man", team_id)
        active = _roster_ids(fetch(path, rosterType="active", date=effective_date), "active", team_id)
        completed = clock()
        if mlb_date(completed) != day or forty is None or not 30 <= len(forty) <= 60:
            return {}
        # Offseason endpoints can return identical sets, even with code "A".
        # In season, tolerate September and doubleheader sizes but never certify
        # active status from a collapsed set, an unrelated set, or a tiny response.
        valid_active = active is not None and 15 <= len(active) <= 29 and active.keys() < forty.keys()
        stamp = completed.astimezone(timezone.utc).isoformat()
        return {
            player_id: {
                "on_40_man": status != "D60",
                "active_roster": status != "D60" and valid_active and active.get(player_id) == "A",
                "observed_at": stamp,
            }
            for player_id, status in forty.items()
        }

    by_mlbam = {}
    ambiguous = set()
    with ThreadPoolExecutor(max_workers=8) as pool:
        for observed in pool.map(observe, sorted(team_ids)):
            ambiguous.update(by_mlbam.keys() & observed.keys())
            by_mlbam.update(observed)
    for player_id in ambiguous:
        by_mlbam.pop(player_id)
    return {
        "source": OFFICIAL_SOURCE,
        "effective_date": day.isoformat(),
        "season_start": start.isoformat(),
        "season_end": end.isoformat(),
        "by_mlbam": by_mlbam,
    }
