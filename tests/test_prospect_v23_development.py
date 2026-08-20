import copy
import importlib
from pathlib import Path

import pytest


RUNNER = "scripts.build_prospect_v23_candidate"
HAS_RUNNER = (Path(__file__).resolve().parents[1] / "scripts" / "build_prospect_v23_candidate.py").exists()
requires_runner = pytest.mark.skipif(not HAS_RUNNER, reason="runner import is the RED gate")


def _runner():
    return importlib.import_module(RUNNER)


def test_fold_runner_import_is_the_registered_red_gate():
    _runner()


@requires_runner
def test_fold_contract_is_exact_and_v09_pitchers_are_sealed_oof_only(monkeypatch):
    candidate = _runner()
    calls = []
    contract = {"current_profiles": [{"mlbam_id": 999, "role": "pitcher"}]}
    v09 = {
        "oof_rows": [
            {"mlbam_id": 1, "role": "pitcher", "test_cohort": 2018, "score_source": "prospect_model_v0_9"},
            {"mlbam_id": 2, "role": "hitter", "test_cohort": 2018, "score_source": "prospect_model_v0_9"},
            {"mlbam_id": 3, "role": "pitcher", "test_cohort": 2019, "score_source": "prospect_model_v0_9"},
        ]
    }

    monkeypatch.setattr(candidate, "build_fold_contract", lambda source, year: {"year": year})
    monkeypatch.setattr(
        candidate,
        "reconstruct_fold_ladders",
        lambda fold, pitchers, year: calls.append((fold, pitchers, year)) or {"year": year},
    )

    assert candidate.DEVELOPMENT_FOLDS == (2018, 2019, 2021)
    assert candidate.TRAINING_FOLDS_BY_TEST == {2018: (2019, 2021), 2019: (2018, 2021), 2021: (2018, 2019)}
    assert candidate.reconstruct_development_ladders(contract, v09) == {2018: {"year": 2018}, 2019: {"year": 2019}, 2021: {"year": 2021}}
    assert calls[0][1] == [v09["oof_rows"][0]]
    assert calls[1][1] == [v09["oof_rows"][2]]
    assert calls[2][1] == []


@requires_runner
def test_product_board_uses_emitted_two_decimal_score_and_full_tie_order():
    candidate = _runner()
    rows = candidate.reconstruct_product_board(
        [
            {"mlbam_id": 2, "role": "hitter", "name": "Zulu", "score": 10.004, "score_source": "universal_fallback"},
            {"mlbam_id": 8, "role": "hitter", "name": "Bravo", "score": 10.004, "score_source": "prospect_model_v0_6"},
            {"mlbam_id": 9, "role": "hitter", "name": "Alpha", "score": 10.004, "score_source": "prospect_model_v0_6"},
            {"mlbam_id": 3, "role": "hitter", "name": "Bravo", "score": 10.004, "score_source": "prospect_model_v0_6"},
        ],
        [{"mlbam_id": 7, "role": "pitcher", "name": "Alpha", "score": 10.004, "score_source": "prospect_model_v0_6"}],
    )
    assert [row["mlbam_id"] for row in rows] == [9, 3, 8, 7, 2]
    assert [row["rank"] for row in rows] == [1, 2, 3, 4, 5]


@requires_runner
def test_align_by_identity_reorders_and_fails_closed_on_identity_or_target_changes():
    candidate = _runner()
    reference = [
        {"mlbam_id": 1, "role": "hitter", "target": 1.0},
        {"mlbam_id": 2, "role": "pitcher", "target": 0.0},
    ]
    rows = [
        {"mlbam_id": 2, "role": "pitcher", "target": 0.0, "score": 0.1},
        {"mlbam_id": 1, "role": "hitter", "target": 1.0, "score": 0.9},
    ]
    assert [row["mlbam_id"] for row in candidate.align_by_identity(reference, rows, "candidate")] == [1, 2]
    for broken in (
        rows[:1],
        [*rows, copy.deepcopy(rows[0])],
        [{**row, "target": 0.5} if row["mlbam_id"] == 1 else row for row in rows],
    ):
        with pytest.raises(ValueError, match="candidate"):
            candidate.align_by_identity(reference, broken, "candidate")


