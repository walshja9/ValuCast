"""Fetch Baseball Savant percentile rankings into a committed snapshot artifact.

Snapshot model (same as data/projections): this script is run MANUALLY on a dev
machine and the resulting data/statcast/percentiles.json is committed. The web
app never fetches Savant at runtime — it only reads the committed artifact.

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
OUT_PATH = Path(__file__).parent.parent / "data" / "statcast" / "percentiles.json"
_TIMEOUT = 30
_SKIP_FIELDS = {"player_name", "player_id", "year"}


def _fetch_csv(kind: str, year: int) -> str:
    req = urllib.request.Request(
        URL.format(kind=kind, year=year),
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


def main() -> int:
    year = int(sys.argv[1]) if len(sys.argv) > 1 else date.today().year

    batters = _parse(_fetch_csv("batter", year))
    pitchers = _parse(_fetch_csv("pitcher", year))
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
