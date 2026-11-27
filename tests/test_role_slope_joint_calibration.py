import copy
import importlib
import math

import numpy as np
import pytest

from prospects.prospect_v2_target import canonical_sha256


def _fit_rows():
    rows = []
    for cohort in (2018, 2019, 2021):
        for role, base_id in (("hitter", 100000), ("pitcher", 200000)):
            for position, (outcome, target) in enumerate(
                (("star", 1.0), ("role", 0.5), ("bust", 0.0)), 1
            ):
                rows.append(
                    {
                        "mlbam_id": base_id + cohort * 10 + position,
                        "role": role,
                        "source_ladder_position": position,
                        "ladder_score": float(4 - position),
                        "outcome": outcome,
                        "target": target,
                        "test_cohort": cohort,
                    }
                )
    return rows


def _source_ladders():
    return (
        [
            {
                "mlbam_id": 9001 + position,
                "role": "hitter",
                "source_ladder_position": position,
                "ladder_score": float(4 - position),
                "rank": 99,
                "final_score": -1.0,
                "label": f"h{position}",
            }
            for position in range(1, 4)
        ],
        [
            {
                "mlbam_id": 8001 + position,
                "role": "pitcher",
                "source_ladder_position": position,
                "ladder_score": float(4 - position),
                "rank": 88,
                "final_score": -2.0,
                "label": f"p{position}",
            }
            for position in range(1, 4)
        ],
    )


