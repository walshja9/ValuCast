"""Tests for the candidate shadow ValuCast Prospect Rank v1 artifact."""
import json

import pytest
import prospects.rank_v1 as rank_v1

from prospects.rank_v1 import (
    BUCKET_CALIBRATION_VERSION,
    FACTUAL_CURRENT_CONTEXT_VERSION,
    LOWER_MINORS_PEDIGREE_SCORE_ADJUSTMENT,
    PROHIBITED_SCORE_INPUTS,
    UPPER_LEVEL_HITTER_LOW_IMPACT_ADJUSTMENT,
    UPPER_LEVEL_HITTER_LOW_IMPACT_ISO,
    UPPER_LEVEL_HITTER_LOW_IMPACT_OPS,
    UPPER_LEVEL_HITTER_LOW_IMPACT_SAMPLE_PA,
    _bucket_calibration_adjustment,
    _confidence,
    _input_lookup,
    _sample_reliability_score,
    _universal_outcome_index,
    _with_verified_investment_facts,
    build_prospect_rank_v1,
    run_prospect_rank_v1,
)


def test_layer_reliability_wins_over_model_profile():
    # 0.3.2: layer-profile precedence restored (0.3.0 order). The 0.3.1
    # model-first swap was reverted by the registered study's SPLIT-REMEDIATE
    # verdict (2026-07-29 design doc); model profile is fallback only.
    assert _sample_reliability_score(
        {"sample_reliability": 0.20},
        {"sample_reliability": 0.573},
    ) == 20.0
    assert _sample_reliability_score(
        {},
        {"sample_reliability": 0.573},
    ) == 57.3


def test_tiny_return_sample_cannot_penalize_prior_model_more_than_inactivity():
    _, components = _bucket_calibration_adjustment(
        42.25,
        "prospect_model_v0_6",
        None,
        {"role": "pitcher", "level": "A", "draft_pick_number": 245},
        {"role": "pitcher", "level": "A"},
        {
            "availability": {
                "status": "thin_current_sample",
                "sample": 3.0,
                "sample_unit": "IP",
            },
            "factual_current_context": {
                "source_kind": "current_season",
                "sample_season": 2026,
                "sample": 3.0,
            },
            "sample_reliability": 72.5,
        },
        {
            "current_season": 2026,
            "rows": [
                {
                    "season": 2025,
                    "role": "pitcher",
                    "innings_pitched": 132.0,
                    "k_bb_pct": 15.6,
                }
            ],
        },
    )

    rule = components["bucket_calibration"]["rules"][0]
    assert rule["adjustment"] == -11.52
    assert rule["continuity_floor_applied"] is True


def _investment_evidence(**overrides):
    row = {
        "mlbam_id": 2,
        "name": "Fallback Good",
        "acquisition_type": "international_amateur_free_agent",
        "signing_bonus": 950_000,
        "source_name": "MLB Pipeline",
        "source_url": "https://www.mlb.com/example",
        "source_checked_at": "2026-07-22",
    }
    row.update(overrides)
    return {
        "artifact": "valucast_international_signing_facts",
        "as_of": "2026-07-22",
        "source_policy": {
            "kind": "factual_rank_input",
            "feeds_rank_score": True,
            "feeds_v06_model": False,
            "feeds_universal_model": False,
            "changes_ranks_or_values": True,
            "permitted_use": "prospect_rank_v1_factual_investment_context_only",
        },
        "rows": [row],
    }


def test_verified_investment_overlay_fills_missing_bonus_without_mutating_contract():
    contract = _input_contract()

    corrected, audit = _with_verified_investment_facts(
        contract, _investment_evidence()
    )

    assert corrected["current"]["hitters"][1]["signing_bonus"] == 950_000
    assert "signing_bonus" not in contract["current"]["hitters"][1]
    assert audit == {
        "artifact": "valucast_international_signing_facts",
        "as_of": "2026-07-22",
        "applied_count": 1,
        "idempotent_count": 0,
    }


def test_verified_investment_overlay_accepts_identical_existing_bonus():
    corrected, audit = _with_verified_investment_facts(
        _input_contract(), _investment_evidence(mlbam_id=1, signing_bonus=4_000_000)
    )

    assert corrected["current"]["hitters"][0]["signing_bonus"] == 4_000_000
    assert audit["applied_count"] == 0
    assert audit["idempotent_count"] == 1


def test_verified_investment_overlay_changes_only_rank_input_component():
    baseline = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), _input_contract()
    )
    corrected = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        investment_evidence=_investment_evidence(),
    )

    baseline_row = next(row for row in baseline["board"] if row["mlbam_id"] == 2)
    corrected_row = next(row for row in corrected["board"] if row["mlbam_id"] == 2)
    assert baseline_row["components"]["factual_investment_context"] is None
    assert corrected_row["components"]["factual_investment_context"] == 68.12
    assert corrected_row["score"] > baseline_row["score"]
    assert corrected["input_artifacts"]["investment_evidence_applied_count"] == 1


