"""Build ValuCast's observe-only proprietary prospect model."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.model import run_model

    result = run_model()
    print(
        f"ValuCast Prospect Model: gate={result['gate']} "
        f"impact_gate={result['impact_gate']} "
        f"candidates={result['candidates']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
