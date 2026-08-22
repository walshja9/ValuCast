"""Unit locks for the Rank-gate v1 replay harness (prospects/rank_backtest.py).

Synthetic only — the full fold replay is a research script, not a test. These
lock the registered mechanics: the concordance estimator, the neutralization
hard-errors, the fold-contract stamping landmines, and bootstrap determinism.
"""
from pathlib import Path

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


def test_explicit_finalized_2021_maturity_is_nonempty_without_changing_default():
    hitters = [
        {
            "mlbam_id": 100000 + index,
            "role": "hitter",
            "cohort_year": 2021,
            "level": "AA",
            "age": 21,
            "outcome": ("bust", "role", "star")[index % 3],
            "plate_appearances": 300,
            "iso": 0.15,
            "k_pct": 22.0,
            "bb_pct": 10.0,
            "ops": 0.75,
        }
        for index in range(385)
    ]
    pitchers = [
        {
            "mlbam_id": 200000 + index,
            "role": "pitcher",
            "cohort_year": 2021,
            "level": "AA",
            "age": 22,
            "outcome": ("bust", "role", "star")[index % 3],
            "innings_pitched": 100,
            "k_per_9": 9.0,
            "bb_per_9": 3.0,
            "k_bb_pct": 15.0,
            "era": 3.5,
            "whip": 1.2,
            "is_starter": True,
        }
        for index in range(387)
    ]
    source = {"historical": {"rows": hitters + pitchers}}

    default_rows = harness._eligible_fold_rows(source, 2021)
    rows = harness._eligible_fold_rows(source, 2021, mature_through=2021)
    assert rows == default_rows
    assert len(rows) == 772
    assert {row["cohort_year"] for row in rows.values()} == {2021}

    with pytest.raises(ValueError, match="2018, 2019, or 2021"):
        harness.build_fold_rank_context(
            {
                "schema_version": "prospect_v2_development_contract_v1",
                "historical": {"rows": []},
                "historical_mlb_seasons": {},
            },
            2022,
            mature_through=2021,
        )


