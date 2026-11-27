"""Tests for ValuCast-owned prospect input contract canonicalization."""
from __future__ import annotations

from prospects import input_builder
from scripts.validate_valucast_prospect_inputs import validate_valucast_prospect_inputs


def _native_contract():
    return {
        "schema_version": "1.2",
        "generated_at": "2026-06-14T12:00:00+00:00",
        "producer": {
            "owner": "valucast",
            "kind": "canonical_factual_prospect_input_contract",
            "contract_version": "0.2.0",
            "upstream_kind": "valucast_raw_ingestion",
            "upstream_model_score_effect": "none",
        },
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


def test_build_valucast_prospect_input_contract_marks_raw_ingestion(monkeypatch):
    monkeypatch.setattr(
        input_builder,
        "build_contract",
        lambda generated_at=None: _native_contract(),
    )

    payload = input_builder.build_valucast_prospect_input_contract()

    assert payload["producer"]["owner"] == "valucast"
    assert payload["producer"]["kind"] == "canonical_factual_prospect_input_contract"
    assert payload["producer"]["upstream_kind"] == "valucast_raw_ingestion"
    assert payload["producer"]["upstream_model_score_effect"] == "none"
    assert payload["source_policy"]["dynasty_values_used"] is False


def test_run_and_validate_valucast_prospect_input_contract(monkeypatch, tmp_path):
    output_path = tmp_path / "prospect_model_inputs.json"
    monkeypatch.setattr(
        input_builder,
        "build_contract",
        lambda generated_at=None: _native_contract(),
    )

    result = input_builder.run_valucast_prospect_input_build(output_path=output_path)
    payload, problems = validate_valucast_prospect_inputs(output_path)

    assert result["producer_owner"] == "valucast"
    assert result["upstream_kind"] == "valucast_raw_ingestion"
    assert payload["producer"]["owner"] == "valucast"
    assert problems == []
