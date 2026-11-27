"""Tests for the shadow-only ValuCast Universal Prospect Index."""
import json

import pytest

from prospects.index import build_index, index_score, rank_profiles, run_index


def _profile(mlbam_id, role, distribution, reliability=0.5):
    return {
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "normalized_name": f"player {mlbam_id}",
        "role": role,
        "position": "SS" if role == "hitter" else "P",
        "team": "AA Club",
        "age": 21,
        "level": "AA",
        "sample": 200,
        "sample_unit": "PA" if role == "hitter" else "IP",
        "sample_reliability": reliability,
        "outcome_distribution": distribution,
    }


def _universal():
    return {
        "model_name": "ValuCast Universal Prospect Model",
        "model_version": "0.4.0",
        "input_contract": {"generated_at": "2026-06-13T00:00:00+00:00"},
        "profiles": [
            _profile(
                1,
                "hitter",
                {
                    "bust_probability": 0.2,
                    "role_probability": 0.5,
                    "star_probability": 0.3,
                },
            ),
            _profile(
                2,
                "pitcher",
                {
                    "bust_probability": 0.4,
                    "role_probability": 0.2,
                    "star_probability": 0.4,
                },
            ),
        ],
    }


def test_index_score_is_transparent_expected_factual_outcome():
    assert index_score(
        {
            "bust_probability": 0.2,
            "role_probability": 0.5,
            "star_probability": 0.3,
        }
    ) == 55.0


def test_index_rejects_incoherent_distribution():
    with pytest.raises(ValueError, match="sum to one"):
        index_score(
            {
                "bust_probability": 0.5,
                "role_probability": 0.5,
                "star_probability": 0.5,
            }
        )


def test_equal_scores_share_rank_without_reliability_tiebreak():
    profiles = [
        _profile(
            2,
            "pitcher",
            {
                "bust_probability": 0.4,
                "role_probability": 0.2,
                "star_probability": 0.4,
            },
            reliability=0.9,
        ),
        _profile(
            1,
            "hitter",
            {
                "bust_probability": 0.2,
                "role_probability": 0.6,
                "star_probability": 0.2,
            },
            reliability=0.1,
        ),
    ]
    board = rank_profiles(profiles)
    assert [row["universal_rank"] for row in board] == [1, 1]
    assert all(row["universal_prospect_index"] == 50.0 for row in board)


def test_index_is_league_and_market_independent_and_blocks_live_use():
    payload = build_index(_universal())
    assert payload["status"] == "shadow_only"
    assert payload["index_contract"]["league_scoring_independent"] is True
    assert payload["index_contract"]["market_independent"] is True
    assert payload["index_contract"]["external_rankings_used"] is False
    assert payload["index_contract"]["uncertainty_penalty"] is False
    assert payload["index_contract"]["role_balance_adjustment"] is False
    assert payload["promotion"]["research_gate"] == "hold"
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["feeds_live_valucast_rank"] is False
    assert payload["promotion"]["feeds_live_dd_value"] is False


def test_index_uses_only_matching_backtest_evidence():
    backtest = {
        "universal_model_version": "0.4.0",
        "generated_at": "2026-06-13T00:00:00+00:00",
        "combined": {"fold_count": 3},
        "promotion": {
            "universal_index_research_gate": "active",
            "role_distribution_prerequisite": "active",
            "reason": "Evidence passed.",
        },
    }
    assert build_index(_universal(), backtest)["promotion"]["research_gate"] == "active"
    backtest["universal_model_version"] = "0.3.0"
    assert build_index(_universal(), backtest)["promotion"]["research_gate"] == "hold"
    backtest["universal_model_version"] = "0.4.0"
    backtest["generated_at"] = "2026-06-12T00:00:00+00:00"
    assert build_index(_universal(), backtest)["promotion"]["research_gate"] == "hold"


def test_run_index_writes_separate_artifact_and_archive(tmp_path):
    universal_path = tmp_path / "universal.json"
    artifact_path = tmp_path / "index.json"
    universal_path.write_text(json.dumps(_universal()), encoding="utf-8")
    result = run_index(
        universal_path=universal_path,
        backtest_path=tmp_path / "missing-backtest.json",
        artifact_path=artifact_path,
        archive_dir=tmp_path / "archive",
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result["candidate_count"] == 2
    assert result["archive_changed"] is True
    assert payload["board"][0]["universal_rank"] == 1
    assert (tmp_path / "archive" / "2026-06-13.json").exists()
