"""Build the ValuCast prospect Buys v1 monitor artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.buys_monitor import run_buys_monitor

    result = run_buys_monitor()
    print(
        "ValuCast prospect buys monitor: "
        f"status={result['status']} "
        f"ready_for_monitoring={result['ready_for_monitoring']} "
        f"buy_comparisons={result['buy_comparison_count']} "
        f"span_days={result['observation_span_days']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
