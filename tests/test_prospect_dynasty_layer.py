"""Tests for the shadow-only prospect dynasty ceiling/risk layer."""
import json

import pytest

from prospects.dynasty import build_layer, coherent_distribution, decision_signal, run_layer


def _profile():
    return {
        "mlbam_id": 1,
        "name": "Example Prospect",
        "normalized_name": "example prospect",
        "role": "hitter",
        "position": "SS",
        "team": "AA Club",
        "age": 21,
        "level": "AA",
        "sample": 200,
        "sample_unit": "PA",
        "sample_reliability": 0.5,
        "outcome_distribution": {
            "bust_probability": 0.4,
            "role_probability": 0.35,
            "star_probability": 0.25,
        },
    }


def _universal():
    return {
        "model_name": "ValuCast Universal Prospect Model",
        "model_version": "0.4.0",
        "profiles": [_profile()],
    }


def test_coherent_distribution_caps_star_at_establishment():
    assert coherent_distribution(0.3, 0.5) == {
        "bust_probability": 0.7,
        "role_probability": 0.0,
        "star_probability": 0.3,
    }


def test_decision_signal_is_math_on_factual_distribution_not_a_value():
    signal = decision_signal(_profile())
    assert signal["bust_risk"] == 0.4
    assert signal["role_or_better_probability"] == 0.6
    assert signal["star_ceiling_probability"] == 0.25
    assert signal["expected_factual_outcome_tier"] == 0.85
    assert 0.0 < signal["outcome_uncertainty"] < 1.0


def test_layer_is_rank_and_value_free_and_blocks_live_consumers():
    payload = build_layer(_universal())
    assert payload["status"] == "shadow_only"
    assert payload["layer_contract"]["rank_free"] is True
    assert payload["layer_contract"]["value_free"] is True
    assert payload["promotion"]["research_gate"] == "hold"
    assert payload["promotion"]["feeds_live_dd_value"] is False
    assert payload["promotion"]["feeds_live_valucast_rank"] is False
    assert all("rank" not in profile for profile in payload["profiles"])
    assert all("value" not in profile for profile in payload["profiles"])


def test_layer_refuses_incoherent_universal_distribution():
    profile = _profile()
    profile["outcome_distribution"]["bust_probability"] = 0.5
    with pytest.raises(ValueError, match="sum to one"):
        decision_signal(profile)


def test_layer_refuses_out_of_range_probability():
    profile = _profile()
    profile["outcome_distribution"] = {
        "bust_probability": 1.1,
        "role_probability": -0.1,
        "star_probability": 0.0,
    }
    with pytest.raises(ValueError, match="between zero and one"):
        decision_signal(profile)


def test_layer_uses_only_matching_historical_evidence():
    backtest = {
        "universal_model_version": "0.4.0",
        "promotion": {
            "dynasty_layer_research_gate": "active",
            "reason": "Evidence passed.",
        },
        "roles": {
            "hitter": {"role_research_gate": "active", "fold_count": 3},
            "pitcher": {"role_research_gate": "active", "fold_count": 3},
        },
    }
    payload = build_layer(_universal(), backtest)
    assert payload["promotion"]["research_gate"] == "active"
    assert payload["historical_evidence"]["role_fold_counts"] == {
        "hitter": 3,
        "pitcher": 3,
    }
    assert (
        "The historical research gate currently has 3 eligible temporal folds per role."
        in payload["limitations"]
    )
    backtest["universal_model_version"] = "0.3.0"
    assert build_layer(_universal(), backtest)["promotion"]["research_gate"] == "hold"


def test_run_layer_writes_separate_artifact(tmp_path):
    universal_path = tmp_path / "universal.json"
    backtest_path = tmp_path / "missing-backtest.json"
    artifact_path = tmp_path / "dynasty-layer.json"
    universal_path.write_text(json.dumps(_universal()), encoding="utf-8")

    result = run_layer(
        universal_path,
        backtest_path,
        artifact_path,
        archive_dir=tmp_path / "archive",
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["candidate_count"] == 1
    assert result["archive_changed"] is True
    assert payload["promotion"]["research_gate"] == "hold"
