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

from mlb.roster_status import (
    ARTIFACT_PATH as MLB_ROSTER_STATUS_PATH,
    active_roster_lookup,
)
from prospects.rank_v1 import ARTIFACT_PATH as RANK_V1_PATH
from web.buy_score import momentum_score, runway_score

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_buys.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_buys"
RANK_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
BUY_REVIEW_PATH = ROOT / "data" / "models" / "valucast_prospect_buys_review.json"

SIGNAL_NAME = "ValuCast Prospect Buy Signals"
SIGNAL_VERSION = "1.0.0"
# Bumping this constant on any future re-baseline deliberately resets the
# forward-validation evidence clock.
# 2026-07-14 epoch (plan 028): the gate-fix + calibration batch -- Phase 0
# label-leak fixes (retrains the served shadow model), thin-sample cliff
# taper, board-pool renorm parity, consensus identity joins, honest peak
# counters. ZERO scoring levers (C1 cut on evidence, C2/C3 cut on power).
# 2026-07-30 epoch: bucket-calibration 0.3.2 split-remediation re-baseline
# (registered study + owner decision, docs/audit-2026-07-29-bucket-calibration-
# 0-3-1-evaluation.md): ~320 thin-sample players return to 0.3.0 discounting
# while the transition-continuity floor stays. Without the bump the re-score
# would print as genuine mover/buy momentum.
PROSPECT_BUYS_EPOCH = "2026-07-30-bucket-calibration-0-3-2"
# Buys momentum must not read history across a scoring epoch: movers already
# floor every window at the epoch date (movers.py), but momentum_score's only
# guard is the 6-pt step filter, so a fix-day re-baseline UNDER 6 pts printed
# as real cooling/warming inside the momentum window (plan 028 amendment 2,
# option ii).
PROSPECT_BUYS_EPOCH_DATE = "-".join(PROSPECT_BUYS_EPOCH.split("-")[:3])
SIGNAL_RELEASE = "valucast_prospect_buys_v1"
LOCKED_RELEASE_STATUS = "locked"
MAX_HISTORY_LIMITED_RATE = 0.50
PROMOTION_BOARD_SIZE = 40
FEATURED_MIN_BOARDS = 3
CONSENSUS_RANK_CAP = 600
PROMOTABLE_SCORE_SOURCES = {"prospect_model_v0_6", "prospect_pedigree_v0_7"}
MAX_TOP40_RAW_FALLBACK_COUNT = 0
MAX_TOP40_MISSING_TEAM_COUNT = 0
MAX_TOP40_LOW_CONFIDENCE_RATE = 0.35
MAX_TOP40_PEDIGREE_RATE = 0.35
MAX_TOP25_PITCHER_RATE = 0.40
RAW_FALLBACK_SCORE_SOURCES = {"universal_fallback", "identity_only_fallback"}
ACTIVE_MLB_ROSTER_STATUS_REQUIRED = True
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr", "cfr_raw"})

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
    "prospect_pedigree_v0_7": 0.62,
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


def _public_source_ranks(source_ranks: dict) -> dict:
    return {
        source: rank
        for source, rank in (source_ranks or {}).items()
        if source not in _INTERNAL_SOURCES
        and isinstance(rank, (int, float))
        and rank <= CONSENSUS_RANK_CAP
    }


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
        # Epoch floor: momentum never reads across a re-baseline (option ii).
        if date and date >= PROSPECT_BUYS_EPOCH_DATE:
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


def _load_same_day_review(path: Path, generated_at: str | None) -> dict | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    if _date_part(payload.get("generated_at")) != _date_part(generated_at):
        return None
    return payload


def _load_mlb_roster_status(path: Path | None) -> dict | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def _active_mlb_roster_ids(payload: dict | None) -> set[str]:
    return set(active_roster_lookup(payload).keys())


def _eligible(row: dict, active_mlb_ids: set[str] | None = None) -> bool:
    if row.get("role") not in {"hitter", "pitcher"}:
        return False
    if row.get("level") == "MLB":
        return False
    key = _identity_key(row)
    if key and active_mlb_ids and key[0] in active_mlb_ids:
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
    top = "model_strength"
    for key, value in ordered:
        if key == "momentum" and value <= 0.4:
            continue
        top = key
        break
    return {
        "model_strength": "ValuCast model strength",
        "momentum": "ValuCast score momentum",
        "runway": "Young runway",
        "buy_window": "Still in the buy window",
        "conviction": "Model conviction",
    }[top]


