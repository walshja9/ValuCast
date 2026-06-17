"""Tests for the ValuCast public dynasty snapshot gate."""
import json
from datetime import date, timedelta
from types import SimpleNamespace

from scripts.build_public_dynasty_snapshot import (
    COMMON_VALUE_SCALE,
    GRAD_FLOOR_DECAY_DAYS,
    GRAD_FLOOR_DISCOUNT,
    _apply_graduation_transition_floor,
    build_snapshot,
)
from web.public_snapshot_store import (
    PublicSnapshotStore,
    validate_public_snapshot_payload,
)


def test_graduation_floor_lifts_crashed_value_for_fresh_callup():
    graduated = [
        {
            "mlbam_id": "806198",
            "name": "Cooper Pratt",
            "prospect_rank": 8,
            "value": 50.0,  # retained prospect score
            "context": {"graduation_context": {"ratio": 0.02}},
        }
    ]
    mlb_rows = [{"mlbam_id": "806198", "name": "Cooper Pratt", "value": 3.0}]

    applied = _apply_graduation_transition_floor(mlb_rows, graduated)

    assert applied == 1
    assert mlb_rows[0]["value"] == round(50.0 * GRAD_FLOOR_DISCOUNT * (1 - 0.02), 2)
    transition = mlb_rows[0]["graduation_transition"]
    assert transition["applied"] is True
    assert transition["raw_mlb_value"] == 3.0
    assert transition["prospect_value"] == 50.0


def test_graduation_floor_is_noop_when_mlb_value_already_exceeds_floor():
    graduated = [{"mlbam_id": "1", "value": 40.0, "context": {"graduation_context": {"ratio": 0.0}}}]
    mlb_rows = [{"mlbam_id": "1", "value": 60.0}]  # collision-promoted, already strong

    applied = _apply_graduation_transition_floor(mlb_rows, graduated)

    assert applied == 0
    assert mlb_rows[0]["value"] == 60.0
    assert mlb_rows[0]["graduation_transition"]["applied"] is False


def test_graduation_floor_fades_as_rookie_eligibility_exhausts():
    graduated = [{"mlbam_id": "2", "value": 50.0, "context": {"graduation_context": {"ratio": 1.0}}}]
    mlb_rows = [{"mlbam_id": "2", "value": 3.0}]

    applied = _apply_graduation_transition_floor(mlb_rows, graduated)

    assert applied == 0  # floor = 50 * 0.7 * (1 - 1.0) = 0, never lifts a real MLB value
    assert mlb_rows[0]["value"] == 3.0


