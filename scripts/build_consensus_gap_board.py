"""Build the two-sided consensus-gap board artifact (offline, deterministic).

Run: python scripts/build_consensus_gap_board.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.consensus_gap import run  # noqa: E402


def main() -> None:
    payload = run()
    summary = payload["summary"]
    print(
        f"consensus gap board: evaluated={summary['evaluated']} "
        f"ahead={summary['ahead_qualified']} fade={summary['fade_qualified']} "
        f"(showing up to {summary['shown_per_side']}/side)"
    )
    for side in ("higher", "lower"):
        print(f"\n{side.upper()}:")
        for row in payload[side][:5]:
            print(
                f"  {row['name']:24s} VC #{row['valucast_rank']:<4} "
                f"field ~#{row['consensus_rank']:<4} ({row['board_count']} boards) "
                f"gap {row['divergence']:+d}"
            )


if __name__ == "__main__":
    main()