@pytest.mark.parametrize(
    "evidence, message",
    [
        (
            lambda: {
                **_investment_evidence(),
                "rows": _investment_evidence()["rows"] * 2,
            },
            "duplicate",
        ),
        (
            lambda: _investment_evidence(acquisition_type="rule_4_draft"),
            "acquisition_type",
        ),
        (lambda: _investment_evidence(source_url=""), "source_url"),
        (lambda: _investment_evidence(mlbam_id=999), "unmatched"),
        (
            lambda: _investment_evidence(mlbam_id=1, signing_bonus=3_000_000),
            "conflict",
        ),
        (
            lambda: {
                **_investment_evidence(),
                "source_policy": {
                    **_investment_evidence()["source_policy"],
                    "changes_ranks_or_values": False,
                },
            },
            "policy",
        ),
    ],
)
def test_verified_investment_overlay_fails_closed(evidence, message):
    with pytest.raises(ValueError, match=message):
        _with_verified_investment_facts(_input_contract(), evidence())


def test_universal_outcome_index_excludes_star_ceiling():
    # 7/7: star_probability fails its own held-out validation gate (worse than
    # a naive historical-neighbor baseline for hitters; below the promotion
    # threshold for pitchers), while role/regular-probability passes. The old
    # formula (role*50 + star*100, or the equivalent expected_factual_outcome_tier
    # = role + 2*star shortcut) let the losing signal outweigh the winning one
    # 2:1 inside a component that drives 15-76% of live rank. Two prospects
    # with IDENTICAL role-or-better odds but very different star upside must
    # now score identically here -- star must contribute nothing.
    # role_or_better_probability = role + star (cumulative, per decision_signal
    # in prospects/dynasty.py) -- both fixtures hold the pure role component at
    # 0.5 constant and only vary star, so role_or_better differs accordingly.
    high_star = {"dynasty_signal": {
        "role_or_better_probability": 0.9, "star_ceiling_probability": 0.4,
        "expected_factual_outcome_tier": 1.7,
    }}
    low_star = {"dynasty_signal": {
        "role_or_better_probability": 0.5, "star_ceiling_probability": 0.0,
        "expected_factual_outcome_tier": 0.5,
    }}
    assert _universal_outcome_index(high_star) == _universal_outcome_index(low_star) == 25.0

    # A pure role_probability/star_probability distribution (no dynasty_signal
    # tier shortcut) must fall back the same way -- role only, no star.
    dist_high_star = {"outcome_distribution": {"role_probability": 0.3, "star_probability": 0.4}}
    dist_low_star = {"outcome_distribution": {"role_probability": 0.3, "star_probability": 0.0}}
    assert _universal_outcome_index(dist_high_star) == _universal_outcome_index(dist_low_star) == 15.0

    # Missing/empty profile still degrades safely to 0, not an exception.
    assert _universal_outcome_index(None) == 0.0
    assert _universal_outcome_index({}) == 0.0


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


def test_input_lookup_prefers_scored_max_sample_line_over_promoted_level():
    # INV-SELECT-1 (scored == shown): _input_row_sort_key selects the max-sample
    # current line (mirroring model._select_current_records), so the displayed line
    # is the one that produced the value -- the bigger A+ stint, not the thinner AA
    # promotion. The promotion stays surfaced via the roster/universe display level.
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

    assert selected["level"] == "A+"


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
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "profiles": [_profile(1, 0.9), _profile(2, 0.8)],
    }


def _prospect_model():
    return {
        "status": "shadow_only",
        "model_version": "0.6.0",
        "input_contract": {"generated_at": "2026-06-13T12:00:00+00:00"},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
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
                    "source_kind": "current_season",
                    "plate_appearances": 200,
                    "draft_pick_number": 10,
                    "signing_bonus": 4_000_000,
                },
                {
                    "mlbam_id": 2,
                    "name": "Fallback Good",
                    "source_kind": "current_season",
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


def _mlb_roster_status(active_ids=None, *, ready=True):
    return {
        "artifact": "valucast_mlb_roster_status",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "validation": {"ready_for_public_snapshot": ready},
        "profiles": [
            {"mlbam_id": mlbam_id, "active_mlb_roster": True}
            for mlbam_id in (active_ids or [])
        ],
    }


def test_rank_v1_uses_real_validation_gates_not_shadow_blockers():
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )
    assert payload["status"] == "blocked"
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["feeds_live_valucast_rank"] is False
    assert payload["promotion"]["feeds_live_dd_value"] is False
    assert payload["validation"]["public_migration_ready"] is False
    assert payload["validation"]["blockers"] == [
        "Top-200 score separation is not strong enough for publication."
    ]
    assert payload["rank_contract"]["dd_values_used_for_score"] is False
    assert payload["rank_contract"]["external_rankings_used_for_score"] is False
    assert payload["rank_contract"]["prohibited_score_inputs"] == PROHIBITED_SCORE_INPUTS


