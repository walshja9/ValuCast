"""Manually build the prospect realized-value readiness artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.realized_value_readiness import audit_realized_value_readiness  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data/prospects/prospect_model_inputs.json",
    )
    parser.add_argument(
        "--model",
        type=Path,
        default=ROOT / "data/models/valucast_prospect_model.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT / "data/validation/valucast_prospect_realized_value_readiness.json"
        ),
    )
    args = parser.parse_args()
    report = audit_realized_value_readiness(_load(args.input), _load(args.model))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
