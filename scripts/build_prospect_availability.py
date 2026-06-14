"""Build the ValuCast prospect availability/risk artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.availability import run_prospect_availability

    result = run_prospect_availability()
    print(
        "ValuCast prospect availability: "
        f"profiles={result['profile_count']} "
        f"risk={result['risk_profile_count']} "
        f"manual_overrides={result['manual_override_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
