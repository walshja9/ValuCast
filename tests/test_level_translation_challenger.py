"""Unit locks for the fitted level-translation challenger (dark parallel path).

Covers what the challenger must guarantee:
  1. Serving freeze: flags OFF => feature vectors and names byte-identical, even
     with a fitted table installed.
  2. Fitted-table determinism + fold-refit isolation: same inputs give the same
     fingerprint; rows past train_through never contribute; different training
     windows give different tables.
  3. EB shrink math: thin cells pull toward the global per-stat curve with the
     documented n/(n+EB_K) weight.
  4. strike_pct None-safety: absent/zero/corrupt counts => the feature is
     absent (0.0, 0.0), never a fabricated command value.
  5. The exploratory replay runs at seed 31017 and can never touch a burned or
     proposed-registered seed; its artifact projection is within-role only.
"""
import pytest

from prospects import level_translation_challenger as ltc
from prospects import model
from prospects import universal
from prospects.model import (
    OUTCOME_FEATURE_NAMES,
    _outcome_feature_names,
    _outcome_feature_vector,
)


@pytest.fixture(autouse=True)
def _flags_off_by_default():
    """Every test starts and ends with both dark levers OFF and no table."""
    model.LEVEL_TRANSLATION_FITTED_ENABLED = False
    model.PITCHER_STRIKE_PCT_ENABLED = False
    yield
    model.LEVEL_TRANSLATION_FITTED_ENABLED = False
    model.PITCHER_STRIKE_PCT_ENABLED = False
    assert ltc.active_table() is None


def _pitcher_record(**overrides):
    record = {
        "role": "pitcher", "level": "AA", "age": 21, "is_starter": True,
        "k_per_9": 11.0, "bb_per_9": 3.0, "k_bb_pct": 22.0, "era": 2.80,
        "whip": 1.05, "innings_pitched": 40.0, "games_started": 8, "games": 8,
        "pitches": 600, "strikes": 400,
    }
    record.update(overrides)
    return record


def _hitter_record(**overrides):
    record = {
        "role": "hitter", "level": "A", "age": 19, "iso": 0.200, "k_pct": 20.0,
        "bb_pct": 10.0, "ops": 0.850, "avg": 0.300, "obp": 0.380, "slg": 0.470,
        "babip": 0.320, "plate_appearances": 300.0, "home_runs": 10,
        "stolen_bases": 5,
    }
    record.update(overrides)
    return record


def _anchor(mid, cohort, level, era, mlb_era):
    row = {
        "role": "pitcher", "mlbam_id": mid, "cohort_year": cohort, "age": 21,
        "level": level, "era": era, "whip": 1.20, "k_per_9": 9.0,
    }
    seasons = [{"year": cohort + 2, "ip": 100.0, "era": mlb_era, "whip": 1.30, "so": 100}]
    return row, {f"{mid}_pitcher": seasons}


def _fit(anchors, train_through):
    rows, seasons = [], {}
    for row, season_map in anchors:
        rows.append(row)
        seasons.update(season_map)
    return ltc.fit_translation_table(rows, seasons, train_through)


# ---- 1. serving freeze ---------------------------------------------------------
def test_flags_default_off():
    assert model.LEVEL_TRANSLATION_FITTED_ENABLED is False
    assert model.PITCHER_STRIKE_PCT_ENABLED is False


def test_flags_off_identity_even_with_table_installed():
    table = _fit([_anchor(1, 2015, "AA", 3.0, 4.0)], 2016)
    pitcher = _pitcher_record()
    hitter = _hitter_record()
    base_model = _outcome_feature_vector(pitcher, "pitcher")
    base_universal = universal._feature_vector(pitcher, "pitcher")
    base_hitter = universal._feature_vector(hitter, "hitter")
    with ltc.active_translation(table):
        assert _outcome_feature_vector(pitcher, "pitcher") == base_model
        assert universal._feature_vector(pitcher, "pitcher") == base_universal
        assert universal._feature_vector(hitter, "hitter") == base_hitter
    assert _outcome_feature_names("pitcher") == OUTCOME_FEATURE_NAMES["pitcher"]
    assert universal._active_feature_names("pitcher") == universal.FEATURE_NAMES["pitcher"]


def test_flag_on_without_table_is_identity():
    record = _pitcher_record()
    base = _outcome_feature_vector(record, "pitcher")
    model.LEVEL_TRANSLATION_FITTED_ENABLED = True
    assert _outcome_feature_vector(record, "pitcher") == base


