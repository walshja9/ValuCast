"""Tests for ValuCast-owned prospect input contract canonicalization."""
import json

from prospects.input_builder import build_valucast_prospect_input_contract
from prospects.input_builder import run_valucast_prospect_input_build
from scripts.validate_valucast_prospect_inputs import validate_valucast_prospect_inputs


def _upstream_contract():
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
        "historical": {"rows": [{}]},
        "historical_mlb_seasons": {"1_hitter": []},
        "current": {"hitters": [{}], "pitchers": [{}]},
        "mlb_service": [],
    }


def test_build_valucast_prospect_input_contract_marks_valucast_owner():
    payload = build_valucast_prospect_input_contract(_upstream_contract())

    assert payload["producer"]["owner"] == "valucast"
    assert payload["producer"]["kind"] == "canonical_factual_prospect_input_contract"
    assert payload["producer"]["upstream_model_score_effect"] == "none"
    assert payload["source_policy"]["dynasty_values_used"] is False


def test_run_and_validate_valucast_prospect_input_contract(tmp_path):
    upstream_path = tmp_path / "upstream.json"
    output_path = tmp_path / "prospect_model_inputs.json"
    upstream_path.write_text(json.dumps(_upstream_contract()), encoding="utf-8")

    result = run_valucast_prospect_input_build(
        upstream_path=upstream_path,
        output_path=output_path,
    )
    payload, problems = validate_valucast_prospect_inputs(output_path)

    assert result["producer_owner"] == "valucast"
    assert payload["producer"]["owner"] == "valucast"
    assert problems == []
