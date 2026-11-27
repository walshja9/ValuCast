"""Validate the observe-only prospect cross-role shadow artifact."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main() -> int:
    from prospects.cross_role_shadow import ARTIFACT_PATH, validate_cross_role_shadow

    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args()
    try:
        payload = json.loads(args.path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"PROSPECT CROSS-ROLE SHADOW VALIDATION FAILED: {exc}")
        return 1
    problems = validate_cross_role_shadow(payload)
    if problems:
        print("PROSPECT CROSS-ROLE SHADOW VALIDATION FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"prospect cross-role shadow: status={payload['status']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
