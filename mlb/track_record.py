"""ValuCast-owned MLB track-record contract.

The contract turns factual MLB stat history into a stable artifact that the
dynasty layer can consume without reading raw API responses or external ranks.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from scraper.mlb_actuals import normalize_ip

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_PATH = ROOT / "data" / "projections" / "current.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_mlb_track_record.json"
CACHE_PATH = ROOT / "data" / "mlb" / "mlb_track_record_cache.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_track_record"

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"
USER_AGENT = "ValuCast track-record builder"
CONTRACT_NAME = "ValuCast MLB Track Record Contract"
CONTRACT_VERSION = "0.1.0"
BULK_HISTORY_CHUNK_SIZE = 75

HITTER_ROLE = "hitter"
PITCHER_ROLE = "pitcher"
PITCHER_POOLS = {"pitcher", "starter", "reliever"}
HISTORY_STATS = "yearByYear,career"
HISTORY_GROUPS = "hitting,pitching"
MIN_HITTER_PA = 100.0
MIN_SP_IP = 40.0
MIN_RP_IP = 20.0
HITTER_TRACK_RECORD_FLOOR_CAP = 62.0
PITCHER_TRACK_RECORD_FLOOR_CAP = 60.0


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


def _clean_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _clean_int(value: Any) -> int:
    numeric = _clean_float(value)
    return int(numeric or 0)


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def _role_from_projection(row: dict) -> str:
    pool = str(row.get("pool") or "").lower()
    return PITCHER_ROLE if pool in PITCHER_POOLS else HITTER_ROLE


def _projected_volume(row: dict, *keys: str) -> float:
    stats = row.get("stats") or {}
    for key in keys:
        value = _clean_float(stats.get(key))
        if value:
            return value
    return 0.0


def _is_mlb_dynasty_eligible_projection(row: dict) -> bool:
    pool = str(row.get("pool") or "").lower()
    if pool == HITTER_ROLE:
        return _projected_volume(row, "PA", "AB") >= MIN_HITTER_PA
    if pool == "starter":
        return _projected_volume(row, "IP") >= MIN_SP_IP
    if pool in {"pitcher", "reliever"}:
        return _projected_volume(row, "IP") >= MIN_RP_IP
    return False


def _mlbam_id_from_projection(row: dict) -> str | None:
    metadata = row.get("metadata") or {}
    mlbam_id = metadata.get("mlbam_id")
    if mlbam_id in (None, ""):
        return None
    return str(mlbam_id)


def _identity_key(mlbam_id: Any, role: str) -> tuple[str, str] | None:
    if mlbam_id in (None, "") or role not in {HITTER_ROLE, PITCHER_ROLE}:
        return None
    return str(mlbam_id), role


def _current_stats_by_key(projections: Iterable[dict]) -> dict[tuple[str, str], dict]:
    current: dict[tuple[str, str], dict] = {}
    for row in projections:
        mlbam_id = _mlbam_id_from_projection(row)
        role = _role_from_projection(row)
        key = _identity_key(mlbam_id, role)
        if key is None:
            continue
        stats_actual = ((row.get("metadata") or {}).get("stats_actual") or {})
        if not stats_actual:
            continue
        existing = current.get(key)
        if not existing or _track_volume(stats_actual, role) > _track_volume(existing, role):
            current[key] = dict(stats_actual)
    return current


def _tracked_keys(projections: Iterable[dict]) -> dict[str, set[str]]:
    keys: dict[str, set[str]] = {}
    for row in projections:
        mlbam_id = _mlbam_id_from_projection(row)
        if mlbam_id is None:
            continue
        keys.setdefault(mlbam_id, set()).add(_role_from_projection(row))
    return keys


def _fetch_history(mlbam_id: str) -> dict:
    url = (
        f"{MLB_API_BASE}/people/{quote(str(mlbam_id))}/stats"
        f"?stats={HISTORY_STATS}&group={HISTORY_GROUPS}&sportId=1"
    )
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_histories_bulk(mlbam_ids: Iterable[str]) -> dict[str, dict]:
    ids = sorted({str(value) for value in mlbam_ids if value not in (None, "")})
    if not ids:
        return {}
    query = urlencode(
        {
            "personIds": ",".join(ids),
            "hydrate": "stats(group=[hitting,pitching],type=[yearByYear,career])",
        }
    )
    request = Request(
        f"{MLB_API_BASE}/people?{query}",
        headers={"User-Agent": USER_AGENT},
    )
    with urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))

    histories: dict[str, dict] = {}
    for person in payload.get("people") or []:
        mlbam_id = person.get("id")
        if mlbam_id in (None, ""):
            continue
        histories[str(mlbam_id)] = {
            "stats": person.get("stats") or [],
        }
    return histories


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _load_cache(path: Path) -> dict:
    if not path.exists():
        return {"schema_version": "1.0", "players": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema_version": "1.0", "players": {}}
    if not isinstance(payload, dict):
        return {"schema_version": "1.0", "players": {}}
    payload.setdefault("schema_version", "1.0")
    payload.setdefault("players", {})
    return payload


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def _save_cache(cache: dict, path: Path) -> Path:
    return _write_json(cache, path)


def _prune_cache(cache: dict, mlbam_ids: Iterable[str]) -> int:
    players = cache.setdefault("players", {})
    keep = {str(value) for value in mlbam_ids if value not in (None, "")}
    pruned = 0
    for mlbam_id in list(players):
        if mlbam_id not in keep:
            del players[mlbam_id]
            pruned += 1
    return pruned


def _history_payloads(
    mlbam_ids: Iterable[str],
    cache: dict,
    *,
    fetcher: Callable[[str], dict] | None = None,
    bulk_fetcher: Callable[[Iterable[str]], dict[str, dict]] | None = None,
    refresh_missing: bool = True,
    fetched_at: str | None = None,
    cache_path: Path | None = None,
    fetch_limit: int | None = None,
) -> tuple[dict[str, dict], list[str], int]:
    players = cache.setdefault("players", {})
    payloads: dict[str, dict] = {}
    missing: list[str] = []
    fetched_count = 0
    fetched_at = fetched_at or datetime.now(timezone.utc).isoformat()
    pending_fetch: list[str] = []

    for mlbam_id in sorted({str(value) for value in mlbam_ids if value not in (None, "")}):
        cached = players.get(mlbam_id)
        if cached and isinstance(cached.get("raw"), dict):
            payloads[mlbam_id] = cached["raw"]
            continue
        if not refresh_missing:
            missing.append(mlbam_id)
            continue
        if fetch_limit is not None and len(pending_fetch) >= fetch_limit:
            missing.append(mlbam_id)
            continue
        pending_fetch.append(mlbam_id)

    if fetcher is not None:
        for mlbam_id in pending_fetch:
            raw = fetcher(mlbam_id)
            players[mlbam_id] = {
                "fetched_at": fetched_at,
                "raw": raw,
            }
            payloads[mlbam_id] = raw
            fetched_count += 1
            cache["updated_at"] = fetched_at
            if cache_path is not None:
                _save_cache(cache, cache_path)
        cache["updated_at"] = fetched_at
        return payloads, missing, fetched_count

    bulk_fetcher = bulk_fetcher or _fetch_histories_bulk
    for chunk in _chunks(pending_fetch, BULK_HISTORY_CHUNK_SIZE):
        raw_by_id = bulk_fetcher(chunk)
        for mlbam_id in chunk:
            raw = raw_by_id.get(mlbam_id)
            if raw is None:
                try:
                    raw = _fetch_history(mlbam_id)
                except Exception:  # noqa: BLE001
                    missing.append(mlbam_id)
                    continue
            players[mlbam_id] = {
                "fetched_at": fetched_at,
                "raw": raw,
            }
            payloads[mlbam_id] = raw
            fetched_count += 1
        cache["updated_at"] = fetched_at
        if cache_path is not None:
            _save_cache(cache, cache_path)

    cache["updated_at"] = fetched_at
    return payloads, missing, fetched_count


def _stats_bucket(raw: dict, group_name: str, type_name: str) -> list[dict]:
    for bucket in raw.get("stats") or []:
        if (bucket.get("group") or {}).get("displayName") != group_name:
            continue
        if (bucket.get("type") or {}).get("displayName") != type_name:
            continue
        return list(bucket.get("splits") or [])
    return []


def _season(split: dict) -> int | None:
    try:
        return int(split.get("season"))
    except (TypeError, ValueError):
        return None


def _hitter_totals_from_stats(stats: dict) -> dict[str, float]:
    hits = _clean_int(stats.get("hits"))
    doubles = _clean_int(stats.get("doubles"))
    triples = _clean_int(stats.get("triples"))
    homers = _clean_int(stats.get("homeRuns"))
    singles = max(0, hits - doubles - triples - homers)
    return {
        "G": _clean_int(stats.get("gamesPlayed")),
        "PA": _clean_int(stats.get("plateAppearances")),
        "AB": _clean_int(stats.get("atBats")),
        "H": hits,
        "HR": homers,
        "R": _clean_int(stats.get("runs")),
        "RBI": _clean_int(stats.get("rbi")),
        "SB": _clean_int(stats.get("stolenBases")),
        "CS": _clean_int(stats.get("caughtStealing")),
        "BB": _clean_int(stats.get("baseOnBalls")),
        "SO": _clean_int(stats.get("strikeOuts")),
        "HBP": _clean_int(stats.get("hitByPitch")),
        "SF": _clean_int(stats.get("sacFlies")),
        "1B": singles,
        "2B": doubles,
        "3B": triples,
    }


def _pitcher_totals_from_stats(stats: dict) -> dict[str, float]:
    ip = normalize_ip(_clean_float(stats.get("inningsPitched")) or 0.0)
    return {
        "G": _clean_int(stats.get("gamesPitched") or stats.get("gamesPlayed")),
        "GS": _clean_int(stats.get("gamesStarted")),
        "IP": round(ip, 4),
        "ER": _clean_int(stats.get("earnedRuns")),
        "BB": _clean_int(stats.get("baseOnBalls")),
        "H_ALLOWED": _clean_int(stats.get("hits")),
        "K": _clean_int(stats.get("strikeOuts")),
        "W": _clean_int(stats.get("wins")),
        "L": _clean_int(stats.get("losses")),
        "SV": _clean_int(stats.get("saves")),
        "HLD": _clean_int(stats.get("holds")),
    }


def _add_totals(rows: Iterable[dict[str, float]], role: str) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        for key, value in row.items():
            totals[key] = totals.get(key, 0.0) + (float(value) if value is not None else 0.0)
    if role == HITTER_ROLE:
        _finalize_hitter_rates(totals)
    else:
        _finalize_pitcher_rates(totals)
    return {key: round(value, 4) if isinstance(value, float) else value for key, value in totals.items()}


def _finalize_hitter_rates(totals: dict[str, float]) -> None:
    ab = totals.get("AB", 0.0)
    hits = totals.get("H", 0.0)
    walks = totals.get("BB", 0.0)
    hbp = totals.get("HBP", 0.0)
    sf = totals.get("SF", 0.0)
    total_bases = (
        totals.get("1B", 0.0)
        + 2 * totals.get("2B", 0.0)
        + 3 * totals.get("3B", 0.0)
        + 4 * totals.get("HR", 0.0)
    )
    obp_denominator = ab + walks + hbp + sf
    totals["AVG"] = round(hits / ab, 4) if ab > 0 else 0.0
    totals["OBP"] = round((hits + walks + hbp) / obp_denominator, 4) if obp_denominator > 0 else 0.0
    totals["SLG"] = round(total_bases / ab, 4) if ab > 0 else 0.0
    totals["OPS"] = round(totals["OBP"] + totals["SLG"], 4)
    totals["TB"] = round(total_bases, 4)
    totals["NSB"] = round(totals.get("SB", 0.0) - totals.get("CS", 0.0), 4)


def _finalize_pitcher_rates(totals: dict[str, float]) -> None:
    ip = totals.get("IP", 0.0)
    er = totals.get("ER", 0.0)
    walks = totals.get("BB", 0.0)
    hits = totals.get("H_ALLOWED", 0.0)
    strikeouts = totals.get("K", 0.0)
    totals["ERA"] = round(9 * er / ip, 4) if ip > 0 else 0.0
    totals["WHIP"] = round((walks + hits) / ip, 4) if ip > 0 else 0.0
    totals["K_9"] = round(9 * strikeouts / ip, 4) if ip > 0 else 0.0
    totals["BB_9"] = round(9 * walks / ip, 4) if ip > 0 else 0.0
    totals["K_BB"] = round(strikeouts / walks, 4) if walks > 0 else 0.0
    totals["SV_HLD"] = round(totals.get("SV", 0.0) + totals.get("HLD", 0.0), 4)


def _season_rows(raw: dict, role: str) -> list[tuple[int, dict[str, float]]]:
    group = "hitting" if role == HITTER_ROLE else "pitching"
    rows = []
    for split in _stats_bucket(raw, group, "yearByYear"):
        season = _season(split)
        if season is None:
            continue
        stats = split.get("stat") or {}
        totals = (
            _hitter_totals_from_stats(stats)
            if role == HITTER_ROLE
            else _pitcher_totals_from_stats(stats)
        )
        if _track_volume(totals, role) <= 0:
            continue
        rows.append((season, totals))
    return rows


def _actual_totals(actual: dict | None, role: str) -> dict[str, float]:
    if not actual:
        return {}
    if role == HITTER_ROLE:
        totals = {
            key: float(actual.get(key, 0) or 0)
            for key in ("G", "PA", "AB", "H", "HR", "R", "RBI", "SB", "CS", "BB", "SO", "HBP", "SF", "1B", "2B", "3B")
        }
        _finalize_hitter_rates(totals)
        return totals
    totals = {
        key: float(actual.get(key, 0) or 0)
        for key in ("G", "GS", "IP", "ER", "BB", "H_ALLOWED", "K", "W", "L", "SV", "HLD")
    }
    _finalize_pitcher_rates(totals)
    return totals


def _track_volume(totals: dict[str, Any], role: str) -> float:
    if role == HITTER_ROLE:
        return _clean_float(totals.get("PA")) or _clean_float(totals.get("AB")) or 0.0
    return _clean_float(totals.get("IP")) or 0.0


def _volume_score(volume: float, target: float) -> float:
    if volume <= 0:
        return 0.0
    return round(100.0 * volume / (volume + target), 2)


def _hitter_quality_score(totals: dict[str, Any]) -> float:
    pa = _track_volume(totals, HITTER_ROLE)
    if pa <= 0:
        return 0.0
    ops = _clean_float(totals.get("OPS")) or 0.0
    obp = _clean_float(totals.get("OBP")) or 0.0
    slg = _clean_float(totals.get("SLG")) or 0.0
    score = (
        55.0
        + (ops - 0.740) * 115.0
        + (obp - 0.320) * 45.0
        + (slg - 0.420) * 35.0
    )
    return round(max(0.0, min(100.0, score)), 2)


def _pitcher_quality_score(totals: dict[str, Any]) -> float:
    ip = _track_volume(totals, PITCHER_ROLE)
    if ip <= 0:
        return 0.0
    era = _clean_float(totals.get("ERA")) or 5.0
    whip = _clean_float(totals.get("WHIP")) or 1.45
    k9 = _clean_float(totals.get("K_9")) or 0.0
    score = (
        55.0
        + (4.20 - era) * 10.0
        + (1.28 - whip) * 45.0
        + (k9 - 8.2) * 3.0
    )
    return round(max(0.0, min(100.0, score)), 2)


def _track_record_floor_score(
    role: str,
    prior: dict[str, Any],
    recent: dict[str, Any],
) -> float:
    prior_volume = _track_volume(prior, role)
    recent_volume = _track_volume(recent, role)
    if role == HITTER_ROLE:
        prior_quality = _hitter_quality_score(prior)
        recent_quality = _hitter_quality_score(recent)
        volume_gate = _volume_score(prior_volume, 900.0)
        recent_gate = _volume_score(recent_volume, 600.0)
        raw = (
            18.0
            + 0.22 * prior_quality
            + 0.18 * recent_quality
            + 0.10 * volume_gate
            + 0.05 * recent_gate
        )
        return round(max(0.0, min(HITTER_TRACK_RECORD_FLOOR_CAP, raw)), 2)
    prior_quality = _pitcher_quality_score(prior)
    recent_quality = _pitcher_quality_score(recent)
    volume_gate = _volume_score(prior_volume, 300.0)
    recent_gate = _volume_score(recent_volume, 160.0)
    raw = (
        14.0
        + 0.20 * prior_quality
        + 0.16 * recent_quality
        + 0.09 * volume_gate
        + 0.05 * recent_gate
    )
    return round(max(0.0, min(PITCHER_TRACK_RECORD_FLOOR_CAP, raw)), 2)


def _certainty_score(role: str, prior: dict[str, Any], career: dict[str, Any]) -> float:
    prior_volume = _track_volume(prior, role)
    career_volume = _track_volume(career, role)
    if role == HITTER_ROLE:
        return round(0.68 * _volume_score(prior_volume, 900.0) + 0.32 * _volume_score(career_volume, 1200.0), 2)
    return round(0.68 * _volume_score(prior_volume, 300.0) + 0.32 * _volume_score(career_volume, 450.0), 2)


def _experience_band(role: str, prior_volume: float, career_volume: float) -> str:
    if role == HITTER_ROLE:
        if prior_volume >= 1500:
            return "established"
        if prior_volume >= 600:
            return "partial_track_record"
        if career_volume >= 250:
            return "current_year_only_or_limited"
        return "minimal_mlb_track_record"
    if prior_volume >= 450:
        return "established"
    if prior_volume >= 180:
        return "partial_track_record"
    if career_volume >= 70:
        return "current_year_only_or_limited"
    return "minimal_mlb_track_record"


def _profile_from_history(
    mlbam_id: str,
    role: str,
    raw: dict | None,
    current_actual: dict | None,
    season: int,
) -> dict | None:
    if not raw:
        return None
    rows = _season_rows(raw, role)
    prior_rows = [totals for row_season, totals in rows if row_season < season]
    recent_rows = [totals for row_season, totals in rows if season - 3 <= row_season < season]
    current = _actual_totals(current_actual, role)
    prior = _add_totals(prior_rows, role)
    recent = _add_totals(recent_rows, role)
    career_parts = list(prior_rows)
    if current:
        career_parts.append(current)
    else:
        career_parts.extend(totals for row_season, totals in rows if row_season == season)
    career = _add_totals(career_parts, role)
    if _track_volume(career, role) <= 0:
        return None

    prior_volume = _track_volume(prior, role)
    current_volume = _track_volume(current, role)
    career_volume = _track_volume(career, role)
    return {
        "mlbam_id": int(mlbam_id) if str(mlbam_id).isdigit() else mlbam_id,
        "role": role,
        "experience_band": _experience_band(role, prior_volume, career_volume),
        "track_record_certainty": _certainty_score(role, prior, career),
        "track_record_floor_score": _track_record_floor_score(role, prior, recent),
        "volume": {
            "career": _round(career_volume, 3),
            "prior_mlb": _round(prior_volume, 3),
            "current_season": _round(current_volume, 3),
            "recent_3yr_prior": _round(_track_volume(recent, role), 3),
        },
        "career": career,
        "prior_mlb": prior,
        "current_season": current,
        "recent_3yr_prior": recent,
        "source": "mlb_stats_api_year_by_year_and_current_actuals",
    }


def _validation(profiles: list[dict], tracked_keys: dict[str, set[str]], missing_history: list[str]) -> dict:
    expected_count = sum(len(roles) for roles in tracked_keys.values())
    profile_keys = {
        (str(row.get("mlbam_id")), row.get("role"))
        for row in profiles
        if row.get("mlbam_id") not in (None, "") and row.get("role")
    }
    duplicate_count = len(profiles) - len(profile_keys)
    coverage_rate = round(len(profile_keys) / expected_count, 4) if expected_count else 0.0
    blockers = []
    if duplicate_count:
        blockers.append("Duplicate MLBAM+role profiles exist in the MLB track-record artifact.")
    if coverage_rate < 0.70:
        blockers.append("MLB track-record coverage is below the dynasty-layer consumption threshold.")
    return {
        "ready_for_mlb_dynasty_layer": not blockers,
        "tracked_identity_count": expected_count,
        "profile_count": len(profiles),
        "coverage_rate": coverage_rate,
        "duplicate_identity_count": duplicate_count,
        "missing_history_count": len(missing_history),
        "missing_history_sample": missing_history[:20],
        "blockers": blockers,
    }


def build_mlb_track_record(
    projections: list[dict],
    *,
    generated_at: str,
    season: int | None = None,
    cache: dict | None = None,
    fetcher: Callable[[str], dict] | None = None,
    bulk_fetcher: Callable[[Iterable[str]], dict[str, dict]] | None = None,
    refresh_missing: bool = True,
    cache_path: Path | None = None,
    fetch_limit: int | None = None,
) -> dict:
    season = season or _season_from_generated_at(generated_at)
    eligible_projections = [
        row for row in projections if _is_mlb_dynasty_eligible_projection(row)
    ]
    tracked = _tracked_keys(eligible_projections)
    current_by_key = _current_stats_by_key(eligible_projections)
    cache = cache if cache is not None else {"schema_version": "1.0", "players": {}}
    pruned_count = _prune_cache(cache, tracked.keys())
    raw_by_id, missing_history, fetched_count = _history_payloads(
        tracked.keys(),
        cache,
        fetcher=fetcher,
        bulk_fetcher=bulk_fetcher,
        refresh_missing=refresh_missing,
        fetched_at=generated_at,
        cache_path=cache_path,
        fetch_limit=fetch_limit,
    )

    profiles = []
    for mlbam_id, roles in sorted(tracked.items()):
        raw = raw_by_id.get(mlbam_id)
        for role in sorted(roles):
            profile = _profile_from_history(
                mlbam_id,
                role,
                raw,
                current_by_key.get((mlbam_id, role)),
                season,
            )
            if profile:
                profiles.append(profile)

    profiles.sort(
        key=lambda row: (
            str(row.get("role") or ""),
            str(row.get("mlbam_id") or ""),
        )
    )
    return {
        "artifact": "valucast_mlb_track_record",
        "contract_name": CONTRACT_NAME,
        "contract_version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "season": season,
        "profiles": profiles,
        "source_policy": {
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
            "public_prospect_ranks_used": False,
        },
        "contract": {
            "identity_key": "MLBAM ID + role",
            "universe": "MLB dynasty-eligible projection rows only",
            "inputs": [
                "official MLB Stats API year-by-year stat history",
                "ValuCast current-season actuals already normalized from MLB Stats API",
            ],
            "eligibility": {
                "hitter_min_pa": MIN_HITTER_PA,
                "starter_min_ip": MIN_SP_IP,
                "reliever_or_generic_pitcher_min_ip": MIN_RP_IP,
            },
            "floor_caps": {
                "hitter": HITTER_TRACK_RECORD_FLOOR_CAP,
                "pitcher": PITCHER_TRACK_RECORD_FLOOR_CAP,
            },
            "score_fields": [
                "track_record_certainty",
                "track_record_floor_score",
                "experience_band",
            ],
        },
        "cache": {
            "fetched_count": fetched_count,
            "missing_history_count": len(missing_history),
            "pruned_player_count": pruned_count,
        },
        "validation": _validation(profiles, tracked, missing_history),
    }


def archive_track_record(payload: dict, archive_dir: Path = ARCHIVE_DIR) -> tuple[Path, bool]:
    generated_date = _date_part(payload.get("generated_at")) or datetime.now(timezone.utc).date().isoformat()
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / f"{generated_date}.json"
    archive_payload = {
        "generated_at": payload.get("generated_at"),
        "contract_version": payload.get("contract_version"),
        "profile_count": len(payload.get("profiles") or []),
        "validation": payload.get("validation") or {},
    }
    text = json.dumps(archive_payload, indent=2, sort_keys=True)
    changed = not archive_path.exists() or archive_path.read_text(encoding="utf-8") != text
    if changed:
        archive_path.write_text(text, encoding="utf-8")
    return archive_path, changed


def run_mlb_track_record(
    projection_path: Path = PROJECTION_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    cache_path: Path = CACHE_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    *,
    generated_at: str | None = None,
    season: int | None = None,
    fetcher: Callable[[str], dict] | None = None,
    bulk_fetcher: Callable[[Iterable[str]], dict[str, dict]] | None = None,
    refresh_missing: bool = True,
    fetch_limit: int | None = None,
) -> dict:
    projections = json.loads(projection_path.read_text(encoding="utf-8"))
    metadata_path = projection_path.parent / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    generated_at = generated_at or metadata.get("as_of") or datetime.now(timezone.utc).isoformat()
    cache = _load_cache(cache_path)
    payload = build_mlb_track_record(
        projections,
        generated_at=generated_at,
        season=season,
        cache=cache,
        fetcher=fetcher,
        bulk_fetcher=bulk_fetcher,
        refresh_missing=refresh_missing,
        cache_path=cache_path,
        fetch_limit=fetch_limit,
    )
    _save_cache(cache, cache_path)
    _write_json(payload, artifact_path)
    archive_path, archive_changed = archive_track_record(payload, archive_dir)
    validation = payload["validation"]
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "profile_count": validation["profile_count"],
        "coverage_rate": validation["coverage_rate"],
        "ready_for_mlb_dynasty_layer": validation["ready_for_mlb_dynasty_layer"],
        "fetched_count": payload["cache"]["fetched_count"],
    }
