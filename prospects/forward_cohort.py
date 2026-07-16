"""Forward-ledger cohort construction (plan 030, S1): freeze a dated cohort.

The forward accuracy benchmark (`plans/030-forward-ledger.md`) registers dated
cohorts of prospects, scores ValuCast against the aggregate public consensus, and
resolves them forward on a published schedule. This module is the S1 builder core:
pure functions that turn ONE committed daily rank-archive snapshot into a frozen
cohort payload. `scripts/build_forward_cohort_registry.py` wraps it with the
registry/immutability/atomic-write machinery.

Two hard invariants govern everything here (both validator-checked downstream):

1. **No per-source third-party ranks in the output.** Boards are public, but this
   is a public repo; we carry the consensus MEDIAN + BOARD_COUNT only, never a
   per-source rank. `context_only.source_ranks` is read to COMPUTE the median and
   is then discarded — it never appears in an emitted row.
2. **Role-blind identity.** The cohort keys on `mlbam_id` (never role); a two-way
   player whose board carries duplicate mlbam_id rows collapses to the min(rank)
   row, and the dedup is counted in cohort metadata. No `role` field is emitted —
   the registered one-look protocol from plan 028 forbids any pitcher/hitter split
   on this surface.

The consensus reconstruction is REDECLARED here, not imported: the frozen
`ahead_of_consensus` / `public_snapshot_models` modules must not become runtime
dependencies of a post-freeze benchmark (the repo's decouple-by-redeclaration
rule). The semantics are ported verbatim from
`web/public_snapshot_models.py:112-120` (rounded median over external boards) and
`ahead_of_consensus._public_source_consensus`, with one extra defensive drop: any
`dd_*` source key is excluded (DD ranks never enter a ValuCast consensus).
"""
from __future__ import annotations

import hashlib
import json

PROTOCOL_VERSION = "030-v1"

# --- Eligibility dials (frozen; echoed into the cohort payload) ----------------
# A player enters the cohort iff it clears EITHER gate (plan 030 A3). Rank-only
# entrants (board_count < 2) carry a null consensus and are scored on tier/ledger
# outcomes, not consensus-gap metrics — they are never silently dropped.
MIN_BOARD_COUNT = 2
MAX_SERVED_RANK = 250

# --- Consensus reconstruction (REDECLARED, never imported) ---------------------
# The proprietary signals that never count toward a public consensus. Mirrors the
# frozen `_INTERNAL_SOURCES` set (milb_perf/milb_breakout/cfr/cfr_raw); any `dd_*`
# key is additionally dropped (DD is independent of ValuCast — its ranks never feed
# a consensus median).
_INTERNAL_SOURCES = frozenset({"milb_perf", "milb_breakout", "cfr", "cfr_raw"})
# Boards run to different depths; only count a rank inside the top-prospect ceiling
# so a single deep list can't poison the median.
_CONSENSUS_RANK_CAP = 600


def _public_source_ranks(source_ranks: dict | None) -> dict:
    """Keep only numeric EXTERNAL board ranks inside the depth cap.

    Ported verbatim from `web/public_snapshot_models.py:105-110` /
    `ahead_of_consensus._public_source_ranks`, plus the defensive `dd_*` drop."""
    return {
        source: rank
        for source, rank in (source_ranks or {}).items()
        if source not in _INTERNAL_SOURCES
        and not str(source).startswith("dd_")
        and isinstance(rank, (int, float))
        and rank <= _CONSENSUS_RANK_CAP
    }


def _public_source_consensus(public_ranks: dict) -> int | None:
    """Rounded median of the external boards.

    Ported verbatim from `web/public_snapshot_models.py:112-120`."""
    ranks = sorted(public_ranks.values())
    if not ranks:
        return None
    midpoint = len(ranks) // 2
    if len(ranks) % 2:
        return round(ranks[midpoint])
    return round((ranks[midpoint - 1] + ranks[midpoint]) / 2)


def _served_rank(row: dict) -> int | None:
    """The SERVED public ordinal (`rank`), never the raw `score`."""
    rank = row.get("rank")
    return int(rank) if isinstance(rank, (int, float)) else None


