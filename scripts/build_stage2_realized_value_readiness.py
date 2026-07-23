"""Manually build the research-only Stage 2 readiness artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.realized_value_readiness import (  # noqa: E402
    audit_stage2_realized_value_readiness,
    source_sha256,
)


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
        "--quality-starts",
        type=Path,
        default=ROOT / "data/validation/valucast_stage2_quality_starts.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "data/validation/valucast_stage2_realized_value_readiness.json"
        ),
    )
    args = parser.parse_args()

    input_bytes = args.input.read_bytes()
    report = audit_stage2_realized_value_readiness(
        json.loads(input_bytes),
        _load(args.model),
        _load(args.quality_starts),
        contract_sha256=source_sha256(input_bytes),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "Stage 2 readiness: "
        f"evidence={report['outcome_evidence']['status']} "
        f"overall={report['status']} -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