def test_role_slope_joint_map_contract_and_scoring():
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    rows = _fit_rows()
    mapping = calibration.fit_role_slope_joint_map(rows)

    assert set(mapping) == {
        "schema",
        "version",
        "design",
        "params",
        "thresholds",
        "role_slopes",
        "pitcher_offset",
        "role_standardization",
        "row_count",
        "row_count_by_role",
        "training_rows_sha256",
        "iterations",
        "log_likelihood",
        "artifact_sha256",
    }
    assert mapping["schema"] == "valucast_prospect_role_slope_joint_ladder_map_v1"
    assert mapping["version"] == "1.0.0"
    assert mapping["design"] == [
        "role_standardized_ladder_score:hitter",
        "role_standardized_ladder_score:pitcher",
        "is_pitcher",
    ]
    assert set(mapping["thresholds"]) == {"bust_role", "role_star"}
    assert set(mapping["role_slopes"]) == {"hitter", "pitcher"}
    assert set(mapping["role_standardization"]) == {"hitter", "pitcher"}
    assert all(set(mapping["role_standardization"][role]) == {"mean", "std"} for role in ("hitter", "pitcher"))
    assert set(mapping["row_count_by_role"]) == {"hitter", "pitcher"}

    ordered_rows = sorted(
        rows,
        key=lambda row: (
            (2018, 2019, 2021).index(row["test_cohort"]),
            ("hitter", "pitcher").index(row["role"]),
            row["source_ladder_position"],
            int(row["mlbam_id"]),
        ),
    )
    assert mapping["training_rows_sha256"] == canonical_sha256(ordered_rows)
    assert mapping["row_count"] == len(rows)
    assert mapping["row_count_by_role"] == {"hitter": 9, "pitcher": 9}
    for role in ("hitter", "pitcher"):
        scores = [row["ladder_score"] for row in rows if row["role"] == role]
        assert mapping["role_standardization"][role]["mean"] == pytest.approx(sum(scores) / len(scores))
        assert mapping["role_standardization"][role]["std"] == pytest.approx(math.sqrt(sum((score - sum(scores) / len(scores)) ** 2 for score in scores) / len(scores)))
        assert mapping["role_standardization"][role]["std"] > 0
        assert mapping["role_slopes"][role] > 0
    assert len(mapping["params"]) == 5
    assert all(math.isfinite(value) for value in mapping["params"])
    assert mapping["thresholds"]["bust_role"] == mapping["params"][0]
    assert mapping["thresholds"]["role_star"] == pytest.approx(mapping["params"][0] + math.exp(mapping["params"][1]))
    assert mapping["role_slopes"] == {"hitter": mapping["params"][2], "pitcher": mapping["params"][3]}
    assert mapping["pitcher_offset"] == mapping["params"][4]
    assert math.isfinite(mapping["iterations"])
    assert math.isfinite(mapping["log_likelihood"])
    assert mapping["artifact_sha256"] == canonical_sha256({key: value for key, value in mapping.items() if key != "artifact_sha256"})
    assert calibration.fit_role_slope_joint_map(copy.deepcopy(rows)) == mapping

    hitters, pitchers = _source_ladders()
    original_hitters, original_pitchers = copy.deepcopy(hitters), copy.deepcopy(pitchers)
    scored = calibration.score_role_slope_joint_ladders(hitters, pitchers, mapping)

    assert hitters == original_hitters
    assert pitchers == original_pitchers
    assert [row["rank"] for row in scored] == list(range(1, len(scored) + 1))
    assert scored == sorted(scored, key=lambda row: (-row["calibrated_expected_tier"], row["source_ladder_position"], int(row["mlbam_id"])))
    for source, result in zip(
        sorted([*hitters, *pitchers], key=lambda row: (-next(item["calibrated_expected_tier"] for item in scored if item["mlbam_id"] == row["mlbam_id"]), row["source_ladder_position"], int(row["mlbam_id"]))),
        scored,
    ):
        assert result["mlbam_id"] == source["mlbam_id"]
        assert result["final_score"] == result["calibrated_expected_tier"]
        assert result["calibrator_version"] == mapping["version"]
        assert result["calibrator_sha256"] == mapping["artifact_sha256"]
        assert set(result["tier_probabilities"]) == {"bust", "role", "star"}
        assert all(0.0 <= value <= 1.0 and math.isfinite(value) for value in result["tier_probabilities"].values())
        assert sum(result["tier_probabilities"].values()) == pytest.approx(1.0)
        assert math.isfinite(result["calibrated_expected_tier"])
    for role in ("hitter", "pitcher"):
        role_rows = [row for row in scored if row["role"] == role]
        assert [row["source_ladder_position"] for row in role_rows] == [1, 2, 3]
        assert sum(
            left["calibrated_expected_tier"] < right["calibrated_expected_tier"]
            for left, right in zip(role_rows, role_rows[1:])
        ) == 0

    malformed = copy.deepcopy(mapping)
    malformed["role_slopes"]["hitter"] = malformed["role_slopes"]["hitter"] + 1.0
    malformed["artifact_sha256"] = canonical_sha256({key: value for key, value in malformed.items() if key != "artifact_sha256"})
    with pytest.raises(ValueError, match="invalid role-slope joint map"):
        calibration.score_role_slope_joint_ladders(hitters, pitchers, malformed)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda rows: rows[0].pop("target"),
        lambda rows: rows[0].__setitem__("unexpected", True),
        lambda rows: rows.__setitem__(slice(None), [row for row in rows if row["role"] == "hitter"]),
        lambda rows: [
            row.update({"outcome": "role", "target": 0.5})
            for row in rows
            if row["outcome"] == "star"
        ],
        lambda rows: rows[1].__setitem__("mlbam_id", rows[0]["mlbam_id"]),
        lambda rows: rows[0].__setitem__("ladder_score", float("nan")),
        lambda rows: [row.__setitem__("ladder_score", 0.0) for row in rows if row["role"] == "hitter"],
    ],
)
def test_fit_rejects_registered_input_contract_violations(mutate):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    rows = _fit_rows()
    mutate(rows)

    with pytest.raises(ValueError):
        calibration.fit_role_slope_joint_map(rows)


