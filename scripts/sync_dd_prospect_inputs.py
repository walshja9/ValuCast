#!/usr/bin/env python3
"""Atomically sync DD's factual prospect input contract into ValuCast."""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_URL = (
    "https://diamonddynastiesleagueanalyzer.onrender.com/api/valucast-prospect-inputs"
)
DEFAULT_OUTPUT = ROOT / "data" / "dd" / "prospect_model_inputs.json"
TIMEOUT_SECONDS = 90
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


def fetch_contract(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ValuCast daily prospect-input refresh"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def validate_contract(payload: dict) -> list[str]:
    problems = []
    schema_version = payload.get("schema_version")
    allowed_sources = SUPPORTED_SCHEMA_SOURCES.get(schema_version)
    if allowed_sources is None:
        problems.append("schema_version must be one of 1.1, 1.2")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy") or {}
    if source_policy.get("kind") != "factual_only":
        problems.append("source_policy.kind must be factual_only")
    elif allowed_sources is not None and set(source_policy.get("sources") or []) != allowed_sources:
        problems.append("source_policy.sources does not match schema_version")
    for flag in (
        "external_rankings_used",
        "external_projections_used",
        "market_values_used",
        "dynasty_values_used",
    ):
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
    else:
        for index, row in enumerate(service_rows):
            if not isinstance(row, dict):
                problems.append(f"mlb_service[{index}] must be an object")
                continue
            if not row.get("mlbam_id"):
                problems.append(f"mlb_service[{index}].mlbam_id is required")
            if row.get("role") not in {"hitter", "pitcher"}:
                problems.append(f"mlb_service[{index}].role is invalid")
            if not isinstance(row.get("graduated"), bool):
                problems.append(f"mlb_service[{index}].graduated must be boolean")
            for volume_field in ("pa", "ab", "ip"):
                value = row.get(volume_field)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, (int, float))
                ):
                    problems.append(
                        f"mlb_service[{index}].{volume_field} must be numeric"
                    )
    return problems


def sync_contract(url: str = DEFAULT_URL, output: Path = DEFAULT_OUTPUT) -> dict:
    body = fetch_contract(url)
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("prospect input response must be a JSON object")
    problems = validate_contract(payload)
    if problems:
        raise ValueError("invalid prospect input contract: " + "; ".join(problems))

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    payload = sync_contract(args.url, args.output)
    current = payload.get("current") or {}
    current_count = len(current.get("hitters") or []) + len(current.get("pitchers") or [])
    print(
        f"Synced DD prospect inputs: generated_at={payload.get('generated_at')} "
        f"historical={len((payload.get('historical') or {}).get('rows') or [])} "
        f"current={current_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
