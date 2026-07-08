"""Fetch historical MLB hitting seasons for the prospect comp pool.

One-time / occasional-refresh NETWORK script (never runs in the daily build):
pulls every MLB hitting season line 2000-2025 from the MLB statsapi, plus
bat-side for every player seen, and commits a compact cache the deterministic
comp builder reads offline. Committing the cache is load-bearing -- runtime
loaders must stay network-free (same policy as the FanGraphs snapshots).

Why ALL players and not just qualified ones: the comp cohort's OUTCOME
measurement needs the small follow-up seasons too (a 40-PA age-27 season is
the "faded out" signal, not noise to drop).

Run: python scripts/fetch_mlb_history_seasons.py
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "data" / "mlb" / "mlb_history_hitting_seasons.json"

SEASONS = range(2000, 2026)
BASE = "https://statsapi.mlb.com/api/v1"
PEOPLE_BATCH = 100


def _get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as response:
        return json.loads(response.read())


def fetch_season(season: int) -> list[dict]:
    url = (
        f"{BASE}/stats?stats=season&group=hitting&season={season}"
        f"&sportId=1&playerPool=All&limit=5000"
    )
    payload = _get(url)
    stats = (payload.get("stats") or [{}])[0]
    rows = []
    for split in stats.get("splits") or []:
        position = (split.get("position") or {}).get("abbreviation")
        if position == "P":
            continue
        stat = split.get("stat") or {}
        player = split.get("player") or {}
        try:
            pa = int(stat.get("plateAppearances") or 0)
        except (TypeError, ValueError):
            continue
        if pa < 1 or not player.get("id"):
            continue
        try:
            row = {
                "id": int(player["id"]),
                "name": player.get("fullName"),
                "season": season,
                "age": int(stat.get("age")) if stat.get("age") else None,
                "pos": position,
                "pa": pa,
                "so": int(stat.get("strikeOuts") or 0),
                "bb": int(stat.get("baseOnBalls") or 0),
                "hr": int(stat.get("homeRuns") or 0),
                "avg": float(stat.get("avg")),
                "obp": float(stat.get("obp")),
                "slg": float(stat.get("slg")),
            }
        except (TypeError, ValueError):
            continue
        rows.append(row)
    return rows


def fetch_bat_sides(player_ids: list[int]) -> dict[int, str]:
    sides: dict[int, str] = {}
    for start in range(0, len(player_ids), PEOPLE_BATCH):
        batch = player_ids[start:start + PEOPLE_BATCH]
        ids = ",".join(str(i) for i in batch)
        url = f"{BASE}/people?personIds={ids}&fields=people,id,batSide,code"
        payload = _get(url)
        for person in payload.get("people") or []:
            code = ((person.get("batSide") or {}).get("code") or "").strip()
            if person.get("id") and code:
                sides[int(person["id"])] = code
        time.sleep(0.2)
    return sides


def main() -> None:
    all_rows: list[dict] = []
    for season in SEASONS:
        rows = fetch_season(season)
        print(f"{season}: {len(rows)} hitter season lines")
        all_rows.extend(rows)
        time.sleep(0.3)

    player_ids = sorted({row["id"] for row in all_rows})
    print(f"fetching bat sides for {len(player_ids)} players...")
    sides = fetch_bat_sides(player_ids)
    for row in all_rows:
        row["bats"] = sides.get(row["id"])

    payload = {
        "artifact": "mlb_history_hitting_seasons",
        "source": "mlb_statsapi_season_hitting",
        "seasons": [min(SEASONS), max(SEASONS)],
        "note": (
            "Non-pitcher MLB hitting season lines incl. sub-qualified samples; "
            "committed cache, read offline by prospects/comps.py."
        ),
        "rows": all_rows,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, OUT_PATH)
    print(f"wrote {OUT_PATH} ({OUT_PATH.stat().st_size / 1e6:.1f} MB, {len(all_rows)} rows)")


if __name__ == "__main__":
    main()
