"""ValuCast-owned MLB availability layer.

This layer derives MLB injury/rehab availability from official MLBAM-keyed
transaction records. It intentionally avoids player-name joins, DD values,
public rankings, market signals, and projection-derived health guesses.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scraper.season import context_season

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_PATH = ROOT / "data" / "projections" / "current.json"
METADATA_PATH = ROOT / "data" / "projections" / "metadata.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_availability.json"
CACHE_PATH = ROOT / "data" / "mlb" / "mlb_availability_transactions_cache.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_availability"

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "ValuCast MLB availability builder"
CONTRACT_NAME = "ValuCast MLB Availability Contract"
CONTRACT_VERSION = "0.2.0"
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1
HOLD_MAX_CONSECUTIVE_FAILURES = 5
HOLD_MAX_FAILURE_SHARE = 0.10
HOLD_MIN_FAILURES_FOR_SHARE_STOP = 5
HOLD_MIN_CALLS_FOR_SEASON_STOP = 3
HOLD_LOOKUP_BUDGET_SECONDS = 300
HOLD_LOOKUP_TIMEOUT_SECONDS = 15

ACTIVE_STATUSES = {"injured", "rehab"}


class OffseasonHoldLookupError(RuntimeError):
    pass


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _parse_date(value: Any) -> date | None:
    text = _date_part(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _season_from_generated_at(value: str | None) -> int:
    date_part = _date_part(value)
    if date_part:
        try:
            return context_season(int(date_part[:4]))
        except ValueError:
            pass
    return context_season()


def _season_start(season: int) -> str:
    return date(season, DEFAULT_SEASON_START_MONTH, DEFAULT_SEASON_START_DAY).isoformat()


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mlbam_id_from_projection(row: dict) -> str | None:
    metadata = row.get("metadata") or {}
    mlbam_id = metadata.get("mlbam_id")
    if mlbam_id in (None, ""):
        return None
    return str(mlbam_id)


def _tracked_mlbam_ids(projections: Iterable[dict]) -> set[str]:
    return {
        mlbam_id
        for row in projections
        if (mlbam_id := _mlbam_id_from_projection(row))
    }


def _fetch_transactions(start_date: str, end_date: str) -> list[dict]:
    query = urlencode(
        {
            "sportId": 1,
            "startDate": start_date,
            "endDate": end_date,
        }
    )
    request = Request(
        f"{MLB_API_BASE}/transactions?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))
    transactions = payload.get("transactions") or []
    return transactions if isinstance(transactions, list) else []


def _fetch_schedule(season: int) -> list[dict]:
    query = urlencode({"sportId": 1, "gameType": "R", "season": season})
    request = Request(f"{MLB_API_BASE}/schedule?{query}", headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=HOLD_LOOKUP_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["dates"]


def _fetch_game_logs(mlbam_id: str, season: int, game_types: str) -> list[dict]:
    query = urlencode({
        "stats": "gameLog", "group": "hitting,pitching", "season": season, "gameType": game_types,
    })
    request = Request(
        f"{MLB_API_BASE}/people/{mlbam_id}/stats?{query}", headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=HOLD_LOOKUP_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return [split for group in payload["stats"] for split in group["splits"]]


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


CACHE_QUERIES_KEEP = 3


def _prune_stale_queries(queries: dict, keep: int = CACHE_QUERIES_KEEP) -> None:
    """The season-start is fixed and end_date advances daily, so each day's
    entry is a near-duplicate of the last (same start_date, one more day of
    transactions) and nothing ever reads an older end_date's entry again --
    unpruned, this grew one ever-larger entry per day forever (23 entries,
    100MB+, enough to blow the daily refresh's GitHub push limit for 3 straight
    runs on 2026-07-07). Mutates in place; keeps the `keep` most-recent."""
    if len(queries) <= keep:
        return
    ordered = sorted(
        queries.keys(),
        key=lambda k: queries[k].get("fetched_at") or queries[k].get("end_date") or "",
    )
    for stale_key in ordered[:-keep]:
        queries.pop(stale_key, None)


def _transactions_from_cache_or_fetch(
    *,
    start_date: str,
    end_date: str,
    cache: dict,
    fetcher: Callable[[str, str], list[dict]] | None = None,
    refresh: bool = True,
    fetched_at: str | None = None,
) -> tuple[list[dict], bool]:
    key = f"{start_date}:{end_date}:sportId=1"
    queries = cache.setdefault("queries", {})
    if not refresh and key in queries:
        return list(queries[key].get("transactions") or []), False

    fetch = fetcher or _fetch_transactions
    transactions = fetch(start_date, end_date)
    queries[key] = {
        "fetched_at": fetched_at or datetime.now(timezone.utc).isoformat(),
        "start_date": start_date,
        "end_date": end_date,
        "transactions": transactions,
    }
    _prune_stale_queries(queries)
    return transactions, True


def _transaction_mlbam_id(row: dict) -> str | None:
    person = row.get("person") or {}
    mlbam_id = person.get("id")
    if mlbam_id in (None, ""):
        return None
    return str(mlbam_id)


def _event_date(row: dict) -> str | None:
    return _date_part(row.get("effectiveDate") or row.get("date") or row.get("resolutionDate"))


def _event_sort_key(row: dict) -> tuple[str, str, int]:
    effective = _event_date(row) or ""
    recorded = _date_part(row.get("date")) or ""
    return effective, recorded, _clean_int(row.get("id")) or 0


def _list_type(description: str) -> str | None:
    text = description.lower()
    for label in ("60-day", "15-day", "10-day", "7-day"):
        if label in text and "injured list" in text:
            return f"{label} injured list"
    if "injured list" in text:
        return "injured list"
    return None


def _event_kind(row: dict) -> str | None:
    description = str(row.get("description") or "")
    text = description.lower()
    if "activated" in text and "injured list" in text:
        return "available"
    if "reinstated" in text and "injured list" in text:
        return "available"
    if "placed" in text and "injured list" in text:
        return "injured"
    if "transferred" in text and "injured list" in text:
        return "injured"
    if "rehab assignment" in text or "rehabilitation assignment" in text:
        return "rehab"
    return None


def _transaction_profile(row: dict) -> dict | None:
    mlbam_id = _transaction_mlbam_id(row)
    status = _event_kind(row)
    if not mlbam_id or not status:
        return None
    person = row.get("person") or {}
    to_team = row.get("toTeam") or {}
    description = str(row.get("description") or "")
    event_date = _event_date(row)
    list_type = _list_type(description)
    return {
        "mlbam_id": _clean_int(mlbam_id) or mlbam_id,
        "name": person.get("fullName"),
        "team": to_team.get("abbreviation") or to_team.get("name"),
        "status": status,
        "active_injury_risk": status in ACTIVE_STATUSES,
        "list_type": list_type,
        "transaction_id": _clean_int(row.get("id")) or row.get("id"),
        "transaction_date": _date_part(row.get("date")),
        "effective_date": event_date,
        "type_code": row.get("typeCode"),
        "type_description": row.get("typeDesc"),
        "description": description,
        "source": "official_mlb_statsapi_transactions",
    }


def _latest_profiles(
    transactions: Iterable[dict],
    tracked_ids: set[str],
    generated_at: str,
) -> list[dict]:
    generated_date = _parse_date(generated_at)
    by_id: dict[str, dict] = {}
    for row in transactions:
        mlbam_id = _transaction_mlbam_id(row)
        if not mlbam_id or (tracked_ids and mlbam_id not in tracked_ids):
            continue
        event_date = _parse_date(_event_date(row))
        if generated_date is not None and event_date is not None and event_date > generated_date:
            continue
        profile = _transaction_profile(row)
        if not profile:
            continue
        previous = by_id.get(mlbam_id)
        if previous is None or _event_sort_key(row) >= previous["_sort_key"]:
            profile["_sort_key"] = _event_sort_key(row)
            by_id[mlbam_id] = profile

    profiles = []
    for profile in by_id.values():
        profile.pop("_sort_key", None)
        profiles.append(profile)
    profiles.sort(
        key=lambda row: (
            row.get("status") not in ACTIVE_STATUSES,
            str(row.get("name") or ""),
            str(row.get("mlbam_id") or ""),
        )
    )
    return profiles


def availability_lookup(payload: dict | None) -> dict[str, dict]:
    lookup = {}
    for row in (payload or {}).get("profiles") or []:
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            continue
        lookup[str(mlbam_id)] = row
    return lookup


def _offseason_hold_failure_message(lookups_by_season: dict[str, dict[str, int]]) -> str | None:
    for season, counts in sorted(lookups_by_season.items()):
        attempted, failed = counts["attempted"], counts["failed"]
        if (
            failed >= HOLD_MIN_FAILURES_FOR_SHARE_STOP and failed / attempted >= HOLD_MAX_FAILURE_SHARE
        ) or (attempted >= HOLD_MIN_CALLS_FOR_SEASON_STOP and failed == attempted):
            return f"Offseason hold game-log failures: season {season}, {failed} of {attempted}"
    attempted = sum(counts["attempted"] for counts in lookups_by_season.values())
    failed = sum(counts["failed"] for counts in lookups_by_season.values())
    if failed >= HOLD_MIN_FAILURES_FOR_SHARE_STOP and failed / attempted >= HOLD_MAX_FAILURE_SHARE:
        return f"Offseason hold game-log failures: all seasons, {failed} of {attempted}"
    return None


def _apply_offseason_hold(
    profiles: list[dict],
    transactions: list[dict],
    tracked_ids: set[str],
    season: int,
    as_of: str,
    schedule_fetcher: Callable[[int], list[dict]] | None,
    game_log_fetcher: Callable[[str, int, str], list[dict]] | None,
) -> dict:
    started = time.monotonic()
    summary = {
        "active": False, "season_end": None, "held_count": 0, "stale_count": 0,
        "cleared_by_appearance": 0, "lookup_failure_count": 0,
        "played_date_count": 0, "release_state": "inactive",
        "lookups_by_season": {},
    }
    errors = []
    consecutive_failures = 0
    fetch_schedule = schedule_fetcher or _fetch_schedule

    def check_budget() -> None:
        if time.monotonic() - started > HOLD_LOOKUP_BUDGET_SECONDS:
            raise OffseasonHoldLookupError("Offseason hold lookup budget exceeded")

    def schedule_dates(year: int) -> tuple[set[str], set[str]]:
        check_budget()
        try:
            days = fetch_schedule(year)
        except Exception as exc:  # noqa: BLE001
            raise OffseasonHoldLookupError(f"schedule {year}: {exc}") from exc
        scheduled, played = set(), set()
        for day in days:
            day_date = _parse_date(day.get("date"))
            games = day.get("games") or []
            if day_date is None or not games:
                continue
            day_text = day_date.isoformat()
            scheduled.add(day_text)
            if day_text <= as_of and any(
                (game.get("status") or {}).get("detailedState")
                in {"Final", "Game Over", "Completed Early"} for game in games
            ):
                played.add(day_text)
        return scheduled, played

    scheduled, played = schedule_dates(season)
    summary["season_end"] = max(played) if played else None
    if not scheduled:
        raise OffseasonHoldLookupError(f"schedule {season}: No regular-season dates found")
    if as_of <= max(scheduled):
        return {"offseason_hold": summary}
    if not played:
        raise OffseasonHoldLookupError(f"schedule {season}: No played regular-season games found")
    season_end = max(played)
    summary["active"] = True
    summary["release_state"] = "pending"
    if int(as_of[:4]) > season:
        _, next_played = schedule_dates(season + 1)
        played_dates = sorted(day for day in next_played if season_end < day <= as_of)
        summary["played_date_count"] = len(played_dates)
        if len(played_dates) >= 14:
            summary.update(active=False, release_state="released", release_date=played_dates[13])

    at_season_end = availability_lookup({
        "profiles": _latest_profiles(transactions, tracked_ids, season_end),
    })
    stints_at_season_end = availability_lookup({
        "profiles": _latest_profiles(
            [row for row in transactions if _event_kind(row) in {"injured", "available"}],
            tracked_ids, season_end,
        ),
    })
    placements = availability_lookup({
        "profiles": _latest_profiles(
            [row for row in transactions if _event_kind(row) == "injured"], tracked_ids, as_of,
        ),
    })
    fetch_logs = game_log_fetcher or _fetch_game_logs
    for profile in profiles:
        mlbam_id = str(profile["mlbam_id"])
        latest_date = profile.get("effective_date") or ""
        stale = profile["status"] in ACTIVE_STATUSES and "" < latest_date <= season_end
        prior = at_season_end.get(mlbam_id) or {}
        stint = stints_at_season_end.get(mlbam_id) or {}
        placement = placements.get(mlbam_id) or {}
        activated_hold = (
            profile["status"] == "available" and latest_date > season_end
            and prior.get("status") in ACTIVE_STATUSES
            and stint.get("status") == "injured"
            and "60-day" in str(stint.get("list_type") or "")
            and re.search(r"\b(?:RHP|LHP)\b", str(stint.get("description") or ""))
            and "" < (placement.get("effective_date") or "") <= season_end
        )
        if not stale and not activated_hold:
            continue
        if summary["release_state"] == "released":
            profile.update(status="available", active_injury_risk=False,
                           hold_cleared="regular_season_release", hold_cleared_date=summary["release_date"])
            continue
        appearance = None
        window_start = latest_date if stale else season_end
        for year, types in ((season, "R,F,D,L,W"), (season + 1, "S,R")):
            if year > season and int(as_of[:4]) <= season:
                continue
            check_budget()
            counts = summary["lookups_by_season"].setdefault(str(year), {"attempted": 0, "failed": 0})
            counts["attempted"] += 1
            try:
                games = fetch_logs(mlbam_id, year, types)
            except Exception as exc:  # noqa: BLE001
                counts["failed"] += 1
                errors.append(f"game_log {mlbam_id}: {exc}")
                summary["lookup_failure_count"] += 1
                consecutive_failures += 1
                if consecutive_failures >= HOLD_MAX_CONSECUTIVE_FAILURES:
                    raise OffseasonHoldLookupError(
                        f"{consecutive_failures} consecutive offseason hold game-log failures"
                    ) from exc
                break
            consecutive_failures = 0
            dates = [
                day.isoformat() for split in games
                if (day := _parse_date(split.get("date"))) is not None
                and window_start < day.isoformat() <= as_of
            ]
            if dates:
                appearance = min(dates)
                break
        if appearance:
            profile.update(status="available", active_injury_risk=False,
                           hold_cleared="game_appearance", hold_cleared_date=appearance)
            summary["cleared_by_appearance"] += 1
            continue
        if activated_hold:
            profile.update(prior)
            profile.update(
                offseason_hold=True, held_since=latest_date,
                hold_note=(
                    "End-of-season injury status held. MLB's offseason roster activation "
                    f"on {latest_date} is not treated as a return. "
                    "This clears when the player appears in a game."
                ),
            )
            summary["held_count"] += 1
        else:
            profile["stale_status"] = True
            summary["stale_count"] += 1
    failure_message = _offseason_hold_failure_message(summary["lookups_by_season"])
    if failure_message:
        raise OffseasonHoldLookupError(failure_message)
    profiles.sort(key=lambda row: (
        row.get("status") not in ACTIVE_STATUSES, str(row.get("name") or ""), str(row.get("mlbam_id") or ""),
    ))
    result = {"offseason_hold": summary}
    if errors:
        result["offseason_hold_error"] = errors
    return result


def _validation(profiles: list[dict], tracked_ids: set[str], transactions: list[dict]) -> dict:
    ids = [str(row.get("mlbam_id")) for row in profiles if row.get("mlbam_id") not in (None, "")]
    duplicate_count = len(ids) - len(set(ids))
    risk_profiles = [row for row in profiles if row.get("status") in ACTIVE_STATUSES]
    blockers = []
    if duplicate_count:
        blockers.append("Duplicate MLBAM profiles exist in the MLB availability artifact.")
    return {
        "ready_for_mlb_dynasty_layer": not blockers,
        "tracked_mlbam_count": len(tracked_ids),
        "transaction_count": len(transactions),
        "profile_count": len(profiles),
        "risk_profile_count": len(risk_profiles),
        "injured_count": sum(1 for row in risk_profiles if row.get("status") == "injured"),
        "rehab_count": sum(1 for row in risk_profiles if row.get("status") == "rehab"),
        "available_after_il_count": sum(1 for row in profiles if row.get("status") == "available"),
        "duplicate_identity_count": duplicate_count,
        "blockers": blockers,
    }


def build_mlb_availability(
    projections: list[dict],
    *,
    generated_at: str,
    transactions: list[dict],
    season: int | None = None,
    schedule_fetcher: Callable[[int], list[dict]] | None = None,
    game_log_fetcher: Callable[[str, int, str], list[dict]] | None = None,
) -> dict:
    season = season or _season_from_generated_at(generated_at)
    start_date = _season_start(season)
    end_date = _date_part(generated_at) or datetime.now(timezone.utc).date().isoformat()
    tracked_ids = _tracked_mlbam_ids(projections)
    profiles = _latest_profiles(transactions, tracked_ids, generated_at)
    hold_validation = _apply_offseason_hold(
        profiles, transactions, tracked_ids, season, end_date, schedule_fetcher, game_log_fetcher,
    )
    return {
        "artifact": "valucast_mlb_availability",
        "contract_name": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "season": season,
        "query": {
            "source": "official_mlb_statsapi_transactions",
            "sport_id": 1,
            "start_date": start_date,
            "end_date": end_date,
        },
        "source_policy": {
            "kind": "official_mlb_transaction_availability",
            "identity_key": "MLBAM ID",
            "official_mlb_transactions_used": True,
            "name_matching_used": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
            "public_prospect_ranks_used": False,
        },
        "contract": {
            "identity_key": "MLBAM ID",
            "inputs": ["official MLB Stats API transactions, schedule and gameLog endpoints"],
            "active_statuses": sorted(ACTIVE_STATUSES),
            "status_rules": {
                "injured": "Latest IL placement/transfer, or season-end status retained by offseason hold.",
                "rehab": "Latest rehab assignment, or season-end rehab retained by offseason hold.",
                "available": "Activation/reinstatement, corroborating appearance, or 14 played-date hold release.",
            },
        },
        "validation": {**_validation(profiles, tracked_ids, transactions), **hold_validation},
        "profiles": profiles,
    }


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _check_transaction_count_ratio_guard(payload: dict, artifact_path: Path) -> None:
    """Fail LOUD on a day-over-day transaction count collapse. Transactions
    accumulate monotonically during a season, so a >10% drop in the same
    season always means a broken feed, never a legitimate reading -- and the
    same-season check avoids false fires at season rollover."""
    if os.environ.get("VALUCAST_SKIP_AVAILABILITY_RATIO_GUARD") == "1":
        return
    if not artifact_path.exists():
        return
    try:
        prior_payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return
    if prior_payload.get("season") != payload.get("season"):
        return
    prior_count = (prior_payload.get("validation") or {}).get("transaction_count", 0)
    if not prior_count or prior_count <= 0:
        return
    new_count = (payload.get("validation") or {}).get("transaction_count", 0)
    if new_count < 0.9 * prior_count:
        raise RuntimeError(
            f"availability sanity: new transaction_count {new_count} is more than "
            f"10% below prior transaction_count {prior_count} for the same season "
            "-- refusing to overwrite with a degraded transactions feed "
            "(set VALUCAST_SKIP_AVAILABILITY_RATIO_GUARD=1 to override)"
        )


# Per-player fields the archive keeps so historical IL membership stays exactly
# replayable (gate-extension review 2026-07-13: the old counts-only archive made
# every historical replay a pseudo-profile). Risk profiles only -- healthy
# players carry no availability signal, so archiving them adds size, not replay.
_ARCHIVE_PROFILE_FIELDS = (
    "mlbam_id",
    "status",
    "active_injury_risk",
    "list_type",
    "effective_date",
    "description",
    "offseason_hold",
    "held_since",
    "stale_status",
)
_ARCHIVE_RISK_STATUSES = {"injured", "rehab"}


def _archive_profiles(payload: dict) -> list[dict]:
    profiles = []
    for profile in payload.get("profiles") or []:
        if str(profile.get("status") or "") not in _ARCHIVE_RISK_STATUSES:
            continue
        profiles.append({field: profile.get(field) for field in _ARCHIVE_PROFILE_FIELDS})
    profiles.sort(key=lambda row: str(row.get("mlbam_id") or ""))
    return profiles


def archive_mlb_availability(payload: dict, archive_dir: Path = ARCHIVE_DIR) -> tuple[Path, bool]:
    generated_date = _date_part(payload.get("generated_at")) or datetime.now(
        timezone.utc
    ).date().isoformat()
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{generated_date}.json"
    archive_payload = {
        "generated_at": payload.get("generated_at"),
        "contract_version": payload.get("contract_version"),
        "query": payload.get("query") or {},
        "validation": payload.get("validation") or {},
        "risk_profiles": _archive_profiles(payload),
    }
    text = json.dumps(archive_payload, indent=2, sort_keys=True)
    changed = not archive_path.exists() or archive_path.read_text(encoding="utf-8") != text
    if changed:
        archive_path.write_text(text, encoding="utf-8")
    return archive_path, changed


def run_mlb_availability(
    projection_path: Path = PROJECTION_PATH,
    metadata_path: Path = METADATA_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    cache_path: Path = CACHE_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    *,
    generated_at: str | None = None,
    season: int | None = None,
    fetcher: Callable[[str, str], list[dict]] | None = None,
    schedule_fetcher: Callable[[int], list[dict]] | None = None,
    game_log_fetcher: Callable[[str, int, str], list[dict]] | None = None,
    refresh: bool = True,
) -> dict:
    projections = json.loads(projection_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    generated_at = generated_at or metadata.get("as_of") or datetime.now(timezone.utc).isoformat()
    season = season or _season_from_generated_at(generated_at)
    start_date = _season_start(season)
    end_date = _date_part(generated_at) or datetime.now(timezone.utc).date().isoformat()
    cache = _load_cache(cache_path)
    transactions, fetched = _transactions_from_cache_or_fetch(
        start_date=start_date,
        end_date=end_date,
        cache=cache,
        fetcher=fetcher,
        refresh=refresh,
        fetched_at=generated_at,
    )
    _save_cache(cache, cache_path)
    payload = build_mlb_availability(
        projections,
        generated_at=generated_at,
        transactions=transactions,
        season=season,
        schedule_fetcher=schedule_fetcher,
        game_log_fetcher=game_log_fetcher,
    )
    _check_transaction_count_ratio_guard(payload, artifact_path)
    _write_json(payload, artifact_path)
    archive_path, archive_changed = archive_mlb_availability(payload, archive_dir)
    validation = payload["validation"]
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "profile_count": validation["profile_count"],
        "risk_profile_count": validation["risk_profile_count"],
        "ready_for_mlb_dynasty_layer": validation["ready_for_mlb_dynasty_layer"],
        "transaction_count": validation["transaction_count"],
        "offseason_hold": validation["offseason_hold"],
        "fetched": fetched,
    }
