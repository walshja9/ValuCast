import copy
import json
import math

import pytest

from projections.models.pitcher_skill_challenger import (
    FEATURE_ORDER,
    PitcherSkillChallengerParams,
    apply_rates_to_control,
    fit_fold,
    predict_rates,
)


def _control(
    mlbam_id="1",
    season=2020,
    *,
    bf=600.0,
    ip=150.0,
    k_bf=0.25,
    bb_bf=0.08,
    p_sp=0.7,
    cfip=3.2,
):
    k = round(k_bf * bf, 4)
    bb = round(bb_bf * bf, 4)
    hr = 18.0
    hbp = 5.0
    hits = 130.0
    raw_fip = (13.0 * hr + 3.0 * (bb + hbp) - 2.0 * k) / ip
    era = max(0.0, raw_fip + cfip)
    return {
        "mlbam_id": str(mlbam_id),
        "season": int(season),
        "BF": bf,
        "IP": ip,
        "K": k,
        "BB": bb,
        "HR": hr,
        "HBP": hbp,
        "H_ALLOWED": hits,
        "ER": round(era * ip / 9.0, 4),
        "ERA": round(era, 3),
        "cFIP": cfip,
        "WHIP": round((bb + hits) / ip, 3),
        "K_9": round(9.0 * k / ip, 3),
        "BB_9": round(9.0 * bb / ip, 3),
        "K_BB": round(k / bb, 3),
        "GS": 25.0,
        "G": 30.0,
        "QS": 15.0,
        "SV": 0.0,
        "HLD": 2.0,
        "W": 12.0,
        "p_sp": p_sp,
        "role": "starter",
        "availability": "available",
        "opportunity": {"rotation_slot": 2, "projected_starts": 25},
    }


def _shape(mean, sample_count=300):
    return {"mean": mean, "sample_count": sample_count, "missing_count": 0}


def _feature(
    mlbam_id="1",
    season=2019,
    *,
    signal=0.0,
    pitch_count=700,
    hand="R",
    missing_shapes=(),
):
    def shape_values(speed, horizontal, vertical, spin, extension):
        values = {
            "velocity": speed,
            "horizontal_movement": horizontal,
            "induced_vertical_movement": vertical,
            "spin": spin,
            "extension": extension,
        }
        return {
            key: _shape(None if key in missing_shapes else value)
            for key, value in values.items()
        }

    return {
        "mlbam_id": str(mlbam_id),
        "season": int(season),
        "pitcher_hand": hand,
        "pitch_count": pitch_count,
        "outcomes": {
            "whiff_rate": 0.25 + signal * 0.01,
            "csw_rate": 0.29 + signal * 0.008,
            "called_strike_rate": 0.16 - signal * 0.002,
        },
        "location": {
            "zone_rate": 0.50 + signal * 0.004,
            "heart_rate": 0.24 - signal * 0.003,
            "edge_rate": 0.35 + signal * 0.002,
            "waste_rate": 0.10 - signal * 0.001,
            "plate_x": {"stddev": 0.71 + signal * 0.01},
            "plate_z": {"stddev": 0.78 + signal * 0.01},
        },
        "pitch_types": {
            "four_seam": {
                "usage": 0.6,
                "shape": shape_values(
                    94.0 + signal,
                    -8.0 - signal,
                    15.0 + signal,
                    2300.0 + signal * 30.0,
                    6.2 + signal * 0.05,
                ),
            },
            "slider": {
                "usage": 0.4,
                "shape": shape_values(
                    84.0 + signal * 0.5,
                    4.0 + signal,
                    2.0 - signal,
                    2400.0 + signal * 20.0,
                    5.9 + signal * 0.04,
                ),
            },
        },
        "arsenal": {
            "count": 2,
            "usage_hhi": 0.52,
            "fastball_share": 0.6,
            "max_velocity_separation": 10.0 + signal * 0.5,
            "max_movement_separation": 15.0 + signal,
        },
    }


