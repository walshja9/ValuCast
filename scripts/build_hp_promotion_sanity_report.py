"""Build the ValuCast H+P promotion sanity report."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from projections.promotion_sanity import run_promotion_sanity_report  # noqa: E402


def main() -> None:
    result = run_promotion_sanity_report()
    print(
        "H+P promotion sanity report: "
        f"projections={result['projection_count']} "
        f"opt_in_ready={result['ready_for_opt_in_source']} "
        f"default_ready={result['ready_for_default_promotion']} -> "
        f"{result['artifact_path']}"
    )


if __name__ == "__main__":
    main()
