"""Build ValuCast's observe-only per-level combined prospect shadow artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.combined_level_shadow import run_combined_level_shadow

    result = run_combined_level_shadow()
    print(
        f"ValuCast Combined-Level Shadow: status={result['status']} "
        f"scored={result['scored_count']} "
        f"shadowed={result['shadowed_count']} "
        f"multi_level={result['multi_level_count']} "
        f"nontrivial_delta={result['nontrivial_delta_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
