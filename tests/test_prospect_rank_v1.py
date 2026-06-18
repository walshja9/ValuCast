"""Tests for the candidate shadow ValuCast Prospect Rank v1 artifact."""
import json

from prospects.rank_v1 import (
    BUCKET_CALIBRATION_VERSION,
    FACTUAL_CURRENT_CONTEXT_VERSION,
    LOWER_MINORS_PEDIGREE_SCORE_ADJUSTMENT,
    PROHIBITED_SCORE_INPUTS,
    UPPER_LEVEL_HITTER_LOW_IMPACT_ADJUSTMENT,
    UPPER_LEVEL_HITTER_LOW_IMPACT_ISO,
    UPPER_LEVEL_HITTER_LOW_IMPACT_OPS,
    UPPER_LEVEL_HITTER_LOW_IMPACT_SAMPLE_PA,
    _input_lookup,
    _validation,
    build_prospect_rank_v1,
    run_prospect_rank_v1,
)


def test_dd_factual_fallback_counts_are_reported():
    # The factual display path still reads DD for some rows; the validation block must
    # quantify it honestly rather than assert blanket independence.
    board = [
        {"score": 50, "rank": 1, "context_only": {
            "stat_line_translated_source": "valucast_owned", "mlb_stat_line_source": None}},
        {"score": 40, "rank": 2, "context_only": {
            "stat_line_translated_source": "dd_feed_fallback", "mlb_stat_line_source": "dd_feed"}},
        {"score": 30, "rank": 3, "context_only": {
            "stat_line_translated_source": None, "mlb_stat_line_source": None}},
    ]
    fallback = _validation({}, {}, {}, None, board, board, [], 0, set(), 0, [])["dd_factual_fallback"]
    assert fallback["translated_valucast_owned"] == 1
    assert fallback["translated_dd_feed_fallback"] == 1
    assert fallback["translated_absent"] == 1
    assert fallback["mlb_stat_line_from_dd_feed"] == 1
    assert fallback["factual_path_fully_valucast_owned"] is False


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


def test_input_lookup_prefers_promoted_level_over_larger_old_stint():
    contract = {
        "current": {
            "hitters": [
                {
                    "mlbam_id": 805796,
                    "name": "Arjun Nimmala",
                    "level": "A+",
                    "age": 20,
                    "position": "SS",
                    "plate_appearances": 105,
                    "sample_season": 2026,
                    "source_kind": "current_season",
                },
                {
                    "mlbam_id": 805796,
                    "name": "Arjun Nimmala",
                    "level": "AA",
                    "age": 20,
                    "position": "SS",
                    "plate_appearances": 72,
                    "sample_season": 2026,
                    "source_kind": "current_season",
                },
            ]
        }
    }

    selected = _input_lookup(contract)[("805796", "hitter")]

    assert selected["level"] == "AA"


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


def _availability():
    return {
        "artifact": "valucast_prospect_availability",
        "artifact_version": "0.1.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "profile_count": 2,
        "profiles": [
            {
                "mlbam_id": 1,
                "role": "hitter",
                "status": "available",
                "risk_level": "clear",
                "risk_discount": 0.0,
                "availability_note": "Current sample is active.",
                "signals": [],
                "sample": 200,
                "sample_unit": "PA",
                "sample_fetched_date": "2026-06-13",
                "sample_staleness_days": 0,
                "present": True,
            },
            {
                "mlbam_id": 2,
                "role": "hitter",
                "age": 21,
                "status": "thin_current_sample",
                "risk_level": "medium",
                "risk_discount": 0.06,
                "availability_note": "Thin sample.",
                "signals": ["thin_upper_level_hitter_sample_under_100_pa"],
                "sample": 90,
                "sample_unit": "PA",
                "sample_fetched_date": "2026-06-13",
                "sample_staleness_days": 0,
                "present": True,
            },
        ],
    }


def test_rank_v1_uses_real_validation_gates_not_shadow_blockers():
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        dd_adapter=_adapter(),
        dd_feed=_feed(),
    )
    assert payload["status"] == "blocked"
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["feeds_live_valucast_rank"] is False
    assert payload["promotion"]["feeds_live_dd_value"] is False
    assert payload["validation"]["public_migration_ready"] is False
    assert payload["validation"]["ready_to_replace_dd_feed"] is False
    assert payload["validation"]["blockers"] == [
        "Top-200 score separation is not strong enough for publication."
    ]
    assert payload["rank_contract"]["dd_values_used_for_score"] is False
    assert payload["rank_contract"]["external_rankings_used_for_score"] is False
    assert payload["rank_contract"]["prohibited_score_inputs"] == PROHIBITED_SCORE_INPUTS


