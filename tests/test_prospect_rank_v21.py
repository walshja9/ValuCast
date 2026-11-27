import pytest

import prospects.rank_v2 as rank_v2
from prospects.rank_v2 import reconstruct_fold_ladders, select_role_ladders


def test_role_ladders_take_hitters_only_from_v1_and_pitchers_only_from_v09():
    incumbent = [
        {"mlbam_id": 11, "role": "hitter", "score": 90.0},
        {"mlbam_id": 12, "role": "hitter", "score": 80.0},
        {"mlbam_id": 21, "role": "pitcher", "score": 70.0},
        {"mlbam_id": 22, "role": "pitcher", "score": 60.0},
    ]
    candidate = [
        {"mlbam_id": 12, "role": "hitter", "score": 99.0},
        {"mlbam_id": 11, "role": "hitter", "score": 10.0},
        {
            "mlbam_id": 22,
            "role": "pitcher",
            "score": 88.0,
            "score_source": "prospect_model_v0_9",
        },
        {
            "mlbam_id": 21,
            "role": "pitcher",
            "score": 77.0,
            "score_source": "prospect_model_v0_9",
        },
    ]
    targets = {
        ("11", "hitter"): 1.0,
        ("12", "hitter"): 0.5,
        ("21", "pitcher"): 0.5,
        ("22", "pitcher"): 1.0,
    }

    result = select_role_ladders(incumbent, candidate, targets)

    assert [row["mlbam_id"] for row in result["candidate_hitters"]] == [11, 12]
    assert [row["mlbam_id"] for row in result["candidate_pitchers"]] == [22, 21]
    assert result["candidate_hitters"] == result["incumbent_hitters"]
    assert all(
        row["score_source"] == "prospect_model_v0_9"
        for row in result["candidate_pitchers"]
    )
    assert result["hitter_pair_inversions"] == 0


def test_role_ladders_fail_closed_on_mixed_pitcher_source_or_missing_scores():
    incumbent = [{"mlbam_id": 1, "role": "pitcher", "score": 10.0}]
    candidate = [
        {
            "mlbam_id": 1,
            "role": "pitcher",
            "score": 10.0,
            "score_source": "prospect_model_v0_8",
        }
    ]
    targets = {("1", "pitcher"): 0.5}

    with pytest.raises(ValueError, match="v0.9"):
        select_role_ladders(incumbent, candidate, targets)

    candidate[0].pop("score")
    candidate[0]["score_source"] = "prospect_model_v0_9"
    with pytest.raises(ValueError, match="score"):
        select_role_ladders(incumbent, candidate, targets)


def test_role_ladders_reject_unsorted_rank_core_rows():
    incumbent = [
        {"mlbam_id": 1, "role": "hitter", "score": 80.0},
        {"mlbam_id": 2, "role": "hitter", "score": 90.0},
        {"mlbam_id": 3, "role": "pitcher", "score": 70.0},
    ]
    candidate = [
        {"mlbam_id": 1, "role": "hitter", "score": 80.0},
        {"mlbam_id": 2, "role": "hitter", "score": 90.0},
        {
            "mlbam_id": 3,
            "role": "pitcher",
            "score": 70.0,
            "score_source": "prospect_model_v0_9",
        },
    ]
    targets = {
        ("1", "hitter"): 0.0,
        ("2", "hitter"): 1.0,
        ("3", "pitcher"): 0.5,
    }

    with pytest.raises(ValueError, match="order"):
        select_role_ladders(incumbent, candidate, targets)


def test_role_ladders_reject_malformed_supplied_ladder_positions():
    incumbent = [
        {"mlbam_id": 1, "role": "hitter", "score": 90.0, "source_ladder_position": 2},
        {"mlbam_id": 2, "role": "pitcher", "score": 70.0, "source_ladder_position": 1},
    ]
    candidate = [
        {"mlbam_id": 1, "role": "hitter", "score": 10.0},
        {
            "mlbam_id": 2,
            "role": "pitcher",
            "score": 80.0,
            "score_source": "prospect_model_v0_9",
        },
    ]
    targets = {("1", "hitter"): 1.0, ("2", "pitcher"): 0.5}

    with pytest.raises(ValueError, match="positions"):
        select_role_ladders(incumbent, candidate, targets)