def _training_row(
    mlbam_id,
    outcome_season,
    *,
    signal=0.0,
    k_residual=None,
    bb_residual=None,
    missing_shapes=(),
    fold_target_season=2030,
):
    control = _control(mlbam_id, outcome_season)
    feature = _feature(
        mlbam_id,
        outcome_season - 1,
        signal=signal,
        missing_shapes=missing_shapes,
    )
    k_residual = signal * 0.01 if k_residual is None else k_residual
    bb_residual = -signal * 0.003 if bb_residual is None else bb_residual
    outcome_bf = 620.0
    outcome = {
        "mlbam_id": str(mlbam_id),
        "season": int(outcome_season),
        "BF": outcome_bf,
        "K": (control["K"] / control["BF"] + k_residual) * outcome_bf,
        "BB": (control["BB"] / control["BF"] + bb_residual) * outcome_bf,
    }
    return {
        "mlbam_id": str(mlbam_id),
        "feature_season": int(outcome_season - 1),
        "outcome_season": int(outcome_season),
        "fold_target_season": int(fold_target_season),
        "control": control,
        "feature_row": feature,
        "outcome": outcome,
    }


def _rows(count=8):
    return [
        _training_row(index + 1, 2018 + index, signal=index - count / 2)
        for index in range(count)
    ]


def _reverse_mapping_order(value):
    if isinstance(value, dict):
        return {
            key: _reverse_mapping_order(value[key])
            for key in reversed(list(value))
        }
    if isinstance(value, list):
        return [_reverse_mapping_order(item) for item in value]
    return value