def test_rank_v1_applies_bounded_availability_discount():
    original = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )
    changed = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        prospect_availability=_availability(),
    )

    original_row = next(row for row in original["board"] if row["mlbam_id"] == 2)
    changed_row = next(row for row in changed["board"] if row["mlbam_id"] == 2)

    assert changed_row["score"] == round(original_row["score"] * 0.94, 2)
    assert changed_row["components"]["score_before_availability_adjustment"] == original_row["score"]
    assert changed_row["components"]["availability_risk_discount"] == 0.06
    assert changed_row["components"]["availability_adjusted"] is True
    assert changed_row["components"]["availability"]["status"] == "thin_current_sample"
    assert changed_row["age"] == 21
    assert changed["input_artifacts"]["prospect_availability_version"] == "0.1.0"


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
    feed["players"][0]["stat_line"] = {"ops": 0.900, "pa": 200}
    feed["players"][0]["stat_line_translated"] = {"stats": {"OPS": 0.760}}
    feed["players"][0]["mlb_stat_line"] = {"pa": 12, "ops": 0.700}
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
    assert context["stat_line"] == {"ops": 0.900, "pa": 200}
    assert context["stat_line_translated"] == {"stats": {"OPS": 0.760}}
    assert context["mlb_stat_line"] == {"pa": 12, "ops": 0.700}


def test_rank_v1_exposes_valucast_current_stats_without_dd_context():
    input_contract = _input_contract()
    input_contract["current"]["hitters"][1].update(
        {
            "avg": 0.252,
            "obp": 0.336,
            "slg": 0.390,
            "ops": 0.726,
            "iso": 0.138,
            "k_pct": 28.6,
            "bb_pct": 7.9,
        }
    )

    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
        dd_feed={"schema_version": "1.1", "players": []},
    )

    context = next(row for row in payload["board"] if row["mlbam_id"] == 2)[
        "context_only"
    ]
    assert context["has_dd_context"] is False
    assert context["stat_line_source"] == "valucast_input_contract"
    assert context["stat_line_sample"] == 150
    assert context["stat_line_sample_unit"] == "PA"
    assert context["stat_line"] == {
        "avg": 0.252,
        "obp": 0.336,
        "slg": 0.39,
        "ops": 0.726,
        "iso": 0.138,
        "k_pct": 28.6,
        "bb_pct": 7.9,
        "pa": 150,
    }


def test_rank_v1_prefers_newest_current_input_row_over_larger_old_sample():
    input_contract = _input_contract()
    input_contract["current"]["pitchers"] = [
        {
            "mlbam_id": 8,
            "name": "Current Pitcher",
            "level": "AAA",
            "sample_season": 2026,
            "source_kind": "current_season",
            "innings_pitched": 25.333,
            "era": 4.26,
            "whip": 1.58,
            "k_per_9": 8.53,
            "bb_per_9": 5.33,
            "k_bb_pct": 8.0,
            "games_started": 6,
        },
        {
            "mlbam_id": 8,
            "name": "Current Pitcher",
            "level": "AAA",
            "sample_season": 2024,
            "source_kind": "latest_milb_history",
            "innings_pitched": 79.0,
            "era": 7.97,
            "whip": 1.77,
            "k_per_9": 11.62,
            "bb_per_9": 4.56,
            "k_bb_pct": 16.8,
            "games_started": 18,
        },
    ]
    universe = _universe(
        [
            {
                "mlbam_id": 8,
                "name": "Current Pitcher",
                "normalized_name": "current pitcher",
                "role": "pitcher",
                "positions": ["P"],
                "mlb_team": "DET",
                "age": 26,
                "level": "AAA",
                "sample_reliability": 0.3,
                "universe_source": "valucast_prospect_dynasty_layer",
            }
        ]
    )
    pitcher_profile = _profile(8, 0.7)
    pitcher_profile.update({"role": "pitcher", "position": "P", "level": "AAA"})
    dynasty_layer = _dynasty_layer()
    dynasty_layer["profiles"].append(pitcher_profile)

    payload = build_prospect_rank_v1(
        universe,
        dynasty_layer,
        _prospect_model(),
        input_contract,
        dd_feed={"schema_version": "1.1", "players": []},
    )

    row = next(item for item in payload["board"] if item["mlbam_id"] == 8)
    assert row["context_only"]["stat_line"] == {
        "era": 4.26,
        "whip": 1.58,
        "k_per_9": 8.5,
        "bb_per_9": 5.3,
        "k_bb_pct": 8.0,
        "ip": 25.3,
    }
    assert row["context_only"]["stat_line_source"] == "valucast_input_contract"
    assert row["context_only"]["stat_line_source_kind"] == "current_season"
    assert row["context_only"]["stat_line_sample_season"] == 2026
    assert row["context_only"]["stat_line_sample"] == 25.333
    assert row["components"]["factual_current_context"]["sample"] == 25.3
    assert row["components"]["factual_current_context"]["era"] == 4.26
    assert row["components"]["factual_current_context"]["source_kind"] == "current_season"
    assert row["components"]["factual_current_context"]["sample_season"] == 2026
    assert payload["validation"]["current_stat_context_mismatch_count"] == 0


