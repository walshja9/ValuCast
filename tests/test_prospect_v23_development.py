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
    rows = [
        {"mlbam_id": 2, "role": "hitter", "name": "Zulu", "score": 10.004, "score_source": "universal_fallback", "rank": 5},
        {"mlbam_id": 8, "role": "hitter", "name": "Bravo", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 3},
        {"mlbam_id": 9, "role": "hitter", "name": "Alpha", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 1},
        {"mlbam_id": 3, "role": "hitter", "name": "Bravo", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 2},
        {"mlbam_id": 7, "role": "pitcher", "name": "Alpha", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 4},
    ]
    board = candidate.reconstruct_product_board(
        [
            rows[0], rows[1], rows[2], rows[3],
        ],
        [rows[4]],
    )
    assert [row["mlbam_id"] for row in board] == [9, 3, 8, 7, 2]
    assert [row["rank"] for row in board] == [1, 2, 3, 4, 5]
    assert board == candidate.reconstruct_product_board(list(reversed(rows[:4])), [rows[4]])
    wrong_ranks = copy.deepcopy(rows)
    wrong_ranks[0]["rank"] = 1
    with pytest.raises(ValueError, match="emitted ranks"):
        candidate.reconstruct_product_board(wrong_ranks[:4], wrong_ranks[4:])


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
        {"mlbam_id": index, "role": "hitter" if index % 2 else "pitcher", "target": float(index % 3) / 2, "candidate": float(30 - index), "control": float(index), "score": float(index), "name": str(index), "score_source": "prospect_model_v0_6", "rank": 27 - index}
        for index in range(1, 27)
    ]
    ladders = {2018: {"candidate_hitters": [row for row in base if row["role"] == "hitter"], "candidate_pitchers": [row for row in reversed(base) if row["role"] == "pitcher"], "incumbent_hitters": [row for row in base if row["role"] == "hitter"], "incumbent_pitchers": [row for row in base if row["role"] == "pitcher"]}}
    candidate_map, control_map = {"field": "candidate"}, {"field": "control"}
    monkeypatch.setattr(candidate, "fit_fold_maps", lambda *_args: (candidate_map, control_map))
    before = copy.deepcopy((candidate_map, control_map))
    result = candidate.build_fold_result(2018, ladders, candidate_map, control_map)
    assert result["candidate_mae"] is not None
    assert result["product_mae"] is None
    assert (candidate_map, control_map) == before


def _fit_ladders():
    ladders = {}
    for year in (2018, 2019, 2021):
        fold = {}
        for prefix, score in (("candidate", 3.0), ("incumbent", 2.0)):
            for role, offset in (("hitter", 10_000), ("pitcher", 20_000)):
                fold[f"{prefix}_{role}s"] = [
                    {
                        "mlbam_id": offset + year * 10 + position,
                        "role": role,
                        "source_ladder_position": position,
                        "ladder_score": score - position,
                        "outcome": outcome,
                        "target": target,
                        "test_cohort": year,
                    }
                    for position, (outcome, target) in enumerate(
                        (("star", 1.0), ("role", 0.5), ("bust", 0.0)), 1
                    )
                ]
        ladders[year] = fold
    return ladders


