"""Tests for the unified prospect outcome evidence artifact."""
import json

from prospects.outcome_backtest import build_outcome_backtest
from prospects.outcome_backtest import run_outcome_backtest
from scripts.validate_prospect_outcome_backtest import validate_outcome_backtest


def _role(sample=300):
    return {
        "role_research_gate": "active",
        "sample_size": sample,
        "fold_count": 3,
        "candidate_rank_concordance": 0.7,
        "baseline_rank_concordance": 0.65,
        "candidate_multiclass_brier": 0.18,
        "baseline_multiclass_brier": 0.20,
        "candidate_top_quartile_precision": 0.35,
        "baseline_top_quartile_precision": 0.30,
        "folds": [
            {
                "test_cohort": year,
                "sample_size": sample // 3,
                "candidate_multiclass_brier": 0.18,
                "baseline_multiclass_brier": 0.20,
                "candidate_rank_concordance": 0.70,
                "baseline_rank_concordance": 0.65,
                "candidate_top_quartile_precision": 0.35,
                "baseline_top_quartile_precision": 0.30,
            }
            for year in (2017, 2018, 2019)
        ],
    }


def _prospect_model():
    return {
        "status": "shadow_only",
        "candidate_count": 100,
        "board_gate": {"status": "fallback"},
        "impact_board_gate": {"status": "active"},
    }


def _dynasty_backtest():
    return {
        "generated_at": "2026-06-14T12:00:00+00:00",
        "promotion": {"dynasty_layer_research_gate": "active"},
        "roles": {"hitter": _role(1100), "pitcher": _role(1120)},
    }


def _cross_role_shadow(*, historical="pass", power="pass"):
    return {
        "generated_at": "2026-06-14T12:00:00+00:00",
        "status": "review_ready" if historical == power == "pass" else "collecting",
        "checks": {
            "historical_absolute_concordance": {
                "status": historical,
                "value": 0.81,
                "floor": 0.60,
            },
            "cross_role_change_power": {
                "status": power,
                "max_power": 0.75 if power == "pass" else 0.015,
                "floor": 0.70,
            },
            "current_board_shape": {"status": "pass"},
            "aaa_measured_coverage": {"status": "pass"},
        },
        "promotion": {"score_changes_authorized": False},
    }


def _forward_validation():
    return {
        "generated_at": "2026-06-14T12:00:00+00:00",
        "status": "collecting",
        "metrics": {"rank_comparison_count": 1},
        "recommendations": ["Keep collecting."],
    }


def _model_v07():
    return {
        "generated_at": "2026-06-14T12:00:00+00:00",
        "status": "shadow_preview",
        "model_version": "0.7.0-preview.1",
        "validation": {"ready_for_backtest": True, "blockers": []},
    }


def test_outcome_backtest_separates_realized_evidence_from_forward_observation():
    payload = build_outcome_backtest(
        _prospect_model(),
        _dynasty_backtest(),
        _cross_role_shadow(),
        _forward_validation(),
        _model_v07(),
    )

    assert payload["status"] == "evidence_ready"
    assert payload["evidence"]["dynasty_fixed_horizon"]["status"] == "active"
    assert payload["evidence"]["cross_role_shadow"]["status"] == "review_ready"
    assert payload["evidence"]["cross_role_shadow"]["score_changes_authorized"] is False
    assert payload["evidence"]["forward_observation"][
        "is_realized_outcome_accuracy_evidence"
    ] is False
    assert payload["evidence"]["bucket_cohort"]["status"] == "ready"
    assert payload["validation"]["bucket_cohort_evidence_ready"] is True
    assert payload["validation"]["blockers"] == []
    assert len(payload["validation"]["evidence_gates"]) == 2
    assert payload["source_policy"]["feeds_model_score"] is False
    assert payload["front_office_track"]["grade"] == "B+"


def test_outcome_backtest_blocks_on_underpowered_cross_role_change_gate():
    payload = build_outcome_backtest(
        _prospect_model(),
        _dynasty_backtest(),
        _cross_role_shadow(power="fail"),
        _forward_validation(),
        _model_v07(),
    )

    assert payload["status"] == "needs_work"
    assert payload["evidence"]["cross_role_shadow"]["historical_absolute_passed"] is True
    assert payload["evidence"]["cross_role_shadow"]["change_power_passed"] is False
    # realized evidence stays ready when the dynasty gate + absolute
    # concordance hold: the change-power gate is structurally unpassable
    # (plan 028) and must not hard-wire this flag False for years.
    assert payload["validation"]["realized_evidence_ready"] is True
    assert payload["validation"]["cross_role_change_power_ready"] is False
    assert any(
        gate["kind"] == "cross_role_change_power"
        for gate in payload["validation"]["evidence_gates"]
    )


def test_run_and_validate_outcome_backtest(tmp_path):
    paths = {}
    payloads = {
        "model": _prospect_model(),
        "dynasty": _dynasty_backtest(),
        "cross_role": _cross_role_shadow(),
        "forward": _forward_validation(),
        "v07": _model_v07(),
    }
    for name, payload in payloads.items():
        paths[name] = tmp_path / f"{name}.json"
        paths[name].write_text(json.dumps(payload), encoding="utf-8")
    artifact_path = tmp_path / "outcome.json"

    result = run_outcome_backtest(
        prospect_model_path=paths["model"],
        dynasty_backtest_path=paths["dynasty"],
        cross_role_shadow_path=paths["cross_role"],
        forward_validation_path=paths["forward"],
        model_v07_path=paths["v07"],
        artifact_path=artifact_path,
    )
    payload, problems = validate_outcome_backtest(artifact_path)

    assert result["status"] == "evidence_ready"
    assert payload["artifact"] == "valucast_prospect_outcome_backtest"
    assert problems == []
