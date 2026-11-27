"""Savant statcast_search batted-ball pull (Phase A). Per-ball EV/LA/outcome for
balls in play, keyed by batter (MLBAM id). Resumable, throttled, retrying."""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0"
SEARCH_URL = (
    "https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details"
    "&game_date_gt={start}&game_date_lt={end}"
)
THROTTLE_SECONDS = 2.0   # be polite to Savant between chunk requests


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_batted_balls(csv_text: str) -> list[dict]:
    """Rows with type=='X' (ball in play). EV/LA may be None (missing tracking).
    Returns {ev, la, events, batter, game_year}."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    out = []
    for row in reader:
        if row.get("type") != "X":   # only balls in play
            continue
        out.append({
            "ev": _to_float(row.get("launch_speed")),
            "la": _to_float(row.get("launch_angle")),
            "events": (row.get("events") or "").strip(),
            "batter": (row.get("batter") or "").strip(),
            "game_year": (row.get("game_date") or "")[:4],   # season tag for grouping
        })
    return out


def date_chunks(start: str, end: str, days: int = 5) -> list[tuple[str, str]]:
    """Inclusive [start,end] split into <=`days`-wide (start,end) windows.
    Sized under Savant's ~25k-row response cap."""
    from datetime import date, timedelta
    y1, m1, d1 = (int(x) for x in start.split("-"))
    y2, m2, d2 = (int(x) for x in end.split("-"))
    cur, last = date(y1, m1, d1), date(y2, m2, d2)
    out = []
    while cur <= last:
        chunk_end = min(cur + timedelta(days=days - 1), last)
        out.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return out


def _fetch_chunk(start: str, end: str) -> list[dict]:
    req = Request(SEARCH_URL.format(start=start, end=end), headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp:
        return parse_batted_balls(resp.read().decode("utf-8-sig", "replace"))


def pull_window(start: str, end: str, cache_dir: Path, days: int = 5,
                fetch=_fetch_chunk, max_retries: int = 3) -> int:
    """Pull all balls-in-play for [start,end] in chunks, caching each chunk to disk.
    Resumable: cached chunks are skipped. Throttled + retried. Returns chunk count."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks = date_chunks(start, end, days)
    for cstart, cend in chunks:
        path = cache_dir / f"{cstart}_{cend}.json"
        if path.exists():
            continue                       # resumable: already fetched
        last_err = None
        for attempt in range(max_retries):
            try:
                balls = fetch(cstart, cend)
                path.write_text(json.dumps(balls), encoding="utf-8")
                if fetch is _fetch_chunk:
                    time.sleep(THROTTLE_SECONDS)   # only throttle real network
                break
            except Exception as e:         # network/parse failure on this chunk
                last_err = e
                if fetch is _fetch_chunk:
                    time.sleep(THROTTLE_SECONDS * (attempt + 1))
        else:
            raise RuntimeError(f"chunk {cstart}..{cend} failed after {max_retries}: {last_err}")
    return len(chunks)


def load_cached_balls(cache_dir: Path) -> list[dict]:
    """Concatenate all cached chunk files into one ball list."""
    balls = []
    for path in sorted(cache_dir.glob("*.json")):
        balls.extend(json.loads(path.read_text(encoding="utf-8")))
    return balls
