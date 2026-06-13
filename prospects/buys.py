"""ValuCast-owned prospect buy signals.

This artifact is separate from the current DD-backed `/buys` board. It scores
the ValuCast prospect universe using ValuCast Rank v1 fields only.
"""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH
from web.buy_score import momentum_score, runway_score

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_buys"
RANK_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"

SIGNAL_NAME = "ValuCast Prospect Buy Signals"
SIGNAL_VERSION = "0.1.0"

WEIGHTS = {
    "model_strength": 0.35,
    "momentum": 0.20,
    "runway": 0.20,
    "buy_window": 0.15,
    "conviction": 0.10,
}
CONFIDENCE_SCORE = {"high": 0.9, "medium": 0.68, "low": 0.38}
SOURCE_SCORE = {
    "prospect_model_v0_6": 0.85,
    "universal_fallback": 0.45,
    "identity_only_fallback": 0.25,
}


def _clean_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _identity_key(row: dict) -> tuple[str, str] | None:
    if row.get("mlbam_id") in (None, "") or row.get("role") not in {"hitter", "pitcher"}:
        return None
    return str(row["mlbam_id"]), row["role"]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def buy_window_score(rank: int | None) -> float:
    """Pure ValuCast buy-window curve.

    Top names are already obvious. The sweet spot is the strong middle of the
    ValuCast board, where the model still likes the player but the player is not
    being promoted as an elite no-doubt prospect.
    """
    if rank is None:
        return 0.35
    if rank <= 10:
        return 0.30
    if rank <= 25:
        return 0.45
    if rank <= 75:
        return 0.90
    if rank <= 150:
        return 1.00
    if rank <= 300:
        return 0.75
    if rank <= 600:
        return 0.45
    return 0.20


def model_strength_score(row: dict) -> float:
    return _clamp01((_clean_float(row.get("score")) or 0.0) / 100.0)


def conviction_score(row: dict) -> float:
    components = row.get("components") if isinstance(row.get("components"), dict) else {}
    reliability = _clean_float(components.get("sample_reliability"))
    reliability_score = _clamp01((reliability or 0.0) / 100.0)
    confidence = CONFIDENCE_SCORE.get(row.get("confidence"), 0.5)
    source = SOURCE_SCORE.get(row.get("score_source"), 0.35)
    return round(0.45 * confidence + 0.35 * reliability_score + 0.20 * source, 4)


def _score_history(
    row: dict,
    history_by_key: dict[tuple[str, str], list[tuple[str, float]]],
    generated_at: str | None,
) -> list[tuple[str, float]]:
    key = _identity_key(row)
    points = list(history_by_key.get(key, [])) if key else []
    generated_date = _date_part(generated_at)
    score = _clean_float(row.get("score"))
    if generated_date and score is not None:
        points.append((generated_date, score))

    by_date: dict[str, float] = {}
    for date, value in points:
        if date:
            by_date[date] = value
    return sorted(by_date.items())


def _history_by_key(history_payloads: list[dict]) -> dict[tuple[str, str], list[tuple[str, float]]]:
    history: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for payload in history_payloads:
        date = _date_part(payload.get("date") or payload.get("generated_at"))
        if not date:
            continue
        for row in payload.get("board") or []:
            key = _identity_key(row)
            score = _clean_float(row.get("score"))
            if key and score is not None:
                history.setdefault(key, []).append((date, score))
    return history


