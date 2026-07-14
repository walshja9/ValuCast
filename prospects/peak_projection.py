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

from prospects.availability import LEVEL_ETA_HINTS
from prospects.availability import eta_window
from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_peak_projection_v1.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_peak_projection_v1"

PROJECTION_VERSION = "1.0.0"
CARD_VISUAL_VERSION = "2.0.0"
# Peak model v2 (shadow, observe-only): folds the now-owned MiLB translation +
# best-single-level line into the shape, and replaces the invented role-probability
# split with the prospect model's real dynasty_signal distribution. Lives alongside
# v1 in the same artifact for A/B review; does NOT feed the card until promoted.
PEAK_V2_VERSION = "2.1.0"
PROJECTION_STATUS = "candidate_ready"
ARTIFACT_NAME = "valucast_prospect_peak_projection_v1"
MIN_TOP200_PROJECTION_COVERAGE = 0.90

# --- Run Prevention semantic sentinel -------------------------------------
# Run Prevention is graded so that LOW ERA/WHIP -> HIGH grade. A past
# double-negation bug inverted this (a 7.11 ERA graded 80, a 1.0 ERA graded 20)
# and still PASSED schema/coverage validation, shipping a stale artifact.
# These checks assert the *semantics* of the grade against the raw ERA the
# grade was built from, so an inverted/stale grade fails the build loudly.
#
# Healthy data: corr(ERA, RunPrevention) ~ -0.63, violation rate 0%.
# Inverted data: corr ~ +0.63, violation rate ~50%.
# Thresholds are deliberately conservative so they only fire on unambiguous
# inversion, never on healthy noise.
RUN_PREVENTION_LABEL = "Run Prevention"
RUN_PREVENTION_MAX_CORR = -0.20  # corr above this (near-zero/positive) = inverted
RUN_PREVENTION_MAX_VIOLATION_RATE = 0.05
RUN_PREVENTION_MIN_PITCHERS = 12  # too few graded ERAs to trust the correlation
RUN_PREVENTION_LOW_ERA = 3.00  # at/below this, grade must NOT be < 40
RUN_PREVENTION_HIGH_ERA = 5.50  # at/above this, grade must NOT be > 60
RUN_PREVENTION_LOW_GRADE = 40
RUN_PREVENTION_HIGH_GRADE = 60

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
    ]) or fallback
    return [
        {"label": "Hit", "grade": _grade(hit), "source": "K% / OPS"},
        {"label": "Power", "grade": _grade(power), "source": "ISO / OPS"},
        {"label": "Approach", "grade": _grade(approach), "source": "BB% / BB-K"},
        {"label": "Impact", "grade": _grade(impact), "source": "OPS / ISO"},
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
        _scale(current.get("era"), 6.25, 2.20),
        _scale(current.get("whip"), 1.75, 0.90),
    ]) or fallback
    return [
        {"label": "Miss", "grade": _grade(miss or fallback), "source": "K/9"},
        {"label": "Command", "grade": _grade(command or fallback), "source": "BB/9"},
        {"label": "Dominance", "grade": _grade(dominance), "source": "K-BB%"},
        {"label": "Run Prevention", "grade": _grade(run_prevention), "source": "ERA / WHIP"},
    ]


def _shape_from_line(line: dict, role: str, rank_score: float) -> list[dict]:
    shape = _pitcher_shape(line, rank_score) if role == "pitcher" else _hitter_shape(line, rank_score)
    return [item for item in shape if item.get("grade") is not None]


def _shape(row: dict, rank_score: float) -> list[dict]:
    return _shape_from_line(_current_context(row), str(row.get("role") or ""), rank_score)


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


# Hitter ceiling tiers, low -> high. Used to floor the role label by the peak shape.
_HITTER_TIERS = [
    "organizational_depth",
    "bench_or_platoon_bat",
    "second_division_regular",
    "everyday_regular",
    "impact_regular",
]


def _floor_ceiling_by_shape(ceiling: str, shape_average: float, role: str, *, risk_band: str | None = None) -> str:
    """Keep a hitter's role label from contradicting the card's own peak-shape grades.

    The label comes from peak_score (58% rank/value, 30% shape), so an elite-shape hitter
    with a soft, day-to-day-volatile rank score can read "bench or platoon bat" next to an
    80-hit peak. Floor the tier so it can't sit more than one rung below the tier the peak
    shape alone implies. Gated off high-risk thin samples so a small hot streak can't float
    the label. Pitchers and non-hitter tiers are untouched.
    """
    if role == "pitcher" or ceiling not in _HITTER_TIERS:
        return ceiling
    if risk_band == "high":
        return ceiling
    shape_band = _ceiling_band({"role": "hitter"}, float(shape_average or 0.0))
    if shape_band not in _HITTER_TIERS:
        return ceiling
    ci = _HITTER_TIERS.index(ceiling)
    si = _HITTER_TIERS.index(shape_band)
    return _HITTER_TIERS[max(ci, si - 1)]


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
    return eta_window(row)


