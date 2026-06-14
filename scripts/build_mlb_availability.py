"""Build the ValuCast MLB availability contract."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.availability import run_mlb_availability  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Build from the cached MLB transaction query instead of refreshing.",
    )
    args = parser.parse_args()

    result = run_mlb_availability(refresh=not args.no_refresh)
    print(
        "ValuCast MLB availability: "
        f"profiles={result['profile_count']} "
        f"risk_profiles={result['risk_profile_count']} "
        f"transactions={result['transaction_count']} "
        f"fetched={result['fetched']} "
        f"ready={result['ready_for_mlb_dynasty_layer']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
