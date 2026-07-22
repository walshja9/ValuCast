"""Tests for the ValuCast Prospect Rank v1 coverage audit."""

import json

from prospects.coverage_audit import build_prospect_coverage_audit
from scripts.validate_prospect_coverage_audit import validate_audit


def _row(
    rank,
    source,
    investment=None,
    dd_rank=None,
    source_ranks=None,
    *,
    role="hitter",
    score=45.0,
):
    return {
        "rank": rank,
        "name": f"Prospect {rank}",
        "mlbam_id": 10_000 + rank,
        "role": role,
        "positions": ["SS"],
        "mlb_team": "BOS",
        "age": 19,
        "level": "A",
        "eta": 2028,
        "score": score,
        "score_source": source,
        "confidence": "low",
        "components": {
            "model_score": None,
            "universal_outcome_index": 30.0,
            "factual_investment_context": investment,
            "sample_reliability": 42.0,
        },
        "context_only": {
            "dd_prospect_rank": dd_rank,
            "source_ranks": source_ranks,
        },
    }


def _rank_payload(rows):
    return {
        "rank_name": "ValuCast Prospect Rank v1 Candidate",
        "rank_version": "0.2.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "input_artifacts": {"prospect_model_version": "0.6.0"},
        "board": rows,
    }


def _investment_evidence(*rows):
    return {
        "artifact": "valucast_international_signing_facts",
        "schema_version": "1.0.0",
        "as_of": "2026-07-22",
        "source_policy": {
            "kind": "factual_observational_only",
            "feeds_model_score": False,
        },
        "rows": list(rows),
    }


def test_coverage_audit_blocks_elite_factual_raw_fallback_inside_top_200():
    payload = build_prospect_coverage_audit(
        _rank_payload(
            [
                _row(1, "prospect_model_v0_6", investment=80),
                _row(75, "universal_fallback", investment=98),
                _row(90, "prospect_pedigree_v0_7", investment=99),
            ]
        )
    )

    assert payload["status"] == "blocked"
    assert payload["metrics"]["v06_model_score_count"] == 1
    assert payload["metrics"]["pedigree_v0_7_score_count"] == 1
    assert payload["metrics"]["elite_factual_raw_fallback_top_200_count"] == 1
    assert payload["elite_factual_raw_fallback_misses"][0]["name"] == "Prospect 75"
    assert "missing_v0_6_model_profile" in payload["elite_factual_raw_fallback_misses"][0]["reasons"]


def test_coverage_audit_keeps_public_context_as_watchlist_only():
    payload = build_prospect_coverage_audit(
        _rank_payload(
            [
                _row(1, "prospect_model_v0_6", investment=80),
                _row(
                    225,
                    "universal_fallback",
                    investment=20,
                    dd_rank=5,
                    source_ranks={"pipeline": 4},
                ),
            ]
        )
    )

    assert payload["status"] == "candidate_ready"
    assert payload["metrics"]["context_watchlist_raw_fallback_count"] == 1
    assert payload["context_watchlist_raw_fallback_misses"][0][
        "dd_prospect_rank_context"
    ] == 5
    assert payload["source_policy"]["external_rankings_used_for_model_score"] is False


def test_coverage_audit_reports_investment_completeness_and_direct_sensitivity():
    payload = build_prospect_coverage_audit(
        _rank_payload(
            [
                _row(1, "prospect_model_v0_6", investment=100, score=60.0),
                _row(2, "prospect_model_v0_6", score=50.0),
                _row(3, "prospect_model_v0_6", role="pitcher", score=40.0),
            ]
        )
    )

    assert payload["status"] == "candidate_ready"
    context = payload["investment_context"]
    assert context["status"] == "incomplete"
    assert context["affects_root_status"] is False
    assert context["bands"]["top_25"]["all"] == {
        "rows": 3,
        "covered": 1,
        "missing": 2,
        "coverage_rate": 0.3333,
    }
    assert context["bands"]["top_25"]["hitter"]["missing"] == 1
    assert context["bands"]["top_25"]["pitcher"]["missing"] == 1

    rows = {
        row["name"]: row
        for row in context["direct_score_sensitivity"]["top_50_missing_rows"]
    }
    assert rows["Prospect 2"]["direct_weight"] == 0.06
    assert rows["Prospect 2"]["maximum_direct_score_delta"] == 4.5
    assert rows["Prospect 2"]["score_upper_bound"] == 54.5
    assert context["direct_score_sensitivity"]["model_score_held_fixed"] is True
    assert context["direct_score_sensitivity"]["counterfactual_ranks_computed"] is False


def test_coverage_audit_separates_verified_evidence_from_frozen_scoring_input():
    rank_payload = _rank_payload(
        [
            _row(1, "prospect_model_v0_6", investment=100, score=60.0),
            _row(2, "prospect_model_v0_6", score=50.0),
        ]
    )
    evidence = _investment_evidence(
        {
            "mlbam_id": 10_002,
            "name": "Prospect 2",
            "acquisition_type": "international_amateur_free_agent",
            "signing_bonus": 950_000,
            "source_name": "MLB Pipeline",
            "source_url": "https://www.mlb.com/example",
            "source_checked_at": "2026-07-22",
        }
    )

    payload = build_prospect_coverage_audit(rank_payload, evidence)

    context = payload["investment_context"]
    assert context["status"] == "incomplete"
    assert context["bands"]["top_25"]["all"]["covered"] == 1
    verified = context["verified_evidence"]
    assert verified["status"] == "complete"
    assert verified["feeds_model_score"] is False
    assert verified["bands"]["top_25"]["all"] == {
        "rows": 2,
        "covered": 2,
        "missing": 0,
        "coverage_rate": 1.0,
    }
    assert verified["resolved_scoring_gaps"][0]["mlbam_id"] == 10_002
    assert verified["resolved_scoring_gaps"][0]["signing_bonus"] == 950_000
    assert rank_payload["board"][1]["components"]["factual_investment_context"] is None


def test_coverage_audit_validator_requires_investment_context(tmp_path):
    payload = build_prospect_coverage_audit(
        _rank_payload([_row(1, "prospect_model_v0_6")])
    )
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_audit(path)[1] == []

    payload.pop("investment_context")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert "investment_context must be an object" in validate_audit(path)[1]
