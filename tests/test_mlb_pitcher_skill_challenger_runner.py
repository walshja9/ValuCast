import copy
import json
import random
from pathlib import Path
from types import SimpleNamespace

import pytest

from projections.backtest import pitcher_skill_challenger_harness as harness
from projections.models.pitcher_skill_challenger import FEATURE_ORDER
from scripts import run_mlb_pitcher_skill_challenger as runner


TARGET_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)
FEATURE_SEASONS = tuple(range(2015, 2025))


def _registration(*, sealed=True):
    registration = {
        "study_id": "mlb_pitcher_skill_challenger_v1",
        "status": "registered_unspent",
        "research_only": True,
        "retrospective_target_seasons": list(TARGET_SEASONS),
        "statcast_feature_seasons": list(FEATURE_SEASONS),
        "minimum_input_pitches": 500,
        "ridge_lambda": 10.0,
        "bootstrap_seed": 35021,
        "forbidden_bootstrap_seeds": [28013, 33021],
        "outer_looks": 1,
        "model_and_evaluation": {
            "target_residuals": {
                "k_bf": "actual_next_season_k_bf_minus_control_k_bf",
                "bb_bf": "actual_next_season_bb_bf_minus_control_bb_bf",
            },
            "feature_set": "one_combined_shape_location_execution_arsenal_set",
            "descriptive_ablations": ["shape", "location_execution", "arsenal"],
            "ablation_policy": "in_look_descriptive_only",
            "fold_rule": "target_T_trains_only_outcome_seasons_before_T",
            "control": {
                "params": "PitcherMarcelParams()",
                "builder": "build_pitcher_projections",
                "version": "registration_commit",
            },
            "context_comparators": ["same_season_persistence", "archived_steamer"],
            "context_comparator_common_support": "exact_same_player_outcome_and_forecast_window_only",
            "context_comparator_policy": "context_only_never_trains_challenger_or_rescues_gate",
            "scored_folds": list(TARGET_SEASONS),
            "scorecard": "canonical_methodology_scorecard",
            "input_eligibility": {
                "feature_season": "T-1",
                "minimum_tracked_pitches": 500,
                "requires_control_projection_for_T": True,
            },
            "meaningful_pitch_type": {"minimum_pitches": 50, "minimum_usage": 0.05},
            "location_geometry": {
                "horizontal_zone_half_width_ft": 0.83,
                "vertical_bounds": "per_pitch_sz_bot_to_sz_top",
                "valid_location_requires": ["plate_x", "plate_z", "sz_top", "sz_bot"],
                "rate_denominator": "pitches_with_all_valid_location_fields",
                "zone": "inside_closed_strike_zone_rectangle",
                "heart": "central_50_percent_of_rectangle_width_and_height",
                "edge": "euclidean_distance_to_clamped_rectangle_boundary_lte_3_inches_inside_or_outside",
                "waste": "outside_euclidean_distance_to_closest_rectangle_point_gte_12_inches",
            },
            "ridge": {"lambda": 10.0, "grid_search": False},
            "correction_clip": {
                "lower_training_residual_percentile": 5,
                "upper_training_residual_percentile": 95,
                "fit_independently_inside_each_fold_and_target": True,
            },
            "primary_gate": {
                "endpoints": ["k_per_9", "bb_per_9", "era", "whip"],
                "minimum_pooled_out_of_sample_mae_reduction_pct": 2.0,
                "maximum_endpoint_or_projected_role_cohort_regression_pct": 1.0,
                "minimum_improved_folds": 4,
                "total_scored_folds": 6,
                "minimum_scored_pitcher_seasons": 250,
            },
            "paired_hierarchical_bootstrap": {
                "resamples": 10000,
                "sampling_order": "completed_target_season_then_pitcher",
                "seed": 35021,
                "interval": "two_sided_95_percentile",
                "use": "descriptive_only_for_retrospective_gate",
            },
            "post_look_policy": "no_second_retrospective_variant_after_outer_result_known",
            "prospective_confirmation": {
                "season": 2026,
                "evaluate_only_after_season_complete": True,
            },
        },
        "feeds_live_projection": False,
        "feeds_rank_or_value": False,
        "feeds_pitcher_publication": False,
        "claim_eligible": False,
    }
    if sealed:
        registration.update(
            {
                "implementation_commit": "a" * 40,
                "source_hashes": {str(year): f"sha-{year}" for year in FEATURE_SEASONS},
                "readiness_hash": "r" * 64,
            }
        )
    return registration


def _control(pid, season, *, p_sp=0.7, delta=0.0):
    bf, ip = 600.0, 150.0
    k, bb, hr, hbp, hits, cfip = 150.0 + delta, 48.0, 18.0, 5.0, 130.0, 3.2
    raw_fip = (13 * hr + 3 * (bb + hbp) - 2 * k) / ip
    era = raw_fip + cfip
    return {
        "mlbam_id": str(pid),
        "season": season,
        "BF": bf,
        "IP": ip,
        "K": k,
        "BB": bb,
        "HR": hr,
        "HBP": hbp,
        "H_ALLOWED": hits,
        "ER": era * ip / 9,
        "ERA": era,
        "WHIP": (bb + hits) / ip,
        "K_9": 9 * k / ip,
        "BB_9": 9 * bb / ip,
        "GS": 25,
        "G": 30,
        "QS": 15,
        "SV": 0,
        "HLD": 2,
        "W": 12,
        "p_sp": p_sp,
        "cFIP": cfip,
    }


def _outcome(pid, season, *, ip=150.0, k=165.0, bb=42.0):
    return {
        "mlbam_id": str(pid),
        "season": season,
        "BF": 610.0,
        "IP": ip,
        "K": k,
        "BB": bb,
        "HR": 17.0,
        "HBP": 4.0,
        "H_ALLOWED": 125.0,
        "ER": 55.0,
        "GS": 25,
        "G": 30,
    }


def _shape(value):
    return {"mean": value, "sample_count": 300, "missing_count": 0}


