"""Build the ValuCast MLB active-roster status contract."""
from pathlib import Path
import argparse
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.roster_status import run_mlb_roster_status  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Build from the cached MLB roster query instead of refreshing.",
    )
    args = parser.parse_args()

    result = run_mlb_roster_status(refresh=not args.no_refresh)
    print(
        "ValuCast MLB roster status: "
        f"teams={result['team_count']} "
        f"active_profiles={result['active_roster_profile_count']} "
        f"fetched_teams={result['fetched_teams']} "
        f"fetched_rosters={result['fetched_rosters']} "
        f"ready={result['ready_for_public_snapshot']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
