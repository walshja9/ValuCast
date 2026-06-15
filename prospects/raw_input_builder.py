"""Build ValuCast's native factual-only prospect-model input contract.

This producer emits MiLB facts, forward MLB outcome labels, draft/signing facts,
availability context, and MLB service facts keyed by MLBAM id. It deliberately
excludes rankings, projections, dynasty values, and valuation outputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from prospects.input_contract import VALUCAST_INPUT_PATH

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "prospects" / "raw"
OUTCOME_DATASET_PATH = RAW_DIR / "valucast_universal_prospect_dataset.json"
CURRENT_STATS_PATH = RAW_DIR / "milb_season_stats.json"
MILB_CARD_HISTORY_PATH = RAW_DIR / "milb_card_history.json"
MLB_SEASONS_PATH = RAW_DIR / "mlb_prospect_seasons_cache.json"
DRAFT_FACTS_PATH = RAW_DIR / "mlb_draft_facts_cache.json"
OUTPUT_PATH = VALUCAST_INPUT_PATH
FANTRAX_CSV_DIR = RAW_DIR / "fantrax"

SCHEMA_VERSION = "1.2"
CONTRACT_VERSION = "0.2.0"
ROOKIE_AB_LIMIT = 131
ROOKIE_IP_LIMIT = 51
MAX_AGE = 25
MIN_CURRENT_SAMPLE = {"hitter": 50.0, "pitcher": 15.0}

_HISTORICAL_FIELDS = (
    "cohort_year",
    "mlbam_id",
    "name",
    "normalized_name",
    "role",
    "level",
    "age",
    "position",
    "is_starter",
    "k_pct",
    "bb_pct",
    "iso",
    "ops",
    "k_per_9",
    "bb_per_9",
    "k_bb_pct",
    "era",
    "whip",
    "outcome",
    "plate_appearances",
    "at_bats",
    "hits",
    "home_runs",
    "strikeouts",
    "walks",
    "doubles",
    "triples",
    "stolen_bases",
    "games_played",
    "avg",
    "obp",
    "slg",
    "babip",
    "innings_pitched",
    "batters_faced",
    "games_started",
    "earned_runs",
    "draft_record_known",
    "rule4_drafted",
    "draft_year",
    "draft_pick_number",
    "draft_round",
    "signing_bonus",
    "pick_value",
    "school_type",
    "bats",
    "throws",
)
_CURRENT_COMMON_FIELDS = (
    "mlbam_id",
    "name",
    "normalized_name",
    "team",
    "level",
    "sport_id",
    "role",
    "age",
    "position",
    "sample_season",
    "sample_fetched_date",
    "sample_staleness_years",
    "source_artifact",
    "source_kind",
    "roster_status",
    "availability_status",
    "availability_source",
    "availability_note",
    "availability_fetched_date",
)
_CURRENT_FIELDS = {
    "hitter": _CURRENT_COMMON_FIELDS
    + (
        "plate_appearances",
        "at_bats",
        "hits",
        "home_runs",
        "strikeouts",
        "walks",
        "doubles",
        "triples",
        "stolen_bases",
        "games_played",
        "avg",
        "obp",
        "slg",
        "ops",
        "iso",
        "k_pct",
        "bb_pct",
        "babip",
    ),
    "pitcher": _CURRENT_COMMON_FIELDS
    + (
        "innings_pitched",
        "k_per_9",
        "bb_per_9",
        "k_bb_pct",
        "era",
        "whip",
        "is_starter",
        "batters_faced",
        "games_started",
        "games_played",
        "strikeouts",
        "walks",
        "hits",
        "home_runs",
        "earned_runs",
    ),
}
_DRAFT_FIELDS = (
    "draft_record_known",
    "rule4_drafted",
    "draft_year",
    "draft_pick_number",
    "draft_round",
    "signing_bonus",
    "pick_value",
    "school_type",
    "bats",
    "throws",
)
_MLB_SEASON_FIELDS = {
    "hitter": ("year", "pa", "ab", "r", "hr", "rbi", "sb", "avg", "ops", "so"),
    "pitcher": (
        "year",
        "ip",
        "era",
        "whip",
        "so",
        "sv",
        "hld",
        "l",
        "k_bb",
        "qs",
    ),
}
_DECLARED_SCHEMA_SOURCES = (
    "valucast_universal_prospect_dataset",
    "milb_season_stats",
    "fantrax_mlb_actuals",
    "mlb_prospect_seasons_cache",
    "mlb_statsapi_draft",
    "fantrax_roster_status",
)
_POLICY_FLAGS = (
    "external_rankings_used",
    "external_projections_used",
    "market_values_used",
    "dynasty_values_used",
)
_POLICY_KEYS = {"kind", "sources", *_POLICY_FLAGS}
_ALLOWED_VALUE_KEYS = {"pick_value"}  # StatsAPI draft slot value, not market value.
_FORBIDDEN_EXACT_KEYS = {
    "rank",
    "ranking",
    "rankings",
    "source_rank",
    "source_ranks",
    "source_ranking",
    "source_rankings",
    "public_consensus",
}
_FORBIDDEN_SOURCE_TOKENS = (
    "rank",
    "ranking",
    "projection",
    "market",
    "dynasty",
    "hkb",
    "cfr",
    "pipeline",
    "scout",
    "sts",
    "public_board",
    "external_board",
)
_SOURCE_VALUE_KEYS = {"source", "sources", "source_artifact", "source_kind"}
_FANTRAX_OWNED_FILES = {
    "hitter": "Fantrax-Players-Diamond Dynasties-OwnedHitters.csv",
    "pitcher": "Fantrax-Players-Diamond Dynasties-OwnedPitchers.csv",
}
_INJURED_ROSTER_STATUSES = {"inj res", "injured reserve", "il", "injured", "out"}


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_optional_json(path: Path) -> dict:
    try:
        return _load_json(path)
    except (OSError, json.JSONDecodeError):
        return {}


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, sort_keys=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


def _normalize_name(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = " ".join(text.split())
    text = re.sub(r"\s+Jr\.?$", " jr", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+Sr\.?$", " sr", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+III$", " iii", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+II$", " ii", text, flags=re.IGNORECASE)
    text = text.replace(".", "")
    text = text.replace("'", "").replace("\u2019", "")
    text = " ".join(text.replace("-", " ").split())
    return text.strip().lower()


def _only(row: dict, fields: tuple[str, ...]) -> dict:
    return {field: row.get(field) for field in fields if field in row}


def _format_path(path: tuple) -> str:
    out = ""
    for part in path:
        if isinstance(part, int):
            out += f"[{part}]"
        elif out:
            out += f".{part}"
        else:
            out = str(part)
    return out or "<root>"


def _nearest_key(path: tuple) -> str | None:
    for part in reversed(path):
        if isinstance(part, str):
            return part
    return None


def _forbidden_key_reason(key) -> str | None:
    lower = str(key).lower()
    if lower in _ALLOWED_VALUE_KEYS or lower == "source_policy":
        return None
    if lower in _FORBIDDEN_EXACT_KEYS:
        return "forbidden rank/source key"
    if lower.startswith(("dynasty_", "market_", "projection_")):
        return "forbidden source family key"
    if lower.startswith("source_rank"):
        return "forbidden source-rank key"
    if lower.endswith(("_rank", "_ranks", "_ranking", "_rankings")):
        return "forbidden rank key"
    if lower.endswith("_value") or lower in {"value", "value_history"}:
        return "forbidden value key"
    if lower in {"hkb", "cfr", "pipeline", "mlb_pipeline", "sts"}:
        return "forbidden external source key"
    return None


def _source_value_reason(value) -> str | None:
    lower = str(value).lower()
    if any(token in lower for token in _FORBIDDEN_SOURCE_TOKENS):
        return "forbidden source family"
    return None


def _factual_policy_violations(value, path: tuple = ()) -> list[str]:
    violations = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = (*path, key)
            if path == () and key == "source_policy":
                if not isinstance(child, dict):
                    violations.append("source_policy must be an object")
                    continue
                if child.get("kind") != "factual_only":
                    violations.append("source_policy.kind must be factual_only")
                unexpected = set(child) - _POLICY_KEYS
                for unexpected_key in sorted(unexpected):
                    violations.append(
                        f"{_format_path(('source_policy', unexpected_key))}: "
                        "unexpected source-policy key"
                    )
                for flag in _POLICY_FLAGS:
                    if child.get(flag) is not False:
                        violations.append(
                            f"{_format_path(('source_policy', flag))}: must be false"
                        )
                for source in child.get("sources") or []:
                    reason = _source_value_reason(source)
                    if reason:
                        violations.append(
                            f"{_format_path(('source_policy', 'sources'))}: "
                            f"{reason} {source!r}"
                        )
                continue
            reason = _forbidden_key_reason(key)
            if reason:
                violations.append(f"{_format_path(child_path)}: {reason}")
            violations.extend(_factual_policy_violations(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            violations.extend(_factual_policy_violations(child, (*path, index)))
    elif isinstance(value, str):
        nearest_key = _nearest_key(path)
        if nearest_key in _SOURCE_VALUE_KEYS:
            reason = _source_value_reason(value)
            if reason:
                violations.append(f"{_format_path(path)}: {reason} {value!r}")
    return violations


def _source_policy_for_payload(payload: dict) -> dict:
    violations = _factual_policy_violations(payload)
    if violations:
        sample = "; ".join(violations[:5])
        raise ValueError(f"ValuCast factual contract includes prohibited inputs: {sample}")
    return {
        "kind": "factual_only",
        "sources": list(_DECLARED_SCHEMA_SOURCES),
        **{flag: False for flag in _POLICY_FLAGS},
    }


def _draft_for_cohort(fact: dict, cohort_year) -> dict:
    draft_year = fact.get("draft_year")
    if draft_year is None or cohort_year is None or int(draft_year) <= int(cohort_year):
        return fact
    return {
        **fact,
        "rule4_drafted": False,
        "draft_year": None,
        "draft_pick_number": None,
        "draft_round": None,
        "signing_bonus": None,
        "pick_value": None,
        "school_type": None,
    }


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fantrax_role_file_rows(csv_dir: Path = FANTRAX_CSV_DIR) -> list[dict]:
    rows = []
    for role, filename in _FANTRAX_OWNED_FILES.items():
        path = csv_dir / filename
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                name = row.get("Player")
                roster_status = str(row.get("Roster Status") or "").strip()
                if not name or not roster_status:
                    continue
                rows.append(
                    {
                        "normalized_name": _normalize_name(name),
                        "name": name,
                        "role": role,
                        "age": _num(row.get("Age")),
                        "roster_status": roster_status,
                        "source_artifact": filename,
                    }
                )
    return rows


def _fantrax_availability_from_csv(csv_dir: Path = FANTRAX_CSV_DIR) -> dict:
    """Return unique injured Fantrax roster statuses by normalized name and role.

    Fantrax exports do not carry MLBAM ids. To avoid reintroducing the same-name
    bug class, ambiguous name+role rows are dropped before the contract is built.
    The downstream row also has to pass an age-compatibility check.
    """
    grouped: dict[tuple[str, str], list[dict]] = {}
    for row in _fantrax_role_file_rows(csv_dir):
        status = row["roster_status"].strip().lower()
        if status not in _INJURED_ROSTER_STATUSES:
            continue
        key = (row["normalized_name"], row["role"])
        grouped.setdefault(key, []).append(row)
    return {
        key: rows[0]
        for key, rows in grouped.items()
        if key[0] and key[1] in {"hitter", "pitcher"} and len(rows) == 1
    }


def _availability_for_row(
    row: dict,
    role: str,
    availability_by_key: dict | None,
    fetched_date,
) -> dict:
    if not availability_by_key:
        return {}
    normalized_name = row.get("normalized_name") or _normalize_name(row.get("name"))
    candidate = availability_by_key.get((normalized_name, role))
    if not candidate:
        return {}

    row_age = _num(row.get("age"))
    candidate_age = _num(candidate.get("age"))
    if row_age is not None and candidate_age is not None and abs(row_age - candidate_age) > 1:
        return {}

    roster_status = str(candidate.get("roster_status") or "").strip()
    if roster_status.lower() not in _INJURED_ROSTER_STATUSES:
        return {}
    return {
        "roster_status": roster_status,
        "availability_status": "injured",
        "availability_source": "fantrax_roster_status",
        "availability_note": f"Fantrax roster status is {roster_status}.",
        "availability_fetched_date": fetched_date,
    }


def _statsapi_number(value, default=0.0):
    try:
        return float(str(value).split()[0])
    except (TypeError, ValueError):
        return default


def _statsapi_innings(value, default=0.0):
    try:
        text = str(value).split()[0]
    except (TypeError, ValueError):
        return default
    if "." not in text:
        try:
            return float(text)
        except ValueError:
            return default
    whole, fraction = text.split(".", 1)
    try:
        outs = int(fraction[:1] or 0)
        if outs not in {0, 1, 2}:
            return default
        return float(whole) + outs / 3.0
    except ValueError:
        return default


def _statsapi_service_seasons(mlbam_id: int, role: str) -> list[dict] | None:
    """Fetch MLB regular-season service lines by MLBAM id.

    This is intentionally not called by build_contract(). The Flask endpoint must
    remain cache-backed and deterministic; daily/manual refreshes populate the
    cache ahead of time.
    """
    group = "hitting" if role == "hitter" else "pitching"
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{mlbam_id}/stats"
        f"?stats=yearByYear&group={group}&gameType=R"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            payload = json.load(response)
    except Exception:
        return None

    seasons: list[dict] = []
    for stats_group in payload.get("stats") or []:
        for split in stats_group.get("splits") or []:
            if str((split.get("sport") or {}).get("id")) != "1":
                continue
            try:
                year = int(split["season"])
            except (KeyError, TypeError, ValueError):
                continue
            stat = split.get("stat") or {}
            if role == "hitter":
                seasons.append(
                    {
                        "year": year,
                        "pa": int(_statsapi_number(stat.get("plateAppearances"))),
                        "ab": int(_statsapi_number(stat.get("atBats"))),
                        "r": int(_statsapi_number(stat.get("runs"))),
                        "hr": int(_statsapi_number(stat.get("homeRuns"))),
                        "rbi": int(_statsapi_number(stat.get("rbi"))),
                        "sb": int(_statsapi_number(stat.get("stolenBases"))),
                        "avg": _statsapi_number(stat.get("avg")),
                        "ops": _statsapi_number(stat.get("ops")),
                        "so": int(_statsapi_number(stat.get("strikeOuts"))),
                    }
                )
            else:
                seasons.append(
                    {
                        "year": year,
                        "ip": _statsapi_innings(stat.get("inningsPitched")),
                        "era": _statsapi_number(stat.get("era"), 99.0),
                        "whip": _statsapi_number(stat.get("whip"), 99.0),
                        "so": int(_statsapi_number(stat.get("strikeOuts"))),
                        "sv": int(_statsapi_number(stat.get("saves"))),
                        "hld": int(_statsapi_number(stat.get("holds"))),
                        "l": int(_statsapi_number(stat.get("losses"))),
                        "k_bb": _statsapi_number(stat.get("strikeoutWalkRatio"), None),
                    }
                )
    return seasons


def _sample(row: dict, role: str) -> float:
    key = "plate_appearances" if role == "hitter" else "innings_pitched"
    return _num(row.get(key)) or 0.0


def _year(value) -> int | None:
    if isinstance(value, str):
        value = value[:4]
    numeric = _num(value)
    if numeric is None:
        return None
    return int(numeric)


def _age_for_current_context(age, sample_season, fetched_date):
    numeric_age = _num(age)
    if numeric_age is None:
        return None
    sample_year = _year(sample_season)
    current_year = _year(fetched_date)
    if sample_year is not None and current_year is not None:
        numeric_age += max(0, current_year - sample_year)
    return int(numeric_age) if float(numeric_age).is_integer() else round(numeric_age, 1)


def _level_rank(level: str | None) -> int:
    return {
        "AAA": 4,
        "AA": 3,
        "A+": 2,
        "HIGH-A": 2,
        "A": 1,
    }.get(str(level or "").upper(), 0)


def _eligible_current_row(row: dict, role: str) -> bool:
    mlbam_id = row.get("mlbam_id")
    age = _num(row.get("age"))
    level = str(row.get("level") or "").upper()
    return (
        bool(mlbam_id)
        and age is not None
        and age <= MAX_AGE
        and level in {"A", "A+", "AA", "AAA"}
        and _sample(row, role) >= MIN_CURRENT_SAMPLE[role]
    )


def _history_blocking_current_key(row: dict, role: str) -> tuple[int, str] | None:
    """Return a key when a fresh row proves older history is no longer eligible."""
    mlbam_id = row.get("mlbam_id")
    if not mlbam_id:
        return None
    age = _num(row.get("age"))
    level = str(row.get("level") or "").upper()
    if (age is not None and age > MAX_AGE) or (level and level not in {"A", "A+", "AA", "AAA"}):
        return int(mlbam_id), role
    return None


def _sanitize_current_row(
    row: dict,
    role: str,
    draft_facts: dict,
    sample_season,
    fetched_date,
    source_artifact: str,
    source_kind: str,
    availability_by_key: dict | None = None,
) -> dict:
    mlbam_id = int(row["mlbam_id"])
    out = {
        **_only(row, _CURRENT_FIELDS[role]),
        **_only(draft_facts.get(str(mlbam_id), {}), _DRAFT_FIELDS),
        **_availability_for_row(row, role, availability_by_key, fetched_date),
    }
    out["mlbam_id"] = mlbam_id
    out["role"] = role
    out["sample_season"] = sample_season
    row_fetched_date = row.get("sample_fetched_date") or fetched_date
    out["sample_fetched_date"] = row_fetched_date
    out["source_artifact"] = source_artifact
    out["source_kind"] = source_kind
    if source_kind == "latest_milb_history":
        current_age = _age_for_current_context(
            out.get("age"),
            sample_season,
            row_fetched_date,
        )
        if current_age is not None:
            out["age"] = current_age
    current_season = (
        _num(row_fetched_date[:4]) if isinstance(row_fetched_date, str) else None
    )
    sample_year = _num(sample_season)
    if current_season is not None and sample_year is not None:
        out["sample_staleness_years"] = int(current_season - sample_year)
    if role == "hitter" and out.get("ops") is None:
        obp = _num(out.get("obp"))
        slg = _num(out.get("slg"))
        if obp is not None and slg is not None:
            out["ops"] = round(obp + slg, 3)
    return out


def _history_candidates(
    milb_history: dict,
    draft_facts: dict,
    fetched_date,
    availability_by_key: dict | None = None,
) -> list[dict]:
    players = milb_history.get("players", {}) if isinstance(milb_history, dict) else {}
    selected: dict[tuple[int, str], dict] = {}
    for normalized_name, rows in players.items():
        if not isinstance(rows, list):
            continue
        for raw in rows:
            if not isinstance(raw, dict) or not raw.get("mlbam_id"):
                continue
            role = raw.get("role")
            if role not in {"hitter", "pitcher"}:
                continue
            row = {
                **raw,
                "name": raw.get("name") or str(normalized_name).title(),
                "normalized_name": raw.get("normalized_name") or normalized_name,
                "sport_id": raw.get("sport_id"),
            }
            current_age = _age_for_current_context(
                row.get("age"),
                row.get("season"),
                fetched_date,
            )
            eligibility_row = row
            if current_age is not None:
                eligibility_row = {**row, "age": current_age}
            if not _eligible_current_row(eligibility_row, role):
                continue
            key = (int(row["mlbam_id"]), role)
            candidate = _sanitize_current_row(
                row,
                role,
                draft_facts,
                sample_season=row.get("season"),
                fetched_date=fetched_date,
                source_artifact="milb_card_history",
                source_kind="latest_milb_history",
                availability_by_key=availability_by_key,
            )
            incumbent = selected.get(key)
            if incumbent is None:
                selected[key] = candidate
                continue
            challenger_key = (
                _num(candidate.get("sample_season")) or 0.0,
                _sample(candidate, role),
                _level_rank(candidate.get("level")),
            )
            incumbent_key = (
                _num(incumbent.get("sample_season")) or 0.0,
                _sample(incumbent, role),
                _level_rank(incumbent.get("level")),
            )
            if challenger_key > incumbent_key:
                selected[key] = candidate
    return [selected[key] for key in sorted(selected)]


def _current_rows(
    current: dict,
    milb_history: dict,
    draft_facts: dict,
    availability_by_key: dict | None = None,
) -> dict:
    rows = {
        group: [
            _sanitize_current_row(
                row,
                role,
                draft_facts,
                sample_season=current.get("season"),
                fetched_date=current.get("fetched_date"),
                source_artifact="milb_season_stats",
                source_kind="current_season",
                availability_by_key=availability_by_key,
            )
            for row in current.get(group, [])
            if row.get("mlbam_id")
        ]
        for role, group in (("hitter", "hitters"), ("pitcher", "pitchers"))
    }
    covered = {
        (int(row["mlbam_id"]), role)
        for role, group in (("hitter", "hitters"), ("pitcher", "pitchers"))
        for row in rows[group]
        if _eligible_current_row(row, role)
    }
    history_blocked = {
        key
        for role, group in (("hitter", "hitters"), ("pitcher", "pitchers"))
        for row in rows[group]
        if (key := _history_blocking_current_key(row, role))
    }
    for row in _history_candidates(
        milb_history,
        draft_facts,
        current.get("fetched_date"),
        availability_by_key=availability_by_key,
    ):
        role = row["role"]
        key = (int(row["mlbam_id"]), role)
        if key in covered or key in history_blocked:
            continue
        rows["hitters" if role == "hitter" else "pitchers"].append(row)
        covered.add(key)
    return rows


def _service_candidates(current: dict) -> list[tuple[dict, str]]:
    """One eligible A-through-AAA record per MLBAM id and role."""
    selected: dict[tuple[int, str], dict] = {}
    for role, group in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in current.get(group, []):
            if not _eligible_current_row(row, role):
                continue
            mlbam_id = row["mlbam_id"]
            key = (int(mlbam_id), role)
            if key not in selected or _sample(row, role) > _sample(selected[key], role):
                selected[key] = row
    return [(row, role) for (_, role), row in sorted(selected.items())]


def _service_totals(mlb_seasons: dict, mlbam_id: int, role: str) -> dict:
    seasons = mlb_seasons.get(f"{mlbam_id}_{role}") or []
    if role == "hitter":
        pa = sum(_num(season.get("pa")) or 0.0 for season in seasons)
        ab = sum(_num(season.get("ab")) or 0.0 for season in seasons)
        # Current cache revisions carry PA, not AB. Preserve the legacy `ab`
        # contract field as service-threshold volume while exposing `pa`.
        service_ab = ab if ab > 0 else pa
        return {"pa": round(pa, 1), "ab": round(service_ab, 1), "ip": 0.0}
    ip = sum(_num(season.get("ip")) or 0.0 for season in seasons)
    return {"pa": 0.0, "ab": 0.0, "ip": round(ip, 1)}


def _missing_service_keys(current: dict, mlb_seasons: dict) -> list[tuple[int, str, str]]:
    missing = []
    seen: set[tuple[int, str]] = set()
    for row, role in _service_candidates(current):
        mlbam_id = int(row["mlbam_id"])
        key = (mlbam_id, role)
        if key in seen:
            continue
        seen.add(key)
        cache_key = f"{mlbam_id}_{role}"
        if cache_key not in mlb_seasons:
            missing.append((mlbam_id, role, str(row.get("name") or "")))
    return missing


def _require_complete_service_cache(current: dict, mlb_seasons: dict) -> None:
    missing = _missing_service_keys(current, mlb_seasons)
    if not missing:
        return
    sample = ", ".join(
        f"{name or mlbam_id} ({mlbam_id}_{role})"
        for mlbam_id, role, name in missing[:8]
    )
    raise ValueError(
        "MLB service cache is missing current prospect candidates; "
        "run `python scripts/build_valucast_prospect_inputs.py --refresh-service-cache` "
        f"before exporting. Missing count={len(missing)} sample={sample}"
    )


def refresh_mlb_service_cache(
    current: dict | None = None,
    mlb_seasons: dict | None = None,
    *,
    limit: int | None = None,
    max_workers: int = 12,
    cache_path: Path = MLB_SEASONS_PATH,
) -> dict:
    current = (
        current
        if current is not None
        else _current_rows(
            _load_json(CURRENT_STATS_PATH),
            _load_optional_json(MILB_CARD_HISTORY_PATH),
            _load_optional_json(DRAFT_FACTS_PATH),
            _fantrax_availability_from_csv(),
        )
    )
    mlb_seasons = mlb_seasons if mlb_seasons is not None else _load_json(cache_path)
    missing = _missing_service_keys(current, mlb_seasons)
    if limit is not None:
        missing = missing[: max(0, limit)]
    if not missing:
        return {
            "cache_path": str(cache_path),
            "missing_before": 0,
            "fetched": 0,
            "failed": 0,
            "written": False,
        }

    fetched = 0
    failed = 0
    workers = max(1, int(max_workers or 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_statsapi_service_seasons, mlbam_id, role): (mlbam_id, role, name)
            for mlbam_id, role, name in missing
        }
        for future in as_completed(futures):
            mlbam_id, role, _name = futures[future]
            seasons = future.result()
            if seasons is None:
                failed += 1
                continue
            mlb_seasons[f"{mlbam_id}_{role}"] = seasons
            fetched += 1

    if fetched:
        _write_json(cache_path, mlb_seasons)
    return {
        "cache_path": str(cache_path),
        "missing_before": len(missing),
        "fetched": fetched,
        "failed": failed,
        "written": bool(fetched),
    }


def _service_facts(current: dict, mlb_seasons: dict) -> list[dict]:
    facts = []
    for row, role in _service_candidates(current):
        totals = _service_totals(mlb_seasons, int(row["mlbam_id"]), role)
        ab = _num(totals.get("ab")) or 0.0
        ip = _num(totals.get("ip")) or 0.0
        facts.append(
            {
                "mlbam_id": int(row["mlbam_id"]),
                "role": role,
                "pa": round(_num(totals.get("pa")) or 0.0, 1),
                "ab": round(ab, 1),
                "ip": round(ip, 1),
                "graduated": ab >= ROOKIE_AB_LIMIT or ip >= ROOKIE_IP_LIMIT,
            }
        )
    return facts


def _historical_mlb_seasons(seasons: dict) -> dict[str, list[dict]]:
    """Sanitize the factual MLB-season cache to the allowed category subset."""
    out = {}
    for key, rows in seasons.items():
        if key.endswith("_hitter"):
            role = "hitter"
        elif key.endswith("_pitcher"):
            role = "pitcher"
        else:
            continue
        out[key] = [_only(row, _MLB_SEASON_FIELDS[role]) for row in rows]
    return out


def build_contract(
    dataset: dict | None = None,
    current: dict | None = None,
    milb_history: dict | None = None,
    mlb_seasons: dict | None = None,
    draft_facts: dict | None = None,
    fantrax_availability: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    current_provided = current is not None
    dataset = dataset if dataset is not None else _load_json(OUTCOME_DATASET_PATH)
    current = current if current is not None else _load_json(CURRENT_STATS_PATH)
    milb_history = (
        milb_history
        if milb_history is not None
        else ({} if current_provided else _load_optional_json(MILB_CARD_HISTORY_PATH))
    )
    mlb_seasons = (
        mlb_seasons if mlb_seasons is not None else _load_json(MLB_SEASONS_PATH)
    )
    draft_facts = (
        draft_facts if draft_facts is not None else _load_optional_json(DRAFT_FACTS_PATH)
    )
    fantrax_availability = (
        fantrax_availability
        if fantrax_availability is not None
        else ({} if current_provided else _fantrax_availability_from_csv())
    )
    generated_at = (
        generated_at
        or (
            f"{current.get('fetched_date')}T00:00:00+00:00"
            if current.get("fetched_date")
            else None
        )
        or datetime.now(timezone.utc).isoformat()
    )

    historical_rows = []
    for row in dataset.get("rows", []):
        draft = (
            _draft_for_cohort(
                draft_facts.get(str(int(row["mlbam_id"])), {}),
                row.get("cohort_year"),
            )
            if row.get("mlbam_id")
            else {}
        )
        historical_rows.append(
            {
                **_only(row, _HISTORICAL_FIELDS),
                **_only(draft, _DRAFT_FIELDS),
            }
        )
    current_rows = _current_rows(
        current,
        milb_history,
        draft_facts,
        fantrax_availability,
    )
    _require_complete_service_cache(current_rows, mlb_seasons)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "producer": {
            "owner": "valucast",
            "kind": "canonical_factual_prospect_input_contract",
            "contract_version": CONTRACT_VERSION,
            "upstream_kind": "valucast_raw_ingestion",
            "upstream_generated_at": generated_at,
            "upstream_model_score_effect": "none",
            "raw_inputs": [
                "valucast_universal_prospect_dataset.json",
                "milb_season_stats.json",
                "milb_card_history.json",
                "mlb_prospect_seasons_cache.json",
                "mlb_draft_facts_cache.json",
                "fantrax/*.csv",
            ],
        },
        "rookie_limits": {
            "at_bats": ROOKIE_AB_LIMIT,
            "innings_pitched": ROOKIE_IP_LIMIT,
        },
        "historical": {
            "cohorts": dataset.get("cohorts", []),
            "omitted_cohorts": dataset.get("omitted_cohorts", []),
            "rows": historical_rows,
        },
        "historical_mlb_seasons": _historical_mlb_seasons(mlb_seasons),
        "current": {
            "season": current.get("season"),
            "fetched_date": current.get("fetched_date"),
            **current_rows,
        },
        "mlb_service": _service_facts(current_rows, mlb_seasons),
    }
    payload["source_policy"] = _source_policy_for_payload(payload)
    _source_policy_for_payload(payload)
    return payload


def write_contract(payload: dict, path: Path = OUTPUT_PATH) -> Path:
    return _write_json(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-service-cache",
        action="store_true",
        help="Fetch missing MLBAM-keyed MLB service seasons before writing the contract.",
    )
    parser.add_argument(
        "--refresh-service-limit",
        type=int,
        default=None,
        help="Limit missing service-cache fetches for resumable backfills.",
    )
    parser.add_argument(
        "--refresh-service-workers",
        type=int,
        default=12,
        help="Concurrent StatsAPI workers for --refresh-service-cache.",
    )
    args = parser.parse_args()

    if args.refresh_service_cache:
        result = refresh_mlb_service_cache(
            limit=args.refresh_service_limit,
            max_workers=args.refresh_service_workers,
        )
        print(
            "MLB service cache refresh: "
            f"missing={result['missing_before']} "
            f"fetched={result['fetched']} failed={result['failed']}"
        )

    payload = build_contract()
    path = write_contract(payload)
    print(f"Wrote {path} ({len(payload['historical']['rows'])} historical rows)")


if __name__ == "__main__":
    main()
