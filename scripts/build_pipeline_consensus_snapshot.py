"""Resolve the editorial MLB Pipeline Top 100 (rank + name) into an mlbam-keyed
consensus snapshot, mirroring the STS / FanGraphs / ProspectsLive snapshots that
prospects/rank_v1.py merges into context_only.source_ranks.

Pipeline ranks are editorial (not in any API), so the input is the hand-maintained
data/pipeline/pipeline_top100.json. We join names to mlbam_id against ValuCast's own
board + universe (the repo joins on mlbam_id, never name, to dodge collisions) using
the same _normalize_name used to build normalized_name everywhere else.

Out-of-band (run when Pipeline re-ranks); the committed snapshot is what the daily
build reads, so no daily-build step is needed.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.raw_input_builder import _normalize_name  # noqa: E402
from scripts.consensus_join_util import build_candidate_index, resolve_mlbam  # noqa: E402

SOURCE_PATH = ROOT / "data" / "pipeline" / "pipeline_top100.json"
SNAPSHOT_PATH = ROOT / "data" / "pipeline" / "pipeline_consensus_snapshot.json"
RANK_V1_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
UNIVERSE_PATH = ROOT / "data" / "models" / "valucast_prospect_universe.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _name_index() -> dict[str, list[dict]]:
    """normalized_name -> [candidate identities], from the board (ranked + graduated)
    then universe. First writer per id wins on collision."""
    board = _load(RANK_V1_PATH)
    rows = list(board.get("board") or []) + list(board.get("active_mlb_roster_board") or [])
    universe = _load(UNIVERSE_PATH)
    rows += list(universe.get("players") or universe.get("candidates") or [])
    return build_candidate_index(rows, _normalize_name)


def build_pipeline_consensus_snapshot() -> dict:
    source = _load(SOURCE_PATH)
    players = source.get("players") or []
    index = _name_index()

    players_by_mlbam: dict[str, dict] = {}
    unmatched: list[dict] = []
    for entry in players:
        rank = entry.get("rank")
        name = entry.get("name")
        if rank is None or not name:
            continue
        # Pipeline carries name + rank ONLY (no team/age/role to self-disambiguate),
        # so it can match only when the normalized name resolves to exactly ONE board
        # identity; a shared name (>=2 ids) is left unmatched rather than guessing.
        mlbam = resolve_mlbam(index.get(_normalize_name(name), []))
        if mlbam is None:
            unmatched.append({"rank": rank, "name": name})
            continue
        # Keep the better (lower) rank if a name resolves to an already-seen id.
        prior = players_by_mlbam.get(mlbam)
        if prior is None or rank < prior["pipeline_rank"]:
            players_by_mlbam[mlbam] = {"pipeline_rank": rank, "name": name}

    payload = {
        "artifact": "valucast_pipeline_consensus",
        "source": source.get("source") or "MLB Pipeline Top 100",
        "as_of": source.get("as_of"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_count": len(players),
        "matched_count": len(players_by_mlbam),
        "unmatched_count": len(unmatched),
        "unmatched": unmatched,
        "players_by_mlbam": players_by_mlbam,
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(SNAPSHOT_PATH)
    return payload


def main() -> int:
    payload = build_pipeline_consensus_snapshot()
    print(
        f"ValuCast Pipeline consensus snapshot: matched={payload['matched_count']}/"
        f"{payload['input_count']} unmatched={payload['unmatched_count']} -> {SNAPSHOT_PATH}"
    )
    for row in payload["unmatched"]:
        print(f"  UNMATCHED #{row['rank']} {row['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
