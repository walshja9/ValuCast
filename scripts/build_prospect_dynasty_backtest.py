"""Build historical promotion evidence for the prospect dynasty layer."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.dynasty_backtest import run_backtest

    result = run_backtest()
    print(
        f"ValuCast prospect dynasty backtest: gate={result['research_gate']} "
        f"roles={result['role_gates']} samples={result['samples']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