def test_rank_v1_prefers_valucast_current_stat_line_over_dd_display_context():
    input_contract = _input_contract()
    input_contract["current"]["hitters"][0].update(
        {
            "source_kind": "current_season",
            "sample_season": 2026,
            "avg": 0.281,
            "obp": 0.351,
            "slg": 0.511,
            "ops": 0.862,
            "iso": 0.230,
            "k_pct": 18.0,
            "bb_pct": 11.2,
        }
    )
    feed = _feed()
    feed["players"][0]["stat_line"] = {"ops": 0.610, "pa": 300}

    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
        dd_feed=feed,
    )

    context = next(row for row in payload["board"] if row["mlbam_id"] == 1)[
        "context_only"
    ]
    assert context["stat_line_source"] == "valucast_input_contract"
    assert context["stat_line_source_kind"] == "current_season"
    assert context["stat_line"]["ops"] == 0.862
    assert context["stat_line"]["pa"] == 200


def test_rank_v1_surfaces_near_graduation_context():
    input_contract = _input_contract()
    input_contract["mlb_service"] = [
        {"mlbam_id": 1, "role": "hitter", "ab": 119.0, "pa": 130.0, "ip": 0.0, "graduated": False},
        {"mlbam_id": 2, "role": "hitter", "ab": 12.0, "pa": 15.0, "ip": 0.0, "graduated": False},
    ]
    input_contract["rookie_limits"] = {"at_bats": 131, "innings_pitched": 51}

    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
    )

    near = next(row for row in payload["board"] if row["mlbam_id"] == 1)[
        "context_only"
    ]["graduation_context"]
    far = next(row for row in payload["board"] if row["mlbam_id"] == 2)["context_only"]
    assert near["status"] == "near_graduation"
    assert near["current"] == 119.0
    assert near["limit"] == 131.0
    assert near["score_effect"] == "display_only_not_used_for_valucast_score"
    assert "graduation_context" not in far


def test_rank_v1_exposes_factual_current_context_for_hitter_components():
    input_contract = _input_contract()
    input_contract["current"]["hitters"][0].update(
        {
            "level": "AA",
            "plate_appearances": 260,
            "ops": 0.881,
            "iso": 0.214,
            "k_pct": 21.2,
            "bb_pct": 12.4,
        }
    )

    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
    )

    row = next(item for item in payload["board"] if item["mlbam_id"] == 1)
    context = row["components"]["factual_current_context"]

    assert context["version"] == FACTUAL_CURRENT_CONTEXT_VERSION
    assert context["role"] == "hitter"
    assert context["level"] == "AA"
    assert context["sample"] == 260
    assert context["sample_unit"] == "PA"
    assert context["skill_band"] == "impact"
    assert context["ops"] == 0.881
    assert context["iso"] == 0.214
    assert context["bb_minus_k_pct"] == -8.8
    assert payload["rank_contract"]["factual_current_context"]["version"] == (
        FACTUAL_CURRENT_CONTEXT_VERSION
    )
    assert payload["rank_contract"]["factual_current_context"]["source"] == (
        "validated_prospect_input_contract_current_rows"
    )
    uncertainty = row["components"]["uncertainty"]
    assert uncertainty["kind"] == "display_only_score_interval"
    assert uncertainty["score_effect"] == "none"
    assert uncertainty["band"] in {"tight", "moderate", "wide"}
    assert uncertainty["lower"] < row["score"] < uncertainty["upper"]


