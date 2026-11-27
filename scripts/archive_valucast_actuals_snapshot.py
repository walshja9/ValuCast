#!/usr/bin/env python3
"""Archive ValuCast MLB actuals snapshots, with a scoped game-log backfill mode."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.mlb_actuals import build_historical_actuals  # noqa: E402

ACTUALS_PATH = ROOT / "data" / "actuals" / "current.json"
FREEZE_ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_mlb_projection_source_freeze"
SNAPSHOT_DIR = ROOT / "data" / "prediction_archive" / "valucast_actuals_snapshot"


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _snapshot_date(rows: list[dict]) -> str:
    for row in rows:
        as_of = (row.get("metadata") or {}).get("as_of")
        if as_of:
            return str(as_of)[:10]
    return date.today().isoformat()


def archive_actuals_snapshot(
    rows: list[dict],
    date_str: str,
    archive_dir: Path = SNAPSHOT_DIR,
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{date_str}.json"
    text = json.dumps(rows, indent=2, sort_keys=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def player_roles_from_freeze(freeze: dict) -> dict[str, str]:
    roles: dict[str, str] = {}
    for source in (freeze.get("sources") or {}).values():
        for mlbam_id, line in (source.get("rate_lines") or {}).items():
            role = "hitter" if (line.get("role") == "hitter") else "pitcher"
            roles.setdefault(str(mlbam_id), role)
    return roles


def archive_current_actuals_snapshot(
    actuals_path: Path = ACTUALS_PATH,
    archive_dir: Path = SNAPSHOT_DIR,
) -> dict:
    rows = _load_json(actuals_path)
    date_str = _snapshot_date(rows)
    path, changed = archive_actuals_snapshot(rows, date_str, archive_dir)
    return {"archive_path": str(path), "archive_changed": changed, "row_count": len(rows)}


def backfill_actuals_snapshot(
    as_of: str,
    *,
    season: int,
    freeze_path: Path,
    archive_dir: Path = SNAPSHOT_DIR,
    delay: float = 0.075,
) -> dict:
    freeze = _load_json(freeze_path)
    player_roles = player_roles_from_freeze(freeze)
    rows = build_historical_actuals(player_roles, season=season, as_of=as_of, delay=delay)
    path, changed = archive_actuals_snapshot(rows, as_of, archive_dir)
    return {"archive_path": str(path), "archive_changed": changed, "row_count": len(rows)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backfill-date", help="Reconstruct actuals as of YYYY-MM-DD.")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--freeze-path", type=Path)
    parser.add_argument("--delay", type=float, default=0.075)
    args = parser.parse_args()

    if args.backfill_date:
        freeze_path = args.freeze_path or FREEZE_ARCHIVE_DIR / f"{args.backfill_date}.json"
        result = backfill_actuals_snapshot(
            args.backfill_date,
            season=args.season,
            freeze_path=freeze_path,
            delay=args.delay,
        )
    else:
        result = archive_current_actuals_snapshot()

    print(
        "ValuCast actuals snapshot: "
        f"rows={result['row_count']} changed={result['archive_changed']} -> {result['archive_path']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
