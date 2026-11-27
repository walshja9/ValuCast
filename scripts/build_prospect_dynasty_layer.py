"""Build shadow-only dynasty ceiling/risk signals from universal profiles."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.dynasty import run_layer

    result = run_layer()
    print(
        f"ValuCast prospect dynasty layer: gate={result['research_gate']} "
        f"candidates={result['candidate_count']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