def _all_finite(value):
    if isinstance(value, dict):
        return all(_all_finite(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_all_finite(item) for item in value)
    return not isinstance(value, float) or math.isfinite(value)


def test_fit_requires_exact_t_minus_one_identity_join_and_rejects_duplicates():
    valid = _training_row("101", 2020)
    model = fit_fold([valid], PitcherSkillChallengerParams())
    assert model["training_row_count"] == 1

    bad_rows = []
    same_season = copy.deepcopy(valid)
    same_season["feature_season"] = 2020
    bad_rows.append(same_season)
    feature_mismatch = copy.deepcopy(valid)
    feature_mismatch["feature_row"]["mlbam_id"] = "999"
    bad_rows.append(feature_mismatch)
    outcome_mismatch = copy.deepcopy(valid)
    outcome_mismatch["outcome"]["season"] = 2021
    bad_rows.append(outcome_mismatch)
    control_mismatch = copy.deepcopy(valid)
    control_mismatch["control"]["mlbam_id"] = "999"
    bad_rows.append(control_mismatch)
    malformed = copy.deepcopy(valid)
    del malformed["outcome"]["BF"]
    bad_rows.append(malformed)

    for row in bad_rows:
        with pytest.raises(ValueError):
            fit_fold([row], PitcherSkillChallengerParams())
    with pytest.raises(ValueError, match="duplicate"):
        fit_fold([valid, copy.deepcopy(valid)], PitcherSkillChallengerParams())


def test_poisoned_held_out_rows_cannot_change_any_fold_local_payload():
    all_rows = _rows(8)
    test_season = 2024
    training = [row for row in all_rows if row["outcome_season"] < test_season]
    held_out = [row for row in all_rows if row["outcome_season"] >= test_season]
    for row in training:
        row["fold_target_season"] = test_season
    before = fit_fold(training, PitcherSkillChallengerParams())

    for row in held_out:
        row["feature_row"] = _feature(
            row["mlbam_id"], row["feature_season"], signal=1_000_000
        )
        row["outcome"]["K"] = 1e100
        row["outcome"]["BB"] = -1e100
        row["player_name"] = "POISON MUST NEVER ENTER MODEL"
    after = fit_fold(training, PitcherSkillChallengerParams())

    assert after == before
    assert "POISON" not in json.dumps(after, sort_keys=True)


def test_fit_rejects_target_or_future_outcomes_and_mixed_fold_targets():
    valid = _training_row("1", 2023, fold_target_season=2024)
    target = _training_row("2", 2024, fold_target_season=2024)
    future = _training_row("3", 2025, fold_target_season=2024)
    mixed_target = _training_row("4", 2022, fold_target_season=2025)

    for poison in (target, future):
        with pytest.raises(ValueError, match="before fold target"):
            fit_fold([valid, poison], PitcherSkillChallengerParams())
    with pytest.raises(ValueError, match="common fold target"):
        fit_fold([valid, mixed_target], PitcherSkillChallengerParams())


def test_fit_and_prediction_are_deterministic_under_row_and_key_reordering():
    rows = _rows(7)
    params = PitcherSkillChallengerParams()
    forward = fit_fold(rows, params)
    reordered = fit_fold(
        [_reverse_mapping_order(row) for row in reversed(rows)], params
    )
    control = _control("50", 2026)
    feature = _feature("50", 2025, signal=1.25)

    assert reordered == forward
    assert predict_rates(forward, control, feature) == predict_rates(
        reordered,
        _reverse_mapping_order(control),
        _reverse_mapping_order(feature),
    )


def test_constant_and_singular_columns_are_finite_and_intercept_is_unpenalized():
    rows = [
        _training_row(
            index,
            2020 + index,
            signal=0.0,
            k_residual=0.04,
            bb_residual=-0.01,
        )
        for index in range(1, 5)
    ]
    model = fit_fold(rows, PitcherSkillChallengerParams())
    predicted = predict_rates(model, _control("9", 2026), _feature("9", 2025))

    assert _all_finite(model)
    assert predicted["k_bf"] == pytest.approx(0.29)
    assert predicted["bb_bf"] == pytest.approx(0.07)


def test_nullable_shape_uses_training_median_and_explicit_known_flag():
    rows = [
        _training_row("1", 2020, signal=-3.0),
        _training_row("2", 2021, signal=-2.0),
        _training_row("3", 2022, signal=6.0),
        _training_row("4", 2023, signal=1.0, missing_shapes=("spin",)),
    ]
    model = fit_fold(rows, PitcherSkillChallengerParams())
    spin_index = model["feature_order"].index("spin_deviation")
    known_index = model["feature_order"].index("spin_known")

    assert model["shape_medians"]["spin_deviation"] != 0.0
    assert model["shape_medians"]["spin_deviation"] == pytest.approx(-60.6666667)
    assert model["scalers"]["means"][known_index] == pytest.approx(0.75)
    assert model["scalers"]["means"][spin_index] == pytest.approx(-15.1666667)


def test_fold_without_any_known_shape_value_fails_closed_instead_of_using_zero():
    rows = [
        _training_row(
            str(index),
            2020 + index,
            signal=float(index),
            missing_shapes=("extension",),
        )
        for index in range(1, 5)
    ]

    with pytest.raises(ValueError, match="no training median for extension"):
        fit_fold(rows, PitcherSkillChallengerParams())


def test_missing_or_below_floor_feature_returns_control_rates_exactly():
    model = fit_fold(_rows(6), PitcherSkillChallengerParams())
    control = _control("50", 2026, k_bf=0.237, bb_bf=0.071)
    expected = {
        "k_bf": control["K"] / control["BF"],
        "bb_bf": control["BB"] / control["BF"],
    }

    assert predict_rates(model, control, None) == expected
    assert predict_rates(
        model,
        control,
        _feature("50", 2025, pitch_count=499),
    ) == expected


def test_prediction_requires_nonempty_matching_identities_or_returns_control():
    model = fit_fold(_rows(6), PitcherSkillChallengerParams())
    control = _control("50", 2026, k_bf=0.237, bb_bf=0.071)
    expected = {
        "k_bf": control["K"] / control["BF"],
        "bb_bf": control["BB"] / control["BF"],
    }

    missing_control_id = copy.deepcopy(control)
    missing_control_id["mlbam_id"] = ""
    missing_feature_id = _feature("50", 2025)
    missing_feature_id["mlbam_id"] = ""
    both_missing_control_id = copy.deepcopy(missing_control_id)
    both_missing_feature_id = copy.deepcopy(missing_feature_id)

    assert predict_rates(model, missing_control_id, _feature("50", 2025)) == expected
    assert predict_rates(model, control, missing_feature_id) == expected
    assert predict_rates(model, control, _feature("999", 2025)) == expected
    assert predict_rates(
        model, both_missing_control_id, both_missing_feature_id
    ) == expected


def test_malformed_nested_evidence_fails_closed_without_attribute_errors():
    model = fit_fold(_rows(6), PitcherSkillChallengerParams())
    control = _control("50", 2026)
    expected = {
        "k_bf": control["K"] / control["BF"],
        "bb_bf": control["BB"] / control["BF"],
    }
    malformed_feature = _feature("50", 2025)
    malformed_feature["pitch_types"] = []

    assert predict_rates(model, control, malformed_feature) == expected

    malformed_training = _training_row("50", 2026)
    malformed_training["feature_row"]["outcomes"] = []
    with pytest.raises(ValueError, match="malformed"):
        fit_fold([malformed_training], PitcherSkillChallengerParams())

    overflowing_feature = _feature("50", 2025)
    overflowing_feature["pitch_count"] = 10**400
    assert predict_rates(model, control, overflowing_feature) == expected

    overflowing_training = _training_row("51", 2026)
    overflowing_training["feature_row"]["pitch_count"] = 10**400
    with pytest.raises(ValueError, match="invalid pitch_count"):
        fit_fold([overflowing_training], PitcherSkillChallengerParams())


def test_finite_inputs_that_overflow_fold_statistics_fail_closed():
    rows = _rows(4)
    for row in rows:
        row["feature_row"]["pitch_types"]["four_seam"]["shape"]["velocity"][
            "mean"
        ] = 1e308

    with pytest.raises(ValueError, match="non-finite"):
        fit_fold(rows, PitcherSkillChallengerParams())


def test_residual_corrections_use_pinned_type7_training_p5_p95_clips():
    rows = [
        _training_row(
            str(index),
            2010 + index,
            signal=float(index),
            k_residual=index / 100.0,
            bb_residual=-index / 200.0,
        )
        for index in range(10)
    ]
    model = fit_fold(rows, PitcherSkillChallengerParams())
    control = _control("99", 2026)
    high = predict_rates(model, control, _feature("99", 2025, signal=1_000.0))

    assert model["quantile_convention"] == "type7_linear"
    assert model["residual_clip_bounds"]["k_bf"] == pytest.approx(
        [0.0045, 0.0855]
    )
    assert model["residual_clip_bounds"]["bb_bf"] == pytest.approx(
        [-0.04275, -0.00225]
    )
    assert high["k_bf"] == pytest.approx(0.25 + 0.0855)
    assert high["bb_bf"] == pytest.approx(0.08 - 0.04275)


def test_predicted_rates_are_always_finite_and_bounded():
    rows = [
        _training_row(
            str(index),
            2010 + index,
            signal=float(index),
            k_residual=0.7,
            bb_residual=-0.07,
        )
        for index in range(1, 6)
    ]
    model = fit_fold(rows, PitcherSkillChallengerParams())
    rates = predict_rates(
        model,
        _control("99", 2026, k_bf=0.9, bb_bf=0.1),
        _feature("99", 2025, signal=1e100),
    )

    assert all(math.isfinite(value) and 0.0 <= value <= 1.0 for value in rates.values())


def test_apply_reports_null_k_bb_at_zero_walks():
    # Review P2-5: K/BB is undefined at zero walks — null, never 0.0 (which
    # would report the best possible outcome as the worst possible ratio).
    control = _control("42", 2026, bf=601.0, ip=149.2)
    result = apply_rates_to_control(control, k_bf=0.3333333, bb_bf=0.0)

    assert result["BB"] == 0.0
    assert result["K_BB"] is None


def test_apply_changes_only_skill_counts_and_reconciles_fip_whip_arithmetic():
    control = _control("42", 2026, bf=601.0, ip=149.2)
    original = copy.deepcopy(control)
    result = apply_rates_to_control(control, k_bf=0.3333333, bb_bf=0.0555555)

    assert control == original
    assert result["K"] == 200.3333
    assert result["BB"] == 33.3889
    unchanged = {
        "BF",
        "IP",
        "GS",
        "G",
        "QS",
        "SV",
        "HLD",
        "HR",
        "HBP",
        "H_ALLOWED",
        "p_sp",
        "role",
        "availability",
        "opportunity",
        "W",
        "mlbam_id",
        "season",
        "cFIP",
    }
    assert {key: result[key] for key in unchanged} == {
        key: original[key] for key in unchanged
    }

    corrected_raw_fip = (
        13.0 * result["HR"]
        + 3.0 * (result["BB"] + result["HBP"])
        - 2.0 * result["K"]
    ) / result["IP"]
    expected_era = max(0.0, corrected_raw_fip + original["cFIP"])
    assert result["ERA"] == round(expected_era, 3)
    assert result["ER"] == round(expected_era * result["IP"] / 9.0, 4)
    assert result["WHIP"] == round(
        (result["BB"] + original["H_ALLOWED"]) / original["IP"], 3
    )
    assert result["K_9"] == round(9.0 * result["K"] / original["IP"], 3)
    assert result["BB_9"] == round(9.0 * result["BB"] / original["IP"], 3)


def test_apply_uses_exact_fold_cfip_instead_of_inferring_from_rounded_era():
    control = _control("42", 2026, bf=601.0, ip=149.2, cfip=3.2009)
    result = apply_rates_to_control(control, k_bf=0.3333333, bb_bf=0.0555555)
    corrected_raw_fip = (
        13.0 * result["HR"]
        + 3.0 * (result["BB"] + result["HBP"])
        - 2.0 * result["K"]
    ) / result["IP"]
    exact_era = max(0.0, corrected_raw_fip + control["cFIP"])
    control_raw_fip = (
        13.0 * control["HR"]
        + 3.0 * (control["BB"] + control["HBP"])
        - 2.0 * control["K"]
    ) / control["IP"]
    old_inferred_era = corrected_raw_fip + (control["ERA"] - control_raw_fip)

    assert result["ERA"] == round(exact_era, 3) == 2.856
    assert round(old_inferred_era, 3) == 2.855
    assert result["ER"] == round(exact_era * control["IP"] / 9.0, 4)

    missing_cfip = copy.deepcopy(control)
    del missing_cfip["cFIP"]
    with pytest.raises(ValueError, match="cFIP"):
        apply_rates_to_control(missing_cfip, k_bf=0.3333333, bb_bf=0.0555555)


def test_payload_is_fixed_auditable_and_contains_no_names_ids_or_raw_rows():
    rows = _rows(6)
    rows[0]["player_name"] = "NEVER SERIALIZE"
    originals = copy.deepcopy(rows)
    params = PitcherSkillChallengerParams()
    model = fit_fold(rows, params)
    encoded = json.dumps(model, sort_keys=True)

    assert rows == originals
    assert set(model) == {
        "research_only",
        "params",
        "feature_order",
        "training_row_count",
        "shape_references",
        "shape_medians",
        "scalers",
        "coefficients",
        "residual_clip_bounds",
        "quantile_convention",
    }
    assert model["research_only"] is True
    assert model["params"] == {
        "ridge_lambda": 10.0,
        "minimum_input_pitches": 500,
        "residual_clip_quantiles": [0.05, 0.95],
    }
    assert tuple(model["feature_order"]) == FEATURE_ORDER
    assert model["training_row_count"] == len(rows)
    for token in ("NEVER SERIALIZE", "player_name", "mlbam_id", '"raw"'):
        assert token not in encoded


def test_fixed_params_reject_tuning_and_inputs_remain_unmodified():
    rows = _rows(6)
    original_rows = copy.deepcopy(rows)
    with pytest.raises(ValueError, match="fixed registered parameters"):
        fit_fold(rows, PitcherSkillChallengerParams(ridge_lambda=1.0))
    assert rows == original_rows

    model = fit_fold(rows, PitcherSkillChallengerParams())
    control = _control("50", 2026)
    feature = _feature("50", 2025)
    original_control = copy.deepcopy(control)
    original_feature = copy.deepcopy(feature)
    predict_rates(model, control, feature)
    assert control == original_control
    assert feature == original_feature
