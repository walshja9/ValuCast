"""Build the ValuCast playing-time and role tracker."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.playing_time_role import run_playing_time_role_tracker  # noqa: E402


def main() -> None:
    result = run_playing_time_role_tracker()
    print(
        "playing-time role tracker: "
        f"profiles={result['profile_count']} "
        f"ready={result['ready_for_role_context']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
