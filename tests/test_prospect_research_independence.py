"""Prospect research must remain independent of public and market opinions."""
from __future__ import annotations

import pytest

from prospects.challenger_readiness import build_plan034_readiness
from prospects.input_contract import validate_factual_contract


def _factual_contract() -> dict:
    return {
        "schema_version": "1.1",
        "generated_at": "2026-08-03T00:00:00+00:00",
        "source_policy": {
            "kind": "factual_only",
            "sources": [
                "fantrax_mlb_actuals",
                "milb_season_stats",
                "mlb_prospect_seasons_cache",
                "mlb_statsapi_draft",
                "valucast_universal_prospect_dataset",
            ],
            "external_rankings_used": False,
            "external_projections_used": False,
            "market_values_used": False,
            "dynasty_values_used": False,
        },
        "historical": {
            "rows": [
                {
                    "cohort_year": 2019,
                    "mlbam_id": 1,
                    "role": "hitter",
                    "age": 20,
                    "level": "AA",
                    "position": "SS",
                }
            ]
        },
        "current": {"hitters": [], "pitchers": []},
        "mlb_service": [],
    }


def _registration() -> dict:
    return {
        "protocol": "prospect-model-challenger-epoch-v1",
        "look_spent": False,
        "execution_authorized": False,
        "execution_trigger": {
            "not_before": "2027-01-01",
            "requires_2026_mlb_season_complete": True,
            "requires_2022_cohort_four_year_horizon_complete": True,
            "requires_reviewed_implementation_amendment": True,
        },
    }


@pytest.mark.parametrize(
    "field",
    [
        "consensus_rank",
        "source_ranks",
        "public_source_consensus",
        "fv",
        "tool_grades",
        "competitor_score",
        "competitor_rank",
        "market_value",
        "dynasty_value",
        "valucast_rank",
    ],
)
def test_factual_contract_rejects_prohibited_model_fields(field):
    payload = _factual_contract()
    payload["historical"]["rows"][0][field] = 1

    assert (
        f"historical.rows[0].{field} is prohibited"
        in validate_factual_contract(payload)
    )


def test_factual_contract_allows_registered_baseball_facts():
    payload = _factual_contract()
    payload["historical"]["rows"][0].update(
        {
            "draft_pick_number": 12,
            "signing_bonus": 3_000_000,
            "availability_status": "available",
        }
    )

    assert validate_factual_contract(payload) == []


def test_new_challenger_readiness_rejects_prohibited_feature_rows():
    contract = _factual_contract()
    contract["historical"]["rows"][0]["source_ranks"] = {"field": 1}

    with pytest.raises(ValueError, match="source_ranks"):
        build_plan034_readiness(
            contract, _registration(), None, as_of="2026-08-03"
        )
