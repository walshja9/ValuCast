import copy

import pytest

import prospects.pre2014_fold_scoring as fold_scoring
from prospects.pre2014_fold_scoring import (
    FoldScoringError,
    derive_inner_fold_years,
    direct_7x7_target,
    fold_local_seasons,
    score_outer_fold,
)


def _row(mlbam_id, role, cohort_year, outcome, signal):
    return {
        "mlbam_id": mlbam_id,
        "name": f"Player {mlbam_id}",
        "role": role,
        "cohort_year": cohort_year,
        "outcome": outcome,
        "signal": signal,
    }


def _hitter_season(year, *, strong=False):
    return {
        "year": year,
        "pa": 500,
        "r": 100 if strong else 50,
        "hr": 30 if strong else 10,
        "rbi": 100 if strong else 50,
        "sb": 20 if strong else 5,
        "avg": 0.300 if strong else 0.240,
        "ops": 0.850 if strong else 0.700,
        "so": 80 if strong else 140,
    }


def _pitcher_season(year, *, strong=False):
    return {
        "year": year,
        "ip": 140,
        "so": 180 if strong else 90,
        "sv": 0,
        "hld": 0,
        "era": 3.00 if strong else 4.50,
        "whip": 1.05 if strong else 1.35,
        "k_bb": 4.0 if strong else 2.0,
        "l": 6 if strong else 12,
    }


def _contract():
    rows = [
        _row(1, "hitter", 2009, "star", 0.10),
        _row(2, "pitcher", 2009, "star", 0.20),
        _row(7, "hitter", 2010, "role", 0.25),
        _row(8, "pitcher", 2010, "role", 0.35),
        _row(3, "hitter", 2013, "poison_if_read", 0.30),
        _row(4, "pitcher", 2013, "poison_if_read", 0.40),
        _row(5, "hitter", 2014, "star", 0.50),
        _row(6, "pitcher", 2014, "star", 0.60),
    ]
    seasons = {
        "1_hitter": [_hitter_season(2010, strong=True)],
        "2_pitcher": [_pitcher_season(2010, strong=True)],
        "7_hitter": [{**_hitter_season(2011), "pa": 300}],
        "8_pitcher": [{**_pitcher_season(2011), "ip": 90}],
        "3_hitter": [{**_hitter_season(2014), "pa": 300}],
        "4_pitcher": [{**_pitcher_season(2014), "ip": 90}],
        "5_hitter": [_hitter_season(2015, strong=True)],
        "6_pitcher": [_pitcher_season(2015, strong=True)],
    }
    quality_starts = {
        "schema": "valucast_stage2_quality_starts",
        "status": "ready",
        "content_sha256": "synthetic-qs-hash",
        "rows": [
            {
                "mlbam_id": mlbam_id,
                "season": year,
                "games_started": 20,
                "quality_starts": 18 if mlbam_id in {2, 6} else 8,
            }
            for mlbam_id, year in ((2, 2010), (8, 2011), (4, 2014), (6, 2015))
        ],
    }
    return {
        "artifact": "synthetic_extended_history",
        "rows": rows,
        "historical_mlb_seasons": seasons,
        "quality_starts": quality_starts,
    }


def test_inner_folds_require_four_years_of_earlier_training():
    rows = [
        _row(year, "hitter", year, "bust", 0.0)
        for year in range(2009, 2019)
    ]

    assert derive_inner_fold_years(rows, 2014) == [2013]
    assert derive_inner_fold_years(rows, 2018) == [2013, 2014, 2015, 2016, 2017]


def test_outer_crossfit_sources_stop_at_the_outcome_complete_boundary():
    rows = [
        _row(year, "hitter", year, "bust", 0.0)
        for year in range(2009, 2018)
    ]

    assert fold_scoring.derive_crossfit_source_years(rows, 2017) == [
        2009,
        2010,
        2011,
        2012,
        2013,
    ]


