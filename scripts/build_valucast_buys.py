"""Build the shadow ValuCast-owned prospect buy signals artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.buys import run_buy_signals  # noqa: E402


def main() -> None:
    result = run_buy_signals()
    print(
        "ValuCast prospect buys: "
        f"rows={result['row_count']} "
        f"eligible={result['eligible_count']} "
        f"ready={result['ready_for_live_consumers']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