def test_rank_v1_is_invariant_to_external_context_mutation(monkeypatch):
    public_rank = {"value": 1}

    def fake_snapshot(path):
        field = {
            rank_v1.STS_CONSENSUS_PATH: "sts_rank",
            rank_v1.FG_FV_SNAPSHOT_PATH: "fg_top100",
            rank_v1.PROSPECTSLIVE_PATH: "pl_rank",
            rank_v1.PIPELINE_PATH: "pipeline_rank",
            rank_v1.HKB_PATH: "hkb_rank",
        }[path]
        return {
            "1": {
                field: public_rank["value"],
                "fv": public_rank["value"],
                "competitor_score": public_rank["value"],
                "market_value": public_rank["value"],
            }
        }

    monkeypatch.setattr(rank_v1, "_snapshot_by_mlbam", fake_snapshot)
    first = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), _input_contract()
    )
    public_rank["value"] = 999
    second = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), _input_contract()
    )

    scored = lambda payload: [
        (row["mlbam_id"], row["score"], row["rank"])
        for row in payload["board"]
    ]
    assert scored(first) == scored(second)
    first_context = next(
        row["context_only"] for row in first["board"] if row["mlbam_id"] == 1
    )
    second_context = next(
        row["context_only"] for row in second["board"] if row["mlbam_id"] == 1
    )
    assert first_context["source_ranks"] != second_context["source_ranks"]


def test_rank_v1_retains_rookie_eligible_active_roster_identities():
    # Rookie-rule retention (7/2): roster membership alone is not graduation — a
    # call-up who hasn't crossed the AB/IP rookie line stays RANKED (Hughes case).
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        mlb_roster_status=_mlb_roster_status([1]),
        require_mlb_roster_status=True,
    )

    board_ids = {row["mlbam_id"] for row in payload["board"]}

    assert 1 in board_ids
    assert 2 in board_ids
    # Retained rows are stamped so archived board days record who was in the
    # majors at that date (AOTC featured/enrollment key off this); pure
    # minor-leaguers must NOT carry the key at all.
    by_id = {row["mlbam_id"]: row for row in payload["board"]}
    assert by_id[1].get("active_mlb_roster") is True
    assert "active_mlb_roster" not in by_id[2]
    assert payload["candidate_count"] == 2
    assert payload["ranked_count"] == 2
    assert payload["validation"]["mlb_roster_status_ready"] is True
    assert payload["validation"]["active_mlb_roster_excluded_count"] == 0
    assert payload["validation"]["active_mlb_roster_overlap_count"] == 1
    assert payload["validation"]["graduated_roster_overlap_count"] == 0
    assert payload["validation"]["blockers"] != [
        "Graduated active-roster identities remain on the prospect board."
    ]


def test_rank_v1_excludes_graduated_active_roster_identities():
    input_contract = _input_contract()
    input_contract["mlb_service"] = [
        {"mlbam_id": 1, "role": "hitter", "ab": 200.0, "pa": 220.0, "ip": 0.0, "graduated": True},
    ]
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
        mlb_roster_status=_mlb_roster_status([1]),
        require_mlb_roster_status=True,
    )

    board_ids = {row["mlbam_id"] for row in payload["board"]}

    assert 1 not in board_ids
    assert 2 in board_ids
    assert payload["validation"]["active_mlb_roster_excluded_count"] == 1
    assert payload["validation"]["graduated_roster_overlap_count"] == 0


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


def test_rank_v1_ignores_removed_dd_feed_context():
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )

    row = next(row for row in payload["board"] if row["mlbam_id"] == 1)
    context = row["context_only"]
    assert row["name"] == "Model Strong"
    assert row["positions"] == ["SS"]
    assert row["mlb_team"] == "BOS"
    assert row["eta"] == 2027
    for key in ("value_history_points", "mlb_stat_line", "mlb_stat_line_source"):
        assert key not in context
    validation = payload["validation"]
    assert "ready_to_replace_dd_feed" not in validation
    assert "dd_factual_fallback" not in validation
    assert "dd_feed_context" not in validation["generated_dates"]
    for key in ("dd_feed_generated_by", "dd_feed_source", "dd_feed_schema_version"):
        assert key not in payload["input_artifacts"]


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
    )

    context = next(row for row in payload["board"] if row["mlbam_id"] == 2)[
        "context_only"
    ]
    assert "has_dd_context" not in context
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
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
    )

    context = next(row for row in payload["board"] if row["mlbam_id"] == 1)[
        "context_only"
    ]
    assert context["stat_line_source"] == "valucast_input_contract"
    assert context["stat_line_source_kind"] == "current_season"
    assert context["stat_line"]["ops"] == 0.862
    assert context["stat_line"]["pa"] == 200


def test_rank_v1_uses_owned_translation_for_qualifying_current_milb_rows():
    milb_history_by_key = {
        ("1", "hitter"): {
            "current_season": 2026,
            "rows": [
                {
                    "role": "hitter",
                    "season": 2026,
                    "level": "AA",
                    "plate_appearances": 200,
                    "k_pct": 21.0,
                    "bb_pct": 12.0,
                    "iso": 0.180,
                }
            ],
        }
    }

    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
        milb_history_by_key=milb_history_by_key,
    )

    context = next(row for row in payload["board"] if row["mlbam_id"] == 1)[
        "context_only"
    ]
    assert context["stat_line_translated"] is not None
    assert context["stat_line_translated_source"] == "valucast_owned"


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


