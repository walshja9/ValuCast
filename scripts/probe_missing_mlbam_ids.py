"""THROWAWAY: feed ids of projected players with no MLB id (ids, names and pool only).

Fetches the Steamer full-season feed exactly as the preseason refresh does (two
requests) and lists rows whose MLBAM id is blank and whose projected playing time
clears the dynasty layer's lowest floor. No stat value is written.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from scraper.fangraphs import fetch_all

MIN_HITTER_PA = 100  # mlb/dynasty.py floor
MIN_PITCHER_IP = 20  # the reliever floor, the lower of the two pitcher floors


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _mlbam(row: dict) -> str:
    # Same expression scraper/blend.py uses for metadata.mlbam_id.
    return str(row.get("xMLBAMID", "") or row.get("MLBAMID", ""))


def main() -> int:
    out_dir = Path(os.environ.get("PROBE_OUT", "."))
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = fetch_all(delay=1.0, system="steamer")
    pools = (
        ("hitter", raw["steamer_hitters"], "PA", MIN_HITTER_PA),
        ("pitcher", raw["steamer_pitchers"], "IP", MIN_PITCHER_IP),
    )
    ids_by_pool = {pool: {str(row.get("playerids", "")) for row in rows} for pool, rows, _, _ in pools}
    lines = []
    for pool, rows, volume_key, floor in pools:
        blank = [row for row in rows if _mlbam(row) == ""]
        eligible = [row for row in blank if _num(row.get(volume_key)) >= floor]
        lines.append(f"{pool}: rows {len(rows)} blank_mlbam {len(blank)} blank_and_over_floor {len(eligible)}")
        other = "pitcher" if pool == "hitter" else "hitter"
        for row in sorted(eligible, key=lambda item: str(item.get("PlayerName", ""))):
            feed_id = str(row.get("playerids", ""))
            lines.append(
                f"  id={feed_id} | name={row.get('PlayerName', '')} | pool={pool} "
                f"| also_in_{other}_feed={feed_id in ids_by_pool[other]}"
            )
    (out_dir / "missing_mlbam_feed_ids.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
