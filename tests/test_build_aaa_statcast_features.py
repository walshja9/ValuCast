"""Aggregation-math tests for scripts/build_aaa_statcast_features.py (offline)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scripts.build_aaa_statcast_features as b


def _pitch(pitcher="P1", batter="H1", **kw):
    base = {
        "pitcher": pitcher, "batter": batter, "pitch_type": None,
        "release_speed": None, "pfx_x": None, "pfx_z": None,
        "release_spin_rate": None, "release_extension": None, "spin_axis": None,
        "arm_angle": None, "plate_x": None, "plate_z": None,
        "sz_top": None, "sz_bot": None, "description": None,
        "type": None, "events": None, "bb_type": None,
        "launch_speed": None, "launch_angle": None,
    }
    base.update(kw)
    return base


def _cache(pitches):
    return {"games": {"1": {"home_team": "BUF", "game_date": "2026-07-10", "pitches": pitches}}}


# --- pitch-shape conversions -----------------------------------------------
def test_ivb_hb_inches_conversion():
    # pfx_z / pfx_x are in FEET on Savant; IVB/HB display in inches (x12).
    pitches = [
        _pitch(pitch_type="FF", release_speed=95.0, pfx_z=1.5, pfx_x=0.5,
               release_spin_rate=2400, release_extension=6.5)
        for _ in range(b.MIN_PITCH_TYPE)
    ]
    rows = b._pitch_type_rows({"FF": _accum_type(pitches)}, len(pitches))
    ff = rows["FF"]
    assert ff["ivb"] == 18.0   # 1.5 ft * 12
    assert ff["hb"] == 6.0     # 0.5 ft * 12
    assert ff["velo"] == 95.0
    assert ff["spin"] == 2400
    assert ff["ext"] == 6.5
    assert ff["usage_pct"] == 100.0


def _accum_type(pitches):
    """Reproduce the builder's per-type accumulation for a homogeneous list."""
    row = {"n": 0, "velo": 0.0, "velo_n": 0, "ivb": 0.0, "ivb_n": 0,
           "hb": 0.0, "hb_n": 0, "spin": 0.0, "spin_n": 0, "ext": 0.0, "ext_n": 0}
    for p in pitches:
        row["n"] += 1
        b._add(row, "velo", p.get("release_speed"))
        b._add(row, "ivb", p.get("pfx_z"), scale=12.0)
        b._add(row, "hb", p.get("pfx_x"), scale=12.0)
        b._add(row, "spin", p.get("release_spin_rate"))
        b._add(row, "ext", p.get("release_extension"))
    return row


# --- zone predicate --------------------------------------------------------
def test_in_zone_uses_own_sz():
    # Inside: |x|<=0.83 and sz_bot<=z<=sz_top.
    assert b._in_zone(0.0, 2.5, 3.5, 1.5) is True
    # Outside horizontally.
    assert b._in_zone(1.2, 2.5, 3.5, 1.5) is False
    # Outside vertically (above the top).
    assert b._in_zone(0.0, 3.9, 3.5, 1.5) is False
    # Missing coords -> None (no zone call).
    assert b._in_zone(None, 2.5, 3.5, 1.5) is None


# --- pitcher plate outcomes ------------------------------------------------
def test_pitcher_whiff_csw_gb_from_pitch_accumulation():
    # Build an unambiguous pitch list and accumulate it the way the builder does.
    pitches = []
    # 4 whiffs (swinging_strike) + 6 fouls -> 10 swings, whiff% = 40.0
    pitches += [_pitch(description="swinging_strike") for _ in range(4)]
    pitches += [_pitch(description="foul") for _ in range(6)]
    # 5 called strikes; CSW numerator = called + whiffs = 9.
    pitches += [_pitch(description="called_strike") for _ in range(5)]
    # 5 plain balls (no swing, no whiff, no called strike).
    pitches += [_pitch(description="ball") for _ in range(5)]
    # 3 balls in play (also swings), 1 grounder -> gb% 33.3.
    pitches.append(_pitch(description="hit_into_play", bb_type="ground_ball"))
    pitches.append(_pitch(description="hit_into_play", bb_type="fly_ball"))
    pitches.append(_pitch(description="hit_into_play", bb_type="line_drive"))
    oc = _accum_outcome(pitches)
    r = b._pitcher_rates(oc)
    # swings = 4 whiffs + 6 fouls + 3 bip = 13; whiffs = 4 -> 30.8%.
    assert r["whiff_pct"] == 30.8
    # CSW = (called 5 + whiffs 4) / 23 pitches = 39.1%.
    assert r["csw_pct"] == 39.1
    assert r["gb_pct"] == 33.3               # 1 grounder / 3 bip
    # No zone coords supplied -> no zone/chase rates.
    assert "zone_pct" not in r
    assert "chase_pct" not in r


