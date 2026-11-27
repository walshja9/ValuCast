"""Refresh the live HKB source and MLBAM-keyed snapshot (prospects only).

HKB (harryknowsball.com) is a crowdsourced ELO ranking that updates continuously,
so the committed CSV goes stale by design. The /calculator page is Next.js SSR
with the full player dataset embedded in
__NEXT_DATA__ (same extraction the DD repo's refresh_data.download_hkb uses).
The daily build promotes source + snapshot only after both candidates succeed;
an upstream outage keeps the committed last-good pair without re-stamping it.
"""
from __future__ import annotations

import csv
import json
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

import build_hkb_consensus_snapshot as hkb

ROOT = Path(__file__).resolve().parents[1]
URL = "https://harryknowsball.com/calculator"
OUT = ROOT / "data" / "hkb" / "hkb_source.csv"
FIELDNAMES = ["Rank", "Name", "Value", "Age", "Positions", "Team", "Level"]


def fetch_source(out: Path) -> int:
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

    with open(out, "w", newline="", encoding="utf-8") as f:
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
    print(f"wrote {len(prospects)} prospects -> {out}")
    return 0


def refresh() -> int:
    """Build candidates first; keep the committed pair on upstream failure."""
    final_snapshot = hkb.SNAPSHOT_PATH
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=OUT.parent) as tmp_dir:
        candidate_source = Path(tmp_dir) / OUT.name
        candidate_snapshot = Path(tmp_dir) / final_snapshot.name
        try:
            status = fetch_source(candidate_source)
        except Exception as exc:  # upstream network/markup failure: keep last-good
            print(f"HKB refresh failed; retaining last-good pair: {exc}", file=sys.stderr)
            return 0
        if status:
            print("HKB refresh rejected; retaining last-good pair", file=sys.stderr)
            return 0

        old_source, old_snapshot = hkb.SOURCE_CSV, hkb.SNAPSHOT_PATH
        try:
            hkb.SOURCE_CSV = candidate_source
            hkb.SNAPSHOT_PATH = candidate_snapshot
            hkb.build_hkb_snapshot()
        finally:
            hkb.SOURCE_CSV = old_source
            hkb.SNAPSHOT_PATH = old_snapshot

        candidate_source.replace(OUT)
        candidate_snapshot.replace(final_snapshot)
        print(f"promoted HKB source + snapshot -> {OUT.parent}")
    return 0


def main() -> int:
    return refresh()


if __name__ == "__main__":
    raise SystemExit(main())