def test_graduation_floor_decays_on_calendar_time_when_debut_known():
    as_of = "2026-06-13T12:00:00+00:00"
    days = max(1, GRAD_FLOOR_DECAY_DAYS // 3)  # well inside the window for any dial value
    debut = (date(2026, 6, 13) - timedelta(days=days)).isoformat()
    # rookie_ratio=1.0 would zero the floor; the debut date must drive it instead.
    graduated = [{"mlbam_id": "5", "value": 50.0, "context": {"graduation_context": {"ratio": 1.0}}}]
    mlb_rows = [{"mlbam_id": "5", "value": 3.0}]

    applied = _apply_graduation_transition_floor(
        mlb_rows, graduated, debut_by_id={"5": debut}, as_of_date=as_of
    )

    expected = round(50.0 * GRAD_FLOOR_DISCOUNT * (1 - days / GRAD_FLOOR_DECAY_DAYS), 2)
    assert applied == 1
    assert mlb_rows[0]["value"] == expected
    transition = mlb_rows[0]["graduation_transition"]
    assert transition["decay_basis"] == "days_since_debut"
    assert transition["days_since_debut"] == days
    assert transition["mlb_debut_date"] == debut


def _rank_payload():
    return {
        "status": "candidate_shadow",
        "rank_version": "0.1.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "candidate_count": 2,
        "ranked_count": 2,
        "rank_contract": {
            "prospect_universe_source": "valucast_prospect_universe",
        },
        "validation": {
            "coverage_rate": 1.0,
            "duplicate_identity_count": 0,
            "missing_mlbam_count": 0,
            "same_day_freshness": True,
            "ranks_contiguous": True,
            "top_200_unique_score_count": 182,
        },
        "board": [
            {
                "mlbam_id": 1,
                "name": "Model Strong",
                "role": "hitter",
                "positions": ["SS"],
                "mlb_team": "BOS",
                "age": 20,
                "rank": 1,
                "score": 55.5,
                "score_source": "prospect_model_v0_6",
                "confidence": "medium",
                "level": "AA",
                "eta": 2027,
                "drivers": ["ops +0.10"],
                "dynasty_signal": {"role_or_better_probability": 0.55},
                "context_only": {
                    "has_dd_context": True,
                    "dd_dynasty_rank": 40,
                    "dd_dynasty_value": 60.0,
                    "dd_prospect_rank": 4,
                    "source_ranks": {"pipeline": 10},
                    "breakout_label": "rising",
                    "breakout_rank_change": 5,
                    "value_history_points": 3,
                    "stat_line": {"ops": 0.900, "pa": 200},
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_level": "AA",
                    "stat_line_team": "New Hampshire",
                    "stat_line_sample": 200,
                    "stat_line_sample_unit": "PA",
                    "stat_line_sample_season": 2026,
                    "graduation_context": {
                        "status": "near_graduation",
                        "unit": "AB",
                        "current": 119.0,
                        "limit": 131.0,
                        "remaining": 12.0,
                        "graduated": False,
                    },
                    "stat_line_translated": {
                        "level_label": "AA+A+",
                        "sample": 260,
                        "sample_unit": "PA",
                        "season": 2026,
                        "stats": {"OPS": 0.760},
                    },
                    "mlb_stat_line": {"pa": 12, "ops": 0.700},
                },
            },
            {
                "mlbam_id": 2,
                "name": "Fallback Good",
                "role": "pitcher",
                "positions": ["SP"],
                "mlb_team": "MIL",
                "age": 19,
                "rank": 2,
                "score": 45.0,
                "score_source": "universal_fallback",
                "confidence": "low",
                "level": "A+",
                "eta": 2028,
                "drivers": [],
                "dynasty_signal": None,
                "context_only": {
                    "stat_line": {"era": 3.20, "ip": 45.0},
                    "stat_line_source": "valucast_input_contract",
                    "stat_line_source_kind": "current_season",
                    "stat_line_sample": 45.0,
                    "stat_line_sample_unit": "IP",
                    "stat_line_sample_season": 2026,
                },
            },
        ],
    }


def _mlb_payload(mlbam_id=99, role="hitter", value=90.0, rank=1):
    return {
        "status": "shadow_only",
        "layer_version": "0.1.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "validation": {
            "row_count": 1,
            "ready_for_live_consumers": False,
            "blockers": ["MLB layer still shadow-only."],
        },
        "players": [
            {
                "id": f"vc_mlb_{mlbam_id}_{role}",
                "player_type": "mlb",
                "name": "MLB Star",
                "mlbam_id": mlbam_id,
                "role": role,
                "positions": ["SS"] if role == "hitter" else ["SP"],
                "team": "BOS",
                "mlb_team": "BOS",
                "age": None,
                "rank": rank,
                "value": value,
                "value_scale": "0_100_valucast_mlb_shadow_dynasty_score",
                "value_source": "valucast_mlb_projection_index_v0_1",
                "confidence": "medium",
                "projection_value": 12.3,
                "components": {"production_score": 90.0},
                "drivers": ["HR +1.20"],
                "stat_line": {"stats": {"PA": 650}},
            }
        ],
    }


def _ready_mlb_payload():
    players = []
    for rank, (mlbam_id, name, value) in enumerate(
        [
            (99, "MLB Star", 90.0),
            (98, "MLB Anchor", 80.0),
            (97, "MLB Core", 70.0),
        ],
        1,
    ):
        players.append(
            {
                "id": f"vc_mlb_{mlbam_id}_hitter",
                "player_type": "mlb",
                "name": name,
                "mlbam_id": mlbam_id,
                "role": "hitter",
                "positions": ["SS"],
                "team": "BOS",
                "mlb_team": "BOS",
                "age": 24,
                "rank": rank,
                "value": value,
                "value_scale": "0_100_valucast_mlb_shadow_dynasty_score",
                "value_source": "valucast_mlb_dynasty_horizon_v0_2",
                "confidence": "high",
                "projection_value": 12.3,
                "components": {
                    "dynasty_horizon_value": 11.0,
                    "horizon_years": [{"season": 2026}, {"season": 2027}, {"season": 2028}],
                },
                "drivers": ["HR +1.20"],
                "stat_line": {"stats": {"PA": 650}},
            }
        )
    return {
        "status": "shadow_only",
        "layer_version": "0.2.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "value_contract": {
            "score_range": [0.0, 100.0],
            "value_kind": "multi_year_dynasty_horizon",
            "horizon_years": 3,
        },
        "validation": {
            "row_count": len(players),
            "ready_for_live_consumers": True,
            "blockers": [],
            "missing_mlbam_count": 0,
            "duplicate_identity_count": 0,
            "ranks_contiguous": True,
            "age_coverage_rate": 1.0,
            "age_coverage_threshold": 0.95,
            "horizon_year_count": 3,
        },
        "players": players,
    }


