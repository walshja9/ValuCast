"""Schema-validator tests for the plate-discipline artifact.

Exercises scripts/validate_pitch_discipline.py against fixture artifacts so the
validator (wired into the daily VALIDATE_STEPS) is itself covered, independent of
whether the committed artifact has been built yet.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validate_pitch_discipline import validate_file


def _good_payload():
    return {
        "artifact": "valucast_pitch_discipline",
        "generated_at": "2026-07-10T00:00:00+00:00",
        "as_of": "2026-07-10",
        "source_policy": {
            "observe_only": True, "feeds_value": False, "feeds_rank": False,
            "exit_velocity": False,
        },
        "cohorts": {
            "min_pitches": 300,
            "cohort_sizes": {"AA": 2},
            "zone_metrics_shipped": True,
            "calibration": {
                "a": 0.02, "b": -2.3, "c": -0.01, "d": 4.0,
                "held_out_agreement_pct": 97.7, "agreement_floor_pct": 85.0,
            },
        },
        "players": {
            "701527": {"AA": {
                "pitches": 811, "qualifies": True, "zone_estimated": True,
                "rates": {"swing_pct": 37.4, "whiff_pct": 24.8, "swstr_pct": 9.2,
                          "chase_pct": 15.8, "z_swing_pct": 64.3,
                          "z_contact_pct": 80.6, "zone_pct": 44.5},
                "percentiles": {"whiff_pct": 75},
            }},
        },
    }


def _write(tmp_path, payload):
    path = tmp_path / "disc.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_valid_artifact_passes(tmp_path):
    path = _write(tmp_path, _good_payload())
    payload, problems, present = validate_file(path)
    assert present is True
    assert problems == []


def test_absent_artifact_is_ok(tmp_path):
    payload, problems, present = validate_file(tmp_path / "missing.json")
    assert present is False
    assert problems == []


def test_wrong_artifact_key_fails(tmp_path):
    bad = _good_payload()
    bad["artifact"] = "something_else"
    payload, problems, present = validate_file(_write(tmp_path, bad))
    assert any("artifact must be" in p for p in problems)


def test_exit_velocity_must_be_false(tmp_path):
    bad = _good_payload()
    bad["source_policy"]["exit_velocity"] = True
    payload, problems, present = validate_file(_write(tmp_path, bad))
    assert any("exit_velocity" in p for p in problems)


def test_sub_floor_bucket_with_percentiles_fails(tmp_path):
    bad = _good_payload()
    bad["players"]["701527"]["AA"]["pitches"] = 100   # below floor
    bad["players"]["701527"]["AA"]["percentiles"] = {"whiff_pct": 75}
    payload, problems, present = validate_file(_write(tmp_path, bad))
    assert any("below floor but has percentiles" in p for p in problems)


def test_zone_shipped_requires_calibration_coeffs(tmp_path):
    bad = _good_payload()
    bad["cohorts"]["calibration"] = {"held_out_agreement_pct": 97.7,
                                     "agreement_floor_pct": 85.0}
    payload, problems, present = validate_file(_write(tmp_path, bad))
    assert any("calibration.a required" in p for p in problems)


def test_zone_estimated_must_be_bool(tmp_path):
    bad = _good_payload()
    bad["players"]["701527"]["AA"]["zone_estimated"] = "yes"
    payload, problems, present = validate_file(_write(tmp_path, bad))
    assert any("zone_estimated must be bool" in p for p in problems)
