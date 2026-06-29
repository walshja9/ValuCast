"""ValuCast prospect movers from denoised Rank v1 score history."""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from prospects.buys import PROSPECT_BUYS_EPOCH, _identity_key
from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH
from web.buy_score import clean_tail

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_movers.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_movers"
RANK_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"

ARTIFACT_NAME = "valucast_prospect_movers"
SIGNAL_NAME = "ValuCast Prospect Movers"
SIGNAL_VERSION = "0.1.0"
EPOCH_DATE = "-".join(PROSPECT_BUYS_EPOCH.split("-")[:3])
MAX_CURRENT_RANK = 250
SIDE_LIMIT = 12
MIN_SCORE_DELTA = 2.0


def _clean_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


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


def _day_ordinal(value: str | None) -> int | None:
    try:
        return date.fromisoformat(str(value)).toordinal()
    except ValueError:
        return None


def clean_score_tail(series: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Sort score history, then apply the shared buys step/gap guard."""
    points = []
    for date_str, score in series or []:
        score = _clean_float(score)
        if date_str and score is not None:
            points.append((str(date_str), score))
    return clean_tail(sorted(points))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _archive_payloads(path: Path = RANK_ARCHIVE_DIR) -> list[dict]:
    payloads = []
    if not path.exists():
        return payloads
    for file in sorted(path.glob("*.json")):
        try:
            payload = _load_json(file)
        except (OSError, json.JSONDecodeError):
            continue
        payload.setdefault("date", _date_part(payload.get("date") or payload.get("generated_at")) or file.stem)
        payloads.append(payload)
    return payloads


def _history_by_key(payloads: list[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    history: dict[tuple[str, str], dict[str, dict]] = {}
    for payload in payloads or []:
        archive_date = _date_part(payload.get("date") or payload.get("generated_at"))
        if not archive_date:
            continue
        for row in payload.get("board") or []:
            if not isinstance(row, dict):
                continue
            key = _identity_key(row)
            score = _clean_float(row.get("score"))
            rank = _clean_int(row.get("rank"))
            if key and score is not None:
                history.setdefault(key, {})[archive_date] = {
                    "date": archive_date,
                    "score": score,
                    "rank": rank,
                    "row": row,
                }
    return history


def _fmt_decimal(value: Any, digits: int = 3) -> str | None:
    numeric = _clean_float(value)
    if numeric is None:
        return None
    text = f"{numeric:.{digits}f}"
    return text.replace("0.", ".", 1)


def _fmt_pct(value: Any) -> str | None:
    numeric = _clean_float(value)
    if numeric is None:
        return None
    if abs(numeric) <= 1:
        numeric *= 100
    return f"{numeric:.1f}%"


def _stat_snippet(row: dict) -> str:
    context = row.get("context_only") if isinstance(row.get("context_only"), dict) else {}
    stat = context.get("combined_season_stat_line")
    if not isinstance(stat, dict):
        return ""
    level = stat.get("level_label") or stat.get("level") or row.get("level") or ""
    sample = _clean_float(stat.get("sample") or stat.get("plate_appearances") or stat.get("pa") or stat.get("ip"))
    unit = stat.get("sample_unit") or ("IP" if row.get("role") == "pitcher" else "PA")
    prefix = f"{level} {int(sample) if sample is not None else ''} {unit}".strip()
    if row.get("role") == "pitcher":
        pieces = [
            f"{_fmt_decimal(stat.get('era'), 2)} ERA" if _fmt_decimal(stat.get("era"), 2) else None,
            f"{_fmt_decimal(stat.get('whip'), 2)} WHIP" if _fmt_decimal(stat.get("whip"), 2) else None,
            f"{_fmt_pct(stat.get('k_pct'))} K%" if _fmt_pct(stat.get("k_pct")) else None,
            f"{_fmt_pct(stat.get('bb_pct'))} BB%" if _fmt_pct(stat.get("bb_pct")) else None,
        ]
    else:
        pieces = [
            f"{_fmt_decimal(stat.get('ops'))} OPS" if _fmt_decimal(stat.get("ops")) else None,
            f"{_fmt_decimal(stat.get('iso'))} ISO" if _fmt_decimal(stat.get("iso")) else None,
            f"{_fmt_pct(stat.get('k_pct'))} K%" if _fmt_pct(stat.get("k_pct")) else None,
            f"{_fmt_pct(stat.get('bb_pct'))} BB%" if _fmt_pct(stat.get("bb_pct")) else None,
        ]
    detail = ", ".join(piece for piece in pieces if piece)
    return f"{prefix}, {detail}" if prefix and detail else prefix or detail


def _why(row: dict) -> str:
    # The current stat line behind the move -- the concrete, plain-English why.
    # We intentionally do NOT surface raw model feature names ("ops x youth") or
    # the DD breakout_label (DD-sourced + can contradict the score direction).
    parts = []
    snippet = _stat_snippet(row)
    if snippet:
        parts.append(snippet)
    return " | ".join(parts)


def _current_rows(rank_payload: dict) -> list[dict]:
    rows = []
    seen: set[tuple[str, str]] = set()
    for row in rank_payload.get("board") or []:
        if not isinstance(row, dict):
            continue
        key = _identity_key(row)
        rank = _clean_int(row.get("rank"))
        score = _clean_float(row.get("score"))
        if not key or key in seen or rank is None or rank > MAX_CURRENT_RANK or score is None:
            continue
        seen.add(key)
        rows.append(row)
    return rows


def _movement_row(row: dict, start: dict, end: dict) -> dict:
    score_delta = round(end["score"] - start["score"], 2)
    start_rank = _clean_int(start.get("rank"))
    current_rank = _clean_int(end.get("rank"))
    rank_delta = (
        start_rank - current_rank
        if start_rank is not None and current_rank is not None
        else None
    )
    start_ord = _day_ordinal(start["date"])
    end_ord = _day_ordinal(end["date"])
    window_days = max(0, (end_ord or 0) - (start_ord or 0)) if start_ord and end_ord else 0
    direction = "UP" if score_delta > 0 else "DOWN"
    positions = list(row.get("positions") or [])
    return {
        "id": f"vc_mover_{row['mlbam_id']}_{row['role']}",
        "player_id": f"vc_prospect_{row['mlbam_id']}_{row['role']}",
        "mlbam_id": row.get("mlbam_id"),
        "name": row.get("name"),
        "team": row.get("mlb_team") or row.get("team") or "",
        "role": row.get("role"),
        "positions": positions,
        "pos": "/".join(positions[:2]) or "-",
        "level": row.get("level") or "-",
        "age": row.get("age"),
        "eta": row.get("eta"),
        "current_rank": current_rank,
        "current_score": round(end["score"], 2),
        "score_delta": score_delta,
        "rank_delta": rank_delta,
        "window_days": window_days,
        "movement_label": f"{direction} {score_delta:+.1f} over {window_days}d",
        "why": _why(row),
        "history_tail": [
            {"date": start["date"], "score": round(start["score"], 2), "rank": start_rank},
            {"date": end["date"], "score": round(end["score"], 2), "rank": current_rank},
        ],
    }


def build_movers_board(
    rank_payload: dict,
    history_payloads: list[dict] | None = None,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or rank_payload.get("generated_at") or datetime.now(timezone.utc).isoformat()
    current_date = _date_part(generated_at) or datetime.now(timezone.utc).date().isoformat()
    history = _history_by_key(history_payloads or [])
    rising = []
    cooling = []
    excluded_step_guard_count = 0
    history_limited_count = 0
    below_threshold_count = 0

    for row in _current_rows(rank_payload):
        key = _identity_key(row)
        if key is None:
            continue
        points_by_date = dict(history.get(key, {}))
        points_by_date[current_date] = {
            "date": current_date,
            "score": _clean_float(row.get("score")),
            "rank": _clean_int(row.get("rank")),
            "row": row,
        }
        points = sorted(points_by_date.values(), key=lambda item: item["date"])
        has_pre_epoch = any(point["date"] < EPOCH_DATE for point in points)
        filtered = [point for point in points if point["date"] >= EPOCH_DATE]
        if has_pre_epoch and filtered:
            excluded_step_guard_count += 1
        clean_scores = clean_score_tail([(point["date"], point["score"]) for point in filtered])
        if len(clean_scores) < len(filtered):
            excluded_step_guard_count += 1
        if len(clean_scores) < 2:
            history_limited_count += 1
            continue
        clean_dates = {clean_scores[0][0], clean_scores[-1][0]}
        clean_points = {point["date"]: point for point in filtered if point["date"] in clean_dates}
        start = clean_points.get(clean_scores[0][0])
        end = clean_points.get(clean_scores[-1][0])
        if not start or not end:
            history_limited_count += 1
            continue
        score_delta = end["score"] - start["score"]
        if abs(score_delta) < MIN_SCORE_DELTA:
            below_threshold_count += 1
            continue
        mover = _movement_row(row, start, end)
        if score_delta > 0:
            rising.append(mover)
        else:
            cooling.append(mover)

    rising.sort(
        key=lambda item: (
            -item["score_delta"],
            -(item.get("rank_delta") or 0),
            item.get("current_rank") or 999999,
            str(item.get("name") or ""),
        )
    )
    cooling.sort(
        key=lambda item: (
            item["score_delta"],
            item.get("rank_delta") or 0,
            item.get("current_rank") or 999999,
            str(item.get("name") or ""),
        )
    )
    rising = rising[:SIDE_LIMIT]
    cooling = cooling[:SIDE_LIMIT]
    archive_dates = sorted(
        {
            _date_part(payload.get("date") or payload.get("generated_at"))
            for payload in (history_payloads or [])
            if _date_part(payload.get("date") or payload.get("generated_at"))
        }
    )
    current_count = len(_current_rows(rank_payload))
    blockers = []
    if not current_count:
        blockers.append("No current Rank v1 rows are available for mover scoring.")
    if len(archive_dates) < 2:
        blockers.append("Fewer than two Rank v1 archive days are available; mover board may be sparse.")
    return {
        "artifact": ARTIFACT_NAME,
        "signal_name": SIGNAL_NAME,
        "signal_version": SIGNAL_VERSION,
        "epoch": PROSPECT_BUYS_EPOCH,
        "generated_at": generated_at,
        "status": "blocked" if not current_count else "candidate_ready",
        "source_policy": {
            "kind": "valucast_prospect_movers",
            "rank_archives": "valucast_prospect_rank_v1",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "dd_context_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "input_artifacts": {
            "prospect_rank_v1_version": rank_payload.get("rank_version"),
            "prospect_rank_v1_status": rank_payload.get("status"),
            "prospect_rank_v1_count": rank_payload.get("ranked_count"),
            "rank_history_artifact_count": len(history_payloads or []),
            "rank_archive_dates": archive_dates,
        },
        "summary": {
            "current_ranked_count": current_count,
            "rising_count": len(rising),
            "cooling_count": len(cooling),
            "mover_count": len(rising) + len(cooling),
            "score_delta_threshold": MIN_SCORE_DELTA,
            "current_rank_cap": MAX_CURRENT_RANK,
            "excluded_step_guard_count": excluded_step_guard_count,
        },
        "validation": {
            "ready_for_public_surface": bool(current_count),
            "rising_count": len(rising),
            "cooling_count": len(cooling),
            "history_limited_count": history_limited_count,
            "below_threshold_count": below_threshold_count,
            "excluded_step_guard_count": excluded_step_guard_count,
            "blockers": blockers,
        },
        "rising": rising,
        "cooling": cooling,
        "board": rising + cooling,
    }


def archive_movers_board(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "artifact": payload["artifact"],
        "signal_version": payload["signal_version"],
        "epoch": payload.get("epoch"),
        "generated_at": payload["generated_at"],
        "summary": payload["summary"],
        "validation": payload["validation"],
        "rising": payload["rising"],
        "cooling": payload["cooling"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run_movers_board(
    rank_path: Path = RANK_V1_PATH,
    rank_archive_dir: Path = RANK_ARCHIVE_DIR,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    rank_payload = _load_json(rank_path)
    payload = build_movers_board(rank_payload, _archive_payloads(rank_archive_dir))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)

    date_str = _date_part(payload["generated_at"]) or datetime.now(timezone.utc).date().isoformat()
    archive_path, archive_changed = archive_movers_board(payload, date_str, archive_dir)
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "rising_count": payload["summary"]["rising_count"],
        "cooling_count": payload["summary"]["cooling_count"],
        "rising": payload["rising"],
        "cooling": payload["cooling"],
        "excluded_step_guard_count": payload["validation"]["excluded_step_guard_count"],
    }