def test_reconstruct_fold_ladders_rejects_a_cohort_mismatch():
    with pytest.raises(ValueError, match="cohort mismatch"):
        reconstruct_fold_ladders({"test_cohort": 2022}, [], 2021)


@pytest.mark.parametrize("target", [float("nan"), float("inf")])
def test_reconstruct_fold_ladders_rejects_non_finite_targets(target):
    with pytest.raises(ValueError, match="target"):
        reconstruct_fold_ladders(
            {
                "test_cohort": 2021,
                "targets": {("1", "hitter"): target},
                "eligible_rows": [],
            },
            [],
            2021,
        )


def test_reconstruct_fold_ladders_rejects_duplicate_outcome_identity():
    with pytest.raises(ValueError, match="duplicate outcome"):
        reconstruct_fold_ladders(
            {
                "test_cohort": 2021,
                "targets": {("1", "hitter"): 1.0},
                "eligible_rows": [
                    {"mlbam_id": 1, "role": "hitter", "outcome": "star"},
                    {"mlbam_id": 1, "role": "hitter", "outcome": "role"},
                ],
            },
            [],
            2021,
        )


def test_reconstruct_fold_ladders_keeps_the_v1_hitter_score_and_v09_pitcher_score(
    monkeypatch,
):
    fold = {
        "test_cohort": 2021,
        "targets": {("1", "hitter"): 1.0, ("2", "pitcher"): 0.5},
        "eligible_rows": [
            {"mlbam_id": 1, "role": "hitter", "outcome": "star"},
            {"mlbam_id": 2, "role": "pitcher", "outcome": "role"},
        ],
        "input_contract": {"generated_at": "2021-09-30T00:00:00+00:00"},
        "context": {
            "prospect_universe": {},
            "dynasty_layer": {},
            "prospect_availability": None,
            "mlb_roster_status": None,
            "milb_history_by_key": None,
            "investment_evidence": None,
            "manual_graduated_ids": set(),
            "consensus_snapshots": {
                key: {}
                for key in ("sts", "fangraphs", "prospectslive", "pipeline", "hkb")
            },
            "incumbent_profiles": [],
        },
    }

    def stage1(_model, *_args, **kwargs):
        return {"score_source": kwargs["expected_score_source"]}

    def build(_universe, stage1, *_args, **_kwargs):
        if stage1["score_source"] == "prospect_model_v0_6":
            return {
                "board": [
                    {"mlbam_id": 1, "role": "hitter", "score": 90.0},
                    {"mlbam_id": 2, "role": "pitcher", "score": 70.0},
                ]
            }
        return {
            "board": [
                {"mlbam_id": 1, "role": "hitter", "score": 10.0},
                {
                    "mlbam_id": 2,
                    "role": "pitcher",
                    "score": 80.0,
                    "score_source": "prospect_model_v0_9",
                },
            ]
        }

    monkeypatch.setattr(rank_v2, "build_stage1_contract", stage1)
    monkeypatch.setattr(rank_v2, "build_prospect_rank_from_stage1", build)

    result = reconstruct_fold_ladders(
        fold,
        [
            {
                "mlbam_id": 2,
                "role": "pitcher",
                "raw_composite": 0.6,
                "score_source": "prospect_model_v0_9",
            }
        ],
        2021,
    )

    assert set(result) == {
        "test_cohort",
        "candidate_hitters",
        "candidate_pitchers",
        "incumbent_hitters",
        "incumbent_pitchers",
        "hitter_pair_inversions",
    }
    assert result["candidate_hitters"][0]["ladder_score"] == 90.0
    assert result["candidate_pitchers"][0]["ladder_score"] == 80.0
    assert result["candidate_pitchers"][0]["source_ladder_position"] == 1
    assert result["candidate_pitchers"][0]["target"] == 0.5
    assert result["candidate_pitchers"][0]["outcome"] == "role"


