"""Unit locks for the E1 pitcher challenger (dark parallel path).

Covers the four things the challenger must guarantee:
  1. Serving freeze: both flags OFF => scoring byte-identical on a synthetic set.
  2. Split detection (lever a): fold-fitted, no target leakage; train/test cohort
     disjointness in the walk-forward; the appended interactions are a pure
     function of the row's own features.
  3. Per-group shrink (lever b): fast K-group regressed less, slow ERA/WHIP-group
     more, and the RETURNED scalar reliability is left at the incumbent value.
  4. The exploratory replay bootstrap is deterministic at seed 28017 and never the
     registered seed 28013.
"""
import numpy as np
import pytest

from prospects import model
from prospects import pitcher_challenger as pc
from prospects.model import (
    OUTCOME_FEATURE_NAMES,
    _outcome_feature_names,
    _outcome_feature_vector,
    _regress_current_features,
    _walk_forward,
)


@pytest.fixture(autouse=True)
def _flags_off_by_default():
    """Every test starts and ends with both dark levers OFF."""
    model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED = False
    model.PITCHER_PER_GROUP_SHRINK_ENABLED = False
    yield
    model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED = False
    model.PITCHER_PER_GROUP_SHRINK_ENABLED = False


def _pitcher_record(**overrides):
    record = {
        "role": "pitcher", "level": "AA", "age": 21, "is_starter": True,
        "k_per_9": 11.0, "bb_per_9": 3.0, "k_bb_pct": 0.22, "era": 2.80,
        "whip": 1.05, "innings_pitched": 40.0, "games_started": 8, "games": 8,
    }
    record.update(overrides)
    return record


# ---- 1. serving freeze --------------------------------------------------------
def test_flags_default_off():
    assert model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED is False
    assert model.PITCHER_PER_GROUP_SHRINK_ENABLED is False


def test_feature_vector_and_names_identical_when_flags_off():
    record = _pitcher_record()
    assert len(_outcome_feature_vector(record, "pitcher")) == len(
        OUTCOME_FEATURE_NAMES["pitcher"]
    )
    assert _outcome_feature_names("pitcher") == OUTCOME_FEATURE_NAMES["pitcher"]
    # Hitters are never touched by either flag, on or off.
    model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED = True
    assert _outcome_feature_names("hitter") == OUTCOME_FEATURE_NAMES["hitter"]


def test_regress_scoring_frozen_when_flag_off():
    record = _pitcher_record()
    names = _outcome_feature_names("pitcher")
    role_model = {"feature_names": list(names), "means": [0.0] * len(names)}
    raw = _outcome_feature_vector(record, "pitcher")
    out_off, rel_off = _regress_current_features(raw, role_model, "pitcher", 40.0)
    # Flipping only the OTHER lever (split) must not perturb the shrink path.
    model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED = True
    names_on = _outcome_feature_names("pitcher")
    role_model_on = {"feature_names": list(names_on), "means": [0.0] * len(names_on)}
    raw_on = _outcome_feature_vector(record, "pitcher")
    out_on, rel_on = _regress_current_features(raw_on, role_model_on, "pitcher", 40.0)
    assert rel_off == rel_on
    # The first 36 (incumbent) regressed values are unchanged by the split lever.
    assert out_on[: len(out_off)] == out_off


# ---- 2. split detection (lever a): purity + fold discipline -------------------
def test_split_appends_four_named_interactions():
    model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED = True
    record = _pitcher_record()
    vector = _outcome_feature_vector(record, "pitcher")
    names = _outcome_feature_names("pitcher")
    assert len(vector) == len(names) == len(OUTCOME_FEATURE_NAMES["pitcher"]) + 4
    assert names[-4:] == pc.PITCHER_ROLE_SPLIT_FEATURE_NAMES
    # is_starter == 1 => each interaction equals the raw core rate.
    assert vector[-4:] == [11.0, 0.22, 2.80, 1.05]


