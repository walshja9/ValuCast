"""Fetch the committed MLB pitcher-season pool used by prospect shape comps.

This is a one-time/occasional network script. Runtime and nightly card reads stay
offline against the committed compact cache.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.mlb_actuals import normalize_ip  # noqa: E402

OUT_PATH = ROOT / "data" / "mlb" / "mlb_history_pitching_seasons.json"
SEASONS = range(2000, 2026)
BASE = "https://statsapi.mlb.com/api/v1"


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())


def _number(value, cast=float):
    try:
        return cast(value or 0)
    except (TypeError, ValueError):
        return cast(0)


def fetch_season(season: int) -> list[dict]:
    url = (
        f"{BASE}/stats?stats=season&group=pitching&season={season}"
        "&sportId=1&playerPool=All&limit=5000"
    )
    payload = _get(url)
    rows = []
    for split in (payload.get("stats") or [{}])[0].get("splits") or []:
        player = split.get("player") or {}
        stat = split.get("stat") or {}
        if not player.get("id"):
            continue
        innings = round(normalize_ip(_number(stat.get("inningsPitched"))), 4)
        if innings <= 0:
            continue
        rows.append({
            "id": int(player["id"]),
            "name": player.get("fullName"),
            "season": season,
            "age": _number(stat.get("age"), int) or None,
            "ip": innings,
            "g": _number(stat.get("gamesPitched"), int),
            "gs": _number(stat.get("gamesStarted"), int),
            "bf": _number(stat.get("battersFaced"), int),
            "k": _number(stat.get("strikeOuts"), int),
            "bb": _number(stat.get("baseOnBalls"), int),
        })
    return rows


def main() -> None:
    rows = []
    for season in SEASONS:
        season_rows = fetch_season(season)
        print(f"{season}: {len(season_rows)} pitcher season lines")
        rows.extend(season_rows)
        time.sleep(0.3)
    payload = {
        "artifact": "mlb_history_pitching_seasons",
        "source": "mlb_statsapi_season_pitching",
        "seasons": [min(SEASONS), max(SEASONS)],
        "rows": rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT_PATH)
    print(f"wrote {OUT_PATH} ({len(rows)} rows)")


if __name__ == "__main__":
    main()
