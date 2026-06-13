"""Fetch Baseball Savant percentile rankings into a committed snapshot artifact.

Snapshot model (same as data/projections): the daily public-data workflow writes
and commits data/statcast/percentiles.json. The web app never fetches Savant at
runtime; it only reads the committed artifact.

Usage: PYTHONPATH=src:. python scripts/fetch_statcast_percentiles.py [year]

Savant's CSV percentiles are already oriented so higher = better for the player
(e.g. a low batter K%% earns a HIGH percentile). Values are kept verbatim.
"""
from __future__ import annotations

import csv
import io
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

URL = "https://baseballsavant.mlb.com/leaderboard/percentile-rankings?type={kind}&year={year}&csv=true"
CUSTOM_URL = (
    "https://baseballsavant.mlb.com/leaderboard/custom?"
    "year={year}&type={kind}&min=1&selections={selections}&csv=true"
)
OUT_PATH = Path(__file__).parent.parent / "data" / "statcast" / "percentiles.json"
_TIMEOUT = 30
_SKIP_FIELDS = {"player_name", "player_id", "year"}
_ID_FIELDS = ("player_id", "batter", "pitcher")

# Artifact key -> possible custom-leaderboard CSV headers. The endpoint changes
# names occasionally, so parsing selects the first alias actually present.
RAW_COLUMNS = {
    "xwoba": ("xwoba",),
    "xba": ("xba",),
    "xslg": ("xslg",),
    "xiso": ("xiso",),
    "xobp": ("xobp",),
    "exit_velocity": ("exit_velocity_avg", "exit_velocity"),
    "brl_percent": ("barrel_batted_rate", "brl_percent"),
    "hard_hit_percent": ("hard_hit_percent",),
    "k_percent": ("k_percent",),
    "bb_percent": ("bb_percent",),
    "whiff_percent": ("whiff_percent",),
    "chase_percent": ("oz_swing_percent", "chase_percent"),
    "sprint_speed": ("sprint_speed",),
    "oaa": ("oaa", "outs_above_average"),
    "xera": ("xera",),
    "fb_velocity": ("fb_velocity", "ff_avg_speed", "fastball_avg_speed"),
    "fb_spin": ("fb_spin", "ff_avg_spin", "fastball_avg_spin"),
}


def _fetch_csv(kind: str, year: int) -> str:
    req = urllib.request.Request(
        URL.format(kind=kind, year=year),
        headers={"User-Agent": "Mozilla/5.0 (ValuCast snapshot fetch)"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8-sig")


def _fetch_custom_csv(kind: str, year: int) -> str:
    selections = ",".join(dict.fromkeys(
        alias for aliases in RAW_COLUMNS.values() for alias in aliases
    ))
    req = urllib.request.Request(
        CUSTOM_URL.format(kind=kind, year=year, selections=selections),
        headers={"User-Agent": "Mozilla/5.0 (ValuCast snapshot fetch)"},
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return resp.read().decode("utf-8-sig")


def _parse(body: str) -> dict[str, dict[str, int]]:
    """mlbam_id -> {metric: percentile}; blank cells are dropped."""
    players: dict[str, dict[str, int]] = {}
    for row in csv.DictReader(io.StringIO(body)):
        mlbam = (row.get("player_id") or "").strip()
        if not mlbam:
            continue
        metrics: dict[str, int] = {}
        for key, value in row.items():
            if key in _SKIP_FIELDS or value is None or value.strip() == "":
                continue
            try:
                metrics[key] = int(float(value))
            except ValueError:
                continue
        if metrics:
            players[mlbam] = metrics
    return players


def _parse_raw(body: str) -> dict[str, dict[str, float]]:
    """mlbam_id -> raw metrics, using only headers present in the returned CSV."""
    rows = list(csv.DictReader(io.StringIO(body)))
    headers = set(rows[0].keys()) if rows else set()
    id_field = next((field for field in _ID_FIELDS if field in headers), None)
    # An alias can be a recognized header yet come back as an all-blank column
    # (e.g. fb_velocity on the custom endpoint) — prefer the first POPULATED one.
    def _populated(alias):
        return alias in headers and any((row.get(alias) or "").strip() for row in rows)
    selected = {
        metric: next((alias for alias in aliases if _populated(alias)), None)
        for metric, aliases in RAW_COLUMNS.items()
    }
    if not id_field:
        return {}

    players: dict[str, dict[str, float]] = {}
    for row in rows:
        mlbam = (row.get(id_field) or "").strip()
        if not mlbam:
            continue
        metrics = {}
        for metric, column in selected.items():
            value = (row.get(column) or "").strip() if column else ""
            if not value:
                continue
            try:
                metrics[metric] = float(value)
            except ValueError:
                continue
        if metrics:
            players[mlbam] = metrics
    return players


def _combine(
    percentiles: dict[str, dict[str, int]],
    raws: dict[str, dict[str, float]],
) -> dict[str, dict[str, dict]]:
    """Build artifact-v2 metric objects without inventing missing raw values."""
    combined = {}
    for mlbam, metrics in percentiles.items():
        player = {}
        raw_metrics = raws.get(mlbam, {})
        for metric, pct in metrics.items():
            value = {"pct": pct}
            if metric in raw_metrics:
                value["raw"] = raw_metrics[metric]
            player[metric] = value
        combined[mlbam] = player
    return combined


def main() -> int:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year

    batters_pct = _parse(_fetch_csv("batter", year))
    pitchers_pct = _parse(_fetch_csv("pitcher", year))
    batters_raw = _parse_raw(_fetch_custom_csv("batter", year))
    pitchers_raw = _parse_raw(_fetch_custom_csv("pitcher", year))
    batters = _combine(batters_pct, batters_raw)
    pitchers = _combine(pitchers_pct, pitchers_raw)
    if not batters or not pitchers:
        print(f"refusing to write: batters={len(batters)} pitchers={len(pitchers)}")
        return 1

    artifact = {
        "source": "Baseball Savant percentile rankings",
        "url": "https://baseballsavant.mlb.com/leaderboard/percentile-rankings",
        "year": year,
        "as_of": date.today().isoformat(),
        "batters": batters,
        "pitchers": pitchers,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(artifact, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT_PATH}: {len(batters)} batters, {len(pitchers)} pitchers (year {year})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
