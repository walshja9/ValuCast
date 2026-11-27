import json

from prospects.peak_calibration import build_peak_calibration_report
from prospects.peak_calibration import run_peak_calibration_report
from scripts.validate_prospect_peak_calibration_report import (
    validate_peak_calibration_report,
)


def _projection(rank, role="hitter", level="AA", risk="medium", confidence="medium", peak_score=60.0):
    return {
        "name": f"Prospect {rank}",
        "rank_v1_rank": rank,
        "rank_v1_score": 50.0,
        "peak_score": peak_score,
        "role": role,
        "level": level,
        "risk_band": risk,
        "confidence": confidence,
        "card_v2": {
            "score_delta": 10.0,
            "role_probabilities": {"regular_or_better": 0.4},
        },
    }


def _peak_payload(rows):
    return {
        "artifact": "valucast_prospect_peak_projection_v1",
        "projection_version": "1.0.0",
        "generated_at": "2026-06-16T00:00:00+00:00",
        "projections": rows,
    }


def test_peak_calibration_groups_projection_rows_by_bucket():
    payload = build_peak_calibration_report(
        _peak_payload([
            _projection(1),
            _projection(2),
            _projection(3, role="pitcher", level="AAA", risk="high", confidence="low"),
        ])
    )

    assert payload["artifact"] == "valucast_prospect_peak_projection_calibration"
    assert payload["source_policy"]["public_scouting_grades_used"] is False
    assert payload["source_policy"]["feeds_live_rank"] is False
    assert payload["summary"]["projection_count"] == 3
    assert payload["summary"]["bucket_count"] == 2
    assert payload["validation"]["ready_for_review"] is True
    first = payload["buckets"][0]
    assert first["role"] == "hitter"
    assert first["level_band"] == "upper_minors"
    assert first["avg_delta"] == 10.0


def test_negative_delta_counts_all_negatives_and_big_cut():
    payload = build_peak_calibration_report(
        _peak_payload([
            _projection(1, peak_score=48.0),  # delta -2
            _projection(2, peak_score=38.0),  # delta -12
            _projection(3, peak_score=60.0),  # delta +10
        ])
    )

    bucket = payload["buckets"][0]
    assert bucket["negative_delta_count"] == 2
    assert bucket["big_negative_delta_count"] == 1


def test_peak_calibration_validator_rejects_external_source_flags(tmp_path):
    payload = build_peak_calibration_report(_peak_payload([_projection(1)]))
    payload["source_policy"]["external_rankings_used_for_score"] = True
    path = tmp_path / "calibration.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    _payload, problems = validate_peak_calibration_report(path)

    assert "source_policy.external_rankings_used_for_score must be false" in problems


def test_run_peak_calibration_writes_valid_artifact(tmp_path):
    peak_path = tmp_path / "peak.json"
    artifact_path = tmp_path / "calibration.json"
    peak_path.write_text(json.dumps(_peak_payload([_projection(1)])), encoding="utf-8")

    result = run_peak_calibration_report(peak_path=peak_path, artifact_path=artifact_path)
    _payload, problems = validate_peak_calibration_report(artifact_path)

    assert result["ready_for_review"] is True
    assert result["bucket_count"] == 1
    assert problems == []
