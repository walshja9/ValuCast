"""Fetch AAA pitch-level Statcast from Baseball Savant into a compact game cache.

This script owns ALL network + file I/O for the AAA-Statcast layer (the aggregation
in scripts/build_aaa_statcast_features.py is pure). It mirrors
scripts/fetch_statcast_percentiles.py's Savant idioms (User-Agent Request, timeout,
utf-8-sig BOM decode, bounded retry/backoff) and
scripts/build_pitch_discipline.py's cache posture (immutable finished games keyed so
a cached game is NEVER re-fetched, checkpoint flushes, incremental budget/no-op).

The Savant minors CSV endpoint (verified live 7/14):
  * ONE game_date per request (game_date_gt == game_date_lt). A wider window silently
    truncates at a HARD 25,000-row cap, so we fetch strictly one day at a time.
  * NO server-side level filter exists (minors_type/level/sport_id are ignored); the
    CSV mixes AAA with 10 Florida State League (Single-A) parks. We fetch the AAA
    abbreviation set from StatsAPI once and keep only rows whose home_team is AAA.
  * pitcher/batter columns ARE mlbam ids -> everything is keyed by mlbam id as str.
  * bat_speed / swing_length are 0%-populated at AAA (MLB-only) and are never stored.

Two modes:
  --backfill   season-wide, checkpointed/resumable: fetch every game_date from the
               season opener through today, extract the compact per-pitch slice, flush
               the cache periodically. A cached game_pk is NEVER re-fetched (a final
               game is immutable), so a re-run resumes for free.
  (default)    incremental: fetch only game_dates AFTER the cache's max date, with a
               new-date budget cap, and no-op gracefully (keep the stale artifact +
               cache, exit 0) on any HTTP error so a bad-fetch morning never stalls
               the daily build.

OBSERVE-ONLY: the artifact this cache feeds is display context, never a value input.
The compact per-pitch slice (never raw Savant rows) is what gets cached; the cache is
rebuildable and is NEVER committed (see .gitignore).
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- Paths -----------------------------------------------------------------
CACHE_PATH = ROOT / "data" / "prospects" / "raw" / "aaa_statcast_pitch_cache.json"
# Written by the aaa-statcast-bootstrap workflow ONLY after a complete --backfill
# succeeds (mirrors build_pitch_discipline.READY_MARKER_PATH). Incremental runs
# refuse to fetch without it: a partial cache (e.g. saved by a timed-out
# bootstrap's if:always() checkpoint) would otherwise let the downstream feature
# build emit a deceptively fresh artifact from incomplete season data.
READY_MARKER_PATH = ROOT / "data" / "prospects" / "raw" / ".aaa_statcast_cache_ready"

# --- Savant / StatsAPI ------------------------------------------------------
_SAVANT_CSV = (
    "https://baseballsavant.mlb.com/statcast-search-minors/csv?all=true&type=details"
    "&minors=true&game_date_gt={day}&game_date_lt={day}&player_type=pitcher"
)
_AAA_TEAMS_URL = "https://statsapi.mlb.com/api/v1/teams?sportId=11&season={season}"
_USER_AGENT = "Mozilla/5.0 (ValuCast AAA statcast fetch)"
_TIMEOUT = 60
_RATE_LIMIT_SECONDS = 0.15
_FLUSH_EVERY = 25

# AAA seasons open in late March / early April; a fixed early anchor is safe because
# the endpoint returns 0 rows for empty days (skipped without caching).
_SEASON_START_MONTH_DAY = (3, 20)

# Incremental-mode safety budget: more than this many NEW game_dates since the cache
# max aborts before any fetch (a cold/stale cache must never turn the daily increment
# into a full-season backfill inside the publish job — the plan-023 posture).
_INCREMENTAL_NEW_DATE_BUDGET = 14

# The compact per-pitch fields we keep. Everything else in the 119-column CSV is
# dropped. bat_speed / swing_length are deliberately absent (0%-populated at AAA).
_PITCH_FIELDS = (
    "pitcher", "batter", "pitch_type", "release_speed", "pfx_x", "pfx_z",
    "release_spin_rate", "release_extension", "spin_axis", "arm_angle",
    "plate_x", "plate_z", "sz_top", "sz_bot", "description",
    "type", "events", "bb_type", "launch_speed", "launch_angle",
)
_FLOAT_FIELDS = frozenset({
    "release_speed", "pfx_x", "pfx_z", "release_spin_rate", "release_extension",
    "spin_axis", "arm_angle", "plate_x", "plate_z", "sz_top", "sz_bot",
    "launch_speed", "launch_angle",
})
_STR_FIELDS = frozenset({
    "pitcher", "batter", "pitch_type", "description", "type", "events", "bb_type",
})


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
def _read_with_retry(url: str, attempts: int = 3) -> str:
    """Bounded retry with backoff -- one transient blip must not abort the run
    (mirrors fetch_statcast_percentiles._read_with_retry)."""
    from urllib.error import HTTPError, URLError

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
                return resp.read().decode("utf-8-sig")
        except HTTPError as exc:
            if exc.code < 500 and exc.code != 429:
                raise
            last = exc
        except (URLError, TimeoutError, OSError) as exc:
            last = exc
        if attempt < attempts - 1:
            time.sleep(2 * (attempt + 1))
    assert last is not None
    raise last


def fetch_aaa_abbreviations(season: int) -> set[str]:
    """AAA team abbreviations from StatsAPI (sportId 11) -- the client-side level
    filter. Savant ignores level params, so this set is the ONLY thing separating
    AAA rows from the Florida State League Single-A parks in the same CSV."""
    body = _read_with_retry(_AAA_TEAMS_URL.format(season=season))
    data = json.loads(body)
    abbrs = {
        (t.get("abbreviation") or "").strip()
        for t in (data.get("teams") or [])
    }
    return {a for a in abbrs if a}


def fetch_day_rows(day: str, aaa_abbrevs: set[str]) -> list[dict]:
    """Fetch one game_date's minors CSV and return AAA-only rows.

    One request == one game_date (the 25k-row cap makes wider windows unsafe). Rows
    are filtered to AAA by home_team membership in the StatsAPI abbreviation set.
    """
    body = _read_with_retry(_SAVANT_CSV.format(day=day))
    rows = []
    for row in csv.DictReader(io.StringIO(body)):
        if (row.get("home_team") or "").strip() in aaa_abbrevs:
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Compact slice
# ---------------------------------------------------------------------------
def _compact_pitch(row: dict) -> dict:
    """Extract ONLY the fields the aggregator needs from a raw Savant row."""
    out: dict = {}
    for field in _PITCH_FIELDS:
        value = row.get(field)
        text = value.strip() if isinstance(value, str) else value
        if text in (None, ""):
            out[field] = None
            continue
        if field in _FLOAT_FIELDS:
            try:
                out[field] = float(text)
            except (TypeError, ValueError):
                out[field] = None
        else:
            out[field] = str(text)
    return out


def rows_to_games(rows: list[dict]) -> dict[str, dict]:
    """Group AAA rows into per-game compact slices keyed by game_pk (as str)."""
    games: dict[str, dict] = {}
    for row in rows:
        pk = (row.get("game_pk") or "").strip()
        if not pk:
            continue
        game = games.setdefault(
            pk,
            {
                "home_team": (row.get("home_team") or "").strip() or None,
                "game_date": (row.get("game_date") or "").strip() or None,
                "pitches": [],
            },
        )
        game["pitches"].append(_compact_pitch(row))
    return games


# ---------------------------------------------------------------------------
# Cache I/O (atomic)
# ---------------------------------------------------------------------------
def load_cache(path: Path = CACHE_PATH) -> dict:
    """Cache shape: {"games": {"<game_pk>": {home_team, game_date, season, pitches}}}."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"games": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), dict):
        return {"games": {}}
    return payload


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, path)