# ---- 2. fitted table: determinism + fold isolation -----------------------------
def test_table_is_deterministic():
    anchors = [
        _anchor(1, 2014, "AA", 3.0, 4.0),
        _anchor(2, 2015, "A", 4.0, 4.5),
        _anchor(3, 2015, "AAA", 3.5, 3.8),
    ]
    first = _fit(anchors, 2016)
    second = _fit(anchors, 2016)
    assert first == second
    assert first["fingerprint"] == second["fingerprint"]


def test_rows_past_train_through_never_contribute():
    inside = _anchor(1, 2015, "AA", 3.0, 4.0)
    outside = _anchor(2, 2019, "AA", 1.0, 9.0)  # extreme delta, must be excluded
    narrow = _fit([inside, outside], 2016)
    assert narrow["roles"]["pitcher"]["era"]["anchor_count"] == 1
    wide = _fit([inside, outside], 2019)
    assert wide["roles"]["pitcher"]["era"]["anchor_count"] == 2
    assert narrow["fingerprint"] != wide["fingerprint"]


def test_single_cell_delta_matches_hand_computation():
    # Two AA anchors: deltas +1.0 and +0.5 -> cell mean 0.75. Only one level, so
    # the global curve is the flat pooled mean and delta_hat == 0.75 exactly.
    table = _fit(
        [_anchor(1, 2015, "AA", 3.0, 4.0), _anchor(2, 2015, "AA", 5.0, 5.5)], 2016
    )
    fit = table["roles"]["pitcher"]["era"]
    aa = fit["levels"]["AA"]
    assert aa["n"] == 2
    assert aa["cell_mean"] == pytest.approx(0.75)
    assert aa["delta_hat"] == pytest.approx(0.75)
    # Levels with no anchors take the curve value outright.
    assert fit["levels"]["A"]["n"] == 0
    assert fit["levels"]["A"]["delta_hat"] == pytest.approx(fit["levels"]["A"]["curve"])


def test_eb_shrink_pulls_thin_cell_toward_curve():
    anchors = [_anchor(100 + i, 2015, "A", 3.0, 5.0) for i in range(30)]
    anchors += [_anchor(200 + i, 2015, "A+", 3.0, 4.5) for i in range(30)]
    anchors += [_anchor(300, 2015, "AAA", 3.0, 8.0)]  # thin outlier cell (n=1)
    table = _fit(anchors, 2016)
    aaa = table["roles"]["pitcher"]["era"]["levels"]["AAA"]
    assert aaa["n"] == 1
    expected = (aaa["n"] * aaa["cell_mean"] + ltc.EB_K * aaa["curve"]) / (
        aaa["n"] + ltc.EB_K
    )
    assert aaa["delta_hat"] == pytest.approx(expected, abs=1e-5)
    # The thin cell is pulled most of the way toward the curve, not its own mean.
    assert abs(aaa["delta_hat"] - aaa["curve"]) < abs(aaa["cell_mean"] - aaa["curve"]) / 10


def test_maybe_translate_shifts_only_fitted_stats_and_is_idempotent():
    table = _fit([_anchor(1, 2015, "AA", 3.0, 4.0)], 2016)
    record = _pitcher_record()
    model.LEVEL_TRANSLATION_FITTED_ENABLED = True
    with ltc.active_translation(table):
        out = ltc.maybe_translate(record, "pitcher")
        delta = table["roles"]["pitcher"]["era"]["levels"]["AA"]["delta_hat"]
        assert out["era"] == pytest.approx(record["era"] + delta)
        assert out["bb_per_9"] == record["bb_per_9"]  # never a translated stat
        assert record["era"] == 2.80  # input never mutated
        again = ltc.maybe_translate(out, "pitcher")
        assert again is out  # sentinel: never translated twice
        # Unknown level -> identity.
        rookie = ltc.maybe_translate(_pitcher_record(level="ROK"), "pitcher")
        assert rookie["era"] == 2.80


# ---- 3. strike% lever ----------------------------------------------------------
def test_strike_pct_none_safety():
    assert ltc.strike_pct_extra({}) == [0.0, 0.0]
    assert ltc.strike_pct_extra({"pitches": None, "strikes": 10}) == [0.0, 0.0]
    assert ltc.strike_pct_extra({"pitches": 0, "strikes": 0}) == [0.0, 0.0]
    assert ltc.strike_pct_extra({"pitches": 100, "strikes": None}) == [0.0, 0.0]
    # Corrupt counts (strikes > pitches) are treated as unknown, not clamped.
    assert ltc.strike_pct_extra({"pitches": 100, "strikes": 150}) == [0.0, 0.0]
    dev, known = ltc.strike_pct_extra({"pitches": 600, "strikes": 400})
    assert known == 1.0
    assert dev == pytest.approx(400 / 600 - ltc.STRIKE_PCT_REF)


