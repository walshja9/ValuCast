"""Build the shadow ValuCast-owned prospect buy signals artifact."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.buys import BUY_REVIEW_PATH, run_buy_signals  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-review",
        action="store_true",
        help="Apply same-day review status to the Buy promotion gate.",
    )
    args = parser.parse_args()

    result = run_buy_signals(
        promotion_review_path=BUY_REVIEW_PATH if args.with_review else None
    )
    print(
        "ValuCast prospect buys: "
        f"rows={result['row_count']} "
        f"eligible={result['eligible_count']} "
        f"ready={result['ready_for_live_consumers']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
