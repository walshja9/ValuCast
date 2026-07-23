"""Quality governor for ValuCast-owned public model artifacts.

The governor is deliberately outside Flask routing. It evaluates generated
model outputs before public consumers are allowed to trust them.
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.calibration_report import (
    MAX_TOP25_PITCHER_COUNT as MAX_TOP25_PROSPECT_PITCHER_COUNT,
)
from prospects.calibration_report import (
    MAX_TOP50_PITCHER_RATE as MAX_TOP50_PROSPECT_PITCHER_RATE,
)
from web.buy_score import STEP_THRESHOLD
from web.public_snapshot_store import DD_DERIVED_SOURCE_TOKENS

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_quality_governor.json"
PUBLIC_SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
MLB_LAYER_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
PROSPECT_RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
PROSPECT_RANK_ARCHIVE_DIR = (
    ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
)
PROSPECT_COVERAGE_AUDIT_PATH = (
    ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"
)
BUY_SIGNALS_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
BUY_REVIEW_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_review.json"
MOVERS_PATH = ROOT / "data" / "models" / "valucast_prospect_movers.json"
MILB_STAT_FRESHNESS_AUDIT_PATH = (
    ROOT / "data" / "models" / "valucast_milb_stat_freshness_audit.json"
)
PROSPECT_CARD_DATA_AUDIT_PATH = (
    ROOT / "data" / "models" / "valucast_prospect_card_data_audit.json"
)
RECENT_SIGNAL_REPORT_PATH = (
    ROOT / "data" / "models" / "valucast_recent_signal_report.json"
)

GOVERNOR_NAME = "ValuCast Quality Governor"
GOVERNOR_VERSION = "0.2.4"
SURFACE_DYNASTY = "dynasty"
SURFACE_PROSPECTS = "prospects"
SURFACE_BUYS = "buys"
SURFACE_MOVERS = "movers"
SURFACE_BOTH = "both"
BOARD_CHECK_SURFACES = {
    SURFACE_DYNASTY,
    SURFACE_PROSPECTS,
    SURFACE_BOTH,
}
# Board checks that gate the PROSPECTS surface / public snapshot but NOT the BUYS
# surface: the buys are a separate, corroboration-filtered list, so the main board's
# pitcher-shape lean and its top-50 card freshness/data audits (which can fire on a
# single non-buy prospect, e.g. an injured player on a prior-year line) should not
# block buys. Buys are gated on their own quality (corroboration + buy promotion gate).
BUY_IRRELEVANT_BOARD_CHECK_IDS = {
    "prospect_top_board_role_shape",
    "prospect_transition_continuity",
    "milb_stat_freshness_audit",
    "prospect_card_data_audit",
}

MAX_TOP_MLB_VALUE_GAP = 18.0
MLB_STABILITY_TOP_N = 25
MLB_ROLE_SHAPE_TOP_N = 25
MAX_TOP25_MLB_PITCHER_COUNT = 9
MAX_TOP25_MLB_RELIEVER_COUNT = 1
MAX_TOP_MLB_CURRENT_OVER_ROS_GAP = 10.0
MAX_TOP_MLB_ADJUSTED_OVER_ROS_GAP = 5.0
MAX_TOP_MLB_ROS_STABILITY_WEIGHT = 0.69
TWO_WAY_POLICY_RANK_LIMIT = 200
PROSPECT_FALLBACK_TOP_N = 50
MAX_TOP50_FALLBACK_RATE = 0.10
MAX_TOP50_SUPPRESSED_RANK_ROWS = 0
MAX_ELITE_FACTUAL_RAW_FALLBACK_TOP200 = 0
MAX_TOP50_PEDIGREE_RATE = 0.35
MAX_TOP50_LOW_CONFIDENCE_RATE = 0.38
MAX_TOP50_LOWER_MINORS_PEDIGREE_COUNT = 15
MAX_TOP50_THIN_UPPER_LEVEL_PITCHER_COUNT = 4
PROSPECT_INVESTMENT_TOP_N = 25
MAX_TOP25_NEUTRAL_INVESTMENT_RATE = 0.35
MAX_TOP25_EXACT_PEDIGREE_CAP_COUNT = 3
MAX_TOP50_MISSING_TEAM_COUNT = 0
MAX_TOP50_MISSING_AVAILABILITY_COUNT = 0
MAX_TOP50_UNPRICED_AVAILABILITY_RISK_COUNT = 0
MAX_TOP50_MISSING_FACTUAL_CONTEXT_COUNT = 0
MAX_TOP50_CAUTION_FACTUAL_CONTEXT_COUNT = 8
MAX_TOP50_CURRENT_STAT_CONTEXT_MISMATCH_COUNT = 0
MAX_TOP50_AVAILABILITY_LEVEL_MISMATCH_COUNT = 0
MAX_MILB_STAT_FRESHNESS_BLOCKERS = 0
MAX_BUY_HISTORY_LIMITED_RATE = 0.50
MAX_BUY_TOP40_LOW_CONFIDENCE_RATE = 0.35
MAX_BUY_TOP40_PEDIGREE_RATE = 0.35
BUY_SURFACE_TOP_N = 40
MAX_BUY_TOP40_MISSING_PUBLIC_PROSPECT_COUNT = 0
MAX_BUY_TOP40_GRADUATED_OR_MLB_COUNT = 0
MAX_BUY_TOP40_LEVEL_MISMATCH_COUNT = 0
MAX_BUY_TOP40_TEAM_MISMATCH_COUNT = 0
MAX_BUY_TOP40_UNDISCLOSED_AVAILABILITY_RISK_COUNT = 0

PEDIGREE_SCORE_SOURCE = "prospect_pedigree_v0_7"
FALLBACK_SCORE_SOURCES = {"universal_fallback", "identity_only_fallback"}
CLEAR_AVAILABILITY_STATUSES = {"", "available", "clear"}
CAUTION_FACTUAL_CONTEXT_BANDS = {"thin", "limited", "low_impact"}
BEST_SINGLE_COVERED_CAUTION_BANDS = {"thin", "limited"}
LOWER_LEVELS = {"DSL", "CPX", "ROK", "A", "A+"}
UPPER_LEVELS = {"AA", "AAA", "MLB"}
PROSPECT_TRANSITION_MODEL_DELTA_LIMIT = 1.0
PROSPECT_TRANSITION_SAMPLE_LIMIT = 12
PROSPECT_TRANSITION_CONFIDENCE_BUCKETS = {
    "thin_current_sample_confidence",
    "moderate_thin_sample_confidence",
}


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


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _generated_at(*payloads: dict | None) -> str:
    for payload in payloads:
        if payload and payload.get("generated_at"):
            return str(payload["generated_at"])
    return datetime.now(timezone.utc).isoformat()


def load_previous_prospect_rank(
    current: dict,
    archive_dir: Path | str = PROSPECT_RANK_ARCHIVE_DIR,
) -> dict | None:
    current_date = _date_part(current.get("generated_at") or current.get("date"))
    if not current_date:
        raise ValueError("current prospect rank is missing a valid generated date")
    root = Path(archive_dir)
    if not root.exists():
        return None
    candidates = [
        path
        for path in root.glob("*.json")
        if (date_str := _date_part(path.stem)) and date_str < current_date
    ]
    if not candidates:
        return None
    path = max(candidates, key=lambda candidate: candidate.stem)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"malformed prospect rank baseline {path}: {exc}") from exc
    baseline_date = _date_part(
        payload.get("generated_at") or payload.get("date")
    ) if isinstance(payload, dict) else None
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("board"), list)
        or not baseline_date
        or baseline_date >= current_date
    ):
        raise ValueError(f"malformed prospect rank baseline {path}")
    return payload


def _check(check_id: str, passed: bool, message: str, **metrics: Any) -> dict:
    return {
        "id": check_id,
        "status": "passed" if passed else "blocked",
        "message": message,
        "metrics": metrics,
    }


def _player_rows(snapshot_or_rows: dict | list[dict] | None) -> list[dict]:
    if isinstance(snapshot_or_rows, list):
        return list(snapshot_or_rows)
    if isinstance(snapshot_or_rows, dict):
        return list(snapshot_or_rows.get("players") or [])
    return []


def _prospect_rank_rows(prospect_rank: dict | None) -> list[dict]:
    return list((prospect_rank or {}).get("board") or [])


def _public_prospect_rows(players: list[dict]) -> list[dict]:
    rows = [row for row in players if row.get("player_type") == "prospect"]
    rows.sort(
        key=lambda row: (
            _clean_int(row.get("prospect_rank")) or 999999,
            _clean_int(row.get("rank")) or 999999,
            str(row.get("name") or ""),
        )
    )
    return rows


def _mlbam_id(row: dict) -> str | None:
    value = row.get("mlbam_id")
    if value in (None, ""):
        return None
    return str(value)


def _identity_key(row: dict) -> tuple[str, str] | None:
    mlbam_id = _mlbam_id(row)
    role = row.get("role")
    if not mlbam_id or role not in {"hitter", "pitcher"}:
        return None
    return mlbam_id, str(role)


def _team(row: dict) -> str:
    return str(row.get("mlb_team") or row.get("team") or "").strip().upper()


def _components(row: dict) -> dict:
    direct = row.get("components")
    if isinstance(direct, dict):
        return direct
    context = row.get("context")
    if isinstance(context, dict):
        nested = context.get("components")
        if isinstance(nested, dict):
            return nested
    return {}


def _is_active_callup_bridge(row: dict) -> bool:
    context = row.get("context")
    graduation_context = (
        context.get("graduation_context")
        if isinstance(context, dict)
        else None
    )
    if not isinstance(graduation_context, dict):
        graduation_context = {}
    return (
        row.get("active_mlb_callup_bridge") is True
        or graduation_context.get("surface") == "active_mlb_roster_bridge"
    )


def _projection_stability(row: dict) -> dict:
    components = _components(row)
    stability = components.get("projection_stability")
    return stability if isinstance(stability, dict) else {}


def _availability_component(row: dict) -> dict:
    availability = _components(row).get("availability")
    return availability if isinstance(availability, dict) else {}


def _factual_context_component(row: dict) -> dict:
    context = _components(row).get("factual_current_context")
    return context if isinstance(context, dict) else {}


def _prospect_transition_continuity(
    current: dict | None,
    previous: dict | None,
) -> dict:
    current_date = _date_part((current or {}).get("generated_at") or (current or {}).get("date"))
    previous_date = _date_part((previous or {}).get("generated_at") or (previous or {}).get("date"))
    if previous is None:
        return _check(
            "prospect_transition_continuity",
            True,
            "Prospect transition continuity is collecting its first prior vintage.",
            sample_ready=False,
            baseline_date=None,
            current_date=current_date,
            evaluated_matched_row_count=0,
            incident_count=0,
            hitter_count=0,
            pitcher_count=0,
            model_delta_limit=PROSPECT_TRANSITION_MODEL_DELTA_LIMIT,
            bucket_step_threshold=STEP_THRESHOLD,
            samples=[],
        )

    prior_by_key = {
        key: row
        for row in _prospect_rank_rows(previous)
        if (key := _identity_key(row))
    }
    matched = 0
    incidents = []
    for row in _prospect_rank_rows(current):
        key = _identity_key(row)
        prior = prior_by_key.get(key) if key else None
        if prior is None:
            continue
        matched += 1
        old_availability = _availability_component(prior).get("status")
        new_availability = _availability_component(row).get("status")
        old_starter = _factual_context_component(prior).get("starter_role")
        new_starter = _factual_context_component(row).get("starter_role")
        transitions = [
            label
            for label, old, new in (
                ("level", prior.get("level"), row.get("level")),
                ("availability_status", old_availability, new_availability),
                ("starter_role", old_starter, new_starter),
            )
            if old != new
        ]

        old_components = _components(prior)
        new_components = _components(row)
        old_calibration = old_components.get("bucket_calibration") or {}
        new_calibration = new_components.get("bucket_calibration") or {}
        old_rules = sorted(
            str(rule.get("bucket"))
            for rule in old_calibration.get("rules") or []
            if isinstance(rule, dict) and rule.get("bucket")
        )
        new_rules = sorted(
            str(rule.get("bucket"))
            for rule in new_calibration.get("rules") or []
            if isinstance(rule, dict) and rule.get("bucket")
        )
        old_confidence_rules = PROSPECT_TRANSITION_CONFIDENCE_BUCKETS.intersection(
            old_rules
        )
        new_confidence_rules = PROSPECT_TRANSITION_CONFIDENCE_BUCKETS.intersection(
            new_rules
        )
        old_model = _clean_float(old_components.get("model_score"))
        new_model = _clean_float(new_components.get("model_score"))
        old_bucket = _clean_float(old_calibration.get("adjustment")) or 0.0
        new_bucket = _clean_float(new_calibration.get("adjustment")) or 0.0
        old_score = _clean_float(prior.get("score"))
        new_score = _clean_float(row.get("score"))
        if None in {old_model, new_model, old_score, new_score}:
            continue
        model_delta = new_model - old_model
        bucket_delta = new_bucket - old_bucket
        final_delta = new_score - old_score
        if not (
            transitions
            and new_confidence_rules - old_confidence_rules
            and abs(model_delta) <= PROSPECT_TRANSITION_MODEL_DELTA_LIMIT
            and bucket_delta < -STEP_THRESHOLD
            and final_delta < -STEP_THRESHOLD
        ):
            continue
        incidents.append(
            {
                "mlbam_id": row.get("mlbam_id"),
                "name": row.get("name"),
                "role": row.get("role"),
                "transition_signals": transitions,
                "old_level": prior.get("level"),
                "new_level": row.get("level"),
                "old_availability_status": old_availability,
                "new_availability_status": new_availability,
                "old_starter_role": old_starter,
                "new_starter_role": new_starter,
                "model_score_delta": round(model_delta, 2),
                "bucket_adjustment_delta": round(bucket_delta, 2),
                "final_score_delta": round(final_delta, 2),
                "old_rank": prior.get("rank"),
                "new_rank": row.get("rank"),
                "old_bucket_rules": old_rules,
                "new_bucket_rules": new_rules,
            }
        )

    return _check(
        "prospect_transition_continuity",
        not incidents,
        (
            "Prospect transition calibration is continuous across the latest vintages."
            if not incidents
            else "Stable model scores produced material prospect transition calibration cliffs."
        ),
        sample_ready=True,
        baseline_date=previous_date,
        current_date=current_date,
        evaluated_matched_row_count=matched,
        incident_count=len(incidents),
        hitter_count=sum(row["role"] == "hitter" for row in incidents),
        pitcher_count=sum(row["role"] == "pitcher" for row in incidents),
        model_delta_limit=PROSPECT_TRANSITION_MODEL_DELTA_LIMIT,
        bucket_step_threshold=STEP_THRESHOLD,
        samples=incidents[:PROSPECT_TRANSITION_SAMPLE_LIMIT],
    )


def _has_best_single_level_stat_line(row: dict) -> bool:
    line = row.get("best_single_level_stat_line")
    if not isinstance(line, dict):
        return False
    stats = line.get("stats")
    metadata_keys = {
        "level",
        "reason",
        "sample",
        "sample_unit",
        "season",
        "team",
    }
    has_stats = (
        isinstance(stats, dict)
        and bool(stats)
        or any(
            key not in metadata_keys and _clean_float(value) is not None
            for key, value in line.items()
        )
    )
    return (
        bool(line.get("level"))
        and _clean_float(line.get("sample")) is not None
        and bool(line.get("sample_unit"))
        and has_stats
    )


def _top_mlb_value_gap(players: list[dict]) -> dict:
    mlb_rows = [
        row
        for row in players
        if row.get("player_type") == "mlb" and _clean_float(row.get("value")) is not None
    ]
    mlb_rows.sort(
        key=lambda row: (
            -(_clean_float(row.get("value")) or 0.0),
            _clean_int(row.get("rank")) or 999999,
            str(row.get("name") or ""),
        )
    )
    if len(mlb_rows) < 2:
        return _check(
            "mlb_top_value_gap",
            True,
            "MLB top-board spike check skipped because fewer than two MLB rows exist.",
            row_count=len(mlb_rows),
            max_allowed_gap=MAX_TOP_MLB_VALUE_GAP,
        )

    top = mlb_rows[0]
    second = mlb_rows[1]
    gap = round((_clean_float(top.get("value")) or 0.0) - (_clean_float(second.get("value")) or 0.0), 2)
    passed = gap <= MAX_TOP_MLB_VALUE_GAP
    return _check(
        "mlb_top_value_gap",
        passed,
        (
            "Top MLB dynasty value is within the maximum spike threshold."
            if passed
            else "Top MLB dynasty value is too far above the second row for public promotion."
        ),
        gap=gap,
        max_allowed_gap=MAX_TOP_MLB_VALUE_GAP,
        top={
            "name": top.get("name"),
            "rank": top.get("rank"),
            "value": top.get("value"),
            "mlbam_id": top.get("mlbam_id"),
        },
        second={
            "name": second.get("name"),
            "rank": second.get("rank"),
            "value": second.get("value"),
            "mlbam_id": second.get("mlbam_id"),
        },
    )


def _mlb_projection_stability_outliers(players: list[dict]) -> dict:
    top_rows = [
        row
        for row in players
        if row.get("player_type") == "mlb"
        and (_clean_int(row.get("rank")) or 999999) <= MLB_STABILITY_TOP_N
    ]
    outliers = []
    for row in sorted(top_rows, key=lambda item: _clean_int(item.get("rank")) or 999999):
        stability = _projection_stability(row)
        current_value = _clean_float(stability.get("current_season_category_value"))
        ros_value = _clean_float(stability.get("ros_category_value"))
        adjusted_value = _clean_float(stability.get("stability_adjusted_category_value"))
        ros_weight = _clean_float(stability.get("ros_stability_weight"))
        if current_value is None or ros_value is None or ros_weight is None:
            continue
        gap = round(current_value - ros_value, 4)
        adjusted_gap = round((adjusted_value if adjusted_value is not None else current_value) - ros_value, 4)
        if (
            gap > MAX_TOP_MLB_CURRENT_OVER_ROS_GAP
            and ros_weight > MAX_TOP_MLB_ROS_STABILITY_WEIGHT
            and adjusted_gap > MAX_TOP_MLB_ADJUSTED_OVER_ROS_GAP
        ):
            outliers.append(
                {
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "rank": row.get("rank"),
                    "value": row.get("value"),
                    "current_season_category_value": current_value,
                    "ros_category_value": ros_value,
                    "current_over_ros_gap": round(gap, 2),
                    "stability_adjusted_category_value": adjusted_value,
                    "adjusted_over_ros_gap": round(adjusted_gap, 2),
                    "ros_stability_weight": ros_weight,
                }
            )
    passed = not outliers
    return _check(
        "mlb_projection_stability_outliers",
        passed,
        (
            "Top MLB rows do not retain extreme current-over-ROS projection outliers after stability adjustment."
            if passed
            else "Top MLB rows retain extreme current-over-ROS projection outliers after stability adjustment."
        ),
        top_n=MLB_STABILITY_TOP_N,
        current_over_ros_gap_limit=MAX_TOP_MLB_CURRENT_OVER_ROS_GAP,
        adjusted_over_ros_gap_limit=MAX_TOP_MLB_ADJUSTED_OVER_ROS_GAP,
        ros_stability_weight_limit=MAX_TOP_MLB_ROS_STABILITY_WEIGHT,
        outlier_count=len(outliers),
        samples=outliers[:10],
    )


def _is_pitcher_row(row: dict) -> bool:
    positions = set(row.get("positions") or [])
    return bool(positions & {"P", "SP", "RP"}) or row.get("role") == "pitcher"


def _is_reliever_only_row(row: dict) -> bool:
    positions = set(row.get("positions") or [])
    return "RP" in positions and "SP" not in positions


def _mlb_top_board_role_shape(players: list[dict]) -> dict:
    top_rows = [
        row
        for row in players
        if row.get("player_type") == "mlb"
        and (_clean_int(row.get("rank")) or 999999) <= MLB_ROLE_SHAPE_TOP_N
    ]
    pitcher_rows = [row for row in top_rows if _is_pitcher_row(row)]
    reliever_rows = [row for row in top_rows if _is_reliever_only_row(row)]
    passed = (
        len(pitcher_rows) <= MAX_TOP25_MLB_PITCHER_COUNT
        and len(reliever_rows) <= MAX_TOP25_MLB_RELIEVER_COUNT
    )
    return _check(
        "mlb_top_board_role_shape",
        passed,
        (
            "Top MLB dynasty board role shape is within publication limits."
            if passed
            else "Top MLB dynasty board is too pitcher/reliever-heavy for public promotion."
        ),
        top_n=MLB_ROLE_SHAPE_TOP_N,
        pitcher_count=len(pitcher_rows),
        max_pitcher_count=MAX_TOP25_MLB_PITCHER_COUNT,
        reliever_count=len(reliever_rows),
        max_reliever_count=MAX_TOP25_MLB_RELIEVER_COUNT,
        pitcher_samples=[
            {
                "rank": row.get("rank"),
                "name": row.get("name"),
                "positions": row.get("positions"),
                "value": row.get("value"),
            }
            for row in pitcher_rows[:10]
        ],
        reliever_samples=[
            {
                "rank": row.get("rank"),
                "name": row.get("name"),
                "positions": row.get("positions"),
                "value": row.get("value"),
            }
            for row in reliever_rows[:10]
        ],
    )


def _prospect_top_board_role_shape(
    prospect_rank: dict | None,
    players: list[dict],
) -> dict:
    top_rows = _prospect_rank_rows(prospect_rank)
    if not top_rows:
        top_rows = _public_prospect_rows(players)
    top_rows.sort(
        key=lambda row: (
            _clean_int(row.get("rank") or row.get("prospect_rank")) or 999999,
            str(row.get("name") or ""),
            str(row.get("mlbam_id") or ""),
        )
    )
    top25_rows = top_rows[:PROSPECT_INVESTMENT_TOP_N]
    top50_rows = top_rows[:PROSPECT_FALLBACK_TOP_N]
    top25_pitcher_rows = [row for row in top25_rows if _is_pitcher_row(row)]
    top50_pitcher_rows = [row for row in top50_rows if _is_pitcher_row(row)]
    top25_ready = len(top25_rows) >= PROSPECT_INVESTMENT_TOP_N
    top50_ready = len(top50_rows) >= PROSPECT_FALLBACK_TOP_N
    top50_pitcher_rate = (
        round(len(top50_pitcher_rows) / len(top50_rows), 4) if top50_rows else 0.0
    )
    passed = (
        (not top25_ready or len(top25_pitcher_rows) <= MAX_TOP25_PROSPECT_PITCHER_COUNT)
        and (not top50_ready or top50_pitcher_rate <= MAX_TOP50_PROSPECT_PITCHER_RATE)
    )
    return _check(
        "prospect_top_board_role_shape",
        passed,
        (
            "Current prospect cross-role calibration is within the publication range."
            if passed
            else "Pitcher representation exceeds the publication range. Rankings remain visible, but the current evidence cannot justify either a cross-role score adjustment or relaxing the publication gate."
        ),
        top25_n=PROSPECT_INVESTMENT_TOP_N,
        top50_n=PROSPECT_FALLBACK_TOP_N,
        top25_evaluated_count=len(top25_rows),
        top50_evaluated_count=len(top50_rows),
        top25_pitcher_count=len(top25_pitcher_rows),
        max_top25_pitcher_count=MAX_TOP25_PROSPECT_PITCHER_COUNT,
        top50_pitcher_count=len(top50_pitcher_rows),
        top50_pitcher_rate=top50_pitcher_rate,
        max_top50_pitcher_rate=MAX_TOP50_PROSPECT_PITCHER_RATE,
        top25_sample_ready=top25_ready,
        top50_sample_ready=top50_ready,
        pitcher_samples=[
            {
                "rank": row.get("rank") or row.get("prospect_rank"),
                "name": row.get("name"),
                "role": row.get("role"),
                "score": row.get("score") or row.get("value"),
                "mlbam_id": row.get("mlbam_id"),
            }
            for row in top50_pitcher_rows[:10]
        ],
    )


def _two_way_policy(players: list[dict]) -> dict:
    by_mlbam: dict[str, list[dict]] = defaultdict(list)
    for row in players:
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            continue
        by_mlbam[str(mlbam_id)].append(row)

    split_rows = []
    for mlbam_id, rows in by_mlbam.items():
        roles = {row.get("role") for row in rows if row.get("role")}
        if len(roles) < 2:
            continue
        best_rank = min(_clean_int(row.get("rank")) or 999999 for row in rows)
        if best_rank > TWO_WAY_POLICY_RANK_LIMIT:
            continue
        split_rows.append(
            {
                "mlbam_id": mlbam_id,
                "best_rank": best_rank,
                "rows": [
                    {
                        "name": row.get("name"),
                        "role": row.get("role"),
                        "rank": row.get("rank"),
                        "value": row.get("value"),
                        "player_type": row.get("player_type"),
                    }
                    for row in sorted(rows, key=lambda item: _clean_int(item.get("rank")) or 999999)
                ],
            }
        )

    split_rows.sort(key=lambda item: item["best_rank"])
    passed = not split_rows
    return _check(
        "two_way_identity_policy",
        passed,
        (
            "Top public rows do not split two-way identities across hitter/pitcher rows."
            if passed
            else "Top public rows split two-way identities without a combined-value policy."
        ),
        rank_limit=TWO_WAY_POLICY_RANK_LIMIT,
        split_identity_count=len(split_rows),
        samples=split_rows[:10],
    )


def _prospect_fallback_rate(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    fallback_count = sum(
        1
        for row in top_rows
        if (row.get("score_source") or row.get("value_source")) in FALLBACK_SCORE_SOURCES
    )
    rate = round(fallback_count / len(top_rows), 4) if top_rows else 0.0
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (not sample_ready) or rate <= MAX_TOP50_FALLBACK_RATE
    return _check(
        "prospect_top50_fallback_rate",
        passed,
        (
            "Top prospect board fallback-score usage is within the publication threshold."
            if passed
            else "Top prospect board uses too many fallback-scored rows for public promotion."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        fallback_count=fallback_count,
        fallback_rate=rate,
        max_allowed_rate=MAX_TOP50_FALLBACK_RATE,
        sample_ready=sample_ready,
    )


def _prospect_pedigree_rate(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    pedigree_rows = [
        {
            "rank": row.get("prospect_rank") or row.get("rank"),
            "name": row.get("name"),
            "score": row.get("value") or row.get("score"),
            "score_source": row.get("score_source") or row.get("value_source"),
        }
        for row in top_rows
        if (row.get("score_source") or row.get("value_source")) == PEDIGREE_SCORE_SOURCE
    ]
    rate = round(len(pedigree_rows) / len(top_rows), 4) if top_rows else 0.0
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (not sample_ready) or rate <= MAX_TOP50_PEDIGREE_RATE
    return _check(
        "prospect_top50_pedigree_rate",
        passed,
        (
            "Top prospect board pedigree-only usage is within the publication threshold."
            if passed
            else "Top prospect board leans too heavily on pedigree-only scoring."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        pedigree_count=len(pedigree_rows),
        pedigree_rate=rate,
        max_allowed_rate=MAX_TOP50_PEDIGREE_RATE,
        sample_ready=sample_ready,
        samples=pedigree_rows[:10],
    )


def _level(row: dict) -> str:
    return str(row.get("level") or "").strip().upper()


def _prospect_bucket_shape(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    low_confidence_rows = [
        {
            "rank": row.get("prospect_rank") or row.get("rank"),
            "name": row.get("name"),
            "score_source": row.get("score_source") or row.get("value_source"),
            "confidence": row.get("confidence"),
        }
        for row in top_rows
        if row.get("confidence") == "low"
    ]
    lower_minors_pedigree_rows = [
        {
            "rank": row.get("prospect_rank") or row.get("rank"),
            "name": row.get("name"),
            "level": row.get("level"),
            "score_source": row.get("score_source") or row.get("value_source"),
        }
        for row in top_rows
        if (row.get("score_source") or row.get("value_source")) == PEDIGREE_SCORE_SOURCE
        and _level(row) in LOWER_LEVELS
    ]
    thin_upper_pitcher_rows = []
    for row in top_rows:
        availability = _availability_component(row)
        if (
            _is_pitcher_row(row)
            and _level(row) in UPPER_LEVELS
            and str(availability.get("status") or "").strip().lower()
            == "thin_current_sample"
        ):
            thin_upper_pitcher_rows.append(
                {
                    "rank": row.get("prospect_rank") or row.get("rank"),
                    "name": row.get("name"),
                    "level": row.get("level"),
                    "sample": availability.get("sample"),
                    "sample_unit": availability.get("sample_unit"),
                    "score_source": row.get("score_source") or row.get("value_source"),
                }
            )

    low_confidence_rate = (
        round(len(low_confidence_rows) / len(top_rows), 4) if top_rows else 0.0
    )
    failures = []
    if low_confidence_rate > MAX_TOP50_LOW_CONFIDENCE_RATE:
        failures.append("low_confidence_rate")
    if len(lower_minors_pedigree_rows) > MAX_TOP50_LOWER_MINORS_PEDIGREE_COUNT:
        failures.append("lower_minors_pedigree_count")
    if len(thin_upper_pitcher_rows) > MAX_TOP50_THIN_UPPER_LEVEL_PITCHER_COUNT:
        failures.append("thin_upper_level_pitcher_count")
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (not sample_ready) or not failures
    return _check(
        "prospect_top50_bucket_shape",
        passed,
        (
            "Top prospect board bucket shape is within publication limits."
            if passed
            else "Top prospect board has a risky bucket concentration."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        sample_ready=sample_ready,
        low_confidence_count=len(low_confidence_rows),
        low_confidence_rate=low_confidence_rate,
        max_low_confidence_rate=MAX_TOP50_LOW_CONFIDENCE_RATE,
        lower_minors_pedigree_count=len(lower_minors_pedigree_rows),
        max_lower_minors_pedigree_count=MAX_TOP50_LOWER_MINORS_PEDIGREE_COUNT,
        thin_upper_level_pitcher_count=len(thin_upper_pitcher_rows),
        max_thin_upper_level_pitcher_count=MAX_TOP50_THIN_UPPER_LEVEL_PITCHER_COUNT,
        failures=failures,
        samples={
            "low_confidence": low_confidence_rows[:8],
            "lower_minors_pedigree": lower_minors_pedigree_rows[:8],
            "thin_upper_level_pitchers": thin_upper_pitcher_rows[:8],
        },
    )


def _prospect_neutral_investment_rate(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_INVESTMENT_TOP_N]
    neutral_count = sum(
        1
        for row in top_rows
        if _components(row).get("factual_investment_missing_uses_neutral") is True
    )
    rate = round(neutral_count / len(top_rows), 4) if top_rows else 0.0
    sample_ready = len(top_rows) >= PROSPECT_INVESTMENT_TOP_N
    passed = (not sample_ready) or rate <= MAX_TOP25_NEUTRAL_INVESTMENT_RATE
    return _check(
        "prospect_top25_neutral_investment_rate",
        passed,
        (
            "Top prospect board has enough factual draft/signing context."
            if passed
            else "Top prospect board leans too heavily on neutral draft/signing context."
        ),
        top_n=PROSPECT_INVESTMENT_TOP_N,
        evaluated_count=len(top_rows),
        neutral_investment_count=neutral_count,
        neutral_investment_rate=rate,
        max_allowed_rate=MAX_TOP25_NEUTRAL_INVESTMENT_RATE,
        sample_ready=sample_ready,
    )


def _prospect_pedigree_cap_plateau(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_INVESTMENT_TOP_N]
    exact_cap_rows = []
    for row in top_rows:
        components = _components(row)
        cap = _clean_float(components.get("pedigree_score_cap"))
        score = _clean_float(row.get("value") or row.get("score"))
        if cap is None or score is None:
            continue
        if abs(score - cap) < 0.005:
            exact_cap_rows.append(
                {
                    "rank": row.get("prospect_rank") or row.get("rank"),
                    "name": row.get("name"),
                    "score": score,
                    "cap": cap,
                    "score_source": row.get("score_source") or row.get("value_source"),
                }
            )
    sample_ready = len(top_rows) >= PROSPECT_INVESTMENT_TOP_N
    passed = (not sample_ready) or len(exact_cap_rows) <= MAX_TOP25_EXACT_PEDIGREE_CAP_COUNT
    return _check(
        "prospect_top25_pedigree_cap_plateau",
        passed,
        (
            "Top prospect board is not dominated by exact pedigree-cap ties."
            if passed
            else "Top prospect board has too many exact pedigree-cap ties."
        ),
        top_n=PROSPECT_INVESTMENT_TOP_N,
        evaluated_count=len(top_rows),
        exact_pedigree_cap_count=len(exact_cap_rows),
        max_allowed_exact_pedigree_cap_count=MAX_TOP25_EXACT_PEDIGREE_CAP_COUNT,
        sample_ready=sample_ready,
        samples=exact_cap_rows[:10],
    )


def _prospect_missing_team_count(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    missing = [
        {
            "rank": row.get("prospect_rank") or row.get("rank"),
            "name": row.get("name"),
            "mlbam_id": row.get("mlbam_id"),
            "role": row.get("role"),
        }
        for row in top_rows
        if not (row.get("mlb_team") or "").strip()
    ]
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (not sample_ready) or len(missing) <= MAX_TOP50_MISSING_TEAM_COUNT
    return _check(
        "prospect_top50_team_coverage",
        passed,
        (
            "Top prospect board has complete MLB-org display coverage."
            if passed
            else "Top prospect board has missing MLB-org display coverage."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        missing_team_count=len(missing),
        max_allowed_missing_team_count=MAX_TOP50_MISSING_TEAM_COUNT,
        sample_ready=sample_ready,
        samples=missing[:10],
    )


def _prospect_factual_context_coverage(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    missing = [
        {
            "rank": row.get("prospect_rank") or row.get("rank"),
            "name": row.get("name"),
            "mlbam_id": row.get("mlbam_id"),
            "role": row.get("role"),
            "score_source": row.get("score_source") or row.get("value_source"),
        }
        for row in top_rows
        if not _factual_context_component(row)
    ]
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (
        not sample_ready
    ) or len(missing) <= MAX_TOP50_MISSING_FACTUAL_CONTEXT_COUNT
    return _check(
        "prospect_top50_factual_context_coverage",
        passed,
        (
            "Top prospect board has factual current-sample context."
            if passed
            else "Top prospect board is missing factual current-sample context."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        missing_factual_context_count=len(missing),
        max_allowed_missing_factual_context_count=(
            MAX_TOP50_MISSING_FACTUAL_CONTEXT_COUNT
        ),
        sample_ready=sample_ready,
        samples=missing[:10],
    )


def _prospect_factual_context_shape(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    caution_rows = []
    best_single_covered = []
    band_counts: dict[str, int] = defaultdict(int)
    for row in top_rows:
        context = _factual_context_component(row)
        band = str(context.get("skill_band") or "missing").strip().lower()
        band_counts[band] += 1
        if band in CAUTION_FACTUAL_CONTEXT_BANDS:
            if (
                band in BEST_SINGLE_COVERED_CAUTION_BANDS
                and _has_best_single_level_stat_line(row)
            ):
                best_single = row.get("best_single_level_stat_line") or {}
                best_single_covered.append(
                    {
                        "rank": row.get("prospect_rank") or row.get("rank"),
                        "name": row.get("name"),
                        "mlbam_id": row.get("mlbam_id"),
                        "role": row.get("role"),
                        "current_level": row.get("level"),
                        "current_skill_band": band,
                        "current_sample": context.get("sample"),
                        "current_sample_unit": context.get("sample_unit"),
                        "best_level": best_single.get("level"),
                        "best_sample": best_single.get("sample"),
                        "best_sample_unit": best_single.get("sample_unit"),
                    }
                )
                continue
            caution_rows.append(
                {
                    "rank": row.get("prospect_rank") or row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "level": row.get("level"),
                    "skill_band": band,
                    "sample": context.get("sample"),
                    "sample_unit": context.get("sample_unit"),
                }
            )

    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (
        not sample_ready
    ) or len(caution_rows) <= MAX_TOP50_CAUTION_FACTUAL_CONTEXT_COUNT
    return _check(
        "prospect_top50_factual_context_shape",
        passed,
        (
            "Top prospect board factual context shape is within publication limits."
            if passed
            else "Top prospect board has too many thin or low-impact current-sample reads."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        caution_factual_context_count=len(caution_rows),
        max_allowed_caution_factual_context_count=(
            MAX_TOP50_CAUTION_FACTUAL_CONTEXT_COUNT
        ),
        band_counts=dict(sorted(band_counts.items())),
        best_single_level_covered_count=len(best_single_covered),
        caution_bands=sorted(CAUTION_FACTUAL_CONTEXT_BANDS),
        sample_ready=sample_ready,
        samples=caution_rows[:10],
        best_single_level_samples=best_single_covered[:10],
    )


def _prospect_current_stat_context_alignment(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    mismatches = []
    evaluated = 0
    for row in top_rows:
        factual = _factual_context_component(row)
        if factual.get("source_kind") != "current_season":
            continue
        evaluated += 1
        context = row.get("context") if isinstance(row.get("context"), dict) else {}
        factual_sample = _clean_float(factual.get("sample"))
        context_sample = _clean_float(context.get("stat_line_sample"))
        factual_season = _clean_int(factual.get("sample_season"))
        context_season = _clean_int(context.get("stat_line_sample_season"))
        sample_matches = (
            factual_sample is None
            or context_sample is None
            or round(factual_sample, 1) == round(context_sample, 1)
        )
        season_matches = (
            factual_season is None
            or context_season is None
            or factual_season == context_season
        )
        if (
            context.get("stat_line_source") == "valucast_input_contract"
            and context.get("stat_line_source_kind") == "current_season"
            and sample_matches
            and season_matches
        ):
            continue
        mismatches.append(
            {
                "rank": row.get("prospect_rank") or row.get("rank"),
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "factual_sample": factual.get("sample"),
                "factual_sample_season": factual.get("sample_season"),
                "stat_line_source": context.get("stat_line_source"),
                "stat_line_source_kind": context.get("stat_line_source_kind"),
                "stat_line_sample": context.get("stat_line_sample"),
                "stat_line_sample_season": context.get("stat_line_sample_season"),
            }
        )
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (
        not sample_ready
    ) or len(mismatches) <= MAX_TOP50_CURRENT_STAT_CONTEXT_MISMATCH_COUNT
    return _check(
        "prospect_top50_current_stat_context_alignment",
        passed,
        (
            "Top prospect board stat lines align with current factual context."
            if passed
            else "Top prospect board has stale or mismatched current stat context."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=evaluated,
        current_stat_context_mismatch_count=len(mismatches),
        max_allowed_current_stat_context_mismatch_count=(
            MAX_TOP50_CURRENT_STAT_CONTEXT_MISMATCH_COUNT
        ),
        sample_ready=sample_ready,
        samples=mismatches[:10],
    )


def _milb_stat_freshness_audit_check(audit: dict | None) -> dict:
    if not audit:
        return _check(
            "milb_stat_freshness_audit",
            True,
            "MiLB stat freshness audit skipped because no audit artifact was provided.",
            audit_present=False,
            max_allowed_blockers=MAX_MILB_STAT_FRESHNESS_BLOCKERS,
        )
    blockers = list(audit.get("blockers") or [])
    metrics = audit.get("metrics") or {}
    passed = (
        audit.get("status") == "candidate_ready"
        and len(blockers) <= MAX_MILB_STAT_FRESHNESS_BLOCKERS
    )
    return _check(
        "milb_stat_freshness_audit",
        passed,
        (
            "MiLB prospect-card stat freshness audit is clean."
            if passed
            else "MiLB prospect-card stat freshness audit blocks public promotion."
        ),
        audit_present=True,
        audit_status=audit.get("status"),
        blocker_count=len(blockers),
        max_allowed_blockers=MAX_MILB_STAT_FRESHNESS_BLOCKERS,
        current_row_count=metrics.get("current_row_count"),
        current_season_row_count=metrics.get("current_season_row_count"),
        targeted_row_refresh_count=metrics.get("targeted_row_refresh_count"),
        top50_history_fallback_count=metrics.get("top50_history_fallback_count"),
        top50_stat_context_mismatch_count=metrics.get(
            "top50_stat_context_mismatch_count"
        ),
        top200_history_fallback_count=metrics.get("top200_history_fallback_count"),
        blockers=blockers[:10],
    )


def _prospect_card_data_audit_check(audit: dict | None) -> dict:
    if not audit:
        return _check(
            "prospect_card_data_audit",
            True,
            "Prospect card data audit skipped because no audit artifact was provided.",
            audit_present=False,
        )
    metrics = audit.get("metrics") or {}
    blockers = list((audit.get("validation") or {}).get("blockers") or [])
    passed = (
        audit.get("status") == "candidate_ready"
        and (audit.get("validation") or {}).get("ready_for_cards") is True
    )
    return _check(
        "prospect_card_data_audit",
        passed,
        (
            "Prospect card identity, level, stat-context, and graduation audit is clean."
            if passed
            else "Prospect card data audit blocks public promotion."
        ),
        audit_present=True,
        audit_status=audit.get("status"),
        top200_count=metrics.get("top200_count"),
        top200_watch_count=metrics.get("top200_watch_count"),
        active_mlb_level_count=metrics.get("active_mlb_level_count"),
        missing_stat_line_count=metrics.get("missing_stat_line_count"),
        blockers=blockers[:10],
    )


def _recent_signal_report_check(report: dict | None) -> dict:
    if not report:
        return _check(
            "recent_signal_report",
            True,
            "Recent signal report skipped because no report artifact was provided.",
            report_present=False,
        )
    summary = report.get("summary") or {}
    blockers = list((report.get("validation") or {}).get("blockers") or [])
    passed = (
        report.get("status") == "candidate_ready"
        and (report.get("validation") or {}).get("ready_for_recent_signal") is True
    )
    return _check(
        "recent_signal_report",
        passed,
        (
            "Recent movement signal is available for cards and scouting reports."
            if passed
            else "Recent movement signal is not ready."
        ),
        report_present=True,
        report_status=report.get("status"),
        signal_count=summary.get("signal_count"),
        top_mover_count=summary.get("top_mover_count"),
        archive_day_span=summary.get("archive_day_span"),
        blockers=blockers[:10],
    )


def _prospect_availability_coverage(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    missing = [
        {
            "rank": row.get("prospect_rank") or row.get("rank"),
            "name": row.get("name"),
            "mlbam_id": row.get("mlbam_id"),
            "role": row.get("role"),
        }
        for row in top_rows
        if not _availability_component(row).get("present")
    ]
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (
        not sample_ready
    ) or len(missing) <= MAX_TOP50_MISSING_AVAILABILITY_COUNT
    return _check(
        "prospect_top50_availability_coverage",
        passed,
        (
            "Top prospect board has availability/risk components."
            if passed
            else "Top prospect board is missing availability/risk pricing."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        missing_availability_count=len(missing),
        max_allowed_missing_availability_count=MAX_TOP50_MISSING_AVAILABILITY_COUNT,
        sample_ready=sample_ready,
        samples=missing[:10],
    )


def _prospect_availability_level_alignment(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    mismatches = []
    evaluated = 0
    for row in top_rows:
        availability = _availability_component(row)
        if not availability:
            continue
        evaluated += 1
        row_level = _level(row)
        availability_level = str(availability.get("level") or "").strip().upper()
        if _is_active_callup_bridge(row) and row_level == "MLB" and availability_level:
            continue
        if row_level and availability_level and row_level == availability_level:
            continue
        mismatches.append(
            {
                "rank": row.get("prospect_rank") or row.get("rank"),
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "board_level": row.get("level"),
                "availability_level": availability.get("level"),
                "availability_status": availability.get("status"),
                "availability_risk_level": availability.get("risk_level"),
            }
        )
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (
        not sample_ready
    ) or len(mismatches) <= MAX_TOP50_AVAILABILITY_LEVEL_MISMATCH_COUNT
    return _check(
        "prospect_top50_availability_level_alignment",
        passed,
        (
            "Top prospect board level labels align with availability-selected current levels."
            if passed
            else "Top prospect board level labels disagree with availability-selected current level."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=evaluated,
        level_mismatch_count=len(mismatches),
        max_allowed_level_mismatch_count=MAX_TOP50_AVAILABILITY_LEVEL_MISMATCH_COUNT,
        sample_ready=sample_ready,
        samples=mismatches[:10],
    )


def _availability_is_risky(availability: dict) -> bool:
    risk_level = str(availability.get("risk_level") or "").strip().lower()
    status = str(availability.get("status") or "").strip().lower()
    return risk_level in {"low", "medium", "high"} or status not in CLEAR_AVAILABILITY_STATUSES


def _prospect_availability_risk_pricing(players: list[dict]) -> dict:
    top_rows = _public_prospect_rows(players)[:PROSPECT_FALLBACK_TOP_N]
    unpriced = []
    priced_risk_count = 0
    for row in top_rows:
        availability = _availability_component(row)
        if not availability:
            continue
        discount = _clean_float(availability.get("risk_discount")) or 0.0
        if _availability_is_risky(availability):
            if discount <= 0:
                unpriced.append(
                    {
                        "rank": row.get("prospect_rank") or row.get("rank"),
                        "name": row.get("name"),
                        "mlbam_id": row.get("mlbam_id"),
                        "role": row.get("role"),
                        "status": availability.get("status"),
                        "risk_level": availability.get("risk_level"),
                        "risk_discount": availability.get("risk_discount"),
                    }
                )
            else:
                priced_risk_count += 1
    sample_ready = len(top_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (
        not sample_ready
    ) or len(unpriced) <= MAX_TOP50_UNPRICED_AVAILABILITY_RISK_COUNT
    return _check(
        "prospect_top50_availability_risk_pricing",
        passed,
        (
            "Top prospect board prices labeled availability risk."
            if passed
            else "Top prospect board has unpriced availability risk."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rows),
        priced_availability_risk_count=priced_risk_count,
        unpriced_availability_risk_count=len(unpriced),
        max_allowed_unpriced_availability_risk_count=(
            MAX_TOP50_UNPRICED_AVAILABILITY_RISK_COUNT
        ),
        sample_ready=sample_ready,
        samples=unpriced[:10],
    )


def _prospect_rank_surface_suppression(
    prospect_rank: dict | None,
    players: list[dict],
    graduated_prospect_ids: set[str] | None = None,
) -> dict:
    top_rank_rows = _prospect_rank_rows(prospect_rank)[:PROSPECT_FALLBACK_TOP_N]
    graduated_prospect_ids = graduated_prospect_ids or set()
    public_prospect_ids = {
        mlbam_id
        for row in _public_prospect_rows(players)
        if (mlbam_id := _mlbam_id(row))
    }
    public_mlb_ids = {
        mlbam_id
        for row in players
        if row.get("player_type") == "mlb" and (mlbam_id := _mlbam_id(row))
    }
    missing = []
    graduated_to_mlb = []
    for row in top_rank_rows:
        level = str(row.get("level") or "").strip().upper()
        if level == "MLB":
            continue
        mlbam_id = _mlbam_id(row)
        if mlbam_id in public_prospect_ids:
            continue
        if mlbam_id in public_mlb_ids or mlbam_id in graduated_prospect_ids:
            graduated_to_mlb.append(
                {
                    "rank": row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "level": row.get("level"),
                    "score": row.get("score"),
                    "score_source": row.get("score_source"),
                    "graduation_surface": (
                        "public_mlb"
                        if mlbam_id in public_mlb_ids
                        else "active_mlb_roster"
                    ),
                }
            )
            continue
        if mlbam_id not in public_prospect_ids:
            missing.append(
                {
                    "rank": row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "level": row.get("level"),
                    "score": row.get("score"),
                    "score_source": row.get("score_source"),
                }
            )
    sample_ready = len(top_rank_rows) >= PROSPECT_FALLBACK_TOP_N
    passed = (not sample_ready) or len(missing) <= MAX_TOP50_SUPPRESSED_RANK_ROWS
    return _check(
        "prospect_rank_surface_suppression",
        passed,
        (
            "Top Prospect Rank v1 rows are present on the public prospect surface."
            if passed
            else "Top Prospect Rank v1 rows are missing from the public prospect surface."
        ),
        top_n=PROSPECT_FALLBACK_TOP_N,
        evaluated_count=len(top_rank_rows),
        suppressed_count=len(missing),
        graduated_to_mlb_count=len(graduated_to_mlb),
        max_allowed_suppressed_count=MAX_TOP50_SUPPRESSED_RANK_ROWS,
        sample_ready=sample_ready,
        samples=missing[:10],
        graduated_samples=graduated_to_mlb[:10],
    )


def _prospect_elite_factual_fallback_audit(
    prospect_coverage_audit: dict | None,
) -> dict:
    if not prospect_coverage_audit:
        return _check(
            "prospect_elite_factual_raw_fallback_audit",
            True,
            "Prospect elite factual fallback audit skipped because no audit artifact was provided.",
            audit_present=False,
            max_allowed_elite_factual_raw_fallback_top_200=MAX_ELITE_FACTUAL_RAW_FALLBACK_TOP200,
        )

    metrics = prospect_coverage_audit.get("metrics") or {}
    count = int(metrics.get("elite_factual_raw_fallback_top_200_count") or 0)
    passed = count <= MAX_ELITE_FACTUAL_RAW_FALLBACK_TOP200
    return _check(
        "prospect_elite_factual_raw_fallback_audit",
        passed,
        (
            "Elite factual lower-minors prospects are not stuck on raw fallback scoring."
            if passed
            else "Elite factual lower-minors prospects remain on raw fallback scoring."
        ),
        audit_present=True,
        audit_status=prospect_coverage_audit.get("status"),
        elite_factual_raw_fallback_top_200_count=count,
        max_allowed_elite_factual_raw_fallback_top_200=MAX_ELITE_FACTUAL_RAW_FALLBACK_TOP200,
        samples=(prospect_coverage_audit.get("elite_factual_raw_fallback_misses") or [])[:10],
    )


def _buy_surface_alignment(
    buy_signals: dict | None,
    players: list[dict],
    graduated_prospect_ids: set[str] | None = None,
) -> dict:
    board = list((buy_signals or {}).get("board") or [])[:BUY_SURFACE_TOP_N]
    if not board:
        return _check(
            "buy_top40_public_surface_alignment",
            True,
            "ValuCast Buy surface alignment skipped because no buy board rows were provided.",
            top_n=BUY_SURFACE_TOP_N,
            evaluated_count=0,
            buy_artifact_present=bool(buy_signals),
        )

    prospect_by_key = {
        key: row
        for row in _public_prospect_rows(players)
        if (key := _identity_key(row)) is not None
    }
    public_mlb_ids = {
        mlbam_id
        for row in players
        if row.get("player_type") == "mlb" and (mlbam_id := _mlbam_id(row))
    }
    graduated_prospect_ids = graduated_prospect_ids or set()
    missing = []
    graduated_or_mlb = []
    level_mismatches = []
    team_mismatches = []
    undisclosed_availability = []

    for row in board:
        key = _identity_key(row)
        if key is None:
            missing.append(
                {
                    "rank": row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "reason": "missing_identity",
                }
            )
            continue

        mlbam_id, _role = key
        if _level(row) == "MLB" or mlbam_id in public_mlb_ids or mlbam_id in graduated_prospect_ids:
            graduated_or_mlb.append(
                {
                    "rank": row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "level": row.get("level"),
                }
            )
            continue

        public_row = prospect_by_key.get(key)
        if public_row is None:
            missing.append(
                {
                    "rank": row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "reason": "not_on_public_prospect_surface",
                }
            )
            continue

        buy_level = _level(row)
        public_level = _level(public_row)
        if buy_level and public_level and buy_level != public_level:
            level_mismatches.append(
                {
                    "rank": row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "buy_level": row.get("level"),
                    "public_level": public_row.get("level"),
                }
            )

        buy_team = _team(row)
        public_team = _team(public_row)
        if buy_team and public_team and buy_team != public_team:
            team_mismatches.append(
                {
                    "rank": row.get("rank"),
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "buy_team": row.get("team"),
                    "public_team": public_row.get("mlb_team") or public_row.get("team"),
                }
            )

        availability = _availability_component(public_row)
        if _availability_is_risky(availability):
            public_status = str(availability.get("status") or "").strip().lower()
            buy_status = str(row.get("availability_status") or "").strip().lower()
            public_discount = _clean_float(availability.get("risk_discount")) or 0.0
            buy_discount = _clean_float(row.get("availability_risk_discount")) or 0.0
            if not buy_status or buy_status != public_status or buy_discount < public_discount:
                undisclosed_availability.append(
                    {
                        "rank": row.get("rank"),
                        "name": row.get("name"),
                        "mlbam_id": row.get("mlbam_id"),
                        "public_status": availability.get("status"),
                        "buy_status": row.get("availability_status"),
                        "public_risk_discount": availability.get("risk_discount"),
                        "buy_risk_discount": row.get("availability_risk_discount"),
                    }
                )

    failures = []
    if len(missing) > MAX_BUY_TOP40_MISSING_PUBLIC_PROSPECT_COUNT:
        failures.append("missing_public_prospect")
    if len(graduated_or_mlb) > MAX_BUY_TOP40_GRADUATED_OR_MLB_COUNT:
        failures.append("graduated_or_mlb")
    if len(level_mismatches) > MAX_BUY_TOP40_LEVEL_MISMATCH_COUNT:
        failures.append("level_mismatch")
    if len(team_mismatches) > MAX_BUY_TOP40_TEAM_MISMATCH_COUNT:
        failures.append("team_mismatch")
    if len(undisclosed_availability) > MAX_BUY_TOP40_UNDISCLOSED_AVAILABILITY_RISK_COUNT:
        failures.append("undisclosed_availability_risk")
    passed = not failures
    return _check(
        "buy_top40_public_surface_alignment",
        passed,
        (
            "ValuCast Buy rows align with the public prospect surface."
            if passed
            else "ValuCast Buy rows have stale level/team/graduation or availability context."
        ),
        top_n=BUY_SURFACE_TOP_N,
        evaluated_count=len(board),
        missing_public_prospect_count=len(missing),
        max_missing_public_prospect_count=MAX_BUY_TOP40_MISSING_PUBLIC_PROSPECT_COUNT,
        graduated_or_mlb_count=len(graduated_or_mlb),
        max_graduated_or_mlb_count=MAX_BUY_TOP40_GRADUATED_OR_MLB_COUNT,
        level_mismatch_count=len(level_mismatches),
        max_level_mismatch_count=MAX_BUY_TOP40_LEVEL_MISMATCH_COUNT,
        team_mismatch_count=len(team_mismatches),
        max_team_mismatch_count=MAX_BUY_TOP40_TEAM_MISMATCH_COUNT,
        undisclosed_availability_risk_count=len(undisclosed_availability),
        max_undisclosed_availability_risk_count=(
            MAX_BUY_TOP40_UNDISCLOSED_AVAILABILITY_RISK_COUNT
        ),
        failures=failures,
        samples={
            "missing_public_prospect": missing[:8],
            "graduated_or_mlb": graduated_or_mlb[:8],
            "level_mismatch": level_mismatches[:8],
            "team_mismatch": team_mismatches[:8],
            "undisclosed_availability_risk": undisclosed_availability[:8],
        },
    )


def _buy_promotion_check(
    buy_signals: dict | None,
    buy_review: dict | None,
    public_board_ready: bool,
) -> dict:
    validation = (buy_signals or {}).get("validation") or {}
    review_status = (buy_review or {}).get("review_status")
    row_count = int(validation.get("row_count") or 0)
    history_limited_count = int(validation.get("history_limited_count") or 0)
    history_limited_rate = (
        round(history_limited_count / max(row_count, 1), 4) if row_count else 0.0
    )
    review_ready = review_status in {"candidate_ready", "approved"}
    buy_validation_ready = bool(validation.get("ready_for_live_consumers"))
    top_board_quality = validation.get("top_board_quality") or {}
    low_confidence_rate = _clean_float(top_board_quality.get("low_confidence_rate")) or 0.0
    pedigree_rate = _clean_float(top_board_quality.get("pedigree_rate")) or 0.0
    review_policy = (buy_review or {}).get("source_policy") or {}
    review_decision = (buy_review or {}).get("promotion_decision") or {}
    history_launch_approved = (
        validation.get("history_launch_approved") is True
        or review_policy.get("history_launch_approved") is True
        or review_decision.get("neutral_momentum_launch_approved") is True
    )
    history_ready = (
        history_limited_rate <= MAX_BUY_HISTORY_LIMITED_RATE
        or history_launch_approved
    )
    passed = (
        public_board_ready
        and bool(buy_signals)
        and bool(buy_review)
        and buy_validation_ready
        and review_ready
        and history_ready
        and low_confidence_rate <= MAX_BUY_TOP40_LOW_CONFIDENCE_RATE
        and pedigree_rate <= MAX_BUY_TOP40_PEDIGREE_RATE
    )
    return _check(
        "buy_promotion_gate",
        passed,
        (
            "ValuCast-owned Buy signals pass promotion checks."
            if passed
            else "ValuCast-owned Buy signals are not approved for public promotion."
        ),
        buy_artifact_present=bool(buy_signals),
        buy_review_present=bool(buy_review),
        buy_validation_ready=buy_validation_ready,
        review_status=review_status,
        review_ready=review_ready,
        row_count=row_count,
        history_limited_count=history_limited_count,
        history_limited_rate=history_limited_rate,
        max_history_limited_rate=MAX_BUY_HISTORY_LIMITED_RATE,
        history_launch_approved=history_launch_approved,
        history_ready=history_ready,
        low_confidence_rate=low_confidence_rate,
        max_low_confidence_rate=MAX_BUY_TOP40_LOW_CONFIDENCE_RATE,
        pedigree_rate=pedigree_rate,
        max_pedigree_rate=MAX_BUY_TOP40_PEDIGREE_RATE,
        public_board_ready=public_board_ready,
    )


def _movers_surface_check(movers: dict | None) -> dict:
    policy = (movers or {}).get("source_policy") or {}
    validation = (movers or {}).get("validation") or {}
    rising_count = int(validation.get("rising_count") or 0)
    cooling_count = int(validation.get("cooling_count") or 0)
    policy_ok = (
        policy.get("kind") == "valucast_prospect_movers"
        and policy.get("feeds_model_score") is False
        and policy.get("feeds_public_rank") is False
        and policy.get("feeds_buy_score") is False
        and policy.get("dd_values_used") is False
        and policy.get("dd_ranks_used") is False
        and policy.get("dd_context_used") is False
    )
    passed = bool(movers) and bool((movers or {}).get("generated_at")) and policy_ok
    return _check(
        "movers_surface_gate",
        passed,
        (
            "ValuCast Prospect Movers artifact is ready for public display."
            if passed
            else "ValuCast Prospect Movers artifact is missing or not native."
        ),
        movers_artifact_present=bool(movers),
        generated_at=(movers or {}).get("generated_at"),
        policy_ok=policy_ok,
        rising_count=rising_count,
        cooling_count=cooling_count,
    )


def _blocker_messages(checks: list[dict]) -> list[str]:
    return [
        str(check["message"])
        for check in checks
        if check.get("status") != "passed"
    ]


def _surface_check(check: dict, surface: str) -> dict:
    if surface not in BOARD_CHECK_SURFACES:
        raise ValueError(f"Unknown ValuCast board-check surface: {surface!r}")
    return {**check, "surface": surface}


def _checks_for_surface(checks: list[dict], surface: str) -> list[dict]:
    missing = [
        str(check.get("id") or "<unknown>")
        for check in checks
        if check.get("surface") not in BOARD_CHECK_SURFACES
    ]
    if missing:
        raise ValueError(
            "ValuCast board checks missing explicit surface attribution: "
            + ", ".join(missing)
        )
    return [
        check
        for check in checks
        if check.get("surface") in {surface, SURFACE_BOTH}
    ]


def _dd_score_source_audit(players: list[dict]) -> dict:
    """Block if any SERVED value/score originates from DD or an external board.

    The snapshot's source_policy independence flags are literals; this derives the
    truth from real row sources so a DD/external-derived score can never be served
    while the flag still claims False. External boards (CFR/HKB/Pipeline) may be
    DISPLAYED as comparison context but must never influence a ValuCast number.
    """
    offenders = [
        (str(row.get("id")), src)
        for row in players
        for src in (str(row.get("value_source") or ""), str(row.get("score_source") or ""))
        if any(token in src.lower() for token in DD_DERIVED_SOURCE_TOKENS)
    ]
    return _check(
        "dd_score_source_audit",
        passed=not offenders,
        message=(
            "no served score/value originates from DD or an external board"
            if not offenders
            else f"{len(offenders)} row score/value source is DD/external-derived"
        ),
        offenders=offenders[:10],
        offender_count=len(offenders),
    )


def evaluate_quality_governor(
    public_snapshot_or_rows: dict | list[dict] | None,
    prospect_rank: dict | None = None,
    previous_prospect_rank: dict | None = None,
    prospect_coverage_audit: dict | None = None,
    mlb_layer: dict | None = None,
    buy_signals: dict | None = None,
    buy_review: dict | None = None,
    movers: dict | None = None,
    milb_stat_freshness_audit: dict | None = None,
    prospect_card_data_audit: dict | None = None,
    recent_signal_report: dict | None = None,
    generated_at: str | None = None,
    graduated_prospect_ids: set[str] | None = None,
) -> dict:
    """Evaluate whether current ValuCast-owned outputs can power public surfaces."""
    players = _player_rows(public_snapshot_or_rows)
    generated_at = generated_at or _generated_at(
        public_snapshot_or_rows if isinstance(public_snapshot_or_rows, dict) else None,
        prospect_rank,
        prospect_coverage_audit,
        mlb_layer,
        buy_signals,
        movers,
    )
    if graduated_prospect_ids is None and isinstance(public_snapshot_or_rows, dict):
        graduated_prospect_ids = {
            str(row.get("mlbam_id"))
            for row in (
                (public_snapshot_or_rows.get("validation") or {}).get(
                    "prospects_excluded_by_mlb_identity_sample"
                )
                or []
            )
            if row.get("mlbam_id") not in (None, "")
        }

    board_checks = [
        _surface_check(_top_mlb_value_gap(players), SURFACE_DYNASTY),
        _surface_check(_mlb_projection_stability_outliers(players), SURFACE_DYNASTY),
        _surface_check(_mlb_top_board_role_shape(players), SURFACE_DYNASTY),
        _surface_check(
            _prospect_top_board_role_shape(prospect_rank, players),
            SURFACE_PROSPECTS,
        ),
        _surface_check(
            _prospect_transition_continuity(prospect_rank, previous_prospect_rank),
            SURFACE_PROSPECTS,
        ),
        _surface_check(_two_way_policy(players), SURFACE_BOTH),
        _surface_check(
            _prospect_rank_surface_suppression(
                prospect_rank,
                players,
                graduated_prospect_ids,
            ),
            SURFACE_PROSPECTS,
        ),
        _surface_check(
            _prospect_elite_factual_fallback_audit(prospect_coverage_audit),
            SURFACE_PROSPECTS,
        ),
        _surface_check(_prospect_fallback_rate(players), SURFACE_PROSPECTS),
        _surface_check(_prospect_pedigree_rate(players), SURFACE_PROSPECTS),
        _surface_check(_prospect_bucket_shape(players), SURFACE_PROSPECTS),
        _surface_check(_prospect_neutral_investment_rate(players), SURFACE_PROSPECTS),
        _surface_check(_prospect_pedigree_cap_plateau(players), SURFACE_PROSPECTS),
        _surface_check(_prospect_missing_team_count(players), SURFACE_PROSPECTS),
        _surface_check(_prospect_factual_context_coverage(players), SURFACE_PROSPECTS),
        _surface_check(_prospect_factual_context_shape(players), SURFACE_PROSPECTS),
        _surface_check(
            _prospect_current_stat_context_alignment(players),
            SURFACE_PROSPECTS,
        ),
        _surface_check(
            _milb_stat_freshness_audit_check(milb_stat_freshness_audit),
            SURFACE_PROSPECTS,
        ),
        _surface_check(
            _prospect_card_data_audit_check(prospect_card_data_audit),
            SURFACE_PROSPECTS,
        ),
        _surface_check(
            _recent_signal_report_check(recent_signal_report),
            SURFACE_PROSPECTS,
        ),
        _surface_check(_prospect_availability_coverage(players), SURFACE_PROSPECTS),
        _surface_check(
            _prospect_availability_level_alignment(players),
            SURFACE_PROSPECTS,
        ),
        _surface_check(
            _prospect_availability_risk_pricing(players),
            SURFACE_PROSPECTS,
        ),
        _surface_check(_dd_score_source_audit(players), SURFACE_BOTH),
    ]
    public_board_ready = all(check["status"] == "passed" for check in board_checks)
    buy_relevant_board_checks = [
        check
        for check in board_checks
        if check.get("id") not in BUY_IRRELEVANT_BOARD_CHECK_IDS
    ]
    buy_relevant_board_ready = all(
        check["status"] == "passed" for check in buy_relevant_board_checks
    )
    dynasty_checks = _checks_for_surface(board_checks, SURFACE_DYNASTY)
    prospect_checks = _checks_for_surface(board_checks, SURFACE_PROSPECTS)
    dynasty_board_ready = all(check["status"] == "passed" for check in dynasty_checks)
    prospect_board_ready = all(check["status"] == "passed" for check in prospect_checks)
    buy_board_checks = [
        _buy_surface_alignment(
            buy_signals,
            players,
            graduated_prospect_ids,
        )
    ]
    buy_check = _buy_promotion_check(
        buy_signals,
        buy_review,
        public_board_ready=buy_relevant_board_ready,
    )
    buy_checks = buy_board_checks + [buy_check]
    movers_check = _movers_surface_check(movers)

    board_blockers = _blocker_messages(board_checks)
    buy_board_blockers = _blocker_messages(buy_relevant_board_checks)
    buy_blockers = list(
        dict.fromkeys(buy_board_blockers + _blocker_messages(buy_checks))
    )
    buy_ready = all(check["status"] == "passed" for check in buy_checks)
    mover_blockers = _blocker_messages([movers_check])
    movers_ready = movers_check["status"] == "passed"
    surface_blockers = {
        SURFACE_DYNASTY: _blocker_messages(dynasty_checks),
        SURFACE_PROSPECTS: _blocker_messages(prospect_checks),
        SURFACE_BUYS: buy_blockers,
        SURFACE_MOVERS: mover_blockers,
    }
    return {
        "artifact": "valucast_quality_governor",
        "governor_name": GOVERNOR_NAME,
        "governor_version": GOVERNOR_VERSION,
        "generated_at": generated_at,
        "status": "candidate_ready" if public_board_ready else "blocked",
        "ready_for_public_snapshot": public_board_ready,
        "ready_for_buys_promotion": buy_ready,
        "ready_for_movers": movers_ready,
        "source_policy": {
            "kind": "model_output_quality_gate",
            "feeds_model_score": False,
            "dd_values_used_for_model_score": False,
            "dd_ranks_used_for_model_score": False,
            "external_rankings_used_for_model_score": False,
        },
        "criteria": {
            "max_top_mlb_value_gap": MAX_TOP_MLB_VALUE_GAP,
            "mlb_stability_top_n": MLB_STABILITY_TOP_N,
            "mlb_role_shape_top_n": MLB_ROLE_SHAPE_TOP_N,
            "max_top25_mlb_pitcher_count": MAX_TOP25_MLB_PITCHER_COUNT,
            "max_top25_mlb_reliever_count": MAX_TOP25_MLB_RELIEVER_COUNT,
            "max_top_mlb_current_over_ros_gap": MAX_TOP_MLB_CURRENT_OVER_ROS_GAP,
            "max_top_mlb_adjusted_over_ros_gap": MAX_TOP_MLB_ADJUSTED_OVER_ROS_GAP,
            "max_top_mlb_ros_stability_weight": MAX_TOP_MLB_ROS_STABILITY_WEIGHT,
            "two_way_policy_rank_limit": TWO_WAY_POLICY_RANK_LIMIT,
            "max_top50_fallback_rate": MAX_TOP50_FALLBACK_RATE,
            "max_top25_prospect_pitcher_count": MAX_TOP25_PROSPECT_PITCHER_COUNT,
            "max_top50_prospect_pitcher_rate": MAX_TOP50_PROSPECT_PITCHER_RATE,
            "max_top50_pedigree_rate": MAX_TOP50_PEDIGREE_RATE,
            "max_top50_low_confidence_rate": MAX_TOP50_LOW_CONFIDENCE_RATE,
            "max_top50_lower_minors_pedigree_count": MAX_TOP50_LOWER_MINORS_PEDIGREE_COUNT,
            "max_top50_thin_upper_level_pitcher_count": MAX_TOP50_THIN_UPPER_LEVEL_PITCHER_COUNT,
            "max_top50_suppressed_rank_rows": MAX_TOP50_SUPPRESSED_RANK_ROWS,
            "max_elite_factual_raw_fallback_top_200": MAX_ELITE_FACTUAL_RAW_FALLBACK_TOP200,
            "max_top25_neutral_investment_rate": MAX_TOP25_NEUTRAL_INVESTMENT_RATE,
            "max_top25_exact_pedigree_cap_count": MAX_TOP25_EXACT_PEDIGREE_CAP_COUNT,
            "max_top50_missing_team_count": MAX_TOP50_MISSING_TEAM_COUNT,
            "max_top50_missing_factual_context_count": (
                MAX_TOP50_MISSING_FACTUAL_CONTEXT_COUNT
            ),
            "max_top50_caution_factual_context_count": (
                MAX_TOP50_CAUTION_FACTUAL_CONTEXT_COUNT
            ),
            "max_top50_current_stat_context_mismatch_count": (
                MAX_TOP50_CURRENT_STAT_CONTEXT_MISMATCH_COUNT
            ),
            "max_top50_availability_level_mismatch_count": (
                MAX_TOP50_AVAILABILITY_LEVEL_MISMATCH_COUNT
            ),
            "max_milb_stat_freshness_blockers": MAX_MILB_STAT_FRESHNESS_BLOCKERS,
            "max_top50_missing_availability_count": MAX_TOP50_MISSING_AVAILABILITY_COUNT,
            "max_top50_unpriced_availability_risk_count": (
                MAX_TOP50_UNPRICED_AVAILABILITY_RISK_COUNT
            ),
            "max_buy_history_limited_rate": MAX_BUY_HISTORY_LIMITED_RATE,
            "max_buy_top40_low_confidence_rate": MAX_BUY_TOP40_LOW_CONFIDENCE_RATE,
            "max_buy_top40_pedigree_rate": MAX_BUY_TOP40_PEDIGREE_RATE,
            "buy_surface_top_n": BUY_SURFACE_TOP_N,
            "max_buy_top40_missing_public_prospect_count": (
                MAX_BUY_TOP40_MISSING_PUBLIC_PROSPECT_COUNT
            ),
            "max_buy_top40_graduated_or_mlb_count": (
                MAX_BUY_TOP40_GRADUATED_OR_MLB_COUNT
            ),
            "max_buy_top40_level_mismatch_count": MAX_BUY_TOP40_LEVEL_MISMATCH_COUNT,
            "max_buy_top40_team_mismatch_count": MAX_BUY_TOP40_TEAM_MISMATCH_COUNT,
            "max_buy_top40_undisclosed_availability_risk_count": (
                MAX_BUY_TOP40_UNDISCLOSED_AVAILABILITY_RISK_COUNT
            ),
        },
        "metrics": {
            "public_row_count": len(players),
            "mlb_count": sum(1 for row in players if row.get("player_type") == "mlb"),
            "prospect_count": sum(
                1 for row in players if row.get("player_type") == "prospect"
            ),
            "generated_dates": {
                "public_snapshot": _date_part(
                    public_snapshot_or_rows.get("generated_at")
                    if isinstance(public_snapshot_or_rows, dict)
                    else generated_at
                ),
                "prospect_coverage_audit": _date_part(
                    (prospect_coverage_audit or {}).get("generated_at")
                ),
                "mlb_layer": _date_part((mlb_layer or {}).get("generated_at")),
                "prospect_rank": _date_part((prospect_rank or {}).get("generated_at")),
                "buy_signals": _date_part((buy_signals or {}).get("generated_at")),
                "buy_review": _date_part((buy_review or {}).get("generated_at")),
                "movers": _date_part((movers or {}).get("generated_at")),
                "milb_stat_freshness_audit": _date_part(
                    (milb_stat_freshness_audit or {}).get("generated_at")
                ),
                "prospect_card_data_audit": _date_part(
                    (prospect_card_data_audit or {}).get("generated_at")
                ),
                "recent_signal_report": _date_part(
                    (recent_signal_report or {}).get("generated_at")
                ),
            },
        },
        "checks": board_checks + buy_checks + [movers_check],
        "blockers": board_blockers,
        "buy_blockers": buy_blockers,
        "mover_blockers": mover_blockers,
        "surface_blockers": surface_blockers,
        "surface_readiness": {
            "dynasty": dynasty_board_ready,
            "prospects": prospect_board_ready,
            "buys": buy_ready,
            "movers": movers_ready,
        },
        "next_allowed_step": (
            "wire_public_consumers"
            if public_board_ready
            else "repair_model_quality_before_public_promotion"
        ),
    }


def _load_optional(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_quality_governor(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_quality_governor(
    public_snapshot_path: Path = PUBLIC_SNAPSHOT_PATH,
    prospect_rank_path: Path = PROSPECT_RANK_PATH,
    prospect_coverage_audit_path: Path = PROSPECT_COVERAGE_AUDIT_PATH,
    mlb_layer_path: Path = MLB_LAYER_PATH,
    buy_signals_path: Path = BUY_SIGNALS_PATH,
    buy_review_path: Path = BUY_REVIEW_PATH,
    movers_path: Path = MOVERS_PATH,
    milb_stat_freshness_audit_path: Path = MILB_STAT_FRESHNESS_AUDIT_PATH,
    prospect_card_data_audit_path: Path = PROSPECT_CARD_DATA_AUDIT_PATH,
    recent_signal_report_path: Path = RECENT_SIGNAL_REPORT_PATH,
    prospect_rank_archive_dir: Path | str = PROSPECT_RANK_ARCHIVE_DIR,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    public_snapshot = _load_optional(public_snapshot_path)
    prospect_rank = _load_optional(prospect_rank_path)
    prospect_coverage_audit = _load_optional(prospect_coverage_audit_path)
    mlb_layer = _load_optional(mlb_layer_path)
    buy_signals = _load_optional(buy_signals_path)
    buy_review = _load_optional(buy_review_path)
    movers = _load_optional(movers_path)
    milb_stat_freshness_audit = _load_optional(milb_stat_freshness_audit_path)
    prospect_card_data_audit = _load_optional(prospect_card_data_audit_path)
    recent_signal_report = _load_optional(recent_signal_report_path)
    previous_prospect_rank = (
        load_previous_prospect_rank(prospect_rank, prospect_rank_archive_dir)
        if prospect_rank is not None
        else None
    )
    payload = evaluate_quality_governor(
        public_snapshot,
        prospect_rank=prospect_rank,
        previous_prospect_rank=previous_prospect_rank,
        prospect_coverage_audit=prospect_coverage_audit,
        mlb_layer=mlb_layer,
        buy_signals=buy_signals,
        buy_review=buy_review,
        movers=movers,
        milb_stat_freshness_audit=milb_stat_freshness_audit,
        prospect_card_data_audit=prospect_card_data_audit,
        recent_signal_report=recent_signal_report,
    )
    path = write_quality_governor(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "ready_for_public_snapshot": payload["ready_for_public_snapshot"],
        "ready_for_buys_promotion": payload["ready_for_buys_promotion"],
        "ready_for_movers": payload["ready_for_movers"],
        "blocker_count": len(payload["blockers"]),
        "buy_blocker_count": len(payload["buy_blockers"]),
        "mover_blocker_count": len(payload["mover_blockers"]),
    }