def _feature(pid, season, *, pitch_count=700, hand=None, signal=0.0):
    row = {
        "mlbam_id": str(pid),
        "season": season,
        "pitch_count": pitch_count,
        "outcomes": {
            "whiff_rate": 0.25 + signal / 100,
            "csw_rate": 0.29 + signal / 100,
            "called_strike_rate": 0.16,
        },
        "location": {
            "zone_rate": 0.5,
            "heart_rate": 0.24,
            "edge_rate": 0.35,
            "waste_rate": 0.1,
            "plate_x": {"stddev": 0.71},
            "plate_z": {"stddev": 0.78},
        },
        "pitch_types": {
            "four_seam": {
                "usage": 0.6,
                "shape": {
                    "velocity": _shape(94 + signal),
                    "horizontal_movement": _shape(-8 - signal),
                    "induced_vertical_movement": _shape(15 + signal),
                    "spin": _shape(2300 + signal),
                    "extension": _shape(6.2),
                },
            },
            "slider": {
                "usage": 0.4,
                "shape": {
                    "velocity": _shape(84 + signal),
                    "horizontal_movement": _shape(4 + signal),
                    "induced_vertical_movement": _shape(2 - signal),
                    "spin": _shape(2400 + signal),
                    "extension": _shape(5.9),
                },
            },
        },
        "arsenal": {
            "count": 2,
            "usage_hhi": 0.52,
            "fastball_share": 0.6,
            "max_velocity_separation": 10.0,
            "max_movement_separation": 15.0,
        },
    }
    if hand is not None:
        row["pitcher_hand"] = hand
    return row


def _bundle(players=2, years=range(2016, 2026)):
    bundle = {
        "pair_keys": [],
        "controls": [],
        "outcomes": [],
        "features": [],
        "identities": [],
        "persistence": [],
        "steamer": [],
        "source_manifest": {
            "feature_seasons": list(FEATURE_SEASONS),
            "source_hashes": {str(year): f"sha-{year}" for year in FEATURE_SEASONS},
        },
    }
    support = {}
    for player in range(players):
        pid = str(1000 + player)
        bundle["identities"].append({"mlbam_id": pid, "throws": "L" if player % 2 else "R"})
        for year in years:
            if year in TARGET_SEASONS:
                bundle["pair_keys"].append({"mlbam_id": pid, "outcome_season": year})
            bundle["controls"].append(_control(pid, year, p_sp=0.8 if player % 2 == 0 else 0.2))
            bundle["outcomes"].append(_outcome(pid, year, ip=150 if player % 2 == 0 else 40))
            bundle["features"].append(_feature(pid, year - 1, signal=player / 10))
            bundle["persistence"].append(
                {
                    "mlbam_id": pid,
                    "season": year,
                    "forecast_window": "full_season",
                    "K_9": 9.5,
                    "BB_9": 2.9,
                    "ERA": 3.5,
                    "WHIP": 1.1,
                }
            )
            if player % 2 == 0:
                bundle["steamer"].append(
                    {
                        "mlbam_id": pid,
                        "season": year,
                        "forecast_window": "full_season",
                        "K_9": 9.4,
                        "BB_9": 2.8,
                        "ERA": 3.6,
                        "WHIP": 1.12,
                    }
                )
    for year in years:
        support[str(year)] = {
            "control_count": players,
            "outcome_count": players,
            "pair_count": players,
            "control_only_count": 0,
            "outcome_only_count": 0,
        }
    bundle["common_support"] = {
        "source_seasons": list(years),
        "scored_target_seasons": [year for year in years if year in TARGET_SEASONS],
        "by_season": support,
        "totals": {
            key: sum(row[key] for row in support.values())
            for key in next(iter(support.values()))
        },
    }
    return bundle


def _fake_fit(rows, params):
    return {"training": [(row["mlbam_id"], row["outcome_season"]) for row in rows]}


def _fake_predict(model, control, feature):
    return {"k_bf": control["K"] / control["BF"] + 0.01, "bb_bf": control["BB"] / control["BF"] - 0.005}


def _install_fake_model(monkeypatch):
    monkeypatch.setattr(harness, "fit_fold", _fake_fit)
    monkeypatch.setattr(harness, "predict_rates", _fake_predict)


def test_real_loader_shape_includes_2016_2019_training_but_declares_only_scored_pairs(monkeypatch):
    registration = _registration(sealed=False)
    feature_rows = {
        year: [_feature("1000", year)] for year in FEATURE_SEASONS
    }
    manifest = {
        "seasons": {
            str(year): {"canonical_sha256": harness.canonical_sha256(feature_rows[year])}
            for year in FEATURE_SEASONS
        }
    }

    def fake_json(path):
        if Path(path).name == "manifest.json":
            return manifest
        year = int(Path(path).stem.rsplit("_", 1)[1])
        return feature_rows[year]

    monkeypatch.setattr(runner, "_json", fake_json)
    monkeypatch.setattr(
        runner,
        "_control_rows",
        lambda season: [
            _control("1000", season),
            _control(f"control-only-{season}", season),
        ],
    )
    monkeypatch.setattr(
        runner,
        "load_pitching_season",
        lambda season, data_dir: [
            _outcome("1000", season),
            _outcome(f"outcome-only-{season}", season),
        ],
    )
    monkeypatch.setattr(
        runner,
        "load_identity_store",
        lambda data_dir: {"1000": {"throws": "R"}},
    )
    bundle = runner.load_study_bundle(registration)
    assert {row["season"] for row in bundle["controls"]} == set(range(2016, 2026))
    assert {row["outcome_season"] for row in bundle["pair_keys"]} == set(TARGET_SEASONS)
    fold = harness.prepare_fold(bundle, 2020, minimum_pitches=500)
    assert {row["outcome_season"] for row in fold["training_rows"]} == {2016, 2017, 2018, 2019}
    assert {row["outcome_season"] for row in fold["scoring_rows"]} == {2020}
    assert bundle["common_support"]["by_season"]["2020"] == {
        "control_count": 2,
        "outcome_count": 2,
        "pair_count": 1,
        "control_only_count": 1,
        "outcome_only_count": 1,
    }


