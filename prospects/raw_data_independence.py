"""Audit ValuCast prospect raw-data ownership boundaries."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.rank_v1 import INPUT_CONTRACT_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_raw_data_independence_audit.json"

AUDIT_VERSION = "0.1.0"
VALUCAST_OWNED_SOURCES = {
    "valucast_universal_prospect_dataset",
    "milb_season_stats",
    "fantrax_mlb_actuals",
    "mlb_prospect_seasons_cache",
    "mlb_statsapi_draft",
    "fantrax_roster_status",
}
DIRECT_RAW_TARGET_SOURCES = {
    "milb_season_stats",
    "fantrax_mlb_actuals",
    "mlb_prospect_seasons_cache",
    "mlb_statsapi_draft",
    "fantrax_roster_status",
}


def build_raw_data_independence_audit(
    input_contract: dict,
    generated_at: str | None = None,
) -> dict:
    generated = generated_at or input_contract.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    policy = input_contract.get("source_policy") or {}
    sources = set(policy.get("sources") or [])
    prohibited_flags = {
        "external_rankings_used": policy.get("external_rankings_used"),
        "external_projections_used": policy.get("external_projections_used"),
        "market_values_used": policy.get("market_values_used"),
        "dynasty_values_used": policy.get("dynasty_values_used"),
    }
    current = input_contract.get("current") or {}
    historical = input_contract.get("historical") or {}
    blockers = []
    if policy.get("kind") != "factual_only":
        blockers.append("Prospect input contract is not factual_only.")
    for flag, value in prohibited_flags.items():
        if value is not False:
            blockers.append(f"source_policy.{flag} must be false.")
    unexpected = sorted(sources - VALUCAST_OWNED_SOURCES)
    if unexpected:
        blockers.append(
            "Prospect input contract contains unexpected source families: "
            + ", ".join(unexpected)
        )

    direct_raw_sources_present = sorted(sources & DIRECT_RAW_TARGET_SOURCES)
    source_boundary = {
        "current_boundary": "DD-hosted factual input contract",
        "desired_boundary": "ValuCast-owned raw ingestion and factual contract",
        "consumer_side_gates": [
            "sync_dd_prospect_inputs",
            "Prospect Model validators",
            "Prospect Rank v1 validators",
        ],
        "remaining_trust_assumption": (
            "ValuCast currently trusts the upstream producer to label factual "
            "fields honestly before ValuCast re-validates the contract."
        ),
    }
    direct_raw_ownership_score = round(
        len(direct_raw_sources_present) / len(DIRECT_RAW_TARGET_SOURCES),
        4,
    )
    return {
        "artifact": "valucast_raw_data_independence_audit",
        "audit_version": AUDIT_VERSION,
        "generated_at": generated,
        "status": "boundary_hardened" if not blockers else "blocked",
        "source_policy": {
            "kind": "raw_data_independence_audit",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "input_contract": {
            "schema_version": input_contract.get("schema_version"),
            "generated_at": input_contract.get("generated_at"),
            "source_policy": policy,
            "historical_row_count": len(historical.get("rows") or []),
            "current_hitter_count": len(current.get("hitters") or []),
            "current_pitcher_count": len(current.get("pitchers") or []),
            "historical_mlb_season_identity_count": len(
                input_contract.get("historical_mlb_seasons") or {}
            ),
        },
        "independence": {
            "contract_factual_only": policy.get("kind") == "factual_only",
            "prohibited_flags_clean": all(value is False for value in prohibited_flags.values()),
            "expected_sources_only": not unexpected,
            "direct_raw_sources_present": direct_raw_sources_present,
            "direct_raw_ownership_score": direct_raw_ownership_score,
            "last_external_trust_boundary": source_boundary,
            "next_cord_to_cut": (
                "Move DD-hosted factual-input production into ValuCast-owned "
                "raw ingestion jobs, then keep DD as a consumer/adapter only."
            ),
        },
        "validation": {
            "ready_for_current_publication": not blockers,
            "raw_data_independence_complete": False,
            "blockers": blockers,
        },
    }


def write_raw_data_independence_audit(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_raw_data_independence_audit(
    input_contract_path: Path = INPUT_CONTRACT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_raw_data_independence_audit(
        json.loads(input_contract_path.read_text(encoding="utf-8"))
    )
    path = write_raw_data_independence_audit(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "direct_raw_ownership_score": payload["independence"][
            "direct_raw_ownership_score"
        ],
        "blocker_count": len(payload["validation"]["blockers"]),
    }
