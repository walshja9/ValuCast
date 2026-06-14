"""Tests for the candidate shadow ValuCast Prospect Rank v1 artifact."""
import json

from prospects.rank_v1 import (
    PROHIBITED_SCORE_INPUTS,
    build_prospect_rank_v1,
    run_prospect_rank_v1,
)


def _feed(extra_players=None):
    players = [
        {
            "id": "p1",
            "player_type": "prospect",
            "name": "Model Strong",
            "mlbam_id": 1,
            "positions": ["SS"],
            "mlb_team": "BOS",
            "age": 20,
            "dynasty_rank": 80,
            "dynasty_value": 60.0,
            "level": "AA",
            "eta": 2027,
            "prospect_rank": 40,
            "source_ranks": {"pipeline": 12},
            "value_history": [["2026-06-13", 60.0]],
        },
        {
            "id": "p2",
            "player_type": "prospect",
            "name": "Fallback Good",
            "mlbam_id": 2,
            "positions": ["SS"],
            "mlb_team": "MIL",
            "age": 19,
            "dynasty_rank": 20,
            "dynasty_value": 80.0,
            "level": "A+",
            "eta": 2028,
            "prospect_rank": 2,
            "source_ranks": {"pipeline": 1},
            "value_history": [["2026-06-13", 80.0]],
        },
    ]
    players.extend(extra_players or [])
    return {
        "schema_version": "1.1",
        "generated_at": "2026-06-13T12:00:00",
        "generated_by": "diamond_dynasties",
        "source": "diamond_dynasties",
        "players": players,
    }


def _universe(extra_players=None):
    players = [
        {
            "mlbam_id": 1,
            "name": "Model Strong",
            "normalized_name": "model strong",
            "role": "hitter",
            "positions": ["SS"],
            "mlb_team": "BOS",
            "age": 20,
            "level": "AA",
            "eta": 2027,
            "sample_reliability": 0.6,
            "universe_source": "valucast_prospect_dynasty_layer",
        },
        {
            "mlbam_id": 2,
            "name": "Fallback Good",
            "normalized_name": "fallback good",
            "role": "hitter",
            "positions": ["SS"],
            "mlb_team": "MIL",
            "age": 19,
            "level": "A+",
            "eta": 2028,
            "sample_reliability": 0.5,
            "universe_source": "valucast_prospect_dynasty_layer",
        },
    ]
    players.extend(extra_players or [])
    return {
        "schema_version": "1.0",
        "artifact": "valucast_prospect_universe",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "candidate_count": len(players),
        "players": players,
    }


def _profile(mlbam_id, tier, reliability=0.6):
    role_probability = min(1.0, tier)
    star_probability = max(0.0, tier - 1.0)
    if tier <= 1.0:
        role_probability = tier
        star_probability = 0.0
    return {
        "mlbam_id": mlbam_id,
        "name": f"Prospect {mlbam_id}",
        "normalized_name": f"prospect {mlbam_id}",
        "role": "hitter",
        "position": "SS",
        "team": "AA Club",
        "age": 20,
        "level": "AA",
        "sample": 200,
        "sample_unit": "PA",
        "sample_reliability": reliability,
        "outcome_distribution": {
            "bust_probability": round(1.0 - role_probability, 4),
            "role_probability": round(role_probability - star_probability, 4),
            "star_probability": round(star_probability, 4),
        },
        "dynasty_signal": {
            "bust_risk": round(1.0 - role_probability, 4),
            "role_or_better_probability": round(role_probability, 4),
            "star_ceiling_probability": round(star_probability, 4),
            "expected_factual_outcome_tier": tier,
            "outcome_uncertainty": 0.5,
        },
    }


def _dynasty_layer():
    return {
        "status": "shadow_only",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "layer_version": "0.1.0",
        "profiles": [_profile(1, 0.9), _profile(2, 0.8)],
    }