def test_rank_v1_exposes_factual_current_context_for_pitcher_components():
    universe = {
        "schema_version": "1.0",
        "artifact": "valucast_prospect_universe",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "candidate_count": 1,
        "players": [
            {
                "mlbam_id": 8,
                "name": "Starter Shape",
                "normalized_name": "starter shape",
                "role": "pitcher",
                "positions": ["SP"],
                "level": "AA",
            }
        ],
    }
    layer_profile = _profile(8, 0.88)
    layer_profile.update({"role": "pitcher", "level": "AA"})
    dynasty_layer = {
        "status": "shadow_only",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "layer_version": "0.1.0",
        "profiles": [layer_profile],
    }
    input_contract = {
        "schema_version": "1.1",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "current": {
            "hitters": [],
            "pitchers": [
                {
                    "mlbam_id": 8,
                    "name": "Starter Shape",
                    "level": "AA",
                    "innings_pitched": 54.1,
                    "games_started": 10,
                    "is_starter": True,
                    "era": 2.81,
                    "whip": 1.05,
                    "k_per_9": 11.7,
                    "bb_per_9": 3.1,
                    "k_bb_pct": 22.4,
                }
            ],
        },
    }

    payload = build_prospect_rank_v1(
        universe,
        dynasty_layer,
        {"status": "shadow_only", "model_version": "0.6.0", "ranked": []},
        input_contract,
    )

    context = payload["board"][0]["components"]["factual_current_context"]
    assert context["version"] == FACTUAL_CURRENT_CONTEXT_VERSION
    assert context["role"] == "pitcher"
    assert context["sample"] == 54.1
    assert context["sample_unit"] == "IP"
    assert context["starter_role"] is True
    assert context["skill_band"] == "starter_volume"
    assert context["k_bb_pct"] == 22.4


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
    assert row["components"]["pedigree_score_cap"] >= 48
    assert row["components"]["pedigree_cap_compressed"] is True
    assert row["components"]["bucket_calibration"]["bucket"] == "lower_minors_pedigree_score_source"
    assert row["score"] > 41.75
    assert row["score"] < row["components"]["pedigree_score_cap"]


def test_rank_v1_applies_lower_minors_pedigree_bucket_calibration():
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
    )

    row = next(item for item in payload["board"] if item["mlbam_id"] == 2)
    calibration = row["components"]["bucket_calibration"]

    assert row["score_source"] == "prospect_pedigree_v0_7"
    assert calibration["version"] == BUCKET_CALIBRATION_VERSION
    assert calibration["adjustment"] == LOWER_MINORS_PEDIGREE_SCORE_ADJUSTMENT
    assert row["score"] == round(
        row["components"]["score_before_bucket_calibration"]
        + LOWER_MINORS_PEDIGREE_SCORE_ADJUSTMENT,
        2,
    )
    assert payload["rank_contract"]["bucket_calibration"]["scope"] == (
        "score_source_level_and_factual_current_stat_bucket_only"
    )


def test_rank_v1_does_not_bucket_adjust_upper_level_pedigree_profiles():
    input_contract = _input_contract()
    input_contract["current"]["hitters"][1].update(
        {
            "age": 20,
            "level": "AA",
            "plate_appearances": 220,
            "draft_pick_number": 1,
            "signing_bonus": 8_200_000,
            "school_type": "college",
        }
    )
    universe = _universe()
    universe["players"][1]["level"] = "AA"

    payload = build_prospect_rank_v1(
        universe,
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
    )

    row = next(item for item in payload["board"] if item["mlbam_id"] == 2)

    assert row["score_source"] == "prospect_pedigree_v0_7"
    assert "bucket_calibration" not in row["components"]