def test_prepare_fold_is_exact_walk_forward_and_held_out_poison_cannot_enter_training():
    bundle = _bundle(players=2)
    before = harness.prepare_fold(bundle, 2023, minimum_pitches=500)
    assert {row["outcome_season"] for row in before["training_rows"]} == set(range(2016, 2023))
    assert {row["feature_season"] for row in before["training_rows"]} == set(range(2015, 2022))
    assert {row["outcome_season"] for row in before["scoring_rows"]} == {2023}
    assert all(row["feature_season"] == row["outcome_season"] - 1 for row in before["training_rows"])

    poisoned = copy.deepcopy(bundle)
    for row in poisoned["features"]:
        if row["season"] >= 2022:
            row["outcomes"]["whiff_rate"] = 1.0
            row["held_out_hand_poison"] = "L" if row.get("pitcher_hand") != "L" else "R"
    for row in poisoned["outcomes"]:
        if row["season"] >= 2023:
            row["K"] = row["BF"] - row["BB"] - row["H_ALLOWED"]
    after = harness.prepare_fold(poisoned, 2023, minimum_pitches=500)
    assert after["training_rows"] == before["training_rows"]
    assert harness.fit_fold(before["training_rows"], harness.PitcherSkillChallengerParams()) == harness.fit_fold(
        after["training_rows"], harness.PitcherSkillChallengerParams()
    )


def test_exact_join_validation_rejects_duplicates_missing_pairs_seasons_and_hands():
    base = _bundle(players=2)
    mutations = []
    duplicate = copy.deepcopy(base)
    duplicate["controls"].append(copy.deepcopy(duplicate["controls"][0]))
    mutations.append((duplicate, "duplicate"))
    missing_control = copy.deepcopy(base)
    missing_control["controls"].pop()
    mutations.append((missing_control, "missing Control"))
    missing_outcome = copy.deepcopy(base)
    missing_outcome["outcomes"].pop()
    mutations.append((missing_outcome, "missing outcome"))
    missing_hand = copy.deepcopy(base)
    missing_hand["identities"][0]["throws"] = ""
    mutations.append((missing_hand, "hand"))
    conflicting_hand = copy.deepcopy(base)
    conflicting_hand["features"][0]["pitcher_hand"] = "L"
    mutations.append((conflicting_hand, "conflicting hand"))
    season_mismatch = copy.deepcopy(base)
    next(
        row
        for row in season_mismatch["controls"]
        if row["mlbam_id"] == "1000" and row["season"] == 2020
    )["season"] = 1999
    mutations.append((season_mismatch, "missing Control"))

    for bundle, message in mutations:
        with pytest.raises(ValueError, match=message):
            harness.prepare_fold(bundle, 2023, minimum_pitches=500)


def test_missing_or_below_floor_feature_is_the_only_registered_fallback(monkeypatch):
    bundle = _bundle(players=2)
    bundle["features"] = [row for row in bundle["features"] if not (row["mlbam_id"] == "1000" and row["season"] == 2022)]
    for row in bundle["features"]:
        if row["mlbam_id"] == "1001" and row["season"] == 2022:
            row["pitch_count"] = 499
    fold = harness.prepare_fold(bundle, 2023, minimum_pitches=500)
    assert [row["fallback_reason"] for row in fold["scoring_rows"]] == ["missing_feature", "below_pitch_floor"]

    _install_fake_model(monkeypatch)
    result = harness.evaluate_registered_look(bundle, _registration())
    assert result["coverage"]["fallback_counts"] == {"below_pitch_floor": 1, "missing_feature": 1}


def test_qualification_uses_control_p_sp_and_existing_ip_floors_not_realized_role():
    bundle = _bundle(players=2)
    for row in bundle["outcomes"]:
        if row["season"] == 2023 and row["mlbam_id"] == "1000":
            row.update({"IP": 59.9, "GS": 0, "G": 80})
        if row["season"] == 2023 and row["mlbam_id"] == "1001":
            row.update({"IP": 20.0, "GS": 20, "G": 20})
    fold = harness.prepare_fold(bundle, 2023, minimum_pitches=500)
    assert [row["mlbam_id"] for row in fold["scoring_rows"]] == ["1001"]
    assert fold["scoring_rows"][0]["projected_role"] == "reliever"


def test_mae_reconciles_by_pair_and_pooled_mae_is_not_mean_of_fold_maes():
    rows = [
        {"season": 2020, "role": "starter", "control_errors": {"k_per_9": 1, "bb_per_9": 1, "era": 1, "whip": 1}, "challenger_errors": {"k_per_9": 0, "bb_per_9": 0, "era": 0, "whip": 0}},
        {"season": 2021, "role": "reliever", "control_errors": {"k_per_9": 9, "bb_per_9": 9, "era": 9, "whip": 9}, "challenger_errors": {"k_per_9": 8, "bb_per_9": 8, "era": 8, "whip": 8}},
        {"season": 2021, "role": "reliever", "control_errors": {"k_per_9": 9, "bb_per_9": 9, "era": 9, "whip": 9}, "challenger_errors": {"k_per_9": 8, "bb_per_9": 8, "era": 8, "whip": 8}},
    ]
    metrics = harness.summarize_errors(rows)
    assert metrics["endpoints"]["k_per_9"] == {"control_mae": pytest.approx(19 / 3), "challenger_mae": pytest.approx(16 / 3)}
    assert metrics["pooled"]["control_mae"] == pytest.approx(76 / 3)
    assert metrics["pooled"]["challenger_mae"] == pytest.approx(64 / 3)
    assert metrics["pooled"]["control_mae"] != pytest.approx((4 + 36) / 2)


def _gate_metrics(*, n=250, reduction=2.1, fold_wins=4, endpoint_regression=0.0, cohort_regression=0.0):
    control = 100.0
    challenger = control * (1 - reduction / 100)
    return {
        "sample": n,
        "pooled": {"control_mae": control, "challenger_mae": challenger},
        "endpoints": {
            name: {"control_mae": 1.0, "challenger_mae": 1.0 * (1 + endpoint_regression / 100)}
            for name in harness.ENDPOINTS
        },
        "folds": {
            str(year): {"control_mae": 1.0, "challenger_mae": 0.9 if index < fold_wins else 1.1}
            for index, year in enumerate(TARGET_SEASONS)
        },
        "projected_roles": {
            role: {"control_mae": 1.0, "challenger_mae": 1.0 * (1 + cohort_regression / 100)}
            for role in ("starter", "reliever")
        },
    }