def test_frozen_v09_reconstruction_uses_the_real_shared_candidate_contract():
    generated_at = "2021-09-30T00:00:00+00:00"

    def profile(mlbam_id, role, tier):
        return {
            "mlbam_id": mlbam_id,
            "name": f"Player {mlbam_id}",
            "normalized_name": f"player {mlbam_id}",
            "role": role,
            "position": "SS" if role == "hitter" else "SP",
            "team": "Test Club",
            "age": 20,
            "level": "AA",
            "sample": 200,
            "sample_unit": "PA" if role == "hitter" else "IP",
            "sample_reliability": 0.6,
            "outcome_distribution": {
                "bust_probability": 1.0 - tier,
                "role_probability": tier,
                "star_probability": 0.0,
            },
            "dynasty_signal": {
                "bust_risk": 1.0 - tier,
                "role_or_better_probability": tier,
                "star_ceiling_probability": 0.0,
                "expected_factual_outcome_tier": tier,
                "outcome_uncertainty": 0.5,
            },
        }

    hitter, pitcher = profile(1, "hitter", 0.8), profile(2, "pitcher", 0.7)
    fold = {
        "test_cohort": 2021,
        "targets": {("1", "hitter"): 1.0, ("2", "pitcher"): 0.5},
        "eligible_rows": [
            {"mlbam_id": 1, "role": "hitter", "outcome": "star"},
            {"mlbam_id": 2, "role": "pitcher", "outcome": "role"},
        ],
        "input_contract": {
            "generated_at": generated_at,
            "current": {
                "hitters": [{"mlbam_id": 1, "name": "Player 1", "plate_appearances": 200, "source_kind": "current_season"}],
                "pitchers": [{"mlbam_id": 2, "name": "Player 2", "innings_pitched": 100, "source_kind": "current_season"}],
            },
        },
        "context": {
            "prospect_universe": {
                "schema_version": "1.0",
                "artifact": "valucast_prospect_universe",
                "generated_at": generated_at,
                "candidate_count": 2,
                "players": [
                    {key: value for key, value in hitter.items() if key not in {"outcome_distribution", "dynasty_signal", "position", "team", "sample", "sample_unit"}},
                    {key: value for key, value in pitcher.items() if key not in {"outcome_distribution", "dynasty_signal", "position", "team", "sample", "sample_unit"}},
                ],
            },
            "dynasty_layer": {
                "generated_at": generated_at,
                "layer_version": "0.1.0",
                "release_contract": {"consumer": "prospect_rank_v1", "feeds_live_valucast_rank": True},
                "profiles": [hitter, pitcher],
            },
            "prospect_availability": None,
            "mlb_roster_status": None,
            "milb_history_by_key": None,
            "investment_evidence": None,
            "manual_graduated_ids": set(),
            "consensus_snapshots": {key: {} for key in ("sts", "fangraphs", "prospectslive", "pipeline", "hkb")},
            "incumbent_profiles": [
                {"mlbam_id": 1, "name": "Player 1", "normalized_name": "player 1", "role": "hitter", "expected_outcome_score": 0.8, "expected_category_impact_score": 0.6, "sample_reliability": 0.6},
                {"mlbam_id": 2, "name": "Player 2", "normalized_name": "player 2", "role": "pitcher", "expected_outcome_score": 0.7, "expected_category_impact_score": 0.5, "sample_reliability": 0.6},
            ],
        },
    }

    result = reconstruct_fold_ladders(
        fold,
        [{"mlbam_id": 2, "name": "Player 2", "normalized_name": "player 2", "role": "pitcher", "raw_composite": 0.7, "score_source": "prospect_model_v0_9", "sample_reliability": 0.6}],
        2021,
    )

    assert result["candidate_pitchers"][0]["score_source"] == "prospect_model_v0_9"
