"""Presentation badges for independently evidenced MLB roster and debut facts."""

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

OFFICIAL_SOURCE = "official_mlb_statsapi_dated_team_rosters"


def roster_id(value):
    if type(value) not in (int, str):
        return None
    value = str(value)
    return value if value.isascii() and value.isdecimal() and not value.startswith("0") else None


def mlb_date(timestamp):
    try:
        return timestamp.astimezone(ZoneInfo("America/New_York")).date()
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _date(value):
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except (TypeError, ValueError):
        return None


def season_dates(start, end):
    start, end = _date(start), _date(end)
    if not start or not end or start.year != end.year or start >= end:
        return None, None
    return start, end


def qualified_roster_display(evidence, *, now=None):
    """Return positive display facts by exact ID; an absent fact proves nothing."""
    now = now if now is not None else datetime.now(timezone.utc)
    if not isinstance(evidence, dict) or evidence.get("source") != OFFICIAL_SOURCE:
        return {}
    effective = _date(evidence.get("effective_date"))
    today = mlb_date(now)
    start, end = season_dates(evidence.get("season_start"), evidence.get("season_end"))
    rows = evidence.get("by_mlbam")
    if not start or not effective or not today or not start <= effective <= today <= end or not isinstance(rows, dict):
        return {}
    facts = {}
    for key, row in rows.items():
        if not roster_id(key) or not isinstance(row, dict) or row.get("on_40_man") is not True:
            continue
        observed = row.get("observed_at")
        if not isinstance(observed, str):
            continue
        try:
            timestamp = datetime.fromisoformat(observed)
        except ValueError:
            continue
        if timestamp.utcoffset() != timedelta(0) or mlb_date(timestamp) != effective:
            continue
        if not timedelta(0) <= now - timestamp < timedelta(hours=24):
            continue
        facts[key] = {"on_40_man": True, "active_roster": row.get("active_roster") is True,
                      "observed_at": observed}
    return facts


def roster_event_badges(
    *, roster_listed=False, on_40_man=False, active_roster=False,
    debut_recorded=False, rule_5_protection=False, observed_at=None,
):
    """Return labels and tooltips for literal True facts."""
    badges = []
    if on_40_man is True:
        protected = rule_5_protection is True
        badges.append({
            "kind": "40_man",
            "label": "40-man roster · Rule 5 protection" if protected else "40-man roster",
            "title": "Added to the 40-man roster for Rule 5 protection." if protected else "Listed on the MLB 40-man roster.",
        })
    if active_roster is True:
        badges.append({
            "kind": "active",
            "label": "Active MLB roster",
            "title": "Listed on the active MLB roster.",
        })
    if roster_listed is True and on_40_man is not True and active_roster is not True:
        badges.append({
            "kind": "roster_listed",
            "label": "MLB roster listed — active status unverified",
            "title": "Roster data lists this prospect. Active roster status is unverified.",
        })
    if observed_at:
        for badge in badges:
            if badge["kind"] in {"40_man", "active"}:
                badge["observed_at"] = observed_at
                badge["title"] += f" Official MLB roster observed at {observed_at}."
    if debut_recorded is True:
        badges.append({
            "kind": "debut",
            "label": "MLB debut recorded",
            "title": "An MLB appearance is recorded.",
        })
    return badges
