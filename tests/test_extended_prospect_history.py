import copy

import pytest

from prospects.extended_history import (
    MissingOutcomeError,
    SeasonCanonicalizationError,
    build_labeled_rows,
    canonicalize_mlb_seasons,
    draft_for_cohort,
    outcome_label,
    parse_innings,
    qualifies,
    select_earliest_candidates,
    validate_identity_parity,
)


def _hitter(mlbam_id, *, year=2014, level="A", age=20, pa=300, role="hitter"):
    return {
        "cohort_year": year,
        "mlbam_id": mlbam_id,
        "name": f"Hitter {mlbam_id}",
        "role": role,
        "level": level,
        "sport_id": {"AAA": 11, "AA": 12, "A+": 13, "A": 14}[level],
        "age": age,
        "plate_appearances": pa,
    }


def _pitcher(mlbam_id, *, year=2014, level="A", age=20, ip=60):
    return {
        "cohort_year": year,
        "mlbam_id": mlbam_id,
        "name": f"Pitcher {mlbam_id}",
        "role": "pitcher",
        "level": level,
        "sport_id": {"AAA": 11, "AA": 12, "A+": 13, "A": 14}[level],
        "age": age,
        "innings_pitched": ip,
    }


def test_qualification_is_frozen_to_age_level_and_role_sample():
    assert qualifies(_hitter(1), "hitter") is True
    assert qualifies(_hitter(2, pa=249), "hitter") is False
    assert qualifies(_hitter(3, age=25), "hitter") is False
    assert qualifies(_pitcher(4, ip=50), "pitcher") is True
    assert qualifies(_pitcher(5, ip=49.2), "pitcher") is False
    assert qualifies({**_hitter(6), "level": "R"}, "hitter") is False


def test_selection_uses_earliest_season_then_highest_level_and_preserves_two_way_roles():
    rows = [
        _hitter(1, year=2010, level="A", pa=500),
        _hitter(1, year=2010, level="AA", pa=300),
        _hitter(1, year=2011, level="AAA", pa=600),
        _pitcher(1, year=2010, level="A+", ip=80),
        _hitter(2, year=2010, level="A", pa=301),
        _hitter(2, year=2010, level="A", pa=450),
    ]

    selected = select_earliest_candidates(rows)

    assert [(row["mlbam_id"], row["role"]) for row in selected] == [
        (1, "hitter"),
        (1, "pitcher"),
        (2, "hitter"),
    ]
    assert selected[0]["cohort_year"] == 2010
    assert selected[0]["level"] == "AA"
    assert selected[2]["plate_appearances"] == 450


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("0", 0.0),
        ("55.0", 55.0),
        ("55.1", 55 + 1 / 3),
        ("55.2", 55 + 2 / 3),
        (3.333, 3 + 1 / 3),
        (3.667, 3 + 2 / 3),
    ],
)
def test_parse_innings_uses_baseball_out_not_decimal_notation(text, expected):
    assert parse_innings(text) == pytest.approx(expected)


def test_outcome_labels_are_forward_only_and_stop_at_four_year_horizon():
    seasons = [
        {"year": 2014, "pa": 700, "ops": 1.100},
        {"year": 2015, "pa": 200, "ops": 0.700},
        {"year": 2019, "pa": 650, "ops": 0.950},
    ]
    assert outcome_label(seasons, "hitter", 2014) == "role"
    assert outcome_label(seasons, "hitter", 2014, horizon_years=5) == "star"


def test_outcome_label_thresholds_match_frozen_contract():
    assert outcome_label([{"year": 2015, "pa": 149, "ops": 1.0}], "hitter", 2014) == "bust"
    assert outcome_label([{"year": 2015, "pa": 449, "ops": 0.900}], "hitter", 2014) == "role"
    assert outcome_label([{"year": 2015, "pa": 450, "ops": 0.800}], "hitter", 2014) == "star"
    assert outcome_label([{"year": 2015, "ip": 49.2, "era": 1.00}], "pitcher", 2014) == "bust"
    assert outcome_label([{"year": 2015, "ip": 119.2, "era": 3.00}], "pitcher", 2014) == "role"
    assert outcome_label([{"year": 2015, "ip": 120, "era": 3.75}], "pitcher", 2014) == "star"


