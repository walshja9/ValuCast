"""Build the shadow-only ValuCast Universal Prospect Index."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.index import run_index

    result = run_index()
    print(
        f"ValuCast Universal Prospect Index: gate={result['research_gate']} "
        f"candidates={result['candidate_count']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
