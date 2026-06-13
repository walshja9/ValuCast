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


def _validation(
    payload: dict,
    rank_payload: dict,
    mlb_layer: dict | None,
    buy_signals: dict | None,
    prospects_excluded_by_mlb_identity_count: int,
) -> dict:
    players = payload.get("players") or []
    identity_keys = [key for row in players if (key := _identity_key(row))]
    duplicate_identity_count = len(identity_keys) - len(set(identity_keys))
    generated_date = _date_part(payload.get("generated_at"))
    rank_date = _date_part(rank_payload.get("generated_at"))
    mlb_date = _date_part((mlb_layer or {}).get("generated_at"))
    buy_date = _date_part((buy_signals or {}).get("generated_at"))
    mlb_validation = (mlb_layer or {}).get("validation") or {}
    buy_validation = (buy_signals or {}).get("validation") or {}
    blockers = []
    if not mlb_layer:
        blockers.append(
            "ValuCast MLB dynasty value layer artifact is missing; snapshot contains no MLB canonical values."
        )
    elif not mlb_validation.get("ready_for_live_consumers"):
        blockers.extend(
            mlb_validation.get("blockers")
            or ["ValuCast MLB dynasty value layer is still shadow-only."]
        )
    blockers.extend(
        [
            "MLB and prospect scores are not yet calibrated to one cross-universe dynasty scale.",
        ]
    )
    if not buy_signals:
        blockers.append("ValuCast-owned buy signal artifact is missing.")
    elif not buy_validation.get("ready_for_live_consumers"):
        blockers.extend(
            buy_validation.get("blockers")
            or ["ValuCast buy signals are still shadow-only."]
        )
    date_values = [generated_date, rank_date]
    if mlb_layer:
        date_values.append(mlb_date)
    if buy_signals:
        date_values.append(buy_date)
    return {
        "ready_for_live_consumers": False,
        "same_day_freshness": all(date_values) and len(set(date_values)) == 1,
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
        "valucast_buy_signal_count": buy_validation.get("row_count"),
        "valucast_buy_signals_ready": bool(
            buy_validation.get("ready_for_live_consumers")
        ),
        "prospects_excluded_by_mlb_identity_count": prospects_excluded_by_mlb_identity_count,
        "cross_universe_value_scale_calibrated": False,
        "surface_readiness": {
            "dynasty": False,
            "prospects": False,
            "buys": bool(buy_validation.get("ready_for_live_consumers")),
        },
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
    prospects_excluded_by_mlb_identity_count = (
        len((prospect_rank.get("board") or [])) - len(prospect_rows)
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
            "valucast_buy_signal_version": (buy_signals or {}).get("signal_version"),
            "valucast_buy_signal_status": (buy_signals or {}).get("status"),
            "prospect_rank_v1_version": prospect_rank.get("rank_version"),
            "prospect_rank_v1_status": prospect_rank.get("status"),
            "prospect_universe_source": (prospect_rank.get("rank_contract") or {}).get(
                "prospect_universe_source"
            ),
        },
        "players": _assign_global_ranks(mlb_rows + prospect_rows),
    }
    payload["validation"] = _validation(
        payload,
        prospect_rank,
        mlb_layer,
        buy_signals,
        prospects_excluded_by_mlb_identity_count,
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
