"""Tests for the shadow-only hitter pedigree feature experiment.

7/7: this must never touch anything the live board reads. rank_v1.py,
prospects/model.py's served OUTCOME_FEATURE_NAMES, and
data/models/valucast_prospect_model.json are all untouched by this module --
it only imports read-only helpers from prospects/model.py and writes its own
separate artifact.
"""
from prospects.hitter_pedigree_shadow import (
    AUGMENTED_HITTER_FEATURE_NAMES,
    PEDIGREE_FEATURE_NAMES,
    _augment_rows,
    _pedigree_extra,
    _source_policy,
)
from prospects.model import OUTCOME_FEATURE_NAMES


def test_source_policy_marks_everything_non_live():
    policy = _source_policy()
    assert policy["feeds_live_valucast_rank"] is False
    assert policy["feeds_model_score"] is False
    assert policy["feeds_public_rank"] is False
    assert policy["feeds_live_dd_value"] is False


def test_augmented_feature_names_only_appends_to_the_real_live_vector():
    # Must be the real, live hitter feature list plus exactly the 2 lean
    # pedigree features -- not a reimplementation that could silently drift
    # from what the served model actually uses.
    assert AUGMENTED_HITTER_FEATURE_NAMES == tuple(OUTCOME_FEATURE_NAMES["hitter"]) + PEDIGREE_FEATURE_NAMES
    assert PEDIGREE_FEATURE_NAMES == ("draft_record_known", "inverse_draft_pick")


def test_pedigree_extra_flags_presence_and_inverts_pick_number():
    drafted = _pedigree_extra({"draft_record_known": True, "draft_pick_number": 4})
    assert drafted == [1.0, 0.25]

    undrafted = _pedigree_extra({"draft_record_known": False, "draft_pick_number": None})
    assert undrafted == [0.0, 1.0 / 999.0]


def test_augment_rows_appends_exactly_two_values_to_real_historical_rows():
    dataset_rows = [
        {
            "role": "hitter", "mlbam_id": 1, "cohort_year": 2015, "level": "AA", "age": 22,
            "outcome": "role", "iso": 0.15, "k_pct": 20.0, "bb_pct": 10.0, "ops": 0.750,
            "avg": 0.260, "obp": 0.330, "slg": 0.420, "babip": 0.300,
            "home_runs": 10, "stolen_bases": 5, "plate_appearances": 400,
            "draft_record_known": True, "draft_pick_number": 12,
        },
        {
            "role": "hitter", "mlbam_id": 2, "cohort_year": 2016, "level": "AAA", "age": 23,
            "outcome": "bust", "iso": 0.10, "k_pct": 25.0, "bb_pct": 8.0, "ops": 0.650,
            "avg": 0.230, "obp": 0.290, "slg": 0.360, "babip": 0.280,
            "home_runs": 5, "stolen_bases": 2, "plate_appearances": 350,
            "draft_record_known": False, "draft_pick_number": None,
        },
    ]
    augmented = _augment_rows(dataset_rows)
    assert len(augmented) == 2
    for row in augmented:
        assert len(row["features"]) == len(AUGMENTED_HITTER_FEATURE_NAMES)
        # last 2 values are the pedigree extras; everything before matches unchanged
        assert row["features"][-2:] == _pedigree_extra(
            next(r for r in dataset_rows if r["mlbam_id"] == row["mlbam_id"])
        )