# Public role-tier display labels: de-jargoned for the card/web surfaces. The role
# KEYS (impact_regular, second_division_regular, ...) drive logic and must NOT change;
# these only govern what a reader sees. "second division regular" was insider scouting
# jargon (FV-45 tier) -> plain language a casual fan gets instantly.
CEILING_LABELS = {
    "impact_regular": "impact everyday bat",
    "second_division_regular": "low-end everyday regular",
    "mid_rotation_or_better": "mid-rotation starter or better",
    "multi_inning_or_setup_arm": "multi-inning or setup reliever",
}


def ceiling_label(key) -> str:
    key = str(key or "")
    return CEILING_LABELS.get(key, key.replace("_", " "))


def _summary(row: dict, peak_score: float, ceiling: str, risk: str) -> str:
    current = _current_context(row)
    sample = _round(current.get("sample"), 1)
    unit = str(current.get("sample_unit") or "")
    skill_band = str(current.get("skill_band") or "current evidence").replace("_", " ")
    role = "pitching" if row.get("role") == "pitcher" else "bat"
    # Label the sample's level so this deterministic PA cite ("over 199 AA PA") cannot
    # read as a silent contradiction of a combined-line scouting read that pooled more
    # levels ("358 PA across AA & A+"). This is a TEXT LABEL ONLY -- the scored line the
    # peak projection consumes is unchanged; only the summary prose names its level.
    level = str(current.get("level") or "").strip()
    if sample is not None and unit:
        sample_text = f"{sample:g} {level} {unit}" if level else f"{sample:g} {unit}"
    else:
        sample_text = "the current sample"
    return (
        f"Peak read: {ceiling_label(ceiling)} with {risk} risk. "
        f"The current {role} shape is {skill_band} over {sample_text}; "
        "this is a role and skill-shape projection, not a full stat forecast."
    )


def _role_probability(row: dict, peak_score: float, risk: str, shape_average: float) -> dict:
    """Small deterministic role distribution for card context.

    These are not calibrated scouting probabilities. They are a display layer
    that keeps the peak read from pretending to be a single-point answer.

    The "top" (regular-or-better) term is anchored to the real peak_score
    distribution (7/7 audit against the live 2,796-player board: p10≈11.5,
    p95≈46.1, median≈23.6) -- the prior anchor (45.0, /35.0) assumed peak_score
    behaved like a roughly-centered 0-100 scale, but it's heavily right-skewed,
    so that anchor sat at the ~94th percentile. Only players ABOVE that
    threshold ever moved off the 0.05 floor -- 96% of the real board was
    pinned to an identical, non-informative floor value regardless of whether
    they were a median prospect or a replacement-level one. Rebased so the
    floor-to-cap ramp spans the real bulk of the distribution (~p10-p95)
    instead of only its top sliver. Revisit if the pool's peak_score
    distribution shifts materially (e.g. a scoring-model change).
    """
    role = str(row.get("role") or "")
    risk_penalty = {"low": 0.0, "medium": 0.10, "high": 0.20}.get(risk, 0.10)
    top = _clamp((peak_score - 12.0) / 34.0 - risk_penalty, 0.05, 0.70)
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


def _cohere_role_probabilities(probs: dict, ceiling: str, role: str, risk: str) -> dict:
    """Keep the modal probability bucket from contradicting the shape-floored ceiling.

    _role_probability derives from raw peak_score, so a hitter whose label was floored
    up by _floor_ceiling_by_shape can still show bench_or_platoon as the most likely
    outcome — the card's probability bars (and the LLM read grounded on them) then
    contradict the card's own Role strip and Projection line. Same gate as the floor:
    hitters only, high-risk untouched. Swapping keeps the distribution's mass; it only
    re-orders which bucket is modal.
    """
    if role == "pitcher" or risk == "high":
        return probs
    if ceiling not in ("everyday_regular", "impact_regular"):
        return probs
    modal = max(probs, key=probs.get)
    if modal == "regular_or_better":
        return probs
    out = dict(probs)
    out["regular_or_better"], out[modal] = probs[modal], probs["regular_or_better"]
    return out


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
        "role_probabilities": _cohere_role_probabilities(
            _role_probability(row, peak_score, risk, shape_average),
            ceiling,
            str(row.get("role") or ""),
            risk,
        ),
        "card_copy": (
            f"Ceiling is {ceiling_label(ceiling)}; "
            f"floor is {floor.removesuffix('_floor').replace('_', ' ')}. "
            f"{risk.capitalize()} risk, {confidence} confidence."
        ),
    }