def _availability_context(row: dict) -> dict:
    components = row.get("components")
    if not isinstance(components, dict):
        return {}
    availability = components.get("availability")
    return availability if isinstance(availability, dict) else {}


def _history_limited_count(rows: list[dict]) -> int:
    return sum(1 for row in rows if len(row.get("score_history") or []) < 2)


def _review_ready(review: dict | None) -> bool:
    return (review or {}).get("review_status") in {"candidate_ready", "approved"}


def _history_launch_approved(review: dict | None) -> bool:
    policy = (review or {}).get("source_policy") or {}
    return bool(policy.get("history_launch_approved"))


def _promotion_eligible(row: dict) -> bool:
    return row.get("score_source") in PROMOTABLE_SCORE_SOURCES


def _top_board_quality(board: list[dict]) -> dict:
    top_rows = board[:PROMOTION_BOARD_SIZE]
    top25_rows = board[:25]
    top25_pitcher_count = sum(1 for row in top25_rows if row.get("role") == "pitcher")
    top25_pitcher_rate = (
        round(top25_pitcher_count / len(top25_rows), 4) if top25_rows else 0.0
    )
    raw_fallback_count = sum(
        1 for row in top_rows if row.get("score_source") in RAW_FALLBACK_SCORE_SOURCES
    )
    missing_team_count = sum(1 for row in top_rows if not (row.get("team") or "").strip())
    low_confidence_count = sum(1 for row in top_rows if row.get("confidence") == "low")
    pedigree_count = sum(
        1 for row in top_rows if row.get("score_source") == "prospect_pedigree_v0_7"
    )
    source_counts: dict[str, int] = {}
    for row in top_rows:
        source = str(row.get("score_source") or "unknown")
        source_counts[source] = source_counts.get(source, 0) + 1
    blockers = []
    if top25_pitcher_rate > MAX_TOP25_PITCHER_RATE:
        blockers.append("buys_top25_pitcher_rate")
    return {
        "top_n": PROMOTION_BOARD_SIZE,
        "evaluated_count": len(top_rows),
        "top25_pitcher_count": top25_pitcher_count,
        "top25_pitcher_rate": top25_pitcher_rate,
        "max_top25_pitcher_rate": MAX_TOP25_PITCHER_RATE,
        "raw_fallback_count": raw_fallback_count,
        "missing_team_count": missing_team_count,
        "low_confidence_count": low_confidence_count,
        "low_confidence_rate": round(low_confidence_count / len(top_rows), 4)
        if top_rows
        else 0.0,
        "max_low_confidence_rate": MAX_TOP40_LOW_CONFIDENCE_RATE,
        "pedigree_count": pedigree_count,
        "pedigree_rate": round(pedigree_count / len(top_rows), 4)
        if top_rows
        else 0.0,
        "max_pedigree_rate": MAX_TOP40_PEDIGREE_RATE,
        "score_source_counts": source_counts,
        "blockers": blockers,
    }


def _release_contract(ready_for_live_consumers: bool, generated_at: str | None) -> dict:
    return {
        "release": SIGNAL_RELEASE,
        "release_status": LOCKED_RELEASE_STATUS
        if ready_for_live_consumers
        else "blocked",
        "locked_signal_version": SIGNAL_VERSION,
        "locked_at": generated_at,
        "calibration_gate": {
            "method": "bucket_calibration_review",
            "required_status": "review_ready",
            "required_flags": 0,
            "result": "passed" if ready_for_live_consumers else "blocked",
        },
        "eye_test_gate": {
            "method": "senior_review",
            "result": "approved" if ready_for_live_consumers else "blocked",
        },
        "frozen_score_contract": ready_for_live_consumers,
        "active_mlb_roster_exclusion_required": True,
        "allowed_score_sources": sorted(PROMOTABLE_SCORE_SOURCES),
    }