def _accum_outcome(pitches):
    oc = {"n": 0, "swings": 0, "whiffs": 0, "called": 0, "zone": 0,
          "zone_denom": 0, "out_swings": 0, "out_pitches": 0, "bip": 0, "gb": 0}
    for p in pitches:
        oc["n"] += 1
        desc = p.get("description")
        swing = b._is_swing(desc)
        if swing:
            oc["swings"] += 1
        if b._is_whiff(desc):
            oc["whiffs"] += 1
        if desc == "called_strike":
            oc["called"] += 1
        z = b._in_zone(p.get("plate_x"), p.get("plate_z"), p.get("sz_top"), p.get("sz_bot"))
        if z is not None:
            oc["zone_denom"] += 1
            if z:
                oc["zone"] += 1
            else:
                oc["out_pitches"] += 1
                if swing:
                    oc["out_swings"] += 1
        bt = p.get("bb_type")
        if isinstance(bt, str) and bt:
            oc["bip"] += 1
            if bt == "ground_ball":
                oc["gb"] += 1
    return oc


def test_pitcher_zone_and_chase_from_real_coords():
    oc = {"n": 20, "swings": 0, "whiffs": 0, "called": 0,
          "zone": 8, "zone_denom": 20, "out_swings": 3, "out_pitches": 12,
          "bip": 0, "gb": 0}
    r = b._pitcher_rates(oc)
    assert r["zone_pct"] == 40.0    # 8 / 20
    assert r["chase_pct"] == 25.0   # 3 swings / 12 out-of-zone


# --- hitter contact quality -------------------------------------------------
def test_hitter_ev_rollups():
    pitches = []
    # 30 balls in play with known EVs -> hardhit (>=95) on 15 of them.
    evs = [96.0] * 15 + [90.0] * 15
    for ev in evs:
        pitches.append(_pitch(batter="H1", description="hit_into_play",
                              bb_type="fly_ball", launch_speed=ev, launch_angle=20.0))
    # Pad pitches so the hitter clears MIN_HITTER_PITCHES.
    for _ in range(b.MIN_HITTER_PITCHES):
        pitches.append(_pitch(batter="H1", description="ball"))
    cache = _cache(pitches)
    out = b.aggregate_hitters(cache, {"H1"})
    rec = out["H1"]
    assert rec["avg_ev"] == 93.0             # (96*15 + 90*15)/30
    assert rec["max_ev"] == 96.0
    assert rec["hardhit_pct"] == 50.0        # 15/30 >= 95
    assert rec["avg_la"] == 20.0
    assert rec["n_bip"] == 30
    assert rec["ev_n"] == 30                 # every BIP here carried launch_speed


def test_ev_n_counts_only_tracked_bbe():
    # ev_n is the REAL Hard-Hit%/avg-EV denominator: balls in play whose
    # launch_speed was tracked. Untracked BIP raise n_bip but not ev_n.
    pitches = []
    for _ in range(b.MIN_HITTER_BIP + 5):     # tracked BBE
        pitches.append(_pitch(batter="H1", description="hit_into_play",
                              bb_type="fly_ball", launch_speed=96.0))
    for _ in range(10):                        # untracked BBE (no launch_speed)
        pitches.append(_pitch(batter="H1", description="hit_into_play",
                              bb_type="ground_ball"))
    for _ in range(b.MIN_HITTER_PITCHES):
        pitches.append(_pitch(batter="H1", description="ball"))
    rec = b.aggregate_hitters(_cache(pitches), {"H1"})["H1"]
    assert rec["n_bip"] == b.MIN_HITTER_BIP + 15
    assert rec["ev_n"] == b.MIN_HITTER_BIP + 5
    # Hard-hit% denominates on ev_n, not n_bip.
    assert rec["hardhit_pct"] == 100.0


def test_hitter_ev_gated_below_min_bip():
    # A hitter with plenty of pitches but only a few balls in play: outcomes render,
    # EV metrics are omitted (below MIN_HITTER_BIP).
    pitches = [_pitch(batter="H1", description="ball") for _ in range(b.MIN_HITTER_PITCHES)]
    for _ in range(b.MIN_HITTER_BIP - 1):
        pitches.append(_pitch(batter="H1", description="hit_into_play",
                              bb_type="fly_ball", launch_speed=99.0, launch_angle=10.0))
    out = b.aggregate_hitters(_cache(pitches), {"H1"})
    rec = out["H1"]
    assert "avg_ev" not in rec
    assert "hardhit_pct" not in rec


