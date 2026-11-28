"""Synthetic contracts for the separate Dynasty release dry run."""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from scripts import run_daily_public_build as daily
from scripts import validate_dynasty_only_release as policy


ROOT = Path(__file__).resolve().parents[1]
TODAY = date(2026, 11, 27)
MONITOR = "scripts/validate_valucast_buys_monitor.py"
GOVERNOR = "scripts/validate_valucast_quality_governor.py"
BUY_PROOFS = (
    "-m", "pytest", "-q",
    "tests/test_buy_consumer_approval.py",
    "tests/test_buy_png_cache.py",
    "tests/test_buy_suppression_overnight.py",
)
PATHS = {
    "monitor": "data/models/valucast_prospect_buys_monitor.json",
    "governor": "data/models/valucast_quality_governor.json",
    "snapshot": "data/public/public_dynasty_snapshot.json",
    "buys": "data/models/valucast_prospect_buys.json",
    "review": "data/models/valucast_prospect_buys_review.json",
}
VALIDATOR_FIXTURES = {Path(MONITOR).name: "monitor", Path(GOVERNOR).name: "governor"}


def fixture_payloads():
    stamp = TODAY.isoformat() + "T10:00:00+00:00"
    no_receipt = "No qualified Buy approval receipt."
    prelim = "Pitcher representation exceeds the publication range."
    surface = {"dynasty": True, "movers": True, "buys": False, "prospects": False}
    blockers = {"dynasty": [], "movers": [], "buys": [no_receipt], "prospects": [prelim]}
    checks = [
        {"id": check, "surface": "dynasty", "status": "passed"}
        for check in (
            "mlb_top_value_gap", "mlb_projection_stability_outliers",
            "mlb_top_board_role_shape", "two_way_identity_policy",
            "dd_score_source_audit",
        )
    ]
    checks += [
        {"id": "movers_surface_gate", "status": "passed"},
        {"id": "buy_promotion_gate", "status": "blocked",
         "metrics": {"approval_receipt_qualified": False}},
        {"id": "prospect_top_board_role_shape", "surface": "prospects", "status": "blocked",
         "metrics": {"top25_n": 25, "top50_n": 50, "top25_evaluated_count": 25,
                     "top50_evaluated_count": 50, "top25_sample_ready": True, "top50_sample_ready": True,
                     "max_top25_pitcher_count": 7, "max_top50_pitcher_rate": 0.3,
                     "top25_pitcher_count": 12, "top50_pitcher_count": 20, "top50_pitcher_rate": 0.4}},
        {"id": "prospect_transition_continuity", "surface": "prospects", "status": "passed",
         "metrics": {"sample_ready": True, "baseline_date": "2026-11-26",
                     "current_date": TODAY.isoformat(), "evaluated_matched_row_count": 100,
                     "incident_count": 0}},
    ]
    governor = {
        "generated_at": stamp, "artifact": "valucast_quality_governor",
        "governor_version": "fixture-1", "status": "blocked",
        "surface_readiness": surface, "surface_blockers": blockers, "checks": checks,
        "ready_for_public_snapshot": False, "ready_for_buys_promotion": False,
        "ready_for_movers": True,
    }
    monitor = {
        "generated_at": stamp, "artifact": "valucast_prospect_buys_monitor", "status": "blocked",
        "source_policy": dict.fromkeys(("feeds_model_score", "feeds_buy_score", "feeds_public_rank",
                                        "dd_values_used", "dd_ranks_used", "external_rankings_used",
                                        "market_values_used"), False),
        "monitor_contract": {"monitors_live_buys_v1": True, "mutates_buy_scores": False,
                             "uses_valucast_archives_only": True},
        "monitoring": {"feeds_live_buys": False, "ready_for_live_consumers": False,
                       "buy_comparison_count": 0, "observation_span_days": 0},
        "validation": {"ready_for_monitoring": False, "blockers": [no_receipt]},
        "input_artifacts": {"buy_signal_version": "1.0.0"}, "recommendations": [],
    }
    snapshot = {
        "generated_at": stamp, "quality_governor": governor,
        "validation": {"quality_governor": governor, "surface_readiness": surface,
                       "surface_blockers": blockers, "local_surface_blockers": {"dynasty": []},
                       "cross_universe_value_scale_compatibility_certified": True,
                       "same_day_freshness": True, "required_fields_complete": True,
                       "ready_for_live_consumers": False, "ready_for_all_public_surfaces": False,
                       "quality_governor_ready": False},
    }
    return {"monitor": monitor, "governor": governor, "snapshot": snapshot,
            "buys": {"generated_at": stamp, "promotion": {"feeds_live_buys": False},
                     "validation": {"ready_for_live_consumers": False}},
            "review": {"generated_at": stamp, "review_status": "blocked", "approval_receipt": None}}


