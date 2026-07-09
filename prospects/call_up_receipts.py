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

# Call-ups to permanently drop from the board, by identity_key. The auto-scan re-reads
# every dated rank archive each build, so a one-time delete from the artifact comes back —
# the exclusion has to live in code. Kevin Alcántara (682634_hitter) reached MLB in late
# May 2026, before ValuCast existed; his June AAA->MLB recall isn't an ahead-of-the-field
# receipt (the field already had him as a big-leaguer), so it doesn't count.
# Noah Schultz (702273_pitcher): real call-up was 2026-04-14 ("CWS selected the contract
# of LHP Noah Schultz from Charlotte Knights" -- MLB transactions cache). He landed on
# the board today only because he was activated 2026-07-01 off a rehab assignment/IL
# stint, which the archive-diff detector reads as a fresh disappearance-into-the-roster
# event. Not a real receipt or miss -- he'd already been up for 2.5 months.
EXCLUDED_IDENTITY_KEYS = {"682634_hitter", "702273_pitcher"}

# Real MLB Stats API transaction types that represent a player being added to the MLB
# roster FROM the minors (a genuine call-up) -- as opposed to injury-list moves, options,
# rehab assignments, trades, etc., which can make a player disappear from / reappear on
# the ranked board without a fresh call-up actually happening (see Schultz above).
CALL_UP_TRANSACTION_TYPE_CODES = {"SE", "CU", "PUR", "CP"}
TRANSACTIONS_CACHE_PATH = ROOT / "data" / "mlb" / "mlb_availability_transactions_cache.json"

# ValuCast's public board went live 2026-06-16 (Alex, 7/1). A call-up whose real date
# (actual_call_up_date, from the transactions cache) predates this has no "ahead of the
# field" story: the field, and the player's own MLB roster spot, already reflected the
# outcome before ValuCast had a public ranking to compare against -- the same principle
# as EXCLUDED_IDENTITY_KEYS (Alcántara), applied automatically instead of one-by-one
# denylisting. Only excludes when a real date is actually known (no date = no action --
# don't guess). Applied AFTER the shadow-date attachment, so this needs a real
# transactions_cache to do anything; without one, nothing changes (same as today).
LAUNCH_DATE = "2026-06-16"


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


def _actual_call_up_dates(transactions_cache: dict) -> dict[str, str]:
    """Earliest genuine call-up transaction date per mlbam_id, across every cached
    transaction query. Observe-only: does not change call_up_date, sorting, or which
    rows count as receipts/misses -- it's a shadow field so the real date is visible
    next to the archive-diff-inferred one (which can be wrong, e.g. Schultz above)."""
    earliest: dict[str, str] = {}
    for query in (transactions_cache.get("queries") or {}).values():
        if not isinstance(query, dict):
            continue
        for row in query.get("transactions") or []:
            if not isinstance(row, dict) or row.get("typeCode") not in CALL_UP_TRANSACTION_TYPE_CODES:
                continue
            mlbam_id = (row.get("person") or {}).get("id")
            date = _date_part(row.get("effectiveDate") or row.get("date"))
            if mlbam_id in (None, "") or not date:
                continue
            key = str(mlbam_id)
            if key not in earliest or date < earliest[key]:
                earliest[key] = date
    return earliest


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


def _on_mlb_roster(row: dict) -> bool:
    """True when the ranked-board row itself carries the active-MLB-roster flag.

    Since 2026-07-04 the prospect board RETAINS called-up rookies on-board with
    ``active_mlb_roster: True`` (see prospects/ahead_of_consensus.py rookie-retention
    note) instead of dropping them, so a call-up no longer shows up as a disappearance.
    The flag flipping falsy->True is the on-board signal that the promotion happened.
    """
    return row.get("active_mlb_roster") is True


