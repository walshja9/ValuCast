"""Committed plate-discipline snapshot (MLB StatsAPI play-by-play) for player cards.

NETWORK-FREE at runtime: reads data/models/valucast_pitch_discipline.json, which is
built by scripts/build_pitch_discipline.py and committed to the repo. A missing or
malformed artifact degrades to "no plate-discipline section" — never an exception and
never a fetch (the same 502-lesson posture as StatcastStore).

Modeled on web/statcast_store.py: lazy _ensure_loaded, fail-soft to empty, keyed by
str(mlbam_id). groups_for(mlbam_id) returns one card-ready group PER LEVEL, exact
metrics tagged estimated=False and zone metrics tagged estimated=True so the template
can render an "est." marker + methodology link on the estimates.

Observe-only display context — NEVER a value input. NO exit velocity exists here.
"""
from __future__ import annotations

import json
from pathlib import Path

from web.statcast_store import percentile_color

_DEFAULT_PATH = (
    Path(__file__).parent.parent / "data" / "models" / "valucast_pitch_discipline.json"
)

# Card display order: EXACT outcome group first (the product), then the ESTIMATED
# zone group. Metric keys map to labels from the artifact but we keep a stable order
# here so the card is deterministic even if the artifact's label dict reorders.
_EXACT_ORDER = ("swing_pct", "whiff_pct", "swstr_pct")
_ESTIMATED_ORDER = ("chase_pct", "z_swing_pct", "z_contact_pct", "zone_pct")

# Level display order (highest level first).
_LEVEL_ORDER = ("AAA", "AA", "A+", "A")

_DEFAULT_LABELS = {
    "swing_pct": "Swing%", "whiff_pct": "Whiff%", "swstr_pct": "SwStr%",
    "chase_pct": "Chase%", "z_swing_pct": "Z-Swing%",
    "z_contact_pct": "Z-Contact%", "zone_pct": "Zone%",
}


def _format_pct(value) -> str | None:
    return f"{float(value):.1f}%" if isinstance(value, (int, float)) else None


class PitchDisciplineStore:
    """Lazy, fail-soft reader of the committed plate-discipline artifact."""

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._loaded = False
        self._players: dict[str, dict] = {}
        self._labels: dict[str, str] = dict(_DEFAULT_LABELS)
        self._as_of: str | None = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            players = raw.get("players")
            self._players = players if isinstance(players, dict) else {}
            labels = raw.get("metric_labels")
            if isinstance(labels, dict):
                self._labels = {**_DEFAULT_LABELS, **labels}
            self._as_of = raw.get("as_of")
        except (OSError, ValueError):
            # Missing/unreadable/malformed -> empty store; the card renders without
            # a plate-discipline section.
            self._players, self._as_of = {}, None
            self._labels = dict(_DEFAULT_LABELS)

    @property
    def as_of(self) -> str | None:
        self._ensure_loaded()
        return self._as_of

    def groups_for(self, mlbam_id: str | int | None) -> list[dict]:
        """Card-ready plate-discipline groups for a player, [] when unavailable.

        One group per level the player has a QUALIFYING bucket for (>= the artifact's
        min-pitch floor). Each group:
          {"level","as_of","estimated" (any estimated metric), "min_pitches",
           "metrics":[{"key","label","raw","display","pct","estimated","color"},...]}
        A metric with no percentile (contextual, or below floor) carries pct=None and
        the template renders the raw value with no fill judgment.
        """
        if mlbam_id is None or str(mlbam_id).strip() == "":
            return []
        self._ensure_loaded()
        levels = self._players.get(str(mlbam_id))
        if not isinstance(levels, dict):
            return []
        groups = []
        for level in self._ordered_levels(levels):
            bucket = levels.get(level)
            if not isinstance(bucket, dict) or not bucket.get("qualifies"):
                continue
            group = self._build_group(level, bucket)
            if group["metrics"]:
                groups.append(group)
        return groups

    def _ordered_levels(self, levels: dict) -> list[str]:
        present = list(levels.keys())
        ranked = [l for l in _LEVEL_ORDER if l in present]
        # Preserve any unexpected level labels after the known order.
        ranked += [l for l in present if l not in _LEVEL_ORDER]
        return ranked

    def _build_group(self, level: str, bucket: dict) -> dict:
        rates = bucket.get("rates") or {}
        pcts = bucket.get("percentiles") or {}
        metrics = []
        for key in _EXACT_ORDER:
            row = self._metric_row(key, rates, pcts, estimated=False)
            if row:
                metrics.append(row)
        zone_estimated = bool(bucket.get("zone_estimated", True))
        for key in _ESTIMATED_ORDER:
            row = self._metric_row(key, rates, pcts, estimated=zone_estimated)
            if row:
                metrics.append(row)
        any_estimated = any(m["estimated"] for m in metrics)
        return {
            "level": level,
            "as_of": self._as_of,
            "estimated": any_estimated,
            "min_pitches": None,   # informational; the artifact holds the real floor
            "pitches": bucket.get("pitches"),
            "metrics": metrics,
        }

    def _metric_row(self, key: str, rates: dict, pcts: dict, *, estimated: bool) -> dict | None:
        raw = rates.get(key)
        if not isinstance(raw, (int, float)):
            return None
        pct = pcts.get(key)
        pct = int(max(0, min(100, pct))) if isinstance(pct, (int, float)) else None
        return {
            "key": key,
            "label": self._labels.get(key, key),
            "raw": float(raw),
            "display": _format_pct(raw),
            "pct": pct,
            "estimated": estimated,
            "color": percentile_color(pct) if pct is not None else None,
        }
