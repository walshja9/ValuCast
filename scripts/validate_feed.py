#!/usr/bin/env python3
"""Pre-deploy gate: fail the build if the committed DD feed is invalid.

Wired into render.yaml's buildCommand. A non-zero exit fails the candidate
deploy, so Render keeps the prior healthy deployment live.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from web.feed_validation import validate_dd_feed  # noqa: E402

FEED = ROOT / "data" / "dd" / "dd_dynasty_feed.json"


def main() -> int:
    problems = validate_dd_feed(FEED)
    if problems:
        print(f"FEED VALIDATION FAILED for {FEED}:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print(f"Feed valid: {FEED}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