def _buy_payload():
    return {
        "status": "shadow_only",
        "signal_version": "0.1.0",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "validation": {
            "row_count": 2,
            "ready_for_live_consumers": False,
            "blockers": ["ValuCast buy signals are shadow-only."],
        },
        "board": [],
    }


def _peak_payload():
    return {
        "artifact": "valucast_prospect_peak_projection_v1",
        "projection_version": "1.0.0",
        "status": "candidate_ready",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "validation": {
            "ready_for_card_v2": True,
            "projection_count": 2,
            "top200_projection_coverage": 1.0,
            "min_top200_projection_coverage": 0.9,
            "duplicate_identity_count": 0,
            "missing_shape_count": 0,
            "blockers": [],
        },
        "projections": [
            {
                "mlbam_id": 1,
                "name": "Model Strong",
                "role": "hitter",
                "rank_v1_rank": 1,
                "rank_v1_score": 55.5,
                "peak_score": 61.2,
                "peak_role": "everyday_regular",
                "ceiling_band": "everyday_regular",
                "floor_band": "reserve_floor",
                "risk_band": "medium",
                "confidence": "medium",
                "eta_window": "2027",
                "shape": [
                    {"label": "Hit", "grade": 65, "source": "K% / OPS"},
                    {"label": "Power", "grade": 60, "source": "ISO / OPS"},
                    {"label": "Approach", "grade": 55, "source": "BB% / BB-K"},
                    {"label": "Impact", "grade": 60, "source": "OPS / ISO / score"},
                ],
                "card_v2": {
                    "visual_version": "2.0.0",
                    "current_score": 55.5,
                    "peak_score": 61.2,
                    "score_delta": 5.7,
                    "trajectory": "more_peak_than_current_value",
                    "role_probabilities": {"regular_or_better": 0.42},
                    "card_copy": "Peak view: everyday regular.",
                },
                "summary": "Peak read: everyday regular with medium risk.",
                "usage": "card_visual_context_not_live_rank_or_value",
            },
            {
                "mlbam_id": 2,
                "name": "Fallback Good",
                "role": "pitcher",
                "rank_v1_rank": 2,
                "rank_v1_score": 45.0,
                "peak_score": 48.2,
                "peak_role": "multi_inning_or_setup_arm",
                "ceiling_band": "multi_inning_or_setup_arm",
                "floor_band": "depth_arm_floor",
                "risk_band": "medium",
                "confidence": "medium",
                "eta_window": "2028",
                "shape": [
                    {"label": "Miss", "grade": 50, "source": "K/9"},
                    {"label": "Command", "grade": 50, "source": "BB/9"},
                    {"label": "Dominance", "grade": 50, "source": "K-BB%"},
                    {"label": "Run Prevention", "grade": 50, "source": "ERA / WHIP"},
                ],
                "card_v2": {
                    "visual_version": "2.0.0",
                    "current_score": 45.0,
                    "peak_score": 48.2,
                    "score_delta": 3.2,
                    "trajectory": "current_and_peak_aligned",
                    "role_probabilities": {"useful_mlb_arm": 0.5},
                    "card_copy": "Peak view: multi inning arm.",
                },
                "summary": "Peak read: multi inning or setup arm with medium risk.",
                "usage": "card_visual_context_not_live_rank_or_value",
            },
        ],
    }


def _write_snapshot(tmp_path, payload):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_build_snapshot_is_valid_but_not_live_ready():
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    problems = validate_public_snapshot_payload(payload)

    assert problems == []
    assert payload["schema_version"] == "1.1"
    assert payload["artifact"] == "valucast_public_dynasty_snapshot"
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["dd_ranks_used"] is False
    assert payload["validation"]["mlb_count"] == 1
    assert payload["validation"]["prospect_count"] == 2
    assert payload["validation"]["row_count"] == 3
    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["validation"]["mlb_dynasty_value_layer_present"] is True
    assert payload["validation"]["visible_prospect_ranks_contiguous"] is True
    assert payload["validation"]["cross_universe_value_scale_calibrated"] is False
    assert payload["validation"]["valucast_buy_signal_count"] == 2
    assert payload["validation"]["valucast_buy_signals_ready"] is False
    assert payload["validation"]["quality_governor_ready"] is True
    assert payload["validation"]["required_fields_complete"] is True
    assert payload["validation"]["required_field_problem_count"] == 0
    assert payload["validation"]["surface_readiness"]["buys"] is False
    assert "shadow-only" in payload["validation"]["blockers"][0]


