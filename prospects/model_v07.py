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
OUTCOME_BACKTEST_PATH = (
    ROOT / "data" / "models" / "valucast_prospect_outcome_backtest.json"
)

MODEL_NAME = "ValuCast Prospect Model v0.7 Preview"
MODEL_VERSION = "0.7.0-preview.1"
MODEL_STATUS = "shadow_preview"
MIN_TOP200_FACTUAL_CONTEXT_COVERAGE = 0.95
MIN_TOP200_AVAILABILITY_COVERAGE = 0.95
MIN_BUCKET_COMPARISON_COUNT = 6


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


def _level_band(level: Any) -> str:
    value = str(level or "").upper()
    if value in {"AA", "AAA", "MLB"}:
        return "upper_level"
    if value in {"DSL", "CPX", "ROK", "A", "A+", "HIGH-A"}:
        return "lower_minors"
    return "unknown_level"


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


def _bucket_id(row: dict) -> str:
    return "|".join(
        [
            str(row.get("role") or "unknown_role"),
            _level_band(row.get("level")),
            str(row.get("score_source") or "unknown_source"),
            str((row.get("candidate_features") or {}).get("availability_status") or "missing_availability"),
        ]
    )


def _bucket_comparison(
    candidates: list[dict],
    outcome_backtest: dict | None,
) -> dict:
    top_rows = candidates[:200]
    buckets = {}
    for row in top_rows:
        bucket = _bucket_id(row)
        entry = buckets.setdefault(
            bucket,
            {
                "bucket": bucket,
                "count": 0,
                "avg_rank_v1_score": 0.0,
                "factual_context_covered": 0,
                "availability_context_covered": 0,
            },
        )
        entry["count"] += 1
        entry["avg_rank_v1_score"] += float(row.get("rank_v1_score") or 0.0)
        coverage = row.get("feature_coverage") or {}
        entry["factual_context_covered"] += int(
            coverage.get("factual_current_context") is True
        )
        entry["availability_context_covered"] += int(
            coverage.get("availability_context") is True
        )
    for entry in buckets.values():
        count = entry["count"] or 1
        entry["avg_rank_v1_score"] = round(entry["avg_rank_v1_score"] / count, 4)
        entry["factual_context_coverage"] = round(
            entry.pop("factual_context_covered") / count, 4
        )
        entry["availability_context_coverage"] = round(
            entry.pop("availability_context_covered") / count, 4
        )

    outcome_validation = (outcome_backtest or {}).get("validation") or {}
    ready = (
        bool(buckets)
        and len(buckets) >= MIN_BUCKET_COMPARISON_COUNT
        and outcome_validation.get("bucket_cohort_evidence_ready") is True
    )
    return {
        "status": "ready" if ready else "collecting",
        "comparison_kind": "v0_7_candidate_features_vs_rank_v1_v0_6_bucket_shape",
        "live_score_mutation": "none",
        "bucket_definition": "role|level_band|score_source|availability_status",
        "minimum_bucket_count": MIN_BUCKET_COMPARISON_COUNT,
        "bucket_count": len(buckets),
        "outcome_bucket_cohort_ready": outcome_validation.get(
            "bucket_cohort_evidence_ready"
        ),
        "buckets": sorted(
            buckets.values(), key=lambda item: (-item["count"], item["bucket"])
        ),
    }


def _coverage_rate(candidates: list[dict], key: str, limit: int) -> float:
    rows = candidates[:limit]
    if not rows:
        return 0.0
    covered = sum(1 for row in rows if row["feature_coverage"].get(key) is True)
    return round(covered / len(rows), 4)


def build_model_v07_preview(
    rank_payload: dict,
    outcome_backtest: dict | None = None,
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
    outcome_validation = (outcome_backtest or {}).get("validation") or {}
    outcome_track = (outcome_backtest or {}).get("front_office_track") or {}
    bucket_comparison = _bucket_comparison(candidates, outcome_backtest)
    if outcome_backtest and outcome_validation.get("realized_evidence_ready") is not True:
        blockers.append("Outcome evidence layer is not ready for v0.7 backtesting.")

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
            "requires_outcome_backtest": True,
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
            "outcome_backtest_version": (outcome_backtest or {}).get(
                "report_version"
            ),
            "outcome_backtest_grade": outcome_track.get("grade"),
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
            "bucket_comparison_ready": bucket_comparison["status"] == "ready",
            "blockers": blockers,
        },
        "bucket_comparison": bucket_comparison,
        "outcome_evidence": {
            "present": bool(outcome_backtest),
            "front_office_track": outcome_track or None,
            "realized_evidence_ready": outcome_validation.get(
                "realized_evidence_ready"
            ),
            "forward_evidence_ready": outcome_validation.get(
                "forward_evidence_ready"
            ),
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
    outcome_backtest_path: Path | None = OUTCOME_BACKTEST_PATH,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    outcome_backtest = (
        json.loads(outcome_backtest_path.read_text(encoding="utf-8"))
        if outcome_backtest_path is not None and outcome_backtest_path.exists()
        else None
    )
    payload = build_model_v07_preview(
        rank_payload,
        outcome_backtest=outcome_backtest,
    )
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
