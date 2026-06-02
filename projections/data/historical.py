"""Immutable historical season snapshots (hitting) + manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from projections.constants import HISTORICAL_COUNTING
from scraper.mlb_actuals import fetch_actuals, normalize_hitter

SCHEMA_VERSION = 1


def normalize_season_rows(players: list[dict]) -> list[dict]:
    """Reduce engine-schema hitter dicts to bare counting rows keyed by mlbam_id."""
    rows = []
    for p in players:
        if p.get("pool") != "hitter":
            continue
        stats = p.get("stats", {})
        row = {"mlbam_id": p["metadata"]["mlbam_id"]}
        for key in HISTORICAL_COUNTING:
            row[key] = int(stats.get(key, 0))
        rows.append(row)
    return rows


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _season_path(season: int, data_dir: Path) -> Path:
    return data_dir / "historical" / f"hitting_{season}.json"


def store_season(season: int, rows: list[dict], data_dir: Path) -> None:
    """Write a season snapshot immutably. Identical re-pull is a no-op;
    a changed finalized season raises."""
    path = _season_path(season, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, indent=2, sort_keys=True)
    if path.exists():
        # Compare parsed content, not raw bytes: text-mode writes translate
        # newlines on Windows, so byte-hashes would never match a re-pull.
        if json.loads(path.read_text(encoding="utf-8")) == rows:
            return  # identical -> no-op
        raise ValueError(
            f"Refusing to overwrite finalized season {season}: content changed."
        )
    path.write_text(payload, encoding="utf-8")
    _update_manifest(season, rows, data_dir)


def _update_manifest(season: int, rows: list[dict], data_dir: Path) -> None:
    manifest_path = data_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[str(season)] = {
        "season": season,
        "row_count": len(rows),
        "schema_version": SCHEMA_VERSION,
        "content_sha256": hashlib.sha256(
            json.dumps(rows, indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def load_season(season: int, data_dir: Path) -> list[dict]:
    return json.loads(_season_path(season, data_dir).read_text(encoding="utf-8"))


def pull_season(season: int, data_dir: Path) -> int:
    """Fetch one season from MLB Stats API, normalize, store. Returns row count."""
    raw = fetch_actuals(season)
    players = [normalize_hitter(e, as_of=f"{season}-final") for e in raw["hitters"]]
    rows = normalize_season_rows(players)
    for r in rows:
        r["season"] = season
    store_season(season, rows, data_dir)
    return len(rows)
