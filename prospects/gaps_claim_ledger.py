"""Two-sided gaps claim lifecycle ledger (plan 017): every gap claim resolves or expires.

The `/gaps` board and the frozen AOTC scorecard both score ARRIVAL, not OUTCOME,
and the trigger that resolves a call — the player getting called up — is exactly
the event that creates survivorship bias. A bullish over-rank the field never
catches up to and that never gets called up is invisible; the entire fade side is
unaccountable (the artifact itself admits `"fade_scored_by_ledger": False`).

This module converts EVERY row that qualifies on either side of the gap board —
not just the 15 displayed per side — into a dated claim keyed by
`(identity_key, claim_date, side)` that must visibly resolve into one terminal
outcome or expire. It is a PARALLEL, ADDITIVE ledger: it reads the same committed
inputs (the dated `valucast_prospect_rank_v1` archive + the transactions cache)
and reuses the divergence/call-up primitives, but it changes NOTHING in the frozen
scorecard and nothing in how the model scores. Its outcome vocabulary is
DELIBERATELY DISJOINT from the scorecard's `funnel` buckets so the two never get
conflated (this file must never import from the frozen scorecard).

--- Historical roster-status enrollment decision (documented per the plan) -------
`build_consensus_gap_board(payload, roster_status=...)` applies a live-roster belt
on TOP of each board row's own `active_mlb_roster` flag, to exclude called-up
players from a gap claim (a delisted call-up's field rank is an eligibility
artifact, not a disagreement). No dated roster-status archive exists for most of
the window: the row-level `active_mlb_roster` flag rides ON the archived board rows
themselves, but only from 2026-07-04 onward; pre-7/04 snapshots have no row-level
roster signal at all.

DECISION: when re-deriving each historical snapshot's qualified set we pass
`roster_status=None`, i.e. we use ONLY the snapshot's own row-level
`active_mlb_roster` and never inject today's roster into a historical board. This
is the same source of truth `consensus_gap.run` would have had on that date, it is
DETERMINISTIC across rebuilds (the committed archive never changes, so the same
archive in yields the same claims out), and it refuses to rewrite a June board with
a July roster. Its honest effect: on pre-7/04 snapshots a prospect who was actually
in the majors but whose row carried no flag COULD open a claim; that claim then
resolves normally the moment his call-up is detected (`resolved_by_callup`, via the
transactions cache), so the accountability is preserved rather than hidden — the
call-up simply becomes the resolution instead of a pre-filter. Resolution against
the LATEST snapshot uses the same row-level rule.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from prospects.consensus_gap import build_consensus_gap_board
from prospects.ahead_of_consensus import _board_rows, _divergence_row
from prospects.call_up_receipts import (
    LAUNCH_DATE,
    RANK_ARCHIVE_DIR,
    TRANSACTIONS_CACHE_PATH,
    _actual_call_up_dates,
    _archive_payloads,
    _date_part,
    _load_json,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_gaps_claim_ledger.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_gaps_claim_ledger"

ARTIFACT_NAME = "valucast_gaps_claim_ledger"
SIGNAL_NAME = "ValuCast Gaps Claim Ledger"
SIGNAL_VERSION = "0.1.0"

# --- Lifecycle dials (documented like the AOTC guard block) --------------------
EXPIRY_DAYS = 60
# A claim that has neither resolved nor been retracted this many days after its
# claim_date -> expired_unresolved. 60 gives a claim two ~monthly board-refresh
# cycles to resolve (the scorecard's publish horizon is 30 days); it's a product
# dial, not a law.
CONSENSUS_MOVE_FLOOR_SPOTS = 10
# Minimum field-median move (in spots, TOWARD our rank) to count
# resolved_by_consensus_move. This mirrors the frozen scorecard's
# NOISE_FLOOR_SPOTS *value* (10) but is REDECLARED here, never imported: the
# frozen, pre-registered scorecard must not become a runtime dependency of a
# post-freeze accountability surface (see the module docstring). A single spots
# floor is enough for a display-only claim resolver and keeps the taxonomy legible.
MODEL_MOVE_FLOOR_SPOTS = 10
# Minimum OUR-rank move (in spots, TOWARD the field) to count retracted_by_model_move.
SIDES = ("higher", "lower")

TERMINAL_OUTCOMES = frozenset(
    {
        "resolved_by_callup",
        "resolved_by_consensus_move",
        "expired_unresolved",
        "retracted_by_model_move",
    }
)
ALL_OUTCOMES = frozenset(TERMINAL_OUTCOMES | {"open"})

TAXONOMY = {
    "resolved_by_callup": (
        "Player was called up while the gap still held. Higher side: the receipts "
        "event for us. Lower side: the field was right and our fade missed."
    ),
    "resolved_by_consensus_move": (
        "The field median moved TOWARD our rank past the noise floor since claim_date "
        "— they caught up (higher) or faded him too (lower)."
    ),
    "expired_unresolved": (
        f"{EXPIRY_DAYS} days elapsed from claim_date with the gap still open and no "
        "call-up — the claim aged out. Counted and shown, not hidden."
    ),
    "retracted_by_model_move": (
        "OUR rank moved to close the gap before the field did (we backed off on the "
        "higher side, or un-faded him on the lower side)."
    ),
    "open": "None of the above yet, and age < EXPIRY_DAYS.",
}


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _days_between(start: str | None, end: str | None) -> int | None:
    try:
        return (date.fromisoformat(str(end)[:10]) - date.fromisoformat(str(start)[:10])).days
    except (TypeError, ValueError):
        return None


def _divergence_by_date_key(archive_payloads: list[dict]) -> dict[str, dict[str, dict]]:
    """date -> {identity_key: divergence_row} across every walked archive payload.

    Built from `_divergence_row` (the SAME primitive the gap board uses), so a
    claim can look up our rank and the field consensus for an identity on ANY
    archived date — including dates the identity no longer qualifies on the gap
    board (needed to detect a consensus/model move that closed the gap)."""
    out: dict[str, dict[str, dict]] = {}
    for payload in archive_payloads:
        d = _date_part(payload.get("date") or payload.get("generated_at"))
        if not d:
            continue
        by_key: dict[str, dict] = {}
        for board_row in _board_rows(payload):
            if not isinstance(board_row, dict):
                continue
            row = _divergence_row(board_row)
            if row is not None and row.get("identity_key"):
                by_key.setdefault(row["identity_key"], row)
        out[d] = by_key
    return out


def _enroll_claims(archive_payloads: list[dict]) -> dict[tuple[str, str, str], dict]:
    """Open a claim for every qualified (identity_key, side) on the first archive
    snapshot (>= LAUNCH_DATE) it qualifies on. Keyed by (identity_key, claim_date,
    side); claim_date is board-observed and immutable. A player who re-qualifies on
    the same side is handled by the merge (a resolved claim is never resurrected;
    a re-qualify on a later date is a NEW key)."""
    # Track the most recent OPEN (unresolved-in-this-scan) claim per (identity, side)
    # so a player who qualifies on consecutive snapshots keeps ONE claim, dated the
    # first day of the run, rather than minting a fresh claim every day.
    live: dict[tuple[str, str], tuple[str, str]] = {}  # (identity, side) -> (claim_date, ...)
    claims: dict[tuple[str, str, str], dict] = {}
    for payload in archive_payloads:
        d = _date_part(payload.get("date") or payload.get("generated_at"))
        if not d or d < LAUNCH_DATE:
            continue
        # A malformed date would sail past the string-compare launch clamp
        # ("not-a-date" > "2026-...") and mint an unexpirable claim; require
        # real ISO or skip the snapshot.
        try:
            date.fromisoformat(d)
        except ValueError:
            continue
        board = build_consensus_gap_board(payload, roster_status=None)
        qualified: set[tuple[str, str]] = set()
        for side in SIDES:
            for row in board.get(f"{side}_all") or []:
                key = row.get("identity_key")
                if not key:
                    continue
                qualified.add((key, side))
                if (key, side) in live:
                    continue  # already an open run; claim_date stays the run's start
                claim_key = (key, d, side)
                claims[claim_key] = {
                    "identity_key": key,
                    "side": side,
                    "claim_date": d,
                    "name": row.get("name"),
                    "mlbam_id": row.get("mlbam_id"),
                    "role": row.get("role"),
                    "team": row.get("team"),
                    "claim_valucast_rank": row.get("valucast_rank"),
                    "claim_consensus_rank": row.get("consensus_rank"),
                    "claim_divergence": row.get("divergence"),
                    "outcome": "open",
                }
                live[(key, side)] = (d, "open")
        # A (identity, side) that dropped off the qualified set ends its run; if it
        # re-qualifies later it opens a fresh claim on that later date.
        for pair in list(live):
            if pair not in qualified:
                del live[pair]
    return claims


def _resolve_claim(
    claim: dict,
    latest_date: str | None,
    divergence_by_date: dict[str, dict[str, dict]],
    actual_call_up_dates: dict[str, str],
) -> dict:
    """Resolve one OPEN claim against the latest snapshot + transactions cache, in
    priority order (first match wins, terminal). Returns the claim (mutated copy)."""
    out = dict(claim)
    side = claim.get("side")
    claim_date = claim.get("claim_date")
    mlbam_id = str(claim.get("mlbam_id") or "")

    # 1. resolved_by_callup: a genuine call-up on/after claim_date, not pre-launch.
    call_up = actual_call_up_dates.get(mlbam_id)
    if call_up and call_up >= claim_date and call_up >= LAUNCH_DATE:
        out["outcome"] = "resolved_by_callup"
        out["resolved_date"] = call_up
        out["lead_time_days"] = _days_between(claim_date, call_up)
        return out

    then_row = (divergence_by_date.get(claim_date) or {}).get(claim["identity_key"])
    latest_row = (divergence_by_date.get(latest_date) or {}).get(claim["identity_key"])
    valucast_then = (then_row or {}).get("valucast_rank")
    valucast_now = (latest_row or {}).get("valucast_rank")
    consensus_then = (then_row or {}).get("consensus_rank")
    consensus_now = (latest_row or {}).get("consensus_rank")

    # 2. retracted_by_model_move: OUR rank moved to CLOSE the gap by >= floor.
    #    higher: our rank rose (number got bigger, toward the field's larger number);
    #    lower:  our rank fell (number got smaller, toward the field's smaller number).
    if valucast_then is not None and valucast_now is not None:
        model_move = valucast_now - valucast_then  # + = we moved down the board (bigger #)
        if side == "higher" and model_move >= MODEL_MOVE_FLOOR_SPOTS:
            out["outcome"] = "retracted_by_model_move"
            out["resolved_date"] = latest_date
            out["model_move_spots"] = model_move
            return out
        if side == "lower" and -model_move >= MODEL_MOVE_FLOOR_SPOTS:
            out["outcome"] = "retracted_by_model_move"
            out["resolved_date"] = latest_date
            out["model_move_spots"] = model_move
            return out

    # 3. resolved_by_consensus_move: the field median moved TOWARD our rank by >= floor.
    #    higher: consensus_now < consensus_then (field pulled him up toward us);
    #    lower:  consensus_now > consensus_then (field faded him down toward us).
    if consensus_then is not None and consensus_now is not None:
        field_move = consensus_now - consensus_then  # - = field moved him up the board
        if side == "higher" and -field_move >= CONSENSUS_MOVE_FLOOR_SPOTS:
            out["outcome"] = "resolved_by_consensus_move"
            out["resolved_date"] = latest_date
            out["consensus_move_spots"] = field_move
            return out
        if side == "lower" and field_move >= CONSENSUS_MOVE_FLOOR_SPOTS:
            out["outcome"] = "resolved_by_consensus_move"
            out["resolved_date"] = latest_date
            out["consensus_move_spots"] = field_move
            return out

    # 4. expired_unresolved: EXPIRY_DAYS elapsed with no resolution.
    age = _days_between(claim_date, latest_date)
    if age is not None and age >= EXPIRY_DAYS:
        out["outcome"] = "expired_unresolved"
        out["resolved_date"] = latest_date
        out["age_days"] = age
        return out

    # 5. still open.
    out["outcome"] = "open"
    out.pop("resolved_date", None)
    out.pop("lead_time_days", None)
    return out


def _existing_claims(existing_log: dict | list | None) -> list[dict]:
    if isinstance(existing_log, dict):
        rows = existing_log.get("claims") or []
    else:
        rows = existing_log or []
    return [dict(r) for r in rows if isinstance(r, dict) and r.get("identity_key")]


def _claim_key(row: dict) -> tuple[str, str, str] | None:
    key = row.get("identity_key")
    claim_date = row.get("claim_date")
    side = row.get("side")
    if not key or not claim_date or side not in SIDES:
        return None
    return (key, claim_date, side)


def _summarize(claims: list[dict]) -> dict:
    summary: dict = {"expiry_days": EXPIRY_DAYS}
    for side in SIDES:
        rows = [c for c in claims if c.get("side") == side]
        counts = {outcome: 0 for outcome in ("open", *sorted(TERMINAL_OUTCOMES))}
        for c in rows:
            counts[c.get("outcome", "open")] = counts.get(c.get("outcome", "open"), 0) + 1
        counts["total"] = len(rows)
        summary[side] = counts
    return summary


def _sort_key(row: dict) -> tuple:
    return (
        str(row.get("side") or ""),
        str(row.get("claim_date") or ""),
        str(row.get("identity_key") or ""),
    )


def build_gaps_claim_ledger(
    *,
    archive_payloads: list[dict],
    transactions_cache: dict | None = None,
    existing_log: dict | list | None = None,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    transactions_cache = transactions_cache or {}
    actual_call_up_dates = _actual_call_up_dates(transactions_cache)
    divergence_by_date = _divergence_by_date_key(archive_payloads)
    dates = sorted(d for d in divergence_by_date if d >= LAUNCH_DATE)
    latest_date = dates[-1] if dates else None

    # Enrollment: every qualified claim across every post-launch snapshot.
    enrolled = _enroll_claims(archive_payloads)

    # Merge: terminal outcomes on the committed artifact are IMMUTABLE (append-only
    # history). Re-resolve only OPEN existing claims + newly enrolled ones.
    merged: dict[tuple[str, str, str], dict] = {}
    for row in _existing_claims(existing_log):
        key = _claim_key(row)
        if key is None:
            continue
        if row.get("outcome") in TERMINAL_OUTCOMES:
            merged[key] = row  # verbatim — never recomputed or rewritten
        # open existing claims fall through to re-resolution below via `enrolled`

    for key, claim in enrolled.items():
        if key in merged:
            continue  # a terminal committed claim wins; never resurrect it
        resolved = _resolve_claim(claim, latest_date, divergence_by_date, actual_call_up_dates)
        # Invariant: re-scanning must never move an OPEN claim's claim_date.
        assert resolved["claim_date"] == claim["claim_date"], "claim_date is immutable"
        merged[key] = resolved

    claims = sorted(merged.values(), key=_sort_key)

    blockers: list[str] = []
    if len(archive_payloads) < 2:
        blockers.append("Fewer than 2 dated rank archives — cannot build a claim lifecycle.")
    if not transactions_cache:
        blockers.append(
            "No transactions cache — call-up resolution is unavailable "
            "(claims still enroll and resolve by consensus/model move/expiry)."
        )
    # status is "blocked" only when the ledger cannot be built at all (no archives).
    status = "blocked" if len(archive_payloads) < 2 else "candidate_ready"

    return {
        "artifact": ARTIFACT_NAME,
        "signal_name": SIGNAL_NAME,
        "signal_version": SIGNAL_VERSION,
        "generated_at": generated_at,
        "generated_by": "valucast",
        "status": status,
        "source_policy": {
            "kind": "valucast_gaps_claim_ledger",
            "inputs": "valucast_prospect_rank_v1_dated_archive + transactions_cache",
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_buy_score": False,
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used": False,
            "market_values_used": False,
            "scored_by_frozen_aotc_scorecard": False,
        },
        "taxonomy": dict(TAXONOMY),
        "dials": {
            "expiry_days": EXPIRY_DAYS,
            "consensus_move_floor_spots": CONSENSUS_MOVE_FLOOR_SPOTS,
            "model_move_floor_spots": MODEL_MOVE_FLOOR_SPOTS,
            "launch_date": LAUNCH_DATE,
        },
        "summary": _summarize(claims),
        "validation": {"ready": not blockers, "blockers": blockers},
        "claims": claims,
    }


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def archive_gaps_claim_ledger(
    payload: dict, date_str: str, archive_dir: Path = ARCHIVE_DIR
) -> tuple[Path, bool]:
    """Dated append-only archive, mirroring archive_call_up_receipts: skip-if-identical,
    atomic tmp + os.replace, indent=2 sort_keys. Writes to the GAPS archive dir, never
    the receipts one."""
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    text = json.dumps(payload, indent=2, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def run(
    *,
    rank_archive_dir: Path = RANK_ARCHIVE_DIR,
    transactions_cache_path: Path = TRANSACTIONS_CACHE_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
) -> dict:
    archive_payloads = _archive_payloads(rank_archive_dir)
    transactions_cache = _load_json(transactions_cache_path)
    existing_log = _load_json(artifact_path)
    payload = build_gaps_claim_ledger(
        archive_payloads=archive_payloads,
        transactions_cache=transactions_cache,
        existing_log=existing_log,
    )
    _write_json(payload, artifact_path)
    _, archived = archive_gaps_claim_ledger(
        payload, payload["generated_at"][:10], archive_dir
    )
    summary = payload["summary"]

    def _tally(outcome: str) -> int:
        return sum(summary[s].get(outcome, 0) for s in SIDES)

    return {
        "artifact_path": str(artifact_path),
        "status": payload["status"],
        "archived": archived,
        "higher_total": summary["higher"]["total"],
        "lower_total": summary["lower"]["total"],
        "open": _tally("open"),
        "resolved_by_callup": _tally("resolved_by_callup"),
        "resolved_by_consensus_move": _tally("resolved_by_consensus_move"),
        "retracted_by_model_move": _tally("retracted_by_model_move"),
        "expired_unresolved": _tally("expired_unresolved"),
    }
