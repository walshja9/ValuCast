"""Audit Prospect Rank v1 coverage gaps before public promotion."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH
from prospects.rank_v1 import PEDIGREE_SCORE_SOURCE

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"

AUDIT_NAME = "ValuCast Prospect Coverage Audit"
AUDIT_VERSION = "0.1.0"

V06_SCORE_SOURCE = "prospect_model_v0_6"
RAW_FALLBACK_SCORE_SOURCES = {"universal_fallback", "identity_only_fallback"}
ELITE_FACTUAL_INVESTMENT_MIN = 90.0
CONTEXT_TOP_PROSPECT_RANK_MAX = 30
CONTEXT_SOURCE_RANK_MAX = 30
TOP_N = 200


def _clean_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _components(row: dict) -> dict:
    return row.get("components") if isinstance(row.get("components"), dict) else {}


def _context(row: dict) -> dict:
    return row.get("context_only") if isinstance(row.get("context_only"), dict) else {}


def _source_rank_min(row: dict) -> int | None:
    source_ranks = _context(row).get("source_ranks")
    if not isinstance(source_ranks, dict):
        return None
    values = [
        rank
        for value in source_ranks.values()
        if (rank := _clean_int(value)) is not None and rank > 0
    ]
    return min(values) if values else None


def _score_source(row: dict) -> str:
    return str(row.get("score_source") or "")


def _is_raw_fallback(row: dict) -> bool:
    return _score_source(row) in RAW_FALLBACK_SCORE_SOURCES


def _factual_investment(row: dict) -> float | None:
    return _clean_float(_components(row).get("factual_investment_context"))


def _dd_prospect_rank(row: dict) -> int | None:
    return _clean_int(_context(row).get("dd_prospect_rank"))


def _miss_reasons(row: dict) -> list[str]:
    reasons = []
    if _score_source(row) != V06_SCORE_SOURCE:
        reasons.append("missing_v0_6_model_profile")
    if _is_raw_fallback(row):
        reasons.append("raw_fallback_score_source")
    if (_factual_investment(row) or 0.0) >= ELITE_FACTUAL_INVESTMENT_MIN:
        reasons.append("elite_factual_draft_signing_context")
    dd_rank = _dd_prospect_rank(row)
    if dd_rank is not None and dd_rank <= CONTEXT_TOP_PROSPECT_RANK_MAX:
        reasons.append("context_dd_top_prospect")
    source_rank = _source_rank_min(row)
    if source_rank is not None and source_rank <= CONTEXT_SOURCE_RANK_MAX:
        reasons.append("context_public_source_top_prospect")
    if (_clean_int(row.get("rank")) or 999999) <= TOP_N:
        reasons.append("top_200_valucast_board")
    return reasons


def _entry(row: dict) -> dict:
    context = _context(row)
    components = _components(row)
    return {
        "rank": row.get("rank"),
        "name": row.get("name"),
        "mlbam_id": row.get("mlbam_id"),
        "role": row.get("role"),
        "positions": row.get("positions") or [],
        "mlb_team": row.get("mlb_team"),
        "age": row.get("age"),
        "level": row.get("level"),
        "eta": row.get("eta"),
        "score": row.get("score"),
        "score_source": row.get("score_source"),
        "confidence": row.get("confidence"),
        "model_score": components.get("model_score"),
        "universal_outcome_index": components.get("universal_outcome_index"),
        "factual_investment_context": components.get("factual_investment_context"),
        "sample_reliability": components.get("sample_reliability"),
        "pedigree_score_cap": components.get("pedigree_score_cap"),
        "dd_prospect_rank_context": context.get("dd_prospect_rank"),
        "dd_dynasty_rank_context": context.get("dd_dynasty_rank"),
        "source_ranks_context": context.get("source_ranks"),
        "reasons": _miss_reasons(row),
    }


def _sort_key(row: dict) -> tuple[int, float, str]:
    rank = _clean_int(row.get("rank")) or 999999
    investment = _factual_investment(row) or 0.0
    return rank, -investment, str(row.get("name") or "")


def build_prospect_coverage_audit(rank_payload: dict) -> dict:
    rows = list(rank_payload.get("board") or [])
    top_rows = rows[:TOP_N]
    raw_fallback_rows = [row for row in rows if _is_raw_fallback(row)]
    top_raw_fallback_rows = [row for row in top_rows if _is_raw_fallback(row)]
    pedigree_rows = [
        row for row in rows if _score_source(row) == PEDIGREE_SCORE_SOURCE
    ]
    non_v06_rows = [row for row in rows if _score_source(row) != V06_SCORE_SOURCE]
    elite_factual_fallback_rows = [
        row
        for row in raw_fallback_rows
        if (_factual_investment(row) or 0.0) >= ELITE_FACTUAL_INVESTMENT_MIN
    ]
    elite_factual_fallback_top_rows = [
        row
        for row in elite_factual_fallback_rows
        if (_clean_int(row.get("rank")) or 999999) <= TOP_N
    ]
    context_watchlist_rows = [
        row
        for row in raw_fallback_rows
        if (
            (_dd_prospect_rank(row) is not None and _dd_prospect_rank(row) <= CONTEXT_TOP_PROSPECT_RANK_MAX)
            or (_source_rank_min(row) is not None and _source_rank_min(row) <= CONTEXT_SOURCE_RANK_MAX)
        )
    ]
    blockers = []
    if elite_factual_fallback_top_rows:
        blockers.append(
            "Elite factual draft/signing prospects remain on raw fallback scoring inside the top-200 review band."
        )

    return {
        "artifact": "valucast_prospect_coverage_audit",
        "audit_name": AUDIT_NAME,
        "audit_version": AUDIT_VERSION,
        "generated_at": rank_payload.get("generated_at")
        or datetime.now(timezone.utc).isoformat(),
        "status": "blocked" if blockers else "candidate_ready",
        "input_artifacts": {
            "rank_name": rank_payload.get("rank_name"),
            "rank_version": rank_payload.get("rank_version"),
            "rank_generated_at": rank_payload.get("generated_at"),
            "prospect_model_version": (rank_payload.get("input_artifacts") or {}).get(
                "prospect_model_version"
            ),
        },
        "source_policy": {
            "kind": "coverage_quality_audit",
            "feeds_model_score": False,
            "dd_values_used_for_model_score": False,
            "dd_ranks_used_for_model_score": False,
            "external_rankings_used_for_model_score": False,
            "dd_and_public_ranks_used_as_context_only": True,
        },
        "criteria": {
            "top_n": TOP_N,
            "v06_score_source": V06_SCORE_SOURCE,
            "pedigree_score_source": PEDIGREE_SCORE_SOURCE,
            "raw_fallback_score_sources": sorted(RAW_FALLBACK_SCORE_SOURCES),
            "elite_factual_investment_min": ELITE_FACTUAL_INVESTMENT_MIN,
            "context_top_prospect_rank_max": CONTEXT_TOP_PROSPECT_RANK_MAX,
            "context_source_rank_max": CONTEXT_SOURCE_RANK_MAX,
        },
        "metrics": {
            "row_count": len(rows),
            "v06_model_score_count": sum(
                1 for row in rows if _score_source(row) == V06_SCORE_SOURCE
            ),
            "pedigree_v0_7_score_count": len(pedigree_rows),
            "non_v06_score_count": len(non_v06_rows),
            "raw_fallback_count": len(raw_fallback_rows),
            "raw_fallback_top_50_count": sum(
                1 for row in rows[:50] if _is_raw_fallback(row)
            ),
            "raw_fallback_top_200_count": len(top_raw_fallback_rows),
            "elite_factual_raw_fallback_count": len(elite_factual_fallback_rows),
            "elite_factual_raw_fallback_top_200_count": len(
                elite_factual_fallback_top_rows
            ),
            "context_watchlist_raw_fallback_count": len(context_watchlist_rows),
        },
        "blockers": blockers,
        "elite_factual_raw_fallback_misses": [
            _entry(row) for row in sorted(elite_factual_fallback_rows, key=_sort_key)[:50]
        ],
        "context_watchlist_raw_fallback_misses": [
            _entry(row) for row in sorted(context_watchlist_rows, key=_sort_key)[:50]
        ],
        "top_200_raw_fallback_rows": [
            _entry(row) for row in sorted(top_raw_fallback_rows, key=_sort_key)[:75]
        ],
        "top_200_non_v06_rows": [
            _entry(row)
            for row in sorted(
                [row for row in top_rows if _score_source(row) != V06_SCORE_SOURCE],
                key=_sort_key,
            )[:75]
        ],
    }


def write_prospect_coverage_audit(
    payload: dict,
    path: Path = ARTIFACT_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_prospect_coverage_audit(
    rank_path: Path = RANK_V1_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    payload = build_prospect_coverage_audit(rank_payload)
    path = write_prospect_coverage_audit(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "row_count": payload["metrics"]["row_count"],
        "raw_fallback_top_200_count": payload["metrics"]["raw_fallback_top_200_count"],
        "elite_factual_raw_fallback_top_200_count": payload["metrics"][
            "elite_factual_raw_fallback_top_200_count"
        ],
        "blocker_count": len(payload["blockers"]),
    }