def test_rank_v1_derives_eta_window_from_level_when_eta_missing():
    universe = _universe()
    universe["players"][0].pop("eta")

    payload = build_prospect_rank_v1(
        universe,
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )

    row = next(item for item in payload["board"] if item["mlbam_id"] == 1)
    assert row["eta"] is None
    assert row["eta_window"] == "one_to_two_years"


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
    # Graded on MLB-equivalent peripherals: the raw AA line (.881 OPS / .214 ISO)
    # cools to translated ISO .157 / BB-K -13.4, so it is "mixed", not "impact".
    assert context["rate_scale"] == "mlb_equivalent"
    assert context["skill_band"] == "mixed"
    assert "ops" not in context  # OPS is not translatable, dropped from the line
    assert context["iso"] == 0.157
    assert context["k_pct"] == 23.3
    assert context["bb_pct"] == 9.9
    assert context["bb_minus_k_pct"] == -13.4
    assert payload["rank_contract"]["factual_current_context"]["version"] == (
        FACTUAL_CURRENT_CONTEXT_VERSION
    )
    assert payload["rank_contract"]["factual_current_context"]["source"] == (
        "validated_prospect_input_contract_current_rows"
    )
    assert set(payload["rank_contract"]["factual_current_context"]["hitter_fields"]) == {
        "level", "sample", "source_kind", "sample_season", "rate_scale",
        "iso", "k_pct", "bb_pct", "bb_minus_k_pct", "skill_band",
        "iso_milb", "ops_milb",
    }
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
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
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
        {
            "status": "shadow_only",
            "model_version": "0.6.0",
            "input_contract": {"generated_at": "2026-06-13T12:00:00+00:00"},
            "release_contract": {
                "consumer": "prospect_rank_v1",
                "feeds_live_valucast_rank": True,
            },
            "ranked": [],
        },
        input_contract,
    )

    context = payload["board"][0]["components"]["factual_current_context"]
    assert context["version"] == FACTUAL_CURRENT_CONTEXT_VERSION
    assert context["role"] == "pitcher"
    assert context["sample"] == 54.1
    assert context["sample_unit"] == "IP"
    assert context["starter_role"] is True
    assert context["skill_band"] == "starter_volume"
    # Peripherals are graded on the MLB-equivalent scale, not the raw AA line
    # (raw k_bb_pct=22.4 -> translated 14.9); ERA/WHIP stay raw for Run Prevention.
    assert context["rate_scale"] == "mlb_equivalent"
    assert context["k_bb_pct"] == 14.9
    assert context["k_per_9"] == 9.1
    assert context["bb_per_9"] == 3.3
    assert context["era"] == 2.81
    assert context["whip"] == 1.05
    assert set(payload["rank_contract"]["factual_current_context"]["pitcher_fields"]) == {
        "level", "sample", "source_kind", "sample_season", "rate_scale",
        "starter_role", "era", "whip", "k_per_9", "bb_per_9", "k_bb_pct",
        "skill_band",
    }


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


def test_rank_v1_reports_the_served_stage1_contract():
    payload = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), _input_contract()
    )
    assert payload["input_artifacts"]["stage1_contract_version"] == "1.0.0"
    assert payload["input_artifacts"]["stage1_state"] == "incumbent"
    assert payload["input_artifacts"]["stage1_profile_count"] == 2


def test_rank_v1_rejects_a_research_stage1_state():
    with pytest.raises(ValueError, match="Stage 1 state"):
        build_prospect_rank_v1(
            _universe(),
            _dynasty_layer(),
            _prospect_model(),
            _input_contract(),
            stage1_state="research",
        )


def test_rank_v1_rejects_noncanonical_stage1_role_before_scoring():
    prospect_model = _prospect_model()
    prospect_model["ranked"][0]["role"] = "HITTER"

    with pytest.raises(ValueError, match="role"):
        build_prospect_rank_v1(
            _universe(),
            _dynasty_layer(),
            prospect_model,
            _input_contract(),
        )


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


def test_rank_v1_candidate_membership_comes_from_valucast_universe():
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )

    assert payload["candidate_count"] == 2
    assert {row["mlbam_id"] for row in payload["board"]} == {1, 2}


def test_rank_v1_does_not_require_dd_feed_context():
    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        _input_contract(),
    )

    assert payload["candidate_count"] == 2
    assert payload["ranked_count"] == 2
    assert all(
        "has_dd_context" not in row["context_only"] for row in payload["board"]
    )


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
    )

    row = next(item for item in payload["board"] if item["name"] == "Fallback Good")

    assert row["score_source"] == "prospect_pedigree_v0_7"
    # Pedigree-led value no longer forces "low" confidence: with a substantial
    # current sample (220 PA) the read is "medium" even though scoring leans on
    # pedigree. Genuinely thin samples still read "low" (see test below).
    assert row["confidence"] == "medium"
    assert row["components"]["factual_investment_context"] >= 90
    assert row["components"]["age_level_context"] > 80
    assert row["components"]["pedigree_score_cap"] >= 48
    assert row["components"]["pedigree_cap_compressed"] is True
    assert row["components"]["bucket_calibration"]["bucket"] == "lower_minors_pedigree_score_source"
    assert row["score"] > 41.75
    assert row["score"] < row["components"]["pedigree_score_cap"]