def flush_cache(cache: dict, path: Path = CACHE_PATH) -> None:
    _atomic_write(path, cache)


def cache_max_date(cache: dict) -> str | None:
    """The latest game_date present in the cache (ISO str), or None when empty."""
    dates = [
        g.get("game_date")
        for g in (cache.get("games") or {}).values()
        if isinstance(g.get("game_date"), str) and g.get("game_date")
    ]
    return max(dates) if dates else None


# ---------------------------------------------------------------------------
# Date planning
# ---------------------------------------------------------------------------
def _iso(d: date) -> str:
    return d.isoformat()


def season_dates(season: int, *, through: date | None = None) -> list[str]:
    """Every game_date from the season opener anchor through `through` (default today)."""
    start = date(season, *_SEASON_START_MONTH_DAY)
    end = through or date.today()
    if end < start:
        return []
    out = []
    cur = start
    while cur <= end:
        out.append(_iso(cur))
        cur += timedelta(days=1)
    return out


def incremental_dates(cache: dict, season: int, *, through: date | None = None) -> list[str]:
    """Game_dates strictly AFTER the cache's max date, through today.

    Cold cache (no dates) returns [] -- an empty cache in incremental mode must not
    become a full backfill inside the daily job (the caller no-ops on that).
    """
    max_date = cache_max_date(cache)
    if not max_date:
        return []
    try:
        start = date.fromisoformat(max_date) + timedelta(days=1)
    except ValueError:
        return []
    end = through or date.today()
    out = []
    cur = start
    while cur <= end:
        out.append(_iso(cur))
        cur += timedelta(days=1)
    return out


