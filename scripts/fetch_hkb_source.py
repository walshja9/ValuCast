"""Fetch the live HKB rankings and refresh data/hkb/hkb_source.csv (prospects only).

HKB (harryknowsball.com) is a crowdsourced ELO ranking that updates continuously,
so the committed CSV goes stale by design. This script is the manual refresh:
the /calculator page is Next.js SSR with the full player dataset embedded in
__NEXT_DATA__ (same extraction the DD repo's refresh_data.download_hkb uses).
Run it, then scripts/build_hkb_consensus_snapshot.py, then commit BOTH files.

NOT wired into the daily build on purpose: board ingestion is a reviewed,
deliberate act (the consensus is load-bearing), and serving stays network-free.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "https://harryknowsball.com/calculator"
OUT = ROOT / "data" / "hkb" / "hkb_source.csv"
FIELDNAMES = ["Rank", "Name", "Value", "Age", "Positions", "Team", "Level"]


def main() -> int:
    req = urllib.request.Request(
        URL, headers={"User-Agent": "Mozilla/5.0 (valucast-consensus-refresh)"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        html = r.read().decode("utf-8")

    m = re.search(
        r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>',
        html,
        re.DOTALL,
    )
    if not m:
        print("no __NEXT_DATA__ found on HKB page", file=sys.stderr)
        return 1
    players = json.loads(m.group(1))["props"]["pageProps"]["players"]

    prospects = [p for p in players if p.get("prospect")]
    if len(prospects) < 400:
        # tiny-refresh guard: the pool has been ~700+; a collapsed payload must
        # never overwrite a good committed source.
        print(f"refusing tiny refresh: only {len(prospects)} prospects", file=sys.stderr)
        return 1
    prospects.sort(key=lambda p: p.get("rank") or 10**9)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, quoting=csv.QUOTE_NONNUMERIC)
        w.writeheader()
        # Rank is re-based 1..N within the prospect pool (the committed format).
        for i, p in enumerate(prospects, 1):
            pos = p.get("positions", [])
            if isinstance(pos, list):
                pos = ", ".join(pos)
            w.writerow(
                {
                    "Rank": i,
                    "Name": p.get("name", ""),
                    "Value": p.get("value", ""),
                    "Age": p.get("age", ""),
                    "Positions": pos,
                    "Team": p.get("team", ""),
                    "Level": p.get("level", ""),
                }
            )
    print(f"wrote {len(prospects)} prospects -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
