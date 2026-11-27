"""Backfill per-pitcher season PITCH and STRIKE counts into the MiLB data layer.

OUT-OF-BAND (network) — NOT part of the network-free daily build. Run manually.

Wave A of the strike-percentage program. The pitcher season rows in the
walk-forward fold source (``valucast_universal_prospect_dataset.json``, cohorts
2014-2022) and the per-season current-era files (``milb_season_stats_20XX.json``,
2022-2026) carry innings/BF/K/BB but NO pitch or strike counts. MLB StatsAPI
season pitching splits expose ``numberOfPitches`` and ``strikes`` for affiliated
MiLB seasons all the way back through the fold era, so we fetch them once per
(season, sportId) and ADD ``pitches``/``strikes`` in place on the matching
pitcher rows.

STRICTLY ADDITIVE: existing rows/fields are left byte-identical; only the two new
count fields are added, and only to pitcher rows whose (mlbam_id, season, level)
was actually served by the API. Rows the API does not cover are left WITHOUT the
fields — never zero-filled — so a partial pull is honestly recorded in the data.

Source: statsapi.mlb.com /api/v1/stats?stats=season (one request per
season x sportId, pitching group), mirroring build_historical_by_level_lines.py.
Progress is checkpointed to a scratch sidecar keyed by (fetch cell) so an
interrupted run resumes instead of re-pulling completed seasons. Writes are
atomic (temp file + os.replace) and preserve each file's exact on-disk format.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "prospects" / "raw"
UNIVERSE_PATH = RAW_DIR / "valucast_universal_prospect_dataset.json"

# sportId -> level label (affiliated MiLB full-season + short-season/rookie).
SPORT_LEVELS = {11: "AAA", 12: "AA", 13: "A+", 14: "A", 16: "R"}
API = "https://statsapi.mlb.com/api/v1/stats"
REQUEST_DELAY_SECONDS = 1.0  # polite pacing, matches the by-level backfill's style

# Default the resume checkpoint OUTSIDE the repo (system temp, or VALUCAST_SCRATCH
# if set) so an operator running without --checkpoint never drops a stray file
# into data/prospects/raw that the nightly's blanket `git add` could sweep in.
DEFAULT_CHECKPOINT = (
    Path(os.environ.get("VALUCAST_SCRATCH", tempfile.gettempdir()))
    / "valucast_backfill_pitch_counts_ckpt.json"
)


def _per_season_paths() -> list[Path]:
    return sorted(RAW_DIR.glob("milb_season_stats_[0-9][0-9][0-9][0-9].json"))


def _fetch_pitching_splits(season: int, sport_id: int) -> list[dict]:
    url = (
        f"{API}?stats=season&season={season}&sportId={sport_id}"
        f"&group=pitching&playerPool=all&limit=5000"
    )
    request = urllib.request.Request(
        url, headers={"User-Agent": "ValuCast MiLB pitch-count backfill"}
    )
    last_exc: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=40) as resp:
                payload = json.load(resp)
            return (payload.get("stats") or [{}])[0].get("splits") or []
        except Exception as exc:  # noqa: BLE001 - bounded retry on a one-off pull
            last_exc = exc
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"unreachable fetch state: {last_exc}")


def _counts_from_splits(splits: list[dict]) -> dict[int, dict[str, int]]:
    """Map mlbam_id -> {'pitches','strikes'} for splits that served both counts.

    A split missing either count is skipped entirely (never zero-filled), so a
    downstream row only gets the fields when the API genuinely had them.
    """
    out: dict[int, dict[str, int]] = {}
    for split in splits:
        pid = (split.get("player") or {}).get("id")
        stat = split.get("stat") or {}
        pitches = stat.get("numberOfPitches")
        strikes = stat.get("strikes")
        if pid is None or pitches in (None, "") or strikes in (None, ""):
            continue
        out[int(pid)] = {"pitches": int(pitches), "strikes": int(strikes)}
    return out


def _load_checkpoint(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data.get("completed_files") or [])


def _save_checkpoint(path: Path, files: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps({"completed_files": sorted(files)}, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def _detect_format(raw: bytes) -> dict:
    """Detect the exact on-disk serialization so untouched bytes stay identical."""
    text = raw.decode("utf-8")
    crlf = "\r\n" in text
    trailing_newline = text.endswith("\r\n") or text.endswith("\n")
    # Indented pretty-print (per-season files) vs single-line default (universe).
    indent = 2 if ("\n  " in text or "\r\n  " in text) else None
    return {"indent": indent, "crlf": crlf, "trailing_newline": trailing_newline}


def _serialize(payload: dict, fmt: dict) -> bytes:
    if fmt["indent"] is None:
        body = json.dumps(payload)
    else:
        body = json.dumps(payload, indent=fmt["indent"], sort_keys=True)
    if fmt["trailing_newline"]:
        body += "\n"
    if fmt["crlf"]:
        body = body.replace("\n", "\r\n")
    return body.encode("utf-8")


def _atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _universe_pitcher_rows(payload: dict) -> list[dict]:
    return [r for r in payload.get("rows", []) if r.get("role") == "pitcher"]


def _apply_universe(
    payload: dict, counts_by_cell: dict[tuple[int, int], dict[int, dict]]
) -> int:
    """Add pitches/strikes to universe pitcher rows, keyed by (cohort_year, sport_id).

    counts_by_cell[(season, sport_id)][mlbam_id] = {'pitches','strikes'}.
    """
    added = 0
    for row in _universe_pitcher_rows(payload):
        mid, season, sport_id = (
            row.get("mlbam_id"),
            row.get("cohort_year"),
            row.get("sport_id"),
        )
        if mid is None or season is None or sport_id is None:
            continue
        cell = counts_by_cell.get((int(season), int(sport_id)))
        if not cell:
            continue
        found = cell.get(int(mid))
        if not found:
            continue
        row["pitches"] = found["pitches"]
        row["strikes"] = found["strikes"]
        added += 1
    return added


def _apply_per_season(
    payload: dict, counts_by_cell: dict[tuple[int, int], dict[int, dict]]
) -> int:
    """Add pitches/strikes to a per-season file's pitcher rows, keyed by (season, sport_id)."""
    season = payload.get("season")
    added = 0
    for row in payload.get("pitchers", []):
        mid, sport_id = row.get("mlbam_id"), row.get("sport_id")
        if mid is None or sport_id is None or season is None:
            continue
        cell = counts_by_cell.get((int(season), int(sport_id)))
        if not cell:
            continue
        found = cell.get(int(mid))
        if not found:
            continue
        row["pitches"] = found["pitches"]
        row["strikes"] = found["strikes"]
        added += 1
    return added


