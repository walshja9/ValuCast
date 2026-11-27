"""Committed ValuCast rank-history snapshot for prospect cards.

NETWORK-FREE at runtime: reads data/models/valucast_prospect_rank_history.json, built
by scripts/build_prospect_rank_history.py from the committed dated rank archive. A
missing or malformed artifact degrades to "no rank-trend section" -- never an exception
and never a fetch (the same fail-soft posture as AaaStatcastStore / PitchDisciplineStore).

Modeled on web/aaa_statcast_store.py: lazy _ensure_loaded, fail-soft to empty, keyed by
str(mlbam_id). One card surface:
  * trend_for(mlbam) -> {sparkline geometry (rank axis INVERTED so #1 is at the top),
                         caption, best/latest ranks+dates} for a tracked prospect, or {}
                         when the player isn't in the artifact / has < 2 series points.

DISPLAY-ONLY: ranks are relative and epoch-robust (they survive score re-baselines), so
this proves ValuCast's early calls (Arias #1 on 2026-06-18) even after a re-baseline.
NEVER a value/rank/buy/AOTC input -- card context only.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

_DEFAULT_PATH = (
    Path(__file__).parent.parent / "data" / "models" / "valucast_prospect_rank_history.json"
)

# Minimum series points to render a trend (a single dot is not a "trend").
_MIN_POINTS = 2

# Sparkline viewBox. The path uses non-scaling stroke + preserveAspectRatio in the
# template, so these are geometry units, not pixels; the SVG scales to its container.
_VIEW_W = 240.0
_VIEW_H = 60.0
_PAD_Y = 6.0  # vertical inset so the #1 dot and the worst-rank dot aren't clipped.

_MONTHS = (
    "", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _fmt_date(iso: str) -> str:
    """'2026-06-18' -> 'Jun 18' (no leading zero on the day). Passthrough on junk."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return str(iso)
    return f"{_MONTHS[d.month]} {d.day}"


class RankHistoryStore:
    """Lazy, fail-soft reader of the committed prospect rank-history artifact."""

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._loaded = False
        self._players: dict[str, dict] = {}
        self._generated_at: str | None = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = {}
            players = raw.get("players")
            self._players = players if isinstance(players, dict) else {}
            self._generated_at = raw.get("generated_at")
        except (OSError, ValueError):
            # Missing/unreadable/malformed -> empty store; the card renders without
            # a rank-trend section.
            self._players, self._generated_at = {}, None

    def trend_for(self, mlbam_id: str | int | None) -> dict:
        """Card-ready rank-trend section, {} when unavailable or too sparse.

        Returns (all pre-computed for the template, no JS):
          {"points": "x,y x,y ...",  # polyline points, rank axis inverted (#1 at top)
           "dot_x","dot_y",          # highlight dot on the latest point
           "view_w","view_h",        # viewBox dims
           "best_rank","best_date","latest_rank","latest_date",  # date strings 'Jun 18'
           "caption",                # "Best #1 (Jun 18) - now #7"
           "n_points"}
        """
        record = self._lookup(mlbam_id)
        if not isinstance(record, dict):
            return {}
        series = record.get("series")
        if not isinstance(series, list) or len(series) < _MIN_POINTS:
            return {}
        # Normalize to clean (date, rank) tuples; drop any malformed entry defensively.
        pts = [
            (d, r) for d, r in (
                p for p in series if isinstance(p, (list, tuple)) and len(p) == 2
            )
            if isinstance(r, int) and not isinstance(r, bool)
        ]
        if len(pts) < _MIN_POINTS:
            return {}

        best_rank = record.get("best_rank")
        best_date = record.get("best_rank_date")
        latest_rank = record.get("latest_rank")
        latest_date = record.get("latest_date")
        # Fall back to the series itself if the summary fields are missing/bad, so the
        # section still renders coherently rather than dropping.
        if not isinstance(best_rank, int) or not isinstance(best_date, str):
            best_date, best_rank = min(pts, key=lambda dr: (dr[1], dr[0]))
        if not isinstance(latest_rank, int) or not isinstance(latest_date, str):
            latest_date, latest_rank = pts[-1]

        coords = self._project(pts)
        dot_x, dot_y = coords[-1]
        return {
            "points": " ".join(f"{x:.1f},{y:.1f}" for x, y in coords),
            "dot_x": round(dot_x, 1),
            "dot_y": round(dot_y, 1),
            "view_w": _VIEW_W,
            "view_h": _VIEW_H,
            "best_rank": best_rank,
            "best_date": _fmt_date(best_date),
            "latest_rank": latest_rank,
            "latest_date": _fmt_date(latest_date),
            "caption": (
                f"Best #{best_rank} ({_fmt_date(best_date)}) - now #{latest_rank}"
            ),
            "n_points": len(pts),
        }

    # --- internals ---------------------------------------------------------
    def _lookup(self, mlbam_id) -> dict | None:
        if mlbam_id is None or str(mlbam_id).strip() == "":
            return None
        self._ensure_loaded()
        # Read the table AFTER load: _ensure_loaded reassigns _players, so a reference
        # captured before load would be the stale pre-load empty dict.
        return self._players.get(str(mlbam_id))

    @staticmethod
    def _project(pts: list[tuple[str, int]]) -> list[tuple[float, float]]:
        """Map (date, rank) points to SVG coords with the RANK AXIS INVERTED.

        x spreads evenly across the width by index (dates are unevenly spaced but the
        trend reads as an ordered sequence). y is inverted so rank #1 (the best) sits at
        the TOP of the chart and larger rank numbers fall toward the bottom.
        """
        n = len(pts)
        ranks = [r for _, r in pts]
        lo, hi = min(ranks), max(ranks)
        span = hi - lo
        usable_h = _VIEW_H - 2 * _PAD_Y
        coords: list[tuple[float, float]] = []
        for i, (_, rank) in enumerate(pts):
            x = 0.0 if n == 1 else (_VIEW_W * i / (n - 1))
            # frac=0 for the best rank (lo) -> top; frac=1 for the worst -> bottom.
            frac = 0.0 if span == 0 else (rank - lo) / span
            y = _PAD_Y + frac * usable_h
            coords.append((x, y))
        return coords
