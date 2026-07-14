"""Committed AAA-Statcast snapshot (Baseball Savant) for prospect cards.

NETWORK-FREE at runtime: reads data/models/valucast_aaa_statcast_features.json, built
by scripts/build_aaa_statcast_features.py from the (uncommitted) pitch cache and
committed to the repo. A missing or malformed artifact degrades to "no AAA-Statcast
section" -- never an exception and never a fetch (the same 502-lesson posture as
StatcastStore / PitchDisciplineStore).

Modeled EXACTLY on web/pitch_discipline_store.py: lazy _ensure_loaded, fail-soft to
empty, keyed by str(mlbam_id). Two card surfaces:
  * pitch_shape_for(mlbam)     -> per-pitch-type shape rows + overall plate outcomes
                                   for a tracked pitcher (empty when unavailable).
  * contact_quality_for(mlbam) -> EV / hard-hit / launch-angle + outcomes for a
                                   tracked hitter (empty when unavailable).

LABELING: these are MEASURED AAA Statcast values (Savant) -- rendered WITHOUT any
"est." tag. AAA only. Observe-only display context, NEVER a value/rank input.
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = (
    Path(__file__).parent.parent / "data" / "models" / "valucast_aaa_statcast_features.json"
)

# Pitch-type display order (four-seam, sinker, cutter, then breakers/offspeed); any
# unlisted type sorts after by descending usage. Codes match Savant's pitch_type.
_PITCH_TYPE_ORDER = ("FF", "SI", "FC", "SL", "ST", "CU", "KC", "CH", "FS", "FO", "SC")
_PITCH_TYPE_LABELS = {
    "FF": "4-Seam", "SI": "Sinker", "FC": "Cutter", "SL": "Slider", "ST": "Sweeper",
    "CU": "Curve", "KC": "Knuckle-Curve", "CH": "Changeup", "FS": "Splitter",
    "FO": "Forkball", "SC": "Screwball",
}

# Overall plate-outcome rows for a pitcher, in card order.
_PITCHER_OUTCOME_ORDER = (
    ("whiff_pct", "Whiff%"),
    ("csw_pct", "CSW%"),
    ("chase_pct", "Chase%"),
    ("zone_pct", "Zone%"),
    ("gb_pct", "GB%"),
)
# Contact-quality + outcome rows for a hitter, in card order.
_HITTER_ROW_ORDER = (
    ("avg_ev", "Avg Exit Velo"),
    ("max_ev", "Max Exit Velo"),
    ("hardhit_pct", "Hard-Hit%"),
    ("avg_la", "Launch Angle"),
    ("whiff_pct", "Whiff%"),
    ("chase_pct", "Chase%"),
    ("gb_pct", "GB%"),
)


def _fmt(key: str, value) -> str | None:
    if not isinstance(value, (int, float)):
        return None
    v = float(value)
    if key in ("avg_ev", "max_ev", "velo"):
        return f"{v:.1f} mph"
    if key == "avg_la":
        return f"{v:.1f}°"
    if key == "spin":
        return f"{v:.0f} rpm"
    if key in ("ivb", "hb", "ext"):
        return f"{v:+.1f} in" if key in ("ivb", "hb") else f"{v:.1f} ft"
    if key.endswith("_pct"):
        return f"{v:.1f}%"
    return str(value)


class AaaStatcastStore:
    """Lazy, fail-soft reader of the committed AAA-Statcast feature artifact."""

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._loaded = False
        self._pitchers: dict[str, dict] = {}
        self._hitters: dict[str, dict] = {}
        self._as_of: str | None = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                # Valid JSON, wrong shape (e.g. a top-level list) degrades to empty.
                raw = {}
            pitchers = raw.get("pitchers")
            hitters = raw.get("hitters")
            self._pitchers = pitchers if isinstance(pitchers, dict) else {}
            self._hitters = hitters if isinstance(hitters, dict) else {}
            self._as_of = raw.get("as_of")
        except (OSError, ValueError):
            # Missing/unreadable/malformed -> empty store; the card renders without
            # an AAA-Statcast section.
            self._pitchers, self._hitters, self._as_of = {}, {}, None

    @property
    def as_of(self) -> str | None:
        self._ensure_loaded()
        return self._as_of

    def pitch_shape_for(self, mlbam_id: str | int | None) -> dict:
        """Card-ready pitch-shape section for a pitcher, {} when unavailable.

        {"as_of","n_pitches","pitch_types":[{key,label,usage,rows:[{label,value}]}],
         "outcomes":[{key,label,value}]} -- all values pre-formatted strings.
        """
        record = self._lookup("pitchers", mlbam_id)
        if not isinstance(record, dict):
            return {}
        pitch_types = self._pitch_type_cards(record.get("pitch_types"))
        outcomes = self._outcome_rows(record.get("overall"), _PITCHER_OUTCOME_ORDER)
        if not pitch_types and not outcomes:
            return {}
        return {
            "as_of": self._as_of,
            "n_pitches": record.get("n_pitches"),
            "pitch_types": pitch_types,
            "outcomes": outcomes,
        }

    def contact_quality_for(self, mlbam_id: str | int | None) -> dict:
        """Card-ready contact-quality section for a hitter, {} when unavailable.

        {"as_of","n_pitches","n_bip","rows":[{key,label,value}]} -- pre-formatted.
        """
        record = self._lookup("hitters", mlbam_id)
        if not isinstance(record, dict):
            return {}
        rows = self._outcome_rows(record, _HITTER_ROW_ORDER)
        if not rows:
            return {}
        return {
            "as_of": self._as_of,
            "n_pitches": record.get("n_pitches"),
            "n_bip": record.get("n_bip"),
            "rows": rows,
        }

    # --- internals ---------------------------------------------------------
    def _lookup(self, role: str, mlbam_id) -> dict | None:
        if mlbam_id is None or str(mlbam_id).strip() == "":
            return None
        self._ensure_loaded()
        # Read the table AFTER load: _ensure_loaded reassigns _pitchers/_hitters, so a
        # reference captured before load would be the stale pre-load empty dict.
        table = self._pitchers if role == "pitchers" else self._hitters
        return table.get(str(mlbam_id))

    def _ordered_pitch_types(self, pitch_types: dict) -> list[str]:
        present = list(pitch_types.keys())
        ranked = [pt for pt in _PITCH_TYPE_ORDER if pt in present]
        # Unexpected codes after the known order, by descending usage share.
        extra = [pt for pt in present if pt not in _PITCH_TYPE_ORDER]
        extra.sort(
            key=lambda pt: (pitch_types.get(pt) or {}).get("usage_pct") or 0.0,
            reverse=True,
        )
        return ranked + extra

    def _pitch_type_cards(self, pitch_types) -> list[dict]:
        if not isinstance(pitch_types, dict):
            return []
        cards = []
        for pt in self._ordered_pitch_types(pitch_types):
            row = pitch_types.get(pt)
            if not isinstance(row, dict):
                continue
            metrics = []
            for key, label in (
                ("velo", "Velo"), ("ivb", "IVB"), ("hb", "HB"),
                ("spin", "Spin"), ("ext", "Ext"),
            ):
                display = _fmt(key, row.get(key))
                if display is not None:
                    metrics.append({"label": label, "value": display})
            if not metrics:
                continue
            cards.append({
                "key": pt,
                "label": _PITCH_TYPE_LABELS.get(pt, pt),
                "usage": _fmt("usage_pct", row.get("usage_pct")),
                "n": row.get("n"),
                "rows": metrics,
            })
        return cards

    @staticmethod
    def _outcome_rows(record, order) -> list[dict]:
        if not isinstance(record, dict):
            return []
        rows = []
        for key, label in order:
            display = _fmt(key, record.get(key))
            if display is not None:
                rows.append({"key": key, "label": label, "value": display})
        return rows
