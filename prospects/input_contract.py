"""Shared paths and validation for ValuCast prospect input contracts."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_DD_INPUT_PATH = ROOT / "data" / "dd" / "prospect_model_inputs.json"
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
    if not isinstance(historical.get("rows"), list):
        problems.append("historical.rows must be a list")
    current = payload.get("current") or {}
    for role in ("hitters", "pitchers"):
        if not isinstance(current.get(role), list):
            problems.append(f"current.{role} must be a list")
    service_rows = payload.get("mlb_service")
    if not isinstance(service_rows, list):
        problems.append("mlb_service must be a list")
    return problems


def load_factual_contract(path: Path = VALUCAST_INPUT_PATH) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("prospect input contract must be a JSON object")
    problems = validate_factual_contract(payload)
    if problems:
        raise ValueError("invalid prospect input contract: " + "; ".join(problems))
    return payload
