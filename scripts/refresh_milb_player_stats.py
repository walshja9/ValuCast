"""Refresh one player's current MiLB stat row from the official MiLB player page."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "prospects" / "raw"
CURRENT_STATS_PATH = RAW_DIR / "milb_season_stats.json"


def _normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "-.--"):
        return default
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    numeric = _number(value)
    return default if numeric is None else int(round(numeric))


def _rate(value: Any, digits: int = 3) -> float | None:
    numeric = _number(value)
    return None if numeric is None else round(numeric, digits)


def _fetch_player_page(mlbam_id: int) -> str:
    request = urllib.request.Request(
        f"https://www.milb.com/player/{mlbam_id}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        return response.read().decode("utf-8", errors="ignore")


def extract_mlb_stats_data(page_html: str) -> list[dict]:
    marker = "mlbStatsData:"
    marker_index = page_html.find(marker)
    if marker_index < 0:
        raise ValueError("MiLB page does not contain mlbStatsData")
    start = page_html.find("[", marker_index)
    if start < 0:
        raise ValueError("MiLB page does not contain mlbStatsData array")

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(page_html)):
        char = page_html[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return json.loads(page_html[start : index + 1])
    raise ValueError("MiLB page contains an unterminated mlbStatsData array")


def _latest_current_row(rows: list[dict], mlbam_id: int, role: str, season: int) -> dict:
    group = "hitting" if role == "hitter" else "pitching"
    candidates = [
        row
        for row in rows
        if str(row.get("playerId")) == str(mlbam_id)
        and row.get("group") == group
        and str(row.get("season")) == str(season)
        and row.get("gameType") == "R"
        and row.get("type") == "yearByYear"
    ]
    if not candidates:
        raise ValueError(f"no {season} {group} MiLB stats found for MLBAM {mlbam_id}")
    candidates.sort(
        key=lambda row: (
            row.get("customClass") == "aggregate-row",
            _number(row.get("plateAppearances") or row.get("inningsPitched"), 0.0),
        ),
        reverse=True,
    )
    return candidates[0]


def _hitter_updates(row: dict, fetched_date: str) -> dict:
    pa = _int(row.get("plateAppearances"))
    at_bats = _int(row.get("atBats"))
    hits = _int(row.get("hits"))
    home_runs = _int(row.get("homeRuns"))
    strikeouts = _int(row.get("strikeOuts"))
    walks = _int(row.get("baseOnBalls"))
    doubles = _int(row.get("doubles"))
    triples = _int(row.get("triples"))
    sac_flies = _int(row.get("sacFlies"))
    avg = _rate(row.get("avg"))
    obp = _rate(row.get("obp"))
    slg = _rate(row.get("slg"))
    ops = _rate(row.get("ops"))
    babip_denominator = at_bats - strikeouts - home_runs + sac_flies
    babip = (
        round((hits - home_runs) / babip_denominator, 3)
        if babip_denominator > 0
        else None
    )
    return {
        "plate_appearances": pa,
        "at_bats": at_bats,
        "hits": hits,
        "home_runs": home_runs,
        "strikeouts": strikeouts,
        "walks": walks,
        "doubles": doubles,
        "triples": triples,
        "stolen_bases": _int(row.get("stolenBases")),
        "rbi": _int(row.get("rbi")),
        "runs": _int(row.get("runs")),
        "games_played": _int(row.get("gamesPlayed")),
        "sac_flies": sac_flies,
        "avg": avg,
        "obp": obp,
        "slg": slg,
        "ops": ops,
        "iso": round(slg - avg, 3) if slg is not None and avg is not None else None,
        "k_pct": round(strikeouts / pa * 100, 1) if pa else None,
        "bb_pct": round(walks / pa * 100, 1) if pa else None,
        "babip": babip,
        "sample_fetched_date": fetched_date,
    }


def _write_json(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _update_current_stats(
    path: Path,
    mlbam_id: int,
    role: str,
    updates: dict,
) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    group = "hitters" if role == "hitter" else "pitchers"
    for row in payload.get(group) or []:
        if int(row.get("mlbam_id") or 0) != mlbam_id:
            continue
        before = {key: row.get(key) for key in updates}
        row.update({key: value for key, value in updates.items() if value is not None})
        _write_json(path, payload)
        return {
            "name": row.get("name"),
            "before": before,
            "after": {key: row.get(key) for key in updates},
        }
    raise ValueError(f"MLBAM {mlbam_id} not found in {path}")


def refresh_milb_player_stats(
    mlbam_id: int,
    role: str = "hitter",
    season: int | None = None,
    fetched_date: str | None = None,
) -> dict:
    season = season or date.today().year
    fetched_date = fetched_date or date.today().isoformat()
    page = _fetch_player_page(mlbam_id)
    rows = extract_mlb_stats_data(page)
    stat_row = _latest_current_row(rows, mlbam_id, role, season)
    if role != "hitter":
        raise NotImplementedError("targeted pitcher refresh is not implemented yet")
    updates = _hitter_updates(stat_row, fetched_date)
    result = _update_current_stats(CURRENT_STATS_PATH, mlbam_id, role, updates)
    result["source_url"] = f"https://www.milb.com/player/{mlbam_id}"
    result["season"] = season
    result["fetched_date"] = fetched_date
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mlbam-id", type=int, required=True)
    parser.add_argument("--role", choices=["hitter"], default="hitter")
    parser.add_argument("--season", type=int, default=date.today().year)
    parser.add_argument("--fetched-date", default=date.today().isoformat())
    args = parser.parse_args()

    try:
        result = refresh_milb_player_stats(
            args.mlbam_id,
            role=args.role,
            season=args.season,
            fetched_date=args.fetched_date,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"MiLB player stat refresh failed: {exc}", file=sys.stderr)
        return 1

    print(
        "MiLB player stat refresh: "
        f"name={result.get('name')} "
        f"mlbam_id={args.mlbam_id} "
        f"season={result['season']} "
        f"fetched_date={result['fetched_date']} "
        f"source={result['source_url']}"
    )
    print("before:", json.dumps(result["before"], sort_keys=True))
    print("after:", json.dumps(result["after"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
