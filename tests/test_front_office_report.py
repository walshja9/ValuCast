"""Tests for the ValuCast front-office readiness report."""
import json

import app as app_module
from prospects.front_office_report import build_front_office_report
from prospects.front_office_report import run_front_office_report
from scripts.validate_front_office_report import validate_front_office_report


def _snapshot():
    return {
        "generated_at": "2026-06-14T12:00:00+00:00",
        "row_count": 100,
        "validation": {
            "ready_for_live_consumers": True,
            "same_day_freshness": True,
            "required_fields_complete": True,
            "duplicate_identity_count": 0,
            "surface_readiness": {"dynasty": True, "prospects": True, "buys": True},
        },
    }


def _governor():
    return {"ready_for_public_snapshot": True}


def _outcome():
    return {
        "status": "evidence_ready",
        "front_office_track": {
            "score": 84,
            "grade": "B",
            "target_grade": "B",
            "interpretation": "Historical evidence ready, proprietary inputs absent.",
        },
    }


def _v07():
    return {
        "validation": {
            "ready_for_backtest": True,
            "top200_factual_context_coverage": 1.0,
        }
    }


def _raw():
    return {
        "validation": {
            "ready_for_current_publication": True,
            "raw_data_independence_complete": False,
        },
        "independence": {
            "direct_raw_ownership_score": 1.0,
            "last_external_trust_boundary": {"current_boundary": "DD-hosted"},
        },
    }


def _buys_monitor():
    return {
        "status": "collecting",
        "monitoring": {
            "buy_comparison_count": 1,
            "observation_span_days": 1,
        },
    }


def test_front_office_report_grades_five_pillars_without_feeding_scores():
    payload = build_front_office_report(
        _snapshot(),
        _governor(),
        _outcome(),
        _v07(),
        _raw(),
        _buys_monitor(),
    )

    assert payload["artifact"] == "valucast_front_office_report"
    assert payload["source_policy"]["feeds_model_score"] is False
    assert len(payload["pillars"]) == 5
    assert {pillar["name"] for pillar in payload["pillars"]} == {
        "Product readiness",
        "Data pipeline readiness",
        "Independence",
        "Prospect credibility",
        "MLB front-office track",
    }
    assert payload["overall"]["grade"] in {"B", "B+", "A-", "A", "A+"}


def test_run_and_validate_front_office_report(tmp_path):
    files = {}
    for name, payload in {
        "snapshot": _snapshot(),
        "governor": _governor(),
        "outcome": _outcome(),
        "v07": _v07(),
        "raw": _raw(),
        "buys": _buys_monitor(),
    }.items():
        files[name] = tmp_path / f"{name}.json"
        files[name].write_text(json.dumps(payload), encoding="utf-8")
    artifact_path = tmp_path / "front-office.json"

    result = run_front_office_report(
        public_snapshot_path=files["snapshot"],
        quality_governor_path=files["governor"],
        outcome_backtest_path=files["outcome"],
        model_v07_path=files["v07"],
        raw_independence_path=files["raw"],
        buys_monitor_path=files["buys"],
        artifact_path=artifact_path,
    )
    payload, problems = validate_front_office_report(artifact_path)

    assert result["status"] == "front_office_track_active"
    assert payload["artifact"] == "valucast_front_office_report"
    assert problems == []


def test_front_office_page_renders():
    client = app_module.app.test_client()
    response = client.get("/front-office")

    assert response.status_code == 200
    html = response.data.decode("utf-8")
    assert "Front Office Track" in html
