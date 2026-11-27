"""Shared paths and validation for ValuCast prospect input contracts."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
VALUCAST_INPUT_PATH = ROOT / "data" / "prospects" / "prospect_model_inputs.json"

SUPPORTED_SCHEMA_SOURCES = {
    "1.1": {
        "valucast_universal_prospect_dataset",
        "milb_season_stats",
        "fantrax_mlb_actuals",
        "mlb_prospect_seasons_cache",
        "mlb_statsapi_draft",
    },
    "1.2": {
        "valucast_universal_prospect_dataset",
        "milb_season_stats",
        "fantrax_mlb_actuals",
        "mlb_prospect_seasons_cache",
        "mlb_statsapi_draft",
        "fantrax_roster_status",
    },
}

PROHIBITED_POLICY_FLAGS = (
    "external_rankings_used",
    "external_projections_used",
    "market_values_used",
    "dynasty_values_used",
)

PROHIBITED_MODEL_FIELDS = frozenset(
    {
        "consensus_rank",
        "source_ranks",
        "public_source_consensus",
        "fv",
        "tool_grades",
        "competitor_score",
        "competitor_rank",
        "market_value",
        "dynasty_value",
        "valucast_rank",
    }
)

NUMERIC_MEASUREMENT_FIELDS = frozenset({
    "age", "iso", "k_pct", "bb_pct", "ops", "k_per_9", "bb_per_9",
    "k_bb_pct", "era", "whip", "plate_appearances", "at_bats", "hits",
    "home_runs", "strikeouts", "walks", "doubles", "triples", "stolen_bases",
    "games_played", "avg", "obp", "slg", "babip", "innings_pitched",
    "batters_faced", "games_started", "earned_runs", "draft_pick_number",
    "draft_round", "signing_bonus", "pick_value", "pa", "ab", "r", "hr",
    "rbi", "sb", "so", "ip", "sv", "hld", "l", "k_bb", "qs", "games",
})
DESCRIPTIVE_DRAFT_FIELDS = frozenset({
    "draft_pick_number", "draft_round", "signing_bonus", "pick_value",
})


def _valid_measurement(value, field: str) -> bool:
    if value is None:
        return True
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except ValueError:
        # Legacy draft descriptions remain missing to the numeric feature parser.
        return field in DESCRIPTIVE_DRAFT_FIELDS and isinstance(value, str)
    except (TypeError, OverflowError):
        return False


def validate_numeric_measurements(payload: dict[str, Any]) -> list[str]:
    historical = payload.get("historical")
    current = payload.get("current")
    groups = [
        ("historical.rows", historical.get("rows") if isinstance(historical, dict) else None),
        ("mlb_service", payload.get("mlb_service")),
    ]
    groups.extend(
        (f"current.{role}", current.get(role) if isinstance(current, dict) else None)
        for role in ("hitters", "pitchers")
    )
    seasons = payload.get("historical_mlb_seasons")
    if isinstance(seasons, dict):
        groups.extend((f"historical_mlb_seasons.{key}", rows) for key, rows in seasons.items())
    return [
        f"{path}[{index}].{field} must be a finite numeric measurement"
        for path, rows in groups if isinstance(rows, list)
        for index, row in enumerate(rows) if isinstance(row, dict)
        for field in sorted(NUMERIC_MEASUREMENT_FIELDS & row.keys())
        if not _valid_measurement(row[field], field)
    ]


def _prohibited_row_fields(rows: list[dict], label: str) -> list[str]:
    return [
        f"{label}[{index}].{field} is prohibited"
        for index, row in enumerate(rows)
        if isinstance(row, dict)
        for field in sorted(PROHIBITED_MODEL_FIELDS & row.keys())
    ]


def validate_factual_contract(payload: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    schema_version = payload.get("schema_version")
    allowed_sources = SUPPORTED_SCHEMA_SOURCES.get(str(schema_version))
    if allowed_sources is None:
        problems.append("schema_version must be one of 1.1, 1.2")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy") or {}
    if source_policy.get("kind") != "factual_only":
        problems.append("source_policy.kind must be factual_only")
    elif allowed_sources is not None and set(source_policy.get("sources") or []) != allowed_sources:
        problems.append("source_policy.sources does not match schema_version")
    for flag in PROHIBITED_POLICY_FLAGS:
        if source_policy.get(flag) is not False:
            problems.append(f"source_policy.{flag} must be false")

    historical = payload.get("historical") or {}
    historical_rows = historical.get("rows")
    if not isinstance(historical_rows, list):
        problems.append("historical.rows must be a list")
    else:
        problems.extend(_prohibited_row_fields(historical_rows, "historical.rows"))
    current = payload.get("current") or {}
    for role in ("hitters", "pitchers"):
        role_rows = current.get(role)
        if not isinstance(role_rows, list):
            problems.append(f"current.{role} must be a list")
        else:
            problems.extend(_prohibited_row_fields(role_rows, f"current.{role}"))
    service_rows = payload.get("mlb_service")
    if not isinstance(service_rows, list):
        problems.append("mlb_service must be a list")
    problems.extend(validate_numeric_measurements(payload))
    return problems


def load_factual_contract(path: Path = VALUCAST_INPUT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prospect input contract must be a JSON object")
    problems = validate_factual_contract(payload)
    if problems:
        raise ValueError("invalid prospect input contract: " + "; ".join(problems))
    return payload