def test_fit_uses_registered_sort_and_exact_role_design(monkeypatch):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    rows = _fit_rows()
    first, second = rows[0], rows[1]
    first["source_ladder_position"] = second["source_ladder_position"] = 1
    first["mlbam_id"], second["mlbam_id"] = 999999, 1
    captured = {}

    def fit(design, outcomes):
        captured["design"] = design.tolist()
        captured["outcomes"] = outcomes.tolist()
        return {
            "params": np.asarray([-1.0, 0.5, 1.0, 1.0, 0.0]),
            "iterations": 3,
            "log_likelihood": -2.0,
        }

    monkeypatch.setattr(calibration, "_fit_ordered_logit", fit)
    mapping = calibration.fit_role_slope_joint_map(list(reversed(rows)))
    ordered = sorted(
        rows,
        key=lambda row: (
            (2018, 2019, 2021).index(row["test_cohort"]),
            ("hitter", "pitcher").index(row["role"]),
            row["source_ladder_position"],
            row["mlbam_id"],
        ),
    )

    assert mapping["training_rows_sha256"] == canonical_sha256(ordered)
    assert captured["outcomes"] == [
        {"bust": 0, "role": 1, "star": 2}[row["outcome"]]
        for row in ordered
    ]
    for row, design in zip(ordered, captured["design"]):
        scores = [item["ladder_score"] for item in ordered if item["role"] == row["role"]]
        z = (row["ladder_score"] - np.mean(scores)) / np.std(scores, ddof=0)
        assert design == pytest.approx([z, 0.0, 0.0] if row["role"] == "hitter" else [0.0, z, 1.0])


@pytest.mark.parametrize("cohorts", [(2018, 2019), (2018, 2021), (2019, 2021)])
def test_fit_accepts_each_two_fold_subset_deterministically(cohorts):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    rows = [row for row in _fit_rows() if row["test_cohort"] in cohorts]

    mapping = calibration.fit_role_slope_joint_map(rows)

    assert mapping == calibration.fit_role_slope_joint_map(list(reversed(rows)))
    assert mapping["row_count"] == 12
    assert mapping["training_rows_sha256"] == canonical_sha256(
        sorted(
            rows,
            key=lambda row: (
                (2018, 2019, 2021).index(row["test_cohort"]),
                ("hitter", "pitcher").index(row["role"]),
                row["source_ladder_position"],
                row["mlbam_id"],
            ),
        )
    )


@pytest.mark.parametrize(
    "cohorts, expected_count",
    [((2018,), 6), ((2019,), 6), ((2021,), 6), ((2018, 2019, 2021), 18)],
)
def test_fit_accepts_one_or_three_registered_folds(cohorts, expected_count):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    rows = [row for row in _fit_rows() if row["test_cohort"] in cohorts]

    assert calibration.fit_role_slope_joint_map(rows)["row_count"] == expected_count


def test_fit_rejects_unregistered_cohort():
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    rows = _fit_rows()
    rows[0]["test_cohort"] = 2020

    with pytest.raises(ValueError, match="invalid role-slope joint fitting row"):
        calibration.fit_role_slope_joint_map(rows)


def test_fit_rejects_negative_optimizer_slopes(monkeypatch):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    monkeypatch.setattr(
        calibration,
        "_fit_ordered_logit",
        lambda *_args: {
            "params": np.asarray([-1.0, 0.5, -0.1, 1.0, 0.0]),
            "iterations": 1,
            "log_likelihood": -1.0,
        },
    )

    with pytest.raises(ValueError, match="slopes must be positive"):
        calibration.fit_role_slope_joint_map(_fit_rows())


def test_fit_translates_optimizer_runtime_failure_to_value_error(monkeypatch):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    monkeypatch.setattr(
        calibration,
        "_fit_ordered_logit",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("optimizer failed")),
    )

    with pytest.raises(ValueError, match="optimizer failed"):
        calibration.fit_role_slope_joint_map(_fit_rows())


def _reseal(mapping):
    mapping["artifact_sha256"] = canonical_sha256(
        {key: value for key, value in mapping.items() if key != "artifact_sha256"}
    )
    return mapping