def test_crossfit_fold_trains_on_every_other_row_in_the_mature_pool():
    rows = [
        _row(year, "hitter", year, "role", float(year))
        for year in range(2009, 2014)
    ]
    seasons = {
        f"{year}_hitter": [_hitter_season(year + 1)]
        for year in range(2009, 2014)
    }

    fold = fold_scoring._fold_input(rows, seasons, 2011)

    assert {row["cohort_year"] for row in fold["training_rows"]} == {
        2009,
        2010,
        2012,
        2013,
    }
    assert {row["cohort_year"] for row in fold["pseudo_current_rows"]} == {2011}
    assert fold["training_strategy"] == "leave_one_cohort_out"


def test_crossfit_fold_rejects_an_incomplete_qualifying_reference_season():
    rows = [
        _row(year, "hitter", year, "role", float(year))
        for year in (2009, 2010, 2011)
    ]
    seasons = {
        f"{year}_hitter": [_hitter_season(year + 1)]
        for year in (2009, 2010, 2011)
    }
    seasons["2009_hitter"][0].pop("sb")

    with pytest.raises(FoldScoringError, match="qualifying reference season.*missing.*sb"):
        fold_scoring._fold_input(rows, seasons, 2011)


def test_production_raw_scorer_uses_the_fold_maturity_boundary(monkeypatch):
    observed = []

    def train_role(role, rows, now=None, *, mature_through=None):
        observed.append(("outcome", role, mature_through))
        return {"role": role}

    def train_impact_role(
        role,
        rows,
        seasons,
        references,
        now=None,
        *,
        mature_through=None,
    ):
        observed.append(("impact", role, mature_through))
        return {"role": role}

    monkeypatch.setattr("prospects.model.train_role", train_role)
    monkeypatch.setattr("prospects.model.train_impact_role", train_impact_role)
    monkeypatch.setattr("prospects.model.score_current", lambda *_args: [])
    fold = {
        "test_year": 2022,
        "train_through": 2021,
        "training_rows": [],
        "training_seasons": {},
        "impact_references": {},
        "pseudo_current_rows": [],
    }

    fold_scoring.production_raw_head_scorer(
        fold,
        model_flags={"PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"},
    )

    assert observed == [
        ("outcome", "hitter", 2021),
        ("outcome", "pitcher", 2021),
        ("impact", "hitter", 2021),
        ("impact", "pitcher", 2021),
    ]


def test_fold_local_seasons_include_only_training_identities_and_horizons():
    contract = _contract()
    training = [row for row in contract["rows"] if row["cohort_year"] <= 2009]

    local = fold_local_seasons(training, contract["historical_mlb_seasons"])

    assert set(local) == {"1_hitter", "2_pitcher"}
    assert [season["year"] for season in local["1_hitter"]] == [2010]


def test_direct_target_requires_joined_qs_for_a_qualifying_pitcher_season():
    record = _row(9, "pitcher", 2010, "role", 0.0)
    seasons = {"9_pitcher": [_pitcher_season(2011)]}
    references = {
        "hitter": {field: [1.0] for field in ("r", "hr", "rbi", "sb", "avg", "ops", "so")},
        "pitcher": {
            field: [1.0]
            for field in ("so", "qs", "sv_hld", "era", "whip", "k_bb", "l")
        },
    }

    with pytest.raises(FoldScoringError, match="missing canonical categories.*qs"):
        direct_7x7_target(record, seasons, references)


