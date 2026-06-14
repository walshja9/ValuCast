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

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_quality_governor.json"
PUBLIC_SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
MLB_LAYER_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
PROSPECT_RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
PROSPECT_COVERAGE_AUDIT_PATH = (
    ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"
)
BUY_SIGNALS_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
BUY_REVIEW_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_review.json"

GOVERNOR_NAME = "ValuCast Quality Governor"
GOVERNOR_VERSION = "0.1.0"

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
PROSPECT_INVESTMENT_TOP_N = 25
MAX_TOP25_NEUTRAL_INVESTMENT_RATE = 0.35
MAX_TOP25_EXACT_PEDIGREE_CAP_COUNT = 3
MAX_TOP50_MISSING_TEAM_COUNT = 0
MAX_BUY_HISTORY_LIMITED_RATE = 0.50

FALLBACK_SCORE_SOURCES = {"universal_fallback", "identity_only_fallback"}


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


def _projection_stability(row: dict) -> dict:
    components = _components(row)
    stability = components.get("projection_stability")
    return stability if isinstance(stability, dict) else {}


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


def _prospect_rank_surface_suppression(prospect_rank: dict | None, players: list[dict]) -> dict:
    top_rank_rows = _prospect_rank_rows(prospect_rank)[:PROSPECT_FALLBACK_TOP_N]
    public_ids = {
        mlbam_id
        for row in _public_prospect_rows(players)
        if (mlbam_id := _mlbam_id(row))
    }
    missing = []
    for row in top_rank_rows:
        level = str(row.get("level") or "").strip().upper()
        if level == "MLB":
            continue
        mlbam_id = _mlbam_id(row)
        if mlbam_id not in public_ids:
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
        max_allowed_suppressed_count=MAX_TOP50_SUPPRESSED_RANK_ROWS,
        sample_ready=sample_ready,
        samples=missing[:10],
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
    passed = (
        public_board_ready
        and bool(buy_signals)
        and bool(buy_review)
        and buy_validation_ready
        and review_ready
        and history_limited_rate <= MAX_BUY_HISTORY_LIMITED_RATE
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
        public_board_ready=public_board_ready,
    )


def _blocker_messages(checks: list[dict]) -> list[str]:
    return [
        str(check["message"])
        for check in checks
        if check.get("status") != "passed"
    ]


def evaluate_quality_governor(
    public_snapshot_or_rows: dict | list[dict] | None,
    prospect_rank: dict | None = None,
    prospect_coverage_audit: dict | None = None,
    mlb_layer: dict | None = None,
    buy_signals: dict | None = None,
    buy_review: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    """Evaluate whether current ValuCast-owned outputs can power public surfaces."""
    players = _player_rows(public_snapshot_or_rows)
    generated_at = generated_at or _generated_at(
        public_snapshot_or_rows if isinstance(public_snapshot_or_rows, dict) else None,
        prospect_rank,
        prospect_coverage_audit,
        mlb_layer,
        buy_signals,
    )

    board_checks = [
        _top_mlb_value_gap(players),
        _mlb_projection_stability_outliers(players),
        _mlb_top_board_role_shape(players),
        _two_way_policy(players),
        _prospect_rank_surface_suppression(prospect_rank, players),
        _prospect_elite_factual_fallback_audit(prospect_coverage_audit),
        _prospect_fallback_rate(players),
        _prospect_neutral_investment_rate(players),
        _prospect_pedigree_cap_plateau(players),
        _prospect_missing_team_count(players),
    ]
    public_board_ready = all(check["status"] == "passed" for check in board_checks)
    buy_check = _buy_promotion_check(
        buy_signals,
        buy_review,
        public_board_ready=public_board_ready,
    )

    board_blockers = _blocker_messages(board_checks)
    buy_blockers = list(dict.fromkeys(board_blockers + _blocker_messages([buy_check])))
    return {
        "artifact": "valucast_quality_governor",
        "governor_name": GOVERNOR_NAME,
        "governor_version": GOVERNOR_VERSION,
        "generated_at": generated_at,
        "status": "candidate_ready" if public_board_ready else "blocked",
        "ready_for_public_snapshot": public_board_ready,
        "ready_for_buys_promotion": buy_check["status"] == "passed",
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
            "max_top50_suppressed_rank_rows": MAX_TOP50_SUPPRESSED_RANK_ROWS,
            "max_elite_factual_raw_fallback_top_200": MAX_ELITE_FACTUAL_RAW_FALLBACK_TOP200,
            "max_top25_neutral_investment_rate": MAX_TOP25_NEUTRAL_INVESTMENT_RATE,
            "max_top25_exact_pedigree_cap_count": MAX_TOP25_EXACT_PEDIGREE_CAP_COUNT,
            "max_top50_missing_team_count": MAX_TOP50_MISSING_TEAM_COUNT,
            "max_buy_history_limited_rate": MAX_BUY_HISTORY_LIMITED_RATE,
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
            },
        },
        "checks": board_checks + [buy_check],
        "blockers": board_blockers,
        "buy_blockers": buy_blockers,
        "surface_readiness": {
            "dynasty": public_board_ready,
            "prospects": public_board_ready,
            "buys": buy_check["status"] == "passed",
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
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    public_snapshot = _load_optional(public_snapshot_path)
    prospect_rank = _load_optional(prospect_rank_path)
    prospect_coverage_audit = _load_optional(prospect_coverage_audit_path)
    mlb_layer = _load_optional(mlb_layer_path)
    buy_signals = _load_optional(buy_signals_path)
    buy_review = _load_optional(buy_review_path)
    payload = evaluate_quality_governor(
        public_snapshot,
        prospect_rank=prospect_rank,
        prospect_coverage_audit=prospect_coverage_audit,
        mlb_layer=mlb_layer,
        buy_signals=buy_signals,
        buy_review=buy_review,
    )
    path = write_quality_governor(payload, artifact_path)
    return {
        "artifact_path": str(path),
        "ready_for_public_snapshot": payload["ready_for_public_snapshot"],
        "ready_for_buys_promotion": payload["ready_for_buys_promotion"],
        "blocker_count": len(payload["blockers"]),
        "buy_blocker_count": len(payload["buy_blockers"]),
    }
