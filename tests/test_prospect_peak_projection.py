"""Tests for ValuCast Prospect Peak Projection v1."""
import json

from prospects.peak_projection import build_peak_projection
from prospects.peak_projection import run_peak_projection
from scripts.validate_prospect_peak_projection import validate_peak_projection


def _row(rank, role="hitter"):
    current = (
        {
            "sample": 224,
            "sample_unit": "PA",
            "skill_band": "impact",
            "ops": 0.976,
            "iso": 0.261,
            "k_pct": 12.9,
            "bb_pct": 9.8,
            "bb_minus_k_pct": -3.1,
        }
        if role == "hitter"
        else {
            "sample": 55.7,
            "sample_unit": "IP",
            "skill_band": "starter_volume",
            "k_per_9": 13.3,
            "bb_per_9": 1.1,
            "k_bb_pct": 37.7,
            "era": 1.13,
            "whip": 0.66,
            "starter_role": True,
        }
    )
    return {
        "rank": rank,
        "name": f"Prospect {rank}",
        "mlbam_id": 10000 + rank,
        "role": role,
        "level": "AA",
        "age": 20,
        "eta": 2027,
        "score": 60.0 - rank,
        "score_source": "prospect_model_v0_6",
        "components": {
            "factual_current_context": current,
            "factual_investment_context": 82.0,
            "sample_reliability": 58.0,
            "availability": {"status": "available"},
            "availability_risk_discount": 0.0,
        },
    }


def _rank_payload(rows):
    return {
        "rank_name": "ValuCast Prospect Rank v1 Candidate",
        "rank_version": "0.2.7",
        "status": "candidate_ready",
        "generated_at": "2026-06-15T00:00:00+00:00",
        "ranked_count": len(rows),
        "board": rows,
    }


def test_peak_projection_builds_card_ready_role_and_shape_without_rank_mutation():
    payload = build_peak_projection(_rank_payload([_row(1), _row(2, role="pitcher")]))

    assert payload["artifact"] == "valucast_prospect_peak_projection_v1"
    assert payload["status"] == "candidate_ready"
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["external_rankings_used_for_score"] is False
    assert payload["source_policy"]["public_scouting_grades_used"] is False
    assert payload["projection_contract"]["feeds_live_rank"] is False
    assert payload["projection_contract"]["feeds_live_value"] is False
    assert payload["projection_contract"]["projection_kind"] == (
        "peak_role_and_skill_shape_not_full_stat_forecast"
    )
    assert payload["projection_contract"]["card_visual_version"] == "2.0.0"
    assert payload["validation"]["ready_for_card_v2"] is True

    hitter = payload["projections"][0]
    pitcher = payload["projections"][1]
    assert hitter["rank_v1_rank"] == 1
    assert hitter["peak_score"] > hitter["rank_v1_score"]
    assert hitter["usage"] == "card_visual_context_not_live_rank_or_value"
    assert hitter["card_v2"]["visual_version"] == "2.0.0"
    assert hitter["card_v2"]["role_probabilities"]["regular_or_better"] > 0
    assert hitter["card_v2"]["card_copy"].startswith("Peak view:")
    assert len(hitter["shape"]) == 4
    assert {item["label"] for item in hitter["shape"]} == {
        "Hit",
        "Power",
        "Approach",
        "Impact",
    }
    assert pitcher["peak_role"] in {
        "rotation_starter",
        "mid_rotation_or_better",
    }
    assert {item["label"] for item in pitcher["shape"]} == {
        "Miss",
        "Command",
        "Dominance",
        "Run Prevention",
    }


def test_peak_projection_thin_rows_get_neutral_shape_and_lower_confidence():
    row = _row(1)
    row["components"].pop("factual_current_context")
    row["components"]["sample_reliability"] = 28.0
    row["components"]["availability"] = {"status": "injured"}
    row["components"]["availability_risk_discount"] = 0.10

    payload = build_peak_projection(_rank_payload([row]))
    projection = payload["projections"][0]

    assert payload["validation"]["ready_for_card_v2"] is True
    assert projection["risk_band"] == "high"
    assert projection["confidence"] == "low"
    assert len(projection["shape"]) == 4
    assert all(20 <= item["grade"] <= 80 for item in projection["shape"])


def test_run_and_validate_peak_projection(tmp_path):
    rank_path = tmp_path / "rank.json"
    artifact_path = tmp_path / "peak.json"
    rank_path.write_text(
        json.dumps(_rank_payload([_row(1), _row(2, role="pitcher")])),
        encoding="utf-8",
    )

    result = run_peak_projection(rank_path=rank_path, artifact_path=artifact_path)
    payload, problems = validate_peak_projection(artifact_path)

    assert result["ready_for_card_v2"] is True
    assert payload["artifact"] == "valucast_prospect_peak_projection_v1"
    assert problems == []


def test_peak_projection_validator_rejects_public_scouting_grade_flag(tmp_path):
    payload = build_peak_projection(_rank_payload([_row(1)]))
    payload["source_policy"]["public_scouting_grades_used"] = True
    artifact_path = tmp_path / "peak.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_peak_projection(artifact_path)

    assert "source_policy.public_scouting_grades_used must be false" in problems