def test_split_interactions_are_pure_and_role_gated():
    # Reliever: is_starter == 0 => every interaction is exactly 0 (role selector).
    model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED = True
    reliever = _pitcher_record(is_starter=False, games_started=0)
    assert _outcome_feature_vector(reliever, "pitcher")[-4:] == [0.0, 0.0, 0.0, 0.0]
    # The extra builder is a pure function of the 8-wide base vector only —
    # no season/outcome/label input can leak in.
    base = [11.0, 3.0, 0.22, 2.80, 1.05, 1.5, 0.0, 1.0]
    assert pc.pitcher_role_split_extra(base) == [11.0, 0.22, 2.80, 1.05]


def test_walk_forward_folds_are_cohort_disjoint_with_split_on():
    # Two synthetic rows per cohort across 4 cohorts; the split lever must not
    # change the fold machinery's train<test disjointness (no leakage).
    model.PITCHER_OUTCOME_ROLE_SPLIT_ENABLED = True
    rows = []
    for cohort in (2015, 2016, 2017, 2018):
        for offset in (0, 1):
            rows.append(
                {
                    "mlbam_id": cohort * 10 + offset,
                    "cohort_year": cohort,
                    "level": "AA",
                    "age": 21,
                    "features": [float(cohort + offset)] * 6,
                    "baseline_features": [float(cohort + offset)] * 6,
                    "target": float(offset),
                }
            )
    validation = _walk_forward(rows)
    for fold in validation["folds"]:
        assert fold["train_year_max"] < fold["test_year"]
        assert set(fold["train_ids"]).isdisjoint(fold["test_ids"])


# ---- 3. per-group shrink (lever b) --------------------------------------------
def test_group_classifier_membership():
    assert pc.pitcher_shrink_group("k_per_9") == "fast"
    assert pc.pitcher_shrink_group("k_bb_pct") == "fast"
    assert pc.pitcher_shrink_group("era") == "slow"
    assert pc.pitcher_shrink_group("whip") == "slow"
    assert pc.pitcher_shrink_group("bb_per_9") == "other"  # walk-adjacent
    assert pc.pitcher_shrink_group("level") == "other"


def test_group_reliability_ordering():
    # Same sample: fast (small constant) trusts the sample MORE than slow.
    sample = 40.0
    fast = pc.pitcher_group_reliability(sample, "k_per_9")
    slow = pc.pitcher_group_reliability(sample, "era")
    other = pc.pitcher_group_reliability(sample, "bb_per_9")
    assert fast > other > slow
    assert other == pytest.approx(sample / (sample + 50.0))


def test_per_group_shrink_moves_only_features_not_scalar():
    record = _pitcher_record()
    names = _outcome_feature_names("pitcher")
    role_model = {"feature_names": list(names), "means": [0.0] * len(names)}
    raw = _outcome_feature_vector(record, "pitcher")
    out_off, rel_off = _regress_current_features(raw, role_model, "pitcher", 40.0)
    model.PITCHER_PER_GROUP_SHRINK_ENABLED = True
    out_on, rel_on = _regress_current_features(raw, role_model, "pitcher", 40.0)
    # Returned scalar reliability is unchanged (confidence tiers stay frozen).
    assert rel_on == rel_off
    k_idx = names.index("k_per_9")
    era_idx = names.index("era")
    # means are 0, so shrunk value == reliability * raw. Fast K closer to raw,
    # slow ERA closer to the (zero) mean, vs the single-constant baseline.
    assert abs(out_on[k_idx]) > abs(out_off[k_idx])   # K trusted more
    assert abs(out_on[era_idx]) < abs(out_off[era_idx])  # ERA trusted less


def test_per_group_shrink_is_pitcher_only():
    # Hitters use the single reliability even with the pitcher flag on.
    from prospects.model import _feature_vector

    model.PITCHER_PER_GROUP_SHRINK_ENABLED = True
    hrec = {"role": "hitter", "level": "AA", "age": 21, "iso": 0.2, "k_pct": 20.0,
            "bb_pct": 10.0, "ops": 0.8, "plate_appearances": 100.0}
    raw = _feature_vector(hrec, "hitter")
    names = OUTCOME_FEATURE_NAMES["hitter"]
    role_model = {"feature_names": list(names[: len(raw)]), "means": [0.0] * len(raw)}
    out, rel = _regress_current_features(raw, role_model, "hitter", 100.0)
    expected = 100.0 / (100.0 + model.SAMPLE_REGRESSION["hitter"])
    assert rel == pytest.approx(expected)
    # every shrunk hitter value == expected * raw (single constant, unchanged)
    assert out[0] == pytest.approx(expected * raw[0])


