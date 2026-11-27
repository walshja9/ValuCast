"""Build ValuCast's rank-free universal prospect outcome profiles."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.universal import run_model

    result = run_model()
    print(
        f"ValuCast Universal Prospect Model: status={result['research_status']} "
        f"targets={result['target_status_counts']} "
        f"candidates={result['candidates']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
