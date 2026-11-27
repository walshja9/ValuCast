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
COVERAGE_FLOOR = 250    # raise if a season pull returns fewer rows than this
MIN_VALUE_SHARE = 0.8   # raise if fewer than this share of rows have usable xBA/xSLG

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


def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8-sig", "replace")  # utf-8-sig strips BOM


def merge_statcast(expected: dict[str, dict], quality: dict[str, dict]) -> list[dict]:
    """Join expected + quality by mlbam_id. Expected stats anchor the row;
    quality fields are added when present (observe-only)."""
    rows = []
    for pid, exp in expected.items():
        q = quality.get(pid, {})
        rows.append({"mlbam_id": pid, **exp,
                     "barrel_pct": q.get("barrel_pct"),
                     "avg_ev": q.get("avg_ev"),
                     "hardhit_pct": q.get("hardhit_pct"),
                     "launch_angle": q.get("launch_angle")})
    return rows


def assert_coverage(season: int, row_count: int) -> None:
    """Fail loud on undercoverage — a silent empty/partial pull would masquerade
    as 'classic fallback everywhere' and fake a tie."""
    if row_count < COVERAGE_FLOOR:
        raise ValueError(
            f"Statcast {season}: {row_count} rows < floor {COVERAGE_FLOOR}; "
            "refusing to store a likely broken pull."
        )


def assert_value_coverage(season: int, rows: list[dict]) -> None:
    """Fail loud on VALUE undercoverage. Row count alone misses a Savant schema
    drift where rows parse but xBA/xSLG come back None — that would silently turn
    the bridge into classic everywhere and fake a tie. Require enough rows with
    usable xBA AND xSLG (the bridge fields); barrel/EV are observe-only, not checked."""
    usable = sum(1 for r in rows
                 if r.get("xba") is not None and r.get("xslg") is not None)
    if usable < COVERAGE_FLOOR:
        raise ValueError(
            f"Statcast {season}: only {usable} rows have usable xBA/xSLG "
            f"< floor {COVERAGE_FLOOR}; likely schema drift in est_ba/est_slg."
        )
    share = usable / len(rows) if rows else 0.0
    if share < MIN_VALUE_SHARE:
        raise ValueError(
            f"Statcast {season}: only {share:.0%} of rows have xBA/xSLG "
            f"(< {MIN_VALUE_SHARE:.0%}); likely schema drift."
        )


def _season_path(season: int, data_dir: Path) -> Path:
    return data_dir / "statcast" / f"hitting_{season}.json"


def store_statcast_season(season: int, rows: list[dict], data_dir: Path) -> None:
    """Immutable per-season snapshot. Identical re-pull is a no-op; a changed
    finalized season raises (compares parsed content, not raw bytes — Windows
    newline-safe, same contract as the MLB backbone)."""
    path = _season_path(season, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) == rows:
            return
        raise ValueError(f"Refusing to overwrite Statcast season {season}: content changed.")
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    _update_manifest(season, rows, data_dir)


def _update_manifest(season: int, rows: list[dict], data_dir: Path) -> None:
    mpath = data_dir / "statcast" / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    manifest[str(season)] = {
        "season": season,
        "row_count": len(rows),
        "schema_version": SCHEMA_VERSION,
        "content_sha256": hashlib.sha256(
            json.dumps(rows, indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def load_statcast_season(season: int, data_dir: Path) -> dict[str, dict]:
    """{mlbam_id: statcast_row} for a season; empty dict if not pulled."""
    path = _season_path(season, data_dir)
    if not path.exists():
        return {}
    return {r["mlbam_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def pull_statcast_season(season: int, data_dir: Path) -> int:
    """Fetch both leaderboards, merge, coverage-check, store. Returns row count."""
    expected = parse_expected_stats(_fetch(EXPECTED_URL.format(year=season)))
    quality = parse_quality(_fetch(QUALITY_URL.format(year=season)))
    rows = merge_statcast(expected, quality)
    assert_coverage(season, len(rows))
    assert_value_coverage(season, rows)
    store_statcast_season(season, rows, data_dir)
    return len(rows)
