"""Build the shadow ValuCast Prospect Model v0.7 preview artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.model_v07 import run_model_v07_preview

    result = run_model_v07_preview()
    print(
        "ValuCast prospect model v0.7 preview: "
        f"ready_for_backtest={result['ready_for_backtest']} "
        f"candidates={result['candidate_count']} "
        f"top200_factual_context_coverage="
        f"{result['top200_factual_context_coverage']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