# ---------------------------------------------------------------------------
# Fetch driver
# ---------------------------------------------------------------------------
def gather_days(
    days: list[str],
    season: int,
    cache: dict,
    aaa_abbrevs: set[str],
    *,
    limit_days: int | None = None,
) -> dict:
    """Fetch each game_date, caching any NEW game_pks it contains. Returns stats.

    A game_pk already in the cache is never re-fetched-into: a finished game is
    immutable, so we keep the first cached slice and never overwrite it. Empty days
    (0 AAA rows) are skipped without caching. Checkpoint-flush every _FLUSH_EVERY days
    so an interrupted backfill resumes from partial progress.
    """
    games = cache.setdefault("games", {})
    stats = {
        "days_fetched": 0, "days_empty": 0,
        "new_games": 0, "skipped_games": 0, "pitches_added": 0,
        "cached_total": len(games),
    }
    for idx, day in enumerate(days):
        if limit_days is not None and stats["days_fetched"] >= limit_days:
            break
        day_rows = fetch_day_rows(day, aaa_abbrevs)
        time.sleep(_RATE_LIMIT_SECONDS)
        stats["days_fetched"] += 1
        if not day_rows:
            stats["days_empty"] += 1
            continue
        for pk, game in rows_to_games(day_rows).items():
            if pk in games:
                # Immutable finished game: never overwrite a cached slice.
                stats["skipped_games"] += 1
                continue
            game["season"] = season
            games[pk] = game
            stats["new_games"] += 1
            stats["pitches_added"] += len(game.get("pitches") or ())
        if (idx + 1) % _FLUSH_EVERY == 0:
            flush_cache(cache)
            print(
                f"  ... {idx + 1}/{len(days)} days, cached {len(games)} games "
                f"({stats['new_games']} new)",
                flush=True,
            )
    stats["cached_total"] = len(games)
    return stats


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=date.today().year)
    parser.add_argument("--backfill", action="store_true",
                        help="Season-wide checkpointed backfill (resumable).")
    parser.add_argument("--date", action="append",
                        help="Fetch specific game_date(s) YYYY-MM-DD (dev smoke).")
    parser.add_argument("--limit-days", type=int, default=None,
                        help="Cap total day fetches (dev smoke).")
    parser.add_argument("--through", default=None,
                        help="Upper game_date bound YYYY-MM-DD (default today).")
    args = parser.parse_args(argv)

    through = date.fromisoformat(args.through) if args.through else None
    cache = load_cache()
    incremental = not args.backfill and not args.date

    if incremental and not READY_MARKER_PATH.exists():
        # Readiness guard (mirrors build_pitch_discipline.py): without the marker
        # the cache is absent OR a partial checkpoint from an interrupted
        # bootstrap. Either way an incremental fetch + downstream rebuild would
        # produce a deceptively fresh artifact from incomplete season data —
        # keep the prior artifact instead. If bootstrap recovery stalls,
        # validate_aaa_statcast_features.py fails the publish closed.
        print(
            "AAA statcast cache not marked ready; skipping incremental fetch, "
            "keeping prior artifact (aaa-statcast-bootstrap workflow owns "
            "--backfill and writes the marker on completion)",
            flush=True,
        )
        return 0

    # AAA abbreviations are a StatsAPI fetch; a failure to obtain them means we cannot
    # safely filter, so fail-soft (keep stale cache/artifact) in incremental mode.
    try:
        aaa_abbrevs = fetch_aaa_abbreviations(args.season)
    except Exception as exc:  # noqa: BLE001
        if not incremental:
            raise
        print(f"AAA team fetch failed, keeping stale cache: {exc}", flush=True)
        return 0
    if not aaa_abbrevs:
        if not incremental:
            print("no AAA abbreviations resolved; aborting", flush=True)
            return 1
        print("no AAA abbreviations resolved; keeping stale cache", flush=True)
        return 0

    if args.date:
        days = list(dict.fromkeys(args.date))
    elif args.backfill:
        days = season_dates(args.season, through=through)
    else:
        days = incremental_dates(cache, args.season, through=through)
        if not days and not cache_max_date(cache):
            print(
                "empty AAA statcast cache; skipping incremental fetch "
                "(cold cache -- run --backfill manually to rebuild)",
                flush=True,
            )
            return 0
        if len(days) > _INCREMENTAL_NEW_DATE_BUDGET:
            print(
                f"incremental new-date budget exceeded ({len(days)} > "
                f"{_INCREMENTAL_NEW_DATE_BUDGET}); skipping fetch, keeping stale cache "
                "(stale cache -- run --backfill manually to catch up)",
                flush=True,
            )
            return 0

    if not days:
        print("no new game-dates to fetch; cache is current", flush=True)
        return 0

    try:
        stats = gather_days(
            days, args.season, cache, aaa_abbrevs, limit_days=args.limit_days
        )
    except Exception as exc:  # noqa: BLE001
        if not incremental:
            raise
        # Fail-soft: keep whatever partial progress flushed, leave the artifact
        # untouched, exit 0 so the daily build continues.
        flush_cache(cache)
        print(f"AAA statcast incremental fetch failed, keeping stale cache: {exc}",
              flush=True)
        return 0

    flush_cache(cache)
    print(
        f"days_fetched={stats['days_fetched']} days_empty={stats['days_empty']} "
        f"new_games={stats['new_games']} skipped_games={stats['skipped_games']} "
        f"pitches_added={stats['pitches_added']} cached_total={stats['cached_total']} "
        f"(generated_at {datetime.now(timezone.utc).isoformat()})",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
