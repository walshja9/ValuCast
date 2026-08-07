#!/usr/bin/env python3
"""Fail unless every daily public ValuCast data artifact is current."""
from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VALUCAST_PROSPECT_INPUTS = ROOT / "data" / "prospects" / "prospect_model_inputs.json"
REDRAFT_METADATA = ROOT / "data" / "projections" / "metadata.json"
REDRAFT_CURRENT = ROOT / "data" / "projections" / "current.json"
REDRAFT_ROS = ROOT / "data" / "projections" / "ros.json"
ACTUALS = ROOT / "data" / "actuals" / "current.json"
STATCAST = ROOT / "data" / "statcast" / "percentiles.json"
MLB_DYNASTY_LAYER = ROOT / "data" / "models" / "valucast_mlb_dynasty_layer.json"
MLB_AVAILABILITY = ROOT / "data" / "models" / "valucast_mlb_availability.json"
MLB_ROSTER_STATUS = ROOT / "data" / "models" / "valucast_mlb_roster_status.json"
MLB_TRACK_RECORD = ROOT / "data" / "models" / "valucast_mlb_track_record.json"
VALUCAST_BUYS = ROOT / "data" / "models" / "valucast_prospect_buys.json"
PROSPECT_LEAGUE_ADAPTERS = ROOT / "data" / "models" / "valucast_prospect_league_adapters.json"
VALUCAST_MOVERS = ROOT / "data" / "models" / "valucast_prospect_movers.json"
VALUCAST_RECEIPTS = ROOT / "data" / "models" / "valucast_call_up_receipts.json"
VALUCAST_BUYS_MONITOR = (
    ROOT / "data" / "models" / "valucast_prospect_buys_monitor.json"
)
VALUCAST_QUALITY_GOVERNOR = ROOT / "data" / "models" / "valucast_quality_governor.json"
MILB_STAT_FRESHNESS_AUDIT = (
    ROOT / "data" / "models" / "valucast_milb_stat_freshness_audit.json"
)
PROSPECT_CARD_DATA_AUDIT = (
    ROOT / "data" / "models" / "valucast_prospect_card_data_audit.json"
)
RECENT_SIGNAL_REPORT = (
    ROOT / "data" / "models" / "valucast_recent_signal_report.json"
)
POOLED_SHADOW = ROOT / "data" / "models" / "valucast_pooled_shadow.json"
RECENT_FORM_SIGNAL = (
    ROOT / "data" / "models" / "valucast_recent_form_signal.json"
)
CALL_UP_PULSE = (
    ROOT / "data" / "models" / "valucast_call_up_pulse.json"
)
AHEAD_OF_CONSENSUS_SCORECARD = (
    ROOT / "data" / "models" / "valucast_ahead_of_consensus_scorecard.json"
)
PIPELINE_OBSERVABILITY = (
    ROOT / "data" / "models" / "valucast_pipeline_observability.json"
)
PROSPECT_MODEL_V07 = ROOT / "data" / "models" / "valucast_prospect_model_v0_7.json"
PROSPECT_OUTCOME_BACKTEST = (
    ROOT / "data" / "models" / "valucast_prospect_outcome_backtest.json"
)
PROSPECT_CROSS_ROLE_SHADOW = (
    ROOT / "data" / "models" / "valucast_prospect_cross_role_shadow.json"
)
RAW_DATA_INDEPENDENCE_AUDIT = (
    ROOT / "data" / "models" / "valucast_raw_data_independence_audit.json"
)
FRONT_OFFICE_REPORT = ROOT / "data" / "models" / "valucast_front_office_report.json"
FRONT_OFFICE_FAILURES = (
    ROOT / "data" / "models" / "valucast_front_office_failures.json"
)
PROSPECT_AVAILABILITY = (
    ROOT / "data" / "models" / "valucast_prospect_availability.json"
)
PROSPECT_CALIBRATION_REPORT = (
    ROOT / "data" / "models" / "valucast_prospect_calibration_report.json"
)
PROSPECT_PEAK_PROJECTION = (
    ROOT / "data" / "models" / "valucast_prospect_peak_projection_v1.json"
)
PROSPECT_PEAK_CALIBRATION = (
    ROOT / "data" / "models" / "valucast_prospect_peak_projection_calibration.json"
)
PROSPECT_FORWARD_VALIDATION = (
    ROOT / "data" / "models" / "valucast_prospect_forward_validation.json"
)
PROSPECT_COVERAGE_AUDIT = (
    ROOT / "data" / "models" / "valucast_prospect_coverage_audit.json"
)
PLAYING_TIME_ROLE_TRACKER = (
    ROOT / "data" / "models" / "valucast_playing_time_role_tracker.json"
)
SCOUTING_REPORTS = ROOT / "data" / "models" / "valucast_scouting_reports.json"
VALUCAST_PROSPECT_COMPS = ROOT / "data" / "models" / "valucast_prospect_comps.json"
VALUCAST_CONSENSUS_GAP = ROOT / "data" / "models" / "valucast_consensus_gap.json"
VALUCAST_PROSPECT_RANK_V1 = ROOT / "data" / "models" / "valucast_prospect_rank_v1.json"
PUBLIC_SNAPSHOT = ROOT / "data" / "public" / "public_dynasty_snapshot.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _iso_date(value) -> str:
    return str(value or "")[:10]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _within_allowed_age(actual: str, expected_date: str, max_age_days: int) -> bool:
    """True when actual is expected_date or at most max_age_days behind it.

    Future-dated artifacts always fail. Unparseable dates fail.
    """
    if actual == expected_date:
        return True
    if max_age_days <= 0:
        return False
    try:
        actual_d = date.fromisoformat(actual)
        expected_d = date.fromisoformat(expected_date)
    except ValueError:
        return False
    return 0 <= (expected_d - actual_d).days <= max_age_days