def test_pedigree_confidence_tracks_current_sample_not_score_source():
    """A pedigree-scored prospect with a real current sample reads "medium";
    a genuinely thin sample (<50 PA) still reads "low". Confidence reflects the
    current evidence, not the fact that value is pedigree-led."""
    thin = _input_contract()
    thin["current"]["hitters"][1].update(
        {"age": 18, "level": "A", "plate_appearances": 40,
         "draft_pick_number": 1, "signing_bonus": 8_200_000,
         "school_type": "high_school"}
    )
    thin_payload = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), thin
    )
    thin_row = next(r for r in thin_payload["board"] if r["name"] == "Fallback Good")
    assert thin_row["score_source"] == "prospect_pedigree_v0_7"
    assert thin_row["confidence"] == "low"

    full = _input_contract()
    full["current"]["hitters"][1].update(
        {"age": 18, "level": "A", "plate_appearances": 220,
         "draft_pick_number": 1, "signing_bonus": 8_200_000,
         "school_type": "high_school"}
    )
    full_payload = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), full
    )
    full_row = next(r for r in full_payload["board"] if r["name"] == "Fallback Good")
    assert full_row["score_source"] == "prospect_pedigree_v0_7"
    assert full_row["confidence"] == "medium"


def test_model_scored_high_confidence_requires_a_non_thin_current_sample():
    """The model-scored branch may only return "high" when the model gates AND a
    real current sample agree. A model-strong profile over a thin/absent current
    line caps at "medium" -- "high" must never sit on essentially no MLB/MiLB line."""
    model_profile = {"role_gate": "active", "impact_gate": "active"}
    # Same model-strong inputs, only the current sample band differs.
    assert _confidence(
        "model_scored", model_profile, 60.0, {"skill_band": "solid"}
    ) == "high"
    assert _confidence(
        "model_scored", model_profile, 60.0, {"skill_band": "thin"}
    ) == "medium"
    # No current context at all is treated as thin -> medium, never high.
    assert _confidence("model_scored", model_profile, 60.0, None) == "medium"


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


def test_rank_v1_excludes_two_season_stale_prospects_from_board():
    # A prospect whose newest stat line is two or more seasons old hasn't played
    # competitively in a full year-plus, so they leave the board entirely. A
    # one-season-stale prospect still ranks (just penalized behind current
    # evidence). The exclusion is counted so coverage stays honest.
    input_contract = _input_contract()
    input_contract["current"]["hitters"][1].update(
        {
            "source_kind": "latest_milb_history",
            "sample_staleness_years": 2,
        }
    )

    payload = build_prospect_rank_v1(
        _universe(),
        _dynasty_layer(),
        _prospect_model(),
        input_contract,
    )

    board_ids = {row["mlbam_id"] for row in payload["board"]}
    assert 2 not in board_ids
    assert 1 in board_ids
    assert payload["validation"]["stale_inactive_excluded_count"] == 1

    # One season stale stays on the board.
    one_stale = _input_contract()
    one_stale["current"]["hitters"][1].update(
        {"source_kind": "latest_milb_history", "sample_staleness_years": 1}
    )
    one_payload = build_prospect_rank_v1(
        _universe(), _dynasty_layer(), _prospect_model(), one_stale
    )
    assert 2 in {row["mlbam_id"] for row in one_payload["board"]}
    assert one_payload["validation"]["stale_inactive_excluded_count"] == 0


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
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "profiles": [layer_profile],
    }
    prospect_model = {
        "status": "shadow_only",
        "model_version": "0.6.0",
        "input_contract": {"generated_at": "2026-06-13T12:00:00+00:00"},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
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
                    "source_kind": "current_season",
                    "age": 21,
                    "level": "AAA",
                    "innings_pitched": 24.2,
                }
            ],
        },
    }

    availability = {
        "artifact": "valucast_prospect_availability",
        "artifact_version": "0.1.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "profile_count": 1,
        "profiles": [
            {
                "mlbam_id": 3,
                "role": "pitcher",
                "status": "thin_current_sample",
                "risk_level": "medium",
                "risk_discount": 0.03,
                "availability_note": "Thin sample.",
                "signals": ["limited_upper_level_starter_workload_under_45_ip"],
                "sample": 24.2,
                "sample_unit": "IP",
                "sample_fetched_date": "2026-06-13",
                "sample_staleness_days": 0,
                "present": True,
            }
        ],
    }

    payload = build_prospect_rank_v1(
        universe,
        dynasty_layer,
        prospect_model,
        input_contract,
        prospect_availability=availability,
    )

    row = payload["board"][0]
    calibration = row["components"]["bucket_calibration"]

    # A thin upper-level pitcher sample is ranked by a lower-confidence bound:
    # the score is pulled down by a penalty that scales with (1 - reliability),
    # using the same thin_current_sample signal the quality governor checks.
    assert row["score_source"] == "prospect_model_v0_6"
    assert calibration["version"] == BUCKET_CALIBRATION_VERSION
    assert calibration["bucket"] == "thin_current_sample_confidence"
    # Meaningfully larger than the old token -2.0 flat adjustment.
    assert calibration["adjustment"] <= -5.0
    assert calibration["rules"][0]["bucket"] == "thin_current_sample_confidence"
    assert row["score"] == round(
        row["components"]["score_before_bucket_calibration"]
        + calibration["adjustment"],
        2,
    )


