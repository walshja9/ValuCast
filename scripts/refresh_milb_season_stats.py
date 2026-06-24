"""Refresh current affiliated MiLB season stats from MLB Stats API."""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "prospects" / "raw"
OUTPUT_PATH = RAW_DIR / "milb_season_stats.json"
RECENT_OUTPUT_PATH = RAW_DIR / "milb_recent_stats.json"

SPORT_LEVELS = {
    11: "AAA",
    12: "AA",
    13: "A+",
    14: "A",
}


def _normalize_name(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, "", "-.--", ".---"):
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


def _pct(numerator: int | float, denominator: int | float) -> float | None:
    return round(float(numerator) / float(denominator) * 100.0, 1) if denominator else None


def _innings(value: Any, default: float = 0.0) -> float:
    try:
        text = str(value).split()[0]
    except (TypeError, ValueError):
        return default
    if "." not in text:
        numeric = _number(text)
        return default if numeric is None else numeric
    whole, fraction = text.split(".", 1)
    try:
        outs = int(fraction[:1] or 0)
        if outs not in {0, 1, 2}:
            return default
        return float(whole) + outs / 3.0
    except ValueError:
        return default


def _fetch_splits(
    group: str,
    sport_id: int,
    season: int,
    *,
    stats_type: str = "season",
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    params = {
        "stats": stats_type,
        "group": group,
        "season": season,
        "sportIds": sport_id,
        "playerPool": "ALL",
        "limit": 10000,
    }
    if stats_type == "byDateRange":
        params["startDate"] = start_date
        params["endDate"] = end_date
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"https://statsapi.mlb.com/api/v1/stats?{query}",
        headers={"User-Agent": "ValuCast MiLB season-stat refresh"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.load(response)
    stats = payload.get("stats") or []
    return list((stats[0] if stats else {}).get("splits") or [])


def _base_row(split: dict, role: str, sport_id: int, fetched_date: str) -> dict:
    player = split.get("player") or {}
    stat = split.get("stat") or {}
    return {
        "mlbam_id": _int(player.get("id")),
        "name": player.get("fullName") or "",
        "normalized_name": _normalize_name(player.get("fullName")),
        "team": (split.get("team") or {}).get("name") or "",
        "level": SPORT_LEVELS[sport_id],
        "sport_id": sport_id,
        "role": role,
        "age": _int(stat.get("age")),
        "position": (split.get("position") or {}).get("abbreviation") or "P",
        "sample_fetched_date": fetched_date,
    }


def _hitter_row(split: dict, sport_id: int, fetched_date: str) -> dict:
    stat = split.get("stat") or {}
    pa = _int(stat.get("plateAppearances"))
    at_bats = _int(stat.get("atBats"))
    hits = _int(stat.get("hits"))
    home_runs = _int(stat.get("homeRuns"))
    strikeouts = _int(stat.get("strikeOuts"))
    walks = _int(stat.get("baseOnBalls"))
    avg = _rate(stat.get("avg"))
    slg = _rate(stat.get("slg"))
    return {
        **_base_row(split, "hitter", sport_id, fetched_date),
        "plate_appearances": pa,
        "at_bats": at_bats,
        "hits": hits,
        "home_runs": home_runs,
        "strikeouts": strikeouts,
        "walks": walks,
        "doubles": _int(stat.get("doubles")),
        "triples": _int(stat.get("triples")),
        "stolen_bases": _int(stat.get("stolenBases")),
        "rbi": _int(stat.get("rbi")),
        "runs": _int(stat.get("runs")),
        "games_played": _int(stat.get("gamesPlayed")),
        "sac_flies": _int(stat.get("sacFlies")),
        "avg": avg,
        "obp": _rate(stat.get("obp")),
        "slg": slg,
        "ops": _rate(stat.get("ops")),
        "iso": round(slg - avg, 3) if slg is not None and avg is not None else None,
        "k_pct": _pct(strikeouts, pa),
        "bb_pct": _pct(walks, pa),
        "babip": _rate(stat.get("babip")),
    }


def _pitcher_row(split: dict, sport_id: int, fetched_date: str) -> dict:
    stat = split.get("stat") or {}
    innings = _innings(stat.get("inningsPitched"))
    strikeouts = _int(stat.get("strikeOuts"))
    walks = _int(stat.get("baseOnBalls"))
    batters_faced = _int(stat.get("battersFaced"))
    games_started = _int(stat.get("gamesStarted"))
    return {
        **_base_row(split, "pitcher", sport_id, fetched_date),
        "position": "P",
        "innings_pitched": round(innings, 1),
        "strikeouts": strikeouts,
        "walks": walks,
        "batters_faced": batters_faced,
        "games_played": _int(stat.get("gamesPlayed") or stat.get("gamesPitched")),
        "games_started": games_started,
        "wins": _int(stat.get("wins")),
        "losses": _int(stat.get("losses")),
        "hits": _int(stat.get("hits")),
        "home_runs": _int(stat.get("homeRuns")),
        "earned_runs": _int(stat.get("earnedRuns")),
        "runs": _int(stat.get("runs")),
        "era": _rate(stat.get("era"), digits=2),
        "whip": _rate(stat.get("whip"), digits=2),
        "k_per_9": _rate(stat.get("strikeoutsPer9Inn"), digits=2),
        "bb_per_9": _rate(stat.get("walksPer9Inn"), digits=2),
        "k_bb_pct": _pct(strikeouts - walks, batters_faced),
        "is_starter": games_started > 0,
    }


def build_milb_season_stats(
    *,
    season: int | None = None,
    fetched_date: str | None = None,
    stats_type: str = "season",
    window_days: int = 30,
    start_date: str | None = None,
    end_date: str | None = None,
    generated_at: str | None = None,
) -> dict:
    season = season or date.today().year
    fetched_date = fetched_date or date.today().isoformat()
    if stats_type not in {"season", "byDateRange"}:
        raise ValueError("stats_type must be season or byDateRange")
    if stats_type == "byDateRange":
        start_date, end_date = _resolve_date_range(
            fetched_date=fetched_date,
            window_days=window_days,
            start_date=start_date,
            end_date=end_date,
        )
    hitters: list[dict] = []
    pitchers: list[dict] = []
    for sport_id in SPORT_LEVELS:
        fetch_kwargs = {}
        if stats_type == "byDateRange":
            fetch_kwargs = {
                "stats_type": stats_type,
                "start_date": start_date,
                "end_date": end_date,
            }
        hitters.extend(
            _hitter_row(split, sport_id, fetched_date)
            for split in _fetch_splits("hitting", sport_id, season, **fetch_kwargs)
        )
        pitchers.extend(
            _pitcher_row(split, sport_id, fetched_date)
            for split in _fetch_splits("pitching", sport_id, season, **fetch_kwargs)
        )
    hitters.sort(key=lambda row: (row["sport_id"], row["name"], row["mlbam_id"]))
    pitchers.sort(key=lambda row: (row["sport_id"], row["name"], row["mlbam_id"]))
    payload = {
        "season": season,
        "fetched_date": fetched_date,
        "source": "mlb_statsapi_byDateRange" if stats_type == "byDateRange" else "mlb_statsapi_season_stats",
        "sport_levels": {str(key): value for key, value in SPORT_LEVELS.items()},
        "hitters": hitters,
        "pitchers": pitchers,
    }
    if stats_type == "byDateRange":
        payload.update(
            {
                "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
                "window_days": window_days,
                "start_date": start_date,
                "end_date": end_date,
            }
        )
    return payload


def _resolve_date_range(
    *,
    fetched_date: str,
    window_days: int,
    start_date: str | None,
    end_date: str | None,
) -> tuple[str, str]:
    if window_days < 1:
        raise ValueError("window_days must be positive")
    if end_date:
        end = date.fromisoformat(end_date)
    else:
        end = date.fromisoformat(fetched_date)
    if start_date:
        start = date.fromisoformat(start_date)
    else:
        start = end - timedelta(days=window_days - 1)
    if start > end:
        raise ValueError("start_date must be on or before end_date")
    return start.isoformat(), end.isoformat()


def write_milb_season_stats(payload: dict, path: Path = OUTPUT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--season", type=int, default=date.today().year)
    parser.add_argument("--fetched-date", default=date.today().isoformat())
    parser.add_argument("--stats-type", choices=("season", "byDateRange"), default="season")
    parser.add_argument("--window-days", type=int, default=30)
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output_path = args.output or (
        RECENT_OUTPUT_PATH if args.stats_type == "byDateRange" else OUTPUT_PATH
    )

    payload = build_milb_season_stats(
        season=args.season,
        fetched_date=args.fetched_date,
        stats_type=args.stats_type,
        window_days=args.window_days,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    path = write_milb_season_stats(payload, output_path)
    print(
        "MiLB season stats refresh: "
        f"season={payload['season']} "
        f"fetched_date={payload['fetched_date']} "
        f"stats_type={args.stats_type} "
        f"window={payload.get('start_date', '')}:{payload.get('end_date', '')} "
        f"hitters={len(payload['hitters'])} "
        f"pitchers={len(payload['pitchers'])} "
        f"-> {path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
