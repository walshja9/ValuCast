"""ValuCast Prospect Peak Projection v1.

This is a card-facing projection layer, not a full statistical forecast. It
turns Prospect Rank v1's ValuCast-owned evidence into a projected peak role and
20-80-style skill shape. It never reads DD values, public ranks, market values,
or external scouting grades.
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
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_peak_projection_v1.json"

PROJECTION_VERSION = "1.0.0"
CARD_VISUAL_VERSION = "2.0.0"
PROJECTION_STATUS = "candidate_ready"
ARTIFACT_NAME = "valucast_prospect_peak_projection_v1"
MIN_TOP200_PROJECTION_COVERAGE = 0.90

SKILL_BAND_BONUS = {
    "impact": 4.0,
    "starter_volume": 3.6,
    "bat_missing": 2.4,
    "balanced": 1.2,
    "mixed": -0.6,
    "low_impact": -2.8,
    "limited": -3.2,
    "thin": -4.0,
}

LEVEL_ETA_HINTS = {
    "MLB": "now",
    "AAA": "near_term",
    "AA": "one_to_two_years",
    "A+": "two_to_three_years",
    "A": "two_to_three_years",
    "ROK": "long_range",
    "CPX": "long_range",
}


def _clean_float(raw: Any) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return value


def _round(value: Any, digits: int = 2) -> float | None:
    numeric = _clean_float(value)
    return round(numeric, digits) if numeric is not None else None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _scale(value: Any, low: float, high: float, *, lower_is_better: bool = False) -> float | None:
    numeric = _clean_float(value)
    if numeric is None:
        return None
    if high == low:
        return None
    ratio = (numeric - low) / (high - low)
    if lower_is_better:
        ratio = 1.0 - ratio
    return _clamp(20.0 + ratio * 60.0, 20.0, 80.0)


def _avg(values: list[float | None]) -> float | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable) / len(usable)


def _grade(value: float | None) -> int | None:
    if value is None:
        return None
    return int(round(_clamp(value, 20.0, 80.0) / 5.0) * 5)


def _components(row: dict) -> dict:
    value = row.get("components")
    return value if isinstance(value, dict) else {}


def _current_context(row: dict) -> dict:
    value = _components(row).get("factual_current_context")
    return value if isinstance(value, dict) else {}


def _availability(row: dict) -> dict:
    value = _components(row).get("availability")
    return value if isinstance(value, dict) else {}


def _reliability(row: dict) -> float:
    value = _clean_float(_components(row).get("sample_reliability"))
    return _clamp(value if value is not None else 35.0)


def _risk_discount(row: dict) -> float:
    value = _clean_float(_components(row).get("availability_risk_discount"))
    return _clamp(value if value is not None else 0.0, 0.0, 1.0)


def _investment_score(row: dict) -> float | None:
    value = _components(row).get("factual_investment_context")
    if isinstance(value, dict):
        for key in ("score", "draft_pick_score", "investment_score"):
            score = _clean_float(value.get(key))
            if score is not None:
                return _clamp(score)
        return None
    score = _clean_float(value)
    return _clamp(score) if score is not None else None


def _level(value: Any) -> str:
    text = str(value or "").upper()
    aliases = {
        "HIGH-A": "A+",
        "HIGH A": "A+",
        "HI-A": "A+",
        "SINGLE-A": "A",
        "LOW-A": "A",
        "LOW A": "A",
        "ROOKIE": "ROK",
        "COMPLEX": "CPX",
    }
    return aliases.get(text, text)


def _hitter_shape(current: dict, rank_score: float) -> list[dict]:
    fallback = _scale(rank_score, 25.0, 62.0)
    hit = _avg([
        _scale(current.get("k_pct"), 34.0, 11.0),
        _scale(current.get("ops"), 0.560, 0.930),
    ]) or fallback
    power = _avg([
        _scale(current.get("iso"), 0.070, 0.260),
        _scale(current.get("ops"), 0.600, 0.960),
    ]) or fallback
    approach = _avg([
        _scale(current.get("bb_pct"), 4.0, 16.0),
        _scale(current.get("bb_minus_k_pct"), -24.0, 6.0),
    ]) or fallback
    impact = _avg([
        _scale(current.get("ops"), 0.590, 0.970),
        _scale(current.get("iso"), 0.070, 0.260),
        _scale(rank_score, 25.0, 62.0),
    ]) or fallback
    return [
        {"label": "Hit", "grade": _grade(hit), "source": "K% / OPS"},
        {"label": "Power", "grade": _grade(power), "source": "ISO / OPS"},
        {"label": "Approach", "grade": _grade(approach), "source": "BB% / BB-K"},
        {"label": "Impact", "grade": _grade(impact), "source": "OPS / ISO / score"},
    ]


def _pitcher_shape(current: dict, rank_score: float) -> list[dict]:
    fallback = _scale(rank_score, 25.0, 62.0)
    miss = _scale(current.get("k_per_9"), 6.5, 13.2)
    command = _scale(current.get("bb_per_9"), 6.0, 1.2)
    dominance = _avg([
        _scale(current.get("k_bb_pct"), 4.0, 33.0),
        miss,
        command,
    ]) or fallback
    run_prevention = _avg([
        _scale(current.get("era"), 6.25, 2.20, lower_is_better=True),
        _scale(current.get("whip"), 1.75, 0.90, lower_is_better=True),
        _scale(rank_score, 25.0, 62.0),
    ]) or fallback
    return [
        {"label": "Miss", "grade": _grade(miss or fallback), "source": "K/9"},
        {"label": "Command", "grade": _grade(command or fallback), "source": "BB/9"},
        {"label": "Dominance", "grade": _grade(dominance), "source": "K-BB%"},
        {"label": "Run Prevention", "grade": _grade(run_prevention), "source": "ERA / WHIP"},
    ]


def _shape(row: dict, rank_score: float) -> list[dict]:
    current = _current_context(row)
    role = str(row.get("role") or "")
    shape = _pitcher_shape(current, rank_score) if role == "pitcher" else _hitter_shape(current, rank_score)
    return [item for item in shape if item.get("grade") is not None]


def _shape_average(shape: list[dict]) -> float:
    grades = [_clean_float(item.get("grade")) for item in shape]
    usable = [grade for grade in grades if grade is not None]
    return sum(usable) / len(usable) if usable else 45.0


def _risk_band(row: dict, shape_average: float) -> str:
    reliability = _reliability(row)
    discount = _risk_discount(row)
    status = str(_availability(row).get("status") or "").lower()
    source = str(row.get("score_source") or "")
    if status in {"injured", "unavailable"} or discount >= 0.08 or reliability < 35.0:
        return "high"
    if reliability < 55.0 or shape_average < 45.0 or source in {"universal_fallback", "identity_only_fallback"}:
        return "medium"
    return "low"


def _confidence(row: dict, risk_band: str) -> str:
    reliability = _reliability(row)
    current = _current_context(row)
    if risk_band == "high" or reliability < 35.0 or not current:
        return "low"
    if reliability >= 65.0 and risk_band == "low":
        return "high"
    return "medium"


def _peak_score(row: dict, shape_average: float) -> float:
    rank_score = _clean_float(row.get("score")) or 0.0
    reliability = _reliability(row)
    investment = _investment_score(row)
    skill_band = str(_current_context(row).get("skill_band") or "").lower()
    score = (
        0.58 * rank_score
        + 0.30 * shape_average
        + 0.08 * reliability
        + 0.04 * (investment if investment is not None else 45.0)
    )
    score += SKILL_BAND_BONUS.get(skill_band, 0.0)
    score -= _risk_discount(row) * 28.0
    return round(_clamp(score), 2)


def _ceiling_band(row: dict, peak_score: float) -> str:
    role = str(row.get("role") or "")
    if role == "pitcher":
        if peak_score >= 68.0:
            return "mid_rotation_or_better"
        if peak_score >= 58.0:
            return "rotation_starter"
        if peak_score >= 50.0:
            return "back_end_starter"
        if peak_score >= 42.0:
            return "multi_inning_or_setup_arm"
        return "depth_arm"
    if peak_score >= 68.0:
        return "impact_regular"
    if peak_score >= 58.0:
        return "everyday_regular"
    if peak_score >= 50.0:
        return "second_division_regular"
    if peak_score >= 42.0:
        return "bench_or_platoon_bat"
    return "organizational_depth"


def _floor_band(row: dict, risk_band: str, shape_average: float) -> str:
    role = str(row.get("role") or "")
    if role == "pitcher":
        if risk_band == "high":
            return "bullpen_or_depth"
        if shape_average >= 58.0:
            return "multi_inning_floor"
        return "depth_arm_floor"
    if risk_band == "high":
        return "org_depth_floor"
    if shape_average >= 58.0:
        return "reserve_floor"
    return "bench_or_depth_floor"


def _eta_window(row: dict) -> str:
    eta = row.get("eta")
    if eta not in (None, ""):
        return str(eta)
    return LEVEL_ETA_HINTS.get(_level(row.get("level")), "unknown")


def _summary(row: dict, peak_score: float, ceiling: str, risk: str) -> str:
    current = _current_context(row)
    sample = _round(current.get("sample"), 1)
    unit = str(current.get("sample_unit") or "")
    skill_band = str(current.get("skill_band") or "current evidence").replace("_", " ")
    role = "pitching" if row.get("role") == "pitcher" else "bat"
    sample_text = f"{sample:g} {unit}" if sample is not None and unit else "the current sample"
    return (
        f"Peak read: {ceiling.replace('_', ' ')} with {risk} risk. "
        f"The current {role} shape is {skill_band} over {sample_text}; "
        "this is a role and skill-shape projection, not a full stat forecast."
    )


def _role_probability(row: dict, peak_score: float, risk: str, shape_average: float) -> dict:
    """Small deterministic role distribution for card context.

    These are not calibrated scouting probabilities. They are a display layer
    that keeps the peak read from pretending to be a single-point answer.
    """
    role = str(row.get("role") or "")
    risk_penalty = {"low": 0.0, "medium": 0.10, "high": 0.20}.get(risk, 0.10)
    top = _clamp((peak_score - 45.0) / 35.0 - risk_penalty, 0.05, 0.70)
    floor = _clamp((52.0 - shape_average) / 40.0 + risk_penalty, 0.10, 0.70)
    middle = max(0.05, 1.0 - top - floor)
    total = top + middle + floor
    labels = (
        ("starter_or_late_inning", "useful_mlb_arm", "depth_or_relief")
        if role == "pitcher"
        else ("regular_or_better", "bench_or_platoon", "depth_or_reserve")
    )
    values = [top / total, middle / total, floor / total]
    return {
        label: round(value, 3)
        for label, value in zip(labels, values)
    }


def _card_v2_context(
    row: dict,
    *,
    rank_score: float,
    peak_score: float,
    ceiling: str,
    floor: str,
    risk: str,
    confidence: str,
    shape_average: float,
) -> dict:
    delta = round(peak_score - rank_score, 2)
    if delta >= 4.0:
        trend = "more_peak_than_current_value"
    elif delta <= -4.0:
        trend = "current_value_ahead_of_peak_read"
    else:
        trend = "current_and_peak_aligned"
    return {
        "visual_version": CARD_VISUAL_VERSION,
        "current_score": round(rank_score, 2),
        "peak_score": peak_score,
        "score_delta": delta,
        "trajectory": trend,
        "ceiling_band": ceiling,
        "floor_band": floor,
        "risk_band": risk,
        "confidence": confidence,
        "role_probabilities": _role_probability(row, peak_score, risk, shape_average),
        "card_copy": (
            f"Peak view: {ceiling.replace('_', ' ')}; floor is "
            f"{floor.replace('_', ' ')}. Risk is {risk}, confidence is {confidence}."
        ),
    }


def _projection_row(row: dict) -> dict:
    rank_score = _clean_float(row.get("score")) or 0.0
    shape = _shape(row, rank_score)
    shape_average = _shape_average(shape)
    peak_score = _peak_score(row, shape_average)
    risk = _risk_band(row, shape_average)
    ceiling = _ceiling_band(row, peak_score)
    floor = _floor_band(row, risk, shape_average)
    confidence = _confidence(row, risk)
    current = _current_context(row)
    availability = _availability(row)
    sample = _round(current.get("sample"), 1)
    card_v2 = _card_v2_context(
        row,
        rank_score=rank_score,
        peak_score=peak_score,
        ceiling=ceiling,
        floor=floor,
        risk=risk,
        confidence=confidence,
        shape_average=shape_average,
    )
    return {
        "mlbam_id": row.get("mlbam_id"),
        "name": row.get("name"),
        "role": row.get("role"),
        "level": row.get("level"),
        "age": row.get("age"),
        "rank_v1_rank": row.get("rank"),
        "rank_v1_score": _round(row.get("score")),
        "rank_v1_score_source": row.get("score_source"),
        "peak_score": peak_score,
        "peak_role": ceiling,
        "ceiling_band": ceiling,
        "floor_band": floor,
        "risk_band": risk,
        "confidence": confidence,
        "eta_window": _eta_window(row),
        "shape_average": round(shape_average, 2),
        "shape": shape,
        "card_v2": card_v2,
        "sample_context": {
            "sample": sample,
            "sample_unit": current.get("sample_unit"),
            "skill_band": current.get("skill_band"),
            "availability_status": availability.get("status"),
            "sample_reliability": _round(_reliability(row)),
            "availability_risk_discount": _round(_risk_discount(row), 4),
        },
        "summary": _summary(row, peak_score, ceiling, risk),
        "usage": "card_visual_context_not_live_rank_or_value",
    }


def _identity_key(row: dict) -> str | None:
    mlbam_id = row.get("mlbam_id")
    role = row.get("role")
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return f"{mlbam_id}_{role}"


def _validation(projections: list[dict], rank_payload: dict) -> dict:
    top200 = [row for row in (rank_payload.get("board") or []) if (row.get("rank") or 999999) <= 200]
    projected_keys = [_identity_key(row) for row in projections]
    top200_keys = {_identity_key(row) for row in top200}
    top200_keys.discard(None)
    covered = len(top200_keys & set(projected_keys))
    coverage = covered / len(top200_keys) if top200_keys else 0.0
    duplicate_count = len(projected_keys) - len(set(projected_keys))
    missing_shape_count = sum(1 for row in projections if len(row.get("shape") or []) < 4)
    missing_card_v2_count = sum(
        1
        for row in projections
        if (row.get("card_v2") or {}).get("visual_version") != CARD_VISUAL_VERSION
    )
    blockers = []
    if not projections:
        blockers.append("Peak projection artifact has no rows.")
    if coverage < MIN_TOP200_PROJECTION_COVERAGE:
        blockers.append("Top-200 peak projection coverage is below threshold.")
    if duplicate_count:
        blockers.append("Peak projection artifact has duplicate MLBAM+role identities.")
    if missing_shape_count:
        blockers.append("Some peak projection rows are missing shape grades.")
    if missing_card_v2_count:
        blockers.append("Some peak projection rows are missing Card V2 context.")
    return {
        "ready_for_card_v2": not blockers,
        "projection_count": len(projections),
        "top200_projection_coverage": round(coverage, 4),
        "min_top200_projection_coverage": MIN_TOP200_PROJECTION_COVERAGE,
        "duplicate_identity_count": duplicate_count,
        "missing_shape_count": missing_shape_count,
        "missing_card_v2_count": missing_card_v2_count,
        "blockers": blockers,
    }


def build_peak_projection(rank_payload: dict, generated_at: str | None = None) -> dict:
    generated_at = (
        generated_at
        or rank_payload.get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    projections = [
        _projection_row(row)
        for row in rank_payload.get("board") or []
        if _identity_key(row)
    ]
    validation = _validation(projections, rank_payload)
    return {
        "artifact": ARTIFACT_NAME,
        "projection_version": PROJECTION_VERSION,
        "status": PROJECTION_STATUS,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "projection_contract": {
            "projection_kind": "peak_role_and_skill_shape_not_full_stat_forecast",
            "card_visual_version": CARD_VISUAL_VERSION,
            "feeds_live_rank": False,
            "feeds_live_value": False,
            "score_mutation": "none",
            "card_visual_context": True,
        },
        "source_policy": {
            "kind": "valucast_owned_peak_projection",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
            "public_scouting_grades_used": False,
        },
        "input_artifacts": {
            "prospect_rank_v1_version": rank_payload.get("rank_version"),
            "prospect_rank_v1_status": rank_payload.get("status"),
            "prospect_rank_v1_generated_at": rank_payload.get("generated_at"),
        },
        "method": {
            "basis": (
                "Prospect Rank v1 score, factual current context, sample reliability, "
                "availability risk, and factual investment context."
            ),
            "non_goals": [
                "No HR/SB/ERA/WHIP stat forecast.",
                "No DD values or ranks.",
                "No public scouting grades.",
            ],
        },
        "validation": validation,
        "projections": projections,
    }


def run_peak_projection(
    rank_path: Path = RANK_V1_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    payload = build_peak_projection(rank_payload)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "ready_for_card_v2": payload["validation"]["ready_for_card_v2"],
        "projection_count": payload["validation"]["projection_count"],
        "top200_projection_coverage": payload["validation"]["top200_projection_coverage"],
    }
