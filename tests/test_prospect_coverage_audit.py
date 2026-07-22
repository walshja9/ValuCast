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
            "kind": "factual_rank_input",
            "feeds_rank_score": True,
            "feeds_v06_model": False,
            "feeds_universal_model": False,
            "changes_ranks_or_values": True,
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


def test_coverage_audit_reports_verified_evidence_applied_to_rank_input():
    rank_payload = _rank_payload(
        [
            _row(1, "prospect_model_v0_6", investment=100, score=60.0),
            _row(2, "prospect_model_v0_6", investment=68.12, score=52.59),
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
    assert context["status"] == "complete"
    assert context["bands"]["top_25"]["all"]["covered"] == 2
    verified = context["verified_evidence"]
    assert verified["status"] == "complete"
    assert verified["feeds_rank_score"] is True
    assert verified["feeds_v06_model"] is False
    assert verified["feeds_universal_model"] is False
    assert context["direct_score_sensitivity"]["counterfactual_ranks_computed"] is True
    assert verified["bands"]["top_25"]["all"] == {
        "rows": 2,
        "covered": 2,
        "missing": 0,
        "coverage_rate": 1.0,
    }
    assert verified["resolved_scoring_gaps"] == []
    assert rank_payload["board"][1]["components"]["factual_investment_context"] == 68.12


def test_coverage_audit_does_not_claim_corrected_ranks_with_unresolved_gap():
    payload = build_prospect_coverage_audit(
        _rank_payload([_row(1, "prospect_model_v0_6")]),
        _investment_evidence(
            {
                "mlbam_id": 10_001,
                "name": "Prospect 1",
                "acquisition_type": "international_amateur_free_agent",
                "signing_bonus": 950_000,
                "source_name": "MLB Pipeline",
                "source_url": "https://www.mlb.com/example",
                "source_checked_at": "2026-07-22",
            }
        ),
    )

    assert payload["investment_context"]["verified_evidence"][
        "resolved_scoring_gaps"
    ]
    assert payload["investment_context"]["direct_score_sensitivity"][
        "counterfactual_ranks_computed"
    ] is False


def test_coverage_audit_validator_requires_investment_context(tmp_path):
    payload = build_prospect_coverage_audit(
        _rank_payload([_row(1, "prospect_model_v0_6", investment=68.12)]),
        _investment_evidence(
            {
                "mlbam_id": 10_001,
                "name": "Prospect 1",
                "acquisition_type": "international_amateur_free_agent",
                "signing_bonus": 950_000,
                "source_name": "MLB Pipeline",
                "source_url": "https://www.mlb.com/example",
                "source_checked_at": "2026-07-22",
            }
        ),
    )
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_audit(path)[1] == []

    payload.pop("investment_context")
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert "investment_context must be an object" in validate_audit(path)[1]


def test_coverage_audit_validator_rejects_universal_model_use(tmp_path):
    payload = build_prospect_coverage_audit(
        _rank_payload([_row(1, "prospect_model_v0_6", investment=68.12)]),
        _investment_evidence(),
    )
    payload["investment_context"]["verified_evidence"][
        "feeds_universal_model"
    ] = True
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert (
        "investment_context.verified_evidence.feeds_universal_model must be false"
        in validate_audit(path)[1]
    )