def test_outer_fold_scores_both_modes_on_identical_ids_then_reads_targets():
    contract = _contract()
    original = copy.deepcopy(contract)
    raw_calls = []
    rank_calls = []

    def raw_scorer(fold, *, model_flags):
        assert all("outcome" not in row for row in fold["pseudo_current_rows"])
        assert set(fold["training_seasons"]) <= {
            f"{row['mlbam_id']}_{row['role']}" for row in fold["training_rows"]
        }
        assert max(row["cohort_year"] for row in fold["training_rows"]) <= 2010
        if fold["training_strategy"] == "leave_one_cohort_out":
            assert all(
                row["cohort_year"] != fold["test_year"]
                for row in fold["training_rows"]
            )
        raw_calls.append((fold["test_year"], dict(model_flags)))
        rows = [
            {
                "mlbam_id": row["mlbam_id"],
                "role": row["role"],
                "expected_outcome_score": row["signal"],
                "expected_category_impact_score": row["signal"] + 0.05,
            }
            for row in fold["pseudo_current_rows"]
        ]
        return rows, {"test_year": fold["test_year"], "trained": len(fold["training_rows"])}

    def rank_scorer(fold, model_rows, *, model_score_mode):
        rank_calls.append(model_score_mode)
        if model_score_mode == "common_target":
            assert all("common_target_calibration" in row for row in model_rows)
            field = "expected_outcome_score_common_target"
        else:
            assert all("expected_outcome_score_common_target" not in row for row in model_rows)
            field = "expected_outcome_score"
        return {
            (str(row["mlbam_id"]), row["role"]): float(row[field])
            for row in model_rows
        }, {"model_score_mode": model_score_mode, "full_rank_v1": "synthetic"}

    result = score_outer_fold(
        contract,
        2014,
        raw_scorer=raw_scorer,
        rank_scorer=rank_scorer,
        calibration_min_rows=1,
        calibration_min_source_folds=2,
    )

    assert contract == original
    assert result["metadata"]["train_through"] == 2010
    assert result["metadata"]["inner_fold_years"] == [2009, 2010]
    assert result["metadata"]["calibration_mature_through"] == 2010
    assert result["metadata"]["calibration_strategy"] == (
        "leave_one_cohort_out_within_outer_mature_pool"
    )
    assert result["metadata"]["quality_starts_sha256"] == "synthetic-qs-hash"
    assert result["metadata"]["identity_count"] == 2
    assert set(result["scores"]["incumbent"]) == {("5", "hitter"), ("6", "pitcher")}
    assert set(result["scores"]["candidate"]) == set(result["scores"]["incumbent"])
    assert result["targets"][("5", "hitter")]["outcome_tier"] == 1.0
    assert result["targets"][("6", "pitcher")]["direct_7x7_target"] == pytest.approx(0.75)
    assert set(result["calibrator_hashes"]) == {
        "hitter.outcome",
        "hitter.impact",
        "pitcher.outcome",
        "pitcher.impact",
    }
    assert raw_calls == [
        (2009, {"PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"}),
        (2010, {"PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"}),
        (2014, {"PITCHER_INVESTMENT_FEATURE_MODE": "incumbent"}),
        (2014, {"PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"}),
    ]
    assert rank_calls == ["incumbent_role_quantile", "common_target"]
    assert result["diagnostics"]["identity_sets_equal"] is True
    assert [
        fold["target_complete_by"]
        for fold in result["diagnostics"]["inner_folds"]
    ] == [2013, 2014]
    assert all(
        fold["training_strategy"] == "leave_one_cohort_out"
        for fold in result["diagnostics"]["inner_folds"]
    )


def test_identity_mismatch_fails_before_outer_targets_are_interpreted():
    contract = _contract()
    for row in contract["rows"]:
        if row["cohort_year"] == 2014:
            row["outcome"] = "poison_if_read"

    def raw_scorer(fold, *, model_flags):
        return [
            {
                "mlbam_id": row["mlbam_id"],
                "role": row["role"],
                "expected_outcome_score": row["signal"],
                "expected_category_impact_score": row["signal"],
            }
            for row in fold["pseudo_current_rows"]
        ], {}

    rank_call = 0

    def rank_scorer(fold, model_rows, *, model_score_mode):
        nonlocal rank_call
        rank_call += 1
        scores = {
            (str(row["mlbam_id"]), row["role"]): 0.5 for row in model_rows
        }
        if rank_call == 2:
            scores.pop(next(iter(scores)))
        return scores, {}

    with pytest.raises(FoldScoringError, match="identity mismatch"):
        score_outer_fold(
            contract,
            2014,
            raw_scorer=raw_scorer,
            rank_scorer=rank_scorer,
            calibration_min_rows=1,
            calibration_min_source_folds=1,
        )
