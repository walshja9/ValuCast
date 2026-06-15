"""Build ValuCast's canonical prospect input contract.

The current upstream still arrives from the DD factual exporter, but public
ValuCast models should consume a ValuCast-owned, revalidated artifact instead
of reading the DD sync path directly.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.input_contract import UPSTREAM_DD_INPUT_PATH
from prospects.input_contract import VALUCAST_INPUT_PATH
from prospects.input_contract import validate_factual_contract

CONTRACT_VERSION = "0.1.0"


def build_valucast_prospect_input_contract(
    upstream_contract: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    problems = validate_factual_contract(upstream_contract)
    if problems:
        raise ValueError("invalid upstream factual contract: " + "; ".join(problems))

    payload = json.loads(json.dumps(upstream_contract))
    payload["generated_at"] = (
        generated_at
        or upstream_contract.get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    payload["producer"] = {
        "owner": "valucast",
        "kind": "canonical_factual_prospect_input_contract",
        "contract_version": CONTRACT_VERSION,
        "upstream_kind": "dd_factual_export",
        "upstream_generated_at": upstream_contract.get("generated_at"),
        "upstream_model_score_effect": "none",
        "consumer_contract": (
            "ValuCast models consume this canonical artifact, not the DD sync "
            "path. DD values, ranks, market signals, and public ranks remain "
            "forbidden by source policy."
        ),
    }
    return payload


def write_contract(payload: dict[str, Any], path: Path = VALUCAST_INPUT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_valucast_prospect_input_build(
    upstream_path: Path = UPSTREAM_DD_INPUT_PATH,
    output_path: Path = VALUCAST_INPUT_PATH,
) -> dict[str, Any]:
    upstream = json.loads(upstream_path.read_text(encoding="utf-8"))
    payload = build_valucast_prospect_input_contract(upstream)
    path = write_contract(payload, output_path)
    current = payload.get("current") or {}
    return {
        "artifact_path": str(path),
        "generated_at": payload.get("generated_at"),
        "historical_rows": len((payload.get("historical") or {}).get("rows") or []),
        "current_rows": len(current.get("hitters") or [])
        + len(current.get("pitchers") or []),
        "producer_owner": (payload.get("producer") or {}).get("owner"),
    }