def test_build_snapshot_calibrates_dynasty_and_prospects_without_promoting_buys():
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_ready_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    problems = validate_public_snapshot_payload(payload)

    assert problems == []
    assert payload["validation"]["ready_for_live_consumers"] is True
    assert payload["validation"]["ready_for_all_public_surfaces"] is False
    assert payload["validation"]["cross_universe_value_scale_calibrated"] is True
    assert payload["validation"]["quality_governor_ready"] is True
    assert payload["validation"]["surface_readiness"] == {
        "dynasty": True,
        "prospects": True,
        "buys": False,
    }
    assert payload["validation"]["blockers"] == []
    assert payload["validation"]["buy_signal_blockers"] == [
        "ValuCast buy signals are shadow-only.",
        "ValuCast-owned Buy signals are not approved for public promotion.",
    ]
    assert {row["value_scale"] for row in payload["players"]} == {COMMON_VALUE_SCALE}
    assert {row["status"] for row in payload["players"]} == {"candidate_ready"}

    calibration = payload["validation"]["cross_universe_calibration"]
    assert calibration["method"] == "raw_common_scale_certification_v1"
    assert calibration["value_mutation"] == "none"
    assert calibration["metrics"]["mlb_rows_at_or_above_top_prospect"] == 3
    assert calibration["metrics"]["top_prospect_mlb_equivalent_rank"] == 4
    assert payload["players"][0]["name"] == "MLB Star"
    top_prospect = next(row for row in payload["players"] if row["player_type"] == "prospect")
    assert top_prospect["rank"] == 4
    assert top_prospect["context"]["kind"] == "optional_display_context"
    assert top_prospect["context"]["stat_line_source"] == "valucast_input_contract"
    assert top_prospect["context"]["stat_line_source_kind"] == "current_season"
    assert top_prospect["context"]["graduation_context"]["status"] == "near_graduation"
    assert top_prospect["context"]["cross_universe_calibration"]["raw_value"] == 55.5
    assert (
        top_prospect["context"]["cross_universe_calibration"]["calibrated_value_scale"]
        == COMMON_VALUE_SCALE
    )


def test_snapshot_carries_peak_projection_card_context(tmp_path):
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_ready_mlb_payload(),
        prospect_peak_projection=_peak_payload(),
        buy_signals=_buy_payload(),
    )
    problems = validate_public_snapshot_payload(payload)
    path = _write_snapshot(tmp_path, payload)
    store = PublicSnapshotStore(path)

    assert problems == []
    assert payload["input_artifacts"]["prospect_peak_projection_version"] == "1.0.0"
    assert payload["input_artifacts"]["prospect_peak_projection_ready"] is True
    prospect = next(row for row in payload["players"] if row["mlbam_id"] == 1)
    assert prospect["peak_projection"]["usage"] == "card_visual_context_not_live_rank_or_value"
    assert prospect["peak_projection"]["peak_score"] == 61.2

    row = store.get_by_id(prospect["id"])
    assert row is not None
    assert row.has_peak_projection is True
    assert row.peak_score_label == "61.2"
    assert row.peak_role_label == "Everyday Regular"
    assert row.peak_risk_label == "Medium"
    assert row.peak_projection_summary == "Projection: everyday regular with medium risk."
    assert row.peak_projection_card_copy == "Peak view: everyday regular."
    assert len(row.peak_shape_items) == 4
    assert row.peak_shape_items[0]["label"] == "Hit"


def test_snapshot_merges_two_way_mlb_rows_into_one_public_row():
    mlb_layer = _ready_mlb_payload()
    mlb_layer["players"] = [
        {
            **mlb_layer["players"][0],
            "id": "vc_mlb_660271_hitter",
            "name": "Shohei Ohtani",
            "mlbam_id": 660271,
            "role": "hitter",
            "positions": ["DH"],
            "value": 60.0,
            "rank": 1,
        },
        {
            **mlb_layer["players"][1],
            "id": "vc_mlb_660271_pitcher",
            "name": "Shohei Ohtani",
            "mlbam_id": 660271,
            "role": "pitcher",
            "positions": ["SP"],
            "value": 40.0,
            "rank": 2,
        },
        {
            **mlb_layer["players"][2],
            "id": "vc_mlb_99_hitter",
            "name": "MLB Star",
            "mlbam_id": 99,
            "value": 90.0,
            "rank": 3,
        },
    ]
    mlb_layer["validation"]["row_count"] = len(mlb_layer["players"])

    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=mlb_layer,
        buy_signals=_buy_payload(),
    )

    ohtani_rows = [
        row for row in payload["players"] if str(row.get("mlbam_id")) == "660271"
    ]
    assert len(ohtani_rows) == 1
    row = ohtani_rows[0]
    assert row["id"] == "vc_mlb_660271_two_way"
    assert row["role"] == "two_way"
    assert row["positions"] == ["DH", "SP"]
    assert row["value"] == 86.0
    assert row["context"]["kind"] == "valucast_mlb_two_way_context"
    assert {item["role"] for item in row["context"]["role_components"]} == {
        "hitter",
        "pitcher",
    }
    assert payload["validation"]["duplicate_identity_count"] == 0
    assert not any("two-way" in blocker for blocker in payload["validation"]["blockers"])