def build_buy_signals(
    rank_payload: dict,
    history_payloads: list[dict] | None = None,
    promotion_review: dict | None = None,
    mlb_roster_status: dict | None = None,
    require_mlb_roster_status: bool = False,
) -> dict:
    generated_at = rank_payload.get("generated_at") or datetime.now(
        timezone.utc
    ).isoformat()
    history = _history_by_key(history_payloads or [])
    active_mlb_ids = _active_mlb_roster_ids(mlb_roster_status)
    mlb_roster_validation = (mlb_roster_status or {}).get("validation") or {}
    mlb_roster_status_ready = (
        mlb_roster_validation.get("ready_for_public_snapshot") is True
    )
    scored = []
    duplicate_keys: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    missing_identity_count = 0
    excluded_score_source_count = 0
    active_mlb_roster_excluded_count = 0

    for row in rank_payload.get("board") or []:
        key = _identity_key(row)
        if key is None:
            missing_identity_count += 1
            continue
        if key in seen:
            duplicate_keys.append(key)
            continue
        seen.add(key)
        if key[0] in active_mlb_ids:
            active_mlb_roster_excluded_count += 1
            continue
        if not _eligible(row, active_mlb_ids):
            continue
        if not _promotion_eligible(row):
            excluded_score_source_count += 1
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
    for composite, terms, row, score_history in scored:
        availability = _availability_context(row)
        context = row.get("context_only") if isinstance(row.get("context_only"), dict) else {}
        board_count = len(_public_source_ranks(context.get("source_ranks") or {}))
        board.append(
            {
                "rank": 0,
                "id": f"vc_buy_{row['mlbam_id']}_{row['role']}",
                "player_id": f"vc_prospect_{row['mlbam_id']}_{row['role']}",
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
                "board_count": board_count,
                "terms": terms,
                "reason": _reason(terms),
                "confidence": row.get("confidence"),
                "availability_status": availability.get("status"),
                "availability_risk_level": availability.get("risk_level"),
                "availability_risk_discount": availability.get("risk_discount"),
                "availability_level": availability.get("level"),
                "score_source": row.get("score_source"),
                "score_history": score_history,
                "drivers": row.get("drivers") or [],
                "source_policy": {
                    "dd_context_used": False,
                    "public_source_ranks_used": True,
                    "external_rankings_used": False,
                    "market_values_used": False,
                },
            }
        )
    board = [row for row in board if row["board_count"] >= FEATURED_MIN_BOARDS]
    for rank, row in enumerate(board, 1):
        row["rank"] = rank

    history_limited_count = _history_limited_count(board)
    history_limited_rate = (
        round(history_limited_count / max(len(board), 1), 4) if board else 0.0
    )
    review_ready = _review_ready(promotion_review)
    history_ready = history_limited_rate <= MAX_HISTORY_LIMITED_RATE
    history_launch_approved = _history_launch_approved(promotion_review)
    top_quality = _top_board_quality(board)
    active_mlb_roster_overlap_count = sum(
        1 for row in board if str(row.get("mlbam_id")) in active_mlb_ids
    )
    blockers = []
    if not review_ready:
        blockers.append(
            "ValuCast Buy review has not approved changing the public /buys source."
        )
    mlb_roster_status_required = (
        ACTIVE_MLB_ROSTER_STATUS_REQUIRED or require_mlb_roster_status
    )
    if mlb_roster_status_required and not mlb_roster_status_ready:
        blockers.append(
            "Official MLB active-roster status artifact is required before promoting ValuCast Buys."
        )
    if active_mlb_roster_overlap_count:
        blockers.append("ValuCast Buy board includes active MLB roster identities.")
    if not history_ready and not history_launch_approved:
        blockers.append(
            "ValuCast Buy momentum is launch-limited until review approves neutral-momentum launch or more dated history accumulates."
        )
    if top_quality["raw_fallback_count"] > MAX_TOP40_RAW_FALLBACK_COUNT:
        blockers.append(
            "ValuCast Buy top board includes raw fallback-scored players."
        )
    if top_quality["missing_team_count"] > MAX_TOP40_MISSING_TEAM_COUNT:
        blockers.append("ValuCast Buy top board has missing MLB-org display coverage.")
    if top_quality["low_confidence_rate"] > MAX_TOP40_LOW_CONFIDENCE_RATE:
        blockers.append(
            "ValuCast Buy top board has too many low-confidence profiles."
        )
    if top_quality["pedigree_rate"] > MAX_TOP40_PEDIGREE_RATE:
        blockers.append(
            "ValuCast Buy top board leans too heavily on pedigree-only profiles."
        )
    if "buys_top25_pitcher_rate" in top_quality["blockers"]:
        blockers.append(
            "ValuCast Buy top-25 is too pitcher-heavy for public promotion."
        )
    if top_quality["evaluated_count"] < PROMOTION_BOARD_SIZE:
        blockers.append(
            "ValuCast Buy top board has too few promotion-eligible rows."
        )
    ready_for_live_consumers = not blockers
    release_contract = _release_contract(ready_for_live_consumers, generated_at)

    return {
        "status": "shadow_only",
        "signal_name": SIGNAL_NAME,
        "signal_version": SIGNAL_VERSION,
        "epoch": PROSPECT_BUYS_EPOCH,
        "generated_at": generated_at,
        "source_policy": {
            "kind": "valucast_owned_prospect_buy_signals",
            "rank_source": "valucast_prospect_rank_v1",
            "dd_values_used": False,
            "dd_ranks_used": False,
            "dd_context_used": False,
            "public_source_ranks_used": True,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
        },
        "score_contract": {
            "contract_status": "v1_locked" if ready_for_live_consumers else "blocked",
            "score_range": [0.0, 100.0],
            "weights": WEIGHTS,
            "buy_window": "ValuCast-rank band curve; no public-rank or market-rank gap.",
            "momentum": "ValuCast prospect score history from Rank v1 archives.",
            "release_notes": "Locked after bucket calibration produced zero tuning flags and the top-board quality gates passed.",
        },
        "release_contract": release_contract,
        "input_artifacts": {
            "prospect_rank_v1_version": rank_payload.get("rank_version"),
            "prospect_rank_v1_status": rank_payload.get("status"),
            "prospect_rank_v1_count": rank_payload.get("ranked_count"),
            "rank_history_artifact_count": len(history_payloads or []),
            "buy_review_status": (promotion_review or {}).get("review_status"),
            "mlb_roster_status_version": (mlb_roster_status or {}).get(
                "contract_version"
            ),
            "mlb_roster_status_ready": mlb_roster_status_ready,
            "active_mlb_roster_profile_count": len(active_mlb_ids),
        },
        "validation": {
            "ready_for_live_consumers": ready_for_live_consumers,
            "candidate_count": len(rank_payload.get("board") or []),
            "eligible_count": len(scored),
            "excluded_score_source_count": excluded_score_source_count,
            "active_mlb_roster_excluded_count": active_mlb_roster_excluded_count,
            "active_mlb_roster_overlap_count": active_mlb_roster_overlap_count,
            "mlb_roster_status_required": mlb_roster_status_required,
            "mlb_roster_status_ready": mlb_roster_status_ready,
            "row_count": len(board),
            "missing_identity_count": missing_identity_count,
            "duplicate_identity_count": len(duplicate_keys),
            "history_limited_count": history_limited_count,
            "history_limited_rate": history_limited_rate,
            "max_history_limited_rate": MAX_HISTORY_LIMITED_RATE,
            "history_ready": history_ready,
            "history_launch_approved": history_launch_approved,
            "buy_review_ready": review_ready,
            "promotion_score_sources": sorted(PROMOTABLE_SCORE_SOURCES),
            "top_board_quality": top_quality,
            "ranks_contiguous": [row["rank"] for row in board] == list(range(1, len(board) + 1)),
            "blockers": blockers,
        },
        "promotion": {
            "live_consumer": "candidate_ready" if ready_for_live_consumers else "blocked",
            "feeds_live_buys": ready_for_live_consumers,
            "next_allowed_step": (
                "monitor_forward_results_and_recalibrate_by_bucket"
                if ready_for_live_consumers
                else "human_review_and_route_switch_gate"
            ),
            "reason": (
                "ValuCast Buy signals are v1 locked for live consumers."
                if ready_for_live_consumers
                else blockers[0]
            ),
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
        "epoch": payload.get("epoch"),
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
    promotion_review_path: Path | None = None,
    mlb_roster_status_path: Path | None = MLB_ROSTER_STATUS_PATH,
) -> dict:
    rank_payload = json.loads(rank_path.read_text(encoding="utf-8"))
    promotion_review = (
        _load_same_day_review(promotion_review_path, rank_payload.get("generated_at"))
        if promotion_review_path
        else None
    )
    mlb_roster_status = _load_mlb_roster_status(mlb_roster_status_path)
    payload = build_buy_signals(
        rank_payload,
        _load_history_payloads(rank_archive_dir),
        promotion_review=promotion_review,
        mlb_roster_status=mlb_roster_status,
        require_mlb_roster_status=mlb_roster_status_path is not None,
    )
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
