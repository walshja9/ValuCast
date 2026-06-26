"""Tests for ValuCast Prospect Peak Projection v1."""
import json

from prospects.peak_projection import _pitcher_shape
from prospects.peak_projection import build_peak_projection
from prospects.peak_projection import run_peak_projection
from scripts.validate_prospect_peak_projection import validate_peak_projection


def _run_prevention_grade(era, whip):
    current = {"k_per_9": 9.0, "bb_per_9": 3.0, "k_bb_pct": 18.0, "era": era, "whip": whip}
    shape = _pitcher_shape(current, rank_score=50.0)
    rp = next(item for item in shape if item["label"] == "Run Prevention")
    return rp["grade"]


def test_run_prevention_grade_rewards_low_era_and_whip():
    # Run Prevention must reward low ERA/WHIP. Under the old double-negated
    # (swapped anchors + lower_is_better=True) code this was fully inverted,
    # so a 7.11 ERA / 1.97 WHIP line graded ABOVE a 1.13 / 0.66 elite line.
    elite = _run_prevention_grade(era=1.13, whip=0.66)
    terrible = _run_prevention_grade(era=7.11, whip=1.97)
    assert elite > terrible


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
    assert hitter["card_v2"]["card_copy"].startswith("Ceiling is")
    # The floor clause must not double-print "floor" — the slug "..._floor"
    # used to render as "floor is reserve floor". "floor" appears once now.
    assert hitter["card_v2"]["card_copy"].lower().count("floor") == 1
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


def _row_with_v2_inputs(rank=1):
    row = _row(rank)
    row["dynasty_signal"] = {
        "role_or_better_probability": 0.6,
        "star_ceiling_probability": 0.2,
    }
    row["context_only"] = {
        "best_single_level_stat_line": {
            "level": "AA",
            "sample": 250,
            "sample_unit": "PA",
            "reason": "current_level_too_thin_best_prior_level",
            "avg": 0.300,
            "obp": 0.380,
            "slg": 0.520,
            "ops": 0.900,
            "iso": 0.220,
            "k_pct": 18.0,
            "bb_pct": 11.0,
        },
        "stat_line_translated": {
            "role": "hitter",
            "season": 2026,
            "level": "AA",
            "level_label": "AA",
            "sample": 250,
            "sample_unit": "PA",
            "low_sample": False,
            "confidence": "moderate",
            "stats": [
                {"key": "k_pct", "label": "K%", "fmt": "pct", "milb": 18.0, "mlb": 20.5, "mlb_avg": 22.0},
                {"key": "iso", "label": "ISO", "fmt": "iso", "milb": 0.220, "mlb": 0.170, "mlb_avg": 0.150},
            ],
        },
    }
    return row


def test_peak_v2_uses_best_single_and_model_role_probabilities():
    payload = build_peak_projection(_rank_payload([_row_with_v2_inputs(1)]))
    proj = payload["projections"][0]
    v2 = proj["peak_v2"]

    assert v2["model_version"] == "2.1.0"
    assert v2["status"] == "shadow_observe_only"
    assert v2["shape_basis"] == "best_single_level"
    assert v2["role_probability_source"] == "model_dynasty_signal"
    assert v2["role_probability_basis"] == "cumulative_uncalibrated_outcome_distribution"
    probs = v2["role_probabilities"]
    # Cumulative outlook: star-ceiling is a SUBSET of role-or-better, so it can never
    # exceed it (the inversion the de-cumulated buckets used to show).
    assert set(probs) == {"reaches_role_or_better", "reaches_star_ceiling", "bust_risk"}
    assert probs["reaches_role_or_better"] == 0.6  # role_or_better_probability passthrough
    assert probs["reaches_star_ceiling"] == 0.2  # star_ceiling_probability, <= role-or-better
    assert probs["reaches_star_ceiling"] <= probs["reaches_role_or_better"]
    assert probs["bust_risk"] == 0.4  # 1 - role_or_better
    assert v2["mlb_equivalent"]["rates"]["iso"]["mlb"] == 0.170
    assert len(v2["shape"]) == 4
    # v1 fields untouched
    assert proj["peak_score"] > proj["rank_v1_score"]
    assert proj["card_v2"]["role_probabilities"]["regular_or_better"] > 0

    v2_summary = payload["v2"]
    assert v2_summary["feeds_card"] is False
    assert v2_summary["best_single_level_shape_count"] == 1
    assert v2_summary["model_role_probability_count"] == 1


def test_peak_v2_falls_back_when_no_owned_inputs():
    v2 = build_peak_projection(_rank_payload([_row(1)]))["projections"][0]["peak_v2"]
    assert v2["shape_basis"] == "current"
    assert v2["role_probability_source"] == "heuristic_fallback"
    assert v2["mlb_equivalent"] is None
    assert v2["delta_vs_v1_peak_score"] == 0.0


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


def test_peak_projection_validator_rejects_stale_card_copy(tmp_path):
    payload = build_peak_projection(_rank_payload([_row(1)]))
    projection = payload["projections"][0]
    projection["card_v2"]["card_copy"] = "Peak view: everyday regular; floor is reserve floor."
    artifact_path = tmp_path / "peak.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_peak_projection(artifact_path)

    assert any("stale card_v2 card_copy" in problem for problem in problems)
