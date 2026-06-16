from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    from prospects.peak_calibration import run_peak_calibration_report

    result = run_peak_calibration_report()
    print(
        "Peak calibration report: "
        f"{result['bucket_count']} buckets, "
        f"{result['watch_item_count']} watch items, "
        f"ready={result['ready_for_review']}"
    )
    return 0 if result["ready_for_review"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
