"""Shadow-only universal prospect ranking from factual MLB outcome profiles.

The index ranks expected MLB outcomes, not fantasy value. It is intentionally
transparent: bust outcomes map to 0, established roles to 50, and stars to 100.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.universal import ARTIFACT_PATH as UNIVERSAL_ARTIFACT_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_universal_prospect_index.json"
BACKTEST_PATH = (
    ROOT / "data" / "models" / "valucast_universal_prospect_index_backtest.json"
)
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_universal_prospect_index"

INDEX_NAME = "ValuCast Universal Prospect Index"
INDEX_VERSION = "0.1.0"
OUTCOME_WEIGHTS = {
    "bust_probability": 0.0,
    "role_probability": 50.0,
    "star_probability": 100.0,
}


def index_score(distribution: dict) -> float:
    """Return the transparent 0-100 expected factual MLB outcome score."""
    if set(distribution) != set(OUTCOME_WEIGHTS):
        raise ValueError("Universal profile has an invalid outcome distribution")
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool)
        for value in distribution.values()
    ):
        raise ValueError("Universal profile outcome probabilities must be numeric")
    if any(not 0.0 <= float(value) <= 1.0 for value in distribution.values()):
        raise ValueError("Universal profile outcome probabilities must be between zero and one")
    if abs(sum(float(value) for value in distribution.values()) - 1.0) > 0.001:
        raise ValueError("Universal profile outcome probabilities must sum to one")
    return round(
        sum(float(distribution[key]) * weight for key, weight in OUTCOME_WEIGHTS.items()),
        2,
    )


def rank_profiles(profiles: list[dict]) -> list[dict]:
    """Rank profiles by score while preserving honest shared ranks for ties."""
    rows = [
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
            "universal_prospect_index": index_score(
                profile.get("outcome_distribution") or {}
            ),
        }
        for profile in profiles
    ]
    rows.sort(
        key=lambda row: (
            -row["universal_prospect_index"],
            str(row.get("role") or ""),
            int(row.get("mlbam_id") or 0),
        )
    )
    previous_score = None
    previous_rank = 0
    for position, row in enumerate(rows, 1):
        if row["universal_prospect_index"] != previous_score:
            previous_rank = position
            previous_score = row["universal_prospect_index"]
        row["universal_rank"] = previous_rank
    return rows


def _evidence_summary(
    backtest: dict | None,
    universal_version: str | None,
    generated_at: str | None,
) -> dict:
    if not backtest:
        return {
            "research_gate": "hold",
            "reason": "No historical Universal Prospect Index backtest is available.",
        }
    if backtest.get("universal_model_version") != universal_version:
        return {
            "research_gate": "hold",
            "reason": "Historical index evidence used a different universal model version.",
        }
    if backtest.get("generated_at") != generated_at:
        return {
            "research_gate": "hold",
            "reason": "Historical index evidence used a different factual input snapshot.",
        }
    promotion = backtest.get("promotion") or {}
    return {
        "research_gate": promotion.get("universal_index_research_gate", "hold"),
        "reason": promotion.get("reason"),
        "combined_fold_count": (backtest.get("combined") or {}).get("fold_count", 0),
        "role_distribution_prerequisite": promotion.get(
            "role_distribution_prerequisite", "hold"
        ),
    }


def build_index(universal: dict, backtest: dict | None = None) -> dict:
    board = rank_profiles(universal.get("profiles") or [])
    generated_at = (universal.get("input_contract") or {}).get("generated_at")
    evidence = _evidence_summary(backtest, universal.get("model_version"), generated_at)
    return {
        "status": "shadow_only",
        "index_name": INDEX_NAME,
        "index_version": INDEX_VERSION,
        "universal_model_name": universal.get("model_name"),
        "universal_model_version": universal.get("model_version"),
        "generated_at": generated_at,
        "candidate_count": len(board),
        "index_contract": {
            "purpose": (
                "Rank expected factual MLB outcomes across statistical prospects "
                "without fantasy-league or market context."
            ),
            "score_range": [0.0, 100.0],
            "outcome_weights": OUTCOME_WEIGHTS,
            "formula": (
                "0 * bust_probability + 50 * role_probability + "
                "100 * star_probability"
            ),
            "league_scoring_independent": True,
            "market_independent": True,
            "external_rankings_used": False,
            "fantasy_value": False,
            "uncertainty_penalty": False,
            "role_balance_adjustment": False,
            "cross_role_interpretation": (
                "Hitter and pitcher profiles share the same bust/role/star scale, "
                "but use role-specific factual thresholds; no role mix is forced."
            ),
            "tie_policy": "Equal index scores share the same universal rank.",
            "profile_identity": "MLBAM id plus statistical role",
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
            "feeds_live_valucast_rank": False,
            "feeds_live_dd_value": False,
        },
        "limitations": [
            "Shadow-only; this board is not consumed by a live ValuCast or DD surface.",
            "The index ranks expected factual MLB outcome tier, not career WAR or fantasy value.",
            "Hitter and pitcher star definitions are role-specific factual thresholds.",
            "Complex-league and rookie-ball prospects remain outside the statistical scope.",
            "No defensive, physical, international amateur investment, or scouting-report inputs.",
        ],
        "board": board,
    }


def archive_index(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "index_version": payload["index_version"],
        "universal_model_version": payload["universal_model_version"],
        "historical_evidence": payload["historical_evidence"],
        "candidate_count": payload["candidate_count"],
        "board": payload["board"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_index(
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
    payload = build_index(universal, backtest)
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
    archive_path, archive_changed = archive_index(
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