def _thin_penalty(
    *,
    role,
    sample,
    status,
    blended_reliability=None,
    served_sample=None,
):
    """Item A harness: the thin + moderate-thin adjustments for one profile."""
    from prospects.rank_v1 import _bucket_calibration_adjustment

    regression = 50.0 if role == "pitcher" else 200.0
    reliability = (
        blended_reliability
        if blended_reliability is not None
        else round(100.0 * sample / (sample + regression), 2)
    )
    factual_context = {"source_kind": "current_season", "role": role}
    if served_sample is not None:
        factual_context["sample"] = served_sample
    components = {
        "factual_current_context": factual_context,
        "availability": {
            "status": status,
            "sample": sample,
            "sample_unit": "IP" if role == "pitcher" else "PA",
        },
        "sample_reliability": reliability,
    }
    _, comp = _bucket_calibration_adjustment(
        30.0, "prospect_model_v0_6", None, {}, {"role": role, "level": "AAA"},
        components,
    )
    rules = (comp.get("bucket_calibration") or {}).get("rules") or []
    by_bucket = {rule["bucket"]: rule["adjustment"] for rule in rules}
    return (
        by_bucket.get("thin_current_sample_confidence", 0.0),
        by_bucket.get("moderate_thin_sample_confidence", 0.0),
    )


def test_thin_sample_penalty_has_no_boundary_cliffs():
    """Epoch-batch item A: the thin penalty tapers to zero as current-sample
    reliability approaches the ramp, so the availability status flip at each
    IP/PA floor hands the row to the moderate-thin haircut with a bounded
    step (<= ~2.6 pts) instead of the verified 11-15 pt cliffs (44.9 vs
    45.0 IP was +15.38)."""
    # (role, availability floor, sweep lo, sweep hi) -- status flips at the
    # floor exactly as prospects/availability.py assigns it.
    boundaries = [("pitcher", 45.0, 43.0, 47.0), ("pitcher", 30.0, 28.0, 32.0),
                  ("pitcher", 12.0, 10.0, 14.0), ("hitter", 150.0, 147.0, 153.0),
                  ("hitter", 100.0, 97.0, 103.0)]
    for role, floor, lo, hi in boundaries:
        prev = None
        sample = lo
        while sample <= hi:
            status = "thin_current_sample" if sample < floor else "available"
            thin, moderate = _thin_penalty(role=role, sample=sample, status=status)
            # Exactly one haircut per row (populations unchanged).
            assert thin == 0.0 or moderate == 0.0, (role, sample)
            total = thin + moderate
            if prev is not None:
                assert abs(total - prev) <= 2.6, (role, floor, sample, prev, total)
            prev = total
            sample += 0.5
    # Anchors: deep-thin keeps a large penalty; a full sample takes none.
    deep, _ = _thin_penalty(
        role="pitcher", sample=2.0, status="thin_current_sample")
    assert deep < -20.0
    thin, moderate = _thin_penalty(
        role="pitcher", sample=120.0, status="available")
    assert thin == 0.0 and moderate == 0.0


def test_thin_sample_handoff_is_bounded_when_model_reliability_lags_sample():
    before = sum(
        _thin_penalty(
            role="pitcher",
            sample=44.9,
            status="thin_current_sample",
            blended_reliability=24.6,
        )
    )
    after = sum(
        _thin_penalty(
            role="pitcher",
            sample=45.0,
            status="available",
            blended_reliability=24.6,
        )
    )

    assert abs(after - before) <= 2.6


def test_thin_penalty_ignores_blended_reliability_at_served_sample():
    # 0.3.2: the thin penalty is always based on current_reliability (0.3.0
    # behavior). The 0.3.1 rebasing to full-history/blended reliability for
    # rows at/above the served-sample floor zeroed -11.5..-13.2 penalties
    # board-wide and was reverted by the registered study's SPLIT-REMEDIATE
    # verdict. Guard: wildly different blended reliabilities must produce the
    # identical thin adjustment for the same current sample.
    low_blend, _ = _thin_penalty(
        role="hitter",
        sample=147.0,
        status="thin_current_sample",
        blended_reliability=31.7,
        served_sample=93.0,
    )
    high_blend, _ = _thin_penalty(
        role="hitter",
        sample=147.0,
        status="thin_current_sample",
        blended_reliability=95.0,
        served_sample=93.0,
    )
    current_only, _ = _thin_penalty(
        role="hitter",
        sample=147.0,
        status="thin_current_sample",
    )

    assert low_blend == high_blend
    assert low_blend < 0.0
    # blended_reliability also feeds the branch gate (`reliability is not
    # None`), so equality with the no-blend case proves the magnitude comes
    # from current_reliability alone.
    assert low_blend == current_only


def test_gs_reclassification_step_is_bounded():
    """Item A: the GS 2->3 starter reclassification at 20 IP flipped which
    floor applied (12 vs 30 IP) and previously moved the score -14.17. With
    the taper, the reclassification hand-off between the two haircuts is a
    bounded ~2 pt step."""
    # As a 3-GS starter at 20 IP: under the 30 IP floor -> flagged thin.
    starter_thin, starter_moderate = _thin_penalty(
        role="pitcher", sample=20.0, status="thin_current_sample")
    # As a 2-GS reliever at 20 IP: above the 12 IP floor -> unflagged.
    reliever_thin, reliever_moderate = _thin_penalty(
        role="pitcher", sample=20.0, status="available")
    assert starter_thin < 0.0 and starter_moderate == 0.0
    assert reliever_thin == 0.0 and reliever_moderate < 0.0
    step = abs(
        (starter_thin + starter_moderate) - (reliever_thin + reliever_moderate)
    )
    assert step <= 2.6, step


