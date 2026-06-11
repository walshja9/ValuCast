"""League settings import from Fantrax / ESPN public leagues.

Self-contained seam by design: this module + the /league-import route are the
ONLY import surface, so a future paid gate wraps one route. Nothing fetched is
stored server-side. Hard 5s timeout per request — Render's 30s ceiling must
never be near.

Parsers are tolerant: any field we can't read is simply omitted from the
returned partial dict and the caller keeps its current/default value.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import requests

FETCH_TIMEOUT = 5  # seconds
MAX_RESPONSE_BYTES = 512 * 1024  # sanity cap; settings payloads are a few KB

_FANTRAX_RE = re.compile(r"fantrax\.com/fantasy/league/([A-Za-z0-9]+)")
_FANTRAX_API = "https://www.fantrax.com/fxea/general/getLeagueInfo"
_ESPN_API = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/"
             "seasons/{season}/segments/0/leagues/{league_id}?view=mSettings")


class ImportError_(Exception):
    """User-facing import failure; .args[0] is the inline notice text."""


def detect_platform(url: str) -> tuple[str, str] | None:
    """Return (platform, league_id) or None if the URL isn't recognized."""
    if not url:
        return None
    m = _FANTRAX_RE.search(url)
    if m:
        return ("fantrax", m.group(1))
    parsed = urlparse(url)
    if "espn.com" in parsed.netloc and "/baseball/" in parsed.path:
        league_id = parse_qs(parsed.query).get("leagueId", [None])[0]
        if league_id and league_id.isdigit():
            return ("espn", league_id)
    return None


def parse_fantrax(data: dict) -> dict:
    """Extract a settings partial from a fxea getLeagueInfo response."""
    partial = {}
    team_info = data.get("teamInfo")
    if isinstance(team_info, dict) and team_info:
        partial["teams"] = len(team_info)
    roster_info = data.get("rosterInfo") or {}
    max_players = roster_info.get("maxTotalPlayers")
    if isinstance(max_players, int) and max_players > 0:
        partial["roster"] = max_players
    return partial


def parse_espn(data: dict) -> dict:
    """Extract a settings partial from an ESPN mSettings response."""
    partial = {}
    settings = data.get("settings") or {}
    size = settings.get("size")
    if isinstance(size, int) and size > 0:
        partial["teams"] = size
    slot_counts = (settings.get("rosterSettings") or {}).get("lineupSlotCounts") or {}
    total_slots = sum(
        int(v) for v in slot_counts.values()
        if isinstance(v, (int, float)) and v > 0 and not isinstance(v, bool)
    )
    if total_slots > 0:
        partial["roster"] = total_slots
    budget = (settings.get("draftSettings") or {}).get("auctionBudget")
    if isinstance(budget, (int, float)) and budget > 0 and not isinstance(budget, bool):
        partial["budget"] = int(budget)
    return partial


def _fetch_json(url: str, params: dict | None = None) -> dict:
    try:
        # allow_redirects=False: the API hosts are hardcoded; following a 30x
        # is never legitimate here and would re-open the fetch to other hosts.
        resp = requests.get(url, params=params, timeout=FETCH_TIMEOUT,
                            allow_redirects=False,
                            headers={"User-Agent": "ValuCast/1.0 league-import"})
    except requests.RequestException:
        raise ImportError_("Couldn't reach the league host — try again, or enter settings manually.") from None
    if resp.status_code in (401, 403):
        raise ImportError_("This league is private — enter settings manually.")
    if resp.status_code != 200:
        raise ImportError_(f"League lookup failed (HTTP {resp.status_code}) — enter settings manually.")
    try:
        declared_size = int(resp.headers.get("Content-Length", "0") or 0)
    except (TypeError, ValueError):
        declared_size = 0
    if declared_size > MAX_RESPONSE_BYTES:
        raise ImportError_("Unexpected response from the league host — enter settings manually.")
    try:
        data = resp.json()
    except ValueError:
        raise ImportError_("Unexpected response from the league host — enter settings manually.") from None
    if not isinstance(data, dict):
        raise ImportError_("Unexpected response from the league host — enter settings manually.")
    return data


def import_league(url: str) -> tuple[dict, str]:
    """Detect + fetch + parse. Returns (settings_partial, notice).

    Raises ImportError_ with a user-facing message on any failure.
    """
    detected = detect_platform(url)
    if detected is None:
        raise ImportError_("Unsupported URL — paste a Fantrax league URL or an "
                           "ESPN baseball league URL (Yahoo isn't supported yet).")
    platform, league_id = detected
    try:
        if platform == "fantrax":
            data = _fetch_json(_FANTRAX_API, params={"leagueId": league_id})
            partial = parse_fantrax(data)
        else:
            season = datetime.now(timezone.utc).year
            data = _fetch_json(_ESPN_API.format(season=season, league_id=league_id))
            partial = parse_espn(data)
    except ImportError_:
        raise
    except Exception:
        # Third-party response shapes drift; a surprise shape must degrade to
        # the inline notice, never a 500 (htmx drops 5xx without swapping).
        raise ImportError_("Couldn't read that league's settings — enter them manually.") from None
    if not partial:
        raise ImportError_("Found the league but couldn't read its settings — enter them manually.")
    imported = ", ".join(sorted(partial))
    missing = sorted({"teams", "budget", "roster"} - set(partial))
    notice = f"Imported {imported} from {platform.title()}."
    if missing:
        notice += f" Couldn't read {', '.join(missing)} — kept your current values."
    return partial, notice
