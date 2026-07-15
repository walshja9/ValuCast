"""Tests for the observe-only prospect cross-role validation shadow."""

from __future__ import annotations

import json

from prospects.cross_role_shadow import (
    build_cross_role_shadow,
    run_cross_role_shadow,
    validate_cross_role_shadow,
)


def _rank_backtest(value=0.81):
    return {
        "variants": {
            "C0": {
                "folds": [
                    {"test_cohort": 2018, "c_cross_report_only": 0.84},
                    {"test_cohort": 2019, "c_cross_report_only": 0.81},
                    {"test_cohort": 2021, "c_cross_report_only": 0.77},
                ],
                "weighted": {"c_cross_report_only": value},
            }
        }
    }


def _power(power=0.015):
    return {
        "e2_cross_role": {
            "0.005": {"power": 0.0},
            "0.03": {"power": power},
        }
    }


def _row(rank, role, mlbam_id, source_count=3, level="AA"):
    sources = {f"source_{index}": rank + index for index in range(source_count)}
    return {
        "rank": rank,
        "role": role,
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "level": level,
        "components": {"model_score": 1000.0 - rank},
        "context_only": {"source_ranks": sources},
    }


def _board(top25_pitchers=10):
    rows = []
    pitcher_id = 100
    hitter_id = 1000
    for rank in range(1, 51):
        is_pitcher = rank <= top25_pitchers or (26 <= rank <= 32)
        if is_pitcher:
            rows.append(
                _row(
                    rank,
                    "pitcher",
                    pitcher_id,
                    source_count=5,
                    level="AAA" if pitcher_id <= 102 else "AA",
                )
            )
            pitcher_id += 1
        else:
            rows.append(_row(rank, "hitter", hitter_id, source_count=5))
            hitter_id += 1
    return {"generated_at": "2026-07-15T12:30:00+00:00", "board": rows}


def _aaa(covered_ids):
    return {
        "generated_at": "2026-07-15T12:20:00+00:00",
        "pitchers": {
            str(mlbam_id): {
                "n_pitches": 500,
                "overall": {
                    "whiff_pct": 30.0 + index,
                    "csw_pct": 28.0,
                    "zone_pct": 45.0,
                    "chase_pct": 31.0,
                    "gb_pct": 44.0,
                },
                "pitch_types": {
                    "FF": {
                        "n": 250,
                        "usage_pct": 50.0,
                        "velo": 95.0,
                        "ivb": 16.0,
                        "hb": -7.0,
                        "spin": 2300,
                        "ext": 6.2,
                    }
                },
            }
            for index, mlbam_id in enumerate(covered_ids)
        },
    }


def test_shadow_separates_absolute_floor_power_shape_and_aaa_coverage():
    payload = build_cross_role_shadow(
        _rank_backtest(),
        _power(),
        _board(),
        _aaa({100, 101, 102}),
        generated_at="2026-07-15T13:00:00+00:00",
    )

    assert payload["status"] == "collecting"
    assert payload["checks"]["historical_absolute_concordance"] == {
        "status": "pass",
        "gate_name": "absolute_cross_role_adapter_floor",
        "metric": "c_cross_report_only",
        "value": 0.81,
        "floor": 0.6,
        "fold_count": 3,
        "folds": [
            {"test_cohort": 2018, "value": 0.84},
            {"test_cohort": 2019, "value": 0.81},
            {"test_cohort": 2021, "value": 0.77},
        ],
        "evidence_class": "retrospective_absolute_floor",
        "confirms_current_change": False,
    }
    assert payload["checks"]["cross_role_change_power"]["max_power"] == 0.015
    assert payload["checks"]["cross_role_change_power"]["status"] == "fail"
    assert payload["checks"]["current_board_shape"]["top25_pitcher_count"] == 10
    assert (
        payload["checks"]["current_board_shape"][
            "model_component_top25_pitcher_count"
        ]
        == 10
    )
    assert payload["checks"]["current_board_shape"]["top50_pitcher_rate"] == 0.34
    assert payload["checks"]["aaa_measured_coverage"]["coverage_rate"] == 1.0
    assert (
        payload["checks"]["aaa_measured_coverage"]["eligible_top25_pitcher_count"] == 3
    )
    assert payload["checks"]["aaa_measured_coverage"]["top25_pitcher_count"] == 10
    assert (
        payload["checks"]["aaa_measured_coverage"]["top25_population_coverage_rate"]
        == 0.3
    )
    assert payload["checks"]["aaa_measured_coverage"]["status"] == "pass"
    assert (
        payload["checks"]["aaa_measured_coverage"][
            "minimum_eligible_top25_pitcher_count"
        ]
        == 3
    )
    assert payload["checks"]["aaa_measured_coverage"]["eligible_sample_ready"] is True
    assert payload["promotion"]["score_changes_authorized"] is False
    assert payload["promotion"]["failed_decay_flag_changed"] is False
    assert payload["source_policy"]["external_rankings_used_as_outcomes"] is False