def _three_hitter_board(*, active_ids, graduated_ids):
    """Item B harness: 3 hitters with distinct raw model scores; id 11 can be
    an active-roster call-up (retained or graduated via mlb_service)."""
    players = []
    profiles = []
    ranked = []
    current = []
    for mlbam_id, outcome, impact in ((11, 0.9, 0.8), (12, 0.6, 0.5), (13, 0.3, 0.2)):
        players.append({
            "mlbam_id": mlbam_id,
            "name": f"Pool Hitter {mlbam_id}",
            "normalized_name": f"pool hitter {mlbam_id}",
            "role": "hitter",
            "positions": ["SS"],
            "mlb_team": "BOS",
            "age": 21,
            "level": "AAA",
            "eta": 2026,
            "universe_source": "valucast_prospect_dynasty_layer",
        })
        profile = _profile(mlbam_id, 0.8)
        profile["name"] = f"Pool Hitter {mlbam_id}"
        profile["normalized_name"] = f"pool hitter {mlbam_id}"
        profiles.append(profile)
        ranked.append({
            "mlbam_id": mlbam_id,
            "name": f"Pool Hitter {mlbam_id}",
            "normalized_name": f"pool hitter {mlbam_id}",
            "role": "hitter",
            "expected_outcome_score": outcome,
            "expected_category_impact_score": impact,
            "sample_reliability": 0.6,
            "role_gate": "active",
            "impact_gate": "active",
        })
        current.append({
            "mlbam_id": mlbam_id,
            "name": f"Pool Hitter {mlbam_id}",
            "source_kind": "current_season",
            "plate_appearances": 250,
        })
    universe = {
        "schema_version": "1.0",
        "artifact": "valucast_prospect_universe",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "candidate_count": len(players),
        "players": players,
    }
    dynasty_layer = {
        "status": "shadow_only",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "layer_version": "0.1.0",
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "profiles": profiles,
    }
    prospect_model = {
        "status": "shadow_only",
        "model_version": "0.6.0",
        "input_contract": {"generated_at": "2026-06-13T12:00:00+00:00"},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "ranked": ranked,
    }
    input_contract = {
        "schema_version": "1.1",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "current": {"hitters": current, "pitchers": []},
        "mlb_service": [
            {"mlbam_id": mlbam_id, "role": "hitter", "ab": 50.0, "pa": 60.0,
             "ip": 0.0, "graduated": mlbam_id in graduated_ids}
            for mlbam_id in (11, 12, 13)
        ],
    }
    return build_prospect_rank_v1(
        universe,
        dynasty_layer,
        prospect_model,
        input_contract,
        mlb_roster_status=_mlb_roster_status(list(active_ids)),
        require_mlb_roster_status=True,
    )


def _role_percentiles(payload):
    out = {}
    for row in payload["board"]:
        fields = (row["components"].get("model_score_normalization") or {}).get(
            "fields") or {}
        outcome = fields.get("expected_outcome_score") or {}
        out[row["mlbam_id"]] = outcome.get("role_percentile")
    return out


def test_retained_callup_shares_the_board_normalization_pool():
    """Epoch-batch item B: a retained (non-graduated) rookie call-up stays on
    the main board and must share the board's Pass-2 normalization pool. The
    old predicate excluded ALL active-roster ids, leaving the call-up on
    Pass-1 full-universe values while neighbors used the board distribution."""
    payload = _three_hitter_board(active_ids=[11], graduated_ids=set())
    pcts = _role_percentiles(payload)
    # One 3-row pool: percentiles (i+1)/(N+1) = 0.75 / 0.5 / 0.25. Under the
    # old split, 12 would carry 2/3 (a 2-row pool) while 11 kept 0.75.
    assert pcts[11] == 0.75
    assert pcts[12] == 0.5
    assert pcts[13] == 0.25


def test_graduated_callup_stays_out_of_the_board_pool():
    payload = _three_hitter_board(active_ids=[11], graduated_ids={11})
    board_ids = {row["mlbam_id"] for row in payload["board"]}
    assert 11 not in board_ids
    pcts = _role_percentiles(payload)
    # The graduated id is off the board AND out of the pool: 2-row pool.
    assert pcts[12] == round(2 / 3, 6)
    assert pcts[13] == round(1 / 3, 6)


