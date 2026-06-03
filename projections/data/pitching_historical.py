"""Immutable historical pitcher snapshots. Normalizes pitcher rows itself from raw
MLB Stats API records (captures battersFaced/gamesFinished/HBP that the app's
normalize_pitcher omits) so scraper/mlb_actuals.py stays untouched."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scraper.mlb_actuals import fetch_actuals, fetch_qs, normalize_ip

SCHEMA_VERSION = 1


def normalize_pitching_rows(raw_pitchers: list[dict], qs_map: dict[str, int]) -> list[dict]:
    """Raw MLB API pitcher splits -> bare counting rows keyed by mlbam_id."""
    rows = []
    for entry in raw_pitchers:
        s = entry["stat"]
        mlbam_id = str(entry["player"]["id"])
        rows.append({
            "mlbam_id": mlbam_id,
            "BF": int(s.get("battersFaced", 0)),
            "IP": round(normalize_ip(float(s.get("inningsPitched", "0") or 0)), 4),
            "ER": int(s.get("earnedRuns", 0)),
            "H_ALLOWED": int(s.get("hits", 0)),
            "BB": int(s.get("baseOnBalls", 0)),
            "HBP": int(s.get("hitByPitch", 0)),
            "K": int(s.get("strikeOuts", 0)),
            "HR": int(s.get("homeRuns", 0)),
            "W": int(s.get("wins", 0)),
            "L": int(s.get("losses", 0)),
            "SV": int(s.get("saves", 0)),
            "HLD": int(s.get("holds", 0)),
            "GS": int(s.get("gamesStarted", 0)),
            "G": int(s.get("gamesPitched", 0)),
            "GF": int(s.get("gamesFinished", 0)),
            "QS": int(qs_map.get(mlbam_id, 0)),
        })
    return rows


def _season_path(season: int, data_dir: Path) -> Path:
    return data_dir / "pitching" / f"pitching_{season}.json"


def store_pitching_season(season: int, rows: list[dict], data_dir: Path) -> None:
    path = _season_path(season, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) == rows:
            return
        raise ValueError(f"Refusing to overwrite finalized pitching season {season}: content changed.")
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    _update_manifest(season, rows, data_dir)


def _update_manifest(season: int, rows: list[dict], data_dir: Path) -> None:
    mpath = data_dir / "pitching" / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    manifest[str(season)] = {
        "season": season, "row_count": len(rows), "schema_version": SCHEMA_VERSION,
        "content_sha256": hashlib.sha256(
            json.dumps(rows, indent=2, sort_keys=True).encode("utf-8")).hexdigest(),
    }
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def load_pitching_season(season: int, data_dir: Path) -> list[dict]:
    return json.loads(_season_path(season, data_dir).read_text(encoding="utf-8"))


def available_pitching_seasons(data_dir: Path) -> list[int]:
    p = data_dir / "pitching"
    if not p.exists():
        return []
    out = []
    for f in p.glob("pitching_*.json"):
        try:
            out.append(int(f.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(out)


def pull_pitching_season(season: int, data_dir: Path) -> int:
    """Fetch pitchers + derive QS (GS>0 only), normalize, store. Returns row count."""
    raw = fetch_actuals(season)
    pitchers = raw["pitchers"]
    qs_map = fetch_qs(pitchers, season)   # existing helper; GS==0 -> 0, GS>0 -> game-log QS
    rows = normalize_pitching_rows(pitchers, qs_map)
    for r in rows:
        r["season"] = season
    store_pitching_season(season, rows, data_dir)
    return len(rows)
