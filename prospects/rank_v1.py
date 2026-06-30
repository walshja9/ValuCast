"""Candidate ValuCast prospect ranking built from ValuCast-owned signals.

It ranks the current ValuCast prospect universe while keeping DD ranks, DD
values, and public source ranks out of the score.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.roster_status import ARTIFACT_PATH as MLB_ROSTER_STATUS_PATH
from mlb.roster_status import active_roster_lookup
from prospects.availability import ARTIFACT_PATH as AVAILABILITY_PATH
from prospects.availability import apply_availability_adjustment
from prospects.availability import availability_lookup
from prospects.availability import eta_window
from prospects.dynasty import ARTIFACT_PATH as DYNASTY_LAYER_PATH
from prospects.input_contract import VALUCAST_INPUT_PATH
from prospects.milb_translation import (
    best_single_level_stat_line,
    combined_season_stat_line,
    translate_peripherals,
)
from prospects.model import ARTIFACT_PATH as PROSPECT_MODEL_PATH
from prospects.universe import ARTIFACT_PATH as PROSPECT_UNIVERSE_PATH

ROOT = Path(__file__).resolve().parents[1]
MILB_SEASON_STATS_PATH = ROOT / "data" / "prospects" / "raw" / "milb_season_stats.json"
MILB_CARD_HISTORY_PATH = ROOT / "data" / "prospects" / "raw" / "milb_card_history.json"
INPUT_CONTRACT_PATH = VALUCAST_INPUT_PATH
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"

RANK_NAME = "ValuCast Prospect Rank v1"
RANK_VERSION = "0.2.8"

PITCHER_POSITIONS = {"P", "SP", "RP"}
PEDIGREE_SCORE_SOURCE = "prospect_pedigree_v0_7"
BUCKET_CALIBRATION_VERSION = "0.3.0"
FACTUAL_CURRENT_CONTEXT_VERSION = "0.1.0"
UNCERTAINTY_VERSION = "0.1.0"
NEAR_GRADUATION_VERSION = "0.1.0"
ROOKIE_AB_LIMIT = 131.0
ROOKIE_IP_LIMIT = 51.0
NEAR_GRADUATION_RATIO = 0.90
UPPER_LEVEL_BUCKETS = {"AA", "AAA", "MLB"}
LOWER_MINORS_PEDIGREE_SCORE_ADJUSTMENT = -3.5
THIN_UPPER_LEVEL_PITCHER_SAMPLE_IP = 30.0
THIN_UPPER_LEVEL_PITCHER_MODEL_ADJUSTMENT = -2.0
# Confidence-adjusted ranking: a thin current sample is penalized continuously by
# (1 - sample_reliability), so an unproven profile is ranked by a lower-confidence
# bound and sorts behind players with fuller evidence. Gated on the SAME
# "thin_current_sample" availability signal the quality governor's top-50
# bucket-shape check uses, so the board and the guardrail stay aligned.
THIN_SAMPLE_CONFIDENCE_PENALTY_MAX = 28.0
# Moderate-thin scored-line haircut -- the gap below B. A gaudy line whose own model
# reliability is low but the availability layer does NOT flag thin_current_sample, so
# B's haircut never fires (e.g. a 94-PA A+ masher at 32% reliability ranking #18 vs
# consensus #460). Linear, zero-anchored at the floor so reliability>=floor rows are
# untouched. Mutually exclusive with the thin_current_sample haircut (gated on NOT
# being flagged), so B ships exactly as is. Calibration knobs -- tuned on the shadow-diff.
MODERATE_THIN_RELIABILITY_FLOOR = 50.0
MODERATE_THIN_CONFIDENCE_PENALTY_K = 22.0
# Career-validated-discipline SOFTENER for the moderate-thin haircut: a thin line whose
# contact/discipline skill is corroborated by >=2 prior MiLB seasons (the multi-year arc
# the current model is blind to) gets ~45% of the haircut given back. Calibration-only
# (modulates the confidence haircut, never the model point estimate) -- same class as the
# pedigree spare-gate, no outcome-validation wall. Knobs tuned on the shadow-diff.
MODERATE_THIN_CAREER_SOFTENER = 0.55
CAREER_MIN_PRIOR_SEASONS = 2
CAREER_MIN_PRIOR_PA = 250.0
CAREER_DISCIPLINE_MAX_K = 15.0
CAREER_DISCIPLINE_MIN_BB = 10.0
CAREER_MIN_PRIOR_IP = 60.0
CAREER_PITCHER_MIN_KBB = 12.0
# Draft pedigree spares the thin-sample confidence haircut as INDEPENDENT support --
# but only while fresh. A recent draftee's pro sample is naturally thin, so the draft
# slot IS the evidence. As he accrues a multi-year pro record, his results become the
# evidence and the draft slot stops being independent support, so the spare DECAYS from
# full (<= FRESH yrs since draft) to none (>= STALE yrs). Keeps a 4-yr-stale top-10 pick
# whose results have since walked his grade down (e.g. Hughes, FV 40, #512 consensus)
# from riding 2022 draft night instead of his line. Calibration-only, not outcome-gated.
PEDIGREE_SPARE_FRESH_YEARS = 2.0
PEDIGREE_SPARE_STALE_YEARS = 5.0
# A prospect whose displayed stat line falls back to a prior-season MiLB sample
# (factual_current_context.source_kind != "current_season") has NO current-season
# evidence at all -- almost always an injured/inactive upper-level arm. They must
# not headline the public board on a year-old line, so they take a flat confidence
# penalty (distinct from the graded thin-sample rule above, which needs a current
# sample to scale against). Magnitude calibrated against the live score curve so no
# such prospect lands in the top-50 and <=10 remain in the top-200 -- the exact
# thresholds the milb_stat_freshness / prospect_card_data audits gate on -- with
# margin. Self-heals: when a current-season line is selected the penalty lifts.
NO_CURRENT_SEASON_ACTIVITY_PENALTY = 20.0
# A prospect whose most recent stat line is two or more seasons stale hasn't
# played competitively in a full year-plus -- not a rankable prospect, so they
# leave the board entirely (mirroring the active-MLB-roster exclusion) rather
# than just taking the penalty above. Self-heals: a current-season line puts them
# straight back on. One-season-stale arms still rank, just behind current
# evidence via NO_CURRENT_SEASON_ACTIVITY_PENALTY.
INACTIVE_BOARD_EXCLUSION_STALENESS_YEARS = 2
UPPER_LEVEL_HITTER_LOW_IMPACT_SAMPLE_PA = 200.0
UPPER_LEVEL_HITTER_LOW_IMPACT_ISO = 0.100
UPPER_LEVEL_HITTER_LOW_IMPACT_OPS = 0.720
UPPER_LEVEL_HITTER_LOW_IMPACT_ADJUSTMENT = -1.5
PEDIGREE_MIN_INVESTMENT_SCORE = 90.0
PEDIGREE_HITTER_SCORE_CAP = 48.0
PEDIGREE_PITCHER_SCORE_CAP = 45.5
PEDIGREE_HIGH_SAMPLE_BONUS_CAP = 0.75
PEDIGREE_UPPER_LEVEL_BONUS_CAP = 1.25
PEDIGREE_CAP_COMPRESSION_WINDOW = 1.5
PEDIGREE_LEVEL_BASELINE_AGE = {
    "DSL": 18.0,
    "CPX": 19.0,
    "ROK": 19.0,
    "A": 20.5,
    "A+": 21.3,
    "HIGH-A": 21.3,
    "AA": 22.2,
    "AAA": 23.0,
    "MLB": 24.0,
}
MODEL_COMPONENT_WEIGHTS = {
    "expected_outcome_score": 0.58,
    "expected_category_impact_score": 0.42,
}
MODEL_SCORE_QUANTILE_NORMALIZATION_VERSION = "role_quantile_to_pooled_v0_1"
MODEL_SCORE_QUANTILE_NORMALIZED_SUFFIX = "_role_quantile_normalized"
MODEL_SCORE_QUANTILE_PERCENTILE_SUFFIX = "_role_percentile"
SCORE_WEIGHTS = {
    "prospect_model_v0_6": {
        "model_score": 0.76,
        "universal_outcome_index": 0.15,
        "factual_investment_context": 0.06,
        "sample_reliability": 0.03,
    },
    "universal_fallback": {
        "universal_outcome_index": 0.76,
        "factual_investment_context": 0.14,
        "sample_reliability": 0.10,
    },
    PEDIGREE_SCORE_SOURCE: {
        "universal_outcome_index": 0.42,
        "factual_investment_context": 0.32,
        "sample_reliability": 0.16,
        "age_level_context": 0.10,
    },
    "identity_only_fallback": {
        "base_score": 1.0,
        "factual_investment_context": 0.08,
        "sample_reliability": 0.06,
    },
}
FALLBACK_SCORE_CAP = 41.75
IDENTITY_ONLY_BASE_SCORE = 18.0
IDENTITY_ONLY_SCORE_CAP = 28.0
IDENTITY_ONLY_NEUTRAL_RELIABILITY = 10.0
MISSING_INVESTMENT_CONTEXT_SCORE = 25.0
MIN_PUBLIC_COVERAGE_RATE = 0.98
MIN_TOP_200_UNIQUE_SCORE_COUNT = 120
SCORE_SOURCE_UNCERTAINTY_WIDTH = {
    "prospect_model_v0_6": 7.0,
    PEDIGREE_SCORE_SOURCE: 12.0,
    "universal_fallback": 14.0,
    "identity_only_fallback": 20.0,
}
CONFIDENCE_UNCERTAINTY_ADJUSTMENT = {
    "high": -2.0,
    "medium": 0.0,
    "moderate": 1.0,
    "low": 4.0,
}
CAUTION_SKILL_BANDS = {"thin", "limited", "low_impact"}

PROHIBITED_SCORE_INPUTS = [
    "DD dynasty_rank",
    "DD dynasty_value",
    "DD prospect_rank",
    "DD value_history",
    "public or external prospect source_ranks",
    "DD trade-market behavior",
    "DD 7x7 adapter rank or score",
]


def _clean_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _hand_code(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("code") or value.get("description") or value.get("side")
    text = str(value or "").strip().upper()
    if text in {"L", "LEFT"} or text.startswith("LEFT "):
        return "L"
    if text in {"R", "RIGHT"} or text.startswith("RIGHT "):
        return "R"
    return None


def _round(value: float | None, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def infer_role(positions: list[str] | tuple[str, ...] | None) -> str:
    normalized = [str(position).upper() for position in positions or [] if position]
    if normalized and all(position in PITCHER_POSITIONS for position in normalized):
        return "pitcher"
    return "hitter"


def identity_key(mlbam_id: Any, role: str | None) -> tuple[str, str] | None:
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return str(mlbam_id), role


def load_milb_history_index(
    season_stats_path: Path = MILB_SEASON_STATS_PATH,
    card_history_path: Path = MILB_CARD_HISTORY_PATH,
) -> dict[tuple[str, str], dict]:
    """ValuCast-owned MiLB rows per (mlbam_id, role) for the in-house translation +
    best-single-level display context. Current per-level
    rows come from milb_season_stats (un-slimmed, retains every level); older seasons
    come from milb_card_history. Newest-first so translate_peripherals reads the
    latest season; the current season is never double-counted across the two sources."""
    by_key_current: dict[tuple[str, str], list[dict]] = {}
    try:
        season_stats = json.loads(season_stats_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        season_stats = {}
    current_season = season_stats.get("season")
    for role_key in ("hitters", "pitchers"):
        for row in season_stats.get(role_key, []) or []:
            key = identity_key(row.get("mlbam_id"), row.get("role"))
            if key is None:
                continue
            by_key_current.setdefault(key, []).append(
                {**row, "season": row.get("season", current_season)}
            )

    by_key_history: dict[tuple[str, str], list[dict]] = {}
    try:
        card_history = json.loads(card_history_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        card_history = {}
    for player_rows in (card_history.get("players") or {}).values():
        for row in player_rows or []:
            key = identity_key(row.get("mlbam_id"), row.get("role"))
            if key is None:
                continue
            by_key_history.setdefault(key, []).append(row)

    index: dict[tuple[str, str], dict] = {}
    for key in set(by_key_current) | set(by_key_history):
        current_rows = by_key_current.get(key, [])
        history_rows = [
            row for row in by_key_history.get(key, [])
            if row.get("season") != current_season
        ]
        rows = current_rows + history_rows
        rows.sort(key=lambda r: (r.get("season") or 0), reverse=True)
        index[key] = {"rows": rows, "current_season": current_season}
    return index


def _sample_size(row: dict, role: str) -> float:
    if role == "pitcher":
        return (
            _clean_float(row.get("innings_pitched"))
            or _clean_float(row.get("sample"))
            or _clean_float(row.get("ip"))
            or 0.0
        )
    return (
        _clean_float(row.get("plate_appearances"))
        or _clean_float(row.get("sample"))
        or _clean_float(row.get("pa"))
        or 0.0
    )


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _generated_date(payload: dict) -> str | None:
    return _date_part(payload.get("generated_at"))


def _model_lookup(prospect_model: dict) -> dict[tuple[str, str], dict]:
    rows = []
    for row in prospect_model.get("ranked") or []:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key:
            rows.append(dict(row))
    _apply_role_quantile_model_score_normalization(rows)
    lookup = {}
    for row in rows:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key:
            lookup[key] = row
    return lookup


def _layer_lookup(dynasty_layer: dict) -> dict[tuple[str, str], dict]:
    lookup = {}
    for row in dynasty_layer.get("profiles") or []:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key:
            lookup[key] = row
    return lookup


def _input_lookup(input_contract: dict) -> dict[tuple[str, str], dict]:
    lookup: dict[tuple[str, str], dict] = {}
    for role, bucket in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in (input_contract.get("current") or {}).get(bucket) or []:
            key = identity_key(row.get("mlbam_id"), role)
            if not key:
                continue
            existing = lookup.get(key)
            if existing is None or _input_row_sort_key(row, role) > _input_row_sort_key(
                existing,
                role,
            ):
                merged = dict(row)
                if existing:
                    _fill_factual_context(merged, existing)
                lookup[key] = merged
            elif existing:
                _fill_factual_context(existing, row)
    return lookup


def _current_stat_expectation_lookup(input_contract: dict) -> dict[tuple[str, str], dict]:
    """Newest current-season stat row per MLBAM+role, used as a regression gate."""
    lookup: dict[tuple[str, str], dict] = {}
    for role, bucket in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in (input_contract.get("current") or {}).get(bucket) or []:
            if row.get("source_kind") != "current_season":
                continue
            key = identity_key(row.get("mlbam_id"), role)
            stat_line = _input_stat_line(row, role)
            if not key or not _has_skill_stat(stat_line):
                continue
            existing = lookup.get(key)
            if existing is None or _input_row_sort_key(row, role) > _input_row_sort_key(
                existing,
                role,
            ):
                lookup[key] = row
    return lookup


def _service_lookup(input_contract: dict) -> dict[tuple[str, str], dict]:
    lookup: dict[tuple[str, str], dict] = {}
    for row in input_contract.get("mlb_service") or []:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key:
            lookup[key] = row
    return lookup


MANUAL_GRADUATION_PATH = ROOT / "data" / "manual" / "prospect_graduation_overrides.json"


def _manual_graduated_ids() -> set[str]:
    """mlbam_ids manually removed from the board. Covers both service-time
    graduates the AB/IP rookie rule misses AND rookie-eligible but aged-out /
    quad-A profiles no longer ranked as prospects. Fail-soft: bad file -> empty."""
    try:
        raw = json.loads(MANUAL_GRADUATION_PATH.read_text(encoding="utf-8"))
        out: set[str] = set()
        for key in ("graduated_mlbam_ids", "excluded_mlbam_ids"):
            ids = raw.get(key)
            if isinstance(ids, list):
                out.update(str(x) for x in ids)
        return out
    except (OSError, ValueError):
        return set()


STS_CONSENSUS_PATH = ROOT / "data" / "sts" / "sts_consensus_snapshot.json"
FG_FV_SNAPSHOT_PATH = ROOT / "data" / "fangraphs" / "fg_fv_snapshot.json"
PROSPECTSLIVE_PATH = ROOT / "data" / "prospectslive" / "prospectslive_consensus_snapshot.json"
PIPELINE_PATH = ROOT / "data" / "pipeline" / "pipeline_consensus_snapshot.json"


def _snapshot_by_mlbam(path: Path) -> dict:
    """players_by_mlbam from a committed consensus/grade snapshot; {} if missing."""
    try:
        return (json.loads(path.read_text(encoding="utf-8")) or {}).get("players_by_mlbam") or {}
    except (OSError, ValueError):
        return {}


def _merge_external_consensus(
    row: dict, mlbam, sts_by_mlbam: dict, fg_by_mlbam: dict, pl_by_mlbam: dict,
    pipeline_by_mlbam: dict,
) -> None:
    """Blend the MLB Pipeline Top 100 + STS Formulated Consensus + the FanGraphs
    ordinal + the ProspectsLive Top-600 rank into a board row's
    context_only.source_ranks, so the public consensus = median of pipeline + hkb +
    sts + fg_ord + pl. Display/divergence reference only -- never a score input.
    (Pipeline re-introduced natively here after the DD-feed cut removed its old
    pass-through source.)"""
    context = row.get("context_only")
    if not isinstance(context, dict):
        return
    source_ranks = dict(context.get("source_ranks") or {})
    sts = sts_by_mlbam.get(str(mlbam)) or {}
    if sts.get("sts_rank") is not None:
        source_ranks["sts"] = sts["sts_rank"]
    fg = fg_by_mlbam.get(str(mlbam)) or {}
    if fg.get("fg_top100") is not None:
        source_ranks["fg_ord"] = fg["fg_top100"]
    pl = pl_by_mlbam.get(str(mlbam)) or {}
    if pl.get("pl_rank") is not None:
        source_ranks["pl"] = pl["pl_rank"]
    pipeline = pipeline_by_mlbam.get(str(mlbam)) or {}
    if pipeline.get("pipeline_rank") is not None:
        source_ranks["pipeline"] = pipeline["pipeline_rank"]
    if source_ranks:
        context["source_ranks"] = source_ranks


def _rookie_limits(input_contract: dict) -> dict[str, float]:
    raw = input_contract.get("rookie_limits") or {}
    return {
        "at_bats": _clean_float(raw.get("at_bats")) or ROOKIE_AB_LIMIT,
        "innings_pitched": _clean_float(raw.get("innings_pitched")) or ROOKIE_IP_LIMIT,
    }


def _input_row_sort_key(row: dict, role: str) -> tuple[float, int, float, int]:
    """Select the current line the model scores: max-sample first, then level.

    INV-SELECT-1 (scored == shown): mirrors prospects/model.py::_select_current_records
    (which scores the largest-sample line) so the displayed/calibration line matches
    the line that produced the value. The scored line, not the most-advanced level, is
    the card's evidence slice; the promotion is still surfaced via the roster/universe-
    sourced display level. `_display_record_key` is intentionally left untouched.
    """
    season = _clean_float(row.get("sample_season")) or 0.0
    current_flag = 1 if row.get("source_kind") == "current_season" else 0
    return (
        season,
        current_flag,
        _sample_size(row, role),
        _input_level_rank(row.get("level")),
    )


def _input_level_rank(level: Any) -> int:
    return {
        "AAA": 4,
        "AA": 3,
        "A+": 2,
        "HIGH-A": 2,
        "A": 1,
    }.get(str(level or "").upper(), 0)


def _fill_factual_context(target: dict, source: dict) -> None:
    for key in (
        "draft_pick_number",
        "draft_record_known",
        "draft_round",
        "draft_year",
        "pick_value",
        "rule4_drafted",
        "school_type",
        "signing_bonus",
    ):
        if target.get(key) in (None, "") and source.get(key) not in (None, ""):
            target[key] = source[key]


def _input_stat_line(row: dict | None, role: str | None) -> dict | None:
    if not row:
        return None
    if role == "pitcher":
        fields = (
            ("era", 2),
            ("whip", 2),
            ("k_per_9", 1),
            ("bb_per_9", 1),
            ("k_bb_pct", 1),
            ("ip", 1),
        )
        aliases = {"ip": "innings_pitched"}
    else:
        fields = (
            ("avg", 3),
            ("obp", 3),
            ("slg", 3),
            ("ops", 3),
            ("iso", 3),
            ("k_pct", 1),
            ("bb_pct", 1),
            ("pa", 0),
        )
        aliases = {"pa": "plate_appearances"}

    stat_line = {}
    for key, digits in fields:
        raw = row.get(key)
        if raw in (None, "") and key in aliases:
            raw = row.get(aliases[key])
        value = _clean_float(raw)
        if value is None:
            continue
        stat_line[key] = int(round(value)) if digits == 0 else round(value, digits)
    return stat_line or None


def _has_skill_stat(stat_line: dict | None) -> bool:
    if not isinstance(stat_line, dict):
        return False
    return any(key not in {"pa", "ip"} for key in stat_line)


def _stat_line_context(row: dict | None, role: str | None) -> dict:
    if not row or role not in {"hitter", "pitcher"}:
        return {}
    sample = _sample_size(row, role)
    sample_season = _clean_float(row.get("sample_season"))
    context = {
        "stat_line_source_kind": row.get("source_kind"),
        "stat_line_level": row.get("level"),
        "stat_line_team": row.get("team"),
        "stat_line_sample": round(sample, 3),
        "stat_line_sample_unit": "IP" if role == "pitcher" else "PA",
        "stat_line_sample_season": int(sample_season)
        if sample_season is not None
        else None,
    }
    return {key: value for key, value in context.items() if value not in (None, "")}


def _graduation_context(
    service_row: dict | None,
    role: str | None,
    limits: dict[str, float],
) -> dict | None:
    if not service_row or role not in {"hitter", "pitcher"}:
        return None
    if role == "pitcher":
        current = _clean_float(service_row.get("ip"))
        limit = limits.get("innings_pitched") or ROOKIE_IP_LIMIT
        unit = "IP"
    else:
        current = _clean_float(service_row.get("ab"))
        unit = "AB"
        if current is None or current <= 0:
            current = _clean_float(service_row.get("pa"))
            unit = "PA"
        limit = limits.get("at_bats") or ROOKIE_AB_LIMIT
    if current is None or limit <= 0:
        return None
    graduated = service_row.get("graduated") is True
    ratio = max(0.0, current / limit)
    if not graduated and ratio < NEAR_GRADUATION_RATIO:
        return None
    status = "graduated" if graduated else "near_graduation"
    remaining = max(0.0, limit - current)
    return {
        "version": NEAR_GRADUATION_VERSION,
        "status": status,
        "unit": unit,
        "current": round(current, 1),
        "limit": round(limit, 1),
        "remaining": round(remaining, 1),
        "ratio": round(min(ratio, 1.0), 3),
        "graduated": graduated,
        "label": (
            "Graduated by rookie limits"
            if graduated
            else f"Near graduation: {current:.1f}/{limit:.0f} {unit}"
        ),
        "score_effect": "display_only_not_used_for_valucast_score",
    }


def _factual_current_context(row: dict | None, role: str | None) -> dict | None:
    if not row or role not in {"hitter", "pitcher"}:
        return None

    sample = _sample_size(row, role)
    level = _level_key(row.get("level"))
    context: dict[str, Any] = {
        "version": FACTUAL_CURRENT_CONTEXT_VERSION,
        "role": role,
        "level": level,
        "sample": round(sample, 1),
        "sample_unit": "IP" if role == "pitcher" else "PA",
        "source_kind": row.get("source_kind"),
        "sample_season": _round(_clean_float(row.get("sample_season")), 0),
    }

    if role == "pitcher":
        k_per_9 = _clean_float(row.get("k_per_9"))
        bb_per_9 = _clean_float(row.get("bb_per_9"))
        k_bb_pct = _clean_float(row.get("k_bb_pct"))
        era = _clean_float(row.get("era"))
        whip = _clean_float(row.get("whip"))
        games_started = _clean_float(row.get("games_started"))
        starter_flag = bool(row.get("is_starter")) or (games_started or 0.0) >= 5.0

        if sample < 15.0:
            skill_band = "thin"
        elif sample < 30.0:
            skill_band = "limited"
        elif starter_flag and sample >= 50.0:
            skill_band = "starter_volume"
        elif (k_bb_pct or 0.0) >= 20.0 or (
            k_per_9 is not None and bb_per_9 is not None and k_per_9 - bb_per_9 >= 7.0
        ):
            skill_band = "bat_missing"
        else:
            skill_band = "mixed"

        context.update(
            {
                "skill_band": skill_band,
                "starter_role": starter_flag,
                "games_started": _round(games_started, 0),
                "era": _round(era, 2),
                "whip": _round(whip, 2),
                "k_per_9": _round(k_per_9, 1),
                "bb_per_9": _round(bb_per_9, 1),
                "k_bb_pct": _round(k_bb_pct, 1),
            }
        )
    else:
        ops = _clean_float(row.get("ops"))
        iso = _clean_float(row.get("iso"))
        k_pct = _clean_float(row.get("k_pct"))
        bb_pct = _clean_float(row.get("bb_pct"))
        bb_minus_k_pct = (
            round(bb_pct - k_pct, 1)
            if bb_pct is not None and k_pct is not None
            else None
        )

        if sample < 50.0:
            skill_band = "thin"
        elif ops is not None and iso is not None and ops >= 0.850 and iso >= 0.170:
            skill_band = "impact"
        elif ops is not None and iso is not None and ops < 0.720 and iso < 0.100:
            skill_band = "low_impact"
        elif (
            ops is not None
            and ops >= 0.760
            and bb_minus_k_pct is not None
            and bb_minus_k_pct >= -10.0
        ):
            skill_band = "balanced"
        else:
            skill_band = "mixed"

        context.update(
            {
                "skill_band": skill_band,
                "ops": _round(ops, 3),
                "iso": _round(iso, 3),
                "k_pct": _round(k_pct, 1),
                "bb_pct": _round(bb_pct, 1),
                "bb_minus_k_pct": bb_minus_k_pct,
            }
        )

    return {key: value for key, value in context.items() if value is not None}


def _universe_rows(prospect_universe: dict) -> list[dict]:
    return [
        row
        for row in prospect_universe.get("players") or []
        if row.get("role") in {"hitter", "pitcher"}
    ]


def _model_score_field_normalized_key(field: str) -> str:
    return f"{field}{MODEL_SCORE_QUANTILE_NORMALIZED_SUFFIX}"


def _model_score_field_percentile_key(field: str) -> str:
    return f"{field}{MODEL_SCORE_QUANTILE_PERCENTILE_SUFFIX}"


def _model_score_tiebreak_key(row: dict) -> tuple[int, int | str, str]:
    mlbam_id = row.get("mlbam_id")
    try:
        return (0, int(mlbam_id), str(row.get("role") or ""))
    except (TypeError, ValueError):
        return (1, str(mlbam_id or ""), str(row.get("role") or ""))


def _pooled_quantile_value(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    percentile = max(0.0, min(1.0, percentile))
    position = percentile * (len(sorted_values) - 1)
    lower_index = int(math.floor(position))
    upper_index = int(math.ceil(position))
    if lower_index == upper_index:
        return sorted_values[lower_index]
    lower = sorted_values[lower_index]
    upper = sorted_values[upper_index]
    return lower + (upper - lower) * (position - lower_index)


def _apply_role_quantile_model_score_normalization(rows: list[dict]) -> None:
    for field in MODEL_COMPONENT_WEIGHTS:
        scored_rows = [
            row
            for row in rows
            if row.get("role") in {"hitter", "pitcher"}
            and _clean_float(row.get(field)) is not None
        ]
        pooled_values = sorted(_clean_float(row.get(field)) for row in scored_rows)
        if not pooled_values:
            continue
        for role in ("hitter", "pitcher"):
            role_rows = [row for row in scored_rows if row.get("role") == role]
            role_rows.sort(
                key=lambda row: (
                    _clean_float(row.get(field)) or 0.0,
                    _model_score_tiebreak_key(row),
                )
            )
            role_count = len(role_rows)
            start = 0
            while start < role_count:
                end = start
                value = _clean_float(role_rows[start].get(field)) or 0.0
                while (
                    end + 1 < role_count
                    and (_clean_float(role_rows[end + 1].get(field)) or 0.0) == value
                ):
                    end += 1
                # Tie block start..end shares a single mean-rank percentile so equal
                # raw scores map to equal normalized scores (no mlbam_id tie-split).
                percentile = sum(
                    (index + 1) / (role_count + 1) for index in range(start, end + 1)
                ) / (end - start + 1)
                normalized = _pooled_quantile_value(pooled_values, percentile)
                for index in range(start, end + 1):
                    row = role_rows[index]
                    if normalized is None:
                        continue
                    row[_model_score_field_percentile_key(field)] = round(percentile, 6)
                    row[_model_score_field_normalized_key(field)] = round(normalized, 6)
                start = end + 1


def _model_score_component_value(model_profile: dict, field: str) -> float | None:
    normalized = _clean_float(
        model_profile.get(_model_score_field_normalized_key(field))
    )
    if normalized is not None:
        return normalized
    return _clean_float(model_profile.get(field))


def _model_score_normalization_component(model_profile: dict | None) -> dict | None:
    if not model_profile:
        return None
    fields = {}
    for field in MODEL_COMPONENT_WEIGHTS:
        normalized = _clean_float(
            model_profile.get(_model_score_field_normalized_key(field))
        )
        if normalized is None:
            continue
        fields[field] = {
            "raw": _round(_clean_float(model_profile.get(field)), 6),
            "normalized": _round(normalized, 6),
            "role_percentile": _round(
                _clean_float(model_profile.get(_model_score_field_percentile_key(field))),
                6,
            ),
        }
    if not fields:
        return None
    return {
        "version": MODEL_SCORE_QUANTILE_NORMALIZATION_VERSION,
        "method": "within_role_percentile_to_pooled_distribution",
        "fields": fields,
    }


def _model_score(model_profile: dict | None) -> float | None:
    if not model_profile:
        return None
    outcome = _model_score_component_value(model_profile, "expected_outcome_score")
    impact = _model_score_component_value(
        model_profile,
        "expected_category_impact_score",
    )
    if outcome is None and impact is None:
        return None
    if outcome is None:
        outcome = impact
    if impact is None:
        impact = outcome
    assert outcome is not None
    assert impact is not None
    return round(
        100.0
        * (
            MODEL_COMPONENT_WEIGHTS["expected_outcome_score"] * outcome
            + MODEL_COMPONENT_WEIGHTS["expected_category_impact_score"] * impact
        ),
        2,
    )


def _universal_outcome_index(layer_profile: dict | None) -> float:
    signal = (layer_profile or {}).get("dynasty_signal") or {}
    tier = _clean_float(signal.get("expected_factual_outcome_tier"))
    if tier is not None:
        return round(max(0.0, min(100.0, tier * 50.0)), 2)
    distribution = (layer_profile or {}).get("outcome_distribution") or {}
    role = _clean_float(distribution.get("role_probability")) or 0.0
    star = _clean_float(distribution.get("star_probability")) or 0.0
    return round(max(0.0, min(100.0, role * 50.0 + star * 100.0)), 2)


def _sample_reliability_score(
    layer_profile: dict | None,
    model_profile: dict | None,
) -> float:
    reliability = _clean_float((layer_profile or {}).get("sample_reliability"))
    if reliability is None:
        reliability = _clean_float((model_profile or {}).get("sample_reliability"))
    if reliability is None:
        return 45.0
    if reliability <= 1.0:
        return round(max(0.0, min(100.0, reliability * 100.0)), 2)
    return round(max(0.0, min(100.0, reliability)), 2)


def _input_sample_reliability_score(input_row: dict | None, role: str) -> float:
    if not input_row:
        return IDENTITY_ONLY_NEUTRAL_RELIABILITY
    sample = _sample_size(input_row, role)
    regression = 200.0 if role == "hitter" else 50.0
    if sample <= 0:
        return IDENTITY_ONLY_NEUTRAL_RELIABILITY
    return round(max(0.0, min(100.0, 100.0 * sample / (sample + regression))), 2)


def _factual_investment_score(input_row: dict | None) -> float | None:
    if not input_row:
        return None
    pieces = []
    draft_pick = _clean_float(input_row.get("draft_pick_number"))
    if draft_pick and draft_pick > 0:
        pieces.append(
            max(0.0, min(100.0, 100.0 - 100.0 * math.log(draft_pick) / math.log(615)))
        )
    bonus = _clean_float(input_row.get("signing_bonus"))
    if bonus and bonus > 0:
        pieces.append(
            max(
                0.0,
                min(
                    100.0,
                    100.0
                    * (math.log10(bonus) - 4.0)
                    / (math.log10(8_000_000) - 4.0),
                ),
            )
        )
    if not pieces:
        return None
    return round(max(pieces), 2)


def _level_key(level: Any) -> str | None:
    if not level:
        return None
    text = str(level).strip().upper()
    aliases = {
        "A_PLUS": "A+",
        "HIGH A": "A+",
        "HIGH-A": "A+",
        "HI-A": "A+",
        "LOW A": "A",
        "LOW-A": "A",
        "SINGLE-A": "A",
        "ROOKIE": "ROK",
        "COMPLEX": "CPX",
    }
    return aliases.get(text, text)


def _age_level_context_score(
    input_row: dict | None,
    layer_profile: dict | None,
    role: str,
) -> float:
    age = _clean_float((input_row or {}).get("age"))
    if age is None:
        age = _clean_float((layer_profile or {}).get("age"))
    level = _level_key((input_row or {}).get("level") or (layer_profile or {}).get("level"))
    baseline_age = PEDIGREE_LEVEL_BASELINE_AGE.get(level or "")
    if age is None or baseline_age is None:
        return 50.0
    if role == "pitcher":
        baseline_age += 0.3
    return round(max(0.0, min(100.0, 70.0 + (baseline_age - age) * 8.0)), 2)


def _pedigree_score_cap(
    role: str,
    level: Any,
    reliability_score: float,
    investment_score: float | None,
) -> float:
    cap = PEDIGREE_PITCHER_SCORE_CAP if role == "pitcher" else PEDIGREE_HITTER_SCORE_CAP
    level_key = _level_key(level)
    if level_key in {"AA", "AAA"}:
        cap += PEDIGREE_UPPER_LEVEL_BONUS_CAP
    if (investment_score or 0.0) >= 98.0 and reliability_score >= 45.0:
        cap += PEDIGREE_HIGH_SAMPLE_BONUS_CAP
    return round(cap, 2)


def _pedigree_fallback_score_components(
    layer_profile: dict,
    input_row: dict | None,
    role: str,
    universal_score: float,
    investment_score: float,
    reliability_score: float,
) -> tuple[float, dict]:
    weights = SCORE_WEIGHTS[PEDIGREE_SCORE_SOURCE]
    age_level_score = _age_level_context_score(input_row, layer_profile, role)
    uncapped_score = (
        weights["universal_outcome_index"] * universal_score
        + weights["factual_investment_context"] * investment_score
        + weights["sample_reliability"] * reliability_score
        + weights["age_level_context"] * age_level_score
    )
    cap = _pedigree_score_cap(
        role,
        (input_row or {}).get("level") or layer_profile.get("level"),
        reliability_score,
        investment_score,
    )
    cap_compressed = uncapped_score > cap
    if cap_compressed:
        overage = min(1.0, (uncapped_score - cap) / 20.0)
        context_blend = (
            0.35 * max(0.0, min(1.0, (investment_score - PEDIGREE_MIN_INVESTMENT_SCORE) / 10.0))
            + 0.25 * max(0.0, min(1.0, reliability_score / 100.0))
            + 0.25 * max(0.0, min(1.0, universal_score / 100.0))
            + 0.15 * max(0.0, min(1.0, age_level_score / 100.0))
        )
        score = min(
            cap - 0.01,
            cap
            - PEDIGREE_CAP_COMPRESSION_WINDOW
            + 0.8 * overage
            + 0.4 * context_blend,
        )
    else:
        score = uncapped_score
    return (
        round(score, 2),
        {
            "age_level_context": _round(age_level_score),
            "pedigree_score_uncapped": _round(uncapped_score),
            "pedigree_score_cap": cap,
            "pedigree_cap_compressed": cap_compressed,
            "pedigree_cap_compression_window": PEDIGREE_CAP_COMPRESSION_WINDOW,
            "pedigree_min_investment_score": PEDIGREE_MIN_INVESTMENT_SCORE,
        },
    )


def _identity_only_score_components(
    input_row: dict | None,
    role: str,
) -> tuple[float, str, dict]:
    investment_score = _factual_investment_score(input_row)
    reliability_score = _input_sample_reliability_score(input_row, role)
    current_context = _factual_current_context(input_row, role)
    investment_component = (
        investment_score
        if investment_score is not None
        else MISSING_INVESTMENT_CONTEXT_SCORE
    )
    weights = SCORE_WEIGHTS["identity_only_fallback"]
    score = (
        weights["base_score"] * IDENTITY_ONLY_BASE_SCORE
        + weights["factual_investment_context"]
        * investment_component
        + weights["sample_reliability"] * reliability_score
    )
    return (
        round(min(score, IDENTITY_ONLY_SCORE_CAP), 2),
        "identity_only_fallback",
        {
            "model_score": None,
            "universal_outcome_index": None,
            "factual_investment_context": _round(investment_score),
            "factual_investment_missing_uses_neutral": False,
            "factual_investment_missing_penalty": investment_score is None,
            "factual_investment_missing_score": (
                MISSING_INVESTMENT_CONTEXT_SCORE if investment_score is None else None
            ),
            "sample_reliability": _round(reliability_score),
            "identity_only_base_score": IDENTITY_ONLY_BASE_SCORE,
            "identity_only_score_cap": IDENTITY_ONLY_SCORE_CAP,
        }
        | ({"factual_current_context": current_context} if current_context else {}),
    )


def _score_components(
    model_profile: dict | None,
    layer_profile: dict,
    input_row: dict | None,
) -> tuple[float, str, dict]:
    model_score = _model_score(model_profile)
    universal_score = _universal_outcome_index(layer_profile)
    investment_score = _factual_investment_score(input_row)
    reliability_score = _sample_reliability_score(layer_profile, model_profile)
    role = (
        (layer_profile or {}).get("role")
        or (model_profile or {}).get("role")
        or (input_row or {}).get("role")
        or "hitter"
    )
    current_context = _factual_current_context(input_row, role)
    investment_component = (
        investment_score
        if investment_score is not None
        else MISSING_INVESTMENT_CONTEXT_SCORE
    )

    if model_score is not None:
        source = "prospect_model_v0_6"
        weights = SCORE_WEIGHTS[source]
        score = (
            weights["model_score"] * model_score
            + weights["universal_outcome_index"] * universal_score
            + weights["factual_investment_context"]
            * investment_component
            + weights["sample_reliability"] * reliability_score
        )
        pedigree_components = {}
    elif (investment_score or 0.0) >= PEDIGREE_MIN_INVESTMENT_SCORE:
        source = PEDIGREE_SCORE_SOURCE
        assert investment_score is not None
        score, pedigree_components = _pedigree_fallback_score_components(
            layer_profile,
            input_row,
            role,
            universal_score,
            investment_score,
            reliability_score,
        )
    else:
        source = "universal_fallback"
        weights = SCORE_WEIGHTS[source]
        uncapped = (
            weights["universal_outcome_index"] * universal_score
            + weights["factual_investment_context"]
            * investment_component
            + weights["sample_reliability"] * reliability_score
        )
        score = min(uncapped, FALLBACK_SCORE_CAP)
        pedigree_components = {}

    components = {
        "model_score": _round(model_score),
        "universal_outcome_index": _round(universal_score),
        "factual_investment_context": _round(investment_score),
        "factual_investment_missing_uses_neutral": False,
        "factual_investment_missing_penalty": investment_score is None,
        "factual_investment_missing_score": (
            MISSING_INVESTMENT_CONTEXT_SCORE if investment_score is None else None
        ),
        "sample_reliability": _round(reliability_score),
    }
    normalization_component = _model_score_normalization_component(model_profile)
    if normalization_component:
        components["model_score_normalization"] = normalization_component
    if current_context:
        components["factual_current_context"] = current_context
    if source == "universal_fallback":
        components["fallback_score_cap"] = FALLBACK_SCORE_CAP
    if pedigree_components:
        components.update(pedigree_components)
    return round(score, 2), source, components


def _board_model_score_normalization_rows(
    rows: list[dict],
    model_by_key: dict[tuple[str, str], dict],
    input_by_key: dict[tuple[str, str], dict],
    active_mlb_roster_ids: set[str],
) -> list[dict]:
    normalization_rows = []
    seen: set[tuple[str, str]] = set()
    for universe_row in rows:
        role = universe_row.get("role")
        key = identity_key(universe_row.get("mlbam_id"), role)
        if key is None or key in seen or key[0] in active_mlb_roster_ids:
            continue
        seen.add(key)
        input_row = input_by_key.get(key)
        staleness_years = _clean_float((input_row or {}).get("sample_staleness_years"))
        if (
            staleness_years is not None
            and staleness_years >= INACTIVE_BOARD_EXCLUSION_STALENESS_YEARS
        ):
            continue
        model_profile = model_by_key.get(key)
        if model_profile:
            normalization_rows.append(model_profile)
    return normalization_rows


def _prior_year_strength(factual: dict, role: str) -> float:
    """0..1 strength of a prior-year fallback line: sample adequacy x production.

    Softens the no-current-season penalty -- a full, productive prior year (e.g.
    an arm returning from injury) is far more predictive than a thin/weak one.
    Calibration judgment, not outcome-gated (the validated outcome set excludes
    thin samples by construction).
    """
    samp = _clean_float((factual or {}).get("sample")) or 0.0
    if role == "pitcher":
        size = min(1.0, samp / 80.0)
        kbb = _clean_float((factual or {}).get("k_bb_pct")) or 0.0
        prod = max(0.0, min(1.0, (kbb - 5.0) / 15.0))
    elif role == "hitter":
        size = min(1.0, samp / 400.0)
        ops = _clean_float((factual or {}).get("ops")) or 0.0
        prod = max(0.0, min(1.0, (ops - 0.650) / 0.200))
    else:
        return 0.0
    return size * prod


def _high_pedigree(input_row: dict | None) -> bool:
    """Top-75 draft pick or >=$1M signing bonus (independence-safe pedigree).

    High-pedigree prospects establish ~52% vs ~16% in the validated outcome set,
    so pedigree credit is well-founded even where the thin-sample axis isn't.
    """
    row = input_row or {}
    pick = _clean_float(row.get("draft_pick_number"))
    bonus = _clean_float(row.get("signing_bonus")) or 0.0
    return (pick is not None and pick <= 75) or bonus >= 1_000_000.0


def _pedigree_spare_credit(input_row: dict | None, current_season: float | None) -> float:
    """Fraction of the draft-pedigree confidence spare that still applies, decayed by
    years since draft (PEDIGREE_SPARE_*). 1.0 = full spare (fresh pedigree, OR draft year
    unknown -> conservative, preserves prior all-or-nothing behavior); 0.0 = no spare
    (not pedigreed, or pedigree too stale to count as independent support). Modulates the
    confidence haircut, never the point estimate -- calibration judgment, not outcome-gated.
    """
    if not _high_pedigree(input_row):
        return 0.0
    draft_year = _clean_float((input_row or {}).get("draft_year"))
    if draft_year is None or current_season is None:
        return 1.0
    years = current_season - draft_year
    if years <= PEDIGREE_SPARE_FRESH_YEARS:
        return 1.0
    if years >= PEDIGREE_SPARE_STALE_YEARS:
        return 0.0
    span = PEDIGREE_SPARE_STALE_YEARS - PEDIGREE_SPARE_FRESH_YEARS
    return (PEDIGREE_SPARE_STALE_YEARS - years) / span


def _career_validated_discipline(career_entry: dict | None, role: str) -> bool:
    """Multi-year MiLB track record corroborating the current thin line's contact/
    discipline skill (k%/bb% for hitters, k-bb% for pitchers). Sibling of _high_pedigree
    -- calibration_judgment_not_outcome_gated: it SOFTENS (never sets) the moderate-thin
    confidence haircut and never touches the model point estimate, so it sidesteps the
    W2.1/MLE outcome-validation wall. Fires only when >=2 PRIOR usable seasons show the
    skill is durable, so a thin current line continuing a proven multi-year skill (e.g.
    Hernandez's K% 20->7 over ~1000 PA) is not docked like a no-history fluke. Graceful
    no-op when career history is absent (the long-tail default), exactly like _high_pedigree.
    """
    if not career_entry:
        return False
    current_season = _clean_float(career_entry.get("current_season"))
    by_season: dict[float, list[tuple[float, dict]]] = {}
    for row in (career_entry.get("rows") or []):
        season = _clean_float(row.get("season"))
        if season is None or (current_season is not None and season >= current_season):
            continue  # PRIOR seasons only -- the current thin line is what we're deciding on
        samp = _sample_size(row, role)
        if samp > 0:
            by_season.setdefault(season, []).append((samp, row))
    if len(by_season) < CAREER_MIN_PRIOR_SEASONS:
        return False

    def _pa_weighted(field: str) -> tuple[float, float]:
        num = den = 0.0
        for entries in by_season.values():
            season_w = sum(s for s, _ in entries)
            if season_w <= 0:
                continue
            season_val = sum(
                (_clean_float(r.get(field)) or 0.0) * s for s, r in entries
            ) / season_w
            num += season_val * season_w
            den += season_w
        return (num / den if den else 0.0), den

    if role == "hitter":
        k_pct, total_pa = _pa_weighted("k_pct")
        bb_pct, _ = _pa_weighted("bb_pct")
        if total_pa < CAREER_MIN_PRIOR_PA:
            return False
        return k_pct <= CAREER_DISCIPLINE_MAX_K and bb_pct >= CAREER_DISCIPLINE_MIN_BB
    k_bb_pct, total_ip = _pa_weighted("k_bb_pct")
    if total_ip < CAREER_MIN_PRIOR_IP:
        return False
    return k_bb_pct >= CAREER_PITCHER_MIN_KBB


def _bucket_calibration_adjustment(
    score: float,
    source: str,
    layer_profile: dict | None,
    input_row: dict | None,
    universe_row: dict | None,
    components: dict,
    career_entry: dict | None = None,
) -> tuple[float, dict]:
    level = _level_key(
        (input_row or {}).get("level")
        or (layer_profile or {}).get("level")
        or (universe_row or {}).get("level")
    )
    role = (
        (universe_row or {}).get("role")
        or (layer_profile or {}).get("role")
        or (input_row or {}).get("role")
    )
    adjustments = []
    availability = components.get("availability")
    availability = availability if isinstance(availability, dict) else {}

    # Match the milb_stat_freshness / prospect_card_data audit predicate exactly:
    # a row is a "history fallback" unless its factual context is current_season.
    # The base penalty keeps such a profile behind current-season evidence, but it
    # is a CALIBRATION JUDGMENT (not outcome-gated -- the validated outcome set
    # excludes thin samples by construction). The flat hit is softened by prior-
    # year strength + draft pedigree + genuine injury, and de-stacked from the
    # availability staleness haircut that fires on the same signal. Evidence:
    # injured-arm-with-strong-prior pitchers establish ~43% vs ~8% (N=14,
    # directional); high-pedigree prospects ~52% vs 16% (large N). Hitter prior
    # softening is capped lower (no historical analogs). See _prior_year_strength.
    factual = components.get("factual_current_context")
    factual = factual if isinstance(factual, dict) else {}
    current_season = _clean_float(factual.get("sample_season"))
    if factual.get("source_kind") != "current_season":
        base = -NO_CURRENT_SEASON_ACTIVITY_PENALTY
        prior_q = _prior_year_strength(factual, str(role or ""))
        max_soft = 0.60 if role == "pitcher" else 0.30
        pedigreed = _high_pedigree(input_row)
        penalty = base * (1.0 - max_soft * prior_q)
        if pedigreed:
            penalty *= 0.70
        if str(availability.get("status") or "") == "injured":
            penalty *= 0.60
        # De-stack: the availability layer already took a staleness haircut for
        # this same no-current-season signal -- credit it back so it isn't
        # double-counted.
        if availability.get("risk_basis") == "sample_staleness":
            disc = _clean_float(availability.get("risk_discount")) or 0.0
            sb = _clean_float(components.get("score_before_availability_adjustment")) or 0.0
            penalty += disc * sb
        penalty = round(min(0.0, penalty), 2)
        if penalty < 0:
            adjustments.append(
                {
                    "bucket": "no_current_season_activity",
                    "label": "No current-season stat line",
                    "level": level,
                    "role": role,
                    "source_kind": factual.get("source_kind") or "missing",
                    "prior_year_strength": round(prior_q, 3),
                    "high_pedigree": pedigreed,
                    "basis": "calibration_judgment_not_outcome_gated",
                    "adjustment": penalty,
                    "reason": (
                        "No current-season MiLB stat line: the card leans on a prior "
                        "season sample, so the profile is ranked behind players with "
                        "current-season evidence. Softened by prior-year strength, "
                        "draft pedigree, and injury status."
                    ),
                }
            )

    if source == PEDIGREE_SCORE_SOURCE and level not in UPPER_LEVEL_BUCKETS:
        adjustments.append(
            {
                "bucket": "lower_minors_pedigree_score_source",
                "label": "Lower-minors context",
                "level": level,
                "score_source": source,
                "adjustment": LOWER_MINORS_PEDIGREE_SCORE_ADJUSTMENT,
                "reason": (
                    "Lower-minors pedigree-only profiles are kept slightly behind "
                    "upper-level evidence until the model has stronger current samples."
                ),
            }
        )

    sample = _clean_float(availability.get("sample"))
    sample_unit = str(availability.get("sample_unit") or "").upper()
    if sample is None:
        sample = _sample_size(input_row or {}, str(role or ""))
        sample_unit = "IP" if role == "pitcher" else "PA"
    reliability = _clean_float(components.get("sample_reliability"))
    status = str(availability.get("status") or "")
    if (
        source in {"prospect_model_v0_6", PEDIGREE_SCORE_SOURCE}
        and status == "thin_current_sample"
        and reliability is not None
    ):
        # The penalty scales with how little evidence exists (1 - reliability),
        # so a 2-IP line drops far more than a near-full one. This catches the
        # governor's failing "thin upper-level pitcher" bucket (e.g. an AAA arm
        # under 45 IP) plus any other thin-sample profile floating up on model
        # or pedigree strength, role-agnostically.
        regression = 200.0 if role == "hitter" else 50.0
        current_reliability = (
            100.0 * sample / (sample + regression)
            if sample is not None and sample > 0
            else 0.0
        )
        thinness = max(0.0, min(1.0, 1.0 - current_reliability / 100.0))
        penalty = -THIN_SAMPLE_CONFIDENCE_PENALTY_MAX * thinness
        # Credit draft pedigree (a large-N outcome signal: ~52% vs 16% established)
        # so a thin-but-pedigreed profile isn't sunk as hard as a thin no-name --
        # decayed once the pedigree goes stale (the pro record is then the evidence).
        spare = _pedigree_spare_credit(input_row, current_season)
        if spare:
            penalty *= 1.0 - 0.25 * spare
        penalty = round(penalty, 2)
        if penalty < 0:
            adjustments.append(
                {
                    "bucket": "thin_current_sample_confidence",
                    "label": "Thin current sample",
                    "level": level,
                    "role": role,
                    "score_source": source,
                    "sample": round(sample, 3) if sample is not None else None,
                    "sample_unit": sample_unit or None,
                    "sample_reliability": round(reliability, 2),
                    "adjustment": penalty,
                    "reason": (
                        "Thin current samples are ranked by a lower-confidence-bound "
                        "score so unproven profiles sort behind players with fuller "
                        "evidence; the penalty scales with sample reliability."
                    ),
                }
            )

    if (
        source in {"prospect_model_v0_6", PEDIGREE_SCORE_SOURCE}
        and status != "thin_current_sample"
        and reliability is not None
        and reliability < MODERATE_THIN_RELIABILITY_FLOOR
    ):
        # The haircut concentrates on thin lines whose value rides the thin sample alone
        # (the Hernandez case). Draft pedigree is independent support, so it SPARES the
        # haircut -- fully while fresh (a Willits-type consensus #3 the model under-rates),
        # then decaying as the pedigree goes stale and the pro record becomes the evidence
        # (the Hughes case: a 4-yr-stale top-10 pick the industry has walked to FV 40).
        deficit = max(
            0.0,
            (MODERATE_THIN_RELIABILITY_FLOOR - reliability)
            / MODERATE_THIN_RELIABILITY_FLOOR,
        )
        penalty = -MODERATE_THIN_CONFIDENCE_PENALTY_K * deficit
        career_validated = _career_validated_discipline(career_entry, role)
        if career_validated:
            # The thin line continues a proven multi-year contact/discipline skill, so
            # give back ~45% of the haircut -- the sample is more trustworthy than its
            # size alone implies (the career the point-estimate model is blind to).
            penalty *= MODERATE_THIN_CAREER_SOFTENER
        pedigree_spare = _pedigree_spare_credit(input_row, current_season)
        penalty *= 1.0 - pedigree_spare
        penalty = round(penalty, 2)
        if penalty < 0:
            adjustments.append(
                {
                    "bucket": "moderate_thin_sample_confidence",
                    "label": "Moderate thin sample",
                    "level": level,
                    "role": role,
                    "score_source": source,
                    "sample": round(sample, 3) if sample is not None else None,
                    "sample_unit": sample_unit or None,
                    "sample_reliability": round(reliability, 2),
                    "adjustment": penalty,
                    "career_validated": career_validated,
                    "pedigree_spare_credit": round(pedigree_spare, 3),
                    "reason": (
                        "A gaudy line whose own model reliability is below the floor "
                        "is discounted toward the confidence the model already assigns "
                        "it, so thin-sample performance doesn't outrank fuller evidence."
                    ),
                }
            )

    # INV-SELECT-2: read the impact ratios from the scored-line context, not the raw
    # display input_row, so the upper-level low-impact penalty fires off the line that
    # produced the score. factual_current_context rides the scored line via
    # _input_row_sort_key's max-sample selection.
    factual = (components or {}).get("factual_current_context") or {}
    iso = _clean_float(factual.get("iso"))
    ops = _clean_float(factual.get("ops"))
    if (
        source == "prospect_model_v0_6"
        and role == "hitter"
        and level in {"AA", "AAA"}
        and sample_unit == "PA"
        and sample >= UPPER_LEVEL_HITTER_LOW_IMPACT_SAMPLE_PA
        and iso is not None
        and iso < UPPER_LEVEL_HITTER_LOW_IMPACT_ISO
        and ops is not None
        and ops < UPPER_LEVEL_HITTER_LOW_IMPACT_OPS
    ):
        adjustments.append(
            {
                "bucket": "upper_level_low_impact_hitter_model_sample",
                "label": "Upper-level impact floor",
                "level": level,
                "role": role,
                "score_source": source,
                "sample": round(sample, 3),
                "sample_unit": sample_unit,
                "sample_threshold": UPPER_LEVEL_HITTER_LOW_IMPACT_SAMPLE_PA,
                "iso": round(iso, 3),
                "iso_threshold": UPPER_LEVEL_HITTER_LOW_IMPACT_ISO,
                "ops": round(ops, 3),
                "ops_threshold": UPPER_LEVEL_HITTER_LOW_IMPACT_OPS,
                "adjustment": UPPER_LEVEL_HITTER_LOW_IMPACT_ADJUSTMENT,
                "reason": (
                    "Upper-level hitter model scores with full current samples but "
                    "limited game impact are kept slightly behind comparable bats "
                    "with stronger impact evidence."
                ),
            }
        )

    if not adjustments:
        return score, components

    total_adjustment = round(
        sum(float(adjustment["adjustment"]) for adjustment in adjustments),
        2,
    )
    adjusted_score = max(0.0, score + total_adjustment)
    next_components = dict(components)
    next_components["score_before_bucket_calibration"] = round(score, 2)
    primary = adjustments[0]
    next_components["bucket_calibration"] = {
        "version": BUCKET_CALIBRATION_VERSION,
        "bucket": primary["bucket"],
        "label": primary["label"],
        "level": primary.get("level"),
        "adjustment": total_adjustment,
        "reason": primary["reason"],
        "rules": adjustments,
    }
    return round(adjusted_score, 2), next_components


def _confidence(
    source: str,
    model_profile: dict | None,
    reliability: float | None,
    current_context: dict | None = None,
) -> str:
    if source in {PEDIGREE_SCORE_SOURCE, "universal_fallback", "identity_only_fallback"}:
        # A pedigree/fallback SCORE no longer forces "low" confidence on its own.
        # The model leans on pedigree for lower-minors value, but a prospect with
        # a substantial current-season line (e.g. 150+ PA at A-ball) is not "low
        # confidence" just because of that scoring choice. Only genuinely thin
        # samples (band "thin": <50 PA / <15 IP) or players with no current line
        # stay "low"; a real current sample earns "medium" (never "high", since
        # the value itself is still pedigree-led).
        band = str((current_context or {}).get("skill_band") or "").lower()
        if not current_context or band == "thin":
            return "low"
        return "medium"
    role_gate = (model_profile or {}).get("role_gate")
    impact_gate = (model_profile or {}).get("impact_gate")
    if role_gate == "active" and impact_gate == "active" and (reliability or 0.0) >= 45:
        return "high"
    return "medium"


def _uncertainty_component(
    score: float,
    source: str,
    confidence: str,
    components: dict,
) -> dict:
    """Attach a display-only uncertainty band around the final score."""
    reliability = _clean_float(components.get("sample_reliability"))
    availability_discount = _clean_float(
        components.get("availability_risk_discount")
    ) or 0.0
    factual_context = components.get("factual_current_context")
    skill_band = (
        str((factual_context or {}).get("skill_band") or "").lower()
        if isinstance(factual_context, dict)
        else ""
    )

    width = SCORE_SOURCE_UNCERTAINTY_WIDTH.get(source, 14.0)
    width += CONFIDENCE_UNCERTAINTY_ADJUSTMENT.get(confidence, 2.0)
    if reliability is None:
        width += 3.0
    elif reliability >= 70.0:
        width -= 1.0
    elif reliability < 25.0:
        width += 4.0
    elif reliability < 45.0:
        width += 2.0
    if availability_discount > 0:
        width += min(5.0, availability_discount * 100.0)
    if skill_band in CAUTION_SKILL_BANDS:
        width += 2.0

    width = round(max(4.0, min(24.0, width)), 1)
    lower = round(max(0.0, score - width), 2)
    upper = round(min(100.0, score + width), 2)
    if width <= 8.0:
        band = "tight"
    elif width <= 14.0:
        band = "moderate"
    else:
        band = "wide"
    return {
        "version": UNCERTAINTY_VERSION,
        "kind": "display_only_score_interval",
        "band": band,
        "width": width,
        "lower": lower,
        "upper": upper,
        "score": round(score, 2),
        "drivers": {
            "score_source": source,
            "confidence": confidence,
            "sample_reliability": _round(reliability),
            "availability_risk_discount": _round(availability_discount, 3),
            "skill_band": skill_band or None,
        },
        "score_effect": "none",
    }


def _score_source_sort_order(source: str | None) -> int:
    return {
        "prospect_model_v0_6": 0,
        PEDIGREE_SCORE_SOURCE: 1,
        "universal_fallback": 2,
        "identity_only_fallback": 3,
    }.get(source or "", 4)


def _drivers(model_profile: dict | None, layer_profile: dict) -> list[str]:
    values: list[str] = []
    for key in ("drivers", "impact_drivers"):
        current = (model_profile or {}).get(key)
        if isinstance(current, list):
            values.extend(str(item) for item in current[:4])
        elif isinstance(current, str):
            values.append(current)
    if values:
        return values[:6]
    signal = layer_profile.get("dynasty_signal") or {}
    return [
        f"role+ probability {signal.get('role_or_better_probability')}",
        f"star probability {signal.get('star_ceiling_probability')}",
    ]


def _context(
    input_row: dict | None,
    role: str | None,
    service_row: dict | None = None,
    rookie_limits: dict[str, float] | None = None,
    milb_entry: dict | None = None,
) -> dict:
    input_stat_line = _input_stat_line(input_row, role)
    use_input_stat_line = bool(input_stat_line)
    stat_line = input_stat_line

    # ValuCast-owned MLB-equivalent translation + best-single-level, computed from
    # ValuCast's own raw MiLB rows.
    milb_rows = (milb_entry or {}).get("rows") or []
    owned_translated = translate_peripherals(milb_rows, role) if milb_rows else None
    stat_line_translated = owned_translated
    stat_line_translated_source = (
        "valucast_owned" if owned_translated is not None
        else None
    )
    best_single = None
    combined_line = (
        combined_season_stat_line(
            history_rows=milb_rows,
            role=role,
            season=(milb_entry or {}).get("current_season"),
        )
        if milb_rows
        else None
    )
    if milb_rows and stat_line:
        best_single = best_single_level_stat_line(
            current_line=stat_line,
            current_level=(owned_translated or {}).get("level"),
            history_rows=milb_rows,
            role=role,
            season=(milb_entry or {}).get("current_season"),
        )
    stat_context = {}
    if use_input_stat_line:
        stat_line_source = "valucast_input_contract"
        stat_context = _stat_line_context(input_row, role)
    else:
        stat_line_source = None
    bats = _hand_code((input_row or {}).get("bats"))
    throws = _hand_code((input_row or {}).get("throws"))
    context = {
        "bats": bats,
        "throws": throws,
        "stat_line": stat_line,
        "stat_line_source": stat_line_source,
        **stat_context,
        "stat_line_translated": stat_line_translated,
        "stat_line_translated_source": stat_line_translated_source,
        "best_single_level_stat_line": best_single,
        "combined_season_stat_line": combined_line,
    }
    graduation = _graduation_context(service_row, role, rookie_limits or {})
    if graduation:
        context["graduation_context"] = graduation
    return context


def _missing_sample(rows: list[dict], missing_keys: set[tuple[str, str]], limit: int = 15) -> list[dict]:
    missing = []
    for row in sorted(rows, key=lambda item: str(item.get("name") or "")):
        role = row.get("role") if row.get("role") in {"hitter", "pitcher"} else infer_role(
            row.get("positions")
        )
        key = identity_key(row.get("mlbam_id"), role)
        if key in missing_keys:
            missing.append(
                {
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": role,
                    "universe_source": row.get("universe_source"),
                }
            )
        if len(missing) >= limit:
            break
    return missing


def _current_stat_context_mismatches(
    board: list[dict],
    expected_by_key: dict[tuple[str, str], dict],
    limit: int = 20,
) -> list[dict]:
    mismatches = []
    for row in board:
        key = identity_key(row.get("mlbam_id"), row.get("role"))
        if key not in expected_by_key:
            continue
        expected = expected_by_key[key]
        context = row.get("context_only") or {}
        expected_season = _clean_float(expected.get("sample_season"))
        actual_season = _clean_float(context.get("stat_line_sample_season"))
        expected_sample = round(_sample_size(expected, str(row.get("role"))), 1)
        actual_sample = _clean_float(context.get("stat_line_sample"))
        actual_sample_rounded = round(actual_sample, 1) if actual_sample is not None else None
        if (
            context.get("stat_line_source") == "valucast_input_contract"
            and context.get("stat_line_source_kind") == "current_season"
            and (
                expected_season is None
                or actual_season is None
                or int(expected_season) == int(actual_season)
            )
            and actual_sample_rounded == expected_sample
        ):
            continue
        mismatches.append(
            {
                "rank": row.get("rank"),
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "stat_line_source": context.get("stat_line_source"),
                "stat_line_source_kind": context.get("stat_line_source_kind"),
                "stat_line_sample_season": context.get("stat_line_sample_season"),
                "stat_line_sample": context.get("stat_line_sample"),
                "expected_source_kind": expected.get("source_kind"),
                "expected_sample_season": expected.get("sample_season"),
                "expected_sample": expected_sample,
            }
        )
        if len(mismatches) >= limit:
            break
    return mismatches


def _validation(
    prospect_universe: dict,
    dynasty_layer: dict,
    input_contract: dict,
    prospect_rows: list[dict],
    board: list[dict],
    duplicate_keys: list[tuple[str, str]],
    missing_mlbam_count: int,
    unmatched_layer_keys: set[tuple[str, str]],
    identity_only_fallback_count: int,
    current_stat_context_mismatches: list[dict],
    active_mlb_roster_ids: set[str] | None = None,
    active_mlb_roster_excluded_count: int = 0,
    stale_inactive_excluded_count: int = 0,
    manual_graduated_excluded_count: int = 0,
    mlb_roster_status_ready: bool = False,
    require_mlb_roster_status: bool = False,
) -> dict:
    universe_date = _generated_date(prospect_universe)
    layer_date = _generated_date(dynasty_layer)
    input_date = _generated_date(input_contract)
    same_day = bool(universe_date and layer_date and input_date) and len(
        {universe_date, layer_date, input_date}
    ) == 1
    eligible_prospect_row_count = max(
        len(prospect_rows)
        - active_mlb_roster_excluded_count
        - stale_inactive_excluded_count
        - manual_graduated_excluded_count,
        0,
    )
    coverage_rate = (
        round(len(board) / eligible_prospect_row_count, 4)
        if eligible_prospect_row_count
        else 0.0
    )
    top_200_scores = {row["score"] for row in board[:200]}
    active_mlb_roster_ids = active_mlb_roster_ids or set()
    active_mlb_roster_overlap_count = sum(
        1 for row in board if str(row.get("mlbam_id")) in active_mlb_roster_ids
    )
    blockers = []
    if coverage_rate < MIN_PUBLIC_COVERAGE_RATE:
        blockers.append(
            "Current ValuCast prospect-model coverage is below the public migration threshold."
        )
    if missing_mlbam_count:
        blockers.append("Some ValuCast prospect-universe rows still lack MLBAM identity.")
    if duplicate_keys:
        blockers.append("Duplicate MLBAM+role identities exist in the prospect universe.")
    if len(top_200_scores) < MIN_TOP_200_UNIQUE_SCORE_COUNT:
        blockers.append("Top-200 score separation is not strong enough for publication.")
    if not same_day:
        blockers.append("Input artifacts were not generated on the same date.")
    if current_stat_context_mismatches:
        blockers.append(
            "Current prospect stat context did not select the newest factual current-season row."
        )
    if require_mlb_roster_status and not mlb_roster_status_ready:
        blockers.append(
            "MLB roster status artifact is required for active-roster prospect exclusion."
        )
    if active_mlb_roster_overlap_count:
        blockers.append("Active MLB roster identities remain on the prospect board.")

    return {
        "public_migration_ready": not blockers,
        "same_day_freshness": same_day,
        "generated_dates": {
            "prospect_universe": universe_date,
            "dynasty_layer": layer_date,
            "prospect_input_contract": input_date,
        },
        "prospect_universe_count": len(prospect_rows),
        "ranked_count": len(board),
        "missing_mlbam_count": missing_mlbam_count,
        "unmatched_dynasty_layer_count": len(unmatched_layer_keys),
        "identity_only_fallback_count": identity_only_fallback_count,
        "mlb_roster_status_ready": mlb_roster_status_ready,
        "active_mlb_roster_excluded_count": active_mlb_roster_excluded_count,
        "stale_inactive_excluded_count": stale_inactive_excluded_count,
        "active_mlb_roster_overlap_count": active_mlb_roster_overlap_count,
        "current_stat_context_mismatch_count": len(current_stat_context_mismatches),
        "current_stat_context_mismatch_sample": current_stat_context_mismatches[:20],
        "coverage_rate": coverage_rate,
        "duplicate_identity_count": len(duplicate_keys),
        "duplicate_identities": [
            {"mlbam_id": mlbam_id, "role": role}
            for mlbam_id, role in duplicate_keys[:20]
        ],
        "top_200_unique_score_count": len(top_200_scores),
        "ranks_contiguous": [row["rank"] for row in board] == list(range(1, len(board) + 1)),
        "unmatched_sample": _missing_sample(prospect_rows, unmatched_layer_keys),
        "blockers": blockers,
    }


def build_prospect_rank_v1(
    prospect_universe: dict,
    dynasty_layer: dict,
    prospect_model: dict,
    input_contract: dict,
    prospect_availability: dict | None = None,
    milb_history_by_key: dict | None = None,
    mlb_roster_status: dict | None = None,
    require_mlb_roster_status: bool = False,
) -> dict:
    model_by_key = _model_lookup(prospect_model)
    layer_by_key = _layer_lookup(dynasty_layer)
    input_by_key = _input_lookup(input_contract)
    expected_current_stat_by_key = _current_stat_expectation_lookup(input_contract)
    service_by_key = _service_lookup(input_contract)
    rookie_limits = _rookie_limits(input_contract)
    availability_by_key = availability_lookup(prospect_availability)
    active_roster_by_mlbam = active_roster_lookup(mlb_roster_status)
    active_mlb_roster_ids = set(active_roster_by_mlbam)
    manual_graduated_ids = _manual_graduated_ids()
    sts_by_mlbam = _snapshot_by_mlbam(STS_CONSENSUS_PATH)
    fg_by_mlbam = _snapshot_by_mlbam(FG_FV_SNAPSHOT_PATH)
    pl_by_mlbam = _snapshot_by_mlbam(PROSPECTSLIVE_PATH)
    pipeline_by_mlbam = _snapshot_by_mlbam(PIPELINE_PATH)
    mlb_roster_status_ready = bool(
        (mlb_roster_status or {}).get("validation", {}).get("ready_for_public_snapshot")
    )

    rows = _universe_rows(prospect_universe)
    _apply_role_quantile_model_score_normalization(
        _board_model_score_normalization_rows(
            rows,
            model_by_key,
            input_by_key,
            active_mlb_roster_ids,
        )
    )
    seen: set[tuple[str, str]] = set()
    duplicate_keys: list[tuple[str, str]] = []
    missing_mlbam_count = 0
    unmatched_layer_keys: set[tuple[str, str]] = set()
    identity_only_fallback_count = 0
    active_mlb_roster_excluded_count = 0
    stale_inactive_excluded_count = 0
    manual_graduated_excluded_count = 0
    board = []
    active_mlb_roster_board = []

    for universe_row in rows:
        role = universe_row.get("role")
        key = identity_key(universe_row.get("mlbam_id"), role)
        if key is None:
            missing_mlbam_count += 1
            continue
        # Active-roster prospects stay OFF the ranked board, but we retain a scored row
        # so the dynasty snapshot's call-up bridge can surface known graduates who aren't
        # yet in the MLB layer (e.g. <40-IP call-ups). Routed to active_mlb_roster_board.
        is_active_mlb_roster = key[0] in active_mlb_roster_ids
        if is_active_mlb_roster:
            active_mlb_roster_excluded_count += 1
        if key[0] in manual_graduated_ids:
            manual_graduated_excluded_count += 1
            continue
        if key in seen:
            duplicate_keys.append(key)
            continue
        seen.add(key)
        layer_profile = layer_by_key.get(key)
        model_profile = model_by_key.get(key)
        input_row = input_by_key.get(key)
        staleness_years = _clean_float((input_row or {}).get("sample_staleness_years"))
        if (
            staleness_years is not None
            and staleness_years >= INACTIVE_BOARD_EXCLUSION_STALENESS_YEARS
        ):
            stale_inactive_excluded_count += 1
            continue
        service_row = service_by_key.get(key)
        availability_profile = availability_by_key.get(key)
        if layer_profile:
            score, source, components = _score_components(
                model_profile,
                layer_profile,
                input_row,
            )
        else:
            unmatched_layer_keys.add(key)
            identity_only_fallback_count += 1
            score, source, components = _identity_only_score_components(input_row, role)
        score, components = apply_availability_adjustment(
            score,
            components,
            availability_profile,
        )
        score, components = _bucket_calibration_adjustment(
            score,
            source,
            layer_profile,
            input_row,
            universe_row,
            components,
            (milb_history_by_key or {}).get(key),
        )
        confidence = _confidence(
            source,
            model_profile,
            components.get("sample_reliability"),
            components.get("factual_current_context"),
        )
        components = {
            **components,
            "uncertainty": _uncertainty_component(
                score,
                source,
                confidence,
                components,
            ),
        }
        display_age = (availability_profile or {}).get("age")
        if display_age is None:
            display_age = universe_row.get("age")
        if display_age is None:
            display_age = (layer_profile or {}).get("age")
        display_level = (
            (availability_profile or {}).get("level")
            or universe_row.get("level")
            or (layer_profile or {}).get("level")
        )
        eta = universe_row.get("eta")
        target_board = active_mlb_roster_board if is_active_mlb_roster else board
        target_board.append(
            {
                "mlbam_id": universe_row.get("mlbam_id"),
                "name": universe_row.get("name")
                or (layer_profile or {}).get("name"),
                "normalized_name": universe_row.get("normalized_name")
                or (layer_profile or {}).get("normalized_name"),
                "role": role,
                "positions": universe_row.get("positions"),
                "mlb_team": universe_row.get("mlb_team"),
                "age": display_age,
                "level": display_level,
                "eta": eta,
                "eta_window": eta_window({"eta": eta, "level": display_level}),
                "universe_source": universe_row.get("universe_source"),
                "score": score,
                "score_source": source,
                "confidence": confidence,
                "components": components,
                "dynasty_signal": (layer_profile or {}).get("dynasty_signal"),
                "drivers": _drivers(model_profile, layer_profile or {}),
                "context_only": _context(
                    input_row,
                    role,
                    service_row,
                    rookie_limits,
                    milb_entry=(milb_history_by_key or {}).get(key),
                ),
            }
        )
        _merge_external_consensus(
            target_board[-1], key[0], sts_by_mlbam, fg_by_mlbam, pl_by_mlbam,
            pipeline_by_mlbam,
        )

    board.sort(
        key=lambda row: (
            -row["score"],
            _score_source_sort_order(row.get("score_source")),
            str(row.get("role") or ""),
            str(row.get("name") or ""),
            int(row.get("mlbam_id") or 0),
        )
    )
    for rank, row in enumerate(board, 1):
        row["rank"] = rank

    validation = _validation(
        prospect_universe,
        dynasty_layer,
        input_contract,
        rows,
        board,
        duplicate_keys,
        missing_mlbam_count,
        unmatched_layer_keys,
        identity_only_fallback_count,
        _current_stat_context_mismatches(board, expected_current_stat_by_key),
        active_mlb_roster_ids=active_mlb_roster_ids,
        active_mlb_roster_excluded_count=active_mlb_roster_excluded_count,
        stale_inactive_excluded_count=stale_inactive_excluded_count,
        manual_graduated_excluded_count=manual_graduated_excluded_count,
        mlb_roster_status_ready=mlb_roster_status_ready,
        require_mlb_roster_status=require_mlb_roster_status,
    )
    coverage_repair_needed = (
        validation["coverage_rate"] < MIN_PUBLIC_COVERAGE_RATE
        or validation["missing_mlbam_count"] > 0
        or validation["duplicate_identity_count"] > 0
    )
    generated_at = (
        prospect_universe.get("generated_at")
        or dynasty_layer.get("generated_at")
        or input_contract.get("generated_at")
    )
    return {
        "status": "candidate_ready" if not validation["blockers"] else "blocked",
        "rank_name": RANK_NAME,
        "rank_version": RANK_VERSION,
        "generated_at": generated_at,
        "candidate_count": len(rows),
        "ranked_count": len(board),
        "active_mlb_roster_board": active_mlb_roster_board,
        "rank_contract": {
            "purpose": (
                "Produce a ValuCast-owned prospect ordering for canonical "
                "ValuCast public snapshots after validation and governor gates pass."
            ),
            "score_range": [0.0, 100.0],
            "score_weights": SCORE_WEIGHTS,
            "model_component_weights": MODEL_COMPONENT_WEIGHTS,
            "fallback_score_cap": FALLBACK_SCORE_CAP,
            "identity_only_score_cap": IDENTITY_ONLY_SCORE_CAP,
            "missing_investment_context_score": MISSING_INVESTMENT_CONTEXT_SCORE,
            "pedigree_fallback_score_source": PEDIGREE_SCORE_SOURCE,
            "pedigree_min_investment_score": PEDIGREE_MIN_INVESTMENT_SCORE,
            "pedigree_score_caps": {
                "hitter": PEDIGREE_HITTER_SCORE_CAP,
                "pitcher": PEDIGREE_PITCHER_SCORE_CAP,
            },
            "bucket_calibration": {
                "version": BUCKET_CALIBRATION_VERSION,
                "upper_level_buckets": sorted(UPPER_LEVEL_BUCKETS),
                "lower_minors_pedigree_score_adjustment": LOWER_MINORS_PEDIGREE_SCORE_ADJUSTMENT,
                "thin_upper_level_pitcher_model_sample_ip": THIN_UPPER_LEVEL_PITCHER_SAMPLE_IP,
                "thin_upper_level_pitcher_model_adjustment": THIN_UPPER_LEVEL_PITCHER_MODEL_ADJUSTMENT,
                "upper_level_hitter_low_impact_sample_pa": UPPER_LEVEL_HITTER_LOW_IMPACT_SAMPLE_PA,
                "upper_level_hitter_low_impact_iso": UPPER_LEVEL_HITTER_LOW_IMPACT_ISO,
                "upper_level_hitter_low_impact_ops": UPPER_LEVEL_HITTER_LOW_IMPACT_OPS,
                "upper_level_hitter_low_impact_adjustment": UPPER_LEVEL_HITTER_LOW_IMPACT_ADJUSTMENT,
                "scope": "score_source_level_and_factual_current_stat_bucket_only",
            },
            "factual_current_context": {
                "version": FACTUAL_CURRENT_CONTEXT_VERSION,
                "source": "validated_prospect_input_contract_current_rows",
                "score_effect": (
                    "context_for_calibration_display_and_quality_review; "
                    "not a DD, market, or public-rank signal"
                ),
                "hitter_fields": [
                    "level",
                "sample",
                "source_kind",
                "sample_season",
                "ops",
                    "iso",
                    "k_pct",
                    "bb_pct",
                    "bb_minus_k_pct",
                    "skill_band",
                ],
                "pitcher_fields": [
                    "level",
                "sample",
                "source_kind",
                "sample_season",
                "starter_role",
                    "era",
                    "whip",
                    "k_per_9",
                    "bb_per_9",
                    "k_bb_pct",
                    "skill_band",
                ],
            },
            "prospect_universe_source": "valucast_prospect_universe",
            "context_only_fields": [
                "source_ranks",
                "value_history",
                "stat_line",
                "stat_line_source",
                "stat_line_source_kind",
                "stat_line_level",
                "stat_line_team",
                "stat_line_sample",
                "stat_line_sample_unit",
                "stat_line_sample_season",
                "graduation_context",
                "stat_line_translated",
            ],
            "prohibited_score_inputs": PROHIBITED_SCORE_INPUTS,
            "external_rankings_used_for_score": False,
            "dd_values_used_for_score": False,
            "market_independent": True,
            "live_surface": True,
            "tie_policy": "Ranks are contiguous after deterministic non-score tiebreakers.",
        },
        "input_artifacts": {
            "prospect_universe_schema_version": prospect_universe.get("schema_version"),
            "prospect_universe_artifact": prospect_universe.get("artifact"),
            "prospect_universe_candidate_count": prospect_universe.get("candidate_count"),
            "prospect_model_version": prospect_model.get("model_version"),
            "dynasty_layer_version": dynasty_layer.get("layer_version"),
            "prospect_input_schema_version": input_contract.get("schema_version"),
            "prospect_availability_version": (prospect_availability or {}).get(
                "artifact_version"
            ),
            "prospect_availability_profile_count": (
                prospect_availability or {}
            ).get("profile_count"),
        },
        "promotion": {
            "live_consumer": "candidate_ready" if not validation["blockers"] else "blocked",
            "feeds_live_valucast_rank": not validation["blockers"],
            "feeds_live_dd_value": False,
            "next_allowed_step": (
                "human_review_and_coverage_repair"
                if coverage_repair_needed
                else "canonical_snapshot_build_and_quality_governor"
            ),
            "reason": (
                validation["blockers"][0]
                if validation["blockers"]
                else "Prospect Rank v1 passes coverage, identity, freshness, and separation gates."
            ),
        },
        "validation": validation,
        "limitations": [
            "Public ValuCast surfaces consume this rank only through the canonical snapshot and quality governor.",
            "ValuCast prospect-universe rows define membership.",
            "Identity-only fallback rows remain for prospects absent from the current ValuCast layer.",
            "Identity-only fallback rows have verified MLBAM identity but no eligible ValuCast model sample yet.",
            "Fallback-only lower-minors profiles are capped until the expanded model earns publication-grade evidence.",
        ],
        "board": board,
    }


def archive_rank(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "rank_version": payload["rank_version"],
        "generated_at": payload["generated_at"],
        "candidate_count": payload["candidate_count"],
        "ranked_count": payload["ranked_count"],
        "validation": payload["validation"],
        "board": payload["board"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_prospect_rank_v1(
    prospect_universe_path: Path = PROSPECT_UNIVERSE_PATH,
    dynasty_layer_path: Path = DYNASTY_LAYER_PATH,
    prospect_model_path: Path = PROSPECT_MODEL_PATH,
    input_contract_path: Path = INPUT_CONTRACT_PATH,
    availability_path: Path | None = AVAILABILITY_PATH,
    mlb_roster_status_path: Path | None = MLB_ROSTER_STATUS_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    prospect_universe = json.loads(prospect_universe_path.read_text(encoding="utf-8"))
    dynasty_layer = json.loads(dynasty_layer_path.read_text(encoding="utf-8"))
    prospect_model = json.loads(prospect_model_path.read_text(encoding="utf-8"))
    input_contract = json.loads(input_contract_path.read_text(encoding="utf-8"))
    prospect_availability = (
        json.loads(availability_path.read_text(encoding="utf-8"))
        if availability_path is not None and availability_path.exists()
        else None
    )
    mlb_roster_status = (
        json.loads(mlb_roster_status_path.read_text(encoding="utf-8"))
        if mlb_roster_status_path is not None and mlb_roster_status_path.exists()
        else None
    )
    milb_history_by_key = load_milb_history_index()
    payload = build_prospect_rank_v1(
        prospect_universe,
        dynasty_layer,
        prospect_model,
        input_contract,
        prospect_availability=prospect_availability,
        milb_history_by_key=milb_history_by_key,
        mlb_roster_status=mlb_roster_status,
        require_mlb_roster_status=True,
    )
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
    archive_path, archive_changed = archive_rank(
        payload,
        date_str=parsed_now.date().isoformat(),
        archive_dir=archive_dir,
    )
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "ranked_count": payload["ranked_count"],
        "candidate_count": payload["candidate_count"],
        "coverage_rate": payload["validation"]["coverage_rate"],
        "live_consumer": payload["promotion"]["live_consumer"],
    }
