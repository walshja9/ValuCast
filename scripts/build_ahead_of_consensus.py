"""Build the ValuCast ahead-of-consensus divergence report."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.ahead_of_consensus import run_ahead_of_consensus_report  # noqa: E402


def main() -> None:
    result = run_ahead_of_consensus_report()
    print(
        "ahead of consensus report: "
        f"status={result['status']} "
        f"ready={result['ready_for_ahead_of_consensus']} "
        f"ahead={result['ahead_count']} "
        f"badges={result['badge_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
