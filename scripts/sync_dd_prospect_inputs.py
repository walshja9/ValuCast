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


def fetch_contract(url: str) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ValuCast daily prospect-input refresh"},
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return response.read()


def validate_contract(payload: dict) -> list[str]:
    problems = []
    if payload.get("schema_version") != "1.1":
        problems.append("schema_version must be 1.1")
    if not payload.get("generated_at"):
        problems.append("generated_at is required")
    source_policy = payload.get("source_policy") or {}
    if source_policy.get("kind") != "factual_only":
        problems.append("source_policy.kind must be factual_only")
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
    if not isinstance(payload.get("mlb_service"), dict):
        problems.append("mlb_service must be an object")
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
