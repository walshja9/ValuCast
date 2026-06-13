"""Build the shadow-only Diamond Dynasties 7x7 prospect adapter."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.dd_adapter import run_dd_adapter

    result = run_dd_adapter()
    print(
        f"ValuCast DD 7x7 prospect adapter: gate={result['research_gate']} "
        f"candidates={result['candidate_count']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
