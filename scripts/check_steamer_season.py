"""Check whether full-season Steamer has rolled past the 2026 season."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scraper.fangraphs import fetch_projections  # noqa: E402

# A draft class shows up in bulk only after its first full pro season: 30 of the
# 2025 class in the May 2026 feed, 475 in the rebuild seen on 11/2/2026. The
# newest class stays small (17 of 2026), so it cannot separate the two.
DRAFT_URL = "https://statsapi.mlb.com/api/v1/draft/2025"
LIVE_MIN_ROWS = 250


def _draftee_count(rows: list[dict], draftee_ids: set) -> int:
    ids = {str(value).strip() for value in draftee_ids}
    return sum(
        any(str(row.get(key)).strip() in ids for key in ("xMLBAMID", "MLBAMID"))
        for row in rows
    )


def verdict(rows: list[dict], draftee_ids: set) -> str:
    if not rows:
        return "unknown"
    return "live" if _draftee_count(rows, draftee_ids) >= LIVE_MIN_ROWS else "not_live"


def main() -> None:
    with urlopen(DRAFT_URL, timeout=30) as response:
        draft = json.load(response)
    draftee_ids = {
        pick["person"]["id"]
        for draft_round in draft["drafts"]["rounds"]
        for pick in draft_round["picks"]
    }
    hitters = fetch_projections("steamer", "bat")
    pitchers = fetch_projections("steamer", "pit")
    rows = hitters + pitchers
    result = verdict(rows, draftee_ids)
    print(f"Steamer hitter rows: {len(hitters)}")
    print(f"Steamer pitcher rows: {len(pitchers)}")
    print(f"2025 draftee rows: {_draftee_count(rows, draftee_ids)}")
    print(f"verdict={result}")
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with open(output_path, "a", encoding="utf-8") as output:
            output.write(f"verdict={result}\n")


if __name__ == "__main__":
    main()
