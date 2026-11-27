"""Permanent receipts for ValuCast ahead-of-consensus prospect call-ups."""
from __future__ import annotations

import json
import math
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
ACTUALS_SNAPSHOT_DIR = ROOT / "data" / "prediction_archive" / "valucast_actuals_snapshot"
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
# Transactions that send a player back DOWN to the minors. When one of these lands on the
# same date as a "call-up" (e.g. SE selected), the selection was 40-man roster paperwork,
# not a genuine promotion -- the player never joins the active MLB roster (see Pratt in
# _actual_call_up_dates). "OPT" (Optioned) and "OUT" (Outrighted) are both unambiguously
# minors-directed per the cache descriptions; "ASG" (Assigned) is direction-ambiguous and
# never co-occurs same-day with a call-up in the cache, so it's deliberately left out.
TO_MINORS_TRANSACTION_TYPE_CODES = {"OPT", "OUT"}
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

# Field-unranked auto lane: mint a receipt for the strongest calls the divergence
# gate CAN'T score -- a post-launch call-up we ranked highly that the public field
# had NO real read on (fewer than MIN_BOARDS public boards inside the 600 cap at
# promotion). Replaces hand-seeding these. STRICT rank cap (25, not MAX_VALUCAST_RANK
# 300): only the most-differentiated calls earn an auto row; Kuroda-Grauer(#41)/
# Cauley(#61)/Watson(#80) stay legacy seeds by design. Pre-registered; frozen.
FIELD_UNRANKED_MAX_VALUCAST_RANK = 25

# --- Maturation layer (plan 016): PRE-REGISTERED, FROZEN 2026-07-14 ------------
# A receipt scores ARRIVAL; maturation scores OUTCOME. Every receipt opens PENDING
# and resolves CONFIRMED (the player stuck and produced real MLB workload) or
# DECAYED (a cup of coffee) at a pre-registered horizon, from ValuCast's own
# archived actuals snapshots. Do NOT tune these after seeing resolutions -- that
# destroys the accountability the layer exists for (bump SIGNAL_VERSION and
# freeze NEW values instead, keeping the old on record, same as AOTC v1 -> v2).
MATURATION_HORIZON_DAYS = 60   # first look: eligible to resolve
MATURATION_FINAL_DAYS = 90     # terminal look: resolve on the counting bar alone
CONFIRM_HITTER_GAMES = 20      # "he stuck and actually played" floors -- roughly a
CONFIRM_HITTER_PA = 60         # month of everyday reps for a hitter...
CONFIRM_PITCHER_GAMES = 12     # ...or a starter's ~4 turns / a reliever's regular
CONFIRM_PITCHER_IP = 20.0      # usage; above cup-of-coffee, below "must be a star"


def _mlb_workload(snapshot_dir: Path = ACTUALS_SNAPSHOT_DIR) -> dict[str, dict]:
    """{mlbam_id: {"games", "pa", "ip", "as_of"}} -- cumulative season MLB workload
    per player, read from the archived actuals snapshots. Stats are already
    season-cumulative, so the MAX over the archive is the peak observed. A pitcher
    can appear under a hitter row (empty batting line) AND a reliever/starter row;
    take the max across ALL rows for the id so his real IP/G isn't read as zero
    off his batting line (live proof case: Owen Murphy 702566)."""
    workload: dict[str, dict] = {}
    try:
        files = sorted(snapshot_dir.glob("*.json"))
    except OSError:
        return {}
    for path in files:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- fail-soft, same as _archive_payloads
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata") or {}
            mid = str(metadata.get("mlbam_id") or "")
            if not mid:
                continue
            stats = row.get("stats") or {}
            try:
                games = int(stats.get("G") or 0)
            except (TypeError, ValueError):
                games = 0
            try:
                pa = int(stats.get("PA") or 0)
            except (TypeError, ValueError):
                pa = 0
            try:
                ip = float(stats.get("IP") or 0.0)
            except (TypeError, ValueError):
                ip = 0.0
            entry = workload.setdefault(
                mid, {"games": 0, "pa": 0, "ip": 0.0, "as_of": ""}
            )
            entry["games"] = max(entry["games"], games)
            entry["pa"] = max(entry["pa"], pa)
            entry["ip"] = max(entry["ip"], ip)
            as_of = str(metadata.get("as_of") or "")
            if as_of > entry["as_of"]:
                entry["as_of"] = as_of
    return workload


def _maturation_age_days(anchor: str | None, today: str | None) -> int | None:
    """Days between two YYYY-MM-DD strings; None when either is unparseable."""
    try:
        start = datetime.fromisoformat(str(anchor)[:10]).date()
        end = datetime.fromisoformat(str(today)[:10]).date()
    except (TypeError, ValueError):
        return None
    return (end - start).days


def _maturation_status(
    row: dict,
    workload: dict[str, dict],
    roster_lookup: dict,
    today: str,
    *,
    prior_status: str | None = None,
) -> str:
    """Resolve a receipt row to PENDING / CONFIRMED / DECAYED (plan 016 rules)."""
    # Rule 1 -- APPEND-ONLY FLOOR: a CONFIRMED row NEVER reverts. The receipt
    # claimed ValuCast saw an MLB-caliber player early; once he demonstrably
    # played at MLB level, the claim is settled regardless of what his career
    # does afterward (a later demotion is career noise, not a receipt reversal).
    if prior_status == "CONFIRMED":
        return "CONFIRMED"
    anchor = row.get("actual_call_up_date") or row.get("call_up_date")
    age = _maturation_age_days(anchor, today)
    if age is None:
        return "PENDING"  # unparseable anchor: don't guess
    if age < MATURATION_HORIZON_DAYS:
        return "PENDING"
    w = workload.get(str(row.get("mlbam_id"))) or {}
    games = w.get("games") or 0
    if row.get("role") == "pitcher":
        confirmed_bar = games >= CONFIRM_PITCHER_GAMES or (w.get("ip") or 0.0) >= CONFIRM_PITCHER_IP
    else:
        confirmed_bar = games >= CONFIRM_HITTER_GAMES or (w.get("pa") or 0) >= CONFIRM_HITTER_PA
    if confirmed_bar:
        return "CONFIRMED"
    if age >= MATURATION_FINAL_DAYS:
        return "DECAYED"  # 90d elapsed, bar never cleared -- terminal
    if str(row.get("mlbam_id")) in roster_lookup:
        return "PENDING"  # up and playing, slow accumulator, not yet 90d
    return "DECAYED"  # off roster, under bar, past 60d: the cup of coffee ended


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


def _to_minors_dates(transactions_cache: dict) -> set[tuple[str, str]]:
    """(mlbam_id, date) pairs where the player was sent DOWN to the minors that day
    (optioned/outrighted). Used to disqualify same-date "call-up" transactions that are
    really 40-man roster paperwork -- see _actual_call_up_dates."""
    pairs: set[tuple[str, str]] = set()
    for query in (transactions_cache.get("queries") or {}).values():
        if not isinstance(query, dict):
            continue
        for row in query.get("transactions") or []:
            if not isinstance(row, dict) or row.get("typeCode") not in TO_MINORS_TRANSACTION_TYPE_CODES:
                continue
            mlbam_id = (row.get("person") or {}).get("id")
            date = _date_part(row.get("effectiveDate") or row.get("date"))
            if mlbam_id in (None, "") or not date:
                continue
            pairs.add((str(mlbam_id), date))
    return pairs