def test_zero_era_is_a_valid_pitcher_star_rate():
    assert outcome_label(
        [{"year": 2015, "ip": 120, "era": 0.0}], "pitcher", 2014
    ) == "star"


def test_shorter_peak_season_cannot_mask_a_separate_star_qualifying_season():
    hitter_seasons = [
        {"year": 2015, "pa": 350, "ops": 0.950},
        {"year": 2016, "pa": 500, "ops": 0.810},
    ]
    pitcher_seasons = [
        {"year": 2015, "ip": 90, "era": 2.00},
        {"year": 2016, "ip": 140, "era": 3.50},
    ]

    assert outcome_label(hitter_seasons, "hitter", 2014) == "star"
    assert outcome_label(pitcher_seasons, "pitcher", 2014) == "star"


def test_mlb_seasons_choose_the_full_year_aggregate_and_handle_baseball_innings():
    hitter = canonicalize_mlb_seasons(
        [
            {"year": 2019, "pa": 100, "r": 10},
            {"year": 2019, "pa": 150, "r": 20},
            {"year": 2019, "pa": 250, "r": 31},
        ],
        "hitter",
    )
    pitcher = canonicalize_mlb_seasons(
        [
            {"year": 2016, "ip": 3.2, "era": 9.00},
            {"year": 2016, "ip": 27.2, "era": 3.00},
            {"year": 2016, "ip": 31.1, "era": 3.50},
        ],
        "pitcher",
    )

    assert hitter == [{"year": 2019, "pa": 250, "r": 31}]
    assert pitcher == [{"year": 2016, "ip": 31.1, "era": 3.50}]


def test_mlb_season_canonicalization_uses_last_aggregate_tie_and_fails_without_total():
    tied = canonicalize_mlb_seasons(
        [
            {"year": 2022, "pa": 0, "r": 0},
            {"year": 2022, "pa": 44, "r": 1},
            {"year": 2022, "pa": 44, "r": 2},
        ],
        "hitter",
    )
    assert tied[0]["r"] == 2

    with pytest.raises(SeasonCanonicalizationError, match="no full-season aggregate"):
        canonicalize_mlb_seasons(
            [
                {"year": 2019, "pa": 100},
                {"year": 2019, "pa": 150},
            ],
            "hitter",
        )


def test_future_draft_facts_are_masked_without_mutating_source():
    fact = {
        "draft_record_known": True,
        "rule4_drafted": True,
        "draft_year": 2012,
        "draft_pick_number": 10,
        "draft_round": "1",
        "signing_bonus": 4_000_000,
        "pick_value": 4_500_000,
        "school_type": "college",
    }
    original = copy.deepcopy(fact)

    masked = draft_for_cohort(fact, 2011)

    assert fact == original
    assert masked["draft_record_known"] is True
    assert masked["rule4_drafted"] is False
    assert masked["draft_year"] is None
    assert masked["pick_value"] is None
    assert draft_for_cohort(fact, 2012) == fact


def test_labeled_rows_fail_closed_when_an_outcome_request_is_missing():
    candidates = [_hitter(1)]
    with pytest.raises(MissingOutcomeError, match="1_hitter"):
        build_labeled_rows(candidates, {}, {})

    rows = build_labeled_rows(candidates, {"1_hitter": []}, {})
    assert rows[0]["outcome"] == "bust"


def test_identity_parity_reports_exact_extra_and_missing_sets():
    candidates = [_hitter(1), _pitcher(2)]
    committed = [_hitter(1), _pitcher(3)]

    report = validate_identity_parity(candidates, committed, cohort_year=2014)

    assert report["status"] == "mismatch"
    assert report["candidate_count"] == 2
    assert report["committed_count"] == 2
    assert report["extra"] == [{"mlbam_id": 2, "role": "pitcher"}]
    assert report["missing"] == [{"mlbam_id": 3, "role": "pitcher"}]
