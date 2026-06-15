"""Build ValuCast's canonical prospect input contract from native raw inputs."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from prospects.input_contract import VALUCAST_INPUT_PATH
from prospects.input_contract import validate_factual_contract
from prospects.raw_input_builder import build_contract
from prospects.raw_input_builder import write_contract


def build_valucast_prospect_input_contract(
    generated_at: str | None = None,
) -> dict[str, Any]:
    payload = build_contract(generated_at=generated_at)
    problems = validate_factual_contract(payload)
    if problems:
        raise ValueError("invalid ValuCast factual contract: " + "; ".join(problems))
    return payload


def run_valucast_prospect_input_build(
    output_path: Path = VALUCAST_INPUT_PATH,
    generated_at: str | None = None,
) -> dict[str, Any]:
    payload = build_valucast_prospect_input_contract(generated_at=generated_at)
    path = write_contract(payload, output_path)
    current = payload.get("current") or {}
    return {
        "artifact_path": str(path),
        "generated_at": payload.get("generated_at"),
        "historical_rows": len((payload.get("historical") or {}).get("rows") or []),
        "current_rows": len(current.get("hitters") or [])
        + len(current.get("pitchers") or []),
        "producer_owner": (payload.get("producer") or {}).get("owner"),
        "upstream_kind": (payload.get("producer") or {}).get("upstream_kind"),
    }