def _actual_call_up_dates(transactions_cache: dict) -> dict[str, str]:
    """Earliest genuine call-up transaction date per mlbam_id, across every cached
    transaction query. Observe-only: does not change call_up_date, sorting, or which
    rows count as receipts/misses -- it's a shadow field so the real date is visible
    next to the archive-diff-inferred one (which can be wrong, e.g. Schultz above).

    A call-up-typed transaction (SE/CU/PUR/CP) is IGNORED when the same player has a
    same-date option/outright back to the minors. That pairing is 40-man roster
    paperwork -- a contract SELECTION plus a SAME-DAY option to keep a Rule-5-protected
    guy on the 40-man without ever putting him on the active MLB roster -- not a genuine
    promotion. Proven case: Cooper Pratt (mlbam 806198), 2026-04-03 "selected the
    contract" + SAME DAY "optioned to Nashville Sounds"; his real first call-up was the
    2026-06-16 "recalled" (first MLB game 6/16). Without this guard the 4/03 pair dated
    him pre-launch and the LAUNCH_DATE guard wrongly dropped him. (Luis Lara, mlbam
    800325, is the same shape: 6/09 SE+OPT paperwork, real recall 7/07.) A GENUINE
    selection with no same-day option still counts -- e.g. Noah Schultz's 2026-04-14 SE."""
    to_minors = _to_minors_dates(transactions_cache)
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
            if (key, date) in to_minors:
                continue
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
    # Only SCORED receipts belong to the receipts lane. Field-unranked auto rows are
    # persisted inside ``receipts`` too (they render on that side) but are owned by the
    # field-unranked lane (_existing_field_unranked); excluding them here keeps a
    # committed field-unranked row from being carried by BOTH lanes on the next build
    # (which would duplicate the identity and trip the pre-merge uniqueness assert).
    if isinstance(existing_log, dict):
        rows = existing_log.get("receipts") or []
    else:
        rows = existing_log or []
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("identity_key") and not row.get("field_unranked")
    ]


def _existing_field_unranked(existing_log: dict | list | None) -> list[dict]:
    """Committed field-unranked auto rows, read from the SAME place they're written:
    ``field_unranked``-marked rows inside the persisted ``receipts`` list. (No separate
    top-level key -- the marker rides on the row, so a committed field-unranked row
    round-trips through ``receipts`` on the incremental merge. Reader and writer MUST
    agree on this location; see the idempotency test.)"""
    if isinstance(existing_log, dict):
        rows = existing_log.get("receipts") or []
    else:
        rows = existing_log or []
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("identity_key") and row.get("field_unranked")
    ]


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


def _latest_source_row(
    key: str, archive_by_date_key: dict[str, dict[str, dict]]
) -> dict | None:
    """The most recent walked archive row for a seed identity (or None if unranked).

    Curated seed rows carry no ``source_ranks`` of their own, so their honest
    field label has to come from the same ranked-board archive the builder already
    loaded. Newest board wins -- it's the current read of what the field says."""
    dates = [d for d in archive_by_date_key if key in archive_by_date_key[d]]
    if not dates:
        return None
    return archive_by_date_key[max(dates)].get(key)


def _field_label_from_source_row(source_row: dict | None) -> str | None:
    """The anonymous ``field_label`` for a call-up, derived from ONE ranked-board row's
    public-board coverage inside the cap:
      * 0 boards inside the cap -> "no public board inside 600" (truly field-unranked).
      * exactly 1 board at rank r -> "1 board, ~#r".
      * >= 2 boards -> a consensus exists; report it ("N boards, consensus ~#c").
    Returns None when there's no source row at all (keep whatever label the caller has).
    Single source of the three-way phrasing shared by seeds and no-claim rows; never
    names a board (ToS)."""
    if source_row is None:
        return None
    public_ranks = _public_source_ranks(_source_ranks(source_row))
    if not public_ranks:
        return "no public board inside 600"
    if len(public_ranks) == 1:
        rank = round(next(iter(public_ranks.values())))
        return f"1 board, ~#{rank}"
    consensus = _public_source_consensus(public_ranks)
    return f"{len(public_ranks)} boards, consensus ~#{consensus}"


def _derive_seed_field_label(
    key: str, archive_by_date_key: dict[str, dict[str, dict]]
) -> str | None:
    """Honest ``field_label`` for a curated seed, derived from the ranked-board archive.

    A seed exists because the divergence gate can't SCORE it (< MIN_BOARDS boards,
    so no consensus), but the boards may still RANK the player deep -- and a typed
    "field outside top 100" then contradicts the archive (Gabriel Hughes: STS ~#512).
    Derive the label from the public boards inside the cap the model already trusts
    (newest board wins). Returns None when the identity has no archive row at all
    (keep the typed label)."""
    return _field_label_from_source_row(_latest_source_row(key, archive_by_date_key))


def _apply_seed_field_labels(
    rows: list[dict], archive_by_date_key: dict[str, dict[str, dict]]
) -> None:
    """Overwrite each SEED row's ``field_label`` with the archive-derived one, in place.

    Label-only: never touches divergence, rank, consensus, or which rows are seeds.
    Runs over the FINAL receipts list so it also corrects seed rows carried forward
    from the committed artifact (the incremental merge keeps existing rows, so a
    stale typed label would otherwise survive forever). No-op when the archive has
    no row for the identity (typed label stands)."""
    for row in rows:
        if not row.get("seed"):
            continue
        key = row.get("identity_key")
        if not key:
            continue
        derived = _derive_seed_field_label(key, archive_by_date_key)
        if derived:
            row["field_label"] = derived


def _field_unranked_label(public_ranks: dict) -> str:
    """Human line for a field-unranked auto receipt, derived from the at-promotion
    board coverage. 0 boards inside the 600 cap -> 'no public board inside 600';
    exactly 1 -> '1 board, ~#<rank>'. (This lane only fires below MIN_BOARDS, so the
    count is 0 or 1.)"""
    if not public_ranks:
        return "no public board inside 600"
    rank = round(min(public_ranks.values()))
    return f"1 board, ~#{rank}"


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
    # Only SCORED misses belong to the misses lane here. Field-unranked-behind auto rows
    # are persisted inside ``misses`` too (they render on that side) but are owned by the
    # mirror lane (_existing_field_unranked_behind); excluding them keeps a committed
    # behind row from being carried by BOTH lanes on the next build (which would duplicate
    # the identity and trip the pre-merge uniqueness assert) -- exactly like 019 does on
    # the receipts side with _existing_receipts / _existing_field_unranked.
    if isinstance(existing_log, dict):
        rows = existing_log.get("misses") or []
    else:
        rows = existing_log or []
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("identity_key") and not row.get("field_unranked_behind")
    ]