def _context_only(row: dict) -> dict:
    value = row.get("context_only")
    return value if isinstance(value, dict) else {}


def _dynasty_signal(row: dict) -> dict:
    value = row.get("dynasty_signal")
    return value if isinstance(value, dict) else {}


def _best_single_line(row: dict) -> dict | None:
    value = _context_only(row).get("best_single_level_stat_line")
    return value if isinstance(value, dict) and value else None


def _v2_shape_line(row: dict) -> tuple[dict, str]:
    """Shape input for v2. When the current sample was thin, rank_v1 emits a
    best-single-level line (a fuller same-season single-level MiLB read in the SAME
    raw-MiLB units the shape scales expect) — grade off that instead of the thin
    current line. Otherwise keep the current-context line (= v1 behavior)."""
    best = _best_single_line(row)
    if best:
        line = dict(best)
        if str(row.get("role") or "") != "pitcher" and "bb_minus_k_pct" not in line:
            bb = _clean_float(best.get("bb_pct"))
            k = _clean_float(best.get("k_pct"))
            if bb is not None and k is not None:
                line["bb_minus_k_pct"] = round(bb - k, 1)
        return line, "best_single_level"
    return _current_context(row), "current"


def _mlb_equivalent(row: dict) -> dict | None:
    """ValuCast-owned MLB-equivalent translation, surfaced as honest context only.
    Deliberately NOT fed into the shape scales (which are tuned on raw-MiLB rates);
    folding it into a graded MLB-equivalent shape is a later, recalibrated pass."""
    translated = _context_only(row).get("stat_line_translated")
    if not isinstance(translated, dict) or not translated:
        return None
    rates = {}
    for stat in translated.get("stats") or []:
        key = stat.get("key") if isinstance(stat, dict) else None
        if key:
            rates[key] = {
                "mlb": stat.get("mlb"),
                "milb": stat.get("milb"),
                "mlb_avg": stat.get("mlb_avg"),
            }
    return {
        "level_label": translated.get("level_label") or translated.get("level"),
        "season": translated.get("season"),
        "sample": translated.get("sample"),
        "sample_unit": translated.get("sample_unit"),
        "confidence": translated.get("confidence"),
        "low_sample": translated.get("low_sample"),
        "rates": rates,
    }


def _v2_role_probability(
    row: dict,
    peak_score: float,
    risk: str,
    shape_average: float,
) -> tuple[dict, str]:
    """Cumulative outcome outlook from the prospect model's dynasty_signal:
    P(reaches role-or-better) >= P(reaches star ceiling) BY CONSTRUCTION. We surface
    the model's native cumulative pair instead of de-cumulating it into mutually
    exclusive star/regular/depth buckets — that de-cumulation is what produced the
    jarring P(star) > P(regular) displays. These are the UNCALIBRATED universal-model
    outcome frequencies (a 25-neighbor empirical vote, ~0.04 resolution), observe-only;
    the harness grades whether they are predictive before any card promotion. Falls back
    to v1's heuristic role-or-better estimate when the signal is absent (identity-only
    rows), tagged so the source is never ambiguous."""
    signal = _dynasty_signal(row)
    role_plus = _clean_float(signal.get("role_or_better_probability"))
    star = _clean_float(signal.get("star_ceiling_probability"))
    if role_plus is None and star is None:
        fallback = _role_probability(row, peak_score, risk, shape_average)
        role_or_better = round(_clamp(next(iter(fallback.values()), 0.0), 0.0, 1.0), 3)
        return {
            "reaches_role_or_better": role_or_better,
            "reaches_star_ceiling": None,  # no model signal -> no star estimate
            "bust_risk": round(1.0 - role_or_better, 3),
        }, "heuristic_fallback"
    role_plus = _clamp(role_plus if role_plus is not None else 0.0, 0.0, 1.0)
    star = _clamp(star if star is not None else 0.0, 0.0, role_plus)
    return {
        "reaches_role_or_better": round(role_plus, 3),
        "reaches_star_ceiling": round(star, 3),
        "bust_risk": round(1.0 - role_plus, 3),
    }, "model_dynasty_signal"


