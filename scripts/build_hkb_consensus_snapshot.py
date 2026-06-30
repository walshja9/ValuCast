"""Recover HKB prospect-board ranks (lost when the DD feed was cut on 6/29) into an
mlbam-keyed consensus snapshot, mirroring the Pipeline/STS/FG/PL snapshots that
prospects/rank_v1.py merges into context_only.source_ranks.

HKB was DD-fed (editorial, not an API), so there's no live feed to pull. Its last-known
ranks are still in the most recent rank_v1 archive that predates the cut — bootstrap from
there to restore the pre-cut consensus coverage. To refresh later with a newer HKB list,
replace data/hkb/hkb_consensus_snapshot.json (same players_by_mlbam shape).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_rank_v1"
SNAPSHOT_PATH = ROOT / "data" / "hkb" / "hkb_consensus_snapshot.json"


def _latest_archive_with_hkb():
    for path in sorted(ARCHIVE_DIR.glob("*.json"), reverse=True):
        try:
            board = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        rows = board.get("board") or []
        n = sum(
            1 for r in rows
            if isinstance((r.get("context_only") or {}).get("source_ranks"), dict)
            and (r["context_only"]["source_ranks"].get("hkb") is not None)
        )
        if n >= 10:
            return path, board
    return None, None


def build_hkb_snapshot() -> dict:
    path, board = _latest_archive_with_hkb()
    players: dict[str, dict] = {}
    if board:
        rows = (board.get("board") or []) + (board.get("active_mlb_roster_board") or [])
        for row in rows:
            mlbam = row.get("mlbam_id")
            sr = (row.get("context_only") or {}).get("source_ranks") or {}
            if mlbam in (None, "") or sr.get("hkb") is None:
                continue
            try:
                players[str(mlbam)] = {"hkb_rank": int(sr["hkb"]), "name": row.get("name")}
            except (TypeError, ValueError):
                continue
    payload = {
        "artifact": "valucast_hkb_consensus",
        "source": "HKB prospect board (recovered from last pre-DD-cut rank archive)",
        "recovered_from": path.name if path else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "matched_count": len(players),
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
        f"HKB consensus snapshot: {payload['matched_count']} players recovered from "
        f"{payload['recovered_from']} -> {SNAPSHOT_PATH}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