def _existing_field_unranked_behind(existing_log: dict | list | None) -> list[dict]:
    """Committed field-unranked-behind auto rows, read from the SAME place they're written:
    ``field_unranked_behind``-marked rows inside the persisted ``misses`` list. Mirror of
    _existing_field_unranked on the receipts side -- the marker rides on the row, so a
    committed behind row round-trips through ``misses`` on the incremental merge."""
    if isinstance(existing_log, dict):
        rows = existing_log.get("misses") or []
    else:
        rows = existing_log or []
    return [
        dict(row)
        for row in rows
        if isinstance(row, dict) and row.get("identity_key") and row.get("field_unranked_behind")
    ]


def _sort_misses(misses: list[dict]) -> list[dict]:
    """Biggest scored miss first: most-negative divergence (field furthest ahead of us).
    Field-unranked-behind rows carry divergence=None (no consensus to diff); they follow the
    scored misses, newest-first, mirroring how _sort_receipts trails the no-divergence rows."""
    scored = sorted(
        (r for r in misses if isinstance(r.get("divergence"), int)),
        key=lambda r: (r["divergence"], r.get("valucast_rank") or 0),
    )
    unscored = sorted(
        (r for r in misses if not isinstance(r.get("divergence"), int)),
        key=lambda r: (str(r.get("call_up_date") or ""), str(r.get("name") or "")),
        reverse=True,
    )
    return scored + unscored


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


def _field_unranked_from_row(row: dict, cur_date: str, logged_at: str) -> dict | None:
    """Mint a field-unranked receipt: a call-up we ranked <= FIELD_UNRANKED_MAX_VALUCAST_RANK
    at promotion that the public field had < MIN_BOARDS boards inside the 600 cap on.
    consensus_rank/divergence are None (there's no field consensus to diff) -- the card
    renders the derived field_label + an AHEAD chip via the existing no-divergence path.

    This classifier and _receipt_from_row are mutually exclusive on the same row: this
    lane requires < MIN_BOARDS public boards, the scored lane requires >= MIN_BOARDS, so
    wiring both against the same event can never double-mint a player as a scored hit AND
    a field-unranked row.
    """
    key = _identity_key(row)
    valucast_rank = _clean_int(row.get("rank"))
    if not key or valucast_rank is None:
        return None
    public_ranks = _public_source_ranks(_source_ranks(row))
    # Only the bucket the scored classifier CAN'T handle: sub-MIN_BOARDS coverage.
    if len(public_ranks) >= MIN_BOARDS:
        return None
    if valucast_rank > FIELD_UNRANKED_MAX_VALUCAST_RANK:
        return None
    return {
        "identity_key": key,
        "mlbam_id": str(row.get("mlbam_id")),
        "role": str(row.get("role")).lower(),
        "name": row.get("name"),
        "team": row.get("mlb_team") or row.get("team") or "-",
        "pos": _pos(row),
        "level": row.get("level") or "-",
        "valucast_rank": valucast_rank,
        "consensus_rank": None,
        "divergence": None,
        "field_label": _field_unranked_label(public_ranks),
        "call_up_date": cur_date,
        "logged_at": logged_at,
        "field_unranked": True,
    }


def _field_unranked_behind_from_row(row: dict, cur_date: str, logged_at: str) -> dict | None:
    """Mirror of _field_unranked_from_row on the BEHIND side: a call-up a SINGLE public
    board rated top-25 while ValuCast sat far below it. The divergence gate can't score it
    (only 1 board -> no MIN_BOARDS consensus), so it would otherwise vanish into no-claims --
    but its ahead-side twin (a vc-top-25 call the field ignored) mints an unscored AHEAD and
    counts in "N ahead", so the guard has to be symmetric: this mints an unscored BEHIND that
    counts in "N behind".

    Fires when the call-up has EXACTLY 1 public board inside the cap, that board's rank
    <= FIELD_UNRANKED_MAX_VALUCAST_RANK (25, the same strict constant the ahead lane uses),
    and (our_rank - board_rank) >= MIN_DIVERGENCE (25). consensus_rank/divergence are None
    (no MIN_BOARDS consensus to diff), field_label comes from the same anonymous derivation,
    and valucast_rank is our at-promotion rank. The row is marked ``field_unranked_behind``
    and lives on the MISSES side.

    Mutually exclusive with the scored lane on the same at-promotion row: the scored miss
    needs >= MIN_BOARDS public boards, this needs exactly 1, so a single event can never
    double-mint a player as a scored miss AND a field-unranked-behind row.
    """
    key = _identity_key(row)
    valucast_rank = _clean_int(row.get("rank"))
    if not key or valucast_rank is None:
        return None
    public_ranks = _public_source_ranks(_source_ranks(row))
    # Exactly one public board: below MIN_BOARDS (so unscorable), but a real read (so the
    # field genuinely called him top-25 -- not "no read", which is the ahead-side lane).
    if len(public_ranks) != 1:
        return None
    board_rank = round(next(iter(public_ranks.values())))
    if board_rank > FIELD_UNRANKED_MAX_VALUCAST_RANK:
        return None
    if valucast_rank - board_rank < MIN_DIVERGENCE:
        return None
    return {
        "identity_key": key,
        "mlbam_id": str(row.get("mlbam_id")),
        "role": str(row.get("role")).lower(),
        "name": row.get("name"),
        "team": row.get("mlb_team") or row.get("team") or "-",
        "pos": _pos(row),
        "level": row.get("level") or "-",
        "valucast_rank": valucast_rank,
        "consensus_rank": None,
        "divergence": None,
        "field_label": _field_unranked_label(public_ranks),
        "call_up_date": cur_date,
        "logged_at": logged_at,
        "field_unranked_behind": True,
    }


def _on_mlb_roster(row: dict) -> bool:
    """True when the ranked-board row itself carries the active-MLB-roster flag.

    Since 2026-07-04 the prospect board RETAINS called-up rookies on-board with
    ``active_mlb_roster: True`` (see prospects/ahead_of_consensus.py rookie-retention
    note) instead of dropping them, so a call-up no longer shows up as a disappearance.
    The flag flipping falsy->True is the on-board signal that the promotion happened.
    """
    return row.get("active_mlb_roster") is True


def _archive_by_date_key(archive_payloads: list[dict]) -> dict[str, dict[str, dict]]:
    """date -> {identity_key: rank_row} across every walked archive payload.

    Built once from the payloads the builder already loaded (no per-event file reads)
    so a lagged call-up event can re-source its rank/consensus row from the archive that
    actually covers the real promotion date -- see ``_at_promotion_source_row``."""
    out: dict[str, dict[str, dict]] = {}
    for payload in archive_payloads:
        date = _date_part(payload.get("date") or payload.get("generated_at"))
        if not date:
            continue
        by_key = out.setdefault(date, {})
        for row in _rows(payload):
            key = _identity_key(row)
            if key is not None:
                by_key.setdefault(key, row)
    return out