def _peak_v2(row: dict, *, v1_peak_score: float, rank_score: float) -> dict:
    role = str(row.get("role") or "")
    line, basis = _v2_shape_line(row)
    shape = _shape_from_line(line, role, rank_score)
    shape_average = _shape_average(shape)
    peak_score = _peak_score(row, shape_average)
    risk = _risk_band(row, shape_average)
    ceiling = _floor_ceiling_by_shape(_ceiling_band(row, peak_score), shape_average, role, risk_band=risk)
    floor = _floor_band(row, risk, shape_average)
    role_probabilities, role_probability_source = _v2_role_probability(
        row, peak_score, risk, shape_average
    )
    return {
        "model_version": PEAK_V2_VERSION,
        "status": "shadow_observe_only",
        "shape_basis": basis,
        "shape": shape,
        "shape_average": round(shape_average, 2),
        "peak_score": peak_score,
        "peak_role": ceiling,
        "ceiling_band": ceiling,
        "floor_band": floor,
        "risk_band": risk,
        "role_probabilities": role_probabilities,
        "role_probability_source": role_probability_source,
        "role_probability_basis": "cumulative_uncalibrated_outcome_distribution",
        "mlb_equivalent": _mlb_equivalent(row),
        "delta_vs_v1_peak_score": round(peak_score - v1_peak_score, 2),
    }


def _v2_summary(projections: list[dict]) -> dict:
    rows = [row.get("peak_v2") for row in projections if isinstance(row.get("peak_v2"), dict)]
    deltas = [
        row.get("delta_vs_v1_peak_score")
        for row in rows
        if isinstance(row.get("delta_vs_v1_peak_score"), (int, float))
    ]
    model_probs = sum(1 for row in rows if row.get("role_probability_source") == "model_dynasty_signal")
    return {
        "model_version": PEAK_V2_VERSION,
        "status": "shadow_observe_only",
        "feeds_card": False,
        "feeds_live_rank": False,
        "feeds_live_value": False,
        "projection_count": len(rows),
        "best_single_level_shape_count": sum(1 for row in rows if row.get("shape_basis") == "best_single_level"),
        "model_role_probability_count": model_probs,
        "heuristic_role_probability_count": len(rows) - model_probs,
        "mlb_equivalent_coverage_count": sum(1 for row in rows if row.get("mlb_equivalent")),
        "shape_changed_vs_v1_count": sum(1 for delta in deltas if delta),
        "avg_abs_delta_vs_v1": round(sum(abs(delta) for delta in deltas) / len(deltas), 3) if deltas else 0.0,
    }


def _projection_row(row: dict) -> dict:
    rank_score = _clean_float(row.get("score")) or 0.0
    shape = _shape(row, rank_score)
    shape_average = _shape_average(shape)
    peak_score = _peak_score(row, shape_average)
    risk = _risk_band(row, shape_average)
    ceiling = _floor_ceiling_by_shape(_ceiling_band(row, peak_score), shape_average, str(row.get("role") or ""), risk_band=risk)
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
        "peak_v2": _peak_v2(row, v1_peak_score=peak_score, rank_score=rank_score),
    }


def _identity_key(row: dict) -> str | None:
    mlbam_id = row.get("mlbam_id")
    role = row.get("role")
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return f"{mlbam_id}_{role}"


class PeakProjectionSentinelError(RuntimeError):
    """Raised when a built peak projection fails a semantic sentinel.

    A failure here means the artifact is unambiguously broken (e.g. an inverted
    Run Prevention grade) and must NOT be written or published.
    """


def _run_prevention_grade(shape: Any) -> int | None:
    if not isinstance(shape, list):
        return None
    for item in shape:
        if isinstance(item, dict) and item.get("label") == RUN_PREVENTION_LABEL:
            grade = item.get("grade")
            return grade if isinstance(grade, (int, float)) else None
    return None


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x <= 0.0 or var_y <= 0.0:
        return None
    return cov / math.sqrt(var_x * var_y)


