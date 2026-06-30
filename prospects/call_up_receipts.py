"""Permanent receipts for ValuCast ahead-of-consensus prospect call-ups."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mlb.roster_status import active_roster_lookup
from prospects.ahead_of_consensus import (
    MAX_VALUCAST_RANK,
    MIN_BOARDS,
    MIN_DIVERGENCE,
    _public_source_consensus,
    _public_source_ranks,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_call_up_receipts.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_call_up_receipts"
RANK_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
ROSTER_PATH = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
# Curated call-ups the auto-scan can't score (field doesn't rank them, or the roster
# artifact lags a same-day promotion). ponytail: hand-maintained JSON, no admin UI.
SEED_PATH = ROOT / "data" / "manual" / "call_up_receipts_seed.json"

ARTIFACT_NAME = "valucast_call_up_receipts"
SIGNAL_NAME = "ValuCast Call-Up Receipts"
SIGNAL_VERSION = "0.1.0"


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return payload if isinstance(payload, dict) else {}


def _date_part(value: Any) -> str | None:
    if not value:
        return None
    text = str(value)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if len(text) >= 10 else None


def _clean_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _identity_key(row: dict) -> str | None:
    mlbam_id = row.get("mlbam_id")
    role = str(row.get("role") or "").lower()
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return f"{mlbam_id}_{role}"


def _rows(payload: dict | list) -> list[dict]:
    rows = payload.get("board") if isinstance(payload, dict) else payload
    return [row for row in (rows or []) if isinstance(row, dict)]


def _source_ranks(row: dict) -> dict:
    context = row.get("context_only")
    if isinstance(context, dict) and isinstance(context.get("source_ranks"), dict):
        return context["source_ranks"]
    source_ranks = row.get("source_ranks")
    return source_ranks if isinstance(source_ranks, dict) else {}


def _pos(row: dict) -> str:
    positions = row.get("positions") or []
    if isinstance(positions, str):
        positions = [positions]
    return "/".join(str(pos) for pos in positions[:2] if pos) or "-"


def _existing_receipts(existing_log: dict | list | None) -> list[dict]:
    if isinstance(existing_log, dict):
        rows = existing_log.get("receipts") or []
    else:
        rows = existing_log or []
    return [dict(row) for row in rows if isinstance(row, dict) and row.get("identity_key")]


def _seed_receipts(seed_path: Path = SEED_PATH) -> list[dict]:
    """Curated receipt rows (e.g. field-unranked guys the divergence gate can't score)."""
    payload = _load_json(seed_path)
    rows = payload.get("receipts") if isinstance(payload, dict) else None
    out = []
    for row in (rows or []):
        if not isinstance(row, dict):
            continue
        key = row.get("identity_key") or _identity_key(row)
        rank = _clean_int(row.get("valucast_rank"))
        if not key or rank is None:
            continue
        out.append({
            "identity_key": key,
            "mlbam_id": str(row.get("mlbam_id")),
            "role": str(row.get("role") or "").lower(),
            "name": row.get("name"),
            "team": row.get("team") or "-",
            "pos": row.get("pos") or "-",
            "level": row.get("level") or "-",
            "valucast_rank": rank,
            "consensus_rank": _clean_int(row.get("consensus_rank")),
            "divergence": _clean_int(row.get("divergence")),
            "field_label": row.get("field_label") or "field outside top 100",
            "call_up_date": _date_part(row.get("call_up_date")) or row.get("call_up_date"),
            "logged_at": row.get("logged_at"),
            "seed": True,
        })
    return out


def _sort_receipts(receipts: list[dict]) -> list[dict]:
    """Scored rows lead, biggest gap over the field first (the receipt's whole point);
    ties break to the better prospect. Curated (field-unranked) rows follow, newest-first."""
    scored = sorted(
        (r for r in receipts if isinstance(r.get("divergence"), int)),
        key=lambda r: (r["divergence"], -(r.get("valucast_rank") or 0)),
        reverse=True,
    )
    seeded = sorted(
        (r for r in receipts if not isinstance(r.get("divergence"), int)),
        key=lambda r: (str(r.get("call_up_date") or ""), str(r.get("name") or "")),
        reverse=True,
    )
    return scored + seeded


def _existing_misses(existing_log: dict | list | None) -> list[dict]:
    if isinstance(existing_log, dict):
        rows = existing_log.get("misses") or []
    else:
        rows = existing_log or []
    return [dict(row) for row in rows if isinstance(row, dict) and row.get("identity_key")]


def _sort_misses(misses: list[dict]) -> list[dict]:
    """Biggest miss first: most-negative divergence (field furthest ahead of us)."""
    return sorted(
        misses,
        key=lambda r: (r.get("divergence", 0), r.get("valucast_rank") or 0),
    )


def _call_up_row(row: dict, cur_date: str, logged_at: str) -> tuple[dict | None, str | None]:
    """Build a call-up row and classify it against the public-board consensus.

    Returns (row, "hit") when ValuCast had the player above the field, (row, "miss")
    when ValuCast was below the field, or (None, None) when there's no usable consensus
    or the gap sits inside the noise band. The miss path is what makes the board
    two-sided — it's auto-only (never seeded), so it can't be cherry-picked.
    """
    key = _identity_key(row)
    valucast_rank = _clean_int(row.get("rank"))
    if not key or valucast_rank is None:
        return None, None
    public_ranks = _public_source_ranks(_source_ranks(row))
    if len(public_ranks) < MIN_BOARDS:
        return None, None
    consensus = _public_source_consensus(public_ranks)
    if consensus is None:
        return None, None
    divergence = consensus - valucast_rank
    base = {
        "identity_key": key,
        "mlbam_id": str(row.get("mlbam_id")),
        "role": str(row.get("role")).lower(),
        "name": row.get("name"),
        "team": row.get("mlb_team") or row.get("team") or "-",
        "pos": _pos(row),
        "level": row.get("level") or "-",
        "valucast_rank": valucast_rank,
        "consensus_rank": consensus,
        "divergence": divergence,
        "call_up_date": cur_date,
        "logged_at": logged_at,
    }
    if valucast_rank <= MAX_VALUCAST_RANK and divergence >= MIN_DIVERGENCE:
        return base, "hit"
    # Miss: the field had him as a real prospect (consensus within range) and we were
    # meaningfully behind. Same magnitude bar as a hit, sign flipped.
    if consensus <= MAX_VALUCAST_RANK and divergence <= -MIN_DIVERGENCE:
        return base, "miss"
    return None, None


def _receipt_from_row(row: dict, cur_date: str, logged_at: str) -> dict | None:
    base, kind = _call_up_row(row, cur_date, logged_at)
    return base if kind == "hit" else None


def _miss_from_row(row: dict, cur_date: str, logged_at: str) -> dict | None:
    base, kind = _call_up_row(row, cur_date, logged_at)
    return base if kind == "miss" else None


def _detect_call_ups(
    prev_board: dict | list,
    cur_board: dict | list,
    cur_date: str,
    roster_lookup: dict[str, dict],
    existing_rows: list[dict],
    from_row,
    *,
    logged_at: str | None = None,
) -> list[dict]:
    """Merge call-ups (built by ``from_row``) for prospects that disappeared into the roster."""
    logged_at = logged_at or f"{cur_date}T00:00:00+00:00"
    merged = {row["identity_key"]: row for row in existing_rows}
    prev_by_key = {
        key: row
        for row in _rows(prev_board)
        if (key := _identity_key(row)) is not None
    }
    cur_keys = {
        key
        for row in _rows(cur_board)
        if (key := _identity_key(row)) is not None
    }

    for key in sorted(set(prev_by_key) - cur_keys):
        row = prev_by_key[key]
        mlbam_id = row.get("mlbam_id")
        if str(mlbam_id) not in roster_lookup:
            continue
        receipt = from_row(row, cur_date, logged_at)
        if not receipt:
            continue
        existing = merged.get(key)
        if not existing:
            merged[key] = receipt
            continue
        if str(receipt["call_up_date"]) < str(existing.get("call_up_date") or "9999-99-99"):
            receipt["logged_at"] = existing.get("logged_at") or receipt["logged_at"]
            merged[key] = receipt

    return sorted(
        merged.values(),
        key=lambda row: (
            str(row.get("call_up_date") or ""),
            str(row.get("name") or ""),
            str(row.get("identity_key") or ""),
        ),
        reverse=True,
    )


def detect_receipts(
    prev_board: dict | list,
    cur_board: dict | list,
    cur_date: str,
    roster_lookup: dict[str, dict],
    existing_log: dict | list | None,
    *,
    logged_at: str | None = None,
) -> list[dict]:
    """Merge ahead-of-field receipts for prospects that disappeared into the MLB roster."""
    return _detect_call_ups(
        prev_board, cur_board, cur_date, roster_lookup,
        _existing_receipts(existing_log), _receipt_from_row, logged_at=logged_at,
    )


def detect_misses(
    prev_board: dict | list,
    cur_board: dict | list,
    cur_date: str,
    roster_lookup: dict[str, dict],
    existing_log: dict | list | None,
    *,
    logged_at: str | None = None,
) -> list[dict]:
    """Merge call-ups where ValuCast sat BEHIND the field (the accountability side)."""
    return _detect_call_ups(
        prev_board, cur_board, cur_date, roster_lookup,
        _existing_misses(existing_log), _miss_from_row, logged_at=logged_at,
    )


def _archive_payloads(path: Path = RANK_ARCHIVE_DIR) -> list[dict]:
    payloads = []
    if not path.exists():
        return payloads
    for file in sorted(path.glob("*.json")):
        payload = _load_json(file)
        if not payload:
            continue
        payload.setdefault("date", _date_part(payload.get("date") or payload.get("generated_at")) or file.stem)
        payloads.append(payload)
    return payloads


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def archive_call_up_receipts(payload: dict, date_str: str, archive_dir: Path = ARCHIVE_DIR) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    text = json.dumps(payload, indent=2, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def build_call_up_receipts(
    *,
    archive_payloads: list[dict],
    roster_payload: dict,
    existing_log: dict | list | None = None,
    seed_rows: list[dict] | None = None,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    roster_lookup = active_roster_lookup(roster_payload)
    receipts = _existing_receipts(existing_log)
    misses = _existing_misses(existing_log)
    archive_dates = [
        date
        for payload in archive_payloads
        if (date := _date_part(payload.get("date") or payload.get("generated_at")))
    ]
    for prev, cur in zip(archive_payloads, archive_payloads[1:]):
        cur_date = _date_part(cur.get("date") or cur.get("generated_at"))
        if cur_date:
            receipts = detect_receipts(prev, cur, cur_date, roster_lookup, receipts, logged_at=generated_at)
            misses = detect_misses(prev, cur, cur_date, roster_lookup, misses, logged_at=generated_at)

    # Merge curated seeds; auto-detected rows win on identity (they carry a real divergence).
    by_key = {row["identity_key"]: row for row in receipts}
    seed_count = 0
    for srow in (seed_rows or []):
        if srow.get("identity_key") and srow["identity_key"] not in by_key:
            srow = dict(srow)
            srow["logged_at"] = srow.get("logged_at") or generated_at
            srow["seed"] = True
            by_key[srow["identity_key"]] = srow
            seed_count += 1
    receipts = _sort_receipts(list(by_key.values()))
    misses = _sort_misses(misses)

    blockers = []
    if len(archive_payloads) < 2:
        blockers.append("Fewer than two dated Rank v1 archives are available.")
    if not roster_lookup:
        blockers.append("No active MLB roster lookup rows are available.")

    return {
        "artifact": ARTIFACT_NAME,
        "signal_name": SIGNAL_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "status": "blocked" if blockers else "candidate_ready",
        "source_policy": {
            "kind": ARTIFACT_NAME,
            "rank_archives": "valucast_prospect_rank_v1",
            "roster_artifact": "valucast_mlb_roster_status",
            "official_mlb_rosters_used": True,
            "name_matching_used": False,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
        },
        "summary": {
            "receipt_count": len(receipts),
            "miss_count": len(misses),
            "seed_count": seed_count,
            "archive_dates_scanned": archive_dates,
        },
        "validation": {
            "ready_for_call_up_receipts": not blockers,
            "blockers": blockers,
        },
        "receipts": receipts,
        "misses": misses,
    }


def run_call_up_receipts(
    *,
    rank_archive_dir: Path = RANK_ARCHIVE_DIR,
    roster_path: Path = ROSTER_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    payload = build_call_up_receipts(
        archive_payloads=_archive_payloads(rank_archive_dir),
        roster_payload=_load_json(roster_path),
        existing_log=_load_json(artifact_path),
        seed_rows=_seed_receipts(),
    )
    _write_json(payload, artifact_path)
    date_str = _date_part(payload["generated_at"]) or datetime.now(timezone.utc).date().isoformat()
    archive_path, archive_changed = archive_call_up_receipts(payload, date_str, archive_dir)
    return {
        "artifact_path": str(artifact_path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "status": payload["status"],
        "receipt_count": payload["summary"]["receipt_count"],
        "miss_count": payload["summary"]["miss_count"],
        "receipts": payload["receipts"],
        "misses": payload["misses"],
    }