def _flagged_days_early(
    identity_key: str | None,
    claimed_rank: int | None,
    anchor_date: str | None,
    archive_by_date_key: dict[str, dict[str, dict]],
) -> int | None:
    """Consecutive archive days of foresight before a call-up (see the plan's
    definition block). Walking back from the latest archive date strictly before
    ``anchor_date``, count each day the player's archive ``rank`` sits inside the
    claimed band (rank <= ceil(claimed_rank * 1.25)); stop at the first out-of-band
    day or the first day with no row. Returns the run length, or ``None`` when the
    archives can't support the claim (no anchor, no earlier archive, or a zero-length
    run). Never returns 0 -- absence means unprovable, presence means >=1 proven day.
    Monotone: a continuous run only, so a distant in-band day across an out-of-band
    gap can't inflate it."""
    if claimed_rank is None or not anchor_date:
        return None
    band = math.ceil(claimed_rank * 1.25)
    earlier = sorted((d for d in archive_by_date_key if d < anchor_date), reverse=True)
    run = 0
    for date in earlier:
        arc_row = archive_by_date_key[date].get(identity_key)
        rank = _clean_int(arc_row.get("rank")) if isinstance(arc_row, dict) else None
        if rank is None or rank > band:
            break
        run += 1
    return run or None


def _at_promotion_source_row(
    key: str,
    source_row: dict,
    source_row_date: str,
    actual_call_up_date: str | None,
    archive_by_date_key: dict[str, dict[str, dict]],
) -> dict | None:
    """The rank row that should score a call-up event, correcting for detection lag.

    A detection event (board disappearance or active_mlb_roster flip) can postdate the
    player's real call-up by days-to-weeks, and the post-call-up board rows are
    contaminated: once a graduate's internal sources drop out, his public rank collapses,
    so a lagged event manufactures a false "field was way ahead" miss (Sean Keys) or a
    false gap. The honest fix -- the "at-promotion standard" -- scores from the archive
    that actually covered the real promotion date.

    When ``actual_call_up_date`` (from the transactions parser) is EARLIER than
    ``source_row_date`` (the date the event's source row came from), re-source from the
    LAST walked archive dated <= the real call-up date. Return that archive's row for the
    player, or ``None`` if he has no row there (an honest no-claim outcome -- Keys/Cabrera
    were even-with / unranked-by the field at their real promotion, so no row is correct).
    When no real date is known, or it isn't earlier than the event, the event-day source
    row stands (current behavior)."""
    if not actual_call_up_date or actual_call_up_date >= source_row_date:
        return source_row
    at_or_before = [d for d in archive_by_date_key if d <= actual_call_up_date]
    if not at_or_before:
        return source_row
    return archive_by_date_key[max(at_or_before)].get(key)


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


def _roster_confirmed(
    mlbam_id: Any,
    roster_lookup: dict[str, dict],
    actual_call_up_date: str | None,
) -> bool:
    """True when the disappearance/flip is corroborated as a real MLB arrival.

    Two independent kinds of evidence, either one is enough:
      (a) the player is on TODAY's active roster snapshot (the original check), OR
      (b) the transactions parser found a genuine in-window call-up (CU/SE-not-negated)
          for him -- a real transaction is direct evidence he reached MLB even if he was
          optioned back down before today's snapshot was taken.
    (b) is what rescues Owen Murphy: real MLB debut 7/06, SE 7/06 + OPT 7/07, so he was
    off the active roster by the time the roster artifact was built, yet the SE
    transaction proves the call-up happened. The guard's original job -- rejecting
    phantom disappearances (IL moves, options, trades, which produce no call-up
    transaction) -- is preserved, because those have neither (a) nor (b)."""
    return str(mlbam_id) in roster_lookup or actual_call_up_date is not None


def _detect_call_ups(
    prev_board: dict | list,
    cur_board: dict | list,
    cur_date: str,
    roster_lookup: dict[str, dict],
    existing_rows: list[dict],
    from_row,
    *,
    logged_at: str | None = None,
    prev_date: str | None = None,
    actual_dates: dict[str, str] | None = None,
    archive_by_date_key: dict[str, dict[str, dict]] | None = None,
    no_claim: dict[str, str] | None = None,
) -> list[dict]:
    """Merge call-ups (built by ``from_row``) for prospects that disappeared into the
    roster OR whose on-board ``active_mlb_roster`` flag flipped falsy->True.

    ``actual_dates`` / ``archive_by_date_key`` enable the at-promotion standard: a lagged
    event is re-scored from the archive covering the real call-up date (see
    ``_at_promotion_source_row``). ``no_claim`` (identity_key -> earliest event cur_date)
    collects genuine post-launch call-ups that produced NO ledger row -- the neither
    bucket, surfaced as a count so an empty misses side is honest, not hollow. All three
    default empty so the historical two-argument call sites keep event-day behavior."""
    logged_at = logged_at or f"{cur_date}T00:00:00+00:00"
    actual_dates = actual_dates or {}
    archive_by_date_key = archive_by_date_key or {}
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
        actual = actual_dates.get(str(mlbam_id))
        if not _roster_confirmed(mlbam_id, roster_lookup, actual):
            continue
        # A flip's source row is the CUR row (dated cur_date); a disappearance's is the
        # PREV row (dated prev_date). The at-promotion re-source keys off that date.
        source_row_date = cur_date if key in cur_by_key else (prev_date or cur_date)
        scored_row = _at_promotion_source_row(
            key, source_row, source_row_date, actual, archive_by_date_key
        )
        # call_up_date keeps its meaning: the board-observation date the event was seen
        # (cur_date). Only the ROW that supplies rank/consensus is re-sourced; the real
        # promotion date already rides along separately as actual_call_up_date.
        receipt = from_row(scored_row, cur_date, logged_at) if scored_row is not None else None
        if not receipt:
            # Genuine post-launch call-up (real transaction) that produced no row: even
            # at promotion (dead-even divergence, no qualifying consensus, or rank over
            # cap). Record it for the neither bucket, earliest event wins.
            if actual is not None and no_claim is not None:
                if key not in no_claim or cur_date < no_claim[key]:
                    no_claim[key] = cur_date
            continue
        existing = merged.get(key)
        if not existing:
            merged[key] = receipt
            continue
        if str(receipt["call_up_date"]) < str(existing.get("call_up_date") or "9999-99-99"):
            receipt["logged_at"] = existing.get("logged_at") or receipt["logged_at"]
            # Carry the resolved status too: the rebuilt receipt has none, and the
            # append-only CONFIRMED floor must survive an earlier-date replacement.
            if existing.get("maturation_status"):
                receipt["maturation_status"] = existing["maturation_status"]
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
    prev_date: str | None = None,
    actual_dates: dict[str, str] | None = None,
    archive_by_date_key: dict[str, dict[str, dict]] | None = None,
    no_claim: dict[str, str] | None = None,
) -> list[dict]:
    """Merge ahead-of-field receipts for prospects that reached the MLB roster (either
    by disappearing from the board or by flipping ``active_mlb_roster`` True on-board)."""
    return _detect_call_ups(
        prev_board, cur_board, cur_date, roster_lookup,
        _existing_receipts(existing_log), _receipt_from_row, logged_at=logged_at,
        prev_date=prev_date, actual_dates=actual_dates,
        archive_by_date_key=archive_by_date_key, no_claim=no_claim,
    )