def test_no_current_season_penalty_is_prior_pedigree_injury_aware_and_destacked():
    from prospects.rank_v1 import _bucket_calibration_adjustment

    def adj(*, role="pitcher", sample, prod, input_row=None, status="stale_or_inactive",
            risk_basis=None, risk_discount=0.0, sba=30.0):
        prodkey = "k_bb_pct" if role == "pitcher" else "ops"
        components = {
            "factual_current_context": {
                "source_kind": "latest_milb_history", "role": role,
                "sample": sample, prodkey: prod,
            },
            "availability": {"status": status, "risk_basis": risk_basis,
                             "risk_discount": risk_discount},
            "score_before_availability_adjustment": sba,
        }
        _, comp = _bucket_calibration_adjustment(
            30.0, "prospect_model_v0_6", None, input_row or {},
            {"role": role, "level": "AAA"}, components)
        return comp["bucket_calibration"]["adjustment"]

    weak = adj(sample=5, prod=0.0)        # no prior evidence -> full flat hit
    strong = adj(sample=80, prod=20.0)    # full, productive prior -> softened
    assert weak == -20.0, weak
    assert -12.0 < strong < -6.0, strong          # ~-8, much softer than flat -20
    # Draft pedigree softens further (large-N outcome signal).
    pedigreed = adj(sample=80, prod=20.0, input_row={"draft_pick_number": 10})
    assert pedigreed > strong, (pedigreed, strong)
    # Genuine injury (involuntary absence) softens further still.
    injured = adj(sample=80, prod=20.0, status="injured")
    assert injured > strong, (injured, strong)
    # De-stack: a staleness haircut already taken is credited back (less negative).
    destacked = adj(sample=80, prod=20.0, risk_basis="sample_staleness",
                    risk_discount=0.1, sba=30.0)
    assert destacked > strong, (destacked, strong)
    # Hitters are softened LESS than pitchers for the same prior (no historical
    # analogs -> cautious): a strong-prior hitter keeps more of the penalty.
    hitter_strong = adj(role="hitter", sample=400, prod=0.850)
    assert hitter_strong < strong, (hitter_strong, strong)
    assert -16.0 < hitter_strong < -12.0, hitter_strong


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


def test_run_rank_v1_leaves_previous_artifact_on_stage1_rejection(tmp_path):
    universe_path = tmp_path / "universe.json"
    layer_path = tmp_path / "layer.json"
    model_path = tmp_path / "model.json"
    input_path = tmp_path / "input.json"
    artifact_path = tmp_path / "rank.json"
    universe_path.write_text(json.dumps(_universe()), encoding="utf-8")
    bad_layer = _dynasty_layer()
    bad_layer["release_contract"]["feeds_live_valucast_rank"] = False
    layer_path.write_text(json.dumps(bad_layer), encoding="utf-8")
    model_path.write_text(json.dumps(_prospect_model()), encoding="utf-8")
    input_path.write_text(json.dumps(_input_contract()), encoding="utf-8")
    artifact_path.write_text("previous promoted artifact", encoding="utf-8")

    with pytest.raises(ValueError, match="not authorized"):
        run_prospect_rank_v1(
            prospect_universe_path=universe_path,
            dynasty_layer_path=layer_path,
            prospect_model_path=model_path,
            input_contract_path=input_path,
            availability_path=None,
            mlb_roster_status_path=None,
            artifact_path=artifact_path,
            archive_dir=tmp_path / "archive",
        )
    assert artifact_path.read_text(encoding="utf-8") == "previous promoted artifact"


def test_run_prospect_rank_v1_writes_artifact_and_archive(tmp_path):
    universe_path = tmp_path / "universe.json"
    layer_path = tmp_path / "layer.json"
    model_path = tmp_path / "model.json"
    input_path = tmp_path / "input.json"
    availability_path = tmp_path / "availability.json"
    roster_status_path = tmp_path / "roster_status.json"
    investment_evidence_path = tmp_path / "investment_evidence.json"
    artifact_path = tmp_path / "rank.json"

    universe_path.write_text(json.dumps(_universe()), encoding="utf-8")
    layer_path.write_text(json.dumps(_dynasty_layer()), encoding="utf-8")
    model_path.write_text(json.dumps(_prospect_model()), encoding="utf-8")
    input_path.write_text(json.dumps(_input_contract()), encoding="utf-8")
    availability_path.write_text(json.dumps(_availability()), encoding="utf-8")
    roster_status_path.write_text(
        json.dumps(_mlb_roster_status()),
        encoding="utf-8",
    )
    investment_evidence_path.write_text(
        json.dumps(_investment_evidence()), encoding="utf-8"
    )

    with pytest.raises(FileNotFoundError):
        run_prospect_rank_v1(
            prospect_universe_path=universe_path,
            dynasty_layer_path=layer_path,
            prospect_model_path=model_path,
            input_contract_path=input_path,
            investment_evidence_path=tmp_path / "missing-evidence.json",
            availability_path=availability_path,
            mlb_roster_status_path=roster_status_path,
            artifact_path=artifact_path,
            archive_dir=tmp_path / "archive",
        )

    result = run_prospect_rank_v1(
        prospect_universe_path=universe_path,
        dynasty_layer_path=layer_path,
        prospect_model_path=model_path,
        input_contract_path=input_path,
        investment_evidence_path=investment_evidence_path,
        availability_path=availability_path,
        mlb_roster_status_path=roster_status_path,
        artifact_path=artifact_path,
        archive_dir=tmp_path / "archive",
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["ranked_count"] == 2
    assert result["live_consumer"] == "blocked"
    assert result["archive_changed"] is True
    assert payload["board"][0]["rank"] == 1
    assert payload["board"][0]["components"]["availability"]["present"] is True
    assert payload["input_artifacts"]["investment_evidence_applied_count"] == 1
    assert "dd_adapter_version" not in payload["input_artifacts"]
    assert (tmp_path / "archive" / "2026-06-13.json").exists()