def _seasons_and_sports_for_universe(payload: dict) -> dict[int, set[int]]:
    want: dict[int, set[int]] = {}
    for row in _universe_pitcher_rows(payload):
        season, sport_id = row.get("cohort_year"), row.get("sport_id")
        if season is None or sport_id is None:
            continue
        want.setdefault(int(season), set()).add(int(sport_id))
    return want


def _seasons_and_sports_for_per_season(payload: dict) -> dict[int, set[int]]:
    season = payload.get("season")
    if season is None:
        return {}
    sports = {
        int(r["sport_id"])
        for r in payload.get("pitchers", [])
        if r.get("sport_id") is not None
    }
    return {int(season): sports} if sports else {}


def _coverage(payload: dict, source: str) -> dict:
    """Per-season (rows_with_counts, total) for honest coverage reporting."""
    rows = (
        _universe_pitcher_rows(payload)
        if source == "universe"
        else payload.get("pitchers", [])
    )
    per_season: dict[int, list[int]] = {}
    for row in rows:
        season = row.get("cohort_year") if source == "universe" else payload.get("season")
        if season is None:
            continue
        bucket = per_season.setdefault(int(season), [0, 0])
        bucket[1] += 1
        if "pitches" in row and "strikes" in row:
            bucket[0] += 1
    return {season: {"with_counts": v[0], "total": v[1]} for season, v in per_season.items()}


def _process_file(
    path: Path,
    source: str,
    fetch_cache: dict[tuple[int, int], dict[int, dict]],
    delay: float,
) -> dict:
    raw = path.read_bytes()
    fmt = _detect_format(raw)
    payload = json.loads(raw)

    if source == "universe":
        want = _seasons_and_sports_for_universe(payload)
    else:
        want = _seasons_and_sports_for_per_season(payload)

    # One StatsAPI request per (season, sportId), shared across every file that
    # needs that cell (the universe and a per-season file both touch e.g. 2022 A).
    for season in sorted(want):
        for sport_id in sorted(want[season]):
            key = (season, sport_id)
            if key in fetch_cache:
                continue
            if sport_id not in SPORT_LEVELS:
                fetch_cache[key] = {}
                continue
            splits = _fetch_pitching_splits(season, sport_id)
            fetch_cache[key] = _counts_from_splits(splits)
            print(
                f"  fetched season={season} {SPORT_LEVELS[sport_id]}: "
                f"{len(fetch_cache[key])} pitcher seasons with counts"
            )
            if delay:
                time.sleep(delay)

    if source == "universe":
        added = _apply_universe(payload, fetch_cache)
    else:
        added = _apply_per_season(payload, fetch_cache)

    _atomic_write(path, _serialize(payload, fmt))
    coverage = _coverage(payload, source)
    print(f"  wrote {path.name}: added counts to {added} pitcher rows")
    return {"path": str(path), "added": added, "coverage": coverage}


def run_backfill(
    *,
    include_universe: bool = True,
    include_per_season: bool = True,
    checkpoint_path: Path = DEFAULT_CHECKPOINT,
    delay: float = REQUEST_DELAY_SECONDS,
) -> dict:
    completed = _load_checkpoint(checkpoint_path)
    fetch_cache: dict[tuple[int, int], dict[int, dict]] = {}
    results: list[dict] = []

    targets: list[tuple[Path, str]] = []
    if include_universe and UNIVERSE_PATH.exists():
        targets.append((UNIVERSE_PATH, "universe"))
    if include_per_season:
        targets.extend((p, "per_season") for p in _per_season_paths())

    for path, source in targets:
        if str(path) in completed:
            print(f"skipping {path.name} (checkpoint: already backfilled)")
            continue
        print(f"processing {source}: {path.name}")
        results.append(_process_file(path, source, fetch_cache, delay))
        # File written atomically; record it so an interrupted run resumes here.
        completed.add(str(path))
        _save_checkpoint(checkpoint_path, completed)
    return {"results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-universe", action="store_true", help="skip the fold-era universe file")
    parser.add_argument("--no-per-season", action="store_true", help="skip the per-season files")
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_SECONDS)
    args = parser.parse_args()

    summary = run_backfill(
        include_universe=not args.no_universe,
        include_per_season=not args.no_per_season,
        checkpoint_path=args.checkpoint,
        delay=args.delay,
    )
    print("\n=== coverage (pitcher rows with pitch/strike counts vs total) ===")
    for result in summary["results"]:
        name = Path(result["path"]).name
        for season in sorted(result["coverage"]):
            cov = result["coverage"][season]
            print(f"  {name} {season}: {cov['with_counts']}/{cov['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
