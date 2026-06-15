"""Build ValuCast's canonical prospect input contract."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.input_builder import run_valucast_prospect_input_build

    result = run_valucast_prospect_input_build()
    print(
        "ValuCast prospect inputs: "
        f"generated_at={result['generated_at']} "
        f"historical={result['historical_rows']} "
        f"current={result['current_rows']} "
        f"producer={result['producer_owner']} "
        f"upstream={result['upstream_kind']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