def test_quality_governor_blocks_public_snapshot_promotion():
    mlb_layer = _ready_mlb_payload()
    mlb_layer["players"] = [
        {
            **mlb_layer["players"][0],
            "id": "vc_mlb_10_pitcher",
            "name": "Spike Pitcher",
            "mlbam_id": 10,
            "role": "pitcher",
            "positions": ["SP"],
            "value": 99.0,
            "rank": 1,
        },
        {
            **mlb_layer["players"][1],
            "id": "vc_mlb_11_hitter",
            "name": "MLB Anchor",
            "mlbam_id": 11,
            "value": 77.0,
            "rank": 2,
        },
        {
            **mlb_layer["players"][2],
            "id": "vc_mlb_660271_hitter",
            "name": "Shohei Ohtani",
            "mlbam_id": 660271,
            "role": "hitter",
            "positions": ["DH"],
            "value": 20.0,
            "rank": 3,
        },
        {
            **mlb_layer["players"][2],
            "id": "vc_mlb_660271_pitcher",
            "name": "Shohei Ohtani",
            "mlbam_id": 660271,
            "role": "pitcher",
            "positions": ["SP"],
            "value": 10.0,
            "rank": 4,
        },
    ]
    mlb_layer["validation"]["row_count"] = len(mlb_layer["players"])

    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=mlb_layer,
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["validation"]["quality_governor_ready"] is False
    assert "Top MLB dynasty value is too far above the second row for public promotion." in payload["validation"]["blockers"]
    assert "Top public rows split two-way identities without a combined-value policy." not in payload["validation"]["blockers"]


def test_public_snapshot_store_loads_valid_shadow_snapshot(tmp_path):
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    path = _write_snapshot(tmp_path, payload)

    store = PublicSnapshotStore(path)

    assert store.is_available is True
    assert store.ready_for_live_consumers is False
    assert store.generated_at == payload["generated_at"]
    assert len(store.get_all()) == 3
    row = store.get_by_id("vc_prospect_1_hitter")
    assert row is not None
    assert row.dynasty_rank == 2
    assert row.dynasty_value == 55.5
    assert row.confidence == {"level": "medium"}
    assert row.tier is None
    assert row.z_scores is None
    assert row.source_divergence is None
    assert row.prospect_rank == 1
    assert row.breakout_label == "rising"
    assert row.public_source_consensus == 10
    assert row.stat_line == {"ops": 0.900, "pa": 200}
    assert row.stat_line_translated == {
        "level_label": "AA+A+",
        "sample": 260,
        "sample_unit": "PA",
        "season": 2026,
        "stats": {"OPS": 0.760},
    }
    assert row.mlb_stat_line == {"pa": 12, "ops": 0.700}


