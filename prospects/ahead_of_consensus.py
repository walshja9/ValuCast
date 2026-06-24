"""Ahead-of-consensus prospect divergence report.

This reads ValuCast's own prospect-rank artifact and the external boards that
already ride along as context_only.source_ranks. For each prospect it computes
divergence = consensus_rank - valucast_rank (positive = ValuCast ranks the
player HIGHER than the public field = an early call). It is READ-ONLY context
for cards and the Backfields page; it never feeds the rank, value, or buy-score
calculations and never feeds consensus back into the ValuCast score.

The board ranks down to ~5800 while pipeline/hkb cap near ~150-300, so a raw
"biggest divergence" list is garbage (a single deep board yields +4000 nonsense).
The guards below are non-negotiable: at least two external boards, a ValuCast
rank inside 300, and a divergence of at least 25.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RANK_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_ahead_of_consensus.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"

ARTIFACT_NAME = "valucast_ahead_of_consensus"
SIGNAL_VERSION = "0.1.0"

# Mirror web/public_snapshot_models.py: the median consensus drops these
# proprietary signals and counts only the remaining external boards. cfr is a
# deep stat-formula list (scale ~1-5700) that poisons the median — excluded.
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr", "cfr_raw"})

# Noise guards. Do not loosen without fresh data — they are the line between
# ~40 credible early calls and a garbage list driven by single deep boards.
MIN_BOARDS = 2
MAX_VALUCAST_RANK = 300
MIN_DIVERGENCE = 25
MAX_AHEAD_ROWS = 25
# Boards have different depths (pipeline ~100, hkb ~650, sts/cfr run thousands
# deep). Only count a board rank inside the top-prospect ceiling so a deep-list
# rank (e.g. sts #1760) can't poison the median; deeper than this = "that board
# doesn't rate him a top prospect", which simply doesn't contribute. 600 matches
# PL+/HKB's real prospect-board depth -- deep enough to keep legit mid-board
# divergences, shallow enough to exclude the thousands-deep formula tails.
CONSENSUS_RANK_CAP = 600


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


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _board_rows(payload: dict) -> list[dict]:
    rows = payload.get("board")
    return rows if isinstance(rows, list) else []


def _source_ranks(row: dict) -> dict:
    context = row.get("context_only")
    if isinstance(context, dict) and isinstance(context.get("source_ranks"), dict):
        return context["source_ranks"]
    raw = row.get("source_ranks")
    return raw if isinstance(raw, dict) else {}


def _public_source_ranks(source_ranks: dict) -> dict:
    """Drop the proprietary signals; keep only numeric external boards.

    Ported verbatim from web/public_snapshot_models.py:105-110 — do not change
    which boards count.
    """
    return {
        source: rank
        for source, rank in (source_ranks or {}).items()
        if source not in _INTERNAL_SOURCES
        and isinstance(rank, (int, float))
        and rank <= CONSENSUS_RANK_CAP
    }


def _public_source_consensus(public_ranks: dict) -> int | None:
    """Rounded median of the external boards.

    Ported verbatim from web/public_snapshot_models.py:112-120.
    """
    ranks = sorted(public_ranks.values())
    if not ranks:
        return None
    midpoint = len(ranks) // 2
    if len(ranks) % 2:
        return round(ranks[midpoint])
    return round((ranks[midpoint - 1] + ranks[midpoint]) / 2)


def _divergence_row(row: dict) -> dict | None:
    key = _identity_key(row)
    valucast_rank = _clean_int(row.get("rank"))
    role = row.get("role")
    if valucast_rank is None or role not in {"hitter", "pitcher"}:
        return None
    public_ranks = _public_source_ranks(_source_ranks(row))
    board_count = len(public_ranks)
    consensus = _public_source_consensus(public_ranks) if board_count >= MIN_BOARDS else None
    divergence = consensus - valucast_rank if consensus is not None else None
    boards = {
        source: _clean_int(rank)
        for source, rank in sorted(public_ranks.items())
    }
    return {
        "identity_key": key,
        "mlbam_id": str(row.get("mlbam_id")) if row.get("mlbam_id") not in (None, "") else None,
        "role": role,
        "name": row.get("name"),
        "team": row.get("mlb_team") or row.get("team"),
        "valucast_rank": valucast_rank,
        "consensus_rank": consensus,
        "board_count": board_count,
        "divergence": divergence,
        "boards": boards,
        "usage": "ahead_of_consensus_context_not_live_rank_or_value",
    }


def _is_guarded(row: dict) -> bool:
    return (
        row.get("board_count", 0) >= MIN_BOARDS
        and row.get("consensus_rank") is not None
        and row.get("divergence") is not None
        and (row.get("valucast_rank") or 999999) <= MAX_VALUCAST_RANK
        and row["divergence"] >= MIN_DIVERGENCE
    )


def _earliest_ahead_dates() -> dict:
    """{identity_key: earliest ISO date ValuCast ranked the player ahead of the
    public field}. Scans the dated board archive and re-applies the SAME divergence
    guard, so a receipt reads "ValuCast has been ahead since this date" -- provable
    and timestamped (the brand wedge). Fail-soft: no archive -> {}."""
    earliest: dict[str, str] = {}
    try:
        files = sorted(ARCHIVE_DIR.glob("*.json"))
    except Exception:  # noqa: BLE001
        return earliest
    for path in files:  # ascending date -> first hit is the earliest
        date = path.stem
        try:
            board = (json.loads(path.read_text(encoding="utf-8")) or {}).get("board") or []
        except (OSError, ValueError):
            continue
        for raw in board:
            if not isinstance(raw, dict):
                continue
            cand = _divergence_row(raw)
            if cand and _is_guarded(cand) and cand["identity_key"] not in earliest:
                earliest[cand["identity_key"]] = date
    return earliest


def _days_between(start: str | None, end: str) -> int:
    if not start:
        return 0
    try:
        from datetime import date
        return max(0, (date.fromisoformat(end) - date.fromisoformat(start)).days)
    except ValueError:
        return 0


def build_ahead_of_consensus_report(
    *,
    rank_path: Path = RANK_PATH,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    rank_payload = _load_optional(rank_path)
    rows = [
        candidate
        for candidate in (
            _divergence_row(row)
            for row in _board_rows(rank_payload)
            if isinstance(row, dict)
        )
        if candidate is not None
    ]
    ahead = sorted(
        [row for row in rows if _is_guarded(row)],
        key=lambda row: (row["divergence"], -(row.get("valucast_rank") or 999999)),
        reverse=True,
    )[:MAX_AHEAD_ROWS]
    # Receipts: how long ValuCast has held each player ahead of the field (provable
    # via the dated board archive). Accrues over time -- thin while the archive is young.
    earliest_ahead = _earliest_ahead_dates()
    today = generated_at[:10]
    for row in ahead:
        since = earliest_ahead.get(row["identity_key"])
        row["ahead_since"] = since
        row["days_ahead"] = _days_between(since, today)
    divergence_by_identity = {
        row["identity_key"]: {
            "valucast_rank": row["valucast_rank"],
            "consensus_rank": row["consensus_rank"],
            "board_count": row["board_count"],
            "divergence": row["divergence"],
        }
        for row in rows
        if row.get("identity_key") and _is_guarded(row)
    }
    blockers: list[str] = []
    if not _board_rows(rank_payload):
        blockers.append("No prospect rank rows are available for ahead-of-consensus reporting.")
    if not ahead:
        blockers.append("No guarded ahead-of-consensus calls cleared the noise guards.")
    return {
        "artifact": ARTIFACT_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": "blocked" if blockers else "candidate_ready",
        "source_policy": {
            "kind": "valucast_ahead_of_consensus_report",
            "rank_artifact": "valucast_prospect_rank_v1",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "guards": {
            "min_boards": MIN_BOARDS,
            "max_valucast_rank": MAX_VALUCAST_RANK,
            "min_divergence": MIN_DIVERGENCE,
            "max_ahead_rows": MAX_AHEAD_ROWS,
        },
        "input_artifacts": {
            "rank_generated_at": rank_payload.get("generated_at"),
            "rank_row_count": len(_board_rows(rank_payload)),
        },
        "summary": {
            "evaluated_count": len(rows),
            "ahead_count": len(ahead),
            "badge_count": len(divergence_by_identity),
        },
        "validation": {
            "ready_for_ahead_of_consensus": not blockers,
            "blockers": blockers,
        },
        "ahead_of_consensus": ahead,
        "divergence_by_identity": divergence_by_identity,
    }


def run_ahead_of_consensus_report(
    *,
    rank_path: Path = RANK_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    payload = build_ahead_of_consensus_report(rank_path=rank_path)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "status": payload["status"],
        "ready_for_ahead_of_consensus": payload["validation"]["ready_for_ahead_of_consensus"],
        "ahead_count": payload["summary"]["ahead_count"],
        "badge_count": payload["summary"]["badge_count"],
    }
