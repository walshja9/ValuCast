import json

from scouting.repository import build_scouting_repository
from scripts.validate_scouting_repository import validate_scouting_repository


def _write_snapshot(tmp_path):
    payload = {
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
        "players": [
            {
                "id": "vc_prospect_1_hitter",
                "player_type": "prospect",
                "name": "Model Strong",
                "mlbam_id": 1,
                "role": "hitter",
                "positions": ["SS"],
                "team": "BOS",
                "mlb_team": "BOS",
                "age": 20,
                "rank": 1,
                "value": 55.5,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "prospect_model_v0_6",
                "confidence": "medium",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "prospect_rank": 1,
                "level": "AA",
                "eta": 2027,
                "score_source": "prospect_model_v0_6",
                "stat_line": {
                    "pa": 224,
                    "ops": 0.976,
                    "iso": 0.261,
                    "k_pct": 12.9,
                    "bb_pct": 9.8,
                    "avg": 0.318,
                    "obp": 0.397,
                    "slg": 0.579,
                },
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 224,
                    "stat_line_sample_unit": "PA",
                    "stat_line_sample_season": 2026,
                },
            },
            {
                "id": "vc_prospect_2_pitcher",
                "player_type": "prospect",
                "name": "Starter Arm",
                "mlbam_id": 2,
                "role": "pitcher",
                "positions": ["SP"],
                "team": "SEA",
                "mlb_team": "SEA",
                "age": 21,
                "rank": 2,
                "value": 50.0,
                "value_scale": "0_100_valucast_dynasty_score",
                "value_source": "prospect_model_v0_6",
                "confidence": "medium",
                "updated_at": "2026-06-16T00:00:00+00:00",
                "status": "candidate_ready",
                "prospect_rank": 2,
                "level": "AA",
                "eta": 2027,
                "score_source": "prospect_model_v0_6",
                "stat_line": {
                    "ip": 55.7,
                    "k_per_9": 13.3,
                    "bb_per_9": 1.1,
                    "k_bb_pct": 37.7,
                    "era": 1.13,
                    "whip": 0.66,
                },
                "context": {
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 55.7,
                    "stat_line_sample_unit": "IP",
                    "stat_line_sample_season": 2026,
                },
            },
        ],
    }
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_scouting_repository_builds_stat_grounded_reports(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)

    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["artifact"] == "valucast_scouting_report_repository"
    assert payload["source_policy"]["llm_generated"] is False
    assert payload["source_policy"]["external_rankings_used_for_report"] is False
    assert payload["validation"]["ready_for_repository"] is True
    assert payload["summary"]["report_count"] == 2
    assert payload["reports"][0]["report"]
    assert payload["reports"][0]["usage"] == "scouting_repository_context_not_live_rank_or_value"


def test_scouting_repository_validator_blocks_robotic_copy(tmp_path):
    snapshot_path = _write_snapshot(tmp_path)
    payload = build_scouting_repository(
        snapshot_path=snapshot_path,
        generated_at="2026-06-16T00:00:00+00:00",
    )
    payload["reports"][0]["report"] = "This display-only artifact is useful."
    artifact_path = tmp_path / "reports.json"
    artifact_path.write_text(json.dumps(payload), encoding="utf-8")

    _, problems = validate_scouting_repository(artifact_path)

    assert any("display-only" in problem for problem in problems)
