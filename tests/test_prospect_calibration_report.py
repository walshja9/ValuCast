"""Tests for the Prospect Rank v1 calibration report."""
import json

from prospects.calibration_report import build_prospect_calibration_report
from prospects.calibration_report import run_prospect_calibration_report
from scripts.validate_prospect_calibration_report import validate_report


def _row(
    rank,
    source="prospect_model_v0_6",
    role="hitter",
    dd_rank=None,
    availability_status="available",
    availability_discount=0.0,
):
    return {
        "rank": rank,
        "name": f"Prospect {rank}",
        "mlbam_id": 10_000 + rank,
        "role": role,
        "positions": ["SP"] if role == "pitcher" else ["SS"],
        "mlb_team": "BOS",
        "age": 20,
        "level": "AA",
        "score": round(60.0 - rank * 0.2, 2),
        "score_source": source,
        "confidence": "medium",
        "components": {
            "model_score": 55.0,
            "sample_reliability": 45.0,
            "availability_adjusted": availability_discount > 0,
            "availability_risk_discount": availability_discount,
            "availability": {
                "present": True,
                "status": availability_status,
                "risk_level": "medium" if availability_discount > 0 else "clear",
                "risk_discount": availability_discount,
                "signals": (
                    ["thin_starter_workload_under_30_ip"]
                    if availability_discount > 0
                    else []
                ),
                "sample": 29.0 if availability_discount > 0 else 180.0,
                "sample_unit": "IP" if role == "pitcher" else "PA",
            },
        },
        "context_only": {
            "dd_prospect_rank": dd_rank,
            "source_ranks": {"pipeline": dd_rank} if dd_rank else None,
        },
    }


def _rank_payload(rows):
    return {
        "rank_name": "ValuCast Prospect Rank v1 Candidate",
        "rank_version": "0.2.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "input_artifacts": {
            "prospect_model_version": "0.6.0",
            "prospect_availability_version": "0.1.0",
        },
        "board": rows,
    }


def test_calibration_report_passes_clean_board_and_keeps_context_observe_only():
    rows = [_row(rank) for rank in range(1, 61)]
    rows[5]["role"] = "pitcher"
    rows[5]["positions"] = ["SP"]
    rows[9]["score_source"] = "prospect_pedigree_v0_7"
    rows[14] = _row(
        15,
        dd_rank=80,
        availability_status="thin_current_sample",
        availability_discount=0.03,
    )

    payload = build_prospect_calibration_report(_rank_payload(rows))

    assert payload["status"] == "review_ready"
    assert payload["metrics"]["bands"]["25"]["role_counts"]["pitcher"] == 1
    assert payload["metrics"]["bands"]["50"]["availability_adjusted_count"] == 1
    assert payload["metrics"]["bucket_metrics"]
    assert payload["metrics"]["bucket_tuning_flag_count"] == 0
    assert payload["metrics"]["context_disagreement_count_top50"] == 1
    assert payload["watchlists"]["top50_dd_context_disagreements"][0][
        "disagreement_direction"
    ] == "valucast_higher"
    assert payload["source_policy"]["feeds_model_score"] is False
    assert payload["source_policy"]["dd_ranks_used_for_model_score"] is False
    assert payload["source_policy"]["external_rankings_used_for_model_score"] is False
    assert payload["tuning_flags"] == []


def test_calibration_report_flags_broad_top_board_shape_problems():
    rows = []
    for rank in range(1, 61):
        source = "prospect_model_v0_6"
        if rank <= 12:
            source = "prospect_pedigree_v0_7"
        if rank <= 8:
            role = "pitcher"
        else:
            role = "hitter"
        if rank in {45, 46, 47, 48, 49, 50}:
            source = "universal_fallback"
        rows.append(_row(rank, source=source, role=role))

    payload = build_prospect_calibration_report(_rank_payload(rows))
    flag_ids = {flag["id"] for flag in payload["tuning_flags"]}

    assert payload["status"] == "needs_review"
    assert "top25_pitcher_crowding" in flag_ids
    assert "top25_pedigree_crowding" in flag_ids
    assert "top50_raw_fallback_rate" in flag_ids
    assert payload["metrics"]["bands"]["50"]["fallback_count"] == 6


def test_calibration_report_flags_thin_upper_level_pitcher_bucket():
    rows = []
    for rank in range(1, 61):
        if rank <= 5:
            rows.append(
                _row(
                    rank,
                    role="pitcher",
                    availability_status="thin_current_sample",
                    availability_discount=0.03,
                )
            )
        else:
            rows.append(_row(rank))

    payload = build_prospect_calibration_report(_rank_payload(rows))
    flag_ids = {flag["id"] for flag in payload["tuning_flags"]}
    thin_bucket = next(
        item
        for item in payload["metrics"]["bucket_metrics"]
        if item["bucket"] == "pitcher|upper_level|prospect_model_v0_6|thin_current_sample"
    )

    assert payload["status"] == "needs_review"
    assert "top50_thin_upper_level_pitcher_count" in flag_ids
    assert payload["metrics"]["bucket_tuning_flag_count"] == 1
    assert thin_bucket["top50_count"] == 5


def test_run_and_validate_calibration_report(tmp_path):
    rank_path = tmp_path / "rank.json"
    artifact_path = tmp_path / "calibration.json"
    rank_path.write_text(
        json.dumps(_rank_payload([_row(rank) for rank in range(1, 61)])),
        encoding="utf-8",
    )

    result = run_prospect_calibration_report(
        rank_path=rank_path,
        artifact_path=artifact_path,
    )
    payload, problems = validate_report(artifact_path)

    assert result["status"] == "review_ready"
    assert result["row_count"] == 60
    assert payload is not None
    assert payload["artifact"] == "valucast_prospect_calibration_report"
    assert problems == []


def test_consensus_elite_valucast_deep_watchlist_sees_deep_rows():
    # 2026-07-29 Sirota review, owner item 3: the top-50-scoped watchlists
    # structurally cannot see a player the public boards rank elite while
    # ValuCast ranks deep. This watchlist scans the whole board. Display-only.
    board = [_row(rank=rank) for rank in range(1, 61)]
    deep = _row(rank=180)
    deep["name"] = "Consensus Elite Deep"
    deep["context_only"] = {
        "source_ranks": {"pipeline": 12, "pl": 13, "hkb": 31, "sts": 43}
    }
    board.append(deep)
    two_board = _row(rank=400)
    two_board["name"] = "Two Board Artifact"
    two_board["context_only"] = {"source_ranks": {"pipeline": 20, "hkb": 25}}
    board.append(two_board)

    report = build_prospect_calibration_report({"board": board})

    watchlist = report["watchlists"]["consensus_elite_valucast_deep"]
    names = [row["name"] for row in watchlist]
    assert "Consensus Elite Deep" in names
    # Featured-claim bar: a 2-board consensus does not qualify.
    assert "Two Board Artifact" not in names
    entry = next(row for row in watchlist if row["name"] == "Consensus Elite Deep")
    assert entry["valucast_rank"] == 180
    assert entry["consensus_gap"] >= 30
    # ToS rule: never republish per-board ranks — only median, count, min/max.
    assert "boards" not in entry
    assert entry["board_count"] == 4
    assert entry["board_rank_min"] == 12 and entry["board_rank_max"] == 43
    assert report["metrics"]["consensus_elite_disagreement_count"] >= 1
