"""Build shadow-only league adapters from ValuCast universal prospect profiles."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.adapters import run_adapters

    result = run_adapters()
    print(
        f"ValuCast prospect league adapters: candidates={result['candidate_count']} "
        f"presets={result['preset_statuses']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
