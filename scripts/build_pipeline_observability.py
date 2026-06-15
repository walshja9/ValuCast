"""Build the ValuCast daily pipeline observability artifact."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.pipeline_observability import run_pipeline_observability  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    args = parser.parse_args()

    result = run_pipeline_observability(expected_date=args.date)
    print(
        "ValuCast pipeline observability: "
        f"status={result['status']} "
        f"ready={result['ready_for_daily_publication']} "
        f"date_mismatches={result['date_mismatch_count']} "
        f"missing={result['missing_or_unreadable_count']} "
        f"targeted_refreshes={result['targeted_row_refresh_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
