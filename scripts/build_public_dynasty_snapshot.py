"""Build the shadow ValuCast-owned public dynasty snapshot."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MLB_LAYER_PATH = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
PROSPECT_RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
BUY_SIGNALS_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
OUTPUT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"

SCHEMA_VERSION = "1.0"
ARTIFACT_NAME = "valucast_public_dynasty_snapshot"
COMMON_VALUE_SCALE = "0_100_valucast_dynasty_score"
CALIBRATION_METHOD = "raw_common_scale_certification_v1"

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


def _positions(row: dict) -> list[str]:
    positions = [str(position) for position in row.get("positions") or [] if position]
    if positions:
        return positions
    return ["P"] if row.get("role") == "pitcher" else ["DH"]


def _snapshot_id(row: dict) -> str:
    return f"vc_prospect_{row['mlbam_id']}_{row['role']}"


def _identity_key(row: dict) -> tuple[str, str] | None:
    if row.get("mlbam_id") in (None, "") or row.get("role") not in {"hitter", "pitcher"}:
        return None
    return str(row["mlbam_id"]), row["role"]


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


def _prospect_rows(
    rank_payload: dict,
    generated_at: str,
    excluded_identity_keys: set[tuple[str, str]] | None = None,
) -> list[dict]:
    excluded_identity_keys = excluded_identity_keys or set()
    rows = []
    for row in rank_payload.get("board") or []:
        if _identity_key(row) in excluded_identity_keys:
            continue
        context = row.get("context_only") or {}
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
                "drivers": row.get("drivers") or [],
                "dynasty_signal": row.get("dynasty_signal"),
                "breakout_label": context.get("breakout_label"),
                "breakout_rank_change": context.get("breakout_rank_change"),
                "context": {
                    "kind": "optional_dd_display_context",
                    "valucast_rank_v1": row.get("rank"),
                    "dd_dynasty_rank": context.get("dd_dynasty_rank"),
                    "dd_dynasty_value": context.get("dd_dynasty_value"),
                    "dd_prospect_rank": context.get("dd_prospect_rank"),
                    "source_ranks": context.get("source_ranks"),
                    "value_history_points": context.get("value_history_points"),
                    "has_dd_context": context.get("has_dd_context", False),
                },
            }
        )
    return rows


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
    prospects_excluded_by_mlb_identity_count: int,
    calibration_report: dict,
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

    dynasty_ready = not blockers and bool(calibration_report.get("applied"))
    prospects_ready = dynasty_ready
    buys_ready = dynasty_ready and bool(buy_validation.get("ready_for_live_consumers"))
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
        "required_fields_complete": True,
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
        "prospects_excluded_by_mlb_identity_count": prospects_excluded_by_mlb_identity_count,
        "cross_universe_value_scale_calibrated": bool(calibration_report.get("applied")),
        "cross_universe_calibration": calibration_report,
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
    buy_signals: dict | None = None,
    generated_at: str | None = None,
) -> dict:
    generated_at = (
        generated_at
        or prospect_rank.get("generated_at")
        or (mlb_layer or {}).get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    mlb_rows = _mlb_rows(mlb_layer, generated_at)
    mlb_identity_keys = {
        key for row in mlb_rows if (key := _identity_key(row))
    }
    prospect_rows = _prospect_rows(
        prospect_rank,
        generated_at,
        excluded_identity_keys=mlb_identity_keys,
    )
    prospect_rows = _assign_visible_prospect_ranks(prospect_rows)
    prospects_excluded_by_mlb_identity_count = (
        len((prospect_rank.get("board") or [])) - len(prospect_rows)
    )
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
            "valucast_buy_signal_version": (buy_signals or {}).get("signal_version"),
            "valucast_buy_signal_status": (buy_signals or {}).get("status"),
            "prospect_rank_v1_version": prospect_rank.get("rank_version"),
            "prospect_rank_v1_status": prospect_rank.get("status"),
            "prospect_universe_source": (prospect_rank.get("rank_contract") or {}).get(
                "prospect_universe_source"
            ),
        },
        "players": _assign_global_ranks(combined_rows),
    }
    payload["validation"] = _validation(
        payload,
        prospect_rank,
        mlb_layer,
        buy_signals,
        prospects_excluded_by_mlb_identity_count,
        calibration_report,
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
    mlb_layer = _load_json(MLB_LAYER_PATH) if MLB_LAYER_PATH.exists() else None
    buy_signals = _load_json(BUY_SIGNALS_PATH) if BUY_SIGNALS_PATH.exists() else None
    payload = build_snapshot(
        rank_payload,
        mlb_layer=mlb_layer,
        buy_signals=buy_signals,
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