def detect_misses(
    prev_board: dict | list,
    cur_board: dict | list,
    cur_date: str,
    roster_lookup: dict[str, dict],
    existing_log: dict | list | None,
    *,
    logged_at: str | None = None,
    prev_date: str | None = None,
    actual_dates: dict[str, str] | None = None,
    archive_by_date_key: dict[str, dict[str, dict]] | None = None,
    no_claim: dict[str, str] | None = None,
) -> list[dict]:
    """Merge call-ups where ValuCast sat BEHIND the field (the accountability side)."""
    return _detect_call_ups(
        prev_board, cur_board, cur_date, roster_lookup,
        _existing_misses(existing_log), _miss_from_row, logged_at=logged_at,
        prev_date=prev_date, actual_dates=actual_dates,
        archive_by_date_key=archive_by_date_key, no_claim=no_claim,
    )


def detect_field_unranked(
    prev_board: dict | list,
    cur_board: dict | list,
    cur_date: str,
    roster_lookup: dict[str, dict],
    existing_log: dict | list | None,
    *,
    logged_at: str | None = None,
    prev_date: str | None = None,
    actual_dates: dict[str, str] | None = None,
    archive_by_date_key: dict[str, dict[str, dict]] | None = None,
    no_claim: dict[str, str] | None = None,
) -> list[dict]:
    """Merge field-unranked auto receipts: the strongest calls the divergence gate can't
    score -- a post-launch call-up ranked <= FIELD_UNRANKED_MAX_VALUCAST_RANK at promotion
    that the public field had < MIN_BOARDS boards inside the 600 cap on. Shares the SAME
    event stream / roster guard / at-promotion re-source as receipts/misses; only the
    ``from_row`` classifier differs. ``existing_log`` may be a list of already-committed
    field-unranked rows (from _existing_field_unranked)."""
    existing_rows = (
        existing_log if isinstance(existing_log, list)
        else _existing_field_unranked(existing_log)
    )
    return _detect_call_ups(
        prev_board, cur_board, cur_date, roster_lookup,
        existing_rows, _field_unranked_from_row, logged_at=logged_at,
        prev_date=prev_date, actual_dates=actual_dates,
        archive_by_date_key=archive_by_date_key, no_claim=no_claim,
    )


def detect_field_unranked_behind(
    prev_board: dict | list,
    cur_board: dict | list,
    cur_date: str,
    roster_lookup: dict[str, dict],
    existing_log: dict | list | None,
    *,
    logged_at: str | None = None,
    prev_date: str | None = None,
    actual_dates: dict[str, str] | None = None,
    archive_by_date_key: dict[str, dict[str, dict]] | None = None,
    no_claim: dict[str, str] | None = None,
) -> list[dict]:
    """Merge field-unranked-BEHIND auto rows: the mirror of detect_field_unranked. A
    post-launch call-up a SINGLE public board rated <= FIELD_UNRANKED_MAX_VALUCAST_RANK
    while ValuCast sat >= MIN_DIVERGENCE below it. Shares the SAME event stream / roster
    guard / at-promotion re-source as receipts/misses; only the ``from_row`` classifier
    differs. ``existing_log`` may be a list of already-committed behind rows (from
    _existing_field_unranked_behind)."""
    existing_rows = (
        existing_log if isinstance(existing_log, list)
        else _existing_field_unranked_behind(existing_log)
    )
    return _detect_call_ups(
        prev_board, cur_board, cur_date, roster_lookup,
        existing_rows, _field_unranked_behind_from_row, logged_at=logged_at,
        prev_date=prev_date, actual_dates=actual_dates,
        archive_by_date_key=archive_by_date_key, no_claim=no_claim,
    )


def _revalidate_existing(
    rows: list[dict],
    want_kind: str,
    actual_dates: dict[str, str],
    archive_by_date_key: dict[str, dict[str, dict]],
    no_claim: dict[str, str],
) -> list[dict]:
    """Re-score already-committed AUTO rows under the at-promotion standard, dropping any
    that no longer classify as ``want_kind`` ("hit" for receipts, "miss" for misses).

    Needed because the incremental merge can only add/update -- a stale row booked under
    the old event-window behavior (Keys/Cabrera) would otherwise survive forever. Only
    rows with a known real call-up date are re-sourced (that's the only case the standard
    changes); rows without one, and curated seeds, are left untouched. A dropped genuine
    call-up is recorded in the neither bucket. call_up_date is treated as the event date
    the archive-diff row came from -- the same date the standard compares against."""
    kept: list[dict] = []
    for row in rows:
        key = row.get("identity_key")
        if not key or row.get("seed") or row.get("divergence") is None:
            kept.append(row)
            continue
        actual = actual_dates.get(str(row.get("mlbam_id")))
        event_date = str(row.get("call_up_date") or "")
        # Only re-validate when the real call-up predates the event AND an archive
        # actually covers that real date -- that's the only case the standard re-scores.
        # Without a covering archive we can't compute an at-promotion score, so we keep
        # the committed row rather than reclassify a receipt-shaped row as if it were a
        # rank row. (A rank ROW carries ``rank``/source_ranks; a committed RECEIPT does
        # not, so passing the latter to _call_up_row would spuriously fail.)
        at_or_before = [d for d in archive_by_date_key if d <= actual] if (actual and event_date) else []
        if not actual or not event_date or not at_or_before or actual >= event_date:
            kept.append(row)
            continue
        prom_row = archive_by_date_key[max(at_or_before)].get(key)
        _base, kind = (None, None) if prom_row is None else _call_up_row(prom_row, event_date, "")
        if kind == want_kind:
            kept.append(row)
        elif key not in no_claim or event_date < no_claim[key]:
            no_claim[key] = event_date
    return kept


