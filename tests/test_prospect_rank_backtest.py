"""Unit locks for the Rank-gate v1 replay harness (prospects/rank_backtest.py).

Synthetic only — the full fold replay is a research script, not a test. These
lock the registered mechanics: the concordance estimator, the neutralization
hard-errors, the fold-contract stamping landmines, and bootstrap determinism.
"""
import pytest

from prospects import rank_backtest as harness
from prospects import rank_v1


def test_pair_concordance_matches_registered_estimator():
    # Perfect ordering: higher score on higher tier.
    assert harness._pair_concordance([(3.0, 1.0), (2.0, 0.5), (1.0, 0.0)]) == 1.0
    # Fully inverted.
    assert harness._pair_concordance([(1.0, 1.0), (2.0, 0.5), (3.0, 0.0)]) == 0.0
    # Score tie on a differing-tier pair contributes 0.5.
    assert harness._pair_concordance([(2.0, 1.0), (2.0, 0.0)]) == 0.5
    # Same-tier pairs are dropped; all-same-tier has no comparable pairs.
    assert harness._pair_concordance([(1.0, 0.5), (2.0, 0.5)]) is None


def test_neutralization_patches_and_restores_module_paths():
    saved = {
        attr: getattr(rank_v1, attr) for attr in harness._NEUTRALIZED_PATH_ATTRS
    }
    with harness._neutralized_module_state():
        for attr in harness._NEUTRALIZED_PATH_ATTRS:
            assert "__rank_backtest_void__" in str(getattr(rank_v1, attr))
        assert rank_v1._manual_graduated_ids() == set()
    for attr, value in saved.items():
        assert getattr(rank_v1, attr) == value


def test_fold_contract_stamps_current_rows_and_ungraduates_service():
    fold_rows = {
        ("101", "hitter"): {
            "mlbam_id": 101, "role": "hitter", "cohort_year": 2019,
            "outcome": "role", "plate_appearances": 400,
        },
        ("202", "pitcher"): {
            "mlbam_id": 202, "role": "pitcher", "cohort_year": 2019,
            "outcome": "bust", "innings_pitched": 90,
        },
    }
    contract = harness._fold_contract(
        {"schema_version": "x", "historical": {"rows": []},
         "historical_mlb_seasons": {}, "rookie_limits": None},
        fold_rows,
        2019,
    )
    rows = contract["current"]["hitters"] + contract["current"]["pitchers"]
    assert len(rows) == 2
    for row in rows:
        # Un-stamped rows take the no-current-season penalty on EVERY row.
        assert row["source_kind"] == "current_season"
        assert row["sample_season"] == 2019
    # Today's graduated flags would drop the whole cohort upstream of rank.
    assert all(row["graduated"] is False for row in contract["mlb_service"])
    assert contract["generated_at"] == "2019-09-30T00:00:00+00:00"


def test_variant_identity_set_mismatch_is_a_hard_error(monkeypatch):
    def fake_fold(contract, test_year, kwargs=None):
        keys = {("1", "hitter")} if kwargs else {("1", "hitter"), ("2", "pitcher")}
        scores = {key: 1.0 for key in keys}
        tiers = {key: 0.5 for key in keys}
        return {"scores": scores, "tiers": tiers}, {"test_cohort": test_year}

    monkeypatch.setattr(harness, "_fold_board_scores", fake_fold)
    contract = {"historical": {"rows": [
        {"cohort_year": 2014}, {"cohort_year": 2018},
    ]}}
    with pytest.raises(harness.NeutralizationError, match="identity sets differ"):
        harness.build_rank_backtest(
            contract, {"C0": {}, "C1": {"lever": True}}
        )


def test_paired_bootstrap_is_deterministic_and_detects_improvement():
    tiers = {("1", "pitcher"): 0.0, ("2", "pitcher"): 0.5, ("3", "pitcher"): 1.0,
             ("4", "pitcher"): 0.0, ("5", "pitcher"): 1.0}
    baseline = {("1", "pitcher"): 5.0, ("2", "pitcher"): 4.0, ("3", "pitcher"): 3.0,
                ("4", "pitcher"): 2.0, ("5", "pitcher"): 1.0}  # inverted: bad
    candidate = {("1", "pitcher"): 1.0, ("2", "pitcher"): 2.0, ("3", "pitcher"): 3.0,
                 ("4", "pitcher"): 0.5, ("5", "pitcher"): 4.0}  # aligned: good
    fold = {"baseline": baseline, "candidate": candidate, "tiers": tiers}
    first = harness.paired_bootstrap_lower_bound([fold], "pitcher", n_bootstraps=200)
    second = harness.paired_bootstrap_lower_bound([fold], "pitcher", n_bootstraps=200)
    assert first == second  # seeded
    # candidate orders all 8 comparable pairs correctly (C=1.0); baseline gets
    # only the two pitcher-4 pairs right (C=0.25).
    assert first["point"] == pytest.approx(0.75)
    assert first["lower_bound"] is not None
