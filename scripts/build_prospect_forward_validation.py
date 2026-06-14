"""Build the ValuCast prospect forward-validation report."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.forward_validation import run_forward_validation_report

    result = run_forward_validation_report()
    print(
        "ValuCast prospect forward validation: "
        f"status={result['status']} "
        f"rank_comparisons={result['rank_comparison_count']} "
        f"buy_comparisons={result['buy_comparison_count']} "
        f"span_days={result['observation_span_days']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
