import json
from pathlib import Path

from prospects.challenger_eval import (
    FORBIDDEN_SEEDS,
    HITTER_RATE_FIELDS,
    REGISTERED_SEED,
    fold_local_contract,
    normalize_rows,
    prepare_fold,
)


def _row(player, *, year=2018, role="hitter", level="AA", iso=.100):
    return {
        "mlbam_id": player,
        "cohort_year": year,
        "role": role,
        "level": level,
        "iso": iso,
        "k_pct": 20.0,
        "bb_pct": 8.0,
        "ops": .700,
        "avg": .250,
        "obp": .320,
        "slg": .380,
        "babip": .300,
    }


def test_leave_one_out_quantile_is_tie_aware_and_non_affine():
    rows = [
        _row(1, iso=.100),
        _row(2, iso=.200),
        _row(3, iso=.200),
        _row(4, iso=.900),
    ]
    normalized, diagnostics = normalize_rows(
        rows, same_level_min=2, role_season_min=3
    )
    by_id = {row["mlbam_id"]: row for row in normalized}
    assert by_id[2]["iso"] == by_id[3]["iso"]
    assert [by_id[i]["iso"] for i in (1, 2, 4)] != [.1, .2, .9]
    assert diagnostics["unavailable"] == 0


def test_sparse_level_backs_off_and_sparse_role_season_is_unavailable():
    rows = [
        _row(i, level="AA" if i == 1 else "AAA", iso=i / 10)
        for i in range(1, 6)
    ]
    normalized, diagnostics = normalize_rows(
        rows, same_level_min=2, role_season_min=3
    )
    assert diagnostics["backoff_rows"] >= 1
    _, blocked = normalize_rows(rows[:2], same_level_min=2, role_season_min=3)
    assert blocked["unavailable"] == 2


def test_blank_level_never_forms_a_same_level_reference_cell():
    for level in ("", None):
        normalized, diagnostics = normalize_rows(
            [_row(player, level=level) for player in range(1, 27)],
            same_level_min=25,
            role_season_min=25,
        )
        assert len(normalized) == 26
        assert diagnostics["same_level_rows"] == 0
        assert diagnostics["backoff_rows"] == 26
        assert diagnostics["unavailable"] == 0


def test_current_rows_use_sample_season_and_missing_season_fails_closed():
    rows = []
    for player in range(1, 5):
        row = _row(player)
        row.pop("cohort_year")
        row["sample_season"] = 2026
        rows.append(row)
    missing_season = _row(5)
    missing_season.pop("cohort_year")
    rows.append(missing_season)
    normalized, diagnostics = normalize_rows(
        rows, same_level_min=3, role_season_min=3
    )
    assert {row["mlbam_id"] for row in normalized} == {1, 2, 3, 4}
    assert diagnostics["unavailable"] == 1
    assert (
        diagnostics["reference_years"]["2026"]["hitter"]["exercised_coverage"]
        == 1.0
    )
    assert diagnostics["reference_years"]["unknown"]["hitter"]["unavailable"] == 1


def test_outcome_mutation_cannot_change_normalized_inputs():
    rows = [_row(i, iso=i / 100) | {"outcome": "bust"} for i in range(1, 30)]
    first = normalize_rows(rows, same_level_min=25, role_season_min=250)
    mutated = [dict(row, outcome="star") for row in rows]
    second = normalize_rows(mutated, same_level_min=25, role_season_min=250)
    first_rates = [
        tuple(row[field] for field in HITTER_RATE_FIELDS) for row in first[0]
    ]
    second_rates = [
        tuple(row[field] for field in HITTER_RATE_FIELDS) for row in second[0]
    ]
    assert first_rates == second_rates
    assert first[1] == second[1]


def test_test_cohort_seasons_never_enter_fold_local_impact_references():
    contract = {
        "historical": {
            "rows": [
                {"mlbam_id": 1, "role": "hitter", "cohort_year": 2014},
                {"mlbam_id": 2, "role": "hitter", "cohort_year": 2018},
            ]
        },
        "historical_mlb_seasons": {
            "1_hitter": [
                {"year": 2015, "pa": 500, "hr": 10},
                {"year": 2020, "pa": 500, "hr": 40},
            ],
            "2_hitter": [{"year": 2019, "pa": 500, "hr": 99}],
        },
    }
    fold = fold_local_contract(contract, test_year=2018)
    assert set(fold["historical_mlb_seasons"]) == {"1_hitter"}
    assert [
        season["year"] for season in fold["historical_mlb_seasons"]["1_hitter"]
    ] == [2015]