def check_run_prevention_sentinel(
    projections: list[dict], rank_payload: dict
) -> dict:
    """Semantic guard: the Run Prevention grade must track ERA *inversely*.

    Pairs each pitcher projection's Run Prevention grade with the raw ERA the
    grade was built from (from the rank payload's factual_current_context), then
    checks (a) corr(ERA, grade) is strongly negative and (b) hard direction
    violations are rare. Raises PeakProjectionSentinelError on unambiguous
    inversion so a bad/stale artifact cannot publish.

    Returns a small summary dict (folded into the artifact's validation block)
    when the data passes — or when there are too few graded ERAs to judge.
    """
    era_by_key: dict[str, float] = {}
    for row in rank_payload.get("board") or []:
        if str(row.get("role") or "") != "pitcher":
            continue
        key = _identity_key(row)
        if key is None:
            continue
        era = _clean_float(_current_context(row).get("era"))
        if era is not None:
            era_by_key[key] = era

    eras: list[float] = []
    grades: list[float] = []
    violations: list[str] = []
    for row in projections:
        if str(row.get("role") or "") != "pitcher":
            continue
        key = _identity_key(row)
        if key is None:
            continue
        era = era_by_key.get(key)
        grade = _run_prevention_grade(row.get("shape"))
        if era is None or grade is None:
            continue
        eras.append(era)
        grades.append(float(grade))
        if era <= RUN_PREVENTION_LOW_ERA and grade < RUN_PREVENTION_LOW_GRADE:
            violations.append(f"{row.get('name')} (ERA {era:.2f} graded {grade})")
        elif era >= RUN_PREVENTION_HIGH_ERA and grade > RUN_PREVENTION_HIGH_GRADE:
            violations.append(f"{row.get('name')} (ERA {era:.2f} graded {grade})")

    pitcher_count = len(eras)
    summary = {
        "graded_pitcher_count": pitcher_count,
        "violation_count": len(violations),
    }
    if pitcher_count < RUN_PREVENTION_MIN_PITCHERS:
        # Not enough graded ERAs to trust a correlation; record and pass.
        summary["era_grade_correlation"] = None
        summary["status"] = "insufficient_sample"
        return summary

    corr = _correlation(eras, grades)
    violation_rate = len(violations) / pitcher_count
    summary["era_grade_correlation"] = round(corr, 4) if corr is not None else None
    summary["violation_rate"] = round(violation_rate, 4)
    summary["status"] = "ok"

    example = violations[0] if violations else "an elite ERA graded as poor"
    if corr is None or corr > RUN_PREVENTION_MAX_CORR:
        raise PeakProjectionSentinelError(
            "Run Prevention sentinel FAILED: corr(ERA, Run Prevention grade) is "
            f"{corr if corr is None else round(corr, 4)} (must be <= "
            f"{RUN_PREVENTION_MAX_CORR}). The grade is inverted or stale — low ERA "
            "must yield a HIGH grade, not low. "
            f"Example violation: {example}. "
            "Refusing to write the peak projection artifact."
        )
    if violation_rate > RUN_PREVENTION_MAX_VIOLATION_RATE:
        raise PeakProjectionSentinelError(
            "Run Prevention sentinel FAILED: "
            f"{len(violations)}/{pitcher_count} pitchers "
            f"({violation_rate:.1%}) violate the ERA<->grade direction "
            f"(threshold {RUN_PREVENTION_MAX_VIOLATION_RATE:.0%}). "
            f"Example: {example}. "
            "The Run Prevention grade is inverted or stale — refusing to write "
            "the peak projection artifact."
        )
    return summary


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
    # Semantic sentinel: fail LOUD here (before the artifact is ever written) if
    # the Run Prevention grade is inverted/stale relative to ERA. Schema/coverage
    # validation cannot catch this — a backwards grade is still well-formed.
    run_prevention_sentinel = check_run_prevention_sentinel(projections, rank_payload)
    validation = _validation(projections, rank_payload)
    validation["run_prevention_sentinel"] = run_prevention_sentinel
    return {
        "artifact": ARTIFACT_NAME,
        "v2": _v2_summary(projections),
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


def archive_peak_projection(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    """Persist the day's peak projection so the projection can later be graded
    against realized graduation outcomes (the accountability harness builds on this).
    Content-deduped + atomic, mirroring rank_v1.archive_rank."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "projection_version": payload["projection_version"],
        "generated_at": payload["generated_at"],
        "projection_count": payload["validation"]["projection_count"],
        "validation": payload["validation"],
        "v2": payload.get("v2"),
        "projections": payload["projections"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_peak_projection(
    rank_path: Path = RANK_V1_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    payload = build_peak_projection(rank_payload)
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
    archive_path, archive_changed = archive_peak_projection(
        payload,
        date_str=parsed_now.date().isoformat(),
        archive_dir=archive_dir,
    )
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "ready_for_card_v2": payload["validation"]["ready_for_card_v2"],
        "projection_count": payload["validation"]["projection_count"],
        "top200_projection_coverage": payload["validation"]["top200_projection_coverage"],
    }
