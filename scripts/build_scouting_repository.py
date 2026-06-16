"""Build the ValuCast scouting report repository."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scouting.repository import run_scouting_repository  # noqa: E402


def main() -> None:
    result = run_scouting_repository()
    print(
        "scouting report repository: "
        f"reports={result['report_count']} "
        f"ready={result['ready_for_repository']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