def validate_public_data(expected_date: str, max_age_days: int = 0) -> list[str]:
    problems: list[str] = []

    dated_artifacts = [
        (VALUCAST_PROSPECT_INPUTS, "generated_at"),
        (MLB_TRACK_RECORD, "generated_at"),
        (MLB_AVAILABILITY, "generated_at"),
        (MLB_ROSTER_STATUS, "generated_at"),
        (MLB_DYNASTY_LAYER, "generated_at"),
        (PROSPECT_AVAILABILITY, "generated_at"),
        (PROSPECT_CALIBRATION_REPORT, "generated_at"),
        (PROSPECT_PEAK_PROJECTION, "generated_at"),
        (PROSPECT_PEAK_CALIBRATION, "generated_at"),
        (PROSPECT_FORWARD_VALIDATION, "generated_at"),
        (PROSPECT_COVERAGE_AUDIT, "generated_at"),
        (PROSPECT_MODEL_V07, "generated_at"),
        (PROSPECT_OUTCOME_BACKTEST, "generated_at"),
        (PROSPECT_CROSS_ROLE_SHADOW, "generated_at"),
        (RAW_DATA_INDEPENDENCE_AUDIT, "generated_at"),
        (VALUCAST_MOVERS, "generated_at"),
        (VALUCAST_RECEIPTS, "generated_at"),
        (VALUCAST_BUYS, "generated_at"),
        (PROSPECT_LEAGUE_ADAPTERS, "generated_at"),
        (VALUCAST_BUYS_MONITOR, "generated_at"),
        (MILB_STAT_FRESHNESS_AUDIT, "generated_at"),
        (PROSPECT_CARD_DATA_AUDIT, "generated_at"),
        (RECENT_SIGNAL_REPORT, "generated_at"),
        (POOLED_SHADOW, "generated_at"),
        (RECENT_FORM_SIGNAL, "generated_at"),
        (CALL_UP_PULSE, "generated_at"),
        (AHEAD_OF_CONSENSUS_SCORECARD, "generated_at"),
        (VALUCAST_QUALITY_GOVERNOR, "generated_at"),
        (PIPELINE_OBSERVABILITY, "generated_at"),
        (FRONT_OFFICE_FAILURES, "generated_at"),
        (FRONT_OFFICE_REPORT, "generated_at"),
        (PLAYING_TIME_ROLE_TRACKER, "generated_at"),
        (SCOUTING_REPORTS, "generated_at"),
        (VALUCAST_PROSPECT_COMPS, "generated_at"),
        (VALUCAST_CONSENSUS_GAP, "generated_at"),
        (VALUCAST_PROSPECT_RANK_V1, "generated_at"),
        (PUBLIC_SNAPSHOT, "generated_at"),
        (REDRAFT_METADATA, "as_of"),
        (STATCAST, "as_of"),
    ]
    # A dated-but-empty artifact passes a date-only gate: a builder that emits
    # {"generated_at": today, "players": []} validated "fresh" (7/2 audit).
    # These payload lists can never legitimately be near-empty. Each artifact
    # maps to a tuple of (key, floor) pairs so one file can floor several keys.
    min_rows = {
        MLB_DYNASTY_LAYER: (("players", 300),),
        MLB_ROSTER_STATUS: (("profiles", 300),),
        PROSPECT_MODEL_V07: (("candidates", 500),),
        PROSPECT_PEAK_PROJECTION: (("projections", 500),),
        VALUCAST_PROSPECT_COMPS: (("players", 20),),
        VALUCAST_CONSENSUS_GAP: (("higher", 3), ("lower", 3)),
        VALUCAST_PROSPECT_RANK_V1: (("board", 1500),),
    }
    for path, field in dated_artifacts:
        try:
            payload = _load(path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{_display_path(path)} unreadable: {exc}")
            continue
        actual = _iso_date(payload.get(field))
        if not _within_allowed_age(actual, expected_date, max_age_days):
            problems.append(
                f"{_display_path(path)} {field}={actual or 'missing'}, "
                f"expected {expected_date}"
                + (f" (allowed lag {max_age_days}d)" if max_age_days else "")
            )
        for key, floor in min_rows.get(path, ()):
            n = len(payload.get(key) or [])
            if n < floor:
                problems.append(
                    f"{_display_path(path)} {key} has {n} rows (< {floor}) -- "
                    "dated-fresh but semantically empty"
                )
        # The actuals metadata re-stamps as_of=today daily, so a stale-season
        # scrape can pass the date gate while silently serving last year's stats.
        # Assert the recorded season matches the expected year (env override lets
        # an intentional cross-year backfill through).
        if path is REDRAFT_METADATA and not os.environ.get("VALUCAST_ACTUALS_SEASON"):
            season = payload.get("season")
            if season is None:
                problems.append(
                    f"{_display_path(path)} season is missing -- "
                    "cannot verify actuals are current-year"
                )
            elif int(season) != int(expected_date[:4]):
                problems.append(
                    f"{_display_path(path)} season={season}, "
                    f"expected {expected_date[:4]}"
                )

    list_artifacts = [REDRAFT_CURRENT, REDRAFT_ROS]
    for path in list_artifacts:
        try:
            payload = _load(path)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"{_display_path(path)} unreadable: {exc}")
            continue
        if not isinstance(payload, list) or not payload:
            problems.append(f"{_display_path(path)} has no player rows")

    # Actuals carries its date per-row in metadata.as_of. Assert it's current so a
    # stale current-stats scrape can't pass the gate while metadata.json re-stamps today.
    try:
        actuals = _load(ACTUALS)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"{_display_path(ACTUALS)} unreadable: {exc}")
    else:
        if not isinstance(actuals, list) or not actuals:
            problems.append(f"{_display_path(ACTUALS)} has no player rows")
        else:
            actual = _iso_date((actuals[0].get("metadata") or {}).get("as_of"))
            if not _within_allowed_age(actual, expected_date, max_age_days):
                problems.append(
                    f"{_display_path(ACTUALS)} metadata.as_of={actual or 'missing'}, "
                    f"expected {expected_date}"
                    + (f" (allowed lag {max_age_days}d)" if max_age_days else "")
                )

    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date",
        default=os.environ.get("VALUCAST_REFRESH_DATE", date.today().isoformat()),
    )
    # PR/push CI runs between UTC midnight and the morning refresh with
    # yesterday's committed artifacts; a bounded lag keeps that check green
    # without letting genuinely stale data through. The publish path leaves
    # this unset (0 = exact same-day, unchanged behavior).
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=int(os.environ.get("VALUCAST_FRESHNESS_MAX_AGE_DAYS", "0")),
    )
    args = parser.parse_args()

    problems = validate_public_data(args.date, max_age_days=args.max_age_days)
    if problems:
        print("PUBLIC DATA FRESHNESS FAILED:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print(f"All daily public data artifacts are current for {args.date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
