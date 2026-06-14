"""Prospect Rank v1 calibration report.

This report is observe-only. It summarizes top-board shape and review
watchlists, but it does not feed model scoring or public eligibility.
"""
from __future__ import annotations

import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH
from prospects.rank_v1 import PEDIGREE_SCORE_SOURCE

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_calibration_report.json"

REPORT_NAME = "ValuCast Prospect Rank v1 Calibration Report"
REPORT_VERSION = "0.1.0"

V06_SCORE_SOURCE = "prospect_model_v0_6"
FALLBACK_SCORE_SOURCES = {"universal_fallback", "identity_only_fallback"}
TOP_BANDS = (25, 50, 100, 200)
TOP_CONTEXT_BAND = 50
CONTEXT_DISAGREEMENT_MIN_RANK_GAP = 30

MAX_TOP25_PITCHER_COUNT = 7
MAX_TOP50_PITCHER_RATE = 0.30
MAX_TOP25_PEDIGREE_COUNT = 8
MAX_TOP50_PEDIGREE_RATE = 0.35
MAX_TOP50_FALLBACK_RATE = 0.10
MAX_TOP50_AVAILABILITY_ADJUSTED_RATE = 0.25
MAX_TOP50_THIN_SAMPLE_COUNT = 12


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


def _round(value: float | None, digits: int = 4) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _components(row: dict) -> dict:
    components = row.get("components")
    return components if isinstance(components, dict) else {}


def _context(row: dict) -> dict:
    context = row.get("context_only")
    return context if isinstance(context, dict) else {}


def _availability(row: dict) -> dict:
    availability = _components(row).get("availability")
    return availability if isinstance(availability, dict) else {}


def _score_source(row: dict) -> str:
    return str(row.get("score_source") or "")


def _role(row: dict) -> str:
    role = str(row.get("role") or "").strip().lower()
    return role if role in {"hitter", "pitcher"} else "unknown"


def _level(row: dict) -> str:
    return str(row.get("level") or "unknown").strip().upper() or "unknown"


def _score(row: dict) -> float | None:
    return _clean_float(row.get("score"))


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _availability_adjusted(row: dict) -> bool:
    components = _components(row)
    if components.get("availability_adjusted") is True:
        return True
    discount = _clean_float(components.get("availability_risk_discount"))
    return bool(discount and discount > 0)


def _availability_status(row: dict) -> str:
    return str(_availability(row).get("status") or "missing")


def _entry(row: dict, *, include_context: bool = True) -> dict:
    components = _components(row)
    availability = _availability(row)
    context = _context(row)
    entry = {
        "rank": row.get("rank"),
        "name": row.get("name"),
        "mlbam_id": row.get("mlbam_id"),
        "role": row.get("role"),
        "positions": row.get("positions") or [],
        "mlb_team": row.get("mlb_team"),
        "age": row.get("age"),
        "level": row.get("level"),
        "score": row.get("score"),
        "score_source": row.get("score_source"),
        "confidence": row.get("confidence"),
        "model_score": components.get("model_score"),
        "sample_reliability": components.get("sample_reliability"),
        "availability_status": availability.get("status"),
        "availability_risk_level": availability.get("risk_level"),
        "availability_risk_discount": components.get("availability_risk_discount"),
        "availability_signals": availability.get("signals") or [],
        "sample": availability.get("sample"),
        "sample_unit": availability.get("sample_unit"),
    }
    if include_context:
        dd_rank = _clean_int(context.get("dd_prospect_rank"))
        rank = _clean_int(row.get("rank"))
        entry["dd_prospect_rank_context"] = dd_rank
        entry["dd_rank_gap_context"] = (
            None if dd_rank is None or rank is None else dd_rank - rank
        )
        entry["source_ranks_context"] = context.get("source_ranks")
    return entry


def _score_source_counts(rows: list[dict]) -> dict:
    counts = Counter(_score_source(row) or "unknown" for row in rows)
    return {key: counts[key] for key in sorted(counts)}