def test_hitter_ev_excludes_fouls_carrying_launch_speed():
    # Savant populates launch_speed on routine fouls too. Contact quality must
    # count batted-ball events (bb_type present) ONLY — counting fouls tanked
    # avg EV by ~6 mph on real data before this was caught in review.
    pitches = []
    for _ in range(b.MIN_HITTER_BIP + 5):
        pitches.append(_pitch(batter="H1", description="hit_into_play",
                              bb_type="fly_ball", launch_speed=96.0, launch_angle=15.0))
    # Fouls with tracked launch_speed but NO bb_type: must not enter EV/LA/n_bip.
    for _ in range(b.MIN_HITTER_BIP + 5):
        pitches.append(_pitch(batter="H1", description="foul",
                              launch_speed=60.0, launch_angle=-30.0))
    for _ in range(b.MIN_HITTER_PITCHES):
        pitches.append(_pitch(batter="H1", description="ball"))
    rec = b.aggregate_hitters(_cache(pitches), {"H1"})["H1"]
    assert rec["avg_ev"] == 96.0             # fouls excluded; buggy value ~78.0
    assert rec["hardhit_pct"] == 100.0
    assert rec["avg_la"] == 15.0
    assert rec["n_bip"] == b.MIN_HITTER_BIP + 5


def test_foul_tip_counts_as_whiff():
    # A caught foul tip is by rule a swinging strike; Savant's CSW includes it
    # (fouls excluded, foul tips included). It is both a whiff and a swing.
    pitches = []
    pitches += [_pitch(description="swinging_strike") for _ in range(10)]
    pitches += [_pitch(description="foul_tip") for _ in range(10)]
    pitches += [_pitch(description="foul") for _ in range(20)]
    pitches += [_pitch(description="called_strike") for _ in range(20)]
    pitches += [_pitch(description="ball") for _ in range(140)]
    oc = _accum_outcome(pitches)
    r = b._pitcher_rates(oc)
    # swings = 10 ss + 10 tips + 20 fouls = 40; whiffs = 20 -> 50.0 (25.0 if
    # foul_tip were treated as contact — the pre-review bug).
    assert r["whiff_pct"] == 50.0
    # CSW = (20 called + 20 whiffs) / 200 = 20.0.
    assert r["csw_pct"] == 20.0


# --- gates + scoping --------------------------------------------------------
def test_pitcher_below_gate_omitted():
    pitches = [_pitch(pitcher="P1", description="ball") for _ in range(b.MIN_PITCHER_PITCHES - 1)]
    assert b.aggregate_pitchers(_cache(pitches), {"P1"}) == {}


def test_universe_scoping_excludes_untracked():
    # P2 is not in the universe id set -> never aggregated even with a huge sample.
    pitches = [_pitch(pitcher="P2", description="ball") for _ in range(b.MIN_PITCHER_PITCHES + 50)]
    assert b.aggregate_pitchers(_cache(pitches), {"P1"}) == {}


def test_pitch_type_below_gate_omitted_but_others_kept():
    pitches = []
    for _ in range(b.MIN_PITCH_TYPE + 5):
        pitches.append(_pitch(pitch_type="FF", release_speed=95.0, pfx_z=1.5))
    for _ in range(b.MIN_PITCH_TYPE - 1):   # below the per-type gate
        pitches.append(_pitch(pitch_type="CH", release_speed=85.0, pfx_z=0.8))
    rows = b._pitch_type_rows(
        {"FF": _accum_type([p for p in pitches if p["pitch_type"] == "FF"]),
         "CH": _accum_type([p for p in pitches if p["pitch_type"] == "CH"])},
        len(pitches),
    )
    assert "FF" in rows and "CH" not in rows


# --- tiny-refresh guard -----------------------------------------------------
def test_tiny_refresh_guard_blocks_shrink(tmp_path):
    path = tmp_path / "art.json"
    healthy = {"pitchers": {str(i): {} for i in range(20)}, "hitters": {}}
    path.write_text(json.dumps(healthy), encoding="utf-8")
    tiny = {"pitchers": {"1": {}}, "hitters": {}}
    try:
        b._assert_not_tiny_refresh(tiny, path)
        assert False, "expected tiny-refresh guard to raise"
    except ValueError as exc:
        assert "tiny" in str(exc).lower()


def test_tiny_refresh_guard_allows_first_write(tmp_path):
    # No prior artifact -> the guard is a no-op.
    b._assert_not_tiny_refresh({"pitchers": {"1": {}}, "hitters": {}}, tmp_path / "nope.json")


