"""Committed Statcast percentile snapshot (Baseball Savant) for player cards.

NETWORK-FREE at runtime: reads data/statcast/percentiles.json, which is built by
scripts/fetch_statcast_percentiles.py and committed to the repo. A missing or
malformed artifact degrades to "no percentile section" — never an exception and
never a fetch (request-time fetches on Render were the 502 lesson).

Savant's percentiles are pre-oriented so higher = better for the player on both
sides of the ball (a batter with a low K%% gets a HIGH k_percent percentile).
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).parent.parent / "data" / "statcast" / "percentiles.json"

# Curated card metrics, in Savant player-page order. Keys absent for a player
# (e.g. no sprint speed for a DH-only sample) are simply skipped.
BATTER_METRICS: list[tuple[str, str]] = [
    ("xwoba", "xwOBA"),
    ("xba", "xBA"),
    ("xslg", "xSLG"),
    ("exit_velocity", "Avg Exit Velo"),
    ("brl_percent", "Barrel %"),
    ("hard_hit_percent", "Hard-Hit %"),
    ("chase_percent", "Chase %"),
    ("whiff_percent", "Whiff %"),
    ("k_percent", "K %"),
    ("bb_percent", "BB %"),
    ("sprint_speed", "Sprint Speed"),
    ("oaa", "Fielding (OAA)"),
]
PITCHER_METRICS: list[tuple[str, str]] = [
    ("xwoba", "xwOBA"),
    ("xera", "xERA"),
    ("k_percent", "K %"),
    ("bb_percent", "BB %"),
    ("whiff_percent", "Whiff %"),
    ("chase_percent", "Chase %"),
    ("brl_percent", "Barrel %"),
    ("hard_hit_percent", "Hard-Hit %"),
    ("exit_velocity", "Avg Exit Velo"),
    ("fb_velocity", "FB Velo"),
    ("fb_spin", "FB Spin"),
]

# Savant-style diverging scale: blue (poor) -> gray (average) -> red (elite).
_LOW = (54, 97, 173)
_MID = (160, 163, 170)
_HIGH = (214, 41, 28)


def percentile_color(pct: int | float) -> str:
    """Hex color for a 0-100 percentile on the Savant-style blue/gray/red scale."""
    p = max(0.0, min(100.0, float(pct)))
    if p <= 50:
        lo, hi, t = _LOW, _MID, p / 50
    else:
        lo, hi, t = _MID, _HIGH, (p - 50) / 50
    rgb = tuple(round(a + (b - a) * t) for a, b in zip(lo, hi))
    return "#{:02x}{:02x}{:02x}".format(*rgb)


class StatcastStore:
    """Lazy, fail-soft reader of the committed percentile artifact."""

    def __init__(self, path: str | Path = _DEFAULT_PATH) -> None:
        self._path = Path(path)
        self._loaded = False
        self._batters: dict[str, dict] = {}
        self._pitchers: dict[str, dict] = {}
        self._as_of: str | None = None

    def _ensure_loaded(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            batters = raw.get("batters")
            pitchers = raw.get("pitchers")
            self._batters = batters if isinstance(batters, dict) else {}
            self._pitchers = pitchers if isinstance(pitchers, dict) else {}
            self._as_of = raw.get("as_of")
        except (OSError, ValueError):
            # Missing/unreadable/malformed -> empty store; the card just renders
            # without a percentile section.
            self._batters, self._pitchers, self._as_of = {}, {}, None

    @property
    def as_of(self) -> str | None:
        self._ensure_loaded()
        return self._as_of

    def display_groups(
        self, mlbam_id: str | int | None, prefer_pitching: bool = False
    ) -> list[dict]:
        """Card-ready percentile groups for a player, [] when unavailable.

        Each group: {"label", "metrics": [{"label", "pct", "color"}, ...]}.
        Two-way players get both groups; prefer_pitching puts pitching first.
        """
        if mlbam_id is None or str(mlbam_id).strip() == "":
            return []
        self._ensure_loaded()
        key = str(mlbam_id)
        groups = []
        batting = self._rows(self._batters.get(key), BATTER_METRICS)
        pitching = self._rows(self._pitchers.get(key), PITCHER_METRICS)
        if batting:
            groups.append({"label": "Batting", "metrics": batting})
        if pitching:
            groups.append({"label": "Pitching", "metrics": pitching})
        if prefer_pitching and len(groups) == 2:
            groups.reverse()
        return groups

    @staticmethod
    def _rows(metrics: dict | None, spec: list[tuple[str, str]]) -> list[dict]:
        if not isinstance(metrics, dict):
            return []
        rows = []
        for key, label in spec:
            pct = metrics.get(key)
            if isinstance(pct, (int, float)):
                p = int(max(0, min(100, pct)))
                rows.append({"label": label, "pct": p, "color": percentile_color(p)})
        return rows
