"""Refresh the prospect current-org cache from MLB StatsAPI (network step).

The board's `mlb_team` was historically inferred from the affiliate team on a
player's selected stat line (universe.MINOR_TEAM_MLB_AFFILIATES). That is the
team a line was EARNED under, not the org the player belongs to today: a traded
player kept his old org until a threshold sample accrued at the new one
(2026-07-14 audit: 24 stale orgs among 2847 board rows, incl. the 7/11
deadline cluster -- Clarke BOS->STL, Gonzalez CHW->PIT, Curet TBR->DET).

This script fetches currentTeam for every input-contract player and resolves
it to the MLB parent org, writing a committed cache that the (network-free)
universe builder consults FIRST, before the stat-line affiliate fallback:

  data/prospects/raw/prospect_current_org.json

Guards:
- currentTeam outside the affiliated ladder (foreign/winter league) -> keep
  the prior cache entry; never map through a non-MLB parent.
- Fetch failures keep prior entries (never overwrite a good org with nothing).
- Catastrophic run (resolved < half of requested ids) -> refuse to write.

Org codes are normalized via consensus_join_util.normalize_org so they compare
equal to board/affiliate-map codes. Runs nightly in daily-public-data.yml
right after the MiLB stat refreshes; the raw dir is already in the commit list.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.consensus_join_util import normalize_org  # noqa: E402

INPUTS_PATH = ROOT / "data" / "prospects" / "prospect_model_inputs.json"
OUT_PATH = ROOT / "data" / "prospects" / "raw" / "prospect_current_org.json"

# MLB + the affiliated MiLB ladder (AAA/AA/A+/A/Rookie incl. complex + DSL).
AFFILIATED_SPORT_IDS = "1,11,12,13,14,16"
BATCH_SIZE = 100
MIN_RESOLVED_FRACTION = 0.5


def _get_json(path: str, params: dict) -> dict:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"https://statsapi.mlb.com/api/v1/{path}?{query}",
        headers={"User-Agent": "valucast-prospect-orgs/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def build_team_org_map(teams_payload: dict) -> dict[int, str]:
    """team_id -> normalized MLB parent-org abbreviation, affiliated ladder only."""
    sport1_abbrev: dict[int, str] = {}
    for team in teams_payload.get("teams") or []:
        if (team.get("sport") or {}).get("id") == 1 and team.get("abbreviation"):
            sport1_abbrev[team["id"]] = normalize_org(team["abbreviation"])
    org_by_team: dict[int, str] = dict(sport1_abbrev)
    for team in teams_payload.get("teams") or []:
        parent = team.get("parentOrgId")
        if team.get("id") not in org_by_team and parent in sport1_abbrev:
            org_by_team[team["id"]] = sport1_abbrev[parent]
    return org_by_team


def resolve_orgs(
    person_team_ids: dict[int, int], team_org_map: dict[int, str]
) -> dict[str, str]:
    """mlbam_id (str) -> org for players whose currentTeam is on the ladder."""
    return {
        str(pid): team_org_map[tid]
        for pid, tid in person_team_ids.items()
        if tid in team_org_map
    }


def merge_preserving_prior(prior: dict, fetched: dict) -> dict:
    """Fetched wins; ids that failed/left the ladder keep their prior org."""
    return {**prior, **fetched}


def _input_ids() -> list[int]:
    current = json.loads(INPUTS_PATH.read_text(encoding="utf-8")).get("current") or {}
    ids = {
        int(row["mlbam_id"])
        for key in ("hitters", "pitchers")
        for row in current.get(key) or []
        if row.get("mlbam_id")
    }
    return sorted(ids)


def _fetch_person_team_ids(ids: list[int]) -> tuple[dict[int, int], int]:
    """person_id -> currentTeam id. Returns (mapping, failed_batches)."""
    mapping: dict[int, int] = {}
    failed = 0
    for start in range(0, len(ids), BATCH_SIZE):
        batch = ids[start : start + BATCH_SIZE]
        try:
            payload = _get_json(
                "people",
                {"personIds": ",".join(map(str, batch)), "hydrate": "currentTeam"},
            )
        except Exception as exc:  # noqa: BLE001 -- keep prior entries, count it
            failed += 1
            print(f"  batch at {start} failed ({exc}); prior entries kept")
            continue
        for person in payload.get("people") or []:
            team_id = (person.get("currentTeam") or {}).get("id")
            if person.get("id") and team_id:
                mapping[int(person["id"])] = int(team_id)
    return mapping, failed


def _load_prior() -> dict:
    try:
        payload = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    orgs = payload.get("orgs")
    return orgs if isinstance(orgs, dict) else {}


def refresh(write: bool) -> dict:
    ids = _input_ids()
    prior = _load_prior()
    team_org_map = build_team_org_map(
        _get_json("teams", {"sportIds": AFFILIATED_SPORT_IDS})
    )
    person_team_ids, failed_batches = _fetch_person_team_ids(ids)
    fetched = resolve_orgs(person_team_ids, team_org_map)
    merged = merge_preserving_prior(prior, fetched)

    counts = {
        "requested": len(ids),
        "resolved_this_run": len(fetched),
        "off_ladder_or_missing": len(ids) - len(fetched),
        "failed_batches": failed_batches,
        "total_cached": len(merged),
    }
    print(json.dumps(counts, indent=2))
    if len(fetched) < MIN_RESOLVED_FRACTION * len(ids):
        raise SystemExit(
            f"refusing to write: resolved {len(fetched)}/{len(ids)} "
            f"(< {MIN_RESOLVED_FRACTION:.0%}); prior cache left untouched"
        )

    payload = {
        "artifact": "prospect_current_org",
        "schema_version": "1.0",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "mlb_statsapi_people_currentTeam",
        "counts": counts,
        "orgs": merged,
    }
    if write:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT_PATH.with_suffix(OUT_PATH.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(tmp, OUT_PATH)
        print("wrote", OUT_PATH)
    else:
        print("(dry run; pass --write to emit", OUT_PATH.name, ")")
    return payload


if __name__ == "__main__":
    refresh(write="--write" in sys.argv)
