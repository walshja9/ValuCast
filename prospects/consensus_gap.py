"""Two-sided consensus-gap board: where ValuCast diverges most from the field.

The ahead side (VC ranks a prospect far HIGHER than the public consensus)
already powers the AOTC pipeline and is scored by the public ledger. This
module adds the side nobody publishes: fades — prospects the field ranks
prominently that ValuCast ranks far lower — and packages both directions as
one display-only artifact for the /gaps page.

The consensus and divergence numbers reuse the AOTC primitives verbatim (same
board filter, same rounded-median, same divergence row), and the live-roster
call-up belt is mirrored from the AOTC report, so the two surfaces are built
from the same inputs by the same code paths.

Honesty rules:
- A gap claim needs a corroborated consensus: >= 3 public boards (the AOTC
  "featured" bar), never a one-board straw man.
- ONE symmetric depth rule for both sides: our rank AND the field's must both
  sit inside the top 300 (7/8 review: an asymmetric cap that runs in the
  flattering direction is the thumb-on-the-scale this page exists to reject).
- Active MLB call-ups are excluded on both sides — a delisted call-up's field
  rank is an eligibility artifact, not a disagreement.
- The ahead side is scored by the AOTC ledger; fades are NOT ledger-scored
  yet, and the artifact says so explicitly rather than borrowing credibility.
- No silent caps: the summary carries how many rows qualified vs. shown.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from prospects.ahead_of_consensus import (
    ARTIFACT_PATH as AOTC_ARTIFACT_PATH,  # noqa: F401  (documented provenance)
    FEATURED_MIN_BOARDS,
    MAX_VALUCAST_RANK,
    MIN_DIVERGENCE,
    MLB_ROSTER_STATUS_PATH,
    RANK_PATH,
    _board_rows,
    _conviction,
    _divergence_row,
    _load_optional,
    active_roster_lookup,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_consensus_gap.json"

ARTIFACT_NAME = "valucast_consensus_gap"
MAX_ROWS_PER_SIDE = 15
# ONE symmetric depth rule for both sides (7/8 review: an asymmetric cap that
# runs in the flattering direction is exactly the kind of thumb-on-the-scale
# this page exists to reject): a gap only qualifies when BOTH ranks — ours and
# the field's — sit inside the top 300. Deeper than that, a rank is a
# sample-size statement (ours) or past the boards' reliable depth (theirs),
# not a price.
MAX_GAP_RANK = MAX_VALUCAST_RANK


# 7/9 claims audit (Surface 3, gap a/b): the /gaps page stamps today's date on a
# field consensus whose source boards are 9-15 days old, and nothing gates the page
# on that vintage. Record the real per-board dates so the page can disclose them.
# Only HKB and Pipeline snapshots carry an internal date; PL/STS derive from their
# source CSV; FG has no dependable committed vintage. See plan 020 "Current state".
_BOARD_SOURCES = {
    "hkb": ROOT / "data" / "hkb" / "hkb_consensus_snapshot.json",
    "pipeline": ROOT / "data" / "pipeline" / "pipeline_consensus_snapshot.json",
    "pl": ROOT / "data" / "prospectslive" / "prospectslive_top600.csv",
    "sts": ROOT / "data" / "sts" / "sts_consensus_hitters.csv",
    # fg intentionally omitted: no dependable committed vintage on the export CSV today.
}


def _board_source_date(source: str, path: Path) -> str | None:
    """Best available YYYY-MM-DD vintage for one board. Internal generated_at/as_of
    for JSON snapshots that carry one; file mtime otherwise. Fail-soft -> None."""
    try:
        if path.suffix == ".json":
            payload = json.loads(path.read_text(encoding="utf-8"))
            stamp = payload.get("generated_at") or payload.get("as_of")
            if stamp:
                return str(stamp)[:10]
        # dateless snapshots / CSVs: fall back to filesystem mtime (the committed
        # CSV's date). NOT the *_consensus_snapshot.json commit date, which the
        # daily build re-stamps to today even when the CSV is 2 weeks old.
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
    except Exception:  # noqa: BLE001
        return None


def _board_vintages() -> dict:
    dates = {src: _board_source_date(src, p) for src, p in _BOARD_SOURCES.items()}
    present = sorted(d for d in dates.values() if d)
    return {
        "board_source_dates": {k: v for k, v in dates.items() if v},
        "board_min_date": present[0] if present else None,
    }


def _within_depth(row: dict) -> bool:
    return (
        (row.get("valucast_rank") or 999999) <= MAX_GAP_RANK
        and (row.get("consensus_rank") or 999999) <= MAX_GAP_RANK
    )


def _qualifies_ahead(row: dict) -> bool:
    return (
        row.get("board_count", 0) >= FEATURED_MIN_BOARDS
        and row.get("divergence") is not None
        and row["divergence"] >= MIN_DIVERGENCE
        and _within_depth(row)
        and not row.get("in_mlb")
    )


def _qualifies_fade(row: dict) -> bool:
    return (
        row.get("board_count", 0) >= FEATURED_MIN_BOARDS
        and row.get("divergence") is not None
        and row["divergence"] <= -MIN_DIVERGENCE
        and _within_depth(row)
        and not row.get("in_mlb")
    )


def _display_row(row: dict) -> dict:
    # Aggregate consensus only — the per-source `boards` dict never enters this
    # artifact (7/8, Alex): the median across boards is our transformative
    # figure; republishing each outside site's exact per-player rank would
    # redistribute their product against their terms of service.
    #
    # But the min/max of that dict ARE publishable as a dispersion signal (7/9
    # audit, Surface 3 gap c): they reveal a split field (Condon #30-#157) vs a
    # tight one (De Vries #2-#23) without redistributing any single board's exact
    # per-player rank. Two anonymous integers, never the dict.
    board_ranks = [
        r for r in (row.get("boards") or {}).values() if isinstance(r, (int, float))
    ]
    out = {
        key: row.get(key)
        for key in (
            "identity_key", "mlbam_id", "name", "team", "role",
            "valucast_rank", "consensus_rank", "board_count",
            "divergence",
        )
    }
    if board_ranks:
        out["board_min"] = int(min(board_ranks))
        out["board_max"] = int(max(board_ranks))
    return out


def build_consensus_gap_board(
    rank_payload: dict,
    generated_at: str | None = None,
    roster_status: dict | None = None,
    board_vintages: dict | None = None,
) -> dict:
    rows = [
        divergence
        for board_row in _board_rows(rank_payload)
        if (divergence := _divergence_row(board_row)) is not None
    ]
    evaluated = len(rows)
    # Same live-roster belt AOTC applies on top of the row stamp: the committed
    # rank artifact can predate the active_mlb_roster stamp. Fail-soft.
    active_ids = set(active_roster_lookup(roster_status or {}))
    if active_ids:
        for row in rows:
            if row.get("mlbam_id") in active_ids:
                row["in_mlb"] = True

    ahead = sorted(
        (row for row in rows if _qualifies_ahead(row)),
        key=lambda row: -_conviction(row),
    )
    fade = sorted(
        (row for row in rows if _qualifies_fade(row)),
        key=lambda row: _conviction(row),  # most negative first
    )

    vintages = board_vintages or {}
    return {
        "artifact": ARTIFACT_NAME,
        "generated_at": generated_at or rank_payload.get("generated_at"),
        # 7/9 audit (gap a): the field's ranks are 9-15 days old even though the
        # artifact is regenerated today. Record the honest per-board vintage and
        # the oldest of them so the page can disclose the field's real age.
        "board_source_dates": vintages.get("board_source_dates") or {},
        "board_min_date": vintages.get("board_min_date"),
        "source_policy": {
            "display_only": True,
            "feeds_live_valucast_rank": False,
            "feeds_model_score": False,
        },
        "method": {
            "consensus": (
                "rounded median of external public boards (same math as the "
                "ahead-of-consensus badge/card/scorecard, reused verbatim)"
            ),
            "min_boards": FEATURED_MIN_BOARDS,
            "min_divergence": MIN_DIVERGENCE,
            "max_rank_both_sides": MAX_GAP_RANK,
            "depth_rule": (
                "symmetric: both our rank and the field's must sit inside the "
                "top 300 — deeper than that a rank is a sample-size statement "
                "(ours) or past the boards' reliable depth (theirs), not a price"
            ),
            "excludes_active_mlb_roster": True,
            "ordering": "by |log(consensus / valucast)| — how many times apart the two ranks sit",
        },
        "scoring": {
            "ahead_scored_by_ledger": True,
            "fade_scored_by_ledger": False,
            "note": (
                "Ahead calls feed the public AOTC scorecard. Fade calls are "
                "published but not ledger-scored yet."
            ),
        },
        "summary": {
            "evaluated": evaluated,
            "ahead_qualified": len(ahead),
            "fade_qualified": len(fade),
            "shown_per_side": MAX_ROWS_PER_SIDE,
        },
        "higher": [_display_row(row) for row in ahead[:MAX_ROWS_PER_SIDE]],
        "lower": [_display_row(row) for row in fade[:MAX_ROWS_PER_SIDE]],
    }


def run(artifact_path: Path = ARTIFACT_PATH) -> dict:
    rank_payload = json.loads(RANK_PATH.read_text(encoding="utf-8"))
    payload = build_consensus_gap_board(
        rank_payload,
        roster_status=_load_optional(MLB_ROSTER_STATUS_PATH),
        board_vintages=_board_vintages(),
    )
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return payload