def test_shadow_is_review_ready_only_when_every_check_passes():
    board = _board(top25_pitchers=7)
    top25_pitcher_ids = {
        row["mlbam_id"] for row in board["board"][:25] if row["role"] == "pitcher"
    }
    payload = build_cross_role_shadow(
        _rank_backtest(0.7),
        _power(0.75),
        board,
        _aaa(top25_pitcher_ids),
    )

    assert payload["status"] == "review_ready"
    assert all(check["status"] == "pass" for check in payload["checks"].values())
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["score_changes_authorized"] is False


def test_shadow_blocks_malformed_required_input():
    payload = build_cross_role_shadow({}, _power(), _board(), _aaa(set()))
    assert payload["status"] == "blocked"
    assert (
        "rank_backtest.variants.C0.weighted.c_cross_report_only"
        in payload["validation"]["problems"]
    )

    problems = validate_cross_role_shadow(payload)
    assert problems == []


def test_shadow_blocks_missing_pitcher_level_used_for_aaa_eligibility():
    board = _board()
    board["board"][0].pop("level")

    payload = build_cross_role_shadow(_rank_backtest(), _power(), board, _aaa(set()))

    assert payload["status"] == "blocked"
    assert "rank_artifact.board.pitcher_level" in payload["validation"]["problems"]


def test_aaa_coverage_requires_complete_measured_pitch_data():
    aaa = _aaa({100, 101, 102})
    aaa["pitchers"]["100"] = {"n_pitches": 0, "overall": {}, "pitch_types": {}}
    payload = build_cross_role_shadow(_rank_backtest(), _power(), _board(), aaa)

    assert (
        payload["checks"]["aaa_measured_coverage"]["covered_top25_pitcher_count"] == 2
    )
    assert payload["checks"]["aaa_measured_coverage"]["coverage_rate"] == 0.666667


def test_aaa_coverage_cannot_pass_with_one_of_one_eligible_pitchers():
    board = _board()
    for row in board["board"]:
        if row["role"] == "pitcher":
            row["level"] = "AAA" if row["mlbam_id"] == 100 else "AA"

    payload = build_cross_role_shadow(
        _rank_backtest(), _power(), board, _aaa({100})
    )

    coverage = payload["checks"]["aaa_measured_coverage"]
    assert coverage["eligible_top25_pitcher_count"] == 1
    assert coverage["covered_top25_pitcher_count"] == 1
    assert coverage["coverage_rate"] == 1.0
    assert coverage["minimum_eligible_top25_pitcher_count"] == 3
    assert coverage["eligible_sample_ready"] is False
    assert coverage["status"] == "fail"


def test_board_shape_computes_model_component_top25_role_mix():
    board = _board()
    pitchers = [row for row in board["board"] if row["role"] == "pitcher"][:13]
    hitters = [row for row in board["board"] if row["role"] == "hitter"][:12]
    selected = pitchers + hitters
    for row in board["board"]:
        row["components"]["model_score"] = -float(row["rank"])
    for index, row in enumerate(selected):
        row["components"]["model_score"] = 1000.0 - index

    payload = build_cross_role_shadow(
        _rank_backtest(), _power(), board, _aaa({100, 101, 102})
    )

    shape = payload["checks"]["current_board_shape"]
    assert shape["top25_pitcher_count"] == 10
    assert shape["model_component_field"] == "components.model_score"
    assert shape["model_component_eligible_board_count"] == 50
    assert shape["model_component_top25_evaluated_count"] == 25
    assert shape["model_component_top25_pitcher_count"] == 13
    assert shape["model_component_top25_hitter_count"] == 12


def test_shadow_blocks_invalid_power_effect_key_instead_of_crashing():
    payload = build_cross_role_shadow(
        _rank_backtest(),
        {"e2_cross_role": {"not-an-effect": {"power": 0.8}}},
        _board(),
        _aaa(set()),
    )

    assert payload["status"] == "blocked"
    assert "power_check.e2_cross_role.effect_keys" in payload["validation"]["problems"]


def test_runner_writes_valid_artifact(tmp_path):
    inputs = {
        "rank_backtest_path": tmp_path / "rank-backtest.json",
        "power_path": tmp_path / "power.json",
        "rank_path": tmp_path / "rank.json",
        "aaa_path": tmp_path / "aaa.json",
    }
    payloads = [_rank_backtest(), _power(), _board(), _aaa({100, 101, 102})]
    for path, payload in zip(inputs.values(), payloads):
        path.write_text(json.dumps(payload), encoding="utf-8")
    artifact_path = tmp_path / "cross-role.json"

    result = run_cross_role_shadow(
        **inputs,
        artifact_path=artifact_path,
        generated_at="2026-07-15T13:00:00+00:00",
    )

    persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result["status"] == "collecting"
    assert persisted["artifact"] == "valucast_prospect_cross_role_shadow"
    assert validate_cross_role_shadow(persisted) == []
