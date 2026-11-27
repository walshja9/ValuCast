"""Build ValuCast's observe-only pooled-line prospect shadow artifact."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    from prospects.pooled_shadow import run_pooled_shadow

    result = run_pooled_shadow()
    print(
        f"ValuCast Pooled Shadow: status={result['status']} "
        f"scored={result['scored_count']} "
        f"shadowed={result['shadowed_count']} "
        f"multi_level={result['multi_level_count']} "
        f"nontrivial_delta={result['nontrivial_delta_count']} "
        f"-> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
