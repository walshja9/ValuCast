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
    return {
        "ready_for_public_snapshot": True,
        "checks": [{"id": "snapshot", "status": "passed"}],
    }


def _outcome():
    return {
        "status": "evidence_ready",
        "front_office_track": {
            "score": 87,
            "grade": "B+",
            "uncapped_score": 91,
            "score_cap": 87,
            "cap_reasons": ["Forward observations are not review-ready yet."],
            "target_grade": "A-",
            "interpretation": "Historical evidence ready, proprietary inputs absent.",
        },
        "validation": {"bucket_cohort_evidence_ready": True},
    }


def _v07():
    return {
        "validation": {
            "ready_for_backtest": True,
            "bucket_comparison_ready": True,
            "top200_factual_context_coverage": 1.0,
            "top200_availability_coverage": 1.0,
            "blockers": [],
        }
    }


def _raw():
    return {
        "validation": {
            "ready_for_current_publication": True,
            "raw_data_independence_complete": False,
        },
        "independence": {
            "canonical_contract_owned": True,
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


def _failures():
    return {
        "status": "watchlist_active",
        "summary": {
            "blocking_finding_count": 0,
            "evidence_gate_count": 2,
            "front_office_risk_count": 4,
            "v0_7_disagreement_count": 3,
            "latest_rank_bucket_count": 6,
            "latest_buy_retention_rate": 0.55,
        },
        "blocking_findings": [],
        "evidence_gates": [
            {"kind": "front_office_cap", "message": "Forward observations are young."}
        ],
        "forward_archive_progress": {
            "next_target_grade": "A-",
            "rank_comparison_count": 1,
            "buy_comparison_count": 1,
            "observation_span_days": 1,
            "remaining_rank_comparisons": 6,
            "remaining_buy_comparisons": 6,
            "remaining_span_days": 13,
        },
    }


def _milb_freshness():
    return {
        "status": "candidate_ready",
        "metrics": {
            "top50_history_fallback_count": 0,
            "top50_stat_context_mismatch_count": 0,
            "top200_history_fallback_count": 6,
            "targeted_row_refresh_count": 1,
        },
        "blockers": [],
    }


def _pipeline_observability():
    return {
        "status": "candidate_ready",
        "expected_date": "2026-06-14",
        "validation": {
            "ready_for_daily_publication": True,
            "date_mismatch_count": 0,
            "missing_or_unreadable_count": 0,
            "targeted_row_refresh_count": 1,
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
        _failures(),
        _milb_freshness(),
        _pipeline_observability(),
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
    pillars = {pillar["name"]: pillar for pillar in payload["pillars"]}
    assert pillars["Independence"]["grade"] == "A"
    assert pillars["MLB front-office track"]["grade"] == "B+"
    assert payload["failure_watchlist"]["status"] == "watchlist_active"
    assert payload["failure_watchlist"]["v0_7_disagreement_count"] == 3
    assert payload["failure_watchlist"]["evidence_gate_count"] == 2
    assert payload["failure_watchlist"]["blocking_finding_count"] == 0
    assert payload["operations_watchlist"]["milb_stat_freshness"]["status"] == (
        "candidate_ready"
    )
    assert payload["operations_watchlist"]["pipeline_observability"][
        "targeted_row_refresh_count"
    ] == 1


def test_front_office_product_readiness_uses_dynasty_surface_when_prospect_surface_blocked():
    snapshot = _snapshot()
    snapshot["validation"]["ready_for_live_consumers"] = False
    snapshot["validation"]["surface_readiness"] = {"dynasty": True, "prospects": False}
    snapshot["validation"]["surface_blockers"] = {
        "prospects": ["Prospect board is pitcher-heavy."]
    }

    payload = build_front_office_report(
        snapshot,
        _governor(),
        _outcome(),
        _v07(),
        _raw(),
        _buys_monitor(),
        _failures(),
        _milb_freshness(),
        _pipeline_observability(),
    )
    product = {
        pillar["name"]: pillar for pillar in payload["pillars"]
    }["Product readiness"]

    assert product["score"] == 95
    assert product["grade"] == "A"
    assert product["status"] == "public_ready"
    assert product["evidence"]["public_snapshot_ready"] is False
    assert product["evidence"]["quality_governor_ready"] is True
    assert product["evidence"]["dynasty_ready"] is True
    assert product["evidence"]["prospects_ready"] is False
    assert product["evidence"]["prospect_board_caveat"] == (
        "Prospect board is pitcher-heavy."
    )


def test_front_office_report_promotes_supported_pillars_to_a_plus():
    snapshot = _snapshot()
    snapshot["row_count"] = 3_500
    snapshot["validation"]["blockers"] = []
    snapshot["validation"]["buy_signal_blockers"] = []
    raw = _raw()
    raw["validation"]["raw_data_independence_complete"] = True

    payload = build_front_office_report(
        snapshot,
        _governor(),
        _outcome(),
        _v07(),
        raw,
        _buys_monitor(),
        _failures(),
        _milb_freshness(),
        _pipeline_observability(),
    )
    pillars = {pillar["name"]: pillar for pillar in payload["pillars"]}

    assert pillars["Product readiness"]["grade"] == "A+"
    assert pillars["Data pipeline readiness"]["grade"] == "A+"
    assert pillars["Independence"]["grade"] == "A+"
    assert pillars["Prospect credibility"]["grade"] == "A+"
    assert pillars["MLB front-office track"]["grade"] == "B+"


def test_run_and_validate_front_office_report(tmp_path):
    files = {}
    for name, payload in {
        "snapshot": _snapshot(),
        "governor": _governor(),
        "outcome": _outcome(),
        "v07": _v07(),
        "raw": _raw(),
        "buys": _buys_monitor(),
        "failures": _failures(),
        "milb": _milb_freshness(),
        "pipeline": _pipeline_observability(),
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
        front_office_failures_path=files["failures"],
        milb_stat_freshness_path=files["milb"],
        pipeline_observability_path=files["pipeline"],
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
    assert "True blockers" in html
    assert "Evidence gates" in html
    assert "Watch items" in html
    assert "Risk flags" not in html
    assert "Next evidence milestone:" in html
    # The B+ cap line renders only while the live MLB front-office track is
    # actually capped. That cap lifts as forward archives collect (the track
    # graduated past B+ to A+ on the 2026-07-06 daily refresh), so assert the
    # cap copy tracks the real artifact state rather than pinning one transient
    # capped state. This still fails if the template drops the cap line while a
    # cap exists, or shows it when there is none.
    from pathlib import Path as _Path

    report_path = (
        _Path(app_module.__file__).parent
        / "data"
        / "models"
        / "valucast_front_office_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    front_track = next(
        (p for p in report.get("pillars", []) if p.get("name") == "MLB front-office track"),
        {},
    )
    has_score_cap = bool((front_track.get("evidence") or {}).get("score_cap"))
    cap_line = "MLB front-office score is capped at B+"
    assert (cap_line in html) == has_score_cap
    # Merged into one paragraph — no duplicated cap/milestone copy.
    assert "Next MLB evidence milestone:" not in html
    assert "Current score is capped" not in html
    # Evidence labels are humanized, not raw JSON keys.
    assert "Top-200 factual context coverage" in html
    assert "V07 Top200" not in html
    assert "A Plus" not in html