def write_payloads(root, payloads):
    for name, value in payloads.items():
        path = root / PATHS[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    original_run = subprocess.run
    actual_validators = []
    commands = []
    overrides = {}

    def run(command, **kwargs):
        args = tuple(map(str, command))
        assert args[0] == sys.executable
        step = args[1:]
        commands.append(step)
        name = Path(step[0]).name
        if name in VALIDATOR_FIXTURES:
            target = tmp_path / PATHS[VALIDATOR_FIXTURES[name]]
            result = original_run(
                [sys.executable, str(ROOT / "scripts" / name), "--path", str(target)],
                cwd=tmp_path, capture_output=True, text=True,
            )
            actual_validators.append(result)
            if name in overrides:
                result = overrides[name]()
            if not kwargs.get("text") and not kwargs.get("encoding") and not kwargs.get("universal_newlines"):
                result = subprocess.CompletedProcess(
                    result.args, result.returncode, result.stdout.encode(), result.stderr.encode(),
                )
        else:
            assert step in daily.VALIDATE_STEPS or step[:2] == ("-m", "pytest")
            exit_code = overrides.get(name, lambda: 0)()
            empty = "" if kwargs.get("text") or kwargs.get("encoding") else b""
            result = subprocess.CompletedProcess(args, exit_code, empty, empty)
        if kwargs.get("check"):
            result.check_returncode()
        return result

    monkeypatch.setattr(policy.subprocess, "run", run)
    return tmp_path, commands, actual_validators, overrides


def test_dynasty_dry_run_accepts_only_the_real_buy_hold(fixture):
    root, commands, actual, _ = fixture
    write_payloads(root, fixture_payloads())

    result = policy.evaluate(root, TODAY)

    assert result["dynasty_eligible"] is True
    assert result["ordinary_publication_eligible"] is False
    assert result["publication_authorized"] is False
    assert result["issues"] == []
    assert [r.returncode for r in actual] == [1, 1]
    assert "monitoring.feeds_live_buys must be true" in actual[0].stdout
    assert "monitoring.ready_for_live_consumers must be true" in actual[0].stdout
    assert "quality governor blocks a live-serving surface: Buys" in actual[1].stdout
    expected_commands = [*daily.VALIDATE_STEPS, BUY_PROOFS]
    assert commands == expected_commands
    assert [tuple(check["command"]) for check in result["checks"]] == expected_commands
    assert sum(check["exit_code"] == 1 for check in result["checks"]) == 2


def test_ordinary_validation_still_stops_at_buy_monitor(fixture):
    root, commands, actual, _ = fixture
    write_payloads(root, fixture_payloads())

    with pytest.raises(subprocess.CalledProcessError) as exc:
        daily.run_stage("validate")

    assert exc.value.returncode == 1
    assert commands[-1] == (MONITOR,)
    assert (GOVERNOR,) not in commands
    assert len(actual) == 1


@pytest.mark.parametrize("fault", ["monitor_error", "tail_failure", "tail_missing", "buy_open",
                                   "prospects_open", "cap_drift", "transition_no_prior",
                                   "transition_no_match", "stale", "candidate_mutated",
                                   "qualified_buy_receipt", "readiness_string", "readiness_absent",
                                   "embedded_governor_mismatch", "dynasty_core_failure",
                                   "monitor_crash", "invalid_timestamp", "timestamp_crosses_utc_day",
                                   "omitted_validator"])
def test_policy_rejects_extra_failure_or_missing_evidence(fixture, fault, monkeypatch):
    root, _, actual, overrides = fixture
    payloads = fixture_payloads()
    if fault == "monitor_error":
        payloads["monitor"]["source_policy"]["feeds_model_score"] = True
    elif fault == "tail_failure":
        overrides["validate_front_office_report.py"] = lambda: 1
    elif fault == "tail_missing":
        def cannot_start():
            raise FileNotFoundError("synthetic subprocess unavailable")
        overrides["validate_front_office_report.py"] = cannot_start
    elif fault == "buy_open":
        payloads["buys"]["promotion"]["feeds_live_buys"] = True
    elif fault == "prospects_open":
        payloads["snapshot"]["validation"]["surface_readiness"]["prospects"] = True
    elif fault == "cap_drift":
        payloads["governor"]["checks"][-2]["metrics"]["max_top25_pitcher_count"] = 8
    elif fault == "transition_no_prior":
        payloads["governor"]["checks"][-1]["metrics"].update(sample_ready=False, baseline_date=None)
    elif fault == "transition_no_match":
        payloads["governor"]["checks"][-1]["metrics"]["evaluated_matched_row_count"] = 0
    elif fault == "qualified_buy_receipt":
        payloads["review"]["approval_receipt"] = {
            "schema_version": "1.0.0",
            "origin": "explicit_manual_input",
            "scope": "valucast_owned_buys_promotion_v1",
            "approved_at": TODAY.isoformat() + "T00:00:00+00:00",
        }
    elif fault == "readiness_string":
        payloads["governor"]["surface_readiness"]["dynasty"] = "true"
    elif fault == "readiness_absent":
        del payloads["governor"]["surface_readiness"]["buys"]
    elif fault == "embedded_governor_mismatch":
        payloads["snapshot"]["quality_governor"] = {
            **payloads["governor"], "governor_version": "different-version",
        }
    elif fault == "dynasty_core_failure":
        payloads["governor"]["checks"][0]["status"] = "blocked"
    elif fault == "stale":
        payloads["snapshot"]["generated_at"] = "2026-11-26T10:00:00+00:00"
    elif fault == "monitor_crash":
        overrides[Path(MONITOR).name] = lambda: subprocess.CompletedProcess(
            [sys.executable, MONITOR], 1, "", "Traceback: synthetic monitor process failure",
        )
    elif fault == "invalid_timestamp":
        payloads["snapshot"]["generated_at"] = "2026-11-27junk"
    elif fault == "timestamp_crosses_utc_day":
        payloads["snapshot"]["generated_at"] = "2026-11-27T23:59:59-08:00"
    elif fault == "omitted_validator":
        missing = ("scripts/validate_front_office_report.py",)
        monkeypatch.setattr(policy, "VALIDATE_STEPS", [step for step in daily.VALIDATE_STEPS if step != missing])
    elif fault == "candidate_mutated":
        def mutate():
            path = root / PATHS["snapshot"]
            path.write_bytes(path.read_bytes() + b"\n")
            return 0
        overrides["validate_front_office_report.py"] = mutate
    write_payloads(root, payloads)

    result = policy.evaluate(root, TODAY)

    assert result["dynasty_eligible"] is False
    assert result["ordinary_publication_eligible"] is False
    assert result["publication_authorized"] is False
    assert result["issues"]
    if fault == "monitor_error":
        assert actual[0].returncode == 1
        assert "source_policy.feeds_model_score must be false" in actual[0].stdout
    if fault == "monitor_crash":
        assert actual[0].returncode == 1
        assert "monitoring.ready_for_live_consumers must be true" in actual[0].stdout