def _prospect_model():
    return {
        "status": "shadow_only",
        "model_version": "0.6.0",
        "ranked": [
            {
                "mlbam_id": 1,
                "name": "Model Strong",
                "normalized_name": "model strong",
                "role": "hitter",
                "expected_outcome_score": 0.72,
                "expected_category_impact_score": 0.62,
                "sample_reliability": 0.6,
                "role_gate": "active",
                "impact_gate": "active",
                "drivers": ["ops +0.10"],
                "impact_drivers": ["iso +0.05"],
            }
        ],
    }


def _input_contract():
    return {
        "schema_version": "1.1",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "current": {
            "hitters": [
                {
                    "mlbam_id": 1,
                    "name": "Model Strong",
                    "plate_appearances": 200,
                    "draft_pick_number": 10,
                    "signing_bonus": 4_000_000,
                },
                {
                    "mlbam_id": 2,
                    "name": "Fallback Good",
                    "plate_appearances": 150,
                },
            ],
            "pitchers": [],
        },
    }


def _adapter():
    return {
        "adapter_version": "0.1.0",
        "roles": {
            "hitter": {
                "players": [
                    {"mlbam_id": 1, "adapter_score": 12.0, "adapter_rank": 30},
                    {"mlbam_id": 2, "adapter_score": 99.0, "adapter_rank": 1},
                ]
            }
        },
    }


def test_rank_v1_is_candidate_shadow_and_blocks_live_consumers():
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        dd_adapter=_adapter(),
        dd_feed=_feed(),
    )
    assert payload["status"] == "candidate_shadow"
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["feeds_live_valucast_rank"] is False
    assert payload["promotion"]["feeds_live_dd_value"] is False
    assert payload["rank_contract"]["dd_values_used_for_score"] is False
    assert payload["rank_contract"]["external_rankings_used_for_score"] is False
    assert payload["rank_contract"]["prohibited_score_inputs"] == PROHIBITED_SCORE_INPUTS


def test_dd_and_public_rank_context_does_not_change_scores():
    feed = _feed()
    adapter = _adapter()
    original = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        dd_adapter=adapter,
        dd_feed=feed,
    )
    original_score = {
        row["mlbam_id"]: row["score"] for row in original["board"]
    }

    feed["players"][0]["dynasty_rank"] = 1
    feed["players"][0]["dynasty_value"] = 150.0
    feed["players"][0]["prospect_rank"] = 1
    feed["players"][0]["source_ranks"] = {"pipeline": 1, "cfr": 1, "hkb": 1}
    feed["players"][0]["value_history"] = [["2026-06-13", 150.0]]
    adapter["roles"]["hitter"]["players"][0]["adapter_score"] = 999.0
    changed = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        dd_adapter=adapter,
        dd_feed=feed,
    )
    changed_score = {row["mlbam_id"]: row["score"] for row in changed["board"]}

    assert changed_score == original_score
    context = next(row for row in changed["board"] if row["mlbam_id"] == 1)[
        "context_only"
    ]
    assert context["dd_dynasty_value"] == 150.0
    assert context["source_ranks"]["pipeline"] == 1
    assert context["dd_adapter_context"]["adapter_score"] == 999.0


def test_rank_v1_reports_coverage_blockers_and_missing_top_names():
    payload = build_prospect_rank_v1(
        _universe(
            [
                {
                    "name": "Missing Layer",
                    "mlbam_id": 3,
                    "role": "hitter",
                    "positions": ["SS"],
                    "universe_source": "valucast_prospect_dynasty_layer",
                },
                {
                    "name": "No Identity",
                    "role": "hitter",
                    "positions": ["SS"],
                    "universe_source": "valucast_prospect_dynasty_layer",
                },
            ]
        ),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )
    validation = payload["validation"]
    assert validation["public_migration_ready"] is False
    assert validation["ready_to_replace_dd_feed"] is False
    assert validation["prospect_universe_count"] == 4
    assert validation["ranked_count"] == 3
    assert validation["missing_mlbam_count"] == 1
    assert validation["unmatched_dynasty_layer_count"] == 1
    assert validation["identity_only_fallback_count"] == 1
    assert validation["unmatched_sample"][0]["name"] == "Missing Layer"
    missing_layer = next(row for row in payload["board"] if row["name"] == "Missing Layer")
    assert missing_layer["score_source"] == "identity_only_fallback"
    assert missing_layer["confidence"] == "low"
    assert any("coverage" in blocker for blocker in validation["blockers"])


