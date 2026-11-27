"""Lazy, fail-soft reader of the committed FanGraphs FV scouting snapshot.

FanGraphs Future Value + tool grades are a SCOUTING REFERENCE for the player
card only. This store is display-only and is intentionally NOT imported by the
scoring/raw-input path, so FG grades can never feed the ValuCast score, rank,
value, or buy-score (independence policy).

Snapshot is produced by scripts/build_fangraphs_fv_snapshot.py
(data/fangraphs/fg_fv_snapshot.json), keyed by mlbam_id.
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = (
    Path(__file__).parent.parent / "data" / "fangraphs" / "fg_fv_snapshot.json"
)


class FgFvStore:
    """Card-ready FanGraphs FV lookup by mlbam_id; empty when artifact missing."""

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._loaded = False
        self._by_mlbam: dict[str, dict] = {}

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            by = raw.get("players_by_mlbam")
            self._by_mlbam = by if isinstance(by, dict) else {}
        except (OSError, ValueError):
            # Missing/unreadable/malformed -> empty store; the card just renders
            # without the FanGraphs section.
            self._by_mlbam = {}

    def get(self, mlbam_id: str | int | None) -> dict | None:
        if mlbam_id is None or str(mlbam_id).strip() == "":
            return None
        self._ensure_loaded()
        return self._by_mlbam.get(str(mlbam_id))