@pytest.mark.parametrize(
    "mutate",
    [
        lambda mapping: mapping["thresholds"].__setitem__("bust_role", False),
        lambda mapping: mapping["thresholds"].__setitem__("role_star", True),
        lambda mapping: mapping.__setitem__("pitcher_offset", False),
    ],
)
def test_score_rejects_boolean_thresholds_and_offset(mutate):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    mapping = calibration.fit_role_slope_joint_map(_fit_rows())
    mapping["params"] = [0.0, 0.0, 1.0, 1.0, 0.0]
    mapping["thresholds"] = {"bust_role": 0.0, "role_star": 1.0}
    mapping["role_slopes"] = {"hitter": 1.0, "pitcher": 1.0}
    mapping["pitcher_offset"] = 0.0
    mutate(mapping)
    _reseal(mapping)

    with pytest.raises(ValueError, match="invalid role-slope joint map"):
        calibration.score_role_slope_joint_ladders([], [], mapping)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda mapping: mapping.__setitem__("extra", True),
        lambda mapping: mapping.pop("version"),
        lambda mapping: mapping["thresholds"].__setitem__("extra", 1.0),
        lambda mapping: mapping["thresholds"].__setitem__("role_star", 0.0),
        lambda mapping: mapping["role_slopes"].__setitem__("extra", 1.0),
        lambda mapping: mapping["role_slopes"].__setitem__("hitter", 0.0),
        lambda mapping: mapping.__setitem__("pitcher_offset", 1.0),
        lambda mapping: mapping["role_standardization"].pop("hitter"),
        lambda mapping: mapping["role_standardization"]["hitter"].__setitem__("std", 0.0),
        lambda mapping: mapping["role_standardization"]["pitcher"].__setitem__("mean", float("nan")),
        lambda mapping: mapping["row_count_by_role"].__setitem__("hitter", "9"),
        lambda mapping: mapping["row_count_by_role"].__setitem__("extra", 1),
        lambda mapping: mapping["params"].__setitem__(1, 1000.0),
        lambda mapping: mapping["params"].__setitem__(0, float("nan")),
    ],
)
def test_score_rejects_resealed_cross_field_and_type_tampering(mutate):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    mapping = _reseal(copy.deepcopy(calibration.fit_role_slope_joint_map(_fit_rows())))
    mutate(mapping)
    _reseal(mapping)

    with pytest.raises(ValueError, match="invalid role-slope joint map"):
        calibration.score_role_slope_joint_ladders([], [], mapping)


def test_score_rejects_overflowed_log_gap_with_none_threshold_for_empty_and_nonempty_ladders():
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    mapping = calibration.fit_role_slope_joint_map(_fit_rows())
    mapping["params"][1] = 1000.0
    mapping["thresholds"]["role_star"] = None
    _reseal(mapping)

    for hitters in ([], _source_ladders()[0][:1]):
        with pytest.raises(ValueError, match="invalid role-slope joint map"):
            calibration.score_role_slope_joint_ladders(hitters, [], mapping)


@pytest.mark.parametrize("probability", [[float("nan"), 0.0, 0.0], [0.0, 0.0, 0.0]])
def test_score_rejects_source_inversions_and_invalid_probabilities(monkeypatch, probability):
    calibration = importlib.import_module("prospects.role_slope_joint_calibration")
    mapping = calibration.fit_role_slope_joint_map(_fit_rows())
    inverted = [
        {"mlbam_id": 1, "role": "hitter", "source_ladder_position": 1, "ladder_score": 1.0},
        {"mlbam_id": 2, "role": "hitter", "source_ladder_position": 2, "ladder_score": 3.0},
    ]

    with pytest.raises(ValueError, match="inversion"):
        calibration.score_role_slope_joint_ladders(inverted, [], mapping)

    monkeypatch.setattr(
        calibration,
        "_ordered_probabilities",
        lambda *_args: np.asarray([probability]),
    )
    with pytest.raises(ValueError, match="probabilities"):
        calibration.score_role_slope_joint_ladders(_source_ladders()[0][:1], [], mapping)
