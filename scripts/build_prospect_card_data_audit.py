"""Build the ValuCast prospect-card data audit."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.card_data_audit import run_prospect_card_data_audit  # noqa: E402


def main() -> None:
    result = run_prospect_card_data_audit()
    print(
        "prospect card data audit: "
        f"status={result['status']} "
        f"ready={result['ready_for_cards']} "
        f"top200={result['top200_count']} "
        f"watch={result['top200_watch_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