def _availability_counts(rows: list[dict]) -> dict:
    counts = Counter(_availability_status(row) for row in rows)
    return {key: counts[key] for key in sorted(counts)}


def _band_metrics(rows: list[dict], top_n: int) -> dict:
    band = rows[:top_n]
    scores = [score for row in band if (score := _score(row)) is not None]
    pitcher_count = sum(1 for row in band if _role(row) == "pitcher")
    pedigree_count = sum(1 for row in band if _score_source(row) == PEDIGREE_SCORE_SOURCE)
    fallback_count = sum(
        1 for row in band if _score_source(row) in FALLBACK_SCORE_SOURCES
    )
    availability_adjusted_count = sum(1 for row in band if _availability_adjusted(row))
    thin_sample_count = sum(
        1
        for row in band
        if _availability_status(row) == "thin_current_sample"
    )
    max_discount = max(
        (
            _clean_float(_components(row).get("availability_risk_discount")) or 0.0
            for row in band
        ),
        default=0.0,
    )
    return {
        "top_n": top_n,
        "evaluated_count": len(band),
        "score_min": _round(min(scores), 2) if scores else None,
        "score_max": _round(max(scores), 2) if scores else None,
        "score_average": _average(scores),
        "role_counts": {
            "hitter": sum(1 for row in band if _role(row) == "hitter"),
            "pitcher": pitcher_count,
            "unknown": sum(1 for row in band if _role(row) == "unknown"),
        },
        "pitcher_rate": _rate(pitcher_count, len(band)),
        "level_counts": {
            key: Counter(_level(row) for row in band)[key]
            for key in sorted(Counter(_level(row) for row in band))
        },
        "score_source_counts": _score_source_counts(band),
        "pedigree_count": pedigree_count,
        "pedigree_rate": _rate(pedigree_count, len(band)),
        "fallback_count": fallback_count,
        "fallback_rate": _rate(fallback_count, len(band)),
        "availability_status_counts": _availability_counts(band),
        "availability_adjusted_count": availability_adjusted_count,
        "availability_adjusted_rate": _rate(availability_adjusted_count, len(band)),
        "thin_current_sample_count": thin_sample_count,
        "max_availability_risk_discount": round(max_discount, 4),
    }


def _rank_gap(row: dict) -> int | None:
    rank = _clean_int(row.get("rank"))
    dd_rank = _clean_int(_context(row).get("dd_prospect_rank"))
    if rank is None or dd_rank is None:
        return None
    return dd_rank - rank


def _context_disagreements(rows: list[dict]) -> list[dict]:
    disagreements = []
    for row in rows[:TOP_CONTEXT_BAND]:
        gap = _rank_gap(row)
        if gap is None or abs(gap) < CONTEXT_DISAGREEMENT_MIN_RANK_GAP:
            continue
        entry = _entry(row)
        entry["disagreement_direction"] = (
            "valucast_higher" if gap > 0 else "dd_context_higher"
        )
        disagreements.append(entry)
    disagreements.sort(
        key=lambda row: (
            -abs(int(row.get("dd_rank_gap_context") or 0)),
            _clean_int(row.get("rank")) or 999999,
            str(row.get("name") or ""),
        )
    )
    return disagreements


