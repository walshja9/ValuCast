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
    calibration_agreement_bands,
    PixelCalibration,
)


def test_swing_and_whiff_detection_over_taxonomy():
    c = count_player_pitches(SYNTHETIC_FEED, PID)
    # 9 pitches to PID; swinging strike + foul + foul bunt + missed bunt +
    # swinging pitchout + in-play = 6 swings; swinging strike + missed bunt +
    # swinging pitchout = 3 whiffs; the rest contact.
    assert c["pitches"] == 9
    assert c["swings"] == 6
    assert c["whiffs"] == 3
    assert c["contact"] == 3


def test_foul_is_swing_but_not_whiff():
    # A single foul: swing + contact, never a whiff.
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Foul"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["swings"] == 1 and c["whiffs"] == 0 and c["contact"] == 1


def test_foul_tip_is_whiff():
    # Savant convention (owner decision on audit F1): a caught foul tip is by
    # rule a swinging strike — swing + whiff, never contact. This matches the
    # AAA Statcast layer so the one "Whiff%" label carries one numerator.
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Foul Tip"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["swings"] == 1 and c["whiffs"] == 1 and c["contact"] == 0


def test_bunt_foul_tip_is_whiff():
    # The bunt member of the foul-tip family follows the same rule.
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Foul Tip Bunt"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["swings"] == 1 and c["whiffs"] == 1 and c["contact"] == 0


def test_foul_pitchout_is_contact_not_whiff():
    # A foul off a pitchout is ordinary foul contact; only a SWINGING pitchout
    # is a whiff.
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Foul Pitchout"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["swings"] == 1 and c["whiffs"] == 0 and c["contact"] == 1


def test_foul_tip_is_not_zone_contact():
    # An in-zone foul tip counts z_swings but NOT z_contact (whiff branch).
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Foul Tip"},
         "pitchData": {"coordinates": {"pX": 0.1, "pZ": 2.5},
                       "strikeZoneTop": 3.4, "strikeZoneBottom": 1.6}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["z_swings"] == 1 and c["z_contact"] == 0


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
    # Swing% = swings/pitches = 6/9, Whiff% = whiffs/swings = 3/6,
    # SwStr% = whiffs/pitches = 3/9.
    assert r["swing_pct"] == round(6 / 9 * 100, 1)
    assert r["whiff_pct"] == round(3 / 6 * 100, 1)
    assert r["swstr_pct"] == round(3 / 9 * 100, 1)


def test_pitchout_taxonomy():
    # A plain Pitchout is a pitch seen but NOT a swing; a Swinging Pitchout is a
    # swing AND a whiff (the batter offered at the pitchout and missed).
    play = [{"matchup": {"batter": {"id": PID}}, "playEvents": [
        {"isPitch": True, "details": {"description": "Pitchout"}},
        {"isPitch": True, "details": {"description": "Swinging Pitchout"}},
    ]}]
    c = count_player_pitches(play, PID)
    assert c["pitches"] == 2
    assert c["swings"] == 1
    assert c["whiffs"] == 1
    assert c["contact"] == 0


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
    # Both zone calls came from the pixel calibration (no real pX/pZ here) — the
    # per-pitch counter behind the level's zone_estimated flag.
    assert c["zone_pitches_calibrated"] == 2


def test_real_coords_pitches_not_counted_as_calibrated():
    # SYNTHETIC_FEED's coordinate-bearing pitches all carry real pX/pZ + sz, so
    # NONE of their zone calls are pixel-calibrated (zone_estimated stays honest
    # even in mixed-coordinate games).
    c = count_player_pitches(SYNTHETIC_FEED, PID)
    assert c["zone_pitches_with_coords"] == 4
    assert c["zone_pitches_calibrated"] == 0


def test_missing_strike_zone_uses_fallback_band_and_flags_quality():
    calib = PixelCalibration(a=0.02, b=-2.36, c=-0.01, d=4.0)
    c = count_player_pitches(MISSING_SZ_EVENTS, PID, calib=calib)
    # The single pixel pitch had no strikeZoneTop/Bottom -> classified via the
    # default band, and counted toward the fallback-quality denominator.
    assert c["zone_pitches_with_coords"] == 1
    assert c["zone_pitches_fallback_sz"] == 1


