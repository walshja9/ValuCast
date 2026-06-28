"""Refresh slim MiLB card history from bulk season leaderboard caches."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.refresh_milb_season_stats import (
    RAW_DIR,
    _normalize_name,
    build_milb_season_stats,
    write_milb_season_stats,
)

CARD_HISTORY_PATH = RAW_DIR / "milb_card_history.json"
UNIVERSE_PATH = ROOT / "data" / "models" / "valucast_prospect_universe.json"

LEVELS = {"A", "A+", "AA", "AAA"}
LEVEL_RANK = {"AAA": 4, "AA": 3, "A+": 2, "A": 1}

HITTER_FIELDS = (
    "age",
    "avg",
    "bb_pct",
    "home_runs",
    "iso",
    "k_pct",
    "level",
    "mlbam_id",
    "obp",
    "plate_appearances",
    "role",
    "season",
    "slg",
    "stolen_bases",
    "team",
)

PITCHER_FIELDS = (
    "age",
    "bb_per_9",
    "era",
    "games_started",
    "innings_pitched",
    "is_starter",
    "k_bb_pct",
    "k_per_9",
    "level",
    "mlbam_id",
    "role",
    "season",
    "team",
    "whip",
)


def season_cache_path(season: int) -> Path:
    return RAW_DIR / f"milb_season_stats_{season}.json"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _season(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _universe_names(universe_payload: dict) -> set[str]:
    names: set[str] = set()
    for player in universe_payload.get("players") or []:
        if not isinstance(player, dict):
            continue
        name = player.get("normalized_name") or _normalize_name(player.get("name"))
        if name:
            names.add(name)
    return names


def _row_name(row: dict) -> str:
    return row.get("normalized_name") or _normalize_name(row.get("name"))


def _slim_row(row: dict, season: int | None) -> dict:
    fields = HITTER_FIELDS if row.get("role") == "hitter" else PITCHER_FIELDS
    slim = {field: row.get(field) for field in fields}
    slim["season"] = season
    return slim


def build_card_history(
    season_payloads: Iterable[dict],
    universe_payload: dict,
) -> dict:
    universe = _universe_names(universe_payload)
    players: dict[str, list[dict]] = {}

    for payload in season_payloads:
        season = _season(payload.get("season"))
        for group in ("hitters", "pitchers"):
            for row in payload.get(group) or []:
                if not isinstance(row, dict):
                    continue
                name = _row_name(row)
                if (
                    not name
                    or name not in universe
                    or row.get("level") not in LEVELS
                    or row.get("role") not in {"hitter", "pitcher"}
                    or row.get("mlbam_id") in (None, "")
                ):
                    continue
                players.setdefault(name, []).append(_slim_row(row, season))

    for rows in players.values():
        rows.sort(
            key=lambda row: (
                _season(row.get("season")) or 0,
                LEVEL_RANK.get(row.get("level"), 0),
            ),
            reverse=True,
        )

    players = {name: players[name] for name in sorted(players)}
    return {
        "_meta": {"artifact": "milb_card_history", "players": len(players)},
        "players": players,
    }


def card_history_bytes(payload: dict) -> bytes:
    return json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
        ensure_ascii=False,
    ).encode("utf-8")


def write_card_history(payload: dict, path: Path = CARD_HISTORY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(card_history_bytes(payload))
    os.replace(tmp, path)
    return path


def refresh_season_caches(
    start_season: int,
    end_season: int,
    *,
    current_year: int | None = None,
) -> list[Path]:
    current_year = current_year or date.today().year
    paths: list[Path] = []
    for season in range(start_season, end_season + 1):
        path = season_cache_path(season)
        if path.exists() and season < current_year:
            paths.append(path)
            continue
        payload = build_milb_season_stats(season=season)
        paths.append(write_milb_season_stats(payload, path))
    return paths


def load_season_payloads(raw_dir: Path = RAW_DIR) -> list[dict]:
    return [_json(path) for path in sorted(raw_dir.glob("milb_season_stats_*.json"))]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-season", type=int, default=2022)
    parser.add_argument("--end-season", type=int, default=date.today().year)
    args = parser.parse_args()
    if args.start_season > args.end_season:
        parser.error("--start-season must be <= --end-season")

    refresh_season_caches(args.start_season, args.end_season)
    artifact = build_card_history(load_season_payloads(), _json(UNIVERSE_PATH))
    path = write_card_history(artifact)
    print(f"milb_card_history: players={artifact['_meta']['players']} -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
