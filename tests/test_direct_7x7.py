import copy

import pytest

from prospects.direct_7x7 import (
    DirectValueError,
    build_fold_references,
    direct_7x7_target,
    join_quality_starts,
    top_k_regret,
)


def test_quality_start_join_is_exact_validated_and_non_mutating():
    seasons = {
        "11_pitcher": [
            {"year": 2015, "ip": 120, "gs": 20, "so": 100, "sv": 0, "hld": 0,
             "era": 3.5, "whip": 1.2, "k_bb": 3.0, "l": 8}
        ]
    }
    original = copy.deepcopy(seasons)
    sidecar = {
        "schema": "valucast_stage2_quality_starts",
        "status": "ready",
        "rows": [{"mlbam_id": 11, "season": 2015, "games_started": 20,
                  "quality_starts": 12}],
    }

    joined = join_quality_starts(seasons, sidecar)

    assert seasons == original
    assert joined["11_pitcher"][0]["qs"] == 12
    with pytest.raises(DirectValueError, match="missing QS"):
        join_quality_starts(seasons, {**sidecar, "rows": []})
    invalid = copy.deepcopy(sidecar)
    invalid["rows"][0]["quality_starts"] = 21
    with pytest.raises(DirectValueError, match="exceeds games started"):
        join_quality_starts(seasons, invalid)


def test_quality_start_join_canonicalizes_team_splits_before_attaching_qs():
    seasons = {
        "11_pitcher": [
            {**_pitcher_season(2015), "ip": 40.0, "era": 3.0},
            {**_pitcher_season(2015), "ip": 60.0, "era": 4.0},
            {**_pitcher_season(2015), "ip": 100.0, "era": 3.6},
        ]
    }
    sidecar = {
        "schema": "valucast_stage2_quality_starts",
        "status": "ready",
        "rows": [
            {
                "mlbam_id": 11,
                "season": 2015,
                "games_started": 18,
                "quality_starts": 15,
            }
        ],
    }

    joined = join_quality_starts(seasons, sidecar)

    assert len(joined["11_pitcher"]) == 1
    assert joined["11_pitcher"][0]["ip"] == 100.0
    assert joined["11_pitcher"][0]["qs"] == 15


def _hitter_season(year, scale=1.0):
    return {
        "year": year,
        "pa": 500,
        "r": 80 * scale,
        "hr": 20 * scale,
        "rbi": 75 * scale,
        "sb": 10 * scale,
        "avg": 0.260 * scale,
        "ops": 0.780 * scale,
        "so": 130 / scale,
    }


def _pitcher_season(year, scale=1.0):
    return {
        "year": year,
        "ip": 150,
        "so": 150 * scale,
        "qs": 15 * scale,
        "sv": 0,
        "hld": 0,
        "era": 4.0 / scale,
        "whip": 1.3 / scale,
        "k_bb": 3.0 * scale,
        "l": 10 / scale,
    }


def test_fold_references_use_only_training_identity_four_year_horizons():
    rows = [
        {"mlbam_id": 1, "role": "hitter", "cohort_year": 2010},
        {"mlbam_id": 2, "role": "pitcher", "cohort_year": 2011},
    ]
    seasons = {
        "1_hitter": [_hitter_season(2010, 9), _hitter_season(2011),
                     _hitter_season(2015, 8)],
        "2_pitcher": [_pitcher_season(2012)],
        "99_hitter": [_hitter_season(2012, 20)],
    }

    refs = build_fold_references(rows, seasons)

    assert refs["hitter"]["hr"] == [20.0]
    assert refs["pitcher"]["qs"] == [15.0]
    assert set(refs["hitter"]) == {"r", "hr", "rbi", "sb", "avg", "ops", "so"}
    assert set(refs["pitcher"]) == {"so", "qs", "sv_hld", "era", "whip", "k_bb", "l"}


def test_fold_references_fail_when_a_qualifying_reference_season_is_incomplete():
    rows = [{"mlbam_id": 1, "role": "hitter", "cohort_year": 2010}]
    seasons = {"1_hitter": [_hitter_season(2011)]}
    seasons["1_hitter"][0].pop("sb")

    with pytest.raises(DirectValueError, match="reference season.*missing.*sb"):
        build_fold_references(rows, seasons)


def test_direct_target_is_best_complete_horizon_season_and_orients_strikeouts():
    training = [
        {"mlbam_id": 1, "role": "hitter", "cohort_year": 2010},
        {"mlbam_id": 2, "role": "hitter", "cohort_year": 2010},
    ]
    seasons = {
        "1_hitter": [_hitter_season(2011, 0.8)],
        "2_hitter": [_hitter_season(2011, 1.2)],
        "3_hitter": [_hitter_season(2015, 1.2), _hitter_season(2020, 5.0)],
    }
    refs = build_fold_references(training, seasons)

    value = direct_7x7_target(
        {"mlbam_id": 3, "role": "hitter", "cohort_year": 2014},
        seasons,
        refs,
    )

    assert 0.75 <= value <= 1.0
    # Lower SO is good, so the strong season remains strong instead of being
    # penalized by raw counting-stat direction.
    assert value > 0.5


