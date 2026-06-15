"""Tests for the raw-data independence audit."""
import json

from prospects.raw_data_independence import build_raw_data_independence_audit
from prospects.raw_data_independence import run_raw_data_independence_audit
from scripts.validate_raw_data_independence_audit import validate_raw_data_independence


def _contract():
    return {
        "schema_version": "1.2",
        "generated_at": "2026-06-14T12:00:00+00:00",
        "source_policy": {
            "kind": "factual_only",
            "sources": [
                "valucast_universal_prospect_dataset",
                "milb_season_stats",
                "fantrax_mlb_actuals",
                "mlb_prospect_seasons_cache",
                "mlb_statsapi_draft",
                "fantrax_roster_status",
            ],
            "external_rankings_used": False,
            "external_projections_used": False,
            "market_values_used": False,
            "dynasty_values_used": False,
        },
        "producer": {
            "owner": "valucast",
            "kind": "canonical_factual_prospect_input_contract",
            "upstream_kind": "dd_factual_export",
            "upstream_model_score_effect": "none",
        },
        "historical": {"rows": [{}]},
        "historical_mlb_seasons": {"1_hitter": []},
        "current": {"hitters": [{}], "pitchers": [{}]},
    }


def test_raw_data_independence_audit_documents_remaining_trust_boundary():
    payload = build_raw_data_independence_audit(_contract())

    assert payload["status"] == "canonical_contract_owned"
    assert payload["validation"]["ready_for_current_publication"] is True
    assert payload["validation"]["raw_data_independence_complete"] is False
    assert payload["independence"]["contract_factual_only"] is True
    assert payload["independence"]["canonical_contract_owned"] is True
    assert payload["independence"]["raw_data_ingestion_owned"] is False
    assert payload["independence"]["last_external_trust_boundary"][
        "current_boundary"
    ] == "ValuCast canonical factual contract"


def test_run_and_validate_raw_data_independence_audit(tmp_path):
    input_path = tmp_path / "inputs.json"
    artifact_path = tmp_path / "audit.json"
    input_path.write_text(json.dumps(_contract()), encoding="utf-8")

    result = run_raw_data_independence_audit(
        input_contract_path=input_path,
        artifact_path=artifact_path,
    )
    payload, problems = validate_raw_data_independence(artifact_path)

    assert result["status"] == "canonical_contract_owned"
    assert payload["artifact"] == "valucast_raw_data_independence_audit"
    assert problems == []
