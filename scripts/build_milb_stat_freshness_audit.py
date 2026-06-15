"""Build the ValuCast MiLB stat freshness audit artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.milb_stat_freshness import run_milb_stat_freshness_audit  # noqa: E402


def main() -> None:
    result = run_milb_stat_freshness_audit()
    print(
        "ValuCast MiLB stat freshness audit: "
        f"status={result['status']} "
        f"rows={result['current_row_count']} "
        f"top50_history={result['top50_history_fallback_count']} "
        f"top200_history={result['top200_history_fallback_count']} "
        f"targeted_refreshes={result['targeted_row_refresh_count']} "
        f"blockers={result['blocker_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