@requires_runner
def test_metrics_hand_check_cross_role_ties_and_exact_top25_selection():
    candidate = _runner()
    rows = [
        {"role": "hitter", "target": 1.0, "expected_tier": 0.8},
        {"role": "pitcher", "target": 0.0, "expected_tier": 0.2},
        {"role": "hitter", "target": 0.5, "expected_tier": 0.4},
        {"role": "pitcher", "target": 1.0, "expected_tier": 0.4},
    ]
    assert candidate.mae(rows, "expected_tier") == pytest.approx(0.275)
    assert candidate.cross_role_concordance(rows, "expected_tier") == pytest.approx((1 + 1 + 0.5) / 3)
    assert candidate.cross_role_concordance(rows[:1], "expected_tier") is None
    top = [
        {"target": float(index), "calibrated_expected_tier": float(index)}
        for index in range(26)
    ]
    assert candidate.top25_target_sum(top) == sum(range(1, 26))
    with pytest.raises(ValueError, match="exactly 25"):
        candidate.top25_target_sum(top[:-2])
    product = [{"rank": index, "target": float(index)} for index in range(1, 27)]
    assert candidate.top25_target_sum(list(reversed(product)), product=True) == sum(range(1, 26))
    with pytest.raises(ValueError, match="exactly 25"):
        candidate.top25_target_sum(product[:-2], product=True)


@requires_runner
def test_fold_result_aligns_adversarial_input_and_cannot_mutate_fitted_maps(monkeypatch):
    candidate = _runner()

    def score(hitters, pitchers, mapping):
        return [
            {**row, "calibrated_expected_tier": row[mapping["field"]]}
            for row in [*hitters, *pitchers]
        ]

    monkeypatch.setattr(candidate, "score_role_slope_joint_ladders", score)
    base = [
        {"mlbam_id": index, "role": "hitter" if index % 2 else "pitcher", "target": float(index % 3) / 2, "candidate": float(30 - index), "control": float(index), "score": float(index), "name": str(index), "score_source": "prospect_model_v0_6"}
        for index in range(1, 27)
    ]
    ladders = {2018: {"candidate_hitters": [row for row in base if row["role"] == "hitter"], "candidate_pitchers": [row for row in reversed(base) if row["role"] == "pitcher"], "incumbent_hitters": [row for row in base if row["role"] == "hitter"], "incumbent_pitchers": [row for row in base if row["role"] == "pitcher"]}}
    candidate_map, control_map = {"field": "candidate"}, {"field": "control"}
    before = copy.deepcopy((candidate_map, control_map))
    result = candidate.build_fold_result(2018, ladders, candidate_map, control_map)
    assert result["candidate_mae"] is not None
    assert result["product_mae"] is None
    assert (candidate_map, control_map) == before
    ladders[2018]["candidate_hitters"][0]["target"] = 1.0
    candidate.build_fold_result(2018, ladders, candidate_map, control_map)
    assert (candidate_map, control_map) == before


def _passing_fold():
    return {
        "candidate_mae": 0.1,
        "control_mae": 0.2,
        "candidate_concordance": 0.8,
        "control_concordance": 0.6,
        "product_concordance": 0.5,
        "candidate_top25_target_sum": 10.0,
        "control_top25_target_sum": 9.0,
        "product_top25_target_sum": 8.0,
    }


@requires_runner
@pytest.mark.parametrize(
    ("expected_gate", "changes"),
    [
        ("mae_improves", {"candidate_mae": 0.2}),
        ("control_concordance_improves", {"candidate_concordance": 0.6}),
        ("candidate_concordance_above_half", {"candidate_concordance": 0.5, "control_concordance": 0.4, "product_concordance": 0.3}),
        ("product_concordance_improves", {"product_concordance": 0.8}),
        ("control_top25_matches", {"candidate_top25_target_sum": 8.9}),
        ("product_top25_matches", {"candidate_top25_target_sum": 7.9, "control_top25_target_sum": 7.0}),
    ],
)
def test_each_fold_gate_fails_at_its_operator_boundary(expected_gate, changes):
    candidate = _runner()
    fold = _passing_fold()
    fold.update(changes)
    report = {"folds": {2018: fold, 2019: _passing_fold(), 2021: _passing_fold()}}
    verdict = candidate.development_qualification(report)
    assert verdict["qualified"] is False
    assert verdict["folds"][2018]["qualified"] is False
    assert [name for name, passed in verdict["folds"][2018]["gates"].items() if not passed] == [expected_gate]


@requires_runner
def test_each_fold_must_pass_without_pooled_or_majority_rescue():
    candidate = _runner()
    failed = _passing_fold()
    failed["candidate_mae"] = failed["control_mae"]
    verdict = candidate.development_qualification({"folds": {2018: failed, 2019: _passing_fold(), 2021: _passing_fold()}})
    assert verdict["qualified"] is False
    assert verdict["folds"][2018]["qualified"] is False
    assert verdict["folds"][2019]["qualified"] is True
