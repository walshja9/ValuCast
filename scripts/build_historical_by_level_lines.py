"""Backfill historical full-season-BY-LEVEL MiLB lines for the universe cohorts.

OUT-OF-BAND (network) — NOT part of the network-free daily build. Run manually;
commit the artifact. Unblocks the pooled-vs-single-level prospect backtest
(docs/specs/2026-06-27-w21-mle-backtest-gate.md): the committed universe dataset is
collapsed to one highest-level line per (mlbam_id, cohort_year), so the pooled INPUT
for mature folds (2018/2019/2021) was non-constructible. MLB StatsAPI returns per-level
season totals back to 2014, so we reconstruct them here.

Source: statsapi.mlb.com /api/v1/stats?stats=season (one request per
season x sportId x group; ~80 requests). Rates are recomputed from summed counting
stats so a mid-season same-level team change aggregates correctly. Output schema mirrors
valucast_universal_prospect_dataset.json row fields so the harness can feature-vectorize
the pooled line identically to a single line.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "data" / "prospects" / "raw" / "valucast_universal_prospect_dataset.json"
OUT = ROOT / "data" / "prospects" / "raw" / "historical_by_level_lines.json"

SPORT_LEVEL = {11: "AAA", 12: "AA", 13: "A+", 14: "A", 16: "R"}
GROUP_ROLE = {"hitting": "hitter", "pitching": "pitcher"}
API = "https://statsapi.mlb.com/api/v1/stats"


def _fetch(season: int, sport_id: int, group: str) -> list[dict]:
    url = (
        f"{API}?stats=season&season={season}&sportId={sport_id}"
        f"&group={group}&playerPool=all&limit=5000"
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=40) as resp:
                payload = json.load(resp)
            return (payload.get("stats") or [{}])[0].get("splits") or []
        except Exception as exc:  # noqa: BLE001 - bounded retry on a one-off pull
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
            _last = exc
    return []


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _ip_to_outs(value) -> int:
    # StatsAPI inningsPitched "133.2" == 133 innings + 2 outs.
    whole, _, frac = str(value or "0").partition(".")
    return int(_num(whole)) * 3 + (int(_num(frac)) if frac else 0)


def _hitter_line(level: str, sport_id: int, agg: dict) -> dict:
    pa = agg["plateAppearances"]
    ab = agg["atBats"]
    h, bb, so, hbp, sf = agg["hits"], agg["baseOnBalls"], agg["strikeOuts"], agg["hitByPitch"], agg["sacFlies"]
    d2, d3, hr = agg["doubles"], agg["triples"], agg["homeRuns"]
    tb = h + d2 + 2 * d3 + 3 * hr
    avg = h / ab if ab else 0.0
    obp = (h + bb + hbp) / (ab + bb + hbp + sf) if (ab + bb + hbp + sf) else 0.0
    slg = tb / ab if ab else 0.0
    babip_den = ab - so - hr + sf
    return {
        "level": level, "sport_id": sport_id,
        "plate_appearances": pa, "at_bats": ab, "hits": h, "doubles": d2, "triples": d3,
        "home_runs": hr, "walks": bb, "strikeouts": so, "stolen_bases": agg["stolenBases"],
        "runs": agg["runs"], "rbi": agg["rbi"], "sac_flies": sf,
        "avg": round(avg, 4), "obp": round(obp, 4), "slg": round(slg, 4),
        "ops": round(obp + slg, 4), "iso": round(slg - avg, 4),
        "babip": round((h - hr) / babip_den, 4) if babip_den > 0 else 0.0,
        "k_pct": round(100 * so / pa, 2) if pa else 0.0,
        "bb_pct": round(100 * bb / pa, 2) if pa else 0.0,
    }


def _pitcher_line(level: str, sport_id: int, agg: dict) -> dict:
    outs = agg["outs"]
    ip = outs / 3.0
    bf, so, bb, er, h, hr = agg["battersFaced"], agg["strikeOuts"], agg["baseOnBalls"], agg["earnedRuns"], agg["hits"], agg["homeRuns"]
    g, gs = agg["gamesPlayed"], agg["gamesStarted"]
    return {
        "level": level, "sport_id": sport_id,
        "innings_pitched": round(ip, 3), "batters_faced": bf, "strikeouts": so, "walks": bb,
        "earned_runs": er, "hits": h, "home_runs": hr, "runs": agg["runs"],
        "games_played": g, "games_started": gs, "wins": agg["wins"], "losses": agg["losses"],
        "era": round(9 * er / ip, 2) if ip else 0.0,
        "whip": round((bb + h) / ip, 2) if ip else 0.0,
        "k_per_9": round(9 * so / ip, 2) if ip else 0.0,
        "bb_per_9": round(9 * bb / ip, 2) if ip else 0.0,
        "k_bb_pct": round(100 * (so - bb) / bf, 2) if bf else 0.0,
        "is_starter": gs >= max(1, 0.5 * g) if g else False,
    }


HIT_KEYS = ("plateAppearances", "atBats", "hits", "doubles", "triples", "homeRuns",
            "baseOnBalls", "strikeOuts", "stolenBases", "runs", "rbi", "sacFlies", "hitByPitch")
PIT_KEYS = ("battersFaced", "strikeOuts", "baseOnBalls", "earnedRuns", "hits", "homeRuns",
            "runs", "gamesPlayed", "gamesStarted", "wins", "losses")


def main() -> None:
    universe = json.loads(UNIVERSE.read_text(encoding="utf-8"))["rows"]
    # need[(mlbam_id, cohort_year)] = role
    need: dict[tuple[int, int], str] = {}
    for row in universe:
        mid, cy = row.get("mlbam_id"), row.get("cohort_year")
        if mid is not None and cy is not None:
            need[(int(mid), int(cy))] = row["role"]
    seasons = sorted({cy for _, cy in need})

    # agg[(mlbam_id, cohort_year, sport_id)] = summed raw counts
    agg: dict[tuple[int, int, int], dict] = {}
    requests = 0
    for season in seasons:
        for sport_id in SPORT_LEVEL:
            for group, role in GROUP_ROLE.items():
                splits = _fetch(season, sport_id, group)
                requests += 1
                for split in splits:
                    pid = (split.get("player") or {}).get("id")
                    if pid is None or need.get((int(pid), season)) != role:
                        continue
                    stat = split.get("stat") or {}
                    key = (int(pid), season, sport_id)
                    bucket = agg.setdefault(key, {})
                    src_keys = HIT_KEYS if group == "hitting" else PIT_KEYS
                    for k in src_keys:
                        bucket[k] = bucket.get(k, 0) + _num(stat.get(k))
                    if group == "pitching":
                        bucket["outs"] = bucket.get("outs", 0) + _ip_to_outs(stat.get("inningsPitched"))
        print(f"  season {season} pulled ({requests} reqs so far)")

    # assemble per (mlbam_id, cohort_year)
    by_player: dict[tuple[int, int], dict] = {}
    for (mid, cy, sport_id), bucket in agg.items():
        role = need[(mid, cy)]
        level = SPORT_LEVEL[sport_id]
        if role == "hitter":
            if bucket.get("plateAppearances", 0) <= 0:
                continue
            line = _hitter_line(level, sport_id, {k: bucket.get(k, 0) for k in HIT_KEYS})
        else:
            if bucket.get("outs", 0) <= 0:
                continue
            line = _pitcher_line(level, sport_id, {**{k: bucket.get(k, 0) for k in PIT_KEYS}, "outs": bucket.get("outs", 0)})
        entry = by_player.setdefault((mid, cy), {"mlbam_id": mid, "cohort_year": cy, "role": role, "level_lines": []})
        entry["level_lines"].append(line)

    rows = []
    for entry in by_player.values():
        # highest level first (AAA < AA < A+ < A < R by sport_id ascending)
        entry["level_lines"].sort(key=lambda ll: ll["sport_id"])
        entry["n_levels"] = len(entry["level_lines"])
        rows.append(entry)

    multi = sum(1 for r in rows if r["n_levels"] >= 2)
    out = {
        "source": "mlb_statsapi_season_by_level",
        "schema": "by_level_season_lines_v1",
        "request_count": requests,
        "universe_pairs": len(need),
        "matched_pairs": len(rows),
        "multi_level_pairs": multi,
        "seasons": seasons,
        "rows": rows,
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    print(f"\nwrote {OUT}")
    print(f"universe pairs {len(need)} | matched {len(rows)} | multi-level {multi} ({100*multi/max(1,len(rows)):.1f}%)")


if __name__ == "__main__":
    main()
