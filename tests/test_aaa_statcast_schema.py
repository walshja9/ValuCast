"""Schema-validator + self-arming staleness-gate tests for the AAA-Statcast artifact.

Exercises scripts/validate_aaa_statcast_features.py against fixture artifacts so the
validator (wired into the daily VALIDATE_STEPS) is itself covered, independent of
whether the committed artifact has been rebuilt yet. Mirrors
tests/test_pitch_discipline_schema.py.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_aaa_statcast_features import (
    DEFAULT_MAX_AGE_DAYS,
    FRESHNESS_REGIME,
    HARD_MAX_AGE_DAYS,
    _staleness_problem,
    validate_file,
)


def _good_payload(**extra):
    payload = {
        "artifact": "valucast_aaa_statcast_features",
        "schema_version": 1,
        "generated_at": "2026-07-14T20:19:20+00:00",
        "as_of": "2026-07-14",
        "season": 2026,
        "source": "baseball_savant_statcast_minors_aaa",
        "source_policy": {
            "kind": "valucast_aaa_statcast_features",
            "level": "AAA",
            "measured": True,
            "observe_only": True,
            "feeds_value": False,
            "feeds_rank": False,
        },
        "gates": {"min_pitcher_pitches": 200},
        "pitchers": {
            "803349": {
                "n_pitches": 900,
                "overall": {"whiff_pct": 28.0, "csw_pct": 30.5},
                "pitch_types": {
                    "FF": {"n": 400, "velo": 95.2, "ivb": 16.9, "hb": 8.1,
                           "spin": 2320, "ext": 6.4},
                },
            },
        },
        "hitters": {
            "699024": {
                "n_pitches": 700, "n_bip": 120, "ev_n": 110,
                "avg_ev": 90.4, "hardhit_pct": 47.5,
            },
        },
    }
    payload.update(extra)
    return payload


def _write(tmp_path, payload):
    path = tmp_path / "aaa.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


# --- schema ------------------------------------------------------------------
def test_valid_artifact_passes(tmp_path):
    payload, problems, present = validate_file(_write(tmp_path, _good_payload()))
    assert present is True
    assert problems == []


def test_absent_artifact_is_ok(tmp_path):
    payload, problems, present = validate_file(tmp_path / "missing.json")
    assert present is False
    assert problems == []


def test_ev_n_optional_but_int_when_present(tmp_path):
    # Legacy artifacts (built before 2026-07-30) lack ev_n entirely: OK.
    legacy = _good_payload()
    del legacy["hitters"]["699024"]["ev_n"]
    _, problems, _ = validate_file(_write(tmp_path, legacy))
    assert problems == []

    # When present it must be an int.
    bad = _good_payload()
    bad["hitters"]["699024"]["ev_n"] = "110"
    _, problems, _ = validate_file(_write(tmp_path, bad))
    assert any("ev_n must be an int" in p for p in problems)


# --- staleness gate: three regimes -------------------------------------------
def _stamped(as_of):
    return {"as_of": as_of, "freshness_regime": FRESHNESS_REGIME}


def test_legacy_no_stamp_under_hard_bound_passes():
    # The committed pre-fix artifact (as_of 2026-07-14, 16 days old on
    # 2026-07-30) must PASS: the tight bound only arms once the stamp appears.
    payload = {"as_of": "2026-07-14"}
    assert _staleness_problem(payload, "2026-07-30", DEFAULT_MAX_AGE_DAYS) is None


def test_legacy_no_stamp_over_hard_bound_fails():
    # A never-recovering pipeline still fails closed at the 30-day hard bound.
    payload = {"as_of": "2026-07-14"}
    old_day = "2026-08-14"  # 31 days later
    problem = _staleness_problem(payload, old_day, DEFAULT_MAX_AGE_DAYS)
    assert problem is not None
    assert f"hard limit {HARD_MAX_AGE_DAYS}" in problem


def test_stamped_over_tight_bound_fails():
    # Once armed (stamp present), the tight bound applies.
    problem = _staleness_problem(_stamped("2026-07-14"), "2026-07-30", 3)
    assert problem is not None
    assert "16 days old" in problem
    assert "allowed 3" in problem


def test_stamped_fresh_passes():
    assert _staleness_problem(_stamped("2026-07-28"), "2026-07-30", 3) is None
    assert _staleness_problem(_stamped("2026-07-30"), "2026-07-30", 3) is None


def test_future_dated_fails_in_both_regimes():
    assert "future" in _staleness_problem({"as_of": "2026-08-01"}, "2026-07-30", 3)
    assert "future" in _staleness_problem(_stamped("2026-08-01"), "2026-07-30", 3)


def test_stamped_cannot_outrun_hard_bound_via_override():
    # Even with --max-age-days / env raised past 30, the hard bound still holds.
    problem = _staleness_problem(_stamped("2026-06-01"), "2026-07-30", 100)
    assert problem is not None
    assert f"hard limit {HARD_MAX_AGE_DAYS}" in problem


def test_staleness_edge_inputs():
    assert _staleness_problem({}, "2026-07-30", 3) is None  # missing as_of: schema's job
    bad = _staleness_problem({"as_of": "not-a-date"}, "2026-07-30", 3)
    assert bad is not None and "not an ISO date" in bad
