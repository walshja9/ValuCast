import json

from prospects.card_data_audit import build_prospect_card_data_audit
from scripts.validate_prospect_card_data_audit import validate_prospect_card_data_audit


def _snapshot(players):
    return {
        "schema_version": "1.1",
        "artifact": "valucast_public_dynasty_snapshot",
        "generated_at": "2026-06-16T00:00:00+00:00",
        "generated_by": "valucast",
        "source_policy": {
            "dd_values_used": False,
            "dd_ranks_used": False,
            "external_rankings_used_for_score": False,
            "market_values_used_for_score": False,
        },
        "validation": {
            "ready_for_live_consumers": False,
            "duplicate_identity_count": 0,
            "required_fields_complete": True,
        },
        "players": players,
    }


def _prospect(**overrides):
    row = {
        "id": "vc_prospect_1_hitter",
        "player_type": "prospect",
        "name": "Model Strong",
        "mlbam_id": 1,
        "role": "hitter",
        "positions": ["SS"],
        "team": "BOS",
        "age": 20,
        "rank": 1,
        "value": 55.5,
        "value_scale": "0_100_valucast_dynasty_score",
        "value_source": "prospect_model_v0_6",
        "confidence": "medium",
        "updated_at": "2026-06-16T00:00:00+00:00",
        "prospect_rank": 1,
        "level": "AA",
        "score_source": "prospect_model_v0_6",
        "stat_line": {"pa": 224, "ops": 0.976, "iso": 0.261, "k_pct": 12.9, "bb_pct": 9.8},
        "peak_projection": {"peak_score": 60.0, "summary": "Peak read: regular bat."},
        "context": {
            "stat_line_source": "valucast_input_contract",
            "stat_line_source_kind": "current_season",
            "stat_line_sample": 224,
            "stat_line_sample_unit": "PA",
            "stat_line_sample_season": 2026,
            "stat_line_level": "AA",
        },
    }
    row.update(overrides)
    return row


def test_prospect_card_data_audit_passes_clean_top_card(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(_snapshot([_prospect()])), encoding="utf-8")
    freshness_path = tmp_path / "freshness.json"
    freshness_path.write_text(
        json.dumps({
            "status": "candidate_ready",
            "generated_at": "2026-06-16T00:00:00+00:00",
            "metrics": {
                "top50_history_fallback_count": 0,
                "top50_stat_context_mismatch_count": 0,
            },
        }),
        encoding="utf-8",
    )

    payload = build_prospect_card_data_audit(
        snapshot_path=snapshot_path,
        freshness_audit_path=freshness_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["status"] == "candidate_ready"
    assert payload["validation"]["ready_for_cards"] is True
    assert payload["metrics"]["top200_count"] == 1
    assert payload["cards"][0]["status"] == "ready"
    assert payload["source_policy"]["feeds_public_rank"] is False


def test_prospect_card_data_audit_allows_active_mlb_callup_bridge(tmp_path):
    snapshot_path = tmp_path / "snapshot.json"
    row = _prospect(level="MLB", active_mlb_callup_bridge=True)
    row["context"] = {
        **row["context"],
        "graduation_context": {
            "status": "active_mlb_callup",
            "graduated": True,
            "surface": "active_mlb_roster_bridge",
            "previous_level": "AAA",
            "reason": "official_mlb_active_roster_without_mlb_projection_row",
        },
    }
    snapshot_path.write_text(json.dumps(_snapshot([row])), encoding="utf-8")

    payload = build_prospect_card_data_audit(
        snapshot_path=snapshot_path,
        freshness_audit_path=tmp_path / "missing_freshness.json",
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["status"] == "candidate_ready"
    assert payload["validation"]["ready_for_cards"] is True
    assert payload["cards"][0]["status"] == "ready"
    assert payload["cards"][0]["has_graduated"] is True


def test_prospect_card_data_audit_validator_catches_duplicate_identity(tmp_path):
    payload = build_prospect_card_data_audit(
        snapshot_path=tmp_path / "missing.json",
        generated_at="2026-06-16T00:00:00+00:00",
    )
    payload["cards"] = [
        {"identity_key": "1_hitter", "status": "ready", "problems": []},
        {"identity_key": "1_hitter", "status": "ready", "problems": []},
    ]
    artifact_path = tmp_path / "audit.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _payload, problems = validate_prospect_card_data_audit(artifact_path)

    assert any("duplicate identity_key" in problem for problem in problems)
