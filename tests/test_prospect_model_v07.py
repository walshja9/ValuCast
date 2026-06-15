"""Tests for the shadow ValuCast Prospect Model v0.7 preview."""
import json

from prospects.model_v07 import build_model_v07_preview
from prospects.model_v07 import run_model_v07_preview
from scripts.validate_prospect_model_v07 import validate_model_v07


def _row(rank, role="hitter"):
    current = (
        {
            "sample": 224,
            "sample_unit": "PA",
            "skill_band": "impact",
            "ops": 0.976,
            "iso": 0.261,
            "bb_minus_k_pct": -3.1,
        }
        if role == "hitter"
        else {
            "sample": 49.7,
            "sample_unit": "IP",
            "skill_band": "starter_volume",
            "k_bb_pct": 22.4,
            "k_per_9": 10.8,
            "bb_per_9": 3.1,
            "starter_role": True,
        }
    )
    return {
        "rank": rank,
        "name": f"Prospect {rank}",
        "mlbam_id": 10_000 + rank,
        "role": role,
        "level": "AA",
        "score": 60.0 - rank,
        "score_source": "prospect_model_v0_6",
        "components": {
            "factual_current_context": current,
            "factual_investment_context": {"draft_round": 1},
            "sample_reliability": 62.0,
            "availability_risk_discount": 0.02,
            "availability": {"status": "available"},
            "age_level_context": {"age_vs_level": -1.2},
            "bucket_calibration": {"bucket": "upper_level_hitters"},
        },
    }


def _rank_payload(rows):
    return {
        "rank_name": "ValuCast Prospect Rank v1 Candidate",
        "rank_version": "0.2.0",
        "status": "candidate_ready",
        "generated_at": "2026-06-14T12:00:00+00:00",
        "ranked_count": len(rows),
        "board": rows,
    }


def test_model_v07_preview_extracts_factual_features_and_stays_shadow_only():
    payload = build_model_v07_preview(
        _rank_payload([_row(1), _row(2, role="pitcher")])
    )

    assert payload["status"] == "shadow_preview"
    assert payload["source_policy"]["feeds_live_rank"] is False
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["model_contract"]["feeds_live_valucast_rank"] is False
    assert payload["validation"]["ready_for_backtest"] is True

    hitter = payload["candidates"][0]
    pitcher = payload["candidates"][1]
    assert hitter["candidate_features"]["ops"] == 0.976
    assert hitter["candidate_features"]["bb_minus_k_pct"] == -3.1
    assert pitcher["candidate_features"]["k_bb_pct"] == 22.4
    assert pitcher["candidate_features"]["starter_role"] is True
    assert hitter["feature_coverage"]["factual_current_context"] is True
    assert pitcher["feature_coverage"]["availability_context"] is True


def test_model_v07_preview_blocks_backtest_when_factual_context_is_missing():
    rows = [_row(rank) for rank in range(1, 21)]
    for row in rows:
        row["components"].pop("factual_current_context")

    payload = build_model_v07_preview(_rank_payload(rows))

    assert payload["validation"]["ready_for_backtest"] is False
    assert payload["validation"]["blockers"] == [
        "Top-200 factual-current context coverage is below threshold."
    ]


def test_run_and_validate_model_v07_preview(tmp_path):
    rank_path = tmp_path / "rank.json"
    artifact_path = tmp_path / "model-v07.json"
    rank_path.write_text(
        json.dumps(_rank_payload([_row(1), _row(2, role="pitcher")])),
        encoding="utf-8",
    )

    result = run_model_v07_preview(rank_path=rank_path, artifact_path=artifact_path)
    payload, problems = validate_model_v07(artifact_path)

    assert result["ready_for_backtest"] is True
    assert payload["artifact"] == "valucast_prospect_model_v0_7_preview"
    assert problems == []


def test_model_v07_validator_rejects_live_feed_claim(tmp_path):
    payload = build_model_v07_preview(_rank_payload([_row(1)]))
    payload["source_policy"]["feeds_live_rank"] = True
    artifact_path = tmp_path / "model-v07.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_model_v07(artifact_path)

    assert "source_policy.feeds_live_rank must be false" in problems