def _revalidate_field_unranked(
    rows: list[dict],
    actual_dates: dict[str, str],
    archive_by_date_key: dict[str, dict[str, dict]],
    no_claim: dict[str, str],
) -> list[dict]:
    """Re-validate already-committed FIELD-UNRANKED auto rows under the at-promotion
    standard. These have ``divergence is None``, so ``_revalidate_existing`` exempts them
    -- but a later archive can show the field actually DID rank the player (>= MIN_BOARDS
    boards) at his real promotion, which would retroactively mean he never was a
    field-unranked call. Re-source the at-promotion archive row and KEEP the row only if
    it still satisfies ``< MIN_BOARDS`` boards AND ``rank <= FIELD_UNRANKED_MAX_VALUCAST_RANK``;
    otherwise drop it into the neither bucket. Also RE-DERIVE ``field_label`` from the
    at-promotion coverage so a committed row's label can't go stale against its own data
    (the claims-register honesty fix, enforced at revalidation as well as mint). When no
    real date / no covering archive exists, KEEP (can't re-score -> don't guess), matching
    the scored path's conservatism."""
    kept: list[dict] = []
    for row in rows:
        key = row.get("identity_key")
        if not key or not row.get("field_unranked"):
            kept.append(row)
            continue
        actual = actual_dates.get(str(row.get("mlbam_id")))
        event_date = str(row.get("call_up_date") or "")
        at_or_before = [d for d in archive_by_date_key if d <= actual] if (actual and event_date) else []
        if not actual or not event_date or not at_or_before or actual >= event_date:
            kept.append(row)
            continue
        prom_row = archive_by_date_key[max(at_or_before)].get(key)
        prom = None if prom_row is None else _field_unranked_from_row(prom_row, event_date, row.get("logged_at") or "")
        if prom is not None:
            # Re-derive the honest label from the at-promotion coverage; keep everything
            # else on the committed row (identity/date/logged_at) as-is.
            row["field_label"] = prom["field_label"]
            kept.append(row)
        elif key not in no_claim or event_date < no_claim[key]:
            no_claim[key] = event_date
    return kept


def _revalidate_field_unranked_behind(
    rows: list[dict],
    actual_dates: dict[str, str],
    archive_by_date_key: dict[str, dict[str, dict]],
    no_claim: dict[str, str],
) -> list[dict]:
    """Re-validate already-committed FIELD-UNRANKED-BEHIND auto rows under the at-promotion
    standard -- the mirror of _revalidate_field_unranked. These carry ``divergence is None``,
    so _revalidate_existing exempts them, but a later archive can show the field actually
    ranked the player on >= MIN_BOARDS boards at his real promotion (the scored miss lane
    would own him next build), or that the single board no longer clears the top-25 / gap
    bars. Re-source the at-promotion archive row and KEEP the row only if it still satisfies
    the mirror guard (exactly 1 in-cap board <= 25, our_rank - board_rank >= MIN_DIVERGENCE);
    otherwise drop it into the neither bucket. Also RE-DERIVE ``field_label`` from the
    at-promotion coverage so a committed label can't go stale. When no real date / no
    covering archive exists, KEEP (can't re-score -> don't guess)."""
    kept: list[dict] = []
    for row in rows:
        key = row.get("identity_key")
        if not key or not row.get("field_unranked_behind"):
            kept.append(row)
            continue
        actual = actual_dates.get(str(row.get("mlbam_id")))
        event_date = str(row.get("call_up_date") or "")
        at_or_before = [d for d in archive_by_date_key if d <= actual] if (actual and event_date) else []
        if not actual or not event_date or not at_or_before or actual >= event_date:
            kept.append(row)
            continue
        prom_row = archive_by_date_key[max(at_or_before)].get(key)
        prom = None if prom_row is None else _field_unranked_behind_from_row(prom_row, event_date, row.get("logged_at") or "")
        if prom is not None:
            row["field_label"] = prom["field_label"]
            kept.append(row)
        elif key not in no_claim or event_date < no_claim[key]:
            no_claim[key] = event_date
    return kept


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


def _no_claim_near_note(source_row: dict | None, valucast_rank: int | None) -> str | None:
    """Near-scoring nudge for a no-claim row, set ONLY when the at-promotion coverage is
    exactly ONE public board inside the cap (the shape one more board would flip into a
    scored call). With a single board at rank r vs our rank v:
      * r at least MIN_DIVERGENCE better than us (v - r >= 25) -> a second board scores
        him as a MISS (the field was well ahead): "a second board and this scores as a miss".
      * us at least MIN_DIVERGENCE better than the board (r - v >= 25) -> a second board
        scores him as a HIT: "a second board and this scores as a hit".
      * gap inside the noise band, or 0/2+ boards -> no note.
    Never names the board (ToS)."""
    if source_row is None or valucast_rank is None:
        return None
    public_ranks = _public_source_ranks(_source_ranks(source_row))
    if len(public_ranks) != 1:
        return None
    board_rank = round(next(iter(public_ranks.values())))
    if valucast_rank - board_rank >= MIN_DIVERGENCE:
        return "a second board and this scores as a miss"
    if board_rank - valucast_rank >= MIN_DIVERGENCE:
        return "a second board and this scores as a hit"
    return None


