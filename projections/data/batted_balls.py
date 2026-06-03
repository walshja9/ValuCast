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