def _tuning_flags(bands: dict[int, dict]) -> list[dict]:
    flags = []
    top25 = bands[25]
    top50 = bands[50]
    if top25["role_counts"]["pitcher"] > MAX_TOP25_PITCHER_COUNT:
        flags.append(
            {
                "id": "top25_pitcher_crowding",
                "severity": "review",
                "message": "Top-25 prospect board is pitcher-heavy.",
                "actual": top25["role_counts"]["pitcher"],
                "threshold": MAX_TOP25_PITCHER_COUNT,
            }
        )
    if top50["pitcher_rate"] > MAX_TOP50_PITCHER_RATE:
        flags.append(
            {
                "id": "top50_pitcher_rate",
                "severity": "review",
                "message": "Top-50 prospect board is pitcher-heavy.",
                "actual": top50["pitcher_rate"],
                "threshold": MAX_TOP50_PITCHER_RATE,
            }
        )
    if top25["pedigree_count"] > MAX_TOP25_PEDIGREE_COUNT:
        flags.append(
            {
                "id": "top25_pedigree_crowding",
                "severity": "review",
                "message": "Top-25 contains too many pedigree-only profiles.",
                "actual": top25["pedigree_count"],
                "threshold": MAX_TOP25_PEDIGREE_COUNT,
            }
        )
    if top50["pedigree_rate"] > MAX_TOP50_PEDIGREE_RATE:
        flags.append(
            {
                "id": "top50_pedigree_rate",
                "severity": "review",
                "message": "Top-50 contains too many pedigree-only profiles.",
                "actual": top50["pedigree_rate"],
                "threshold": MAX_TOP50_PEDIGREE_RATE,
            }
        )
    if top50["fallback_rate"] > MAX_TOP50_FALLBACK_RATE:
        flags.append(
            {
                "id": "top50_raw_fallback_rate",
                "severity": "repair",
                "message": "Top-50 contains too many raw fallback profiles.",
                "actual": top50["fallback_rate"],
                "threshold": MAX_TOP50_FALLBACK_RATE,
            }
        )
    if top50["availability_adjusted_rate"] > MAX_TOP50_AVAILABILITY_ADJUSTED_RATE:
        flags.append(
            {
                "id": "top50_availability_adjusted_rate",
                "severity": "review",
                "message": "Top-50 has unusually broad availability discounts.",
                "actual": top50["availability_adjusted_rate"],
                "threshold": MAX_TOP50_AVAILABILITY_ADJUSTED_RATE,
            }
        )
    if top50["thin_current_sample_count"] > MAX_TOP50_THIN_SAMPLE_COUNT:
        flags.append(
            {
                "id": "top50_thin_current_sample_count",
                "severity": "review",
                "message": "Top-50 has too many thin-current-sample profiles.",
                "actual": top50["thin_current_sample_count"],
                "threshold": MAX_TOP50_THIN_SAMPLE_COUNT,
            }
        )
    return flags


def _recommendations(flags: list[dict], disagreements: list[dict]) -> list[str]:
    recommendations = []
    ids = {flag["id"] for flag in flags}
    if "top25_pitcher_crowding" in ids or "top50_pitcher_rate" in ids:
        recommendations.append(
            "Review pitcher outcome weighting and availability gates before the next public prospect pass."
        )
    if "top25_pedigree_crowding" in ids or "top50_pedigree_rate" in ids:
        recommendations.append(
            "Expand lower-minors factual model coverage so pedigree-only scores do not carry too much top-board weight."
        )
    if "top50_raw_fallback_rate" in ids:
        recommendations.append(
            "Repair raw fallback coverage for top-50 profiles before treating the board as publication-grade."
        )
    if "top50_availability_adjusted_rate" in ids or "top50_thin_current_sample_count" in ids:
        recommendations.append(
            "Audit current-season sample thresholds; many top prospects are being priced down for limited current evidence."
        )
    if disagreements:
        recommendations.append(
            "Review the largest DD-context disagreements as questions, not scoring inputs."
        )
    if not recommendations:
        recommendations.append(
            "No broad calibration defect tripped the current thresholds; review watchlists before hand-tuning names."
        )
    return recommendations


