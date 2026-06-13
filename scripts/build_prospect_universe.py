"""Build the ValuCast-owned prospect universe artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.universe import run_universe

    result = run_universe()
    validation = result["validation"]
    print(
        "ValuCast prospect universe: "
        f"candidates={result['candidate_count']} "
        f"duplicates={validation['duplicate_identity_count']} "
        f"missing_mlbam={validation['missing_mlbam_count']} "
        f"dd_context={validation['dd_context_count']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
