"""Recent ValuCast prospect signal report.

This reads ValuCast's own prospect-rank and buys archives to explain movement.
It is context for cards, scouting reports, and graphics; it does not feed the
rank, value, or buy-score calculations.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
BUY_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
RANK_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
BUY_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_buys"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_recent_signal_report.json"

ARTIFACT_NAME = "valucast_recent_signal_report"
SIGNAL_VERSION = "0.1.0"
MAX_SIGNAL_ROWS = 300


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_optional(path: Path) -> dict:
    try:
        return _load(path)
    except Exception:  # noqa: BLE001
        return {}


def _identity_key(row: dict) -> str | None:
    if row.get("mlbam_id") in (None, "") or row.get("role") in (None, ""):
        return None
    return f"{row['mlbam_id']}_{str(row['role']).lower()}"


def _date_from_payload(path: Path, payload: dict) -> str:
    raw = payload.get("date") or payload.get("generated_at")
    return str(raw or path.stem)[:10]


def _archive_payloads(directory: Path) -> list[tuple[str, dict]]:
    payloads = []
    if not directory.exists():
        return payloads
    for path in sorted(directory.glob("*.json")):
        payload = _load_optional(path)
        if not payload:
            continue
        payloads.append((_date_from_payload(path, payload), payload))
    unique = {}
    for archive_date, payload in payloads:
        unique[archive_date] = payload
    return sorted(unique.items())


def _clean_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _board_rows(payload: dict) -> list[dict]:
    rows = payload.get("board")
    return rows if isinstance(rows, list) else []


def _history_by_identity(archives: list[tuple[str, dict]]) -> dict[str, list[dict]]:
    history: dict[str, list[dict]] = {}
    for archive_date, payload in archives:
        for row in _board_rows(payload):
            if not isinstance(row, dict):
                continue
            key = _identity_key(row)
            if not key:
                continue
            history.setdefault(key, []).append(
                {
                    "date": archive_date,
                    "rank": _clean_int(row.get("rank") or row.get("valucast_prospect_rank")),
                    "score": _clean_float(row.get("score") or row.get("valucast_prospect_score")),
                }
            )
    return history


def _buy_index(payload: dict) -> dict[str, dict]:
    indexed = {}
    for row in _board_rows(payload):
        if not isinstance(row, dict):
            continue
        key = _identity_key(row)
        if key:
            indexed[key] = row
    return indexed


def _point_at_or_before(points: list[dict], target_index: int) -> dict | None:
    if not points:
        return None
    if target_index < 0:
        return points[0]
    return points[target_index]


def _movement_label(score_delta: float | None, rank_delta: int | None, days: int) -> str:
    if score_delta is not None and abs(score_delta) >= 0.05:
        direction = "up" if score_delta > 0 else "down"
        return f"{direction} {score_delta:+.1f} in {days}d"
    if rank_delta:
        direction = "up" if rank_delta > 0 else "down"
        return f"{direction} {abs(rank_delta)} spots in {days}d"
    return "holding steady"


def _signal_row(row: dict, points: list[dict], buy_row: dict | None) -> dict:
    key = _identity_key(row)
    points = sorted(points, key=lambda item: item["date"])
    current = points[-1] if points else {
        "date": None,
        "rank": _clean_int(row.get("rank")),
        "score": _clean_float(row.get("score")),
    }
    prior3 = _point_at_or_before(points, len(points) - 4)
    prior7 = _point_at_or_before(points, len(points) - 8)
    score_now = _clean_float(current.get("score"))
    rank_now = _clean_int(current.get("rank"))
    score_3d = None
    rank_3d = None
    if prior3:
        prior_score = _clean_float(prior3.get("score"))
        prior_rank = _clean_int(prior3.get("rank"))
        if score_now is not None and prior_score is not None:
            score_3d = round(score_now - prior_score, 2)
        if rank_now is not None and prior_rank is not None:
            rank_3d = prior_rank - rank_now
    score_7d = None
    rank_7d = None
    if prior7:
        prior_score = _clean_float(prior7.get("score"))
        prior_rank = _clean_int(prior7.get("rank"))
        if score_now is not None and prior_score is not None:
            score_7d = round(score_now - prior_score, 2)
        if rank_now is not None and prior_rank is not None:
            rank_7d = prior_rank - rank_now
    buy_score = _clean_float((buy_row or {}).get("score"))
    buy_rank = _clean_int((buy_row or {}).get("rank"))
    return {
        "identity_key": key,
        "mlbam_id": str(row.get("mlbam_id")) if row.get("mlbam_id") not in (None, "") else None,
        "role": row.get("role"),
        "name": row.get("name"),
        "team": row.get("mlb_team") or row.get("team"),
        "positions": list(row.get("positions") or ()),
        "prospect_rank": rank_now,
        "prospect_score": score_now,
        "score_delta_3d": score_3d,
        "rank_delta_3d": rank_3d,
        "score_delta_7d": score_7d,
        "rank_delta_7d": rank_7d,
        "movement_label": _movement_label(score_3d, rank_3d, 3),
        "buy_rank": buy_rank,
        "buy_score": buy_score,
        "buy_reason": (buy_row or {}).get("reason"),
        "buy_terms": (buy_row or {}).get("terms") or {},
        "history_points": points[-8:],
        "usage": "recent_valucast_signal_context_not_live_rank_or_value",
    }


def build_recent_signal_report(
    *,
    rank_path: Path = RANK_PATH,
    buy_path: Path = BUY_PATH,
    rank_archive_dir: Path = RANK_ARCHIVE_DIR,
    buy_archive_dir: Path = BUY_ARCHIVE_DIR,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    rank_payload = _load_optional(rank_path)
    buy_payload = _load_optional(buy_path)
    rank_archives = _archive_payloads(rank_archive_dir)
    buy_archives = _archive_payloads(buy_archive_dir)
    rank_history = _history_by_identity(rank_archives)
    buy_index = _buy_index(buy_payload)
    rows = sorted(
        [row for row in _board_rows(rank_payload) if isinstance(row, dict)],
        key=lambda row: (_clean_int(row.get("rank")) or 999999, str(row.get("name") or "")),
    )[:MAX_SIGNAL_ROWS]
    signals = [
        _signal_row(row, rank_history.get(_identity_key(row) or "", []), buy_index.get(_identity_key(row) or ""))
        for row in rows
    ]
    top_movers = sorted(
        signals,
        key=lambda row: (
            _clean_float(row.get("score_delta_3d")) or 0.0,
            _clean_int(row.get("rank_delta_3d")) or 0,
            -(row.get("prospect_rank") or 999999),
        ),
        reverse=True,
    )[:25]
    archive_dates = [archive_date for archive_date, _payload in rank_archives]
    blockers: list[str] = []
    if not signals:
        blockers.append("No prospect rank rows are available for recent-signal reporting.")
    if len(rank_archives) < 2:
        blockers.append("Recent-signal reporting needs at least two ValuCast rank archives.")
    return {
        "artifact": ARTIFACT_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": "blocked" if blockers else "candidate_ready",
        "source_policy": {
            "kind": "valucast_recent_signal_report",
            "rank_archives": "valucast_prospect_rank_v1",
            "buy_archives": "valucast_prospect_buys",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "input_artifacts": {
            "rank_generated_at": rank_payload.get("generated_at"),
            "buy_generated_at": buy_payload.get("generated_at"),
            "rank_archive_count": len(rank_archives),
            "buy_archive_count": len(buy_archives),
            "rank_archive_dates": archive_dates,
        },
        "summary": {
            "signal_count": len(signals),
            "top_mover_count": len(top_movers),
            "archive_day_span": len(set(archive_dates)),
        },
        "validation": {
            "ready_for_recent_signal": not blockers,
            "blockers": blockers,
        },
        "top_movers": top_movers,
        "signals": signals,
    }


def run_recent_signal_report(
    *,
    rank_path: Path = RANK_PATH,
    buy_path: Path = BUY_PATH,
    rank_archive_dir: Path = RANK_ARCHIVE_DIR,
    buy_archive_dir: Path = BUY_ARCHIVE_DIR,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_recent_signal_report(
        rank_path=rank_path,
        buy_path=buy_path,
        rank_archive_dir=rank_archive_dir,
        buy_archive_dir=buy_archive_dir,
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "status": payload["status"],
        "ready_for_recent_signal": payload["validation"]["ready_for_recent_signal"],
        "signal_count": payload["summary"]["signal_count"],
        "top_mover_count": payload["summary"]["top_mover_count"],
    }
