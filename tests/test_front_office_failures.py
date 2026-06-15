"""Tests for the ValuCast front-office failure report."""
import json

from prospects.front_office_failures import build_front_office_failures
from prospects.front_office_failures import run_front_office_failures
from scripts.validate_front_office_failures import validate_front_office_failures


def _forward():
    return {
        "generated_at": "2026-06-14T12:00:00+00:00",
        "metrics": {"rank_comparison_count": 1},
        "evidence_status": {
            "status": "collecting",
            "next_target_grade": "A-",
            "thresholds": {"A-": {"passed": False}},
        },
        "latest_rank_comparison": {
            "bucket_count": 1,
            "buckets": [{"bucket": "hitter|upper|model|available"}],
        },
        "latest_buy_comparison": {
            "retention_rate": 0.7,
            "largest_movers": [{"name": "Buy Mover"}],
        },
    }


def _outcome():
    return {
        "front_office_track": {
            "cap_reasons": [
                "Ordinal bridge is still partial.",
                "Forward observations are not review-ready yet.",
            ],
        }
    }


def _model_v07():
    return {
        "candidates": [
            {
                "name": "V07 Up",
                "mlbam_id": 1,
                "role": "hitter",
                "level": "AA",
                "rank_v1_rank": 4,
                "rank_v1_score": 50.0,
                "v0_7_shadow_score": 56.0,
                "v0_7_delta_vs_rank_v1": 6.0,
                "score_source": "prospect_model_v0_6",
                "candidate_features": {"availability_status": "available"},
            }
        ]
    }


def _rank():
    return {
        "generated_at": "2026-06-14T12:00:00+00:00",
        "board": [
            {
                "name": "Risky Prospect",
                "mlbam_id": 2,
                "role": "pitcher",
                "level": "AAA",
                "rank": 12,
                "score": 45.0,
                "score_source": "universal_fallback",
                "components": {
                    "availability_risk_discount": 0.08,
                    "availability": {"status": "thin_current_sample"},
                    "uncertainty": {"band": "wide"},
                    "factual_current_context": {"skill_band": "thin"},
                },
            }
        ],
    }


def test_front_office_failures_tracks_caps_risks_and_v07_disagreements():
    payload = build_front_office_failures(
        _forward(),
        _outcome(),
        _model_v07(),
        _rank(),
    )

    assert payload["source_policy"]["feeds_model_score"] is False
    assert payload["summary"]["blocking_finding_count"] == 3
    assert payload["front_office_risks"][0]["name"] == "Risky Prospect"
    assert payload["v0_7_disagreements"][0]["name"] == "V07 Up"
    assert payload["forward_archive_thresholds"]["next_target_grade"] == "A-"
    assert payload["latest_rank_bucket_watchlist"][0]["bucket"].startswith("hitter")


def test_run_and_validate_front_office_failures(tmp_path):
    paths = {}
    for name, payload in {
        "forward": _forward(),
        "outcome": _outcome(),
        "v07": _model_v07(),
        "rank": _rank(),
    }.items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(payload), encoding="utf-8")
    artifact_path = tmp_path / "failures.json"

    result = run_front_office_failures(
        forward_validation_path=paths["forward"],
        outcome_backtest_path=paths["outcome"],
        model_v07_path=paths["v07"],
        rank_path=paths["rank"],
        artifact_path=artifact_path,
    )
    payload, problems = validate_front_office_failures(artifact_path)

    assert result["status"] == "watchlist_active"
    assert payload["artifact"] == "valucast_front_office_failures"
    assert problems == []
