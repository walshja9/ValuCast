"""Dry-run the independent Dynasty release policy on an already-built bundle."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.buy_approval import qualified_approval_receipt
from scripts.run_daily_public_build import STAGES, VALIDATE_STEPS, validate_steps
from scripts.validate_valucast_buys_monitor import validate_buys_monitor
from scripts.validate_valucast_quality_governor import validate_governor

CANDIDATE_FILES = {
    "monitor": "data/models/valucast_prospect_buys_monitor.json",
    "governor": "data/models/valucast_quality_governor.json",
    "snapshot": "data/public/public_dynasty_snapshot.json",
    "buys": "data/models/valucast_prospect_buys.json",
    "review": "data/models/valucast_prospect_buys_review.json",
}
MONITOR = "scripts/validate_valucast_buys_monitor.py"
GOVERNOR = "scripts/validate_valucast_quality_governor.py"
HOLD_PROBLEMS = [
    "monitoring.feeds_live_buys must be true",
    "monitoring.ready_for_live_consumers must be true",
]
REQUIRED_VALIDATORS = {
    (MONITOR,),
    (GOVERNOR,),
    ("scripts/validate_valucast_buys.py",),
    ("scripts/validate_valucast_movers.py",),
    ("scripts/validate_pipeline_observability.py",),
    ("scripts/validate_front_office_report.py",),
    ("scripts/validate_scouting_repository.py",),
    ("scripts/validate_public_dynasty_snapshot.py",),
    ("scripts/validate_public_data_freshness.py",),
    (
        "-m", "pytest", "-q", "tests/test_refresh.py", "tests/test_public_data_refresh.py",
        "tests/test_public_dynasty_snapshot.py", "tests/test_valucast_quality_governor.py",
        "tests/test_public_surfaces_smoke.py",
    ),
}
SURFACES = {"dynasty": True, "movers": True, "buys": False, "prospects": False}
DYNASTY_CHECKS = {
    "mlb_top_value_gap",
    "mlb_projection_stability_outliers",
    "mlb_top_board_role_shape",
    "two_way_identity_policy",
    "dd_score_source_audit",
}
SPECIAL_CHECKS = {"buy_promotion_gate", "movers_surface_gate", "buy_top40_public_surface_alignment"}
BUY_CONSUMER_CHECKS = (
    "-m", "pytest", "-q",
    "tests/test_buy_consumer_approval.py",
    "tests/test_buy_png_cache.py",
    "tests/test_buy_suppression_overnight.py",
)


def _object(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def _blocked(value: object) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, str) and v for v in value)


def _day(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 10:
            day = date.fromisoformat(value)
            return day if value == day.isoformat() else None
        timestamp = datetime.fromisoformat(value)
        if timestamp.utcoffset() is not None:
            return timestamp.astimezone(timezone.utc).date()
    except (OverflowError, ValueError):
        return None
    return None


def _flags(values: dict, expected: dict) -> bool:
    return all(values.get(name) is value for name, value in expected.items())


def _read_inputs(root: Path) -> tuple[dict, dict]:
    candidates, fingerprints = {}, {}
    for name, relative in CANDIDATE_FILES.items():
        path = root / relative
        if path.resolve() != path or not path.is_file():
            raise ValueError("Candidate file must be an exact regular path")
        raw = path.read_bytes()
        candidate = json.loads(raw)
        if not isinstance(candidate, dict):
            raise ValueError("Candidate artifact must be an object")
        candidates[name] = candidate
        fingerprints[relative] = hashlib.sha256(raw).hexdigest()
    return candidates, fingerprints


def _held_buys(candidate: dict) -> bool:
    monitor, buys, review = (candidate[name] for name in ("monitor", "buys", "review"))
    validation = _object(monitor.get("validation"))
    return (
        monitor.get("status") == "blocked"
        and _flags(_object(monitor.get("monitoring")), {
            "feeds_live_buys": False, "ready_for_live_consumers": False,
        })
        and validation.get("ready_for_monitoring") is False
        and _blocked(validation.get("blockers"))
        and _object(buys.get("promotion")).get("feeds_live_buys") is False
        and _object(buys.get("validation")).get("ready_for_live_consumers") is False
        and not qualified_approval_receipt(review.get("approval_receipt"))
    )


def _continuity(check: dict, today: date) -> bool:
    metrics = _object(check.get("metrics"))
    prior = _day(metrics.get("baseline_date"))
    matched = metrics.get("evaluated_matched_row_count")
    return (
        check.get("status") == "passed"
        and metrics.get("sample_ready") is True
        and prior is not None and prior < today
        and _day(metrics.get("current_date")) == today
        and type(matched) is int and matched > 0
        and type(metrics.get("incident_count")) is int and metrics["incident_count"] == 0
    )


def _prospect_limits(check: dict) -> bool:
    metrics = _object(check.get("metrics"))
    top25, top50 = (metrics.get(key) for key in ("top25_pitcher_count", "top50_pitcher_count"))
    if type(top25) is not int or type(top50) is not int:
        return False
    return (
        check.get("surface") == "prospects"
        and metrics.get("top25_n") == metrics.get("top25_evaluated_count") == 25
        and metrics.get("top50_n") == metrics.get("top50_evaluated_count") == 50
        and metrics.get("top25_sample_ready") is True and metrics.get("top50_sample_ready") is True
        and metrics.get("max_top25_pitcher_count") == 7
        and metrics.get("max_top50_pitcher_rate") == 0.3
        and 0 <= top25 <= 25 and top25 <= top50 <= top25 + 25
        and metrics.get("top50_pitcher_rate") == round(top50 / 50, 4)
        and check.get("status") == ("blocked" if top25 > 7 or top50 > 15 else "passed")
    )


def _candidate_issues(candidate: dict, today: date) -> list[str]:
    issues = []
    if any(_day(payload.get("generated_at")) != today for payload in candidate.values()):
        issues.append("policy_input_not_current_utc_day")
    if not _held_buys(candidate):
        issues.append("buy_hold_inconsistent")

    governor, snapshot = candidate["governor"], candidate["snapshot"]
    blockers = _object(governor.get("surface_blockers"))
    if not (
        governor.get("status") == "blocked"
        and _flags(_object(governor.get("surface_readiness")), SURFACES)
        and _flags(governor, {
            "ready_for_public_snapshot": False, "ready_for_movers": True,
            "ready_for_buys_promotion": False,
        })
        and blockers.get("dynasty") == blockers.get("movers") == []
        and _blocked(blockers.get("buys")) and _blocked(blockers.get("prospects"))
    ):
        issues.append("independent_surface_state")

    checks = {}
    rows = governor.get("checks")
    for row in rows if isinstance(rows, list) else []:
        row = _object(row)
        key = row.get("id")
        if (
            not isinstance(key, str) or not key or key in checks
            or row.get("status") not in ("passed", "blocked")
            or (key not in SPECIAL_CHECKS and row.get("surface") not in ("dynasty", "prospects", "both"))
        ):
            issues.append("invalid_governor_check")
            continue
        checks[key] = row
    if (
        not DYNASTY_CHECKS <= checks.keys()
        or any(checks[name].get("surface") not in ("dynasty", "both") for name in DYNASTY_CHECKS & checks.keys())
        or any(c["status"] != "passed" for c in checks.values() if c.get("surface") in ("dynasty", "both"))
    ):
        issues.append("dynasty_checks")
    if checks.get("movers_surface_gate", {}).get("status") != "passed":
        issues.append("movers_gate")
    if not _continuity(checks.get("prospect_transition_continuity", {}), today):
        issues.append("transition_continuity")
    if not _prospect_limits(checks.get("prospect_top_board_role_shape", {})):
        issues.append("prospect_pitcher_limits")
    buy_check = checks.get("buy_promotion_gate", {})
    if buy_check.get("status") != "blocked" or _object(buy_check.get("metrics")).get("approval_receipt_qualified") is not False:
        issues.append("buy_approval_gate")

    validation = _object(snapshot.get("validation"))
    if not (
        _flags(_object(validation.get("surface_readiness")), {
            "dynasty": True, "buys": False, "prospects": False,
        })
        and _flags(validation, {
            "ready_for_live_consumers": False, "ready_for_all_public_surfaces": False,
            "quality_governor_ready": False, "same_day_freshness": True,
            "cross_universe_value_scale_compatibility_certified": True,
            "required_fields_complete": True,
        })
        and _object(validation.get("surface_blockers")).get("dynasty") == []
        and _object(validation.get("local_surface_blockers")).get("dynasty") == []
        and snapshot.get("quality_governor") == validation.get("quality_governor") == governor
    ):
        issues.append("snapshot_dynasty_state")
    return issues


def evaluate(root: Path, today: date) -> dict:
    """Record eligibility for the separate lane. This command cannot publish."""
    root = root.resolve()
    result = {
        "policy": "dynasty_only",
        "dry_run_only": True,
        "date": today.isoformat(),
        "dynasty_eligible": False,
        "ordinary_publication_eligible": False,
        "publication_authorized": False,
        "issues": [],
        "checks": [],
    }
    issues, checks = result["issues"], result["checks"]
    try:
        candidate, before = _read_inputs(root)
    except (OSError, ValueError):
        issues.append("unreadable_policy_input")
        return result
    result["policy_input_sha256"] = before
    issues.extend(_candidate_issues(candidate, today))

    if os.environ.get("VALUCAST_ACTUALS_SEASON") or os.environ.get("VALUCAST_BUYS_REVIEW_APPROVED") not in (None, "", "0"):
        issues.append("incompatible_release_environment")
    env = {**os.environ, "VALUCAST_REFRESH_DATE": today.isoformat(), "VALUCAST_FRESHNESS_MAX_AGE_DAYS": "0"}
    validate_steps()
    if VALIDATE_STEPS != STAGES["validate"] or not REQUIRED_VALIDATORS <= set(VALIDATE_STEPS):
        issues.append("canonical_validators_missing")
        return result

    buy_blockers = _object(candidate["governor"].get("surface_blockers")).get("buys")
    expected_governor = (
        ["quality governor blocks a live-serving surface: Buys (" + "; ".join(buy_blockers[:3]) + ")"]
        if _blocked(buy_blockers) else []
    )
    held = {
        (MONITOR,): ("VALUCAST BUYS MONITOR", "monitor", HOLD_PROBLEMS),
        (GOVERNOR,): ("VALUCAST QUALITY GOVERNOR", "governor", expected_governor),
    }
    for step in (*VALIDATE_STEPS, BUY_CONSUMER_CHECKS):
        verdict = held.get(step)
        try:
            output = {"capture_output": True, "text": True} if verdict else {
                "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
            }
            completed = subprocess.run([sys.executable, *step], cwd=root, env=env, check=False, **output)
            exit_code = completed.returncode
            if verdict:
                label, name, problems = verdict
                expected_lines = [f"{label} VALIDATION FAILED for {root / CANDIDATE_FILES[name]}:"]
                expected_lines.extend(f"  - {problem}" for problem in problems)
                if completed.stderr or completed.stdout.splitlines() != expected_lines:
                    issues.append("unrecognized_validator_output:" + step[0])
        except OSError:
            exit_code = None
        checks.append({"command": list(step), "exit_code": exit_code})
        expected = 1 if verdict else 0
        if exit_code != expected:
            issues.append("validator_exit:" + " ".join(step))

    # Preserve real nonzero exits. The separate policy recognizes only the entire known held verdicts.
    try:
        monitor, monitor_problems = validate_buys_monitor(root / CANDIDATE_FILES["monitor"])
        governor, governor_problems = validate_governor(root / CANDIDATE_FILES["governor"])
        if monitor != candidate["monitor"] or monitor_problems != HOLD_PROBLEMS:
            issues.append("unexpected_buy_monitor_verdict")
        if not expected_governor or governor != candidate["governor"] or governor_problems != expected_governor:
            issues.append("unexpected_governor_verdict")
        if _read_inputs(root)[1] != before:
            issues.append("policy_input_changed")
    except (OSError, ValueError, TypeError, AttributeError):
        issues.append("unverifiable_policy_input")
    result["dynasty_eligible"] = not issues
    return result


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    today = datetime.now(timezone.utc).date()
    result = evaluate(ROOT, today)
    if datetime.now(timezone.utc).date() != today:
        result["issues"].append("validation_crossed_utc_day")
        result["dynasty_eligible"] = False
    print(json.dumps(result, indent=2))
    return 0 if result["dynasty_eligible"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
