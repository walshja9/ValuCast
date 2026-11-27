"""Build the ValuCast front-office readiness report."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.front_office_report import run_front_office_report

    result = run_front_office_report()
    print(
        "ValuCast front-office report: "
        f"status={result['status']} "
        f"grade={result['grade']} "
        f"score={result['score']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