def _dedup_min_rank(board: list[dict]) -> tuple[dict[str, dict], int]:
    """Role-blind collapse: mlbam_id -> the min(rank) row. Returns (by_id, deduped).

    Rows without an mlbam_id are ignored (they cannot be cohort entrants). A
    two-way player carried on both a hitter and a pitcher board row shares one
    mlbam_id; the lower (better) served rank wins and the dropped row is counted."""
    by_id: dict[str, dict] = {}
    deduped = 0
    for row in board:
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            continue
        mlbam_id = str(mlbam_id)
        rank = _served_rank(row)
        if rank is None:
            continue
        prior = by_id.get(mlbam_id)
        if prior is None:
            by_id[mlbam_id] = row
            continue
        deduped += 1
        prior_rank = _served_rank(prior)
        # Lower served rank wins; ties keep the incumbent (deterministic on the
        # archive's own row order, which the committed file fixes).
        if prior_rank is None or (rank < prior_rank):
            by_id[mlbam_id] = row
    return by_id, deduped


def _entrant(mlbam_id: str, row: dict) -> dict | None:
    """Build one cohort entrant from a deduped board row, or None if ineligible.

    Consensus median + board_count are the ONLY consensus fields carried forward;
    the per-source `source_ranks` used to compute them are discarded here."""
    served_rank = _served_rank(row)
    if served_rank is None:
        return None
    public_ranks = _public_source_ranks((row.get("context_only") or {}).get("source_ranks"))
    board_count = len(public_ranks)
    consensus = _public_source_consensus(public_ranks) if board_count >= MIN_BOARD_COUNT else None
    # Eligibility (A3): board_count >= 2 OR served rank <= 250.
    if not (board_count >= MIN_BOARD_COUNT or served_rank <= MAX_SERVED_RANK):
        return None
    return {
        "mlbam_id": mlbam_id,
        "name": row.get("name"),
        "valucast_rank": served_rank,
        "consensus_rank": consensus,  # null for rank-only entrants
        "board_count": board_count,
    }


def _entrant_sort_key(entrant: dict) -> tuple:
    return (int(entrant["valucast_rank"]), str(entrant["mlbam_id"]))


def _content_sha256(payload: dict) -> str:
    """sha256 over the deterministic JSON body EXCLUDING the hash field itself.

    Sort keys + compact separators so the digest is stable across rebuilds."""
    body = {k: v for k, v in payload.items() if k != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_cohort(
    *,
    board: list[dict],
    registration_date: str,
    archive_date: str,
    board_vintages: dict | None = None,
) -> dict:
    """Freeze a cohort from ONE archive snapshot's board.

    - `registration_date`: the date the cohort is registered (TODAY at build time;
      never back-dated).
    - `archive_date`: the date of the archive file actually read (may lag
      `registration_date` by a day — recorded explicitly, never assumed equal).
    - `board_vintages`: prospective-only source->date map from the live vintage
      machinery; nullable (not reconstructable for past dates, so it stays null on
      dev/back-fill runs).

    Returns the frozen cohort payload (schema in `plans/030-forward-ledger.md` B).
    The `content_sha256` seals the body; a re-build on the same inputs is
    hash-identical (immutability is asserted by the registry builder)."""
    by_id, deduped = _dedup_min_rank(board)
    entrants: list[dict] = []
    consensus_covered = 0
    rank_only = 0
    for mlbam_id, row in by_id.items():
        entrant = _entrant(mlbam_id, row)
        if entrant is None:
            continue
        entrants.append(entrant)
        if entrant["consensus_rank"] is None:
            rank_only += 1
        else:
            consensus_covered += 1
    entrants.sort(key=_entrant_sort_key)

    payload = {
        "protocol_version": PROTOCOL_VERSION,
        "registration_date": registration_date,
        "archive_date": archive_date,
        # Prospective-only; null when the vintage map is unavailable (all past dates).
        "board_vintages": board_vintages,
        "eligibility": {
            "min_board_count": MIN_BOARD_COUNT,
            "max_served_rank": MAX_SERVED_RANK,
            "consensus_rank_cap": _CONSENSUS_RANK_CAP,
            "internal_sources_excluded": sorted(_INTERNAL_SOURCES),
            "dd_sources_excluded": True,
        },
        "counts": {
            "eligible_total": len(entrants),
            "consensus_covered": consensus_covered,
            "rank_only": rank_only,
            "deduped": deduped,
        },
        "entrants": entrants,
        "content_sha256": "",
    }
    payload["content_sha256"] = _content_sha256(payload)
    return payload
