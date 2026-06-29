"""Per-season MiLB exposure (games + PA/IP) for current prospects.

OUT-OF-BAND (network) — NOT part of the network-free daily build. Run manually;
commit the artifact. Powers the card's honesty layer: a prospect who is "old for the
level" because a recent season was cut short (injury/lost development time) reads
differently than one who stalled. The model can't see this; the card can surface it.

Source: statsapi.mlb.com /api/v1/stats?stats=season (one request per
season x sportId x group), joined to the current prospect board by mlbam_id. Stores
ONE season total per (mlbam_id, season): games + the role's sample (PA or IP).
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
OUT = ROOT / "data" / "prospects" / "raw" / "prospect_exposure_history.json"

SPORT_IDS = (11, 12, 13, 14, 16)
GROUP_ROLE = {"hitting": "hitter", "pitching": "pitcher"}
SEASONS = range(2021, 2027)
API = "https://statsapi.mlb.com/api/v1/stats"


def _fetch(season: int, sport_id: int, group: str) -> list[dict]:
    url = (
        f"{API}?stats=season&season={season}&sportId={sport_id}"
        f"&group={group}&playerPool=all&limit=5000"
    )
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=40) as resp:
                return (json.load(resp).get("stats") or [{}])[0].get("splits") or []
        except Exception:  # noqa: BLE001 - bounded retry on a one-off pull
            if attempt == 3:
                raise
            time.sleep(1.5 * (attempt + 1))
    return []


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ip_outs(value) -> int:
    whole, _, frac = str(value or "0").partition(".")
    return int(_num(whole)) * 3 + (int(_num(frac)) if frac else 0)


def _draft_years(ids: list[int]) -> dict[int, int]:
    """Batched people lookup -> {mlbam_id: draft_year}. draftYear disambiguates a
    shortened first full season (Sirota 2025) from a normal draft-summer debut."""
    out: dict[int, int] = {}
    for start in range(0, len(ids), 100):
        chunk = ids[start:start + 100]
        url = "https://statsapi.mlb.com/api/v1/people?personIds=" + ",".join(str(i) for i in chunk)
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=40) as resp:
                    people = json.load(resp).get("people") or []
                break
            except Exception:  # noqa: BLE001
                if attempt == 3:
                    raise
                time.sleep(1.5 * (attempt + 1))
        for person in people:
            year = person.get("draftYear")
            if person.get("id") is not None and year is not None:
                out[int(person["id"])] = int(year)
    return out


def main() -> None:
    board = json.loads(BOARD.read_text(encoding="utf-8")).get("board") or []
    role_by_id = {int(b["mlbam_id"]): b.get("role") for b in board if b.get("mlbam_id")}

    # acc[(mlbam_id, season)] = {"games": g, "pa": pa, "outs": outs}
    acc: dict[tuple[int, int], dict] = {}
    requests = 0
    for season in SEASONS:
        for sport_id in SPORT_IDS:
            for group, role in GROUP_ROLE.items():
                for split in _fetch(season, sport_id, group):
                    pid = (split.get("player") or {}).get("id")
                    if pid is None or role_by_id.get(int(pid)) != role:
                        continue
                    stat = split.get("stat") or {}
                    bucket = acc.setdefault((int(pid), season), {"games": 0.0, "pa": 0.0, "outs": 0})
                    bucket["games"] += _num(stat.get("gamesPlayed"))
                    if group == "hitting":
                        bucket["pa"] += _num(stat.get("plateAppearances"))
                    else:
                        bucket["outs"] += _ip_outs(stat.get("inningsPitched"))
                requests += 1
        print(f"  season {season} pulled ({requests} reqs)")

    seasons_by_pid: dict[int, list] = {}
    for (pid, season), bucket in acc.items():
        role = role_by_id[pid]
        entry = {
            "season": season,
            "games": int(round(bucket["games"])),
            "unit": "PA" if role == "hitter" else "IP",
            "sample": round(bucket["pa"], 1) if role == "hitter" else round(bucket["outs"] / 3.0, 1),
        }
        if entry["games"] <= 0:
            continue
        seasons_by_pid.setdefault(pid, []).append(entry)

    draft = _draft_years(sorted(seasons_by_pid))
    print(f"  draft years fetched: {len(draft)}")

    history = {
        str(pid): {"draft_year": draft.get(pid), "seasons": sorted(seasons, key=lambda e: e["season"])}
        for pid, seasons in seasons_by_pid.items()
    }
    OUT.write_text(
        json.dumps(
            {"source": "mlb_statsapi_season_exposure", "request_count": requests,
             "players": len(history), "seasons": list(SEASONS), "history": history},
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    print(f"\nwrote {OUT}\nplayers with exposure history: {len(history)}")


if __name__ == "__main__":
    main()
