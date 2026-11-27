#!/usr/bin/env python3
"""Validate the research-only fold-local prospect impact OOF artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prospects.impact_oof import validate_impact_oof_report  # noqa: E402
from prospects.input_contract import VALUCAST_INPUT_PATH  # noqa: E402

ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_impact_oof_scores.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    parser.add_argument("--input", type=Path, default=VALUCAST_INPUT_PATH)
    args = parser.parse_args()
    report = json.loads(args.path.read_text(encoding="utf-8"))
    source_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    errors = validate_impact_oof_report(
        report, source_file_sha256=source_hash
    )
    if errors:
        raise SystemExit("invalid impact OOF report: " + ", ".join(errors))
    print(
        f"impact OOF valid: players={len(report.get('rows') or [])} "
        f"folds={len(report.get('folds') or [])}"
    )


if __name__ == "__main__":
    main()
