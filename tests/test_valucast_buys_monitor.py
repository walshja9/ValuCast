"""Tests for ValuCast prospect Buys v1 monitoring."""
import json

from prospects.buys_monitor import build_buys_monitor
from prospects.buys_monitor import run_buys_monitor
from scripts.validate_valucast_buys_monitor import validate_buys_monitor


def _buy_payload(ready=True):
    return {
        "signal_version": "1.0.0",
        "generated_at": "2026-06-14T12:00:00+00:00",
        "validation": {
            "ready_for_live_consumers": ready,
        },
        "promotion": {
            "feeds_live_buys": ready,
        },
    }


def _forward_payload(
    *,
    buy_comparisons=1,
    span_days=1,
    retention_rate=0.60,
):
    return {
        "status": "collecting",
        "report_version": "0.1.0",
        "metrics": {
            "buy_comparison_count": buy_comparisons,
            "observation_span_days": span_days,
        },
        "latest_buy_comparison": {
            "retention_rate": retention_rate,
            "new_top_count": 16,
            "exited_top_count": 16,
        },
        "recommendations": ["Keep monitoring."],
    }


def test_buys_monitor_collects_until_archive_depth_is_ready():
    payload = build_buys_monitor(_buy_payload(), _forward_payload())

    assert payload["status"] == "collecting"
    assert payload["validation"]["ready_for_monitoring"] is True
    assert payload["monitoring"]["review_ready"] is False
    assert payload["monitoring"]["next_action"] == (
        "collect_more_valucast_owned_buy_observations"
    )
    assert payload["source_policy"]["feeds_buy_score"] is False
    assert payload["monitor_contract"]["mutates_buy_scores"] is False


def test_buys_monitor_marks_review_ready_after_archive_depth():
    payload = build_buys_monitor(
        _buy_payload(),
        _forward_payload(buy_comparisons=7, span_days=14),
    )

    assert payload["status"] == "review_ready"
    assert payload["monitoring"]["review_ready"] is True
    assert payload["monitoring"]["next_action"] == (
        "review_bucket_movement_before_next_calibration"
    )


def test_buys_monitor_blocks_bad_live_state_or_retention():
    payload = build_buys_monitor(
        _buy_payload(ready=False),
        _forward_payload(retention_rate=0.20),
    )

    assert payload["status"] == "blocked"
    assert payload["validation"]["ready_for_monitoring"] is False
    assert "ValuCast Buys artifact is not ready for live consumers." in payload[
        "validation"
    ]["blockers"]
    assert "ValuCast Buys top-40 retention is below monitor threshold." in payload[
        "validation"
    ]["blockers"]


def test_run_and_validate_buys_monitor(tmp_path):
    buy_path = tmp_path / "buys.json"
    forward_path = tmp_path / "forward.json"
    artifact_path = tmp_path / "monitor.json"
    buy_path.write_text(json.dumps(_buy_payload()), encoding="utf-8")
    forward_path.write_text(json.dumps(_forward_payload()), encoding="utf-8")

    result = run_buys_monitor(
        buy_path=buy_path,
        forward_validation_path=forward_path,
        artifact_path=artifact_path,
    )
    payload, problems = validate_buys_monitor(artifact_path)

    assert result["status"] == "collecting"
    assert payload["artifact"] == "valucast_prospect_buys_monitor"
    assert problems == []


def test_buys_monitor_validator_rejects_score_mutation_claim(tmp_path):
    payload = build_buys_monitor(_buy_payload(), _forward_payload())
    payload["monitor_contract"]["mutates_buy_scores"] = True
    artifact_path = tmp_path / "monitor.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_buys_monitor(artifact_path)

    assert "monitor_contract.mutates_buy_scores must be false" in problems
