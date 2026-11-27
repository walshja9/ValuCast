"""Build the ValuCast recent prospect signal report."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.recent_signal import run_recent_signal_report  # noqa: E402


def main() -> None:
    result = run_recent_signal_report()
    print(
        "recent signal report: "
        f"status={result['status']} "
        f"ready={result['ready_for_recent_signal']} "
        f"signals={result['signal_count']} "
        f"movers={result['top_mover_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