def test_public_snapshot_rows_expose_prospect_sample_context(tmp_path):
    rank_payload = _rank_payload()
    rank_payload["board"][0]["components"] = {
        "availability_adjusted": True,
        "availability_risk_discount": 0.06,
        "availability": {
            "status": "thin_current_sample",
            "risk_level": "medium",
            "note": "Thin sample.",
            "sample": 260,
            "sample_unit": "PA",
        },
        "bucket_calibration": {
            "bucket": "lower_minors_pedigree_score_source",
            "adjustment": -1.0,
            "reason": "Lower-minors pedigree-only profile.",
        },
        "factual_current_context": {
            "version": "0.1.0",
            "role": "hitter",
            "level": "AA",
            "sample": 224,
            "sample_unit": "PA",
            "skill_band": "impact",
            "ops": 0.976,
            "iso": 0.261,
            "k_pct": 12.9,
            "bb_pct": 9.8,
            "bb_minus_k_pct": -3.1,
        },
        "uncertainty": {
            "version": "0.1.0",
            "kind": "display_only_score_interval",
            "band": "moderate",
            "lower": 48.0,
            "upper": 62.0,
            "score_effect": "none",
            "drivers": {
                "score_source": "prospect_model_v0_6",
                "confidence": "medium",
                "sample_reliability": 63.0,
                "skill_band": "impact",
                "availability_risk_discount": 0.06,
            },
        },
    }
    payload = build_snapshot(
        rank_payload,
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    path = _write_snapshot(tmp_path, payload)

    store = PublicSnapshotStore(path)
    row = store.get_by_id("vc_prospect_1_hitter")

    assert row is not None
    assert row.prospect_components["availability_adjusted"] is True
    assert row.availability_adjusted is True
    assert row.availability_risk_discount == 0.06
    assert row.availability_status_label == "Thin Current Sample"
    assert row.availability_sample_label == "260 PA"
    assert row.stat_line_sample_label == "200 PA"
    assert row.current_level_sample_label == "AA sample: 200 PA"
    assert row.current_level_sample_badge == "AA 200 PA"
    assert row.has_split_level_sample is True
    assert row.season_total_sample_label == "2026 total: 260 PA across AA+A+"
    assert row.season_total_sample_badge == "2026 total 260 PA"
    assert row.sample_context_label == (
        "AA sample: 200 PA | 2026 total: 260 PA across AA+A+"
    )
    assert row.availability_note == "Thin sample."
    assert row.bucket_calibration_adjusted is True
    assert row.bucket_calibration_label == "Lower-minors context"
    assert row.factual_skill_label == "Impact bat"
    assert row.factual_context_note == (
        "Impact bat from the current 224 PA factual sample."
    )
    assert row.factual_context_stat_items == (
        {"label": "Sample", "value": "224 PA"},
        {"label": "OPS", "value": "0.976"},
        {"label": "ISO", "value": "0.261"},
        {"label": "BB-K", "value": "-3.1%"},
    )
    assert row.uncertainty_label == "Moderate band: 48.0-62.0"
    assert row.uncertainty_note is not None
    assert row.uncertainty_driver_items[0]["label"] == "Source"
    assert row.why_rank_chips == (
        {
            "label": "Impact bat",
            "kind": "positive",
            "title": "Impact bat from the current 224 PA factual sample.",
        },
        {
            "label": "Sample adjusted",
            "kind": "caution",
            "title": "Availability or sample risk is priced into the score.",
        },
        {
            "label": "Bucket calibrated",
            "kind": "neutral",
            "title": "Lower-minors pedigree-only profile.",
        },
    )


def test_split_level_sample_ignores_rounding_noise(tmp_path):
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    prospect = next(row for row in payload["players"] if row["id"] == "vc_prospect_1_hitter")
    prospect["context"]["stat_line_sample"] = 200.0
    prospect["context"]["stat_line_sample_unit"] = "PA"
    prospect["stat_line_translated"] = {
        "level_label": "AA",
        "sample": 200.2,
        "sample_unit": "PA",
        "season": 2026,
        "stats": {"OPS": 0.760},
    }
    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))

    row = store.get_by_id("vc_prospect_1_hitter")

    assert row is not None
    assert row.has_split_level_sample is False
    assert row.season_total_sample_label is None
    assert row.sample_context_label == "AA sample: 200 PA"


def test_card_level_label_prefers_fresh_promoted_level_over_stale_feed(tmp_path):
    # Promoted prospect: current-season sample is at AA, but the feed snapshot
    # still carries the pre-promotion level. The card must show the fresh level,
    # not the stale feed value (the header/profile-grid mismatch bug).
    rank_payload = _rank_payload()
    rank_payload["board"][0]["level"] = "A+"
    payload = build_snapshot(
        rank_payload,
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))

    row = store.get_by_id("vc_prospect_1_hitter")

    assert row is not None
    assert row.level == "A+"  # raw feed value preserved for provenance
    assert row.card_level_label == "AA"  # card shows fresh current-season level


def test_card_level_label_falls_back_to_feed_without_current_sample(tmp_path):
    # No current-season stat line -> nothing fresher than the feed, so the card
    # must fall back to the feed level rather than inventing a level from history.
    rank_payload = _rank_payload()
    rank_payload["board"][0]["level"] = "A+"
    rank_payload["board"][0]["context_only"]["stat_line_source_kind"] = "latest_milb_history"
    payload = build_snapshot(
        rank_payload,
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))

    row = store.get_by_id("vc_prospect_1_hitter")

    assert row is not None
    assert row.card_level_label == "A+"


def test_public_snapshot_sp_filter_includes_generic_prospect_pitchers(tmp_path):
    rank_payload = _rank_payload()
    rank_payload["board"][1]["positions"] = ["P"]
    payload = build_snapshot(
        rank_payload,
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))

    names = [row.name for row in store.filter(pool="prospect", position="SP")]

    assert "Fallback Good" in names


