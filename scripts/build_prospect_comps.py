"""Build the prospect comps artifact (deterministic, offline).

Reads the committed MLB history cache + the public dynasty snapshot and
writes data/models/valucast_prospect_comps.json. No network. Runs in the
daily build after the snapshot step.

Run: python scripts/build_prospect_comps.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospects.comps import (  # noqa: E402
    ARTIFACT_PATH,
    HISTORY_PATH,
    SNAPSHOT_PATH,
    build_prospect_comps,
)


def run(artifact_path: Path = ARTIFACT_PATH) -> dict:
    history = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    generated_at = snapshot.get("generated_at")  # pin to snapshot freshness
    payload = build_prospect_comps(history, snapshot, generated_at=generated_at)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return payload


if __name__ == "__main__":
    result = run()
    players = result["players"]
    print(f"comps built for {len(players)} prospects "
          f"(pool rows: {result['method']['match_pool_rows']}, "
          f"resolved through {result['method']['resolved_through']})")
    sample = players.get("699302")
    if sample:
        print(f"\n{sample['name']} (P#{sample['prospect_rank']}) "
              f"target {sample['target']}")
        for twin in sample["twins"]:
            out = twin.get("outcome")
            tier = out["tier"] if out else "unresolved"
            print(f"  twin: {twin['name']} {twin['season']} age {twin['age']} "
                  f"({twin['pos']}, bats {twin['bats']}) "
                  f"K {twin['k_pct']} BB {twin['bb_pct']} ISO {twin['iso']} -> {tier}")
        print(f"  cohort: {sample['cohort']['tiers']} "
              f"(n={sample['cohort']['size']}, "
              f"median PA/yr {sample['cohort']['median_pa_per_year']})")