def test_rank_v1_bucket_adjusts_thin_upper_level_pitcher_model_samples():
    universe = {
        "schema_version": "1.0",
        "artifact": "valucast_prospect_universe",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "candidate_count": 1,
        "players": [
            {
                "mlbam_id": 3,
                "name": "Thin Upper Pitcher",
                "normalized_name": "thin upper pitcher",
                "role": "pitcher",
                "positions": ["SP"],
                "mlb_team": "MIA",
                "age": 21,
                "level": "AAA",
                "eta": 2027,
                "universe_source": "valucast_prospect_dynasty_layer",
            }
        ],
    }
    layer_profile = _profile(3, 0.9)
    layer_profile.update(
        {
            "name": "Thin Upper Pitcher",
            "normalized_name": "thin upper pitcher",
            "role": "pitcher",
            "position": "SP",
            "level": "AAA",
            "sample": 24.2,
            "sample_unit": "IP",
            "sample_reliability": 0.32,
        }
    )
    dynasty_layer = {
        "status": "shadow_only",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "layer_version": "0.1.0",
        "profiles": [layer_profile],
    }
    prospect_model = {
        "status": "shadow_only",
        "model_version": "0.6.0",
        "ranked": [
            {
                "mlbam_id": 3,
                "name": "Thin Upper Pitcher",
                "normalized_name": "thin upper pitcher",
                "role": "pitcher",
                "expected_outcome_score": 0.64,
                "expected_category_impact_score": 0.58,
                "sample_reliability": 0.32,
                "role_gate": "active",
                "impact_gate": "active",
            }
        ],
    }
    input_contract = {
        "schema_version": "1.1",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "current": {
            "hitters": [],
            "pitchers": [
                {
                    "mlbam_id": 3,
                    "name": "Thin Upper Pitcher",
                    "age": 21,
                    "level": "AAA",
                    "innings_pitched": 24.2,
                }
            ],
        },
    }

    payload = build_prospect_rank_v1(
        universe,
        dynasty_layer,
        prospect_model,
        input_contract,
    )

    row = payload["board"][0]
    calibration = row["components"]["bucket_calibration"]

    assert row["score_source"] == "prospect_model_v0_6"
    assert calibration["version"] == BUCKET_CALIBRATION_VERSION
    assert calibration["bucket"] == "upper_level_thin_pitcher_model_sample"
    assert calibration["adjustment"] == -2.0
    assert calibration["rules"][0]["sample_threshold"] == 30.0
    assert row["score"] == round(
        row["components"]["score_before_bucket_calibration"] - 2.0,
        2,
    )


def test_rank_v1_bucket_adjusts_upper_level_low_impact_hitter_model_samples():
    universe = _universe()
    universe["players"][0]["level"] = "AAA"
    input_contract = _input_contract()
    input_contract["current"]["hitters"][0].update(
        {
            "level": "AAA",
            "plate_appearances": 250,
            "iso": 0.079,
            "ops": 0.694,
        }
    )

    payload = build_prospect_rank_v1(
        universe,
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
    )

    row = next(item for item in payload["board"] if item["mlbam_id"] == 1)
    calibration = row["components"]["bucket_calibration"]

    assert row["score_source"] == "prospect_model_v0_6"
    assert calibration["version"] == BUCKET_CALIBRATION_VERSION
    assert calibration["bucket"] == "upper_level_low_impact_hitter_model_sample"
    assert calibration["adjustment"] == UPPER_LEVEL_HITTER_LOW_IMPACT_ADJUSTMENT
    assert calibration["rules"][0]["sample_threshold"] == (
        UPPER_LEVEL_HITTER_LOW_IMPACT_SAMPLE_PA
    )
    assert calibration["rules"][0]["iso_threshold"] == UPPER_LEVEL_HITTER_LOW_IMPACT_ISO
    assert calibration["rules"][0]["ops_threshold"] == UPPER_LEVEL_HITTER_LOW_IMPACT_OPS
    assert row["score"] == round(
        row["components"]["score_before_bucket_calibration"]
        + UPPER_LEVEL_HITTER_LOW_IMPACT_ADJUSTMENT,
        2,
    )


def test_run_prospect_rank_v1_writes_artifact_and_archive(tmp_path):
    universe_path = tmp_path / "universe.json"
    feed_path = tmp_path / "feed.json"
    layer_path = tmp_path / "layer.json"
    model_path = tmp_path / "model.json"
    input_path = tmp_path / "input.json"
    availability_path = tmp_path / "availability.json"
    adapter_path = tmp_path / "adapter.json"
    artifact_path = tmp_path / "rank.json"

    universe_path.write_text(json.dumps(_universe()), encoding="utf-8")
    feed_path.write_text(json.dumps(_feed()), encoding="utf-8")
    layer_path.write_text(json.dumps(_dynasty_layer()), encoding="utf-8")
    model_path.write_text(json.dumps(_prospect_model()), encoding="utf-8")
    input_path.write_text(json.dumps(_input_contract()), encoding="utf-8")
    availability_path.write_text(json.dumps(_availability()), encoding="utf-8")
    adapter_path.write_text(json.dumps(_adapter()), encoding="utf-8")

    result = run_prospect_rank_v1(
        prospect_universe_path=universe_path,
        dynasty_layer_path=layer_path,
        prospect_model_path=model_path,
        input_contract_path=input_path,
        availability_path=availability_path,
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
    assert payload["board"][0]["components"]["availability"]["present"] is True
    assert (tmp_path / "archive" / "2026-06-13.json").exists()
