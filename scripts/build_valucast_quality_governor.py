"""Build the ValuCast quality-governor artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from quality.valucast_governor import run_quality_governor  # noqa: E402


def main() -> None:
    result = run_quality_governor()
    print(
        "ValuCast quality governor: "
        f"snapshot_ready={result['ready_for_public_snapshot']} "
        f"buys_ready={result['ready_for_buys_promotion']} "
        f"blockers={result['blocker_count']} "
        f"buy_blockers={result['buy_blocker_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()

