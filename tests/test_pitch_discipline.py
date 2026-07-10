"""Counting-logic tests for the plate-discipline layer — the load-bearing exactness.

The swing/whiff/contact definitions matched ProspectSavant to the decimal on the
7/10 spike; these fixtures lock that contract. Rates are computed count-then-divide
so multi-game aggregation stays exact.
"""
from fixtures.pitch_events import (
    SYNTHETIC_FEED,
    SECOND_GAME_FEED,
    PIXEL_ONLY_EVENTS,
    MISSING_SZ_EVENTS,
    PID,
    OTHER_PID,
)

from prospects.pitch_discipline import (
    count_player_pitches,
    merge_counts,
    rates_from_counts,
    classify_zone,
    fit_pixel_calibration,
    calibration_agreement,
    PixelCalibration,
)


def test_swing_and_whiff_detection_over_taxonomy():
    c = count_player_pitches(SYNTHETIC_FEED, PID)
    # 8 pitches to PID; swinging strike + foul + foul bunt + missed bunt + in-play
    # = 5 swings; swinging strike + missed bunt = 2 whiffs; the rest contact.
    assert c["pitches"] == 8
    assert c["swings"] == 5
    assert c["whiffs"] == 2
    assert c["contact"] == 3


def test_foul_is_swing_but_not_whiff():
    # A single foul: swing + contact, never a whiff.
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Foul"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["swings"] == 1 and c["whiffs"] == 0 and c["contact"] == 1


def test_called_ball_and_strike_are_not_swings():
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Ball"}},
        {"isPitch": True, "details": {"description": "Called Strike"}},
        {"isPitch": True, "details": {"description": "Intent Ball"}},
        {"isPitch": True, "details": {"description": "Pitchout"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["pitches"] == 4 and c["swings"] == 0 and c["whiffs"] == 0


def test_bunts_special_cased():
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Foul Bunt"}},
        {"isPitch": True, "details": {"description": "Missed Bunt"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["swings"] == 2      # both bunt attempts are swings
    assert c["whiffs"] == 1      # only the missed bunt is a whiff
    assert c["contact"] == 1     # the foul bunt is contact


def test_batter_filter_excludes_other_batter():
    c = count_player_pitches(SYNTHETIC_FEED, OTHER_PID)
    # OTHER_PID has exactly one swinging strike in the fixture.
    assert c["pitches"] == 1 and c["swings"] == 1 and c["whiffs"] == 1
    # And PID's counts do not leak into OTHER_PID's.
    assert c["contact"] == 0


def test_exact_denominators():
    c = count_player_pitches(SYNTHETIC_FEED, PID)
    r = rates_from_counts(c)
    # Swing% = swings/pitches = 5/8, Whiff% = whiffs/swings = 2/5,
    # SwStr% = whiffs/pitches = 2/8.
    assert r["swing_pct"] == round(5 / 8 * 100, 1)
    assert r["whiff_pct"] == round(2 / 5 * 100, 1)
    assert r["swstr_pct"] == round(2 / 8 * 100, 1)


def test_zone_classify_real_coords():
    in_zone = {"coordinates": {"pX": 0.1, "pZ": 2.5}, "strikeZoneTop": 3.4, "strikeZoneBottom": 1.6}
    out_zone = {"coordinates": {"pX": 1.6, "pZ": 2.5}, "strikeZoneTop": 3.4, "strikeZoneBottom": 1.6}
    assert classify_zone(in_zone) is True
    assert classify_zone(out_zone) is False


def test_zone_classify_missing_coords_is_none():
    # No coordinates at all -> excluded from zone denominators (None), never guessed.
    assert classify_zone({}) is None
    assert classify_zone({"coordinates": {}}) is None
    # Pixel-only coords but no calibration passed -> still None (needs a calib).
    assert classify_zone({"coordinates": {"x": 118.0, "y": 150.0}}) is None


def test_rate_none_on_zero_denominator():
    # A batter with zero swings: whiff_pct (whiffs/swings) must be None, not 0.0.
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Ball"}},
    ]}]
    r = rates_from_counts(count_player_pitches(play, PID))
    assert r["whiff_pct"] is None
    assert r["chase_pct"] is None   # no out-of-zone pitches counted
    assert r["swing_pct"] == 0.0    # 0 swings / 1 pitch is a real 0%, not None


def test_multi_game_aggregation_is_exact():
    c1 = count_player_pitches(SYNTHETIC_FEED, PID)
    c2 = count_player_pitches(SECOND_GAME_FEED, PID)
    merged = merge_counts(c1, c2)
    # Summed counts, then divide once == treating both games as one combined stream.
    combined_feed = SYNTHETIC_FEED + SECOND_GAME_FEED
    direct = count_player_pitches(combined_feed, PID)
    assert merged == direct
    # Rates from summed counts are the exact combined rates.
    r = rates_from_counts(merged)
    assert r["swstr_pct"] == round(direct["whiffs"] / direct["pitches"] * 100, 1)


def test_pixel_calibration_zone_counts_with_calib():
    # Fit a trivial identity-ish calibration from paired (x,y,pX,pZ) samples, then
    # confirm pixel-only pitches get zone-classified through it.
    pairs = [
        (118.0, 150.0, 0.0, 2.5),
        (200.0, 150.0, 1.6, 2.5),
        (100.0, 120.0, -0.4, 3.0),
        (160.0, 180.0, 0.8, 2.0),
    ]
    calib, quality = fit_pixel_calibration(pairs)
    assert calib is not None
    assert quality["n_pairs"] == 4
    c = count_player_pitches(PIXEL_ONLY_EVENTS, PID, calib=calib)
    # 3 pitches: a foul near-center (in-zone swing), a ball far outside (out-of-zone,
    # no swing), a called strike with no coords (excluded from zone denominators).
    assert c["zone_pitches_with_coords"] == 2
    assert c["in_zone"] >= 1
    assert c["out_zone"] >= 1
    assert c["z_swings"] >= 1     # the foul was a swing on an in-zone pixel pitch


def test_missing_strike_zone_uses_fallback_band_and_flags_quality():
    calib = PixelCalibration(a=0.02, b=-2.36, c=-0.01, d=4.0)
    c = count_player_pitches(MISSING_SZ_EVENTS, PID, calib=calib)
    # The single pixel pitch had no strikeZoneTop/Bottom -> classified via the
    # default band, and counted toward the fallback-quality denominator.
    assert c["zone_pitches_with_coords"] == 1
    assert c["zone_pitches_fallback_sz"] == 1


def test_calibration_agreement_high_on_consistent_pairs():
    pairs = [
        (118.0, 150.0, 0.0, 2.5),
        (200.0, 150.0, 1.6, 2.5),
        (100.0, 120.0, -0.4, 3.0),
        (160.0, 180.0, 0.8, 2.0),
        (130.0, 160.0, 0.2, 2.3),
    ]
    calib, _ = fit_pixel_calibration(pairs)
    agree = calibration_agreement(pairs, calib, sz_top=3.4, sz_bottom=1.6)
    assert agree is not None and agree >= 80.0
