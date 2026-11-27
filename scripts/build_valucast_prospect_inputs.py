"""Build ValuCast's canonical prospect input contract."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--refresh-service-cache",
        action="store_true",
        help="Fetch missing MLBAM-keyed MLB service seasons before writing the contract.",
    )
    parser.add_argument(
        "--refresh-service-limit",
        type=int,
        default=None,
        help="Limit missing service-cache fetches for resumable backfills.",
    )
    parser.add_argument(
        "--refresh-service-workers",
        type=int,
        default=12,
        help="Concurrent StatsAPI workers for --refresh-service-cache.",
    )
    args = parser.parse_args()

    from prospects.input_builder import run_valucast_prospect_input_build
    from prospects.raw_input_builder import refresh_mlb_service_cache

    if args.refresh_service_cache:
        service_result = refresh_mlb_service_cache(
            limit=args.refresh_service_limit,
            max_workers=args.refresh_service_workers,
        )
        print(
            "MLB service cache refresh: "
            f"missing={service_result['missing_before']} "
            f"fetched={service_result['fetched']} "
            f"failed={service_result['failed']}"
        )

    result = run_valucast_prospect_input_build()
    print(
        "ValuCast prospect inputs: "
        f"generated_at={result['generated_at']} "
        f"historical={result['historical_rows']} "
        f"current={result['current_rows']} "
        f"producer={result['producer_owner']} "
        f"upstream={result['upstream_kind']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
