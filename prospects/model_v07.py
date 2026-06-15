"""Shadow preview for the next ValuCast prospect model.

This artifact does not replace Prospect Model v0.6 or mutate Prospect Rank v1.
It packages the factual-current context that v0.7 should learn from, then
validates whether the live board has enough coverage to start backtesting.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_model_v0_7.json"

MODEL_NAME = "ValuCast Prospect Model v0.7 Preview"
MODEL_VERSION = "0.7.0-preview.1"
MODEL_STATUS = "shadow_preview"
MIN_TOP200_FACTUAL_CONTEXT_COVERAGE = 0.95
MIN_TOP200_AVAILABILITY_COVERAGE = 0.95


def _clean_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, 4)


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _components(row: dict) -> dict:
    components = row.get("components")
    return components if isinstance(components, dict) else {}


def _context(components: dict, key: str) -> dict:
    value = components.get(key)
    return value if isinstance(value, dict) else {}


def _availability_status(components: dict) -> str | None:
    availability = _context(components, "availability")
    status = availability.get("status")
    return str(status) if status not in (None, "") else None


def _feature_coverage(components: dict) -> dict:
    return {
        "factual_current_context": bool(_context(components, "factual_current_context")),
        "availability_context": bool(_context(components, "availability")),
        "factual_investment_context": bool(
            _context(components, "factual_investment_context")
        ),
        "sample_reliability": components.get("sample_reliability") is not None,
        "bucket_calibration": bool(_context(components, "bucket_calibration")),
    }


def _candidate_features(row: dict) -> dict:
    components = _components(row)
    current = _context(components, "factual_current_context")
    investment = _context(components, "factual_investment_context")
    age_level = _context(components, "age_level_context")
    bucket = _context(components, "bucket_calibration")
    role = row.get("role")

    features = {
        "current_sample": _clean_float(current.get("sample")),
        "current_sample_unit": current.get("sample_unit"),
        "current_skill_band": current.get("skill_band"),
        "factual_investment_context": investment or None,
        "sample_reliability": _clean_float(components.get("sample_reliability")),
        "availability_status": _availability_status(components),
        "availability_risk_discount": _clean_float(
            components.get("availability_risk_discount")
        ),
        "age_level_context": age_level or None,
        "bucket_calibration": bucket or None,
    }
    if role == "hitter":
        features.update(
            {
                "ops": _clean_float(current.get("ops")),
                "iso": _clean_float(current.get("iso")),
                "bb_minus_k_pct": _clean_float(current.get("bb_minus_k_pct")),
            }
        )
    elif role == "pitcher":
        features.update(
            {
                "k_bb_pct": _clean_float(current.get("k_bb_pct")),
                "k_per_9": _clean_float(current.get("k_per_9")),
                "bb_per_9": _clean_float(current.get("bb_per_9")),
                "starter_role": current.get("starter_role"),
            }
        )
    return features


def _feature_row(row: dict) -> dict:
    components = _components(row)
    return {
        "mlbam_id": row.get("mlbam_id"),
        "name": row.get("name"),
        "role": row.get("role"),
        "level": row.get("level"),
        "rank_v1_rank": row.get("rank"),
        "rank_v1_score": _clean_float(row.get("score")),
        "score_source": row.get("score_source"),
        "candidate_features": _candidate_features(row),
        "feature_coverage": _feature_coverage(components),
    }


def _coverage_rate(candidates: list[dict], key: str, limit: int) -> float:
    rows = candidates[:limit]
    if not rows:
        return 0.0
    covered = sum(1 for row in rows if row["feature_coverage"].get(key) is True)
    return round(covered / len(rows), 4)


def build_model_v07_preview(
    rank_payload: dict,
    generated_at: str | None = None,
) -> dict:
    generated = generated_at or rank_payload.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    candidates = [_feature_row(row) for row in rank_payload.get("board") or []]
    top_limit = min(200, len(candidates))
    factual_coverage = _coverage_rate(candidates, "factual_current_context", top_limit)
    availability_coverage = _coverage_rate(candidates, "availability_context", top_limit)
    blockers = []
    if factual_coverage < MIN_TOP200_FACTUAL_CONTEXT_COVERAGE:
        blockers.append("Top-200 factual-current context coverage is below threshold.")
    if availability_coverage < MIN_TOP200_AVAILABILITY_COVERAGE:
        blockers.append("Top-200 availability context coverage is below threshold.")

    return {
        "artifact": "valucast_prospect_model_v0_7_preview",
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "status": MODEL_STATUS,
        "generated_at": generated,
        "as_of": _date_part(generated),
        "source_policy": {
            "kind": "valucast_shadow_prospect_model_preview",
            "rank_source": "valucast_prospect_rank_v1_components",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
            "feeds_live_rank": False,
            "feeds_live_value": False,
        },
        "model_contract": {
            "replaces_v0_6": False,
            "feeds_live_valucast_rank": False,
            "score_mutation": "none",
            "purpose": "Feature-readiness preview for Prospect Model v0.7.",
        },
        "feature_families": {
            "current_performance": [
                "current_sample",
                "current_skill_band",
                "ops",
                "iso",
                "bb_minus_k_pct",
                "k_bb_pct",
                "k_per_9",
                "bb_per_9",
                "starter_role",
            ],
            "pedigree_and_context": [
                "factual_investment_context",
                "sample_reliability",
                "availability_status",
                "availability_risk_discount",
                "age_level_context",
                "bucket_calibration",
            ],
        },
        "input_artifacts": {
            "prospect_rank_v1_version": rank_payload.get("rank_version"),
            "prospect_rank_v1_status": rank_payload.get("status"),
            "ranked_count": rank_payload.get("ranked_count")
            or len(rank_payload.get("board") or []),
        },
        "validation": {
            "ready_for_backtest": not blockers,
            "candidate_count": len(candidates),
            "top_n": top_limit,
            "top200_factual_context_coverage": factual_coverage,
            "top200_availability_coverage": availability_coverage,
            "min_top200_factual_context_coverage": (
                MIN_TOP200_FACTUAL_CONTEXT_COVERAGE
            ),
            "min_top200_availability_coverage": MIN_TOP200_AVAILABILITY_COVERAGE,
            "blockers": blockers,
        },
        "candidates": candidates,
    }


def write_model_v07_preview(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_model_v07_preview(
    rank_path: Path = RANK_V1_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    payload = build_model_v07_preview(rank_payload)
    path = write_model_v07_preview(payload, artifact_path)
    validation = payload["validation"]
    return {
        "artifact_path": str(path),
        "ready_for_backtest": validation["ready_for_backtest"],
        "candidate_count": validation["candidate_count"],
        "top200_factual_context_coverage": validation[
            "top200_factual_context_coverage"
        ],
    }
