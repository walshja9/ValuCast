"""Build the ValuCast front-office failure report."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.front_office_failures import run_front_office_failures

    result = run_front_office_failures()
    print(
        "ValuCast front-office failures: "
        f"status={result['status']} "
        f"blocking={result['blocking_finding_count']} "
        f"evidence_gates={result['evidence_gate_count']} "
        f"risks={result['front_office_risk_count']} "
        f"v07_disagreements={result['v0_7_disagreement_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
