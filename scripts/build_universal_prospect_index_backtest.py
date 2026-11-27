"""Build historical evidence for the ValuCast Universal Prospect Index."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.dynasty import BACKTEST_PATH as DYNASTY_BACKTEST_PATH
    from prospects.index_backtest import run_backtest

    result = run_backtest(dynasty_backtest_path=DYNASTY_BACKTEST_PATH)
    print(
        f"ValuCast Universal Prospect Index backtest: gate={result['research_gate']} "
        f"combined={result['combined_gate']} sample={result['sample_size']} "
        f"folds={result['fold_count']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
