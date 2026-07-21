#!/usr/bin/env python3
"""Build the research-only fold-local prospect impact OOF artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prospects.impact_oof import (  # noqa: E402
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DEFAULT_BOOTSTRAP_SEED,
    build_impact_oof_report,
    validate_impact_oof_report,
)
from prospects.input_contract import VALUCAST_INPUT_PATH  # noqa: E402
from prospects.model import load_input_contract  # noqa: E402

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_impact_oof_scores.json"


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=VALUCAST_INPUT_PATH)
    parser.add_argument("--output", type=Path, default=ARTIFACT_PATH)
    parser.add_argument("--generated-at")
    parser.add_argument("--seed", type=int, default=DEFAULT_BOOTSTRAP_SEED)
    parser.add_argument(
        "--resamples",
        type=int,
        default=DEFAULT_BOOTSTRAP_RESAMPLES,
    )
    args = parser.parse_args()

    source_bytes = args.input.read_bytes()
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    report = build_impact_oof_report(
        load_input_contract(args.input),
        generated_at=args.generated_at,
        bootstrap_seed=args.seed,
        bootstrap_resamples=args.resamples,
        source_file_sha256=source_hash,
    )
    errors = validate_impact_oof_report(
        report, source_file_sha256=source_hash
    )
    if errors:
        raise SystemExit("invalid impact OOF report: " + ", ".join(errors))
    _write_atomic(args.output, report)
    print(
        f"impact OOF: players={len(report['rows'])} "
        f"folds={len(report['folds'])} -> {args.output}"
    )


if __name__ == "__main__":
    main()
