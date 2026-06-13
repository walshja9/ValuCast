"""Export the slim ValuCast DD prospect Statistical Lens feed."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _copy_path() -> Path:
    from prospects.dd_lens_feed import DEFAULT_DD_COPY_PATH

    configured = os.environ.get("DD_PROSPECT_LENS_DEST")
    if not configured:
        return DEFAULT_DD_COPY_PATH
    destination = Path(configured)
    if destination.suffix.lower() == ".json":
        return destination
    return destination / "valucast_prospect_lens.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--copy-to-dd",
        action="store_true",
        help="Atomically copy the validated feed to DD_PROSPECT_LENS_DEST.",
    )
    args = parser.parse_args()

    from prospects.dd_lens_feed import copy_feed, run_feed

    result = run_feed()
    suffix = ""
    if args.copy_to_dd:
        payload = json.loads(Path(result["artifact_path"]).read_text(encoding="utf-8"))
        suffix = f" copied={copy_feed(payload, _copy_path())}"
    print(
        f"ValuCast DD prospect lens: gate={result['research_gate']} "
        f"candidates={result['candidate_count']} -> {result['artifact_path']}{suffix}"
    )


if __name__ == "__main__":
    main()
