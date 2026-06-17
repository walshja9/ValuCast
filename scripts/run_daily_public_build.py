"""Run ValuCast's staged daily public-data build.

The GitHub workflow owns checkout, dependency install, input refresh, git add,
commit, and push. This script owns the ordered build and validation stages so
the command graph is testable outside YAML.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter


BUILD_STEPS: list[tuple[str, ...]] = [
    ("scripts/backfill_projection_identities.py",),
    (
        "scripts/backfill_projection_identities.py",
        "--projection-path",
        "projections/runs/valucast_hp_2026_v1/projections.json",
    ),
    ("scripts/build_mlb_track_record.py",),
    ("scripts/build_mlb_availability.py",),
    ("scripts/build_hp_promotion_sanity_report.py",),
    ("scripts/build_mlb_dynasty_layer.py",),
    ("scripts/build_mlb_roster_status.py",),
    ("scripts/build_playing_time_role_tracker.py",),
    ("scripts/run_prospect_shadow_pipeline.py",),
    ("scripts/build_prospect_universe.py",),
    ("scripts/build_prospect_availability.py",),
    ("scripts/build_prospect_rank_v1.py",),
    ("scripts/build_prospect_model_v07.py",),
    ("scripts/build_prospect_coverage_audit.py",),
    ("scripts/build_prospect_calibration_report.py",),
    ("scripts/build_prospect_peak_projection.py",),
    ("scripts/build_prospect_peak_calibration_report.py",),
    ("scripts/build_valucast_buys.py",),
    ("scripts/review_valucast_buys.py",),
    ("scripts/build_valucast_buys.py", "--with-review"),
    ("scripts/build_prospect_forward_validation.py",),
    ("scripts/build_valucast_buys_monitor.py",),
    ("scripts/build_prospect_outcome_backtest.py",),
    ("scripts/build_front_office_failures.py",),
    ("scripts/build_raw_data_independence_audit.py",),
    ("scripts/build_public_dynasty_snapshot.py",),
    ("scripts/build_milb_stat_freshness_audit.py",),
    ("scripts/build_prospect_card_data_audit.py",),
    ("scripts/build_recent_signal_report.py",),
    ("scripts/build_scouting_repository.py",),
    ("scripts/build_valucast_quality_governor.py",),
    ("scripts/build_pipeline_observability.py",),
    ("scripts/build_front_office_report.py",),
]


VALIDATE_STEPS: list[tuple[str, ...]] = [
    ("scripts/validate_feed.py",),
    ("scripts/validate_mlb_track_record.py",),
    ("scripts/validate_hp_promotion_sanity_report.py",),
    ("scripts/validate_mlb_availability.py",),
    ("scripts/validate_playing_time_role_tracker.py",),
    ("scripts/validate_mlb_roster_status.py",),
    ("scripts/validate_valucast_prospect_inputs.py",),
    ("scripts/validate_prospect_availability.py",),
    ("scripts/validate_prospect_model_v07.py",),
    ("scripts/validate_prospect_coverage_audit.py",),
    ("scripts/validate_prospect_calibration_report.py",),
    ("scripts/validate_prospect_peak_projection.py",),
    ("scripts/validate_prospect_peak_calibration_report.py",),
    ("scripts/validate_prospect_forward_validation.py",),
    ("scripts/validate_prospect_outcome_backtest.py",),
    ("scripts/validate_front_office_failures.py",),
    ("scripts/validate_raw_data_independence_audit.py",),
    ("scripts/validate_milb_stat_freshness_audit.py",),
    ("scripts/validate_prospect_card_data_audit.py",),
    ("scripts/validate_recent_signal_report.py",),
    ("scripts/validate_valucast_buys.py",),
    ("scripts/validate_valucast_buys_monitor.py",),
    ("scripts/validate_valucast_quality_governor.py",),
    ("scripts/validate_pipeline_observability.py",),
    ("scripts/validate_front_office_report.py",),
    ("scripts/validate_scouting_repository.py",),
    ("scripts/validate_public_dynasty_snapshot.py",),
    ("scripts/validate_public_data_freshness.py",),
    (
        "-m",
        "pytest",
        "-q",
        "tests/test_refresh.py",
        "tests/test_dd_feed_integrity.py",
        "tests/test_public_data_refresh.py",
        "tests/test_public_dynasty_snapshot.py",
        "tests/test_valucast_quality_governor.py",
    ),
]


STAGES = {
    "build": BUILD_STEPS,
    "validate": VALIDATE_STEPS,
}


def _duplicate_steps(steps: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
    counts = Counter(steps)
    return [step for step, count in counts.items() if count > 1]


def validate_steps() -> None:
    for stage, steps in STAGES.items():
        duplicates = _duplicate_steps(steps)
        if duplicates:
            formatted = ", ".join(" ".join(step) for step in duplicates)
            raise ValueError(f"duplicate {stage} command(s): {formatted}")


def run_stage(stage: str) -> None:
    validate_steps()
    for step in STAGES[stage]:
        cmd = (sys.executable, *step)
        print("+", " ".join(cmd), flush=True)
        subprocess.run(cmd, check=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only",
        choices=("all", "build", "validate"),
        default="all",
        help="Run one stage or the full build+validate sequence.",
    )
    args = parser.parse_args(argv)

    stages = ("build", "validate") if args.only == "all" else (args.only,)
    for stage in stages:
        run_stage(stage)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
