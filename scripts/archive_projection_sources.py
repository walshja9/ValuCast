"""Weekly dated per-source ROS projection snapshots for the source-accuracy backtest.

Phase 3 of the model-core program (docs/model-core-program-2026-07-13.md): we
cannot prove ValuCast beats Steamer/ZiPS without matched archived vintages, and
today no per-source dated store exists -- ZiPS is averaged away at blend time
and the raw FanGraphs pulls are overwritten in place nightly. This step writes
one dated file per week holding all three sources at the SAME vintage, keyed by
mlbam_id, so a future backtest can score them against rest-of-season actuals on
identical dates. Additive: reads the H+P run and the raw pulls, serves nothing.

Weekly, not daily: day-over-day projections are near-perfectly autocorrelated,
so daily vintages add file size (~2 MB/snapshot) without statistical power.
"""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "projection_source_ros"
RAW_DIR = ROOT / "data" / "projections" / "raw"
METADATA_PATH = ROOT / "data" / "projections" / "metadata.json"
CADENCE_DAYS = 7
# Refuse to archive an obviously truncated source (normal: valucast ~2000,
# steamer ~10000 rows post-thin). ZiPS is exempt -- it legitimately shrinks to
# a partial pool midseason and its count is disclosed in the payload instead.
ARCHIVE_MIN_ROWS = 400

HITTER_KEEP = ("PA", "AB", "H", "HR", "R", "RBI", "SB", "BB", "SO", "AVG", "OBP", "SLG", "OPS")
PITCHER_KEEP = ("IP", "GS", "SO", "W", "L", "SV", "HLD", "QS", "ERA", "WHIP", "BB")


def _thin_rows(rows: list[dict]) -> dict:
    """Keep only what the future backtest can use: mlbam-joinable rows with
    nonzero projected volume, whitelisted stats, rounded. Dropped rows are
    counted, never silently discarded."""
    kept, no_mlbam, zero_volume = [], 0, 0
    for row in rows:
        metadata = row.get("metadata") or {}
        mlbam = str(metadata.get("mlbam_id") or row.get("mlbam_id") or "").strip()
        if not mlbam:
            no_mlbam += 1
            continue
        pool = str(row.get("pool") or "")
        stats = row.get("stats") or {}
        keep = HITTER_KEEP if pool == "hitter" else PITCHER_KEEP
        volume_key = "PA" if pool == "hitter" else "IP"
        try:
            volume = float(stats.get(volume_key) or 0.0)
        except (TypeError, ValueError):
            volume = 0.0
        if volume <= 0:
            zero_volume += 1
            continue
        thinned = {}
        for key in keep:
            value = stats.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                thinned[key] = round(float(value), 3)
        kept.append(
            {
                "mlbam_id": mlbam,
                "name": row.get("name") or "",
                "pool": pool,
                "stats": thinned,
            }
        )
    kept.sort(key=lambda r: (r["pool"], r["mlbam_id"]))
    return {"rows": kept, "dropped_no_mlbam": no_mlbam, "dropped_zero_volume": zero_volume}


