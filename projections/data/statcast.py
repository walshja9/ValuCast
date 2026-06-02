"""Baseball Savant Statcast snapshots (hitting): xBA/xSLG (the de-noising bridge)
plus barrel%/EV (observe-only). Immutable per-season snapshots, joined by MLBAM
id. Pulled once, never scraped at projection time."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0"
SCHEMA_VERSION = 1
COVERAGE_FLOOR = 250  # raise if a season pull returns fewer rows than this

EXPECTED_URL = (
    "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
    "?type=batter&year={year}&min=1&filterType=bip&csv=true"
)
QUALITY_URL = (
    "https://baseballsavant.mlb.com/leaderboard/statcast"
    "?type=batter&year={year}&min=1&csv=true"
)


def _to_float(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_expected_stats(csv_text: str) -> dict[str, dict]:
    """{mlbam_id: {xba, xslg, xwoba}} from the expected_statistics CSV.

    Savant prepends a UTF-8 BOM and quotes the combined "last_name, first_name"
    field; the BOM must be stripped or it sits before the opening quote and breaks
    the quoted-field parse. We lstrip defensively so the parser is correct whether
    or not the caller decoded with utf-8-sig.
    """
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    out: dict[str, dict] = {}
    for row in reader:
        pid = row.get("player_id")
        if not pid:
            continue
        out[pid] = {
            "xba": _to_float(row.get("est_ba")),
            "xslg": _to_float(row.get("est_slg")),
            "xwoba": _to_float(row.get("est_woba")),
        }
    return out


def parse_quality(csv_text: str) -> dict[str, dict]:
    """{mlbam_id: {barrel_pct, avg_ev, hardhit_pct, launch_angle}} (observe-only)."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    out: dict[str, dict] = {}
    for row in reader:
        pid = row.get("player_id")
        if not pid:
            continue
        out[pid] = {
            "barrel_pct": _to_float(row.get("brl_percent")),
            "avg_ev": _to_float(row.get("avg_hit_speed")),
            "hardhit_pct": _to_float(row.get("ev95percent")),
            "launch_angle": _to_float(row.get("avg_hit_angle")),
        }
    return out