def test_snapshot_prefers_active_prospect_row_over_mlb_projection_collision():
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_mlb_payload(mlbam_id=1, value=8.0, rank=700),
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["prospects_excluded_by_mlb_identity_count"] == 0
    assert payload["validation"]["mlb_projection_rows_suppressed_by_prospect_count"] == 1
    assert payload["validation"]["duplicate_identity_count"] == 0
    assert payload["validation"]["mlb_count"] == 0
    assert payload["validation"]["prospect_count"] == 2
    assert payload["validation"]["visible_prospect_ranks_contiguous"] is True
    assert [row["id"] for row in payload["players"] if row["mlbam_id"] == 1] == [
        "vc_prospect_1_hitter"
    ]
    top_prospect = next(row for row in payload["players"] if row["mlbam_id"] == 1)
    assert top_prospect["prospect_rank"] == 1
    assert top_prospect["context"]["valucast_rank_v1"] == 1


def test_snapshot_promotes_current_active_mlb_roster_identity_even_when_mlb_row_is_low():
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_mlb_payload(mlbam_id=1, value=8.0, rank=700),
        mlb_roster_status={
            "artifact": "valucast_mlb_roster_status",
            "contract_version": "0.1.0",
            "validation": {
                "ready_for_public_snapshot": True,
                "active_roster_profile_count": 1,
            },
            "profiles": [
                {
                    "mlbam_id": 1,
                    "name": "Model Strong",
                    "team_abbreviation": "BOS",
                    "active_mlb_roster": True,
                    "status_code": "A",
                    "source": "official_mlb_statsapi_active_roster",
                }
            ],
        },
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["prospects_excluded_by_mlb_identity_count"] == 1
    assert payload["validation"]["mlb_projection_rows_suppressed_by_prospect_count"] == 0
    assert payload["validation"]["mlb_count"] == 1
    assert payload["validation"]["prospect_count"] == 1
    assert [row["id"] for row in payload["players"] if row["mlbam_id"] == 1] == [
        "vc_mlb_1_hitter"
    ]
    assert payload["input_artifacts"]["mlb_roster_status_ready"] is True


def test_snapshot_excludes_active_mlb_roster_identity_without_mlb_layer_row():
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_mlb_payload(mlbam_id=99),
        mlb_roster_status={
            "artifact": "valucast_mlb_roster_status",
            "contract_version": "0.1.0",
            "validation": {
                "ready_for_public_snapshot": True,
                "active_roster_profile_count": 1,
            },
            "profiles": [
                {
                    "mlbam_id": 1,
                    "name": "Model Strong",
                    "team_abbreviation": "BOS",
                    "active_mlb_roster": True,
                    "status_code": "A",
                    "source": "official_mlb_statsapi_active_roster",
                }
            ],
        },
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["prospects_excluded_by_mlb_identity_count"] == 1
    assert payload["validation"]["mlb_projection_rows_suppressed_by_prospect_count"] == 0
    assert payload["validation"]["mlb_count"] == 1
    assert payload["validation"]["prospect_count"] == 1
    assert not any(row["mlbam_id"] == 1 for row in payload["players"])
    assert payload["validation"]["prospects_excluded_by_mlb_identity_sample"][0] == {
        "mlbam_id": 1,
        "name": "Model Strong",
        "role": "hitter",
        "level": "AA",
        "rank": 1,
        "reason": "active_mlb_roster",
    }


def test_snapshot_promotes_material_current_mlb_row_over_stale_prospect_context():
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_mlb_payload(mlbam_id=1, value=90.0, rank=1),
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["prospects_excluded_by_mlb_identity_count"] == 1
    assert payload["validation"]["mlb_projection_rows_suppressed_by_prospect_count"] == 0
    assert payload["validation"]["duplicate_identity_count"] == 0
    assert payload["validation"]["mlb_count"] == 1
    assert payload["validation"]["prospect_count"] == 1
    assert [row["id"] for row in payload["players"] if row["mlbam_id"] == 1] == [
        "vc_mlb_1_hitter"
    ]


