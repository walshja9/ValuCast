"""Build the ValuCast Prospect Rank v1 coverage audit artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.coverage_audit import run_prospect_coverage_audit  # noqa: E402


def main() -> None:
    result = run_prospect_coverage_audit()
    print(
        "ValuCast prospect coverage audit: "
        f"status={result['status']} "
        f"rows={result['row_count']} "
        f"raw_fallback_top200={result['raw_fallback_top_200_count']} "
        "elite_factual_raw_fallback_top200="
        f"{result['elite_factual_raw_fallback_top_200_count']} "
        f"blockers={result['blocker_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