def _load_raw(raw_dir: Path, name: str) -> list[dict]:
    path = raw_dir / f"{name}.json"
    if not path.exists():
        raise RuntimeError(
            f"raw projection pull missing: {path} -- refusing to archive a vintage "
            "without its source data (run scraper.refresh first)"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_vintage_block(raw_dir: Path, as_of: str) -> str | None:
    """Reason the raw pulls cannot honestly be archived under as_of, or None.

    Refuse a false vintage: raw pulls are NOT committed, so their mtime is a
    real local-write date (unlike committed files, where checkout fakes it).
    If the pulls were not written on the as_of date, archiving them under that
    date would lie about what the sources knew.

    Returns a SKIP REASON instead of raising: the steamer/zips pulls are
    manual, local-only artifacts (FanGraphs blocks CI fetches), so the nightly
    runner structurally never has them -- a hard error here killed the whole
    2026-07-14 public build. The archive is an observational side artifact;
    it must never take the public product down with it. Vintages get archived
    on whatever machine actually refreshes the raw pulls.
    """
    for name in ("steamer_hitters", "steamer_pitchers", "zips_hitters", "zips_pitchers"):
        path = raw_dir / f"{name}.json"
        if not path.exists():
            return (
                f"raw pull {name}.json not present (manual-refresh artifact; "
                "the CI runner never has raw pulls)"
            )
        written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date().isoformat()
        if written != as_of:
            return (
                f"raw pull {name}.json written {written} but archive as_of is {as_of} "
                "-- refusing to archive a stale pull under a fresh vintage"
            )
    return None


def _due(archive_dir: Path, as_of: str, cadence_days: int = CADENCE_DAYS) -> bool:
    if not archive_dir.exists():
        return True
    prior = [
        p.stem
        for p in archive_dir.glob("*.json")
        if len(p.stem) == 10 and p.stem < as_of
    ]
    if not prior:
        return True
    latest = max(prior)
    return (date.fromisoformat(as_of) - date.fromisoformat(latest)).days >= cadence_days


def _hp_run_path() -> Path:
    runs = sorted(_glob.glob(str(ROOT / "projections" / "runs" / "valucast_hp_*_v2" / "projections.json")))
    if not runs:
        raise RuntimeError("no ValuCast H+P run found under projections/runs/")
    return Path(runs[-1])


def build_archive_payload(
    *,
    as_of: str,
    season: int,
    valucast_rows: list[dict],
    steamer_rows: list[dict],
    zips_rows: list[dict],
    min_rows: int = ARCHIVE_MIN_ROWS,
) -> dict:
    sources = {
        "valucast_hp": _thin_rows(valucast_rows),
        "steamer": _thin_rows(steamer_rows),
        "zips": _thin_rows(zips_rows),
    }
    for name in ("valucast_hp", "steamer"):
        count = len(sources[name]["rows"])
        if count < min_rows:
            raise RuntimeError(
                f"source {name} has {count} archivable rows (< {min_rows}) -- "
                "refusing to archive a truncated vintage"
            )
    return {
        "as_of": as_of,
        "season": season,
        "scope": "rest_of_season",
        "cadence_days": CADENCE_DAYS,
        "join_key": "mlbam_id",
        "sources": {
            name: {
                "row_count": len(bundle["rows"]),
                "dropped_no_mlbam": bundle["dropped_no_mlbam"],
                "dropped_zero_volume": bundle["dropped_zero_volume"],
                "rows": bundle["rows"],
            }
            for name, bundle in sources.items()
        },
    }


def run_archive(
    *,
    archive_dir: Path = ARCHIVE_DIR,
    raw_dir: Path = RAW_DIR,
    metadata_path: Path = METADATA_PATH,
    hp_run_path: Path | None = None,
    min_rows: int = ARCHIVE_MIN_ROWS,
) -> dict:
    from scraper.blend import blend_hitters, blend_pitchers

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    as_of = str(metadata["as_of"])
    season = int(metadata.get("season") or 0)
    if not _due(archive_dir, as_of):
        return {"as_of": as_of, "skipped": True, "reason": f"within {CADENCE_DAYS}-day cadence"}
    block = _raw_vintage_block(raw_dir, as_of)
    if block:
        return {"as_of": as_of, "skipped": True, "reason": block}

    valucast_rows = json.loads((hp_run_path or _hp_run_path()).read_text(encoding="utf-8"))
    steamer_rows = blend_hitters(_load_raw(raw_dir, "steamer_hitters"), []) + blend_pitchers(
        _load_raw(raw_dir, "steamer_pitchers"), []
    )
    zips_rows = blend_hitters([], _load_raw(raw_dir, "zips_hitters")) + blend_pitchers(
        [], _load_raw(raw_dir, "zips_pitchers")
    )
    payload = build_archive_payload(
        as_of=as_of,
        season=season,
        valucast_rows=valucast_rows,
        steamer_rows=steamer_rows,
        zips_rows=zips_rows,
        min_rows=min_rows,
    )

    archive_dir.mkdir(parents=True, exist_ok=True)
    path = archive_dir / f"{as_of}.json"
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return {"as_of": as_of, "skipped": False, "archive_path": str(path), "changed": False}
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return {
        "as_of": as_of,
        "skipped": False,
        "archive_path": str(path),
        "changed": True,
        "row_counts": {name: bundle["row_count"] for name, bundle in payload["sources"].items()},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = run_archive()
    print(f"projection source archive: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