@pytest.mark.parametrize(
    "metrics,failed_gate",
    [
        (_gate_metrics(reduction=1.99), "pooled_reduction"),
        (_gate_metrics(fold_wins=3), "fold_wins"),
        (_gate_metrics(n=249), "minimum_sample"),
        (_gate_metrics(endpoint_regression=1.01), "endpoint_regression"),
        (_gate_metrics(cohort_regression=1.01), "projected_role_regression"),
    ],
)
def test_registered_gate_requires_every_threshold(metrics, failed_gate):
    gates = harness.score_registered_gate(metrics, _registration())
    assert gates["passed"] is False
    assert gates["checks"][failed_gate]["passed"] is False
    assert harness.score_registered_gate(_gate_metrics(), _registration())["passed"] is True


def test_zero_denominators_ties_empty_and_cohort_undercoverage_fail_closed():
    zero = _gate_metrics()
    zero["pooled"] = {"control_mae": 0.0, "challenger_mae": 0.0}
    assert harness.score_registered_gate(zero, _registration())["passed"] is False
    tie = _gate_metrics(reduction=0.0)
    assert harness.score_registered_gate(tie, _registration())["checks"]["pooled_reduction"]["value"] == 0.0
    empty = harness.summarize_errors([])
    assert empty["sample"] == 0
    missing_role = _gate_metrics()
    del missing_role["projected_roles"]["reliever"]
    assert harness.score_registered_gate(missing_role, _registration())["passed"] is False


def test_hierarchical_bootstrap_is_exactly_seeded_order_invariant_and_global_rng_independent():
    rows = []
    for season in TARGET_SEASONS:
        for pid in range(4):
            rows.append({"season": season, "mlbam_id": str(pid), "control_total_error": 4.0 + pid, "challenger_total_error": 3.0 + pid})
    random.seed(999)
    first = harness.hierarchical_paired_bootstrap(rows, resamples=10000, seed=35021)
    random.seed(1)
    second = harness.hierarchical_paired_bootstrap(list(reversed(rows)), resamples=10000, seed=35021)
    assert first == second
    assert first["resamples"] == 10000
    assert first["seed"] == 35021
    assert len(first["percentile_interval_95"]) == 2
    assert first["sampling_order"] == "completed_target_season_then_pitcher"


def test_context_comparators_use_exact_common_support_and_cannot_change_verdict(monkeypatch):
    _install_fake_model(monkeypatch)
    bundle = _bundle(players=30)
    base = harness.evaluate_registered_look(bundle, _registration())
    changed = copy.deepcopy(bundle)
    changed["persistence"] = []
    changed["steamer"] = [
        {**row, "K_9": 999, "BB_9": 999, "ERA": 999, "WHIP": 999, "forecast_window": "wrong_window"}
        for row in bundle["steamer"]
    ]
    comparison = harness.evaluate_registered_look(changed, _registration())
    assert comparison["verdict"] == base["verdict"]
    assert comparison["gate"] == base["gate"]
    assert comparison["metrics"] == base["metrics"]
    assert base["context_comparators"]["steamer"]["missing_count"] > 0
    for comparator in ("persistence", "steamer"):
        context = base["context_comparators"][comparator]
        assert set(context["mae"]) == set(harness.ENDPOINTS)
        assert set(context["control_mae_on_common_support"]) == set(harness.ENDPOINTS)
        assert set(context["challenger_mae_on_common_support"]) == set(harness.ENDPOINTS)
        assert context["common_support_count"] + context["missing_count"] == base["sample"]


def test_three_ablations_are_descriptive_only_and_cannot_rescue_gate(monkeypatch):
    _install_fake_model(monkeypatch)
    bundle = _bundle(players=30)
    result = harness.evaluate_registered_look(bundle, _registration())
    assert list(result["descriptive_ablations"]) == ["shape", "location_execution", "arsenal"]
    assert all(value["use"] == "descriptive_only_never_selects_or_rescues" for value in result["descriptive_ablations"].values())
    assert result["verdict"] == harness.verdict_from_gate(result["metrics"], result["gate"])


def test_every_payload_is_private_and_uses_only_allowed_verdicts(monkeypatch):
    _install_fake_model(monkeypatch)
    bundle = _bundle(players=30)
    bundle["features"][0]["player_name"] = "PRIVATE PLAYER"
    result = harness.evaluate_registered_look(bundle, _registration())
    encoded = json.dumps(result, sort_keys=True)
    assert {key: result[key] for key in harness.BASE_FLAGS} == harness.BASE_FLAGS
    assert result["verdict"] in harness.ALLOWED_VERDICTS
    for token in ("PRIVATE PLAYER", "player_name", "mlbam_id", "predictions", "per_player", "competitor", "board_rank", "raw_pitch"):
        assert token.lower() not in encoded.lower()
    assert result["prospective_confirmation"] == {"required": True, "season": 2026, "after_season_complete": True}
    qualification = result["qualification"]
    assert qualification["totals"] == {
        "eligible": 180,
        "qualified": 180,
        "excluded": 0,
    }
    assert set(qualification["by_fold"]) == {str(year) for year in TARGET_SEASONS}
    assert result["coverage"]["common_support"]["by_season"]["2020"]["pair_count"] == 30


def test_malformed_present_score_feature_fails_before_prediction_or_line_rebuild(monkeypatch):
    _install_fake_model(monkeypatch)
    bundle = _bundle(players=30)
    feature = next(
        row
        for row in bundle["features"]
        if row["mlbam_id"] == "1000" and row["season"] == 2022
    )
    del feature["outcomes"]["whiff_rate"]
    monkeypatch.setattr(
        harness,
        "apply_rates_to_control",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("malformed evidence reached line rebuild")
        ),
    )
    with pytest.raises(ValueError, match="malformed score feature"):
        harness.evaluate_registered_look(bundle, _registration())