# ---- 4. exploratory replay determinism + seed guard ---------------------------
def test_replay_uses_exploratory_seed_not_registered():
    from scripts import run_e1_exploratory_replay as replay

    assert replay.EXPLORATORY_SEED == 28017
    assert replay.EXPLORATORY_SEED != replay.REGISTERED_SEED == 28013
    # The registered C1 pedigree lever must NOT be part of the E1 variant.
    assert "PITCHER_STALE_PEDIGREE_DECAY_ENABLED" not in replay.E1_SPEC["model_flags"]


def test_replay_bootstrap_deterministic_at_exploratory_seed():
    from prospects.rank_backtest import paired_bootstrap_lower_bound

    tiers = {("1", "pitcher"): 0.0, ("2", "pitcher"): 0.5, ("3", "pitcher"): 1.0,
             ("4", "pitcher"): 0.0, ("5", "pitcher"): 1.0}
    baseline = {k: v for k, v in zip(tiers, (5.0, 4.0, 3.0, 2.0, 1.0))}
    candidate = {k: v for k, v in zip(tiers, (1.0, 2.0, 3.0, 0.5, 4.0))}
    fold = {"baseline": baseline, "candidate": candidate, "tiers": tiers}
    first = paired_bootstrap_lower_bound([fold], "pitcher", n_bootstraps=200, seed=28017)
    second = paired_bootstrap_lower_bound([fold], "pitcher", n_bootstraps=200, seed=28017)
    assert first == second
    # A different seed changes the CI (proves the seed actually drives resampling).
    # NEVER 28013 here -- the registered gate seed stays out of every pitcher
    # bootstrap call, even on toy data, so the no-spend guarantee is absolute.
    other = paired_bootstrap_lower_bound([fold], "pitcher", n_bootstraps=200, seed=29001)
    assert other["bootstrap_sd"] != first["bootstrap_sd"]


def test_slice_delta_weights_by_slice_sample():
    from scripts.run_e1_exploratory_replay import _slice_delta

    # Perfect challenger ordering vs inverted baseline on a 3-pitcher slice.
    fold = {
        "baseline": {("1", "pitcher"): 3.0, ("2", "pitcher"): 2.0, ("3", "pitcher"): 1.0},
        "candidate": {("1", "pitcher"): 1.0, ("2", "pitcher"): 2.0, ("3", "pitcher"): 3.0},
        "tiers": {("1", "pitcher"): 0.0, ("2", "pitcher"): 0.5, ("3", "pitcher"): 1.0},
    }
    keys = {("1", "pitcher"), ("2", "pitcher"), ("3", "pitcher")}
    result = _slice_delta([fold], [keys])
    # baseline C=0 (fully inverted), candidate C=1 => delta +1.0.
    assert result["point_delta_c"] == pytest.approx(1.0)
    assert result["pooled_n"] == 3


def test_slice_delta_skips_folds_below_two():
    from scripts.run_e1_exploratory_replay import _slice_delta

    fold = {
        "baseline": {("1", "pitcher"): 3.0},
        "candidate": {("1", "pitcher"): 1.0},
        "tiers": {("1", "pitcher"): 0.0},
    }
    result = _slice_delta([fold], [{("1", "pitcher")}])
    assert result["point_delta_c"] is None
    assert result["per_fold"][0]["delta_c"] is None


def test_fast_concordance_reference_parity_holds():
    from prospects.rank_backtest import _pair_concordance, _tier_concordance_fast

    rng = np.random.default_rng(11)
    for _ in range(30):
        n = int(rng.integers(3, 40))
        scores = np.round(rng.normal(0, 1, n), 1)
        tiers = rng.choice([0.0, 0.5, 1.0], n)
        ref = _pair_concordance(list(zip(scores, tiers)))
        fast = _tier_concordance_fast(scores, tiers)
        if ref is None:
            assert fast is None
        else:
            assert fast == pytest.approx(ref, abs=1e-12)