def test_tiny_refresh_guard_override_env(tmp_path, monkeypatch):
    path = tmp_path / "art.json"
    path.write_text(json.dumps({"pitchers": {str(i): {} for i in range(20)}, "hitters": {}}),
                    encoding="utf-8")
    monkeypatch.setenv("VALUCAST_SKIP_AAA_STATCAST_TINY_GUARD", "1")
    # Should not raise despite a drastic shrink.
    b._assert_not_tiny_refresh({"pitchers": {"1": {}}, "hitters": {}}, path)


# --- artifact envelope ------------------------------------------------------
def test_build_artifact_envelope(tmp_path):
    universe = tmp_path / "universe.json"
    universe.write_text(json.dumps({
        "players": [
            {"mlbam_id": 1001, "role": "pitcher"},
            {"mlbam_id": 2001, "role": "hitter"},
        ]
    }), encoding="utf-8")
    pitches = [_pitch(pitcher="1001", description="swinging_strike")
               for _ in range(b.MIN_PITCHER_PITCHES + 10)]
    art = b.build_artifact(_cache(pitches), 2026, universe_path=universe)
    assert art["artifact"] == "valucast_aaa_statcast_features"
    assert art["schema_version"] == 1
    # Self-arming staleness stamp: every fresh build carries the regime marker
    # that arms the validator's tight bound (legacy artifacts lack it).
    assert art["freshness_regime"] == "cache_bootstrap_v1"
    assert art["source_policy"]["observe_only"] is True
    assert art["source_policy"]["measured"] is True
    assert art["source_policy"]["feeds_value"] is False
    assert art["source_policy"]["feeds_rank"] is False
    assert art["source_policy"]["level"] == "AAA"
    assert "1001" in art["pitchers"]
    assert art["counts"]["pitchers"] == 1


# ---------------------------------------------------------------------------
# as_of honesty + no-advance rebuild refusal (freshness-bypass fix)
# ---------------------------------------------------------------------------
def _coverage_cache(day="2026-07-20"):
    return {
        "checked_through": day,
        "games": {"pk1": {"game_date": day, "home_team": "LHV", "season": 2026,
                          "pitches": []}},
    }


def test_artifact_as_of_is_cache_coverage_not_build_date():
    from scripts.build_aaa_statcast_features import build_artifact

    payload = build_artifact(_coverage_cache("2026-07-20"), 2026)
    # A rebuild from an old cache must carry the old coverage date, never
    # today's date — otherwise the staleness gate is bypassed (2026-07-30
    # owner review of PR #34).
    assert payload["as_of"] == "2026-07-20"


def test_builder_refuses_rebuild_when_coverage_did_not_advance(tmp_path, monkeypatch):
    import scripts.build_aaa_statcast_features as b

    out = tmp_path / "art.json"
    out.write_text(json.dumps({
        "artifact": "valucast_aaa_statcast_features",
        "freshness_regime": "cache_bootstrap_v1",
        "as_of": "2026-07-20",
        "pitchers": {}, "hitters": {"h": {"n_pitches": 1}},
    }), encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(_coverage_cache("2026-07-20")), encoding="utf-8")

    rc = b.main(["--cache-path", str(cache_path), "--out", str(out)])

    assert rc == 0
    kept = json.loads(out.read_text(encoding="utf-8"))
    assert kept["as_of"] == "2026-07-20"
    assert "generated_at" not in kept or kept.get("hitters") == {"h": {"n_pitches": 1}}


def test_builder_allows_equal_coverage_rebuild_when_schema_stamp_missing(tmp_path):
    import scripts.build_aaa_statcast_features as b

    out = tmp_path / "art.json"
    out.write_text(json.dumps({
        "artifact": "valucast_aaa_statcast_features",
        "as_of": "2026-07-20",  # legacy: no freshness_regime stamp
        "pitchers": {}, "hitters": {},
    }), encoding="utf-8")
    cache_path = tmp_path / "cache.json"
    cache_path.write_text(json.dumps(_coverage_cache("2026-07-20")), encoding="utf-8")

    rc = b.main(["--cache-path", str(cache_path), "--out", str(out)])

    assert rc == 0
    rebuilt = json.loads(out.read_text(encoding="utf-8"))
    # Schema-upgrade exception: equal coverage may rebuild ONCE to gain the
    # stamp (and ev_n fields); afterwards the no-advance refusal applies.
    assert rebuilt.get("freshness_regime") == "cache_bootstrap_v1"
    assert rebuilt["as_of"] == "2026-07-20"
