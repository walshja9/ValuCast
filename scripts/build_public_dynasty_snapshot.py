"""Build the shadow ValuCast-owned public dynasty snapshot."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.milb_stat_freshness import build_milb_stat_freshness_audit  # noqa: E402
from quality.valucast_governor import evaluate_quality_governor  # noqa: E402
from web.public_snapshot_store import required_field_problems  # noqa: E402

PROSPECT_INPUTS_PATH = ROOT / "data" / "prospects" / "prospect_model_inputs.json"
MLB_LAYER_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
MLB_TRACK_RECORD_PATH = ROOT / "data" / "models" / "valucast_mlb_track_record.json"
MLB_ROSTER_STATUS_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
PROSPECT_RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
PROSPECT_COVERAGE_AUDIT_PATH = (
    ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"
)
PROSPECT_PEAK_PROJECTION_PATH = (
    ROOT / "data" / "models" / "valucast_prospect_peak_projection_v1.json"
)
BUY_SIGNALS_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
BUY_REVIEW_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_review.json"
OUTPUT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"

SCHEMA_VERSION = "1.1"
ARTIFACT_NAME = "valucast_public_dynasty_snapshot"
COMMON_VALUE_SCALE = "0_100_valucast_dynasty_score"
CALIBRATION_METHOD = "raw_common_scale_certification_v1"
TWO_WAY_VALUE_SOURCE = "valucast_mlb_two_way_combined_v0_1"
TWO_WAY_SECONDARY_VALUE_WEIGHT = 0.65
MLB_COLLISION_PROMOTION_MAX_RANK = 75
MLB_COLLISION_PROMOTION_MIN_VALUE = 45.0
MLB_COLLISION_PROMOTION_MIN_MARGIN = 15.0
# Graduation-transition floor: a freshly called-up prospect's value should not crater to
# a 3-PA MLB line. Floor it at this fraction of his retained prospect score, fading as
# he accrues MLB sample.
GRAD_FLOOR_DISCOUNT = 0.75
# Calendar-time decay window: the floor fully releases this many days after MLB debut
# (~a season of MLB sample, by which point the raw MLB value stands on its own). This is a
# taste dial like GRAD_FLOOR_DISCOUNT; the accountability harness recalibrates it once
# graduates' realized outcomes accrue. Falls back to the rookie-eligibility ratio when no
# debut date is known.
GRAD_FLOOR_DECAY_DAYS = 180

MIN_PROSPECT_COVERAGE_RATE = 0.98
MIN_TOP_200_UNIQUE_SCORE_COUNT = 150
MIN_MLB_ROWS_ABOVE_TOP_PROSPECT = 3
MAX_MLB_ROWS_ABOVE_TOP_PROSPECT = 50
MIN_MLB_HORIZON_YEARS = 3


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _date_part(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _parse_date(value: str | None):
    iso = _date_part(value)
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso).date()
    except ValueError:
        return None


def _positions(row: dict) -> list[str]:
    positions = [str(position) for position in row.get("positions") or [] if position]
    if positions:
        return positions
    return ["P"] if row.get("role") == "pitcher" else ["DH"]


def _clean_float(value) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _clean_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _snapshot_id(row: dict) -> str:
    return f"vc_prospect_{row['mlbam_id']}_{row['role']}"


def _identity_key(row: dict) -> tuple[str, str] | None:
    if row.get("mlbam_id") in (None, "") or row.get("role") not in {"hitter", "pitcher", "two_way"}:
        return None
    return str(row["mlbam_id"]), row["role"]


def _mlbam_id(row: dict) -> str | None:
    value = row.get("mlbam_id")
    if value in (None, ""):
        return None
    return str(value)


def _is_confirmed_mlb_level_prospect(row: dict) -> bool:
    return str(row.get("level") or "").strip().upper() == "MLB"


def _mlb_collision_should_promote(prospect_row: dict, mlb_rows: list[dict]) -> bool:
    if _is_confirmed_mlb_level_prospect(prospect_row):
        return True
    prospect_value = _clean_float(prospect_row.get("value")) or 0.0
    for row in mlb_rows:
        mlb_value = _clean_float(row.get("value")) or 0.0
        mlb_rank = _clean_int(row.get("rank")) or 999999
        if (
            mlb_rank <= MLB_COLLISION_PROMOTION_MAX_RANK
            and mlb_value >= MLB_COLLISION_PROMOTION_MIN_VALUE
            and mlb_value - prospect_value >= MLB_COLLISION_PROMOTION_MIN_MARGIN
        ):
            return True
    return False


def _active_mlb_roster_ids(roster_status: dict | None) -> set[str]:
    ids = set()
    for row in (roster_status or {}).get("profiles") or []:
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, "") or row.get("active_mlb_roster") is not True:
            continue
        ids.add(str(mlbam_id))
    return ids


def _debut_dates_by_id(mlb_track_record: dict | None) -> dict[str, str]:
    debut_by_id: dict[str, str] = {}
    for profile in (mlb_track_record or {}).get("profiles") or []:
        mlbam_id = profile.get("mlbam_id")
        debut = profile.get("mlb_debut_date")
        if mlbam_id in (None, "") or not debut:
            continue
        debut_by_id[str(mlbam_id)] = debut
    return debut_by_id


def _apply_graduation_transition_floor(
    mlb_rows: list[dict],
    graduated_prospect_rows: list[dict],
    debut_by_id: dict[str, str] | None = None,
    as_of_date: str | None = None,
) -> int:
    """Keep a freshly-graduated prospect's value from cratering to a 3-PA MLB line.

    When a prospect is called up his prospect row is swapped for a thin MLB row whose
    value can fall near the production floor (a 3-PA debut, with the track-record floor
    blocked at the experience-band gate). Floor that MLB value at a market-discounted
    fraction of his retained prospect score, fading as he accrues MLB experience. The
    recovery signal — prospect score + graduation_context — already lives on the graduated
    prospect row. Decay rides CALENDAR TIME (days since MLB debut / GRAD_FLOOR_DECAY_DAYS)
    when a debut date is known, falling back to the rookie-eligibility ratio when it is not
    (so the floor never depends on the debut feed being present)."""
    debut_by_id = debut_by_id or {}
    as_of = _parse_date(as_of_date)
    floor_by_id: dict[str, dict] = {}
    for row in graduated_prospect_rows:
        mlbam_id = _mlbam_id(row)
        prospect_value = _clean_float(row.get("value"))
        if not mlbam_id or prospect_value is None or prospect_value <= 0:
            continue
        grad_context = ((row.get("context") or {}).get("graduation_context")) or {}
        ratio = _clean_float(grad_context.get("ratio")) or 0.0
        floor_by_id[mlbam_id] = {
            "prospect_value": prospect_value,
            "ratio": max(0.0, min(1.0, ratio)),
            "prospect_rank": row.get("prospect_rank"),
        }
    applied = 0
    for row in mlb_rows:
        mlbam_id = _mlbam_id(row)
        info = floor_by_id.get(mlbam_id)
        if not info:
            continue
        debut = debut_by_id.get(mlbam_id)
        debut_date = _parse_date(debut)
        if debut_date and as_of and GRAD_FLOOR_DECAY_DAYS > 0:
            days_since_debut = max(0, (as_of - debut_date).days)
            decay = min(1.0, days_since_debut / GRAD_FLOOR_DECAY_DAYS)
            decay_basis = "days_since_debut"
        else:
            days_since_debut = None
            decay = info["ratio"]
            decay_basis = "rookie_eligibility_ratio_fallback"
        floor_value = round(
            info["prospect_value"] * GRAD_FLOOR_DISCOUNT * (1.0 - decay), 2
        )
        current = _clean_float(row.get("value")) or 0.0
        row["graduation_transition"] = {
            "applied": floor_value > current,
            "prospect_value": round(info["prospect_value"], 2),
            "prospect_rank": info["prospect_rank"],
            "discount": GRAD_FLOOR_DISCOUNT,
            "decay": round(decay, 4),
            "decay_basis": decay_basis,
            "days_since_debut": days_since_debut,
            "mlb_debut_date": debut,
            "rookie_ratio": info["ratio"],
            "raw_mlb_value": round(current, 2),
            "floored_value": floor_value,
            "basis": "market_discounted_prospect_value_decaying_on_calendar_time",
        }
        if floor_value > current:
            row["value"] = floor_value
            applied += 1
    return applied


def _mlb_rows(mlb_layer: dict | None, generated_at: str) -> list[dict]:
    rows = []
    for row in (mlb_layer or {}).get("players") or []:
        context = {
            "kind": "valucast_mlb_projection_context",
            "source_layer_rank": row.get("rank"),
            "projection_value": row.get("projection_value"),
            "components": row.get("components"),
        }
        rows.append(
            {
                "id": row.get("id"),
                "player_type": "mlb",
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "positions": row.get("positions") or [],
                "team": row.get("team") or row.get("mlb_team") or "",
                "mlb_team": row.get("mlb_team") or row.get("team") or "",
                "age": row.get("age"),
                "rank": row.get("rank"),
                "value": row.get("value"),
                "value_scale": row.get("value_scale"),
                "value_source": row.get("value_source"),
                "confidence": row.get("confidence"),
                "updated_at": generated_at,
                "status": "candidate_shadow",
                "stat_line": row.get("stat_line"),
                "drivers": row.get("drivers") or [],
                "context": context,
            }
        )
    return rows


def _combined_confidence(rows: list[dict]) -> str | dict | None:
    levels = [
        row.get("confidence")
        for row in rows
        if isinstance(row.get("confidence"), str) and row.get("confidence")
    ]
    if not levels:
        return rows[0].get("confidence") if rows else None
    if "low" in levels:
        return "low"
    if "medium" in levels:
        return "medium"
    return "high"


def _merge_two_way_mlb_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    passthrough = []
    for row in rows:
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            passthrough.append(row)
            continue
        grouped.setdefault(str(mlbam_id), []).append(row)

    merged_rows = list(passthrough)
    for mlbam_id, group in grouped.items():
        roles = {row.get("role") for row in group if row.get("role")}
        if len(group) == 1 or len(roles) < 2:
            merged_rows.extend(group)
            continue

        ordered = sorted(
            group,
            key=lambda row: (
                -(_clean_float(row.get("value")) or 0.0),
                row.get("role") != "hitter",
                str(row.get("name") or ""),
            ),
        )
        primary = ordered[0]
        secondary_value = sum(
            (_clean_float(row.get("value")) or 0.0) for row in ordered[1:]
        )
        primary_value = _clean_float(primary.get("value")) or 0.0
        combined_value = min(
            100.0,
            primary_value + TWO_WAY_SECONDARY_VALUE_WEIGHT * secondary_value,
        )
        positions = []
        for row in ordered:
            for position in row.get("positions") or []:
                if position and position not in positions:
                    positions.append(position)
        drivers = []
        for row in ordered:
            for driver in row.get("drivers") or []:
                if driver not in drivers:
                    drivers.append(driver)

        component_rows = [
            {
                "role": row.get("role"),
                "id": row.get("id"),
                "rank": row.get("rank"),
                "value": row.get("value"),
                "value_source": row.get("value_source"),
                "stat_line": row.get("stat_line"),
                "drivers": row.get("drivers") or [],
                "context": row.get("context") or {},
            }
            for row in ordered
        ]
        context = {
            "kind": "valucast_mlb_two_way_context",
            "primary_role": primary.get("role"),
            "combined_value_formula": (
                "primary_value + secondary_value * "
                f"{TWO_WAY_SECONDARY_VALUE_WEIGHT}"
            ),
            "primary_value": round(primary_value, 2),
            "secondary_value": round(secondary_value, 2),
            "combined_value": round(combined_value, 2),
            "role_components": component_rows,
        }
        merged = {
            **primary,
            "id": f"vc_mlb_{mlbam_id}_two_way",
            "role": "two_way",
            "positions": positions or primary.get("positions") or [],
            "value": round(combined_value, 2),
            "value_source": TWO_WAY_VALUE_SOURCE,
            "confidence": _combined_confidence(ordered),
            "drivers": drivers[:6],
            "context": context,
        }
        merged_rows.append(merged)

    return merged_rows


def _prospect_rows(
    rank_payload: dict,
    generated_at: str,
    peak_projection: dict | None = None,
) -> list[dict]:
    peak_lookup = _prospect_peak_projection_lookup(peak_projection)
    rows = []
    for row in rank_payload.get("board") or []:
        context = row.get("context_only") or {}
        peak = peak_lookup.get(_identity_key(row))
        rows.append(
            {
                "id": _snapshot_id(row),
                "player_type": "prospect",
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "positions": _positions(row),
                "team": row.get("mlb_team") or "",
                "mlb_team": row.get("mlb_team") or "",
                "age": row.get("age"),
                "rank": row.get("rank"),
                "value": row.get("score"),
                "value_scale": "0_100_valucast_prospect_score",
                "value_source": row.get("score_source"),
                "confidence": row.get("confidence"),
                "updated_at": generated_at,
                "status": "candidate_shadow",
                "prospect_rank": row.get("rank"),
                "level": row.get("level"),
                "eta": row.get("eta"),
                "score_source": row.get("score_source"),
                "components": row.get("components") or {},
                "drivers": row.get("drivers") or [],
                "dynasty_signal": row.get("dynasty_signal"),
                "breakout_label": context.get("breakout_label"),
                "breakout_rank_change": context.get("breakout_rank_change"),
                "stat_line": context.get("stat_line"),
                "stat_line_translated": context.get("stat_line_translated"),
                "best_single_level_stat_line": context.get("best_single_level_stat_line"),
                "mlb_stat_line": context.get("mlb_stat_line"),
                "peak_projection": peak,
                "context": {
                    "kind": "optional_display_context",
                    "usage": "display_only_not_used_for_valucast_score",
                    "valucast_rank_v1": row.get("rank"),
                    # External-board comparison context (CFR/HKB/Pipeline) — kept,
                    # labeled, never feeds a ValuCast score. The DD rank/value keys are
                    # not dropped here: no consumer reads them off the public snapshot
                    # (rank_v1's internal context_only still carries them for the
                    # coverage/calibration audits).
                    "source_ranks": context.get("source_ranks"),
                    "stat_line_source": context.get("stat_line_source"),
                    "stat_line_source_kind": context.get("stat_line_source_kind"),
                    "stat_line_level": context.get("stat_line_level"),
                    "stat_line_team": context.get("stat_line_team"),
                    "stat_line_sample": context.get("stat_line_sample"),
                    "stat_line_sample_unit": context.get("stat_line_sample_unit"),
                    "stat_line_sample_season": context.get("stat_line_sample_season"),
                    "graduation_context": context.get("graduation_context"),
                },
            }
        )
    return rows


def _prospect_peak_projection_lookup(peak_projection: dict | None) -> dict[str, dict]:
    if not peak_projection:
        return {}
    validation = peak_projection.get("validation") or {}
    if validation.get("ready_for_card_v2") is not True:
        return {}
    lookup = {}
    for row in peak_projection.get("projections") or []:
        key = _identity_key(row)
        if key and key not in lookup:
            lookup[key] = row
    return lookup


def _assign_visible_prospect_ranks(rows: list[dict]) -> list[dict]:
    for rank, row in enumerate(rows, 1):
        row["prospect_rank"] = rank
    return rows


def _assign_global_ranks(players: list[dict]) -> list[dict]:
    ranked = sorted(
        players,
        key=lambda row: (
            -float(row.get("value") or 0.0),
            row.get("player_type") != "mlb",
            int(row.get("rank") or 999999),
            str(row.get("name") or ""),
            str(row.get("id") or ""),
        ),
    )
    for rank, row in enumerate(ranked, 1):
        row["rank"] = rank
    return ranked


def _numeric_values(rows: list[dict]) -> list[float]:
    values = []
    for row in rows:
        try:
            value = float(row.get("value"))
        except (TypeError, ValueError):
            continue
        if value == value and 0.0 <= value <= 100.0:
            values.append(value)
    return values


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = (len(ordered) - 1) * percentile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return round(ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction, 2)


def _value_distribution(values: list[float]) -> dict:
    return {
        "count": len(values),
        "max": round(max(values), 2) if values else None,
        "p95": _percentile(values, 0.95),
        "p90": _percentile(values, 0.90),
        "p75": _percentile(values, 0.75),
        "median": _percentile(values, 0.50),
    }


def _apply_common_value_scale(players: list[dict], report: dict) -> None:
    for row in players:
        original_scale = row.get("value_scale")
        row["value_scale"] = COMMON_VALUE_SCALE
        row["status"] = "candidate_ready"
        context = dict(row.get("context") or {})
        context["cross_universe_calibration"] = {
            "method": CALIBRATION_METHOD,
            "value_mutation": "none",
            "raw_value": row.get("value"),
            "raw_value_scale": original_scale,
            "calibrated_value": row.get("value"),
            "calibrated_value_scale": COMMON_VALUE_SCALE,
            "mlb_equivalent_rank_for_top_prospect": report["metrics"].get(
                "top_prospect_mlb_equivalent_rank"
            ),
        }
        row["context"] = context


def _cross_universe_calibration_report(
    players: list[dict],
    rank_payload: dict,
    mlb_layer: dict | None,
    generated_date: str | None,
    rank_date: str | None,
    mlb_date: str | None,
    duplicate_identity_count: int,
) -> dict:
    mlb_rows = [row for row in players if row.get("player_type") == "mlb"]
    prospect_rows = [row for row in players if row.get("player_type") == "prospect"]
    mlb_values = _numeric_values(mlb_rows)
    prospect_values = _numeric_values(prospect_rows)
    mlb_validation = (mlb_layer or {}).get("validation") or {}
    value_contract = (mlb_layer or {}).get("value_contract") or {}
    rank_validation = rank_payload.get("validation") or {}

    top_prospect_value = max(prospect_values) if prospect_values else None
    mlb_rows_above_top_prospect = (
        sum(1 for value in mlb_values if value >= top_prospect_value)
        if top_prospect_value is not None
        else 0
    )
    minimum_mlb_rows_above = min(MIN_MLB_ROWS_ABOVE_TOP_PROSPECT, len(mlb_values))
    maximum_mlb_rows_above = min(MAX_MLB_ROWS_ABOVE_TOP_PROSPECT, len(mlb_values))

    metrics = {
        "mlb": _value_distribution(mlb_values),
        "prospects": _value_distribution(prospect_values),
        "top_prospect_value": round(top_prospect_value, 2)
        if top_prospect_value is not None
        else None,
        "mlb_rows_at_or_above_top_prospect": mlb_rows_above_top_prospect,
        "top_prospect_mlb_equivalent_rank": (
            mlb_rows_above_top_prospect + 1 if prospect_values else None
        ),
        "minimum_mlb_rows_at_or_above_top_prospect": minimum_mlb_rows_above,
        "maximum_mlb_rows_at_or_above_top_prospect": maximum_mlb_rows_above,
    }

    blockers = []
    if not mlb_layer:
        blockers.append("ValuCast MLB dynasty layer is missing.")
    if not mlb_validation.get("ready_for_live_consumers"):
        blockers.append("ValuCast MLB dynasty layer is not standalone-ready.")
    if value_contract.get("value_kind") != "multi_year_dynasty_horizon":
        blockers.append("ValuCast MLB layer is not a multi-year dynasty horizon.")
    if int(value_contract.get("horizon_years") or 0) < MIN_MLB_HORIZON_YEARS:
        blockers.append("ValuCast MLB horizon is shorter than the calibration gate.")
    if mlb_validation.get("duplicate_identity_count", 0) != 0:
        blockers.append("ValuCast MLB layer has duplicate MLBAM+role identities.")
    if mlb_validation.get("missing_mlbam_count", 0) != 0:
        blockers.append("ValuCast MLB layer has rows missing MLBAM identity.")
    if not mlb_validation.get("ranks_contiguous", False):
        blockers.append("ValuCast MLB layer ranks are not contiguous.")
    if not mlb_values:
        blockers.append("ValuCast MLB layer has no numeric 0-100 values.")

    coverage_rate = float(rank_validation.get("coverage_rate") or 0.0)
    top_unique_count = int(rank_validation.get("top_200_unique_score_count") or 0)
    if coverage_rate < MIN_PROSPECT_COVERAGE_RATE:
        blockers.append("Prospect Rank v1 coverage is below the calibration gate.")
    if rank_validation.get("duplicate_identity_count", 0) != 0:
        blockers.append("Prospect Rank v1 has duplicate MLBAM+role identities.")
    if rank_validation.get("missing_mlbam_count", 0) != 0:
        blockers.append("Prospect Rank v1 has rows missing MLBAM identity.")
    if not rank_validation.get("same_day_freshness", False):
        blockers.append("Prospect Rank v1 input artifacts are not same-day fresh.")
    if not rank_validation.get("ranks_contiguous", False):
        blockers.append("Prospect Rank v1 ranks are not contiguous.")
    if top_unique_count < MIN_TOP_200_UNIQUE_SCORE_COUNT:
        blockers.append("Prospect Rank v1 top-200 score separation is below the gate.")
    if not prospect_values:
        blockers.append("Prospect Rank v1 has no numeric 0-100 values.")

    date_values = [generated_date, rank_date, mlb_date]
    if not all(date_values) or len(set(date_values)) != 1:
        blockers.append("MLB layer, prospect rank, and public snapshot are not same-day fresh.")
    if duplicate_identity_count:
        blockers.append("Public snapshot has duplicate MLBAM+role identities.")
    if len(mlb_values) != len(mlb_rows) or len(prospect_values) != len(prospect_rows):
        blockers.append("Public snapshot has non-numeric or out-of-range values.")
    if (
        top_prospect_value is not None
        and mlb_values
        and mlb_rows_above_top_prospect < minimum_mlb_rows_above
    ):
        blockers.append(
            "Top prospect is calibrated above too much of the current MLB dynasty board."
        )
    if (
        top_prospect_value is not None
        and mlb_values
        and mlb_rows_above_top_prospect > maximum_mlb_rows_above
    ):
        blockers.append(
            "Top prospect is calibrated below too much of the current MLB dynasty board."
        )

    return {
        "method": CALIBRATION_METHOD,
        "target_value_scale": COMMON_VALUE_SCALE,
        "value_mutation": "none",
        "applied": not blockers,
        "metrics": metrics,
        "criteria": {
            "mlb_value_kind": "multi_year_dynasty_horizon",
            "minimum_mlb_horizon_years": MIN_MLB_HORIZON_YEARS,
            "minimum_prospect_coverage_rate": MIN_PROSPECT_COVERAGE_RATE,
            "minimum_top_200_unique_score_count": MIN_TOP_200_UNIQUE_SCORE_COUNT,
            "minimum_mlb_rows_at_or_above_top_prospect": minimum_mlb_rows_above,
            "maximum_mlb_rows_at_or_above_top_prospect": maximum_mlb_rows_above,
            "same_day_freshness_required": True,
            "duplicate_identity_count_required": 0,
        },
        "blockers": blockers,
    }


def _validation(
    payload: dict,
    rank_payload: dict,
    mlb_layer: dict | None,
    buy_signals: dict | None,
    quality_governor: dict,
    prospects_excluded_by_mlb_identity_count: int,
    prospects_excluded_by_mlb_identity_sample: list[dict],
    mlb_projection_rows_suppressed_by_prospect_count: int,
    mlb_projection_rows_suppressed_by_prospect_sample: list[dict],
    calibration_report: dict,
    graduation_transition_floor_count: int = 0,
) -> dict:
    players = payload.get("players") or []
    identity_keys = [key for row in players if (key := _identity_key(row))]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    prospect_visible_ranks = [
        row.get("prospect_rank")
        for row in players
        if row.get("player_type") == "prospect"
    ]
    visible_prospect_ranks_contiguous = prospect_visible_ranks == list(
        range(1, len(prospect_visible_ranks) + 1)
    )
    generated_date = _date_part(payload.get("generated_at"))
    rank_date = _date_part(rank_payload.get("generated_at"))
    mlb_date = _date_part((mlb_layer or {}).get("generated_at"))
    buy_date = _date_part((buy_signals or {}).get("generated_at"))
    mlb_validation = (mlb_layer or {}).get("validation") or {}
    buy_validation = (buy_signals or {}).get("validation") or {}
    blockers = []
    buy_blockers = []
    if not mlb_layer:
        blockers.append(
            "ValuCast MLB dynasty value layer artifact is missing; snapshot contains no MLB canonical values."
        )
    elif not mlb_validation.get("ready_for_live_consumers"):
        blockers.extend(
            mlb_validation.get("blockers")
            or ["ValuCast MLB dynasty value layer is still shadow-only."]
        )
    blockers.extend(calibration_report.get("blockers") or [])
    if not buy_signals:
        buy_blockers.append("ValuCast-owned buy signal artifact is missing.")
    elif not buy_validation.get("ready_for_live_consumers"):
        buy_blockers.extend(
            buy_validation.get("blockers")
            or ["ValuCast buy signals are still shadow-only."]
        )
    if not quality_governor.get("ready_for_public_snapshot"):
        blockers.extend(
            quality_governor.get("blockers")
            or ["ValuCast quality governor has not approved public snapshot promotion."]
        )
    if not quality_governor.get("ready_for_buys_promotion"):
        buy_blockers.extend(
            quality_governor.get("buy_blockers")
            or ["ValuCast quality governor has not approved Buy promotion."]
        )
    date_values = [generated_date, rank_date]
    if mlb_layer:
        date_values.append(mlb_date)
    if buy_signals:
        date_values.append(buy_date)
    same_day_freshness = all(date_values) and len(set(date_values)) == 1
    if not same_day_freshness:
        blockers.append("Public snapshot input artifacts are not all same-day fresh.")
    if duplicate_identity_count:
        blockers.append("Public snapshot has duplicate MLBAM+role identities.")
    if not visible_prospect_ranks_contiguous:
        blockers.append("Public snapshot visible prospect ranks are not contiguous.")
    field_problems = required_field_problems(players)
    if field_problems:
        blockers.append("Public snapshot has incomplete required fields.")

    quality_surface_readiness = quality_governor.get("surface_readiness") or {}
    dynasty_ready = (
        not blockers
        and bool(calibration_report.get("applied"))
        and bool(quality_surface_readiness.get("dynasty"))
    )
    prospects_ready = dynasty_ready
    buys_ready = dynasty_ready and bool(quality_surface_readiness.get("buys"))
    blockers = list(dict.fromkeys(blockers))
    buy_blockers = list(dict.fromkeys(buy_blockers))

    return {
        "ready_for_live_consumers": dynasty_ready and prospects_ready,
        "ready_for_all_public_surfaces": dynasty_ready and prospects_ready and buys_ready,
        "same_day_freshness": same_day_freshness,
        "generated_dates": {
            "public_snapshot": generated_date,
            "mlb_dynasty_layer": mlb_date,
            "prospect_rank_v1": rank_date,
            "valucast_prospect_buys": buy_date,
        },
        "row_count": len(players),
        "mlb_count": sum(1 for row in players if row.get("player_type") == "mlb"),
        "prospect_count": sum(1 for row in players if row.get("player_type") == "prospect"),
        "duplicate_identity_count": duplicate_identity_count,
        "required_fields_complete": not field_problems,
        "required_field_problem_count": len(field_problems),
        "required_field_problem_sample": field_problems[:12],
        "mlb_dynasty_value_layer_present": bool(mlb_layer and mlb_validation.get("row_count")),
        "mlb_dynasty_value_layer_ready": bool(
            mlb_validation.get("ready_for_live_consumers")
        ),
        "prospect_rank_v1_candidate_count": rank_payload.get("candidate_count"),
        "prospect_rank_v1_ranked_count": rank_payload.get("ranked_count"),
        "visible_prospect_ranks_contiguous": visible_prospect_ranks_contiguous,
        "valucast_buy_signal_count": buy_validation.get("row_count"),
        "valucast_buy_signals_ready": bool(
            buy_validation.get("ready_for_live_consumers")
        ),
        "quality_governor_ready": bool(
            quality_governor.get("ready_for_public_snapshot")
        ),
        "quality_governor_version": quality_governor.get("governor_version"),
        "quality_governor_blockers": quality_governor.get("blockers") or [],
        "prospects_excluded_by_mlb_identity_count": prospects_excluded_by_mlb_identity_count,
        "prospects_excluded_by_mlb_identity_sample": prospects_excluded_by_mlb_identity_sample,
        "mlb_projection_rows_suppressed_by_prospect_count": mlb_projection_rows_suppressed_by_prospect_count,
        "mlb_projection_rows_suppressed_by_prospect_sample": mlb_projection_rows_suppressed_by_prospect_sample,
        "graduation_transition_floor_count": graduation_transition_floor_count,
        "cross_universe_value_scale_calibrated": bool(calibration_report.get("applied")),
        "cross_universe_calibration": calibration_report,
        "quality_governor": quality_governor,
        "surface_readiness": {
            "dynasty": dynasty_ready,
            "prospects": prospects_ready,
            "buys": buys_ready,
        },
        "surface_blockers": {
            "dynasty": blockers,
            "prospects": blockers,
            "buys": buy_blockers,
        },
        "buy_signal_blockers": buy_blockers,
        "blockers": blockers,
    }


def build_snapshot(
    prospect_rank: dict,
    mlb_layer: dict | None = None,
    mlb_roster_status: dict | None = None,
    mlb_track_record: dict | None = None,
    prospect_coverage_audit: dict | None = None,
    prospect_peak_projection: dict | None = None,
    buy_signals: dict | None = None,
    buy_review: dict | None = None,
    prospect_inputs: dict | None = None,
    milb_stat_freshness_audit: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    generated_at = (
        generated_at
        or prospect_rank.get("generated_at")
        or (mlb_layer or {}).get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    mlb_rows = _merge_two_way_mlb_rows(_mlb_rows(mlb_layer, generated_at))
    mlb_identity_ids = {
        mlbam_id
        for row in mlb_rows
        if (mlbam_id := _mlbam_id(row))
    }
    mlb_rows_by_id: dict[str, list[dict]] = {}
    for row in mlb_rows:
        if mlbam_id := _mlbam_id(row):
            mlb_rows_by_id.setdefault(mlbam_id, []).append(row)
    active_mlb_ids = _active_mlb_roster_ids(mlb_roster_status)
    all_prospect_rows = _prospect_rows(
        prospect_rank,
        generated_at,
        peak_projection=prospect_peak_projection,
    )
    graduated_prospect_rows = [
        row
        for row in all_prospect_rows
        if (mlbam_id := _mlbam_id(row)) in active_mlb_ids
        or (
            mlbam_id in mlb_identity_ids
            and _mlb_collision_should_promote(row, mlb_rows_by_id.get(mlbam_id, []))
        )
    ]
    graduated_ids = {
        mlbam_id
        for row in graduated_prospect_rows
        if (mlbam_id := _mlbam_id(row))
    }
    prospect_rows = [
        row
        for row in all_prospect_rows
        if _mlbam_id(row) not in graduated_ids
    ]
    active_prospect_ids = {
        mlbam_id
        for row in prospect_rows
        if (mlbam_id := _mlbam_id(row))
    }
    suppressed_mlb_rows = [
        row for row in mlb_rows if _mlbam_id(row) in active_prospect_ids
    ]
    mlb_rows = [
        row for row in mlb_rows if _mlbam_id(row) not in active_prospect_ids
    ]
    graduation_transition_floor_count = _apply_graduation_transition_floor(
        mlb_rows,
        graduated_prospect_rows,
        debut_by_id=_debut_dates_by_id(mlb_track_record),
        as_of_date=generated_at,
    )
    prospect_rows = _assign_visible_prospect_ranks(prospect_rows)
    prospects_excluded_by_mlb_identity_count = len(graduated_prospect_rows)
    graduated_prospect_sample = [
        {
            "mlbam_id": row.get("mlbam_id"),
            "name": row.get("name"),
            "role": row.get("role"),
            "level": row.get("level"),
            "rank": row.get("prospect_rank"),
            "reason": (
                "active_mlb_roster"
                if _mlbam_id(row) in active_mlb_ids
                else "material_mlb_row"
            ),
        }
        for row in sorted(
            graduated_prospect_rows,
            key=lambda row: (
                int(row.get("prospect_rank") or 999999),
                str(row.get("name") or ""),
            ),
        )[:12]
    ]
    suppressed_mlb_sample = [
        {
            "mlbam_id": row.get("mlbam_id"),
            "name": row.get("name"),
            "role": row.get("role"),
            "value": row.get("value"),
        }
        for row in sorted(
            suppressed_mlb_rows,
            key=lambda row: (
                int(row.get("rank") or 999999),
                str(row.get("name") or ""),
            ),
        )[:12]
    ]
    combined_rows = mlb_rows + prospect_rows
    identity_keys = [key for row in combined_rows if (key := _identity_key(row))]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    generated_date = _date_part(generated_at)
    rank_date = _date_part(prospect_rank.get("generated_at"))
    mlb_date = _date_part((mlb_layer or {}).get("generated_at"))
    calibration_report = _cross_universe_calibration_report(
        combined_rows,
        prospect_rank,
        mlb_layer,
        generated_date,
        rank_date,
        mlb_date,
        duplicate_identity_count,
    )
    if calibration_report.get("applied"):
        _apply_common_value_scale(combined_rows, calibration_report)
    players = _assign_global_ranks(combined_rows)
    if milb_stat_freshness_audit is None and prospect_inputs:
        milb_stat_freshness_audit = build_milb_stat_freshness_audit(
            prospect_inputs,
            prospect_rank,
            public_snapshot={"players": players},
            generated_at=generated_at,
        )
    quality_governor = evaluate_quality_governor(
        players,
        prospect_rank=prospect_rank,
        prospect_coverage_audit=prospect_coverage_audit,
        mlb_layer=mlb_layer,
        buy_signals=buy_signals,
        buy_review=buy_review,
        milb_stat_freshness_audit=milb_stat_freshness_audit,
        generated_at=generated_at,
        graduated_prospect_ids=graduated_ids,
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifact": ARTIFACT_NAME,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "source_policy": {
            "kind": "valucast_public_snapshot_shadow",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
            "dd_context_allowed": True,
        },
        "input_artifacts": {
            "mlb_dynasty_layer_version": (mlb_layer or {}).get("layer_version"),
            "mlb_dynasty_layer_status": (mlb_layer or {}).get("status"),
            "mlb_roster_status_version": (mlb_roster_status or {}).get("contract_version"),
            "mlb_roster_status_ready": (
                ((mlb_roster_status or {}).get("validation") or {}).get(
                    "ready_for_public_snapshot"
                )
            ),
            "valucast_buy_signal_version": (buy_signals or {}).get("signal_version"),
            "valucast_buy_signal_status": (buy_signals or {}).get("status"),
            "prospect_coverage_audit_version": (prospect_coverage_audit or {}).get(
                "audit_version"
            ),
            "prospect_coverage_audit_status": (prospect_coverage_audit or {}).get(
                "status"
            ),
            "prospect_peak_projection_version": (prospect_peak_projection or {}).get(
                "projection_version"
            ),
            "prospect_peak_projection_status": (prospect_peak_projection or {}).get(
                "status"
            ),
            "prospect_peak_projection_ready": (
                ((prospect_peak_projection or {}).get("validation") or {}).get(
                    "ready_for_card_v2"
                )
            ),
            "milb_stat_freshness_audit_version": (
                milb_stat_freshness_audit or {}
            ).get("audit_version"),
            "milb_stat_freshness_audit_status": (
                milb_stat_freshness_audit or {}
            ).get("status"),
            "prospect_rank_v1_version": prospect_rank.get("rank_version"),
            "prospect_rank_v1_status": prospect_rank.get("status"),
            "prospect_universe_source": (prospect_rank.get("rank_contract") or {}).get(
                "prospect_universe_source"
            ),
        },
        "quality_governor": quality_governor,
        "players": players,
    }
    payload["validation"] = _validation(
        payload,
        prospect_rank,
        mlb_layer,
        buy_signals,
        quality_governor,
        prospects_excluded_by_mlb_identity_count,
        graduated_prospect_sample,
        len(suppressed_mlb_rows),
        suppressed_mlb_sample,
        calibration_report,
        graduation_transition_floor_count,
    )
    return payload


def write_snapshot(payload: dict, path: Path = OUTPUT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def main() -> None:
    rank_payload = _load_json(PROSPECT_RANK_PATH)
    prospect_inputs = (
        _load_json(PROSPECT_INPUTS_PATH) if PROSPECT_INPUTS_PATH.exists() else None
    )
    mlb_layer = _load_json(MLB_LAYER_PATH) if MLB_LAYER_PATH.exists() else None
    mlb_roster_status = (
        _load_json(MLB_ROSTER_STATUS_PATH)
        if MLB_ROSTER_STATUS_PATH.exists()
        else None
    )
    mlb_track_record = (
        _load_json(MLB_TRACK_RECORD_PATH) if MLB_TRACK_RECORD_PATH.exists() else None
    )
    prospect_coverage_audit = (
        _load_json(PROSPECT_COVERAGE_AUDIT_PATH)
        if PROSPECT_COVERAGE_AUDIT_PATH.exists()
        else None
    )
    prospect_peak_projection = (
        _load_json(PROSPECT_PEAK_PROJECTION_PATH)
        if PROSPECT_PEAK_PROJECTION_PATH.exists()
        else None
    )
    buy_signals = _load_json(BUY_SIGNALS_PATH) if BUY_SIGNALS_PATH.exists() else None
    buy_review = _load_json(BUY_REVIEW_PATH) if BUY_REVIEW_PATH.exists() else None
    payload = build_snapshot(
        rank_payload,
        mlb_layer=mlb_layer,
        mlb_roster_status=mlb_roster_status,
        mlb_track_record=mlb_track_record,
        prospect_coverage_audit=prospect_coverage_audit,
        prospect_peak_projection=prospect_peak_projection,
        buy_signals=buy_signals,
        buy_review=buy_review,
        prospect_inputs=prospect_inputs,
    )
    path = write_snapshot(payload)
    validation = payload["validation"]
    print(
        "ValuCast public dynasty snapshot: "
        f"rows={validation['row_count']} "
        f"mlb={validation['mlb_count']} "
        f"prospects={validation['prospect_count']} "
        f"ready={validation['ready_for_live_consumers']} -> {path}"
    )


if __name__ == "__main__":
    main()