def test_rank_v1_uses_contiguous_ranks_and_flags_duplicate_identities():
    duplicate = {
        "name": "Model Strong Copy",
        "mlbam_id": 1,
        "role": "hitter",
        "positions": ["SS"],
    }
    payload = build_prospect_rank_v1(
        _universe([duplicate]),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )
    assert [row["rank"] for row in payload["board"]] == [1, 2]
    assert payload["validation"]["ranks_contiguous"] is True
    assert payload["validation"]["duplicate_identity_count"] == 1
    assert any("Duplicate MLBAM+role" in blocker for blocker in payload["validation"]["blockers"])


def test_rank_v1_candidate_membership_comes_from_valucast_universe_not_dd_feed():
    dd_extra = {
        "id": "p3",
        "player_type": "prospect",
        "name": "DD Only",
        "mlbam_id": 3,
        "positions": ["SS"],
        "dynasty_rank": 1,
        "dynasty_value": 150.0,
        "prospect_rank": 1,
    }

    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        dd_feed=_feed([dd_extra]),
    )

    assert payload["candidate_count"] == 2
    assert {row["mlbam_id"] for row in payload["board"]} == {1, 2}


def test_rank_v1_does_not_require_dd_feed_context():
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        dd_feed=None,
    )

    assert payload["candidate_count"] == 2
    assert payload["ranked_count"] == 2
    assert all(row["context_only"]["has_dd_context"] is False for row in payload["board"])


def test_elite_factual_fallback_uses_pedigree_v0_7_not_raw_fallback():
    input_contract = _input_contract()
    input_contract["current"]["hitters"][1].update(
        {
            "age": 18,
            "level": "A",
            "plate_appearances": 220,
            "draft_pick_number": 1,
            "signing_bonus": 8_200_000,
            "school_type": "high_school",
        }
    )
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
        dd_feed=_feed(),
    )

    row = next(item for item in payload["board"] if item["name"] == "Fallback Good")

    assert row["score_source"] == "prospect_pedigree_v0_7"
    assert row["confidence"] == "low"
    assert row["components"]["factual_investment_context"] >= 90
    assert row["components"]["age_level_context"] > 80
    assert row["components"]["pedigree_score_cap"] >= 49
    assert row["score"] > 41.75


def test_run_prospect_rank_v1_writes_artifact_and_archive(tmp_path):
    universe_path = tmp_path / "universe.json"
    feed_path = tmp_path / "feed.json"
    layer_path = tmp_path / "layer.json"
    model_path = tmp_path / "model.json"
    input_path = tmp_path / "input.json"
    adapter_path = tmp_path / "adapter.json"
    artifact_path = tmp_path / "rank.json"

    universe_path.write_text(json.dumps(_universe()), encoding="utf-8")
    feed_path.write_text(json.dumps(_feed()), encoding="utf-8")
    layer_path.write_text(json.dumps(_dynasty_layer()), encoding="utf-8")
    model_path.write_text(json.dumps(_prospect_model()), encoding="utf-8")
    input_path.write_text(json.dumps(_input_contract()), encoding="utf-8")
    adapter_path.write_text(json.dumps(_adapter()), encoding="utf-8")

    result = run_prospect_rank_v1(
        prospect_universe_path=universe_path,
        dynasty_layer_path=layer_path,
        prospect_model_path=model_path,
        input_contract_path=input_path,
        dd_adapter_path=adapter_path,
        dd_feed_path=feed_path,
        artifact_path=artifact_path,
        archive_dir=tmp_path / "archive",
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["ranked_count"] == 2
    assert result["live_consumer"] == "blocked"
    assert result["archive_changed"] is True
    assert payload["board"][0]["rank"] == 1
    assert (tmp_path / "archive" / "2026-06-13.json").exists()
