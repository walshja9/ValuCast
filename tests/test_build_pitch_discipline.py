"""Number-producing build-logic tests for scripts/build_pitch_discipline.py.

Covers the cohort-percentile math (orientation + midrank), the hard min-pitch
gate's pool exclusion, the deterministic calibration train/held split, and the
per-pitch zone_estimated derivation — all offline (no network, no repo data).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prospects.pitch_discipline import PixelCalibration
from scripts.build_pitch_discipline import (
    MIN_PITCHES,
    _split_pairs,
    assemble_player_levels,
    compute_cohort_percentiles,
)


def _bucket(pitches, **rates):
    base = {
        "swing_pct": 40.0, "whiff_pct": 20.0, "swstr_pct": 8.0,
        "chase_pct": 25.0, "z_swing_pct": 60.0, "z_contact_pct": 80.0,
        "zone_pct": 45.0,
    }
    base.update(rates)
    return {"pitches": pitches, "counts": {}, "rates": base, "zone_estimated": True}


def test_cohort_percentiles_orientation():
    # Three qualifying AA hitters with known whiff (LOWER_IS_BETTER) and
    # z_contact (higher-is-better) values.
    player_levels = {
        "1": {"AA": _bucket(400, whiff_pct=10.0, z_contact_pct=90.0)},
        "2": {"AA": _bucket(400, whiff_pct=20.0, z_contact_pct=80.0)},
        "3": {"AA": _bucket(400, whiff_pct=30.0, z_contact_pct=70.0)},
    }
    out, cohorts = compute_cohort_percentiles(player_levels)
    # LOWER_IS_BETTER inverts: the LOWEST whiff gets the HIGHEST percentile.
    assert out["1"]["AA"]["percentiles"]["whiff_pct"] == 83
    assert out["2"]["AA"]["percentiles"]["whiff_pct"] == 50
    assert out["3"]["AA"]["percentiles"]["whiff_pct"] == 17
    # Higher-is-better does NOT invert: the highest z_contact gets the highest pct.
    assert out["1"]["AA"]["percentiles"]["z_contact_pct"] == 83
    assert out["3"]["AA"]["percentiles"]["z_contact_pct"] == 17
    # Contextual metrics (no defensible quality direction) get NO percentile.
    assert "swing_pct" not in out["1"]["AA"]["percentiles"]
    assert "zone_pct" not in out["1"]["AA"]["percentiles"]
    assert cohorts["min_pitches"] == MIN_PITCHES
    assert cohorts["cohort_sizes"] == {"AA": 3}


def test_sub_floor_bucket_gated_and_excluded_from_pool():
    # Player 4 is below the floor with an EXTREME whiff value: if he leaked into
    # the pool, player 1's percentile would shift (83 -> 63). He must not.
    player_levels = {
        "1": {"AA": _bucket(400, whiff_pct=10.0)},
        "2": {"AA": _bucket(400, whiff_pct=20.0)},
        "3": {"AA": _bucket(400, whiff_pct=30.0)},
        "4": {"AA": _bucket(MIN_PITCHES - 1, whiff_pct=5.0)},
    }
    out, cohorts = compute_cohort_percentiles(player_levels)
    assert out["4"]["AA"]["qualifies"] is False
    assert out["4"]["AA"]["percentiles"] == {}
    assert cohorts["cohort_sizes"] == {"AA": 3}          # pool excludes player 4
    assert out["1"]["AA"]["percentiles"]["whiff_pct"] == 83  # unchanged by player 4


def test_split_pairs_deterministic_and_disjoint():
    pairs = [(i,) for i in range(10)]
    train, held = _split_pairs(pairs)
    # i % 5 == 0 -> held: indices 0 and 5.
    assert held == [(0,), (5,)]
    assert len(train) == 8
    assert set(train).isdisjoint(held)
    assert set(train) | set(held) == set(pairs)
    # Deterministic: a second call produces the identical split.
    train2, held2 = _split_pairs(pairs)
    assert train == train2 and held == held2


def _pitch(desc, **kw):
    p = {"description": desc, "isInPlay": kw.pop("is_in_play", False),
         "pX": None, "pZ": None, "x": None, "y": None,
         "szTop": None, "szBottom": None}
    p.update(kw)
    return p


def test_zone_estimated_derived_per_pitch_not_per_game():
    # One game whose plays MIX real-coords and pixel-only pitches for player 1,
    # while player 2 sees only real-coords pitches in the same game. The old
    # per-game heuristic would have labeled both players "measured"; the per-pitch
    # counter labels player 1 estimated and player 2 measured.
    calib = PixelCalibration(a=1.0, b=0.0, c=1.0, d=0.0)  # identity: pixel==feet
    cache = {"games": {"100": {"level": "AAA", "season": 2026, "plays": [
        {"batter": 1, "pitches": [
            _pitch("Ball", pX=0.1, pZ=2.5, szTop=3.4, szBottom=1.6),   # real coords
            _pitch("Ball", x=0.2, y=2.5, szTop=3.4, szBottom=1.6),     # pixel only
        ]},
        {"batter": 2, "pitches": [
            _pitch("Ball", pX=0.1, pZ=2.5, szTop=3.4, szBottom=1.6),   # real coords
        ]},
    ]}}}
    hitters = [{"mlbam_id": 1}, {"mlbam_id": 2}]
    out = assemble_player_levels(hitters, cache, calib)
    assert out["1"]["AAA"]["zone_estimated"] is True    # a pixel call happened
    assert out["2"]["AAA"]["zone_estimated"] is False   # all zone calls measured


def test_incremental_without_ready_marker_keeps_prior_artifact(tmp_path, monkeypatch, capsys):
    # Readiness guard: a missing marker means the cache is absent or a partial
    # bootstrap checkpoint; an incremental run must preserve the prior artifact
    # (exit 0, no fetch, no artifact write) rather than build a deceptively
    # fresh one from incomplete data.
    from scripts import build_pitch_discipline as bpd

    monkeypatch.setattr(bpd, "READY_MARKER_PATH", tmp_path / ".ready-missing")
    monkeypatch.setattr(
        bpd, "load_tracked_hitters", lambda: [{"mlbam_id": 1, "name": "X", "level": "AA"}]
    )
    monkeypatch.setattr(
        bpd, "load_cache", lambda *a, **k: {"games": {"1": {}}}
    )

    def _boom(*a, **k):  # any fetch or write attempt is a guard failure
        raise AssertionError("guard must prevent fetch/build without marker")

    monkeypatch.setattr(bpd, "gather_games", _boom)
    monkeypatch.setattr(bpd, "build_artifact", _boom)
    monkeypatch.setattr(bpd, "write_artifact", _boom)

    assert bpd.main([]) == 0
    out = capsys.readouterr().out
    assert "not marked ready" in out
    assert "keeping prior artifact" in out


def test_incremental_with_ready_marker_proceeds(tmp_path, monkeypatch):
    from scripts import build_pitch_discipline as bpd

    marker = tmp_path / ".ready"
    marker.write_text("", encoding="utf-8")
    monkeypatch.setattr(bpd, "READY_MARKER_PATH", marker)
    monkeypatch.setattr(
        bpd, "load_tracked_hitters", lambda: [{"mlbam_id": 1, "name": "X", "level": "AA"}]
    )
    monkeypatch.setattr(bpd, "load_cache", lambda *a, **k: {"games": {"1": {}}})

    calls = {}

    def _gather(*a, **k):
        calls["gather"] = True
        raise RuntimeError("stop after reaching the fetch stage")

    monkeypatch.setattr(bpd, "gather_games", _gather)

    # The incremental error backstop keeps the prior artifact and exits 0 —
    # what matters here is the guard let execution REACH the fetch stage.
    assert bpd.main([]) == 0
    assert calls.get("gather") is True