def test_snapshot_allows_confirmed_mlb_level_prospect_to_graduate():
    rank_payload = _rank_payload()
    rank_payload["board"][0]["level"] = "MLB"

    payload = build_snapshot(
        rank_payload,
        mlb_layer=_mlb_payload(mlbam_id=1),
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["prospects_excluded_by_mlb_identity_count"] == 1
    assert payload["validation"]["mlb_projection_rows_suppressed_by_prospect_count"] == 0
    assert payload["validation"]["duplicate_identity_count"] == 0
    assert payload["validation"]["mlb_count"] == 1
    assert payload["validation"]["prospect_count"] == 1
    assert [row["id"] for row in payload["players"] if row["mlbam_id"] == 1] == [
        "vc_mlb_1_hitter"
    ]
    remaining_prospect = next(
        row for row in payload["players"] if row["player_type"] == "prospect"
    )
    assert remaining_prospect["prospect_rank"] == 1
    assert remaining_prospect["context"]["valucast_rank_v1"] == 2


def test_rejects_bad_schema(tmp_path):
    payload = build_snapshot(_rank_payload())
    payload["schema_version"] = "9.9"

    assert "unsupported schema_version 9.9" in validate_public_snapshot_payload(payload)
    assert PublicSnapshotStore(_write_snapshot(tmp_path, payload)).is_available is False


def test_rejects_duplicate_ids():
    payload = build_snapshot(_rank_payload())
    payload["players"][1]["id"] = payload["players"][0]["id"]

    assert "duplicate row ids" in validate_public_snapshot_payload(payload)


def test_rejects_duplicate_mlbam_role_identities():
    payload = build_snapshot(_rank_payload())
    payload["players"][1]["mlbam_id"] = payload["players"][0]["mlbam_id"]
    payload["players"][1]["role"] = payload["players"][0]["role"]

    assert "duplicate MLBAM+role identities" in validate_public_snapshot_payload(payload)


def test_rejects_missing_required_fields():
    payload = build_snapshot(_rank_payload())
    del payload["players"][0]["value_source"]

    assert "players[0].value_source is required" in validate_public_snapshot_payload(payload)


def test_rejects_missing_prospect_stat_context():
    payload = build_snapshot(_rank_payload())
    prospect_index = next(
        index
        for index, row in enumerate(payload["players"])
        if row["player_type"] == "prospect"
    )
    del payload["players"][prospect_index]["stat_line"]
    del payload["players"][prospect_index]["context"]["stat_line_source"]

    problems = validate_public_snapshot_payload(payload)

    assert (
        f"players[{prospect_index}].stat_line is required for prospects"
        in problems
    )
    assert (
        f"players[{prospect_index}].context.stat_line_source is required for prospects"
        in problems
    )


def test_rejects_missing_valucast_prospect_stat_provenance():
    payload = build_snapshot(_rank_payload())
    prospect_index = next(
        index
        for index, row in enumerate(payload["players"])
        if row["player_type"] == "prospect"
    )
    del payload["players"][prospect_index]["context"]["stat_line_source_kind"]

    problems = validate_public_snapshot_payload(payload)

    assert (
        f"players[{prospect_index}].context.stat_line_source_kind is required "
        "for ValuCast prospect stat context"
        in problems
    )


def test_builder_computes_required_field_completeness():
    rank_payload = _rank_payload()
    del rank_payload["board"][0]["context_only"]["stat_line"]
    del rank_payload["board"][0]["context_only"]["stat_line_source"]

    payload = build_snapshot(
        rank_payload,
        mlb_layer=_ready_mlb_payload(),
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["required_fields_complete"] is False
    assert payload["validation"]["required_field_problem_count"] >= 1
    assert (
        "Public snapshot has incomplete required fields."
        in payload["validation"]["blockers"]
    )


def test_rejects_source_policy_that_uses_dd_values():
    payload = build_snapshot(_rank_payload())
    payload["source_policy"]["dd_values_used"] = True

    assert "source_policy.dd_values_used must be false" in validate_public_snapshot_payload(
        payload
    )


def test_app_selector_keeps_dd_when_snapshot_gate_closed():
    from app import _select_dynasty_store

    dd = SimpleNamespace(is_available=True)
    snapshot = SimpleNamespace(is_available=True, ready_for_live_consumers=False)

    selected, source = _select_dynasty_store(dd, snapshot, use_public_snapshot=True)

    assert selected is dd
    assert source == "dd_feed"


def test_app_selector_can_use_ready_public_snapshot():
    from app import _select_dynasty_store

    dd = SimpleNamespace(is_available=True)
    snapshot = SimpleNamespace(is_available=True, ready_for_live_consumers=True)

    selected, source = _select_dynasty_store(dd, snapshot, use_public_snapshot=True)

    assert selected is snapshot
    assert source == "valucast_public_snapshot"


def test_app_selector_uses_ready_public_snapshot_by_default(monkeypatch):
    from app import _select_dynasty_store

    dd = SimpleNamespace(is_available=True)
    snapshot = SimpleNamespace(is_available=True, ready_for_live_consumers=True)
    monkeypatch.delenv("VALUCAST_USE_PUBLIC_SNAPSHOT", raising=False)

    selected, source = _select_dynasty_store(dd, snapshot)

    assert selected is snapshot
    assert source == "valucast_public_snapshot"


def test_app_selector_can_disable_public_snapshot_rollout(monkeypatch):
    from app import _select_dynasty_store

    dd = SimpleNamespace(is_available=True)
    snapshot = SimpleNamespace(is_available=True, ready_for_live_consumers=True)
    monkeypatch.setenv("VALUCAST_USE_PUBLIC_SNAPSHOT", "0")

    selected, source = _select_dynasty_store(dd, snapshot)

    assert selected is dd
    assert source == "dd_feed"
