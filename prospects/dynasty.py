"""Shadow-only dynasty decision signals from universal prospect outcomes.

This layer does not change the universal baseball model. It translates the
model's factual bust/role/star distribution into dynasty-oriented decision
signals without emitting a rank, fantasy value, or recommendation.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.universal import ARTIFACT_PATH as UNIVERSAL_ARTIFACT_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_dynasty_layer.json"
BACKTEST_PATH = ROOT / "data" / "models" / "valucast_prospect_dynasty_backtest.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_dynasty_layer"

LAYER_NAME = "ValuCast Prospect Dynasty Ceiling/Risk Layer"
LAYER_VERSION = "0.1.0"


def coherent_distribution(established: float, star: float) -> dict[str, float]:
    established = max(0.0, min(1.0, float(established)))
    star = max(0.0, min(established, float(star)))
    return {
        "bust_probability": 1.0 - established,
        "role_probability": established - star,
        "star_probability": star,
    }


def _normalized_entropy(distribution: dict[str, float]) -> float:
    entropy = -sum(
        probability * math.log(probability)
        for probability in distribution.values()
        if probability > 0.0
    )
    return entropy / math.log(len(distribution))


def decision_signal(profile: dict) -> dict:
    distribution = profile.get("outcome_distribution") or {}
    expected_keys = {
        "bust_probability",
        "role_probability",
        "star_probability",
    }
    if set(distribution) != expected_keys:
        raise ValueError("Universal profile has an invalid outcome distribution")
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool)
        for value in distribution.values()
    ):
        raise ValueError("Universal profile outcome probabilities must be numeric")
    if any(not 0.0 <= float(value) <= 1.0 for value in distribution.values()):
        raise ValueError("Universal profile outcome probabilities must be between zero and one")
    if abs(sum(distribution.values()) - 1.0) > 0.001:
        raise ValueError("Universal profile outcome probabilities must sum to one")

    bust = float(distribution["bust_probability"])
    role = float(distribution["role_probability"])
    star = float(distribution["star_probability"])
    return {
        "bust_risk": round(bust, 4),
        "role_or_better_probability": round(role + star, 4),
        "star_ceiling_probability": round(star, 4),
        "expected_factual_outcome_tier": round(role + 2.0 * star, 4),
        "outcome_uncertainty": round(_normalized_entropy(distribution), 4),
    }


def _evidence_summary(backtest: dict | None, universal_version: str | None) -> dict:
    if not backtest:
        return {
            "research_gate": "hold",
            "reason": "No historical dynasty-layer backtest artifact is available.",
            "role_gates": {},
        }
    if backtest.get("universal_model_version") != universal_version:
        return {
            "research_gate": "hold",
            "reason": "Historical evidence was built from a different universal model version.",
            "role_gates": {},
        }
    promotion = backtest.get("promotion") or {}
    return {
        "research_gate": promotion.get("dynasty_layer_research_gate", "hold"),
        "reason": promotion.get("reason"),
        "role_gates": {
            role: result.get("role_research_gate", "hold")
            for role, result in (backtest.get("roles") or {}).items()
        },
    }


def build_layer(universal: dict, backtest: dict | None = None) -> dict:
    profiles = []
    for profile in universal.get("profiles") or []:
        profiles.append(
            {
                key: profile.get(key)
                for key in (
                    "mlbam_id",
                    "name",
                    "normalized_name",
                    "role",
                    "position",
                    "team",
                    "age",
                    "level",
                    "sample",
                    "sample_unit",
                    "sample_reliability",
                )
            }
            | {
                "outcome_distribution": profile.get("outcome_distribution"),
                "dynasty_signal": decision_signal(profile),
            }
        )
    evidence = _evidence_summary(backtest, universal.get("model_version"))
    return {
        "status": "shadow_only",
        "layer_name": LAYER_NAME,
        "layer_version": LAYER_VERSION,
        "universal_model_name": universal.get("model_name"),
        "universal_model_version": universal.get("model_version"),
        "generated_at": (universal.get("input_contract") or {}).get("generated_at"),
        "candidate_count": len(profiles),
        "layer_contract": {
            "purpose": (
                "Expose factual ceiling and risk signals for dynasty decisions "
                "without producing a rank or fantasy value."
            ),
            "consumes": ["outcome_distribution", "sample_reliability"],
            "rank_free": True,
            "value_free": True,
            "league_scoring_independent": True,
            "market_independent": True,
            "expected_factual_outcome_tier": {
                "bust": 0,
                "role": 1,
                "star": 2,
            },
            "outcome_uncertainty": "normalized entropy of bust/role/star probabilities",
        },
        "historical_evidence": evidence,
        "promotion": {
            "research_gate": evidence["research_gate"],
            "next_allowed_step": (
                "dated_forward_shadow_observation"
                if evidence["research_gate"] == "active"
                else "improve_model_or_historical_evidence"
            ),
            "live_consumer": "blocked",
            "feeds_live_dd_value": False,
            "feeds_live_valucast_rank": False,
        },
        "limitations": [
            "This is a ceiling/risk signal layer, not a complete dynasty valuation model.",
            "It contains no league, roster, trade-market, position-scarcity, or manager-preference context.",
            "The historical research gate currently has two eligible temporal folds per role.",
            "Live consumers remain blocked until dated forward shadow evidence is stable.",
        ],
        "profiles": profiles,
    }


def archive_predictions(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "layer_version": payload["layer_version"],
        "universal_model_version": payload["universal_model_version"],
        "historical_evidence": payload["historical_evidence"],
        "candidate_count": payload["candidate_count"],
        "profiles": payload["profiles"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_layer(
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
    payload = build_layer(universal, backtest)
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
    archive_path, archive_changed = archive_predictions(
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
    }
