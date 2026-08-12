import copy
import math

import pytest

from prospects.common_target_calibration import (
    CalibrationError,
    apply_common_target_calibrators,
    build_role_calibrator,
    fit_isotonic,
    predict_isotonic,
)


def test_pooled_adjacent_violators_is_deterministic_and_monotone():
    first = fit_isotonic([3, 1, 2, 2], [0.9, 0.2, 0.8, 0.4])
    second = fit_isotonic([2, 3, 2, 1], [0.4, 0.9, 0.8, 0.2])

    assert first == second
    assert first["version"] == "isotonic_piecewise_linear_v1"
    assert first["x"] == [1.0, 2.0, 3.0]
    assert first["y"] == sorted(first["y"])
    assert first["y"] == pytest.approx([0.2, 0.6, 0.9])


def test_prediction_clamps_and_interpolates_between_knots():
    model = fit_isotonic([0, 1, 2], [0.0, 0.5, 1.0])

    assert predict_isotonic(model, -10) == 0.0
    assert predict_isotonic(model, 0.5) == pytest.approx(0.25)
    assert predict_isotonic(model, 10) == 1.0


def test_constant_input_has_one_stable_knot():
    model = fit_isotonic([4, 4, 4], [0.2, 0.5, 0.8])

    assert model["x"] == [4.0]
    assert model["y"] == pytest.approx([0.5])
    assert predict_isotonic(model, 99) == pytest.approx(0.5)


def test_fit_rejects_bad_or_nonfinite_inputs():
    with pytest.raises(CalibrationError):
        fit_isotonic([], [])
    with pytest.raises(CalibrationError):
        fit_isotonic([1], [1, 2])
    with pytest.raises(CalibrationError):
        fit_isotonic([1, math.nan], [0, 1])
    with pytest.raises(CalibrationError):
        fit_isotonic([1, 2], [0, 1], weights=[1, 0])


def _rows(role="pitcher", count=8):
    return [
        {
            "mlbam_id": 1000 + index,
            "role": role,
            "source_fold": 2010 + index % 4,
            "cohort_year": 2010 + index % 4,
            "is_out_of_fold": True,
            "prediction": index / count,
            "target": (index // 2) / (count / 2),
        }
        for index in range(count)
    ]


def test_role_calibrator_requires_oof_unique_prior_rows_and_source_folds():
    rows = _rows()
    original = copy.deepcopy(rows)

    model = build_role_calibrator(
        rows,
        role="pitcher",
        prediction_field="prediction",
        target_field="target",
        before_cohort=2020,
        min_rows=8,
        min_source_folds=4,
    )

    assert rows == original
    assert model["role"] == "pitcher"
    assert model["row_count"] == 8
    assert model["source_folds"] == [2010, 2011, 2012, 2013]
    assert len(model["sha256"]) == 64

    for mutation, message in (
        ({"is_out_of_fold": False}, "out-of-fold"),
        ({"cohort_year": 2020}, "future"),
    ):
        bad = copy.deepcopy(rows)
        bad[0].update(mutation)
        with pytest.raises(CalibrationError, match=message):
            build_role_calibrator(
                bad,
                role="pitcher",
                prediction_field="prediction",
                target_field="target",
                before_cohort=2020,
                min_rows=8,
                min_source_folds=4,
            )

    duplicate = copy.deepcopy(rows)
    duplicate[1]["mlbam_id"] = duplicate[0]["mlbam_id"]
    duplicate[1]["role"] = duplicate[0]["role"]
    with pytest.raises(CalibrationError, match="duplicate"):
        build_role_calibrator(
            duplicate,
            role="pitcher",
            prediction_field="prediction",
            target_field="target",
            before_cohort=2020,
            min_rows=8,
            min_source_folds=4,
        )


def test_role_calibrator_never_reads_other_roles():
    rows = _rows("hitter") + _rows("pitcher")
    hitter = build_role_calibrator(
        rows,
        role="hitter",
        prediction_field="prediction",
        target_field="target",
        before_cohort=2020,
        min_rows=8,
        min_source_folds=4,
    )
    pitcher = build_role_calibrator(
        rows,
        role="pitcher",
        prediction_field="prediction",
        target_field="target",
        before_cohort=2020,
        min_rows=8,
        min_source_folds=4,
    )

    assert hitter["calibrator"] == pitcher["calibrator"]


def test_apply_calibrators_adds_audited_fields_without_mutating_raw_scores():
    rows = [
        {
            "mlbam_id": 7,
            "role": "pitcher",
            "expected_outcome_score": 0.5,
            "expected_category_impact_score": 0.25,
        }
    ]
    original = copy.deepcopy(rows)
    outcome = build_role_calibrator(
        _rows(),
        role="pitcher",
        prediction_field="prediction",
        target_field="target",
        before_cohort=2020,
        min_rows=8,
        min_source_folds=4,
    )
    impact_rows = _rows()
    for row in impact_rows:
        row["impact_target"] = row["target"] / 2
    impact = build_role_calibrator(
        impact_rows,
        role="pitcher",
        prediction_field="prediction",
        target_field="impact_target",
        before_cohort=2020,
        min_rows=8,
        min_source_folds=4,
    )

    calibrated = apply_common_target_calibrators(
        rows,
        {"pitcher": {"outcome": outcome, "impact": impact}},
    )

    assert rows == original
    assert calibrated[0]["expected_outcome_score"] == 0.5
    assert calibrated[0]["expected_category_impact_score"] == 0.25
    assert 0 <= calibrated[0]["expected_outcome_score_common_target"] <= 1
    assert 0 <= calibrated[0]["expected_category_impact_score_common_target"] <= 1
    assert len(calibrated[0]["common_target_calibration"]["sha256"]) == 64
