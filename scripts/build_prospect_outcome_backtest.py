"""Build the unified ValuCast prospect outcome evidence artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.outcome_backtest import run_outcome_backtest

    result = run_outcome_backtest()
    print(
        "ValuCast prospect outcome backtest: "
        f"status={result['status']} "
        f"front_office_grade={result['front_office_grade']} "
        f"score={result['front_office_score']} "
        f"blockers={result['blocker_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