def test_invalid_training_row_cannot_bypass_final_horizon_clip():
    invalid = _row(1, year=2014) | {"age": 99}
    fold = fold_local_contract(
        {
            "historical": {"rows": [invalid]},
            "historical_mlb_seasons": {
                "1_hitter": [{"year": 2015}, {"year": 2030}],
            },
        },
        test_year=2018,
    )
    assert [
        season["year"] for season in fold["historical_mlb_seasons"]["1_hitter"]
    ] == [2015]


def test_prepare_fold_keeps_exact_available_identities_and_reports_role_coverage():
    rows = [_row(player) for player in range(1, 28)]
    rows[0].pop("iso")
    missing_season = _row(28)
    missing_season.pop("cohort_year")
    rows.append(missing_season)
    prepared = prepare_fold(
        {
            "historical": {"rows": rows},
            "historical_mlb_seasons": {},
        },
        test_year=2018,
    )
    expected = {(2018, player, "hitter") for player in range(2, 28)}
    for name in ("control_contract", "candidate_contract"):
        assert {
            (row["cohort_year"], row["mlbam_id"], row["role"])
            for row in prepared[name]["historical"]["rows"]
        } == expected
    assert {
        tuple(identity) for identity in prepared["common_identities"]["hitter"]
    } == expected
    assert prepared["common_identities"]["pitcher"] == []
    assert prepared["coverage"]["hitter"]["rows"] == 27
    assert prepared["coverage"]["hitter"]["unavailable"] == 1
    assert prepared["coverage"]["hitter"]["exercised_coverage"] == 26 / 27


def test_registered_seed_is_fresh_and_forbidden_seeds_stay_forbidden():
    assert REGISTERED_SEED == 33021
    assert REGISTERED_SEED not in FORBIDDEN_SEEDS
    assert FORBIDDEN_SEEDS == {28013, 28017, 29001, 31013, 31017}


def test_registered_fold_keys_are_not_inferred_from_observed_years():
    observed = (2000, 2014, 2015, 2016, 2017, 2018, 2019, 2021)
    _, diagnostics = normalize_rows(
        [_row(player, year=year) for player, year in enumerate(observed, 1)],
        same_level_min=1,
        role_season_min=1,
    )
    assert tuple(diagnostics["folds"]) == (
        "2016",
        "2017",
        "2018",
        "2019",
        "2021",
        "2022",
    )
    assert set(diagnostics["reference_years"]) == {str(year) for year in observed}
    assert diagnostics["folds"]["2022"]["hitter"]["rows"] == 0
    assert diagnostics["folds"]["2022"]["hitter"]["exercised_coverage"] == 0.0


def test_real_input_exercises_challenger_without_outcome_values():
    payload = json.loads(
        (Path(__file__).resolve().parents[1] / "data/prospects/prospect_model_inputs.json")
        .read_text(encoding="utf-8")
    )
    rows = [
        {key: value for key, value in row.items() if key != "outcome"}
        for row in payload["historical"]["rows"]
    ]
    _, diagnostics = normalize_rows(rows)
    assert diagnostics["overall"]["rows"] == 6756
    assert diagnostics["overall"]["available"] == 6756
    assert set(diagnostics["reference_years"]) == {
        "2014",
        "2015",
        "2016",
        "2017",
        "2018",
        "2019",
        "2021",
        "2022",
    }
    assert set(diagnostics["folds"]) == {
        "2016",
        "2017",
        "2018",
        "2019",
        "2021",
        "2022",
    }
    for fold in diagnostics["folds"].values():
        for role in ("hitter", "pitcher"):
            assert fold[role]["exercised_coverage"] >= 0.90
            counts = fold[role]["reference_counts"]["role_season"]
            assert (
                336
                <= counts["cell_size"]["minimum"]
                <= counts["cell_size"]["maximum"]
                <= 410
            )
            assert (
                335
                <= counts["other_peers"]["minimum"]
                <= counts["other_peers"]["maximum"]
                <= 409
            )
