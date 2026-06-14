"""Tests for the ValuCast Prospect Rank v1 coverage audit."""

from prospects.coverage_audit import build_prospect_coverage_audit


def _row(rank, source, investment=None, dd_rank=None, source_ranks=None):
    return {
        "rank": rank,
        "name": f"Prospect {rank}",
        "mlbam_id": 10_000 + rank,
        "role": "hitter",
        "positions": ["SS"],
        "mlb_team": "BOS",
        "age": 19,
        "level": "A",
        "eta": 2028,
        "score": 45.0,
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