def build_prospect_calibration_report(rank_payload: dict) -> dict:
    rows = list(rank_payload.get("board") or [])
    rows.sort(key=lambda row: _clean_int(row.get("rank")) or 999999)
    bands = {top_n: _band_metrics(rows, top_n) for top_n in TOP_BANDS}
    flags = _tuning_flags(bands)
    disagreements = _context_disagreements(rows)
    top50 = rows[:50]
    availability_watchlist = [
        _entry(row)
        for row in top50
        if _availability_adjusted(row)
    ]
    pedigree_watchlist = [
        _entry(row)
        for row in top50
        if _score_source(row) == PEDIGREE_SCORE_SOURCE
    ]
    fallback_watchlist = [
        _entry(row)
        for row in rows[:200]
        if _score_source(row) in FALLBACK_SCORE_SOURCES
    ]
    status = "needs_review" if flags else "review_ready"
    return {
        "artifact": "valucast_prospect_calibration_report",
        "report_name": REPORT_NAME,
        "report_version": REPORT_VERSION,
        "generated_at": rank_payload.get("generated_at")
        or datetime.now(timezone.utc).isoformat(),
        "status": status,
        "input_artifacts": {
            "rank_name": rank_payload.get("rank_name"),
            "rank_version": rank_payload.get("rank_version"),
            "rank_generated_at": rank_payload.get("generated_at"),
            "prospect_model_version": (rank_payload.get("input_artifacts") or {}).get(
                "prospect_model_version"
            ),
            "prospect_availability_version": (
                rank_payload.get("input_artifacts") or {}
            ).get("prospect_availability_version"),
        },
        "source_policy": {
            "kind": "observe_only_calibration_report",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "dd_values_used_for_model_score": False,
            "dd_ranks_used_for_model_score": False,
            "external_rankings_used_for_model_score": False,
            "dd_and_public_ranks_used_as_context_only": True,
        },
        "criteria": {
            "top_bands": list(TOP_BANDS),
            "top_context_band": TOP_CONTEXT_BAND,
            "context_disagreement_min_rank_gap": CONTEXT_DISAGREEMENT_MIN_RANK_GAP,
            "max_top25_pitcher_count": MAX_TOP25_PITCHER_COUNT,
            "max_top50_pitcher_rate": MAX_TOP50_PITCHER_RATE,
            "max_top25_pedigree_count": MAX_TOP25_PEDIGREE_COUNT,
            "max_top50_pedigree_rate": MAX_TOP50_PEDIGREE_RATE,
            "max_top50_fallback_rate": MAX_TOP50_FALLBACK_RATE,
            "max_top50_availability_adjusted_rate": MAX_TOP50_AVAILABILITY_ADJUSTED_RATE,
            "max_top50_thin_sample_count": MAX_TOP50_THIN_SAMPLE_COUNT,
        },
        "metrics": {
            "row_count": len(rows),
            "bands": {str(top_n): bands[top_n] for top_n in TOP_BANDS},
            "tuning_flag_count": len(flags),
            "context_disagreement_count_top50": len(disagreements),
            "availability_watchlist_count_top50": len(availability_watchlist),
            "pedigree_watchlist_count_top50": len(pedigree_watchlist),
            "fallback_watchlist_count_top200": len(fallback_watchlist),
        },
        "tuning_flags": flags,
        "recommendations": _recommendations(flags, disagreements),
        "watchlists": {
            "top50_availability_adjusted": availability_watchlist[:25],
            "top50_pedigree_only": pedigree_watchlist[:25],
            "top200_raw_fallback": fallback_watchlist[:50],
            "top50_dd_context_disagreements": disagreements[:25],
        },
    }


def write_prospect_calibration_report(
    payload: dict,
    path: Path = ARTIFACT_PATH,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_prospect_calibration_report(
    rank_path: Path = RANK_V1_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    payload = build_prospect_calibration_report(rank_payload)
    path = write_prospect_calibration_report(payload, artifact_path)
    metrics = payload.get("metrics") or {}
    return {
        "artifact_path": str(path),
        "status": payload["status"],
        "row_count": metrics.get("row_count"),
        "tuning_flag_count": metrics.get("tuning_flag_count"),
        "availability_watchlist_count_top50": metrics.get(
            "availability_watchlist_count_top50"
        ),
        "context_disagreement_count_top50": metrics.get(
            "context_disagreement_count_top50"
        ),
    }
