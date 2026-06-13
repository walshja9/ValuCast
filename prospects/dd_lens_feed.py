"""Slim, versioned ValuCast-to-DD prospect Statistical Lens feed."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.adapters import PRESETS
from prospects.dd_adapter import ARTIFACT_PATH as DD_ADAPTER_PATH
from prospects.universal import ARTIFACT_PATH as UNIVERSAL_ARTIFACT_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "exports" / "valucast_dd_prospect_lens.json"
DEFAULT_DD_COPY_PATH = Path(
    r"C:\Users\Alex\DiamondDynastiesTradeAnalyzer\data\valucast_prospect_lens.json"
)

SCHEMA_VERSION = 2
CONTRACT_VERSION = 2
ARTIFACT_NAME = "valucast_dd_prospect_lens"
ALLOWED_ROLES = {"hitter", "pitcher"}
ALLOWED_GATE_STATUSES = {"active", "hold"}
PROHIBITED_SOURCE_FLAGS = (
    "external_rankings_used",
    "external_projections_used",
    "market_values_used",
    "dynasty_values_used",
)


def _as_positive_int(value) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _as_number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_source_policy(policy: dict) -> None:
    if policy.get("kind") != "factual_only":
        raise ValueError("ValuCast source policy must be factual_only")
    if any(policy.get(flag) is not False for flag in PROHIBITED_SOURCE_FLAGS):
        raise ValueError("ValuCast source policy contains prohibited inputs")


def _validate_relationship(adapter: dict, universal: dict) -> dict:
    if adapter.get("status") != "shadow_only":
        raise ValueError("DD adapter must remain shadow_only")
    if universal.get("status") != "shadow_only":
        raise ValueError("universal model must remain shadow_only")
    input_contract = universal.get("input_contract") or {}
    source_policy = input_contract.get("source_policy") or {}
    _validate_source_policy(source_policy)
    if adapter.get("generated_at") != input_contract.get("generated_at"):
        raise ValueError("DD adapter and universal model snapshots do not match")
    if adapter.get("universal_model_version") != universal.get("model_version"):
        raise ValueError("DD adapter and universal model versions do not match")

    contract = adapter.get("adapter_contract") or {}
    promotion = adapter.get("promotion") or {}
    categories = contract.get("categories") or {}
    if (
        contract.get("preset") != "dd_7x7"
        or contract.get("rank_scope") != "within_role"
        or contract.get("cross_role_rank") is not False
        or contract.get("market_independent") is not True
        or contract.get("external_rankings_used") is not False
        or contract.get("dd_values_used") is not False
        or contract.get("is_live_dd_valuation") is not False
        or promotion.get("live_consumer") != "blocked"
        or promotion.get("feeds_live_dd_value") is not False
        or any(
            set(categories.get(role) or {}) != set(PRESETS["dd_7x7"][role])
            for role in ALLOWED_ROLES
        )
    ):
        raise ValueError("DD adapter relationship contract is invalid")
    return source_policy


def build_feed(
    adapter: dict,
    universal: dict,
    *,
    published_at: str | None = None,
) -> dict:
    """Build the only artifact DD needs to render the observe-only lens."""
    source_policy = _validate_relationship(adapter, universal)
    evidence = adapter.get("historical_evidence") or {}
    role_gates = evidence.get("role_gates") or {}
    role_fold_counts = evidence.get("role_fold_counts") or {}
    if (
        evidence.get("research_gate") not in ALLOWED_GATE_STATUSES
        or any(role_gates.get(role) not in ALLOWED_GATE_STATUSES for role in ALLOWED_ROLES)
    ):
        raise ValueError("DD adapter historical evidence is invalid")
    categories = (adapter.get("adapter_contract") or {}).get("categories") or {}
    players = []
    seen = set()

    for role in ("hitter", "pitcher"):
        role_result = (adapter.get("roles") or {}).get(role) or {}
        if role_result.get("status") != "research_ranked":
            raise ValueError("DD adapter role is not research_ranked")
        expected_categories = set((categories.get(role) or PRESETS["dd_7x7"][role]))
        for row in role_result.get("players") or []:
            mlbam_id = _as_positive_int(row.get("mlbam_id"))
            adapter_rank = _as_positive_int(row.get("adapter_rank"))
            adapter_score = _as_number(row.get("adapter_score"))
            projected_volume = _as_number(row.get("projected_volume"))
            row_categories = row.get("categories") or {}
            identity = (mlbam_id, role)
            if (
                mlbam_id is None
                or adapter_rank is None
                or adapter_score is None
                or projected_volume is None
                or projected_volume < 0
                or not row.get("name")
                or row.get("role") != role
                or set(row_categories) != expected_categories
                or any(_as_number(value) is None for value in row_categories.values())
            ):
                raise ValueError("DD adapter contains an invalid player row")
            if identity in seen:
                raise ValueError("DD adapter contains duplicate MLBAM identities")
            seen.add(identity)
            players.append(
                {
                    "mlbam_id": mlbam_id,
                    "name": str(row["name"]),
                    "role": role,
                    "age": row.get("age"),
                    "level": row.get("level"),
                    "adapter_rank": adapter_rank,
                    "adapter_score": round(adapter_score, 4),
                    "projected_volume": round(projected_volume, 4),
                    "categories": {
                        key: round(float(value), 4)
                        for key, value in sorted(row_categories.items())
                    },
                }
            )

    players.sort(key=lambda row: (row["role"], row["adapter_rank"], row["mlbam_id"]))
    generated_at = adapter.get("generated_at")
    return {
        "_meta": {
            "artifact": ARTIFACT_NAME,
            "schema_version": SCHEMA_VERSION,
            "contract_version": CONTRACT_VERSION,
            "generated_at": generated_at,
            "published_at": published_at or datetime.now(timezone.utc).isoformat(),
            "sources": [
                "valucast_universal_prospect_model",
                "valucast_dd_7x7_prospect_adapter",
            ],
            "sample_size": len(players),
            "staleness_max_hours": 96,
        },
        "status": "shadow_only",
        "source_model": universal.get("model_name"),
        "source_model_version": universal.get("model_version"),
        "source_adapter": adapter.get("adapter_name"),
        "source_adapter_version": adapter.get("adapter_version"),
        "source_generated_at": generated_at,
        "source_policy": source_policy,
        "candidate_count": len(players),
        "adapter_contract": {
            "league": "Diamond Dynasties",
            "preset": "dd_7x7",
            "categories": categories,
            "rank_scope": "within_role",
            "cross_role_rank": False,
            "identity": "mlbam_id_plus_role",
            "market_independent": True,
            "external_rankings_used": False,
            "dd_values_used": False,
            "is_live_dd_valuation": False,
        },
        "historical_evidence": {
            "research_gate": evidence.get("research_gate", "hold"),
            "reason": evidence.get("reason"),
            "outcome_horizon_years": evidence.get("outcome_horizon_years"),
            "role_gates": {
                role: role_gates.get(role, "hold") for role in sorted(ALLOWED_ROLES)
            },
            "role_fold_counts": {
                role: int(role_fold_counts.get(role) or 0)
                for role in sorted(ALLOWED_ROLES)
            },
        },
        "promotion": {
            "live_consumer": "blocked",
            "feeds_live_dd_value": False,
            "feeds_live_valucast_rank": False,
        },
        "players": players,
    }


def write_feed(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def copy_feed(payload: dict, destination: Path = DEFAULT_DD_COPY_PATH) -> Path:
    return write_feed(payload, destination)


def run_feed(
    adapter_path: Path = DD_ADAPTER_PATH,
    universal_path: Path = UNIVERSAL_ARTIFACT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    *,
    published_at: str | None = None,
) -> dict:
    adapter = json.loads(Path(adapter_path).read_text(encoding="utf-8"))
    universal = json.loads(Path(universal_path).read_text(encoding="utf-8"))
    payload = build_feed(adapter, universal, published_at=published_at)
    write_feed(payload, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "candidate_count": payload["candidate_count"],
        "research_gate": payload["historical_evidence"]["research_gate"],
    }