@pytest.mark.parametrize("field", ["BF", "IP", "K", "BB", "ER", "H_ALLOWED"])
@pytest.mark.parametrize("bad_value", [None, -1, float("nan"), float("inf")])
def test_required_outcome_fields_fail_closed_before_scoring(field, bad_value):
    bundle = _bundle(players=2)
    outcome = next(
        row
        for row in bundle["outcomes"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    if bad_value is None:
        del outcome[field]
    else:
        outcome[field] = bad_value
    with pytest.raises(ValueError, match="outcome"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize(
    ("section", "field"),
    [
        ("outcomes", "whiff_rate"),
        ("location", "zone_rate"),
        ("arsenal", "usage_hhi"),
        ("arsenal", "fastball_share"),
    ],
)
def test_registered_probability_features_must_be_within_unit_interval(
    section, field
):
    bundle = _bundle(players=2)
    feature = next(
        row
        for row in bundle["features"]
        if row["mlbam_id"] == "1000" and row["season"] == 2022
    )
    feature[section][field] = 2.0
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


def test_pitch_type_usage_must_be_within_unit_interval():
    bundle = _bundle(players=2)
    feature = next(
        row
        for row in bundle["features"]
        if row["mlbam_id"] == "1000" and row["season"] == 2022
    )
    feature["pitch_types"]["four_seam"]["usage"] = 1.01
    with pytest.raises(ValueError, match=r"\[0, 1\]"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda feature: feature.update(pitch_count=-1),
        lambda feature: feature["arsenal"].update(count=-1),
        lambda feature: feature["pitch_types"]["four_seam"]["shape"][
            "velocity"
        ].update(sample_count=-1),
    ],
)
def test_registered_feature_counts_must_be_nonnegative(mutation):
    bundle = _bundle(players=2)
    feature = next(
        row
        for row in bundle["features"]
        if row["mlbam_id"] == "1000" and row["season"] == 2022
    )
    mutation(feature)
    with pytest.raises(ValueError, match="nonnegative"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize("field", ["K", "BB"])
def test_outcome_component_counts_cannot_exceed_batters_faced(field):
    bundle = _bundle(players=2)
    outcome = next(
        row
        for row in bundle["outcomes"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    outcome[field] = outcome["BF"] + 1
    with pytest.raises(ValueError, match="cannot exceed outcome BF"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


def test_zero_ip_outcome_fails_before_fit_or_scored_endpoint_reconstruction(
    monkeypatch,
):
    bundle = _bundle(players=2)
    outcome = next(
        row
        for row in bundle["outcomes"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    outcome["IP"] = 0
    monkeypatch.setattr(
        harness,
        "fit_fold",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid outcome reached fit")
        ),
    )
    with pytest.raises(ValueError, match="outcome IP must be positive"):
        harness.evaluate_registered_look(bundle, _registration())


@pytest.mark.parametrize("field", ["BF", "K", "BB", "ER", "H_ALLOWED"])
def test_observed_outcome_counts_must_be_integer_valued(field):
    bundle = _bundle(players=2)
    outcome = next(
        row
        for row in bundle["outcomes"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    outcome[field] = float(outcome[field]) + 0.5
    with pytest.raises(ValueError, match="integer-valued"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda feature: feature.update(pitch_count=700.5),
        lambda feature: feature["arsenal"].update(count=2.5),
        *[
            (
                lambda feature, field=field: feature["pitch_types"]["four_seam"]
                ["shape"][field].update(sample_count=300.5)
            )
            for field in (
                "velocity",
                "induced_vertical_movement",
                "horizontal_movement",
                "spin",
                "extension",
            )
        ],
    ],
)
def test_consumed_feature_counts_must_be_integer_valued(mutation):
    bundle = _bundle(players=2)
    feature = next(
        row
        for row in bundle["features"]
        if row["mlbam_id"] == "1000" and row["season"] == 2022
    )
    mutation(feature)
    with pytest.raises(ValueError, match="integer-valued"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


def test_outcome_strikeouts_walks_and_hits_cannot_exceed_batters_faced():
    bundle = _bundle(players=2)
    outcome = next(
        row
        for row in bundle["outcomes"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    outcome["H_ALLOWED"] = outcome["BF"] - outcome["K"] - outcome["BB"] + 1
    with pytest.raises(ValueError, match="K plus BB plus H_ALLOWED"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda feature: feature["location"].update(
                heart_rate=feature["location"]["zone_rate"] + 0.01
            ),
            "heart_rate cannot exceed zone_rate",
        ),
        (
            lambda feature: feature["outcomes"].update(
                called_strike_rate=feature["outcomes"]["csw_rate"] + 0.01
            ),
            "called_strike_rate cannot exceed csw_rate",
        ),
        (
            lambda feature: feature["outcomes"].update(
                csw_rate=feature["outcomes"]["called_strike_rate"]
                + feature["outcomes"]["whiff_rate"]
                + 0.01
            ),
            "csw_rate cannot exceed called_strike_rate plus whiff_rate",
        ),
        (
            lambda feature: feature["pitch_types"].update(
                slider={**feature["pitch_types"]["slider"], "usage": 0.5},
                four_seam={
                    **feature["pitch_types"]["four_seam"],
                    "usage": 0.6,
                },
            ),
            "pitch-type usage sum cannot exceed 1",
        ),
        (
            lambda feature: feature["arsenal"].update(count=1),
            "arsenal.count must equal included pitch-type count",
        ),
    ],
)
def test_registered_feature_relations_fail_closed(mutation, message):
    bundle = _bundle(players=2)
    feature = next(
        row
        for row in bundle["features"]
        if row["mlbam_id"] == "1000" and row["season"] == 2022
    )
    mutation(feature)
    with pytest.raises(ValueError, match=message):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize(
    ("field", "bad_value"),
    [
        ("BF", 0.0),
        ("IP", 0.0),
        ("K", -1.0),
        ("BB", -1.0),
        ("HR", -1.0),
        ("HBP", -1.0),
        ("H_ALLOWED", -1.0),
        ("K_9", -1.0),
        ("BB_9", -1.0),
        ("ERA", -1.0),
        ("WHIP", -1.0),
        ("cFIP", -1.0),
        ("cFIP", float("nan")),
        ("p_sp", float("inf")),
    ],
)
def test_result_determining_control_inputs_fail_closed(field, bad_value):
    bundle = _bundle(players=2)
    control = next(
        row
        for row in bundle["controls"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    control[field] = bad_value
    with pytest.raises(ValueError, match="Control"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize("p_sp", [-0.01, 1.01])
def test_control_role_probability_must_be_within_unit_interval(p_sp):
    bundle = _bundle(players=2)
    control = next(
        row
        for row in bundle["controls"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    control["p_sp"] = p_sp
    with pytest.raises(ValueError, match=r"Control p_sp must be in \[0, 1\]"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


def test_control_strikeouts_plus_walks_cannot_exceed_batters_faced():
    bundle = _bundle(players=2)
    control = next(
        row
        for row in bundle["controls"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    control["K"] = control["BF"] - control["BB"] + 1
    with pytest.raises(ValueError, match="Control K plus BB cannot exceed Control BF"):
        harness.prepare_fold(bundle, 2023, minimum_pitches=500)


@pytest.mark.parametrize("fallback_kind", ["missing_feature", "below_pitch_floor"])
def test_invalid_control_cannot_reach_fit_or_exact_control_fallback(
    monkeypatch, fallback_kind
):
    bundle = _bundle(players=2)
    if fallback_kind == "missing_feature":
        bundle["features"] = [
            row
            for row in bundle["features"]
            if not (row["mlbam_id"] == "1000" and row["season"] == 2022)
        ]
    else:
        feature = next(
            row
            for row in bundle["features"]
            if row["mlbam_id"] == "1000" and row["season"] == 2022
        )
        feature["pitch_count"] = 499
    control = next(
        row
        for row in bundle["controls"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    control["WHIP"] = float("nan")
    monkeypatch.setattr(
        harness,
        "fit_fold",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("invalid Control reached fit")
        ),
    )
    with pytest.raises(ValueError, match="Control"):
        harness.evaluate_registered_look(bundle, _registration())


def test_observed_ip_and_projected_control_counts_may_remain_fractional():
    bundle = _bundle(players=2)
    outcome = next(
        row
        for row in bundle["outcomes"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    outcome["IP"] = 149.1
    control = next(
        row
        for row in bundle["controls"]
        if row["mlbam_id"] == "1000" and row["season"] == 2023
    )
    control.update(IP=149.1, K=150.5, BB=47.25, HR=17.5, HBP=4.25)
    fold = harness.prepare_fold(bundle, 2023, minimum_pitches=500)
    assert fold["qualification"]["eligible"] == 2


def test_registration_extraction_is_deterministic_and_drift_fails_before_fit(tmp_path, monkeypatch):
    registration = _registration()
    plan = tmp_path / "plan.md"
    plan.write_text(
        "<!-- mlb-pitcher-skill-registration:start -->\n```json\n"
        + json.dumps(registration, indent=2)
        + "\n```\n<!-- mlb-pitcher-skill-registration:end -->\n",
        encoding="utf-8",
    )
    first = harness.load_registration(plan)
    second = harness.load_registration(plan)
    assert first == second == registration
    harness.validate_registration(first, require_seals=True)

    called = False
    def forbidden_fit(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("fit must not run")
    monkeypatch.setattr(harness, "fit_fold", forbidden_fit)
    drifted = copy.deepcopy(registration)
    drifted["ridge_lambda"] = 9.0
    with pytest.raises(ValueError, match="registration drift"):
        harness.evaluate_registered_look(_bundle(players=30), drifted)
    assert called is False


def test_registered_param_and_control_floor_drift_fail_before_fit(monkeypatch):
    called = False

    def forbidden_fit(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("fit must not run")

    monkeypatch.setattr(harness, "fit_fold", forbidden_fit)
    monkeypatch.setattr(
        harness,
        "PitcherSkillChallengerParams",
        lambda: SimpleNamespace(
            ridge_lambda=9.0,
            minimum_input_pitches=500,
            residual_clip_quantiles=(0.05, 0.95),
        ),
    )
    with pytest.raises(ValueError, match="parameter defaults"):
        harness.evaluate_registered_look(_bundle(players=30), _registration())
    assert called is False


def test_registered_control_param_defaults_fail_closed_before_fit(monkeypatch):
    monkeypatch.setattr(
        harness,
        "PitcherMarcelParams",
        lambda: SimpleNamespace(
            season_weights=(5.0, 4.0, 3.0),
            n_reg=301.0,
            era_from_fip=True,
        ),
    )
    monkeypatch.setattr(
        harness,
        "fit_fold",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("fit must not run")
        ),
    )
    with pytest.raises(ValueError, match="Control parameter defaults"):
        harness.evaluate_registered_look(_bundle(players=30), _registration())


def test_implementation_seal_covers_every_result_determining_path(monkeypatch):
    calls = []

    def clean_git(*args):
        calls.append(args)
        if args[0] == "status":
            return ""
        return "a" * 40

    monkeypatch.setattr(runner, "_git", clean_git)
    assert runner.current_implementation_commit() == "a" * 40
    log_call = next(args for args in calls if args[0] == "log")
    expected = {
        "projections/models/pitcher_skill_challenger.py",
        "projections/backtest/pitcher_skill_challenger_harness.py",
        "scripts/run_mlb_pitcher_skill_challenger.py",
        "projections/models/marcel_pitcher.py",
        "projections/models/pitcher_params.py",
        "projections/models/pitcher_role.py",
        "projections/backtest/pitching_harness.py",
        "projections/constants.py",
        "projections/data/pitching_historical.py",
        "projections/data/identity.py",
    }
    assert expected <= set(log_call)


@pytest.mark.parametrize(
    ("dirty_marker", "dirty_path"),
    [
        (" M", "projections/models/marcel_pitcher.py"),
        ("M ", "projections/data/identity.py"),
    ],
)
def test_implementation_seal_rejects_dirty_control_or_identity_path(
    monkeypatch, dirty_marker, dirty_path
):
    def dirty_git(*args):
        if args[0] == "status":
            assert dirty_path in args
            return f"{dirty_marker} {dirty_path}"
        return "a" * 40

    monkeypatch.setattr(runner, "_git", dirty_git)
    with pytest.raises(ValueError, match="uncommitted"):
        runner.current_implementation_commit()


def test_readiness_hash_binds_every_joined_input_without_publishing_rows():
    registration = _registration()
    bundle = _bundle(players=60)
    reserve = "reserve"
    bundle["controls"].append(_control(reserve, 2020))
    bundle["outcomes"].append(_outcome(reserve, 2020))
    bundle["features"].append(_feature(reserve, 2019))
    bundle["identities"].append({"mlbam_id": reserve, "throws": "R"})
    bundle["persistence"].append(
        {
            "mlbam_id": reserve,
            "season": 2020,
            "forecast_window": "full_season",
            "K_9": 9.5,
            "BB_9": 2.9,
            "ERA": 3.5,
            "WHIP": 1.1,
        }
    )
    bundle["common_support"] = harness.summarize_common_support(bundle)
    unsealed = {
        key: value for key, value in registration.items() if key != "readiness_hash"
    }
    baseline = harness.check_readiness(
        bundle,
        unsealed,
        implementation_commit="a" * 40,
        source_hashes=registration["source_hashes"],
        serving_import_matches=[],
    )
    registration["readiness_hash"] = baseline["evidence_hash"]
    assert harness.check_readiness(
        bundle,
        registration,
        implementation_commit="a" * 40,
        source_hashes=registration["source_hashes"],
        serving_import_matches=[],
    )["ready_to_spend"] is True

    mutations = []

    outcome_changed = copy.deepcopy(bundle)
    next(
        row
        for row in outcome_changed["outcomes"]
        if row["mlbam_id"] == "1000" and row["season"] == 2020
    )["K"] = 175.0
    mutations.append(outcome_changed)

    identity_changed = copy.deepcopy(bundle)
    next(
        row for row in identity_changed["identities"] if row["mlbam_id"] == "1000"
    )["throws"] = "L"
    mutations.append(identity_changed)

    pairs_changed = copy.deepcopy(bundle)
    pair = next(
        row
        for row in pairs_changed["pair_keys"]
        if row["mlbam_id"] == "1000" and row["outcome_season"] == 2020
    )
    pair["mlbam_id"] = reserve
    pairs_changed["common_support"] = harness.summarize_common_support(pairs_changed)
    mutations.append(pairs_changed)

    feature_changed = copy.deepcopy(bundle)
    next(
        row
        for row in feature_changed["features"]
        if row["mlbam_id"] == "1000" and row["season"] == 2019
    )["outcomes"]["whiff_rate"] += 0.01
    mutations.append(feature_changed)

    control_changed = copy.deepcopy(bundle)
    next(
        row
        for row in control_changed["controls"]
        if row["mlbam_id"] == "1000" and row["season"] == 2020
    )["K"] += 1.0
    mutations.append(control_changed)

    for changed in mutations:
        readiness = harness.check_readiness(
            changed,
            registration,
            implementation_commit="a" * 40,
            source_hashes=registration["source_hashes"],
            serving_import_matches=[],
        )
        assert readiness["ready_to_spend"] is False
        assert "readiness_hash_mismatch" in readiness["blockers"]
        assert readiness["evidence_hash"] != baseline["evidence_hash"]
        assert readiness["scoreable_population"] == baseline["scoreable_population"]

    hashes = baseline["input_hashes"]
    assert set(hashes) == {
        "controls_sha256",
        "outcomes_sha256",
        "identities_sha256",
        "pair_keys_sha256",
        "features_sha256",
        "persistence_sha256",
        "steamer_sha256",
        "source_manifest_sha256",
    }
    assert all(len(value) == 64 for value in hashes.values())
    encoded = json.dumps(hashes)
    assert "1000" not in encoded
    assert reserve not in encoded


def test_readiness_requires_every_registered_scored_fold_even_when_total_is_large():
    registration = _registration()
    bundle = _bundle(players=60)
    bundle["pair_keys"] = [
        row for row in bundle["pair_keys"] if row["outcome_season"] != 2020
    ]
    bundle["common_support"]["scored_target_seasons"] = list(TARGET_SEASONS[1:])
    readiness = harness.check_readiness(
        bundle,
        registration,
        implementation_commit="a" * 40,
        source_hashes=registration["source_hashes"],
        serving_import_matches=[],
    )
    assert readiness["scoreable_population"] >= 250
    assert readiness["ready_to_spend"] is False
    assert "scored_target_seasons_mismatch" in readiness["blockers"]
    assert "missing_declared_pairs:2020" in readiness["blockers"]
    assert "missing_qualified_support:2020" in readiness["blockers"]


def test_unmatched_control_and_outcome_rows_are_disclosed_not_invalid():
    registration = _registration()
    bundle = _bundle(players=50)
    bundle["controls"].append(_control("control-only", 2020))
    bundle["outcomes"].append(_outcome("outcome-only", 2020))
    bundle["identities"].extend(
        [
            {"mlbam_id": "control-only", "throws": "R"},
            {"mlbam_id": "outcome-only", "throws": "L"},
        ]
    )
    bundle["features"].extend(
        [
            _feature("control-only", 2019),
            _feature("outcome-only", 2019),
        ]
    )
    bundle["common_support"] = harness.summarize_common_support(bundle)
    fold = harness.prepare_fold(bundle, 2020, minimum_pitches=500)
    scored_ids = {row["mlbam_id"] for row in fold["scoring_rows"]}
    assert "control-only" not in scored_ids
    assert "outcome-only" not in scored_ids
    provisional = harness.check_readiness(
        bundle,
        {key: value for key, value in registration.items() if key != "readiness_hash"},
        implementation_commit="a" * 40,
        source_hashes=registration["source_hashes"],
        serving_import_matches=[],
    )
    registration["readiness_hash"] = provisional["evidence_hash"]
    readiness = harness.check_readiness(
        bundle,
        registration,
        implementation_commit="a" * 40,
        source_hashes=registration["source_hashes"],
        serving_import_matches=[],
    )
    assert readiness["ready_to_spend"] is True
    assert readiness["common_support"]["by_season"]["2020"] == {
        "control_count": 51,
        "outcome_count": 51,
        "pair_count": 50,
        "control_only_count": 1,
        "outcome_only_count": 1,
    }
    assert readiness["common_support"]["totals"]["control_only_count"] == 1
    assert readiness["common_support"]["totals"]["outcome_only_count"] == 1


def test_unsealed_registration_reports_missing_hashes_but_cannot_be_ready_or_spent(monkeypatch):
    registration = _registration(sealed=False)
    bundle = _bundle(players=30)
    readiness = harness.check_readiness(
        bundle,
        registration,
        implementation_commit="a" * 40,
        source_hashes={str(year): f"sha-{year}" for year in FEATURE_SEASONS},
        serving_import_matches=[],
    )
    assert readiness["ready_to_spend"] is False
    assert readiness["missing_registration_seals"] == ["implementation_commit", "readiness_hash", "source_hashes"]
    assert "endpoint" not in json.dumps(readiness).lower()
    assert "prediction" not in json.dumps(readiness).lower()

    monkeypatch.setattr(runner, "load_study_bundle", lambda registration: bundle)
    monkeypatch.setattr(runner, "current_implementation_commit", lambda: "a" * 40)
    monkeypatch.setattr(runner, "current_source_hashes", lambda registration: readiness["source_hashes"])
    monkeypatch.setattr(runner, "load_registration", lambda path=runner.PLAN_PATH: registration)
    with pytest.raises(ValueError, match="sealed"):
        runner.main(["--spend-registered-look"])


def test_readiness_checks_sources_population_seed_imports_and_sealed_hashes_without_scoring(monkeypatch):
    registration = _registration()
    bundle = _bundle(players=50)
    provisional = harness.check_readiness(
        bundle,
        {key: value for key, value in registration.items() if key != "readiness_hash"},
        implementation_commit="a" * 40,
        source_hashes=registration["source_hashes"],
        serving_import_matches=[],
    )
    registration["readiness_hash"] = provisional["evidence_hash"]
    monkeypatch.setattr(harness, "fit_fold", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("readiness scored")))
    ready = harness.check_readiness(bundle, registration, implementation_commit="a" * 40, source_hashes=registration["source_hashes"], serving_import_matches=[])
    assert ready["ready_to_spend"] is True
    assert ready["scoreable_population"] >= 250
    assert ready["fold_training_counts"]["2020"] > 0
    assert ready["required_feature_seasons"] == list(FEATURE_SEASONS)

    poisoned = copy.deepcopy(registration)
    poisoned["bootstrap_seed"] = poisoned["forbidden_bootstrap_seeds"][0]
    with pytest.raises(ValueError, match="seed"):
        harness.check_readiness(bundle, poisoned, implementation_commit="a" * 40, source_hashes=registration["source_hashes"], serving_import_matches=[])


def test_atomic_spent_write_refuses_every_existing_file_even_if_identical(tmp_path):
    path = tmp_path / "result.json"
    payload = {**harness.BASE_FLAGS, "verdict": "invalid"}
    harness.write_spent_result(path, payload)
    original = path.read_bytes()
    with pytest.raises(FileExistsError, match="already exists"):
        harness.write_spent_result(path, payload)
    assert path.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


def test_runner_failure_writes_spent_error_with_fail_closed_boundaries(tmp_path, monkeypatch):
    registration = _registration()
    output = tmp_path / "result.json"
    monkeypatch.setattr(runner, "OUTPUT_PATH", output)
    monkeypatch.setattr(runner, "load_registration", lambda path=runner.PLAN_PATH: registration)
    monkeypatch.setattr(runner, "load_study_bundle", lambda registration: _bundle(players=30))
    monkeypatch.setattr(runner, "current_implementation_commit", lambda: "a" * 40)
    monkeypatch.setattr(runner, "current_source_hashes", lambda registration: registration["source_hashes"])
    monkeypatch.setattr(runner, "serving_import_matches", lambda: [])
    monkeypatch.setattr(runner, "evaluate_registered_look", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(runner, "build_readiness", lambda *args, **kwargs: {"ready_to_spend": True, "evidence_hash": registration["readiness_hash"]})
    assert runner.main(["--spend-registered-look"]) == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert {key: result[key] for key in harness.BASE_FLAGS} == harness.BASE_FLAGS
    assert result["verdict"] == "spent_error"
    assert result["implementation_commit"] == registration["implementation_commit"]
    assert result["source_hashes"] == registration["source_hashes"]
    assert result["registration_hash"] == harness.canonical_sha256(registration)
    assert result["readiness_hash"] == registration["readiness_hash"]
    assert "boom" not in json.dumps(result)


def test_serving_import_scan_follows_indirect_production_python_imports(tmp_path, monkeypatch):
    (tmp_path / "projections" / "backtest").mkdir(parents=True)
    (tmp_path / "projections" / "models").mkdir(parents=True)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "serving_package").mkdir()
    (tmp_path / "app.py").write_text(
        "import serving_helper\nimport serving_package\n", encoding="utf-8"
    )
    (tmp_path / "serving_helper.py").write_text(
        "from projections.backtest import pitcher_skill_challenger_harness\n",
        encoding="utf-8",
    )
    (tmp_path / "projections" / "backtest" / "pitcher_skill_challenger_harness.py").write_text(
        "from projections.models import pitcher_skill_challenger\n", encoding="utf-8"
    )
    (tmp_path / "projections" / "models" / "pitcher_skill_challenger.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "run_mlb_pitcher_skill_challenger.py").write_text(
        "VALUE = 1\n", encoding="utf-8"
    )
    (tmp_path / "serving_package" / "__init__.py").write_text(
        "from . import nested\n", encoding="utf-8"
    )
    (tmp_path / "serving_package" / "nested.py").write_text(
        "from projections.models import pitcher_skill_challenger\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_allowed.py").write_text(
        "from projections.backtest import pitcher_skill_challenger_harness\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "ROOT", tmp_path)
    matches = runner.serving_import_matches()
    assert any(match.startswith("app.py -> serving_helper.py ->") for match in matches)
    assert any(
        match.startswith(
            "app.py -> serving_package/__init__.py -> serving_package/nested.py ->"
        )
        for match in matches
    )
    assert not any("tests/test_allowed.py" in match for match in matches)


def test_real_serving_graph_allows_sealed_control_dependencies():
    assert runner.serving_import_matches() == []


@pytest.mark.parametrize(
    "argv",
    [[], ["--check-readiness", "--spend-registered-look"], ["--unknown"], ["--seed", "1"], ["--output", "other.json"], ["--folds", "2025"]],
)
def test_cli_has_exactly_two_modes_and_no_tuning_surface(argv):
    with pytest.raises(SystemExit):
        runner.parse_args(argv)


def test_check_readiness_cli_never_scores_or_writes_result(monkeypatch, capsys):
    registration = _registration(sealed=False)
    bundle = _bundle(players=30)
    monkeypatch.setattr(runner, "load_registration", lambda path=runner.PLAN_PATH: registration)
    monkeypatch.setattr(runner, "load_study_bundle", lambda registration: bundle)
    monkeypatch.setattr(runner, "current_implementation_commit", lambda: "a" * 40)
    monkeypatch.setattr(runner, "current_source_hashes", lambda registration: {str(year): f"sha-{year}" for year in FEATURE_SEASONS})
    monkeypatch.setattr(runner, "serving_import_matches", lambda: [])
    monkeypatch.setattr(runner, "evaluate_registered_look", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("scored")))
    monkeypatch.setattr(runner, "write_spent_result", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("wrote")))
    assert runner.main(["--check-readiness"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ready_to_spend"] is False