def test_strike_lever_appends_last_and_is_pitcher_only():
    model.PITCHER_STRIKE_PCT_ENABLED = True
    record = _pitcher_record()
    vector = _outcome_feature_vector(record, "pitcher")
    names = _outcome_feature_names("pitcher")
    assert len(vector) == len(names) == len(OUTCOME_FEATURE_NAMES["pitcher"]) + 2
    assert names[-2:] == ltc.STRIKE_PCT_FEATURE_NAMES
    off = OUTCOME_FEATURE_NAMES["pitcher"]
    model.PITCHER_STRIKE_PCT_ENABLED = False
    assert vector[: len(off)] == _outcome_feature_vector(record, "pitcher")
    # Hitters never gain the feature, flag on or off.
    model.PITCHER_STRIKE_PCT_ENABLED = True
    assert _outcome_feature_names("hitter") == OUTCOME_FEATURE_NAMES["hitter"]
    hitter = _hitter_record()
    base = universal._feature_vector(hitter, "hitter")
    assert len(base) == len(universal.FEATURE_NAMES["hitter"])


def test_universal_strike_shrink_membership():
    # strike_pct_dev shrinks with reliability; strike_pct_known does not.
    model.PITCHER_STRIKE_PCT_ENABLED = True
    record = _pitcher_record(innings_pitched=25.0)
    raw = universal._feature_vector(record, "pitcher")
    names = universal._active_feature_names("pitcher")
    assert names[-2:] == ltc.STRIKE_PCT_FEATURE_NAMES
    role_model = {"means": [0.0] * len(raw)}
    out, reliability = universal._regress_current_features(
        raw, role_model, "pitcher", 25.0
    )
    dev_idx = names.index("strike_pct_dev")
    known_idx = names.index("strike_pct_known")
    assert out[dev_idx] == pytest.approx(reliability * raw[dev_idx])
    assert out[known_idx] == raw[known_idx] == 1.0


def test_model_regress_holds_known_flag_fixed():
    model.PITCHER_STRIKE_PCT_ENABLED = True
    record = _pitcher_record(innings_pitched=25.0)
    names = _outcome_feature_names("pitcher")
    role_model = {"feature_names": list(names), "means": [0.0] * len(names)}
    raw = _outcome_feature_vector(record, "pitcher")
    out, reliability = model._regress_current_features(raw, role_model, "pitcher", 25.0)
    dev_idx = names.index("strike_pct_dev")
    known_idx = names.index("strike_pct_known")
    assert out[dev_idx] == pytest.approx(reliability * raw[dev_idx])
    assert out[known_idx] == raw[known_idx] == 1.0


# ---- 4. exploratory replay seed + quarantine locks ------------------------------
def test_replay_seed_discipline():
    from scripts import run_level_translation_dryrun as replay

    assert replay.EXPLORATORY_SEED == 31017
    assert replay.EXPLORATORY_SEED not in replay.FORBIDDEN_SEEDS
    assert {28013, 28017, 29001, 31013} <= replay.FORBIDDEN_SEEDS
    assert replay.REGISTERED_SEED == 28013
    for spec in replay.ABLATION_SPECS.values():
        # Never the registered C1 lever nor the E1 levers in this wave's variants.
        assert "PITCHER_STALE_PEDIGREE_DECAY_ENABLED" not in spec["model_flags"]
        assert "PITCHER_OUTCOME_ROLE_SPLIT_ENABLED" not in spec["model_flags"]
        assert "PITCHER_PER_GROUP_SHRINK_ENABLED" not in spec["model_flags"]


def test_replay_within_role_projection_is_quarantined():
    from scripts import run_level_translation_dryrun as replay

    scores = {
        ("1", "pitcher"): 3.0, ("2", "pitcher"): 2.0, ("3", "pitcher"): 1.0,
        ("4", "hitter"): 3.0, ("5", "hitter"): 1.0,
    }
    tiers = {
        ("1", "pitcher"): 1.0, ("2", "pitcher"): 0.5, ("3", "pitcher"): 0.0,
        ("4", "hitter"): 1.0, ("5", "hitter"): 0.0,
    }
    metrics = replay._within_role_metrics(scores, tiers)
    assert set(metrics) == {"c_pitcher", "pitcher_sample", "c_hitter", "hitter_sample"}
    assert metrics["c_pitcher"] == pytest.approx(1.0)
    assert metrics["c_hitter"] == pytest.approx(1.0)
