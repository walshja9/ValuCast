#!/usr/bin/env python3
"""Build the advisory MLB projection-source comparison (Marcel/H+P vs Steamer/ROS).

Freezes both pure projection sources daily and scores the oldest freeze against current
actuals. Advisory only — never flips the live dynasty source.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from mlb.projection_source_comparison import run_projection_source_comparison  # noqa: E402


def main() -> None:
    payload = run_projection_source_comparison()
    basis = payload["comparison_basis"]
    gate = payload["gate"]
    print(
        "ValuCast MLB projection-source comparison: "
        f"gate={gate['status']} horizon={basis['horizon_days']}d "
        f"scoreable={basis['scoreable_players']} "
        f"marcel_mean_ratio={payload['scores'].get('marcel_mean_ratio_vs_steamer')} "
        f"marcel_beats_steamer={payload['marcel_beats_steamer']}"
    )


if __name__ == "__main__":
    main()
