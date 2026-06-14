"""Build the ValuCast Prospect Rank v1 calibration report."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.calibration_report import run_prospect_calibration_report

    result = run_prospect_calibration_report()
    print(
        "ValuCast prospect calibration report: "
        f"status={result['status']} "
        f"rows={result['row_count']} "
        f"flags={result['tuning_flag_count']} "
        f"availability_top50={result['availability_watchlist_count_top50']} "
        f"context_disagreements_top50={result['context_disagreement_count_top50']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