@requires_runner
def test_fold_complement_maps_exclude_held_out_targets_and_bind_build_result(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()
    candidate_map, control_map = candidate.fit_fold_maps(2018, ladders)
    before = (
        candidate_map["artifact_sha256"], candidate_map["params"],
        control_map["artifact_sha256"], control_map["params"],
    )
    training_rows = candidate._training_rows(2018, ladders, "candidate")
    assert {row["test_cohort"] for row in training_rows} == {2019, 2021}
    assert all(row["test_cohort"] != 2018 for row in training_rows)

    ladders[2018]["candidate_hitters"][0]["target"] = 0.0
    ladders[2018]["incumbent_pitchers"][0]["target"] = 0.0
    repeated_candidate, repeated_control = candidate.fit_fold_maps(2018, ladders)
    assert before == (
        repeated_candidate["artifact_sha256"], repeated_candidate["params"],
        repeated_control["artifact_sha256"], repeated_control["params"],
    )

    monkeypatch.setattr(candidate, "fit_fold_maps", lambda *_args: (candidate_map, control_map))
    monkeypatch.setattr(candidate, "score_role_slope_joint_ladders", lambda *_args: [])
    with pytest.raises(ValueError, match="fold-complement"):
        candidate.build_fold_result(2018, ladders, {}, control_map)


@requires_runner
def test_fold_complement_rejects_swapped_or_aliased_cohort_markers():
    candidate = _runner()
    swapped = _fit_ladders()
    swapped[2019]["candidate_hitters"][0]["test_cohort"] = 2018
    with pytest.raises(ValueError, match="cohort marker"):
        candidate.fit_fold_maps(2018, swapped)

    aliased = _fit_ladders()
    aliased[2019] = copy.deepcopy(aliased[2018])
    with pytest.raises(ValueError, match="cohort marker"):
        candidate.build_fold_result(2018, aliased, {}, {})


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


def _bootstrap_fold(year):
    rows = []
    for role, offset in (("hitter", 0), ("pitcher", 10)):
        for index in range(1, 14):
            target = float(index % 2)
            rows.append({
                "mlbam_id": year * 100 + offset + index,
                "role": role,
                "target": target,
                "calibrated_expected_tier": target,
                "score": target,
            })
    candidate = [dict(row) for row in rows]
    control = [{**row, "calibrated_expected_tier": 1.0 - row["target"]} for row in rows]
    product = [{**row, "score": 1.0 - row["target"], "rank": index} for index, row in enumerate(rows, 1)]
    return {"year": year, "candidate": candidate, "control": control, "product": product}


@requires_runner
def test_bootstrap_uses_one_deterministic_shared_sample_plan_without_refits(monkeypatch):
    candidate = _runner()
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda *_args: pytest.fail("bootstrap must not fit maps"))

    first = candidate.build_bootstrap_summary(folds, seed=17, replicates=12)
    second = candidate.build_bootstrap_summary(copy.deepcopy(folds), seed=17, replicates=12)

    assert first == second
    assert first["sample_plan_sha256"]
    assert first["metrics"]["candidate_control_mae_delta"]["valid_replicates"] == 12
    assert first["metrics"]["candidate_control_concordance_delta"]["valid_replicates"] == 12
    assert first["metrics"]["candidate_product_concordance_delta"]["valid_replicates"] == 12


@requires_runner
def test_pooled_fit_runs_once_only_after_fold_and_bootstrap_qualification(monkeypatch):
    candidate = _runner()
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    map_calls = []

    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: {year: {} for year in candidate.DEVELOPMENT_FOLDS})
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda year, _ladders: (candidate._completed_fold_receipt(folds[year]), folds[year]))
    monkeypatch.setattr(candidate, "build_bootstrap_summary", lambda _folds: {
        "status": "completed", "seed": 39017, "replicates": 10_000,
        "minimum_valid_replicates": 9_900,
        "interval": {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"},
        "sample_plan_sha256": "0" * 64,
        "metrics": {name: {"point": -0.1, "lower": -0.2 if name == "candidate_control_mae_delta" else 0.1, "upper": -0.05, "valid_replicates": 10_000, "gate_passed": True} for name in candidate.BOOTSTRAP_METRICS},
    })
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda rows: map_calls.append(rows) or {"training_rows_sha256": "1" * 64, "artifact_sha256": "2" * 64})
    monkeypatch.setattr(candidate, "_validate_pooled_map", lambda mapping, rows: mapping)
    monkeypatch.setattr(candidate, "_pooled_candidate_rows", lambda _ladders: [
        {"mlbam_id": 1, "role": "hitter", "source_ladder_position": 1, "ladder_score": 1.0, "outcome": "star", "target": 1.0, "test_cohort": 2018},
        {"mlbam_id": 2, "role": "pitcher", "source_ladder_position": 1, "ladder_score": 1.0, "outcome": "star", "target": 1.0, "test_cohort": 2018},
    ])

    result, pooled_map = candidate.build_development_artifacts({}, {}, {})

    assert len(map_calls) == 1
    assert pooled_map["artifact_sha256"] == "2" * 64
    assert result["pooled_fit"] == {"attempted": True, "status": "validated", "row_count": 2, "training_rows_sha256": "1" * 64, "map_artifact_sha256": "2" * 64}
