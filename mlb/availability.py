"""ValuCast-owned MLB availability layer.

This layer derives MLB injury/rehab availability from official MLBAM-keyed
transaction records. It intentionally avoids player-name joins, DD values,
public rankings, market signals, and projection-derived health guesses.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_PATH = ROOT / "data" / "projections" / "current.json"
METADATA_PATH = ROOT / "data" / "projections" / "metadata.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_availability.json"
CACHE_PATH = ROOT / "data" / "mlb" / "mlb_availability_transactions_cache.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_availability"

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "ValuCast MLB availability builder"
CONTRACT_NAME = "ValuCast MLB Availability Contract"
CONTRACT_VERSION = "0.1.0"
DEFAULT_SEASON_START_MONTH = 3
DEFAULT_SEASON_START_DAY = 1

ACTIVE_STATUSES = {"injured", "rehab"}


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
            return int(date_part[:4])
        except ValueError:
            pass
    return datetime.now(timezone.utc).year


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
) -> dict:
    season = season or _season_from_generated_at(generated_at)
    start_date = _season_start(season)
    end_date = _date_part(generated_at) or datetime.now(timezone.utc).date().isoformat()
    tracked_ids = _tracked_mlbam_ids(projections)
    profiles = _latest_profiles(transactions, tracked_ids, generated_at)
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
            "inputs": ["official MLB Stats API transactions endpoint"],
            "active_statuses": sorted(ACTIVE_STATUSES),
            "status_rules": {
                "injured": "Latest MLBAM-keyed transaction placed/transferred player on an injured list.",
                "rehab": "Latest MLBAM-keyed transaction sent player on a rehab assignment.",
                "available": "Latest MLBAM-keyed injured-list transaction activated/reinstated player.",
            },
        },
        "validation": _validation(profiles, tracked_ids, transactions),
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
        "fetched": fetched,
    }
