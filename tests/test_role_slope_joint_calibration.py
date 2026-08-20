import copy
import importlib
import math

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
