"""Build the ValuCast raw-data independence audit."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.raw_data_independence import run_raw_data_independence_audit

    result = run_raw_data_independence_audit()
    print(
        "ValuCast raw-data independence audit: "
        f"status={result['status']} "
        f"direct_raw_ownership_score={result['direct_raw_ownership_score']} "
        f"blockers={result['blocker_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