def _build_no_claim_rows(
    no_claim_keys: set[str],
    no_claim: dict[str, str],
    actual_dates: dict[str, str],
    archive_by_date_key: dict[str, dict[str, dict]],
) -> list[dict]:
    """Persist the no-claim bucket as disclosable rows -- one per PUBLISHED no-claim
    identity (same set as ``no_claim_keys``; count parity is a hard invariant). For each,
    source the at-promotion row (last walked archive <= the real call-up date when known,
    else the event date) and emit an anonymous, ToS-safe row. An identity with no archive
    row at all is emitted with null fields rather than dropped -- count parity beats field
    completeness. Sorted newest-first by call-up date."""
    rows: list[dict] = []
    for key in no_claim_keys:
        event_date = no_claim.get(key)
        mlbam_id = key.split("_")[0]
        real_date = actual_dates.get(mlbam_id)
        # At-promotion anchor: the real call-up date when it's known and earlier than the
        # detection event, else the event date itself.
        anchor = real_date if (real_date and event_date and real_date < event_date) else event_date
        # Source the LAST archive at/before the anchor that actually RANKS him -- the
        # honest "our rank at promotion". A no-claim is often a DISAPPEARANCE, so on the
        # anchor date itself he's already gone from the board; walking back to his last
        # on-board read is the same at-promotion standard the scored lanes use, just
        # tolerant of the board no longer carrying a graduate. If he was never ranked at
        # or before the anchor (all his reads postdate it), fall back to his earliest
        # archive read so the row still carries a real rank/label rather than nulls.
        dates_with_key = [d for d in archive_by_date_key if key in archive_by_date_key[d]]
        source_row = None
        if dates_with_key:
            at_or_before = [d for d in dates_with_key if not anchor or d <= anchor]
            pick = max(at_or_before) if at_or_before else min(dates_with_key)
            source_row = archive_by_date_key[pick].get(key)
        valucast_rank = _clean_int(source_row.get("rank")) if isinstance(source_row, dict) else None
        public_ranks = _public_source_ranks(_source_ranks(source_row)) if isinstance(source_row, dict) else {}
        row = {
            "name": (source_row.get("name") if isinstance(source_row, dict) else None),
            "identity_key": key,
            "mlbam_id": mlbam_id,
            "team": (source_row.get("mlb_team") or source_row.get("team")) if isinstance(source_row, dict) else None,
            "pos": _pos(source_row) if isinstance(source_row, dict) else None,
            "level": (source_row.get("level") if isinstance(source_row, dict) else None),
            "call_up_date": event_date,
            "valucast_rank": valucast_rank,
            "field_label": _field_label_from_source_row(source_row),
            "board_count": len(public_ranks),
            "near_note": _no_claim_near_note(source_row, valucast_rank),
        }
        if real_date:
            row["actual_call_up_date"] = real_date
        rows.append(row)
    # Sort by the date the PAGE displays (real call-up date when known, else the
    # detection date) so a newest-first list never shows an older date above a newer one.
    rows.sort(
        key=lambda r: (
            str(r.get("actual_call_up_date") or r.get("call_up_date") or ""),
            str(r.get("name") or ""),
        ),
        reverse=True,
    )
    return rows


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
    field_unranked = _existing_field_unranked(existing_log)
    field_unranked_behind = _existing_field_unranked_behind(existing_log)
    archive_dates = [
        date
        for payload in archive_payloads
        if (date := _date_part(payload.get("date") or payload.get("generated_at")))
    ]
    # Real call-up dates + a date->key->row index, both derived from inputs the builder
    # already loaded, drive the at-promotion standard: lagged events re-score from the
    # archive covering the real promotion date, and the roster guard accepts a genuine
    # call-up transaction as MLB-arrival evidence. no_claim collects genuine post-launch
    # call-ups that produced no ledger row (the neither bucket).
    actual_dates = _actual_call_up_dates(transactions_cache) if transactions_cache else {}
    archive_index = _archive_by_date_key(archive_payloads)
    no_claim: dict[str, str] = {}
    for prev, cur in zip(archive_payloads, archive_payloads[1:]):
        cur_date = _date_part(cur.get("date") or cur.get("generated_at"))
        prev_date = _date_part(prev.get("date") or prev.get("generated_at"))
        if cur_date:
            receipts = detect_receipts(
                prev, cur, cur_date, roster_lookup, receipts, logged_at=generated_at,
                prev_date=prev_date, actual_dates=actual_dates,
                archive_by_date_key=archive_index, no_claim=no_claim,
            )
            misses = detect_misses(
                prev, cur, cur_date, roster_lookup, misses, logged_at=generated_at,
                prev_date=prev_date, actual_dates=actual_dates,
                archive_by_date_key=archive_index, no_claim=no_claim,
            )
            # Third lane: auto-mint the field-unranked calls the divergence gate can't
            # score. Shares the same no_claim dict -- a player who fails the strict rank
            # cap still belongs in the neither bucket; one who becomes a field-unranked
            # ROW is removed from no_claim later via claimed_keys (he's folded into
            # receipts before that count is taken).
            field_unranked = detect_field_unranked(
                prev, cur, cur_date, roster_lookup, field_unranked, logged_at=generated_at,
                prev_date=prev_date, actual_dates=actual_dates,
                archive_by_date_key=archive_index, no_claim=no_claim,
            )
            # Fourth lane: the mirror of field_unranked on the BEHIND side -- a single
            # board calling a guy top-25 while we sat far below. Symmetry with the ahead
            # lane: today zero rows qualify (built for the future). Shares the same
            # no_claim dict -- a player who fails the mirror bars stays in the neither
            # bucket; one who becomes a behind ROW is folded into misses before the
            # count is taken (removed from no_claim via claimed_keys).
            field_unranked_behind = detect_field_unranked_behind(
                prev, cur, cur_date, roster_lookup, field_unranked_behind, logged_at=generated_at,
                prev_date=prev_date, actual_dates=actual_dates,
                archive_by_date_key=archive_index, no_claim=no_claim,
            )

    # Re-validate INCREMENTAL rows under the at-promotion standard. The merge above only
    # adds/updates; it can't drop an already-committed row that the corrected standard no
    # longer supports (Sean Keys / Jose Cabrera were booked as misses off a lagged
    # retention-flip, but at their real promotion the field was even-with / hadn't-ranked
    # them -> no honest row). Re-score each existing AUTO row against its at-promotion
    # archive and drop the ones that no longer qualify; a dropped genuine call-up falls
    # through to the neither bucket. Seeds are curated (no divergence) and exempt.
    receipts = _revalidate_existing(receipts, "hit", actual_dates, archive_index, no_claim)
    misses = _revalidate_existing(misses, "miss", actual_dates, archive_index, no_claim)
    # Field-unranked rows carry divergence=None, so _revalidate_existing exempts them; they
    # get their OWN revalidation (still < MIN_BOARDS boards AND rank <= cap at promotion),
    # which also re-derives the honest field_label. A row that no longer qualifies drops to
    # the neither bucket, exactly like a de-qualified scored hit/miss.
    field_unranked = _revalidate_field_unranked(field_unranked, actual_dates, archive_index, no_claim)
    # Field-unranked-BEHIND rows also carry divergence=None; their own revalidation checks
    # the mirror guard still holds at promotion (exactly 1 in-cap board <= 25, our_rank -
    # board_rank >= MIN_DIVERGENCE) and re-derives the label. A de-qualified row (e.g. a
    # second board appeared -> the scored miss lane owns it next build) drops to the neither
    # bucket, exactly like a de-qualified field-unranked hit.
    field_unranked_behind = _revalidate_field_unranked_behind(
        field_unranked_behind, actual_dates, archive_index, no_claim
    )

    # Fold the field-unranked auto rows into the receipts board (they render on the
    # "AHEAD OF THE FIELD" side via the no-divergence field_label + AHEAD path, and
    # _sort_receipts drops them into the trailing no-divergence group with the seeds).
    # They must appear BEFORE the seed merge so a seed for the same identity is deduped
    # out below -- field-unranked (auto) wins over seed on identity.
    #
    # Precedence when an identity qualifies via more than one lane: scored > field-unranked
    # > seed. _field_unranked_from_row and _receipt_from_row are mutually exclusive on the
    # SAME at-promotion row (one needs < MIN_BOARDS boards, the other >= MIN_BOARDS), so a
    # single event can't double-mint. But ACROSS events a player can produce both -- e.g. a
    # disappearance dated when the field had < 2 boards on him (field-unranked) AND a later
    # retention-flip dated when >= 2 boards had appeared (scored hit). The scored hit has
    # field corroboration, so it is the stronger claim: field-unranked defers to a SCORED
    # receipt (int divergence) on identity. It does NOT defer to a committed SEED -- the
    # whole point of this lane is that auto wins over seed, so a field-unranked mint
    # SUPERSEDES a carried-forward seed for the same identity (the seed is dropped here; the
    # by_key merge below then keeps only the field-unranked row). Both may still be launch-
    # guarded downstream, but resolving precedence here keeps a player off the board twice.
    scored_keys = {row["identity_key"] for row in receipts if isinstance(row.get("divergence"), int)}
    field_unranked = [row for row in field_unranked if row["identity_key"] not in scored_keys]
    superseded_seed_keys = {row["identity_key"] for row in field_unranked}
    receipts = [
        row for row in receipts
        if not (row.get("seed") and row["identity_key"] in superseded_seed_keys)
    ]
    receipts = receipts + field_unranked

    # Fold the field-unranked-BEHIND auto rows into the misses board (they render on the
    # "BEHIND THE FIELD" side via the no-divergence field_label + BEHIND path). Precedence:
    # scored > field_unranked_behind, same as the ahead side. A scored miss (int divergence)
    # has field corroboration (>= MIN_BOARDS boards), so it is the stronger claim -- a behind
    # row defers to a scored miss on identity, and the two can never coexist for one player.
    scored_miss_keys = {row["identity_key"] for row in misses if isinstance(row.get("divergence"), int)}
    field_unranked_behind = [row for row in field_unranked_behind if row["identity_key"] not in scored_miss_keys]
    misses = misses + field_unranked_behind

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

    # Make each seed's field_label truthful against the ranked-board archive. A typed
    # "field outside top 100" can contradict the boards (Hughes: STS ~#512); derive the
    # label from the same archive the builder already loaded. Runs over the final list so
    # seed rows carried forward from the committed artifact get corrected too (the merge
    # only ever adds/keeps existing rows). Label-only -- no scoring/divergence change.
    _apply_seed_field_labels(receipts, archive_index)

    # Attach the real call-up date next to the archive-diff-inferred one, when a genuine
    # call-up transaction exists for that player. Never changes call_up_date or sorting.
    # (actual_dates was already computed above to drive the at-promotion standard.)
    for row in receipts + misses:
        real_date = actual_dates.get(str(row.get("mlbam_id")))
        if real_date:
            row["actual_call_up_date"] = real_date
        # field_unranked_behind rows are EXCLUDED from the lead-time attach: the helper walks
        # OUR claimed-rank band, which is meaningless praise on a row whose whole point is
        # that the field beat us. Pop any stale committed value and skip the compute.
        if row.get("field_unranked_behind"):
            row.pop("flagged_days_early", None)
            continue
        # Lead time: days ValuCast held this call before the field's trigger fired.
        # Anchor on the real date when known, else the board-observed call_up_date.
        # Recomputed every build from the archive index (no migration needed -- the
        # incremental merge preserves the row, and this just re-derives the field). The
        # loop runs even when actual_dates is empty (real_date is None-safe).
        days_early = _flagged_days_early(
            row.get("identity_key"),
            _clean_int(row.get("valucast_rank")),
            real_date or _date_part(row.get("call_up_date")),
            archive_index,
        )
        if days_early is not None:
            row["flagged_days_early"] = days_early
        else:
            row.pop("flagged_days_early", None)  # keep stale committed values from surviving

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

    # Neither bucket: genuine post-launch call-ups that produced no ledger row (model and
    # field even, no qualifying consensus at promotion, or rank over cap). This is the
    # honesty cure for an empty misses side -- the field's silence is counted, not hidden.
    # A row that ended up a hit/miss, a pre-launch call-up (already out of scope), and the
    # code denylist are all excluded so the count is genuine-and-in-scope no-claims only.
    claimed_keys = {r["identity_key"] for r in receipts} | {m["identity_key"] for m in misses}
    no_claim_keys = {
        key for key, event_date in no_claim.items()
        if key not in claimed_keys
        and key not in EXCLUDED_IDENTITY_KEYS
        and not (
            (real := actual_dates.get(str(key.split("_")[0]))) and real < LAUNCH_DATE
        )
    }
    # Persist + disclose the neither bucket: one anonymous, at-promotion-sourced row per
    # PUBLISHED no-claim identity (SAME set as no_claim_keys -- count parity is a hard
    # invariant asserted by the validator). Both directions used the same thresholds, so
    # the board can now SHOW every call-up it didn't score instead of only counting them.
    no_claim_rows = _build_no_claim_rows(no_claim_keys, no_claim, actual_dates, archive_index)

    # Maturation resolution (plan 016): runs on the FINAL receipts list (post
    # denylist, post real-date attach, post pre-launch drop). prior_status rides
    # in on the merged row from existing_log, so the append-only CONFIRMED floor
    # holds across rebuilds. today is the build date, not wall clock.
    workload = _mlb_workload()
    today = _date_part(generated_at) or ""
    for row in receipts:
        row["maturation_status"] = _maturation_status(
            row,
            workload,
            roster_lookup,
            today,
            prior_status=row.get("maturation_status"),
        )
    maturation_counts = {
        "pending": sum(1 for r in receipts if r["maturation_status"] == "PENDING"),
        "confirmed": sum(1 for r in receipts if r["maturation_status"] == "CONFIRMED"),
        "decayed": sum(1 for r in receipts if r["maturation_status"] == "DECAYED"),
    }

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
            # receipt_count counts the FINAL receipts list, which now INCLUDES the
            # field-unranked auto rows (they render on that side), so it grows by
            # field_unranked_count naturally. field_unranked_count is derived from the
            # final list by marker so pre-launch/denylist/revalidation drops are reflected.
            "receipt_count": len(receipts),
            "miss_count": len(misses),
            "seed_count": seed_count,
            "field_unranked_count": sum(1 for r in receipts if r.get("field_unranked")),
            # miss_count now naturally includes field-unranked-behind rows (they render on
            # the behind side), so "N behind" counts unscored behinds exactly as "N ahead"
            # counts unscored aheads -- the whole point of the mirror lane.
            "field_unranked_behind_count": sum(1 for m in misses if m.get("field_unranked_behind")),
            "no_claim_call_up_count": len(no_claim_keys),
            "archive_dates_scanned": archive_dates,
            "pre_launch_excluded_count": len(pre_launch_excluded),
            "pre_launch_excluded_names": sorted(
                {row.get("name") for row in pre_launch_excluded if row.get("name")}
            ),
            "maturation": maturation_counts,
        },
        "definitions": {
            "maturation": {
                "horizon_days": MATURATION_HORIZON_DAYS,
                "final_days": MATURATION_FINAL_DAYS,
                "confirmed": (
                    f"hitter: games >= {CONFIRM_HITTER_GAMES} OR PA >= {CONFIRM_HITTER_PA}; "
                    f"pitcher: games >= {CONFIRM_PITCHER_GAMES} OR IP >= {CONFIRM_PITCHER_IP} "
                    "-- cumulative MLB workload from ValuCast's own archived actuals "
                    "snapshots; 'he stuck and actually played' floors, comfortably above "
                    "a cup of coffee, comfortably below 'must be a star'."
                ),
                "decayed": (
                    "past the horizon, under the confirmed bar, and off the active MLB "
                    "roster -- or the 90-day final look elapsed with the bar never cleared."
                ),
                "pending": (
                    "under 60 days since call-up, or on the active roster and still "
                    "accumulating before the 90-day final look."
                ),
                "append_only": (
                    "a CONFIRMED receipt never reverts; a later demotion is career "
                    "noise, not a receipt reversal"
                ),
                "frozen": (
                    "2026-07-14, pre-registered before the first row matures (~2026-09-09)"
                ),
            },
        },
        "validation": {
            "ready_for_call_up_receipts": not blockers,
            "blockers": blockers,
        },
        "receipts": receipts,
        "misses": misses,
        "no_claim_rows": no_claim_rows,
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