def _load_history_payloads(path: Path = RANK_ARCHIVE_DIR) -> list[dict]:
    if not path.exists():
        return []
    payloads = []
    for file in sorted(path.glob("*.json")):
        try:
            payloads.append(json.loads(file.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return payloads


def _eligible(row: dict) -> bool:
    if row.get("role") not in {"hitter", "pitcher"}:
        return False
    if row.get("level") == "MLB":
        return False
    return _identity_key(row) is not None


def _terms(
    row: dict,
    history_by_key: dict[tuple[str, str], list[tuple[str, float]]],
    generated_at: str | None,
) -> dict:
    history = _score_history(row, history_by_key, generated_at)
    return {
        "model_strength": round(model_strength_score(row), 4),
        "momentum": round(momentum_score(history), 4),
        "runway": round(runway_score(row.get("age"), row.get("level")), 4),
        "buy_window": round(buy_window_score(row.get("rank")), 4),
        "conviction": conviction_score(row),
    }


def _reason(terms: dict) -> str:
    ordered = sorted(
        ((key, terms.get(key, 0.0)) for key in terms),
        key=lambda item: item[1],
        reverse=True,
    )
    top = ordered[0][0] if ordered else "model_strength"
    return {
        "model_strength": "ValuCast model strength",
        "momentum": "ValuCast score momentum",
        "runway": "Young runway",
        "buy_window": "Still in the buy window",
        "conviction": "Model conviction",
    }[top]


def _history_limited_count(rows: list[dict]) -> int:
    return sum(1 for row in rows if len(row.get("score_history") or []) < 2)


def build_buy_signals(
    rank_payload: dict,
    history_payloads: list[dict] | None = None,
) -> dict:
    generated_at = rank_payload.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    history = _history_by_key(history_payloads or [])
    scored = []
    duplicate_keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    missing_identity_count = 0

    for row in rank_payload.get("board") or []:
        key = _identity_key(row)
        if key is None:
            missing_identity_count += 1
            continue
        if key in seen:
            duplicate_keys.append(key)
            continue
        seen.add(key)
        if not _eligible(row):
            continue
        terms = _terms(row, history, generated_at)
        composite = sum(WEIGHTS[key] * terms[key] for key in WEIGHTS)
        scored.append((composite, terms, row, _score_history(row, history, generated_at)))

    scored.sort(
        key=lambda item: (
            -item[0],
            int(item[2].get("rank") or 999999),
            str(item[2].get("name") or ""),
            str(item[2].get("mlbam_id") or ""),
        )
    )
    board = []
    for rank, (composite, terms, row, score_history) in enumerate(scored, 1):
        board.append(
            {
                "rank": rank,
                "id": f"vc_buy_{row['mlbam_id']}_{row['role']}",
                "name": row.get("name"),
                "mlbam_id": row.get("mlbam_id"),
                "role": row.get("role"),
                "positions": row.get("positions") or [],
                "team": row.get("mlb_team") or "",
                "age": row.get("age"),
                "level": row.get("level"),
                "eta": row.get("eta"),
                "valucast_prospect_rank": row.get("rank"),
                "valucast_prospect_score": row.get("score"),
                "score": round(max(0.0, composite) * 100.0, 1),
                "terms": terms,
                "reason": _reason(terms),
                "confidence": row.get("confidence"),
                "score_source": row.get("score_source"),
                "score_history": score_history,
                "drivers": row.get("drivers") or [],
                "source_policy": {
                    "dd_context_used": False,
                    "public_source_ranks_used": False,
                    "external_rankings_used": False,
                    "market_values_used": False,
                },
            }
        )

    blockers = [
        "ValuCast buy signals are shadow-only until human review compares the top board against the current DD-backed /buys page.",
    ]
    if _history_limited_count(board):
        blockers.append(
            "Most buy rows have fewer than two ValuCast score-history points until the daily archive accumulates."
        )

    return {
        "status": "shadow_only",
        "signal_name": SIGNAL_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "source_policy": {
            "kind": "valucast_owned_prospect_buy_signals",
            "rank_source": "valucast_prospect_rank_v1",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "dd_context_used": False,
            "public_source_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
        },
        "score_contract": {
            "score_range": [0.0, 100.0],
            "weights": WEIGHTS,
            "buy_window": "ValuCast-rank band curve; no public-rank or market-rank gap.",
            "momentum": "ValuCast prospect score history from Rank v1 archives.",
        },
        "input_artifacts": {
            "prospect_rank_v1_version": rank_payload.get("rank_version"),
            "prospect_rank_v1_status": rank_payload.get("status"),
            "prospect_rank_v1_count": rank_payload.get("ranked_count"),
            "rank_history_artifact_count": len(history_payloads or []),
        },
        "validation": {
            "ready_for_live_consumers": False,
            "candidate_count": len(rank_payload.get("board") or []),
            "eligible_count": len(scored),
            "row_count": len(board),
            "missing_identity_count": missing_identity_count,
            "duplicate_identity_count": len(duplicate_keys),
            "history_limited_count": _history_limited_count(board),
            "ranks_contiguous": [row["rank"] for row in board] == list(range(1, len(board) + 1)),
            "blockers": blockers,
        },
        "promotion": {
            "live_consumer": "blocked",
            "feeds_live_buys": False,
            "next_allowed_step": "human_review_and_route_switch_gate",
            "reason": blockers[0],
        },
        "limitations": blockers,
        "board": board,
    }


def archive_buy_signals(
    payload: dict,
    date_str: str,
    archive_dir: Path = ARCHIVE_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "signal_version": payload["signal_version"],
        "generated_at": payload["generated_at"],
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


def run_buy_signals(
    rank_path: Path = RANK_V1_PATH,
    rank_archive_dir: Path = RANK_ARCHIVE_DIR,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    payload = build_buy_signals(rank_payload, _load_history_payloads(rank_archive_dir))
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)

    date_str = _date_part(payload["generated_at"]) or datetime.now(
        timezone.utc
    ).date().isoformat()
    archive_path, archive_changed = archive_buy_signals(payload, date_str, archive_dir)
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "row_count": payload["validation"]["row_count"],
        "eligible_count": payload["validation"]["eligible_count"],
        "ready_for_live_consumers": payload["validation"]["ready_for_live_consumers"],
    }