def test_fold_rank_context_uses_only_caller_supplied_data(monkeypatch):
    row = {
        "mlbam_id": 1,
        "role": "hitter",
        "cohort_year": 2021,
        "outcome": "role",
        "plate_appearances": 300,
    }
    contract = {
        "schema_version": "prospect_v2_development_contract_v1",
        "historical": {"rows": [{**row, "cohort_year": 2017}, row]},
        "historical_mlb_seasons": {},
    }
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("disk read")))
    monkeypatch.setattr(harness, "_eligible_fold_rows", lambda *_args, **_kwargs: {("1", "hitter"): row})
    monkeypatch.setattr(harness, "train_role", lambda *_args, **_kwargs: {})
    impact_calls = []

    def train_impact(*_args, **kwargs):
        impact_calls.append(kwargs)
        return {}

    monkeypatch.setattr(harness, "train_impact_role", train_impact)
    monkeypatch.setattr(harness, "model_score_current", lambda *_args, **_kwargs: [{"mlbam_id": 1, "role": "hitter"}])
    monkeypatch.setattr(harness, "train_target", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(harness, "universal_score_current", lambda *_args, **_kwargs: [{"mlbam_id": 1, "role": "hitter"}])
    monkeypatch.setattr(harness, "build_layer", lambda *_args, **_kwargs: {"profiles": [{"mlbam_id": 1, "role": "hitter"}]})
    monkeypatch.setattr(harness, "build_universe", lambda *_args, **kwargs: {"players": [], "current_orgs": kwargs["current_orgs"]})

    context = harness.build_fold_rank_context(contract, 2021, mature_through=2021)

    assert set(context) == {
        "prospect_universe",
        "dynasty_layer",
        "prospect_availability",
        "mlb_roster_status",
        "milb_history_by_key",
        "investment_evidence",
        "manual_graduated_ids",
        "consensus_snapshots",
        "incumbent_profiles",
        "input_contract",
    }
    assert context["prospect_universe"]["current_orgs"] == {}
    assert impact_calls == [
        {"now": "2021-09-30T00:00:00+00:00", "fold_local_evidence": True, "mature_through": 2021},
        {"now": "2021-09-30T00:00:00+00:00", "fold_local_evidence": True, "mature_through": 2021},
    ]


def test_explicit_historical_fold_omits_only_unavailable_qs_target(monkeypatch):
    rows = [
        {"mlbam_id": 1, "role": "hitter", "cohort_year": 2017, "outcome": "role", "plate_appearances": 300},
        {"mlbam_id": 2, "role": "pitcher", "cohort_year": 2017, "outcome": "role", "innings_pitched": 100},
    ]
    fold_rows = {
        ("3", "hitter"): {**rows[0], "mlbam_id": 3, "cohort_year": 2021},
        ("4", "pitcher"): {**rows[1], "mlbam_id": 4, "cohort_year": 2021},
    }
    contract = {
        "schema_version": "prospect_v2_development_contract_v1",
        "historical": {"rows": rows},
        "historical_mlb_seasons": {},
    }
    monkeypatch.setattr(harness, "TARGET_SPECS", {
        "hitter": {"representative_hr_per_600": {}},
        "pitcher": {"representative_qs_per_180": {}, "representative_k_per_180": {}},
    })
    monkeypatch.setattr(harness, "_eligible_fold_rows", lambda *_args, **_kwargs: fold_rows)
    monkeypatch.setattr(harness, "train_role", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(harness, "train_impact_role", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(harness, "model_score_current", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(harness, "universal_score_current", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(harness, "build_layer", lambda *_args, **_kwargs: {"profiles": []})
    monkeypatch.setattr(harness, "build_universe", lambda *_args, **_kwargs: {"players": []})
    captured = []
    monkeypatch.setattr(
        harness,
        "train_target",
        lambda role, target, *_args, **_kwargs: captured.append((role, target)) or {},
    )
    monkeypatch.setattr(
        harness,
        "_horizon_clipped_seasons",
        lambda *_args, **_kwargs: {"2_pitcher": [{"qs": None}]},
    )

    harness.build_fold_rank_context(contract, 2021, mature_through=2021)
    assert ("pitcher", "representative_qs_per_180") not in captured
    assert ("pitcher", "representative_k_per_180") in captured

    captured.clear()
    monkeypatch.setattr(
        harness,
        "_horizon_clipped_seasons",
        lambda *_args, **_kwargs: {"2_pitcher": [{"qs": 1}]},
    )
    harness.build_fold_rank_context(contract, 2021, mature_through=2021)
    assert ("pitcher", "representative_qs_per_180") in captured


def test_variant_identity_set_mismatch_is_a_hard_error(monkeypatch):
    def fake_fold(contract, test_year, variant=None):
        keys = {("1", "hitter")} if variant else {("1", "hitter"), ("2", "pitcher")}
        scores = {key: 1.0 for key in keys}
        tiers = {key: 0.5 for key in keys}
        return {"scores": scores, "tiers": tiers}, {"test_cohort": test_year}

    monkeypatch.setattr(harness, "_fold_board_scores", fake_fold)
    contract = {"historical": {"rows": [
        {"cohort_year": 2014}, {"cohort_year": 2018},
    ]}}
    with pytest.raises(harness.NeutralizationError, match="identity sets differ"):
        harness.build_rank_backtest(
            contract, {"C0": {}, "C1": {"model_flags": {"MAX_AGE": 25}}}
        )


def test_variant_spec_unknown_keys_and_unknown_flags_are_hard_errors():
    contract = {"historical": {"rows": [
        {"cohort_year": 2014}, {"cohort_year": 2018},
    ]}}
    with pytest.raises(harness.NeutralizationError, match="unknown spec keys"):
        harness.build_rank_backtest(contract, {"C1": {"lever": True}})
    with pytest.raises(harness.NeutralizationError, match="unknown model flag"):
        with harness._model_flags({"NOT_A_REAL_FLAG": True}):
            pass


def test_model_flags_sets_and_restores():
    from prospects import model

    assert model.PITCHER_STALE_PEDIGREE_DECAY_ENABLED is False
    with harness._model_flags(
        {"PITCHER_STALE_PEDIGREE_DECAY_ENABLED": True}
    ):
        assert model.PITCHER_STALE_PEDIGREE_DECAY_ENABLED is True
    assert model.PITCHER_STALE_PEDIGREE_DECAY_ENABLED is False


def test_fast_concordance_matches_reference_estimator():
    """_tier_concordance_fast must produce IDENTICAL values to the registered
    O(n^2) reference, including score-tie handling, or the bootstrap and the
    point metrics would silently measure different things."""
    import numpy as np

    rng = np.random.default_rng(7)
    for _ in range(50):
        n = int(rng.integers(3, 60))
        scores = np.round(rng.normal(50, 10, n), 1)  # rounding forces ties
        tiers = rng.choice([0.0, 0.5, 1.0], n)
        reference = harness._pair_concordance(list(zip(scores, tiers)))
        fast = harness._tier_concordance_fast(scores, tiers)
        if reference is None:
            assert fast is None
        else:
            assert fast == pytest.approx(reference, abs=1e-12)


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
