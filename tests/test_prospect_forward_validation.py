"""Tests for ValuCast prospect forward-validation reports."""
import json

from prospects.forward_validation import (
    build_forward_validation_report,
    compare_buy_archives,
    compare_rank_archives,
    run_forward_validation_report,
)
from scripts.validate_prospect_forward_validation import validate_report


def _rank_row(
    mlbam_id,
    name,
    rank,
    score,
    *,
    role="hitter",
    level="AA",
    source="prospect_model_v0_6",
    availability_status="available",
):
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "rank": rank,
        "score": score,
        "level": level,
        "score_source": source,
        "components": {
            "availability": {
                "status": availability_status,
            }
        },
    }


def _rank_payload(date_str, rows):
    return {
        "date": date_str,
        "generated_at": f"{date_str}T12:00:00+00:00",
        "rank_version": "test",
        "board": rows,
    }


def _buy_row(mlbam_id, name, rank, score, role="hitter"):
    return {
        "mlbam_id": mlbam_id,
        "name": name,
        "role": role,
        "rank": rank,
        "score": score,
    }


def _buy_payload(date_str, rows):
    return {
        "date": date_str,
        "generated_at": f"{date_str}T12:00:00+00:00",
        "signal_version": "1.0.0",
        "board": rows,
    }


def test_rank_archive_comparison_groups_movement_by_current_bucket():
    previous = _rank_payload(
        "2026-06-13",
        [
            _rank_row(1, "Thin Arm", 30, 50.0, role="pitcher", level="AAA", availability_status="thin_current_sample"),
            _rank_row(2, "Stable Bat", 10, 60.0),
        ],
    )
    current = _rank_payload(
        "2026-06-14",
        [
            _rank_row(1, "Thin Arm", 20, 52.0, role="pitcher", level="AAA", availability_status="thin_current_sample"),
            _rank_row(2, "Stable Bat", 12, 59.0),
            _rank_row(3, "New Bat", 40, 48.0),
        ],
    )

    comparison = compare_rank_archives(previous, current)
    thin_bucket = next(
        bucket
        for bucket in comparison["buckets"]
        if bucket["bucket"] == "pitcher|upper_level|prospect_model_v0_6|thin_current_sample"
    )

    assert comparison["new_identity_count"] == 1
    assert thin_bucket["current_top50_count"] == 1
    assert thin_bucket["average_rank_change"] == -10.0
    assert thin_bucket["moved_up_count"] == 1
    assert thin_bucket["largest_movers"][0]["name"] == "Thin Arm"


def test_buy_archive_comparison_tracks_top40_retention():
    previous = _buy_payload(
        "2026-06-13",
        [_buy_row(index, f"Buy {index}", index, 60.0 - index) for index in range(1, 41)],
    )
    current = _buy_payload(
        "2026-06-14",
        [_buy_row(index, f"Buy {index}", index, 60.0 - index) for index in range(21, 61)],
    )

    comparison = compare_buy_archives(previous, current)

    assert comparison["retained_top_count"] == 20
    assert comparison["retention_rate"] == 0.5
    assert comparison["new_top_count"] == 20
    assert comparison["exited_top_count"] == 20


def test_forward_validation_report_is_observe_only_until_enough_archive_span():
    rank_payloads = [
        _rank_payload("2026-06-13", [_rank_row(1, "A", 1, 60.0)]),
        _rank_payload("2026-06-14", [_rank_row(1, "A", 2, 59.0)]),
    ]
    buy_payloads = [
        _buy_payload("2026-06-13", [_buy_row(1, "A", 1, 60.0)]),
        _buy_payload("2026-06-14", [_buy_row(1, "A", 1, 59.0)]),
    ]

    report = build_forward_validation_report(rank_payloads, buy_payloads)

    assert report["status"] == "collecting"
    assert report["source_policy"]["feeds_model_score"] is False
    assert report["source_policy"]["feeds_public_rank"] is False
    assert report["observation_contract"]["is_realized_outcome_accuracy_evidence"] is False
    assert report["metrics"]["rank_comparison_count"] == 1
    assert report["latest_rank_comparison"]["buckets"]


def test_run_forward_validation_report_writes_valid_artifact(tmp_path):
    rank_dir = tmp_path / "rank"
    buy_dir = tmp_path / "buys"
    rank_dir.mkdir()
    buy_dir.mkdir()
    (rank_dir / "2026-06-13.json").write_text(
        json.dumps(_rank_payload("2026-06-13", [_rank_row(1, "A", 1, 60.0)])),
        encoding="utf-8",
    )
    (rank_dir / "2026-06-14.json").write_text(
        json.dumps(_rank_payload("2026-06-14", [_rank_row(1, "A", 2, 59.0)])),
        encoding="utf-8",
    )
    (buy_dir / "2026-06-13.json").write_text(
        json.dumps(_buy_payload("2026-06-13", [_buy_row(1, "A", 1, 60.0)])),
        encoding="utf-8",
    )
    (buy_dir / "2026-06-14.json").write_text(
        json.dumps(_buy_payload("2026-06-14", [_buy_row(1, "A", 1, 59.0)])),
        encoding="utf-8",
    )
    artifact_path = tmp_path / "forward-validation.json"

    result = run_forward_validation_report(rank_dir, buy_dir, artifact_path)
    payload, problems = validate_report(artifact_path)

    assert result["rank_comparison_count"] == 1
    assert result["buy_comparison_count"] == 1
    assert payload["artifact"] == "valucast_prospect_forward_validation"
    assert problems == []