def test_calibration_agreement_high_on_consistent_pairs():
    # 6-tuples: (x, y, pX, pZ, szTop, szBottom) — each pair's OWN strike zone
    # scores both the real-coords truth and the calibrated call.
    pairs = [
        (118.0, 150.0, 0.0, 2.5, 3.4, 1.6),
        (200.0, 150.0, 1.6, 2.5, 3.4, 1.6),
        (100.0, 120.0, -0.4, 3.0, 3.5, 1.7),
        (160.0, 180.0, 0.8, 2.0, 3.3, 1.5),
        (130.0, 160.0, 0.2, 2.3, 3.4, 1.6),
    ]
    calib, _ = fit_pixel_calibration(pairs)
    agree = calibration_agreement(pairs, calib)
    assert agree is not None and agree >= 80.0


def test_calibration_agreement_bands_partition_by_edge_distance():
    # Banded agreement (audit F3): borderline pitches are where the pixel
    # calibration is weakest, so agreement is also scored on the subsets of
    # held-out pairs whose REAL location is within 3in / 1in of the zone edge.
    # Identity calibration: pixel coords == feet, so every call agrees.
    calib = PixelCalibration(a=1.0, b=0.0, c=1.0, d=0.0)
    pairs = [
        (0.0, 2.5, 0.0, 2.5, 3.4, 1.6),    # dead center: > 3in from any edge
        (0.80, 2.5, 0.80, 2.5, 3.4, 1.6),  # 0.03 ft = 0.36in from the side edge
        (0.0, 3.25, 0.0, 3.25, 3.4, 1.6),  # 0.15 ft = 1.8in from the top edge
    ]
    bands = calibration_agreement_bands(pairs, calib)
    assert bands["overall"]["n"] == 3
    assert bands["overall"]["agreement_pct"] == 100.0
    assert bands["within_3in"]["n"] == 2
    assert bands["within_3in"]["agreement_pct"] == 100.0
    assert bands["within_1in"]["n"] == 1
    assert bands["within_1in"]["agreement_pct"] == 100.0


def test_calibration_agreement_bands_catch_edge_disagreement():
    # A calibration shifted +0.1 ft in pX flips only the near-edge call: the
    # overall number stays presentable while the 1-inch band exposes the miss.
    calib = PixelCalibration(a=1.0, b=0.1, c=1.0, d=0.0)
    pairs = [
        (0.0, 2.5, 0.0, 2.5, 3.4, 1.6),    # est 0.10, real 0.0 -> both in: agree
        (0.80, 2.5, 0.80, 2.5, 3.4, 1.6),  # est 0.90 out, real 0.80 in: disagree
    ]
    bands = calibration_agreement_bands(pairs, calib)
    assert bands["overall"]["agreement_pct"] == 50.0
    assert bands["within_1in"]["n"] == 1
    assert bands["within_1in"]["agreement_pct"] == 0.0


def test_calibration_agreement_bands_empty_pairs():
    calib = PixelCalibration(a=1.0, b=0.0, c=1.0, d=0.0)
    bands = calibration_agreement_bands([], calib)
    assert bands["overall"] == {"n": 0, "agreement_pct": None}
    assert bands["within_1in"]["agreement_pct"] is None


def test_calibration_agreement_uses_per_pair_strike_zone():
    # Identity-ish calibration so pixel == feet. A pitch at pZ=3.0 is IN a tall
    # zone (top 3.4) but OUT of a short zone (top 2.8). Agreement must score each
    # pair against its OWN zone: with matching per-pair zones both cases agree.
    from prospects.pitch_discipline import PixelCalibration
    calib = PixelCalibration(a=1.0, b=0.0, c=1.0, d=0.0)
    pairs = [
        (0.0, 3.0, 0.0, 3.0, 3.4, 1.6),   # in tall zone -> both sides say in
        (0.0, 3.0, 0.0, 3.0, 2.8, 1.6),   # out of short zone -> both sides say out
    ]
    assert calibration_agreement(pairs, calib) == 100.0
