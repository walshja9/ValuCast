"""Build the shadow ValuCast MLB dynasty value layer."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from mlb.dynasty import run_mlb_dynasty_layer  # noqa: E402


def main() -> None:
    result = run_mlb_dynasty_layer()
    print(
        "ValuCast MLB dynasty layer: "
        f"rows={result['row_count']} "
        f"missing_mlbam={result['missing_mlbam_count']} "
        f"ready={result['ready_for_live_consumers']} -> {result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
