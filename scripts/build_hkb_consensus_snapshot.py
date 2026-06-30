"""Resolve the Harry Knows Ball (HKB) prospect list (rank + name) into an mlbam-keyed
consensus snapshot, mirroring the Pipeline/STS/FG/PL snapshots that
prospects/rank_v1.py merges into context_only.source_ranks.

HKB is editorial (no API). The source is the committed CSV data/hkb/hkb_source.csv
(Rank,Name,... columns). Names are joined to mlbam_id against ValuCast's own board +
universe (the repo joins on mlbam_id, never name) via the same _normalize_name used to
build normalized_name everywhere else.

Out-of-band (run when HKB re-ranks): drop a fresh export into data/hkb/hkb_source.csv
and re-run. The committed snapshot is what the daily build reads, so no daily step.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.raw_input_builder import _normalize_name  # noqa: E402

SOURCE_CSV = ROOT / "data" / "hkb" / "hkb_source.csv"
SNAPSHOT_PATH = ROOT / "data" / "hkb" / "hkb_consensus_snapshot.json"
RANK_V1_PATH = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
UNIVERSE_PATH = ROOT / "data" / "models" / "valucast_prospect_universe.json"


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _name_index() -> dict[str, str]:
    """normalized_name -> mlbam_id from the board (ranked + graduated) then universe."""
    index: dict[str, str] = {}
    board = _load(RANK_V1_PATH)
    rows = list(board.get("board") or []) + list(board.get("active_mlb_roster_board") or [])
    universe = _load(UNIVERSE_PATH)
    rows += list(universe.get("players") or universe.get("candidates") or [])
    for row in rows:
        if not isinstance(row, dict):
            continue
        mlbam = row.get("mlbam_id")
        if mlbam in (None, ""):
            continue
        key = row.get("normalized_name") or _normalize_name(row.get("name"))
        if key and key not in index:
            index[key] = str(mlbam)
    return index


def build_hkb_snapshot() -> dict:
    index = _name_index()
    players: dict[str, dict] = {}
    unmatched: list[dict] = []
    input_count = 0
    with open(SOURCE_CSV, encoding="utf-8-sig", newline="") as fh:
        for entry in csv.DictReader(fh):
            try:
                rank = int(entry["Rank"])
            except (KeyError, ValueError, TypeError):
                continue
            name = (entry.get("Name") or "").strip()
            if not name:
                continue
            input_count += 1
            mlbam = index.get(_normalize_name(name))
            if mlbam is None:
                unmatched.append({"rank": rank, "name": name})
                continue
            prior = players.get(mlbam)
            if prior is None or rank < prior["hkb_rank"]:
                players[mlbam] = {"hkb_rank": rank, "name": name}

    payload = {
        "artifact": "valucast_hkb_consensus",
        "source": "Harry Knows Ball (HKB) prospect list",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_count": input_count,
        "matched_count": len(players),
        "unmatched_count": len(unmatched),
        "unmatched": unmatched,
        "players_by_mlbam": players,
    }
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = SNAPSHOT_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(SNAPSHOT_PATH)
    return payload


def main() -> int:
    payload = build_hkb_snapshot()
    print(
        f"HKB consensus snapshot: matched={payload['matched_count']}/{payload['input_count']} "
        f"unmatched={payload['unmatched_count']} -> {SNAPSHOT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