def test_direct_target_fails_closed_on_missing_qualifying_category():
    rows = [{"mlbam_id": 1, "role": "hitter", "cohort_year": 2010}]
    seasons = {"1_hitter": [_hitter_season(2011)]}
    refs = build_fold_references(rows, seasons)
    bad = {"2_hitter": [_hitter_season(2012)]}
    bad["2_hitter"][0].pop("ops")

    with pytest.raises(DirectValueError, match="missing canonical categories"):
        direct_7x7_target(
            {"mlbam_id": 2, "role": "hitter", "cohort_year": 2011},
            bad,
            refs,
        )


def test_zero_walk_positive_strikeout_target_has_top_ordered_k_bb_value():
    record = {"mlbam_id": 11, "role": "pitcher", "cohort_year": 2015}
    references = {
        "pitcher": {
            field: [1.0, 2.0]
            for field in ("so", "qs", "sv_hld", "era", "whip", "k_bb", "l")
        }
    }
    zero_walk = _pitcher_season(2016)
    zero_walk.update({"ip": 11, "so": 6, "bb": 0, "k_bb": None})
    explicit_above_max = {**zero_walk, "k_bb": 999.0}

    assert direct_7x7_target(
        record, {"11_pitcher": [zero_walk]}, references
    ) == direct_7x7_target(
        record, {"11_pitcher": [explicit_above_max]}, references
    )


@pytest.mark.parametrize(
    ("mlbam_id", "cohort_year", "season_year"),
    [(607320, 2013, 2016), (670288, 2018, 2022)],
)
def test_registered_zero_walk_target_regressions_are_category_complete(
    mlbam_id, cohort_year, season_year
):
    record = {
        "mlbam_id": mlbam_id,
        "role": "pitcher",
        "cohort_year": cohort_year,
    }
    references = {
        "pitcher": {
            field: [1.0, 2.0]
            for field in ("so", "qs", "sv_hld", "era", "whip", "k_bb", "l")
        }
    }
    season = {
        "year": season_year,
        "ip": 11.0,
        "so": 6.0,
        "bb": 0.0,
        "qs": 0,
        "sv": 0.0,
        "hld": 0.0,
        "era": 1.64,
        "whip": 0.91,
        "k_bb": None,
        "l": 0.0,
    }

    assert direct_7x7_target(
        record, {f"{mlbam_id}_pitcher": [season]}, references
    ) >= 0.0


@pytest.mark.parametrize(
    ("strikeouts", "walks"),
    [(0, 0), (6, 1), (None, 0), (6, None)],
)
def test_missing_k_bb_still_fails_without_positive_strikeout_zero_walk_fact(
    strikeouts, walks
):
    record = {"mlbam_id": 11, "role": "pitcher", "cohort_year": 2015}
    references = {
        "pitcher": {
            field: [1.0]
            for field in ("so", "qs", "sv_hld", "era", "whip", "k_bb", "l")
        }
    }
    season = _pitcher_season(2016)
    season.update({"ip": 11, "so": strikeouts, "bb": walks, "k_bb": None})

    with pytest.raises(DirectValueError, match="missing canonical categories.*k_bb"):
        direct_7x7_target(record, {"11_pitcher": [season]}, references)


def test_zero_walk_missing_k_bb_reference_remains_fail_closed():
    row = {"mlbam_id": 11, "role": "pitcher", "cohort_year": 2015}
    season = _pitcher_season(2016)
    season.update({"ip": 20, "so": 6, "bb": 0, "k_bb": None})

    with pytest.raises(DirectValueError, match="reference season.*missing.*k_bb"):
        build_fold_references([row], {"11_pitcher": [season]})


def test_direct_target_always_uses_all_seven_categories_without_coverage_drops():
    references = {
        "hitter": {
            field: ([0.0] if field == "sb" else [0.0, 10.0])
            for field in ("r", "hr", "rbi", "sb", "avg", "ops", "so")
        },
        "pitcher": {
            field: [0.0]
            for field in ("so", "qs", "sv_hld", "era", "whip", "k_bb", "l")
        },
    }
    seasons = {
        "2_hitter": [
            {
                "year": 2012,
                "pa": 100,
                "r": 0,
                "hr": 0,
                "rbi": 0,
                "sb": 10,
                "avg": 0,
                "ops": 0,
                "so": 0,
            }
        ]
    }

    value = direct_7x7_target(
        {"mlbam_id": 2, "role": "hitter", "cohort_year": 2011},
        seasons,
        references,
    )

    assert value == pytest.approx(4.0 / 7.0)


def test_top_k_regret_matches_oracle_opportunity_cost_and_requires_full_k():
    rows = [
        {"mlbam_id": 1, "role": "hitter", "prediction": 0.9, "target": 0.2},
        {"mlbam_id": 2, "role": "hitter", "prediction": 0.8, "target": 1.0},
        {"mlbam_id": 3, "role": "hitter", "prediction": 0.7, "target": 0.8},
    ]

    result = top_k_regret(rows, prediction_field="prediction", target_field="target", k=2)

    assert result["oracle_mean"] == pytest.approx(0.9)
    assert result["selected_mean"] == pytest.approx(0.6)
    assert result["regret"] == pytest.approx(0.3)
    with pytest.raises(DirectValueError, match="fewer than k"):
        top_k_regret(rows[:1], prediction_field="prediction", target_field="target", k=2)
