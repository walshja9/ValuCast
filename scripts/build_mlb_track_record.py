"""Build the ValuCast MLB track-record contract."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.track_record import run_mlb_track_record  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-refresh-missing",
        action="store_true",
        help="Do not fetch missing MLB history; build only from the local cache.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of missing MLBAM histories to fetch in this run.",
    )
    args = parser.parse_args()

    result = run_mlb_track_record(
        refresh_missing=not args.no_refresh_missing,
        fetch_limit=args.limit,
    )
    print(
        "ValuCast MLB track record: "
        f"profiles={result['profile_count']} "
        f"coverage={result['coverage_rate']:.1%} "
        f"fetched={result['fetched_count']} "
        f"ready={result['ready_for_mlb_dynasty_layer']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
