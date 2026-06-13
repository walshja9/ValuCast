"""Build the historical promotion evidence for ValuCast prospect adapters."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.adapter_backtest import run_backtest

    result = run_backtest()
    print(
        f"ValuCast prospect adapter backtest: gate={result['adapter_research_gate']} "
        f"roles={result['role_gates']} samples={result['samples']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