def _call_up_events(
    prev_by_key: dict[str, dict],
    cur_by_key: dict[str, dict],
) -> list[tuple[str, dict, dict]]:
    """(identity_key, source_row, cur_row) pairs that look like a fresh call-up.

    Two shapes, both minted through the same path/guards downstream:
      * disappearance -- on last board, gone from this one (the pre-7/04 signal); the
        source row is the PREV row, since the player is no longer in ``cur``.
      * flip -- on-board in both, ``active_mlb_roster`` newly True this board (the
        7/04+ retention signal); the source row is the CUR row, where the flip is
        first observed, so its date (cur_date) is the defensible committed call-up date.
    Disappearance and flip are mutually exclusive within a pair (a disappearance is not
    in ``cur`` at all), so a player yields at most one event here; cross-pair dedupe by
    identity_key happens in the merge loop below (a player who flips then later
    disappears/reappears keeps his earliest receipt, never gets a second row).
    """
    events: list[tuple[str, dict, dict]] = []
    cur_keys = set(cur_by_key)
    for key in sorted(set(prev_by_key) - cur_keys):
        events.append((key, prev_by_key[key], prev_by_key[key]))
    for key in sorted(prev_by_key.keys() & cur_keys):
        if not _on_mlb_roster(prev_by_key[key]) and _on_mlb_roster(cur_by_key[key]):
            events.append((key, cur_by_key[key], cur_by_key[key]))
    return events


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
    """Merge call-ups (built by ``from_row``) for prospects that disappeared into the
    roster OR whose on-board ``active_mlb_roster`` flag flipped falsy->True."""
    logged_at = logged_at or f"{cur_date}T00:00:00+00:00"
    merged = {row["identity_key"]: row for row in existing_rows}
    prev_by_key = {
        key: row
        for row in _rows(prev_board)
        if (key := _identity_key(row)) is not None
    }
    cur_by_key = {
        key: row
        for row in _rows(cur_board)
        if (key := _identity_key(row)) is not None
    }

    for key, source_row, _cur_row in _call_up_events(prev_by_key, cur_by_key):
        mlbam_id = source_row.get("mlbam_id")
        if str(mlbam_id) not in roster_lookup:
            continue
        receipt = from_row(source_row, cur_date, logged_at)
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
    """Merge ahead-of-field receipts for prospects that reached the MLB roster (either
    by disappearing from the board or by flipping ``active_mlb_roster`` True on-board)."""
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
    transactions_cache: dict | None = None,
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
    receipts = [r for r in _sort_receipts(list(by_key.values())) if r.get("identity_key") not in EXCLUDED_IDENTITY_KEYS]
    misses = [m for m in _sort_misses(misses) if m.get("identity_key") not in EXCLUDED_IDENTITY_KEYS]

    # Attach the real call-up date next to the archive-diff-inferred one, when a genuine
    # call-up transaction exists for that player. Never changes call_up_date or sorting.
    actual_dates = _actual_call_up_dates(transactions_cache) if transactions_cache else {}
    if actual_dates:
        for row in receipts + misses:
            real_date = actual_dates.get(str(row.get("mlbam_id")))
            if real_date:
                row["actual_call_up_date"] = real_date

    # Drop anyone whose REAL call-up predates launch -- see LAUNCH_DATE above. Only acts
    # on a confirmed actual_call_up_date; a row with no real-date match is left alone.
    pre_launch_excluded = [
        row for row in receipts + misses
        if row.get("actual_call_up_date") and row["actual_call_up_date"] < LAUNCH_DATE
    ]
    if pre_launch_excluded:
        dropped_keys = {row["identity_key"] for row in pre_launch_excluded}
        receipts = [r for r in receipts if r["identity_key"] not in dropped_keys]
        misses = [m for m in misses if m["identity_key"] not in dropped_keys]

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
            "pre_launch_excluded_count": len(pre_launch_excluded),
            "pre_launch_excluded_names": sorted(
                {row.get("name") for row in pre_launch_excluded if row.get("name")}
            ),
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
    transactions_cache_path: Path = TRANSACTIONS_CACHE_PATH,
) -> dict:
    payload = build_call_up_receipts(
        archive_payloads=_archive_payloads(rank_archive_dir),
        roster_payload=_load_json(roster_path),
        existing_log=_load_json(artifact_path),
        seed_rows=_seed_receipts(),
        transactions_cache=_load_json(transactions_cache_path),
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
