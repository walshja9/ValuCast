"""Build the candidate shadow ValuCast Prospect Rank v1 artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.rank_v1 import run_prospect_rank_v1

    result = run_prospect_rank_v1()
    print(
        "ValuCast Prospect Rank v1: "
        f"live={result['live_consumer']} "
        f"ranked={result['ranked_count']}/{result['candidate_count']} "
        f"coverage={result['coverage_rate']:.1%} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
