"""Enrich ValuCast projection rows with identity/eligibility metadata from the
Steamer outlook (current.json), used STRICTLY as a names/teams/positions and
active-player universe — NO projection stats are copied. Rows whose player is not
in the eligibility universe for that pool (ghosts: pitcher batting history, retired
players) are DROPPED."""
from __future__ import annotations

_PITCHER_POOLS = {"starter", "reliever", "pitcher"}


def build_eligibility(steamer_rows: list[dict]) -> dict[str, dict[str, dict]]:
    """{'hitters': {mlbam_id: {name, team, positions}}, 'pitchers': {...}} from
    current.json. Two-way players (Ohtani) appear in both maps."""
    hitters: dict[str, dict] = {}
    pitchers: dict[str, dict] = {}
    for r in steamer_rows:
        mid = (r.get("metadata") or {}).get("mlbam_id")
        if not mid:
            continue
        meta = {"name": r.get("name", ""), "team": r.get("team", ""),
                "positions": list(r.get("positions") or [])}
        target = pitchers if r.get("pool") in _PITCHER_POOLS else hitters
        target.setdefault(str(mid), meta)
    return {"hitters": hitters, "pitchers": pitchers}


def enrich_rows(rows: list[dict], by_mlbam: dict[str, dict]) -> list[dict]:
    """Keep only rows whose mlbam_id is in the eligibility map; overwrite name/team/
    positions from it (metadata only, no stats). Drops ineligible ghosts/retired."""
    out = []
    for r in rows:
        mid = (r.get("metadata") or {}).get("mlbam_id")
        elig = by_mlbam.get(str(mid)) if mid else None
        if not elig:
            continue   # not in the active eligibility universe for this pool -> drop
        r2 = dict(r)
        r2["name"] = elig["name"] or r.get("name", "")
        r2["positions"] = elig["positions"] or list(r.get("positions") or [])
        m = dict(r2.get("metadata") or {})
        m["team"] = elig["team"]
        m["eligibility_source"] = "current.json (metadata/eligibility only, no stats)"
        r2["metadata"] = m
        out.append(r2)
    return out
