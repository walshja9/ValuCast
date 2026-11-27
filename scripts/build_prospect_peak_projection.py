"""Build the ValuCast Prospect Peak Projection v1 artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.peak_projection import run_peak_projection

    result = run_peak_projection()
    print(
        "ValuCast prospect peak projection v1: "
        f"ready_for_card_v2={result['ready_for_card_v2']} "
        f"projections={result['projection_count']} "
        f"top200_projection_coverage={result['top200_projection_coverage']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
