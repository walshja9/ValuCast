"""Run the fresh-input-gated ValuCast prospect shadow pipeline."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--force",
        action="store_true",
        help="Rebuild even when the latest completed run used the same input fingerprint.",
    )
    args = parser.parse_args()

    from prospects.forward_shadow import run_pipeline

    result = run_pipeline(force=args.force)
    print(
        f"ValuCast prospect shadow pipeline: status={result['status']} "
        f"reason={result['reason']} date={result['date']} "
        f"forward={result['forward_observation_status']}"
    )


if __name__ == "__main__":
    main()
