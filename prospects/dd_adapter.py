"""Shadow-only Diamond Dynasties 7x7 adapter for universal prospect profiles.

The adapter is a league-specific sibling of the Universal Prospect Index. It
consumes the same factual universal profiles, but translates their projected
category production into DD 7x7 role ranks. It never changes the universal
model or live DD value.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.adapter_backtest import (
    ARTIFACT_PATH as BACKTEST_PATH,
    OUTCOME_HORIZON_YEARS,
)
from prospects.adapters import ADAPTER_VERSION, PRESETS, adapt_categories
from prospects.universal import ARTIFACT_PATH as UNIVERSAL_ARTIFACT_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_dd_7x7_prospect_adapter.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_dd_7x7_prospect_adapter"

ADAPTER_NAME = "ValuCast Diamond Dynasties 7x7 Prospect Adapter"
DD_ADAPTER_VERSION = "0.1.0"
PRESET_KEY = "dd_7x7"


def _assign_shared_ranks(players: list[dict]) -> None:
    """Preserve honest shared ranks when rounded adapter scores are equal."""
    previous_score = None
    previous_rank = 0
    for position, player in enumerate(players, 1):
        score = player.get("adapter_score")
        if score != previous_score:
            previous_rank = position
            previous_score = score
        player["adapter_rank"] = previous_rank


def _evidence_summary(
    backtest: dict | None,
    universal_version: str | None,
    generated_at: str | None,
) -> dict:
    if not backtest:
        return {
            "research_gate": "hold",
            "reason": "No historical DD 7x7 adapter backtest is available.",
            "role_gates": {},
            "role_fold_counts": {},
        }
    if backtest.get("universal_model_version") != universal_version:
        return {
            "research_gate": "hold",
            "reason": "Historical DD adapter evidence used a different universal model version.",
            "role_gates": {},
            "role_fold_counts": {},
        }
    if backtest.get("generated_at") != generated_at:
        return {
            "research_gate": "hold",
            "reason": "Historical DD adapter evidence used a different factual input snapshot.",
            "role_gates": {},
            "role_fold_counts": {},
        }
    validation = backtest.get("validation_contract") or {}
    if (
        backtest.get("adapter_preset") != PRESET_KEY
        or validation.get("outcome_horizon_years") != OUTCOME_HORIZON_YEARS
    ):
        return {
            "research_gate": "hold",
            "reason": "Historical DD adapter evidence used a different league or outcome horizon.",
            "role_gates": {},
            "role_fold_counts": {},
        }
    promotion = backtest.get("promotion") or {}
    roles = backtest.get("roles") or {}
    return {
        "research_gate": promotion.get("adapter_research_gate", "hold"),
        "reason": promotion.get("reason"),
        "outcome_horizon_years": validation.get("outcome_horizon_years"),
        "role_gates": {
            role: result.get("role_research_gate", "hold")
            for role, result in roles.items()
        },
        "role_fold_counts": {
            role: int(result.get("fold_count") or 0)
            for role, result in roles.items()
        },
    }


def build_dd_adapter(universal: dict, backtest: dict | None = None) -> dict:
    generated_at = (universal.get("input_contract") or {}).get("generated_at")
    preset = PRESETS[PRESET_KEY]
    adapted = adapt_categories(
        universal.get("profiles") or [],
        name=preset["name"],
        categories={"hitter": preset["hitter"], "pitcher": preset["pitcher"]},
    )
    for role_result in adapted["roles"].values():
        if role_result["status"] == "research_ranked":
            _assign_shared_ranks(role_result["players"])
    evidence = _evidence_summary(backtest, universal.get("model_version"), generated_at)
    current_contract_active = adapted["status"] == "research_ranked"
    research_gate = (
        "active"
        if evidence["research_gate"] == "active" and current_contract_active
        else "hold"
    )
    return {
        "status": "shadow_only",
        "adapter_name": ADAPTER_NAME,
        "adapter_version": DD_ADAPTER_VERSION,
        "category_adapter_version": ADAPTER_VERSION,
        "universal_model_name": universal.get("model_name"),
        "universal_model_version": universal.get("model_version"),
        "generated_at": generated_at,
        "candidate_count": sum(
            result["candidate_count"] for result in adapted["roles"].values()
        ),
        "adapter_contract": {
            "purpose": (
                "Translate ValuCast factual prospect profiles into expected future "
                "Diamond Dynasties 7x7 category impact."
            ),
            "league": "Diamond Dynasties",
            "preset": PRESET_KEY,
            "categories": {
                role: dict(categories)
                for role, categories in (
                    ("hitter", preset["hitter"]),
                    ("pitcher", preset["pitcher"]),
                )
            },
            "consumes": "ValuCast Universal Prospect Model factual category projections",
            "universal_index_relationship": (
                "Sibling consumer of the same factual universal profiles; the "
                "Universal Prospect Index rank is not an input."
            ),
            "rank_scope": "within_role",
            "cross_role_rank": False,
            "tie_policy": "Equal adapter scores share the same within-role rank.",
            "market_independent": True,
            "external_rankings_used": False,
            "dd_values_used": False,
            "is_live_dd_valuation": False,
        },
        "historical_evidence": evidence,
        "promotion": {
            "research_gate": research_gate,
            "current_category_contract": (
                "active" if current_contract_active else "hold"
            ),
            "reason": (
                evidence["reason"]
                if current_contract_active
                else "The current universal artifact does not support every DD 7x7 category."
            ),
            "next_allowed_step": (
                "dated_forward_shadow_observation"
                if research_gate == "active"
                else "improve_model_or_historical_evidence"
            ),
            "live_consumer": "blocked",
            "feeds_live_dd_value": False,
            "feeds_live_valucast_rank": False,
        },
        "limitations": [
            "Shadow-only; this adapter is not consumed by live DD value or rank.",
            "Ranks are within hitter and pitcher roles because no cross-role DD exchange rate is validated.",
            "Category projections inherit the statistical scope and limitations of the universal model.",
            "Roster scarcity, trade-market behavior, ownership, and manager preferences are absent.",
        ],
        "roles": adapted["roles"],
    }


def archive_dd_adapter(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "adapter_version": payload["adapter_version"],
        "universal_model_version": payload["universal_model_version"],
        "historical_evidence": payload["historical_evidence"],
        "candidate_count": payload["candidate_count"],
        "roles": payload["roles"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_dd_adapter(
    universal_path: Path = UNIVERSAL_ARTIFACT_PATH,
    backtest_path: Path = BACKTEST_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    universal = json.loads(universal_path.read_text(encoding="utf-8"))
    backtest = (
        json.loads(backtest_path.read_text(encoding="utf-8"))
        if backtest_path.exists()
        else None
    )
    payload = build_dd_adapter(universal, backtest)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    generated_at = payload.get("generated_at")
    parsed_now = (
        datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if generated_at
        else datetime.now(timezone.utc)
    )
    if parsed_now.tzinfo is None:
        parsed_now = parsed_now.replace(tzinfo=timezone.utc)
    archive_path, archive_changed = archive_dd_adapter(
        payload,
        date_str=parsed_now.date().isoformat(),
        archive_dir=archive_dir,
    )
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "research_gate": payload["promotion"]["research_gate"],
        "candidate_count": payload["candidate_count"],
        "role_statuses": {
            role: result["status"] for role, result in payload["roles"].items()
        },
    }
