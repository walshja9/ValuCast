"""Tests for the ValuCast public dynasty snapshot gate."""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import scripts.build_public_dynasty_snapshot as snapshot_builder
from scripts.build_public_dynasty_snapshot import (
    COMMON_VALUE_SCALE,
    GRAD_FLOOR_DECAY_DAYS,
    GRAD_FLOOR_DISCOUNT,
    TWO_WAY_SECONDARY_VALUE_WEIGHT,
    _apply_graduation_transition_floor,
    build_snapshot,
)
from web.public_snapshot_store import (
    PublicSnapshotRow,
    PublicSnapshotStore,
    validate_public_snapshot_payload,
)


PRESET_IDS = ("5x5", "obp", "6x6", "sv_hld", "7x7", "7x7_ops", "points")


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
                "bats": "L",
                "throws": "R",
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
                    "combined_season_stat_line": {
                        "role": "hitter",
                        "season": 2026,
                        "level": "AA",
                        "levels": ["AA", "A+"],
                        "level_label": "AA+A+",
                        "sample": 260,
                        "sample_unit": "PA",
                        "pa": 260,
                        "avg": 0.304,
                        "obp": 0.390,
                        "slg": 0.540,
                        "ops": 0.930,
                        "iso": 0.236,
                        "babip": 0.350,
                        "k_pct": 15.0,
                        "bb_pct": 10.0,
                        "home_runs": 9,
                        "stolen_bases": 4,
                        "walks": 26,
                        "hits": 70,
                        "at_bats": 230,
                        "plate_appearances": 260,
                    },
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
                "bats": "L",
                "throws": "L",
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
                    "card_copy": "Ceiling is everyday regular; floor is reserve.",
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
                    "card_copy": "Ceiling is multi inning arm; floor is depth arm.",
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


def test_build_snapshot_stamps_real_build_time_for_same_day_artifacts(monkeypatch):
    class FrozenDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 6, 13, 17, 21, 33, tzinfo=timezone.utc)

    monkeypatch.setattr(snapshot_builder, "datetime", FrozenDateTime)
    rank = _rank_payload()
    rank["generated_at"] = "2026-06-13T00:00:00+00:00"
    mlb_layer = _ready_mlb_payload()
    mlb_layer["generated_at"] = "2026-06-13T00:00:00+00:00"
    buy_signals = _buy_payload()
    buy_signals["generated_at"] = "2026-06-13T00:00:00+00:00"

    payload = build_snapshot(rank, mlb_layer=mlb_layer, buy_signals=buy_signals)

    assert payload["generated_at"] == "2026-06-13T17:21:33+00:00"
    assert payload["validation"]["same_day_freshness"] is True
    assert payload["validation"]["generated_dates"]["public_snapshot"] == "2026-06-13"
    assert payload["validation"]["generated_dates"]["prospect_rank_v1"] == "2026-06-13"
    assert payload["validation"]["generated_dates"]["mlb_dynasty_layer"] == "2026-06-13"


def test_snapshot_decouples_dynasty_readiness_when_only_prospect_surface_blocked(
    monkeypatch,
    tmp_path,
):
    prospect_blocker = "Top prospect board is too pitcher-heavy for public promotion."

    def fake_quality_governor(*args, **kwargs):
        return {
            "governor_version": "test",
            "ready_for_public_snapshot": False,
            "ready_for_buys_promotion": False,
            "blockers": [prospect_blocker],
            "buy_blockers": [prospect_blocker],
            "surface_readiness": {
                "dynasty": True,
                "prospects": False,
                "buys": False,
            },
            "surface_blockers": {
                "dynasty": [],
                "prospects": [prospect_blocker],
                "buys": [prospect_blocker],
            },
        }

    monkeypatch.setattr(
        snapshot_builder,
        "evaluate_quality_governor",
        fake_quality_governor,
    )

    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_ready_mlb_payload(),
        buy_signals=_buy_payload(),
    )

    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["validation"]["surface_readiness"]["dynasty"] is True
    assert payload["validation"]["surface_blockers"]["dynasty"] == []
    assert payload["validation"]["surface_readiness"]["prospects"] is False
    assert payload["validation"]["surface_blockers"]["prospects"] == [prospect_blocker]

    from app import _select_dynasty_store

    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))
    selected, source = _select_dynasty_store(store, use_public_snapshot=True)

    assert store.ready_for_live_consumers is False
    assert store.dynasty_ready is True
    assert selected is store
    assert source == "valucast_public_snapshot"
    top_prospect = next(row for row in payload["players"] if row["player_type"] == "prospect")
    assert top_prospect["rank"] == 4
    assert top_prospect["context"]["kind"] == "optional_display_context"
    assert top_prospect["context"]["stat_line_source"] == "valucast_input_contract"
    assert top_prospect["context"]["stat_line_source_kind"] == "current_season"
    assert top_prospect["combined_season_stat_line"]["level_label"] == "AA+A+"
    assert top_prospect["combined_season_stat_line"]["sample"] == 260
    assert top_prospect["context"]["graduation_context"]["status"] == "near_graduation"
    assert top_prospect["context"]["cross_universe_calibration"]["raw_value"] == 55.5
    assert (
        top_prospect["context"]["cross_universe_calibration"]["calibrated_value_scale"]
        == COMMON_VALUE_SCALE
    )


def test_public_snapshot_preserves_prospect_handedness_for_scouting():
    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_ready_mlb_payload(),
        buy_signals=_buy_payload(),
    )

    pitcher_record = next(row for row in payload["players"] if row["name"] == "Fallback Good")
    assert pitcher_record["bats"] == "L"
    assert pitcher_record["throws"] == "L"

    pitcher = PublicSnapshotRow.from_snapshot(pitcher_record)
    assert pitcher.bats == "L"
    assert pitcher.throws == "L"


def test_build_snapshot_adds_mlb_value_history_from_archive(tmp_path):
    for date_str, value in [
        ("2026-06-11", 82.0),
        ("2026-06-12", 85.5),
        ("2026-06-13", 88.0),
    ]:
        (tmp_path / f"{date_str}.json").write_text(
            json.dumps({"players": [{"mlbam_id": 99, "value": value}]}),
            encoding="utf-8",
        )

    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_ready_mlb_payload(),
        buy_signals=_buy_payload(),
        generated_at="2026-06-13T12:00:00+00:00",
        mlb_value_history_archive_dir=tmp_path,
    )

    mlb = next(row for row in payload["players"] if row["mlbam_id"] == 99)
    prospect = next(row for row in payload["players"] if row["player_type"] == "prospect")

    assert mlb["context"]["value_history"] == [
        ("2026-06-11", 82.0),
        ("2026-06-12", 85.5),
        ("2026-06-13", 90.0),
    ]
    assert len(mlb["context"]["value_history"]) <= 30
    assert "value_history" not in prospect["context"]


def test_build_snapshot_adds_prospect_value_history_from_rank_archive(tmp_path):
    for date_str, score, dd_value in [
        ("2026-06-21", 10.0, 777.0),
        ("2026-06-22", 51.25, 888.0),
        ("2026-06-24", 52.0, 999.0),
    ]:
        (tmp_path / f"{date_str}.json").write_text(
            json.dumps(
                {
                    "board": [
                        {
                            "mlbam_id": 1,
                            "role": "hitter",
                            "score": score,
                            "context_only": {"dd_dynasty_value": dd_value},
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )

    payload = build_snapshot(
        _rank_payload(),
        mlb_layer=_ready_mlb_payload(),
        buy_signals=_buy_payload(),
        generated_at="2026-06-24T12:00:00+00:00",
        mlb_value_history_archive_dir=None,
        prospect_value_history_archive_dir=tmp_path,
    )

    prospect = next(row for row in payload["players"] if row["mlbam_id"] == 1)

    assert prospect["context"]["value_history"] == [
        ("2026-06-22", 51.25),
        ("2026-06-24", 55.5),
    ]
    assert 888.0 not in [value for _, value in prospect["context"]["value_history"]]
    assert 999.0 not in [value for _, value in prospect["context"]["value_history"]]


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
    assert row.peak_projection_card_copy == "Ceiling is everyday regular; floor is reserve."
    assert len(row.peak_shape_items) == 4
    assert row.peak_shape_items[0]["label"] == "Hit"


def test_snapshot_merges_two_way_mlb_rows_into_one_public_row():
    mlb_layer = _ready_mlb_payload()
    hitter_presets = {
        "5x5": 60.0,
        "obp": 61.0,
        "6x6": 70.0,
        "sv_hld": 55.0,
        "7x7": 65.0,
        "7x7_ops": 66.0,
        "points": 80.0,
    }
    pitcher_presets = {
        "5x5": 40.0,
        "obp": 30.0,
        "6x6": 40.0,
        "sv_hld": 50.0,
        "7x7": 45.0,
        "7x7_ops": 47.0,
        "points": 50.0,
    }
    star_presets = {
        "5x5": 90.0,
        "obp": 88.0,
        "6x6": 91.0,
        "sv_hld": 87.0,
        "7x7": 89.0,
        "7x7_ops": 90.0,
        "points": 92.0,
    }
    mlb_layer["players"] = [
        {
            **mlb_layer["players"][0],
            "id": "vc_mlb_660271_hitter",
            "name": "Shohei Ohtani",
            "mlbam_id": 660271,
            "role": "hitter",
            "positions": ["DH"],
            "value": 60.0,
            "value_by_preset": hitter_presets,
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
            "value_by_preset": pitcher_presets,
            "rank": 2,
        },
        {
            **mlb_layer["players"][2],
            "id": "vc_mlb_99_hitter",
            "name": "MLB Star",
            "mlbam_id": 99,
            "value": 90.0,
            "value_by_preset": star_presets,
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
    assert set(row["value_by_preset"]) == set(PRESET_IDS)
    assert row["value_by_preset"] == {
        preset: round(
            min(
                100.0,
                hitter_presets[preset]
                + TWO_WAY_SECONDARY_VALUE_WEIGHT * pitcher_presets[preset],
            ),
            2,
        )
        for preset in PRESET_IDS
    }
    assert row["context"]["kind"] == "valucast_mlb_two_way_context"
    assert {item["role"] for item in row["context"]["role_components"]} == {
        "hitter",
        "pitcher",
    }
    assert all(
        set(player["value_by_preset"]) == set(PRESET_IDS)
        for player in payload["players"]
        if player["player_type"] == "mlb"
    )
    assert all(
        "value_by_preset" not in player or player["value_by_preset"] == {}
        for player in payload["players"]
        if player["player_type"] == "prospect"
    )
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
        actuals=[
            {"metadata": {"mlbam_id": "1"}, "pool": "hitter",
             "stats": {"PA": 12, "OPS": 0.700}},
        ],
    )
    path = _write_snapshot(tmp_path, payload)

    store = PublicSnapshotStore(path)

    assert store.is_available is True
    assert store.ready_for_live_consumers is False
    assert store.dynasty_ready is False
    assert store.surface_readiness == payload["validation"]["surface_readiness"]
    assert store.surface_blockers == payload["validation"]["surface_blockers"]
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
    assert not hasattr(row, "breakout_label")
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


def test_public_snapshot_row_uses_preset_value_with_default_fallback():
    record = {
        "id": "vc_mlb_99_hitter",
        "player_type": "mlb",
        "name": "MLB Star",
        "mlbam_id": 99,
        "role": "hitter",
        "positions": ["SS"],
        "team": "BOS",
        "age": 24,
        "rank": 1,
        "value": 90.0,
        "value_by_preset": {"sv_hld": 83.5},
        "value_scale": "0_100_valucast_dynasty_score",
        "value_source": "valucast_mlb_dynasty_horizon_v0_2",
        "confidence": "high",
        "updated_at": "2026-06-13T12:00:00+00:00",
    }

    row = PublicSnapshotRow.from_snapshot(record)
    empty_preset_row = PublicSnapshotRow.from_snapshot(
        {**record, "id": "vc_mlb_98_hitter", "value_by_preset": {}}
    )

    assert row.value_for("sv_hld") == 83.5
    assert row.value_for(None) == row.value
    assert row.value_for("unknown") == row.value
    assert empty_preset_row.value_for("sv_hld") == empty_preset_row.value
    assert row.value_is_league_tuned("sv_hld") is True
    assert empty_preset_row.value_is_league_tuned("sv_hld") is False
    assert row.value_is_league_tuned(None) is False


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
    assert row.current_level_sample_label == "Combined 2026 line - AA+A+ - 260 PA"
    assert row.current_level_sample_badge == "AA 200 PA"
    assert row.has_split_level_sample is True
    assert row.season_total_sample_label == "Combined 2026 line - AA+A+ - 260 PA"
    assert row.season_total_sample_badge == "2026 total 260 PA"
    assert row.sample_context_label == "Combined 2026 line - AA+A+ - 260 PA"
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
    prospect["combined_season_stat_line"] = {
        "role": "hitter",
        "season": 2026,
        "level": "AA",
        "levels": ["AA"],
        "level_label": "AA",
        "sample": 200.2,
        "sample_unit": "PA",
        "pa": 200.2,
        "avg": 0.300,
        "obp": 0.380,
        "slg": 0.500,
        "ops": 0.880,
        "iso": 0.200,
        "babip": 0.330,
        "k_pct": 18.0,
        "bb_pct": 10.0,
    }
    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))

    row = store.get_by_id("vc_prospect_1_hitter")

    assert row is not None
    assert row.has_split_level_sample is False
    assert row.season_total_sample_label == "Combined 2026 line - AA - 200.2 PA"
    assert row.sample_context_label == "Combined 2026 line - AA - 200.2 PA"


def _cross_season_split_row(current_season, total_season):
    return PublicSnapshotRow.from_snapshot(
        {
            "id": "vc_prospect_111_hitter",
            "name": "Aidan Miller",
            "player_type": "prospect",
            "positions": ["SS"],
            "team": "PHI",
            "age": 21,
            "rank": 5,
            "value": 55.0,
            "value_scale": "x",
            "value_source": "prospect_model_v0_6",
            "confidence": "medium",
            "updated_at": "2026-06-24",
            "mlbam_id": "111",
            "role": "hitter",
            "prospect_rank": 5,
            "level": "AA",
            "score_source": "prospect_model_v0_6",
            "stat_line": {"pa": 489},
            # No combined_season_stat_line: this is the fallback (translated) path where
            # the cross-season split shows up, exactly like the audited rows.
            "stat_line_translated": {
                "level_label": "AA",
                "sample": 526,
                "sample_unit": "PA",
                "season": total_season,
                "stats": {"OPS": 0.760},
            },
            "context": {
                "kind": "optional_display_context",
                "stat_line_source": "valucast_input_contract",
                "stat_line_source_kind": "current_season",
                "stat_line_level": "AA",
                "stat_line_sample": 489,
                "stat_line_sample_unit": "PA",
                "stat_line_sample_season": current_season,
            },
        }
    )


def test_cross_season_split_tags_current_half_with_its_season():
    # Current 2026 sample next to a 2025 season total: both halves must carry a season
    # tag so the prior-year total can't read as current.
    row = _cross_season_split_row(2026, 2025)
    assert row.has_split_level_sample is True
    assert row.current_level_sample_label == "2026 AA sample: 489 PA"
    assert row.current_level_sample_badge == "2026 AA 489 PA"
    assert row.season_total_sample_label == "2025 total: 526 PA across AA"
    assert (
        row.sample_context_label
        == "2026 AA sample: 489 PA | 2025 total: 526 PA across AA"
    )


def test_same_season_split_leaves_current_half_untagged():
    # When both halves are the same season, the current half stays untagged (unchanged
    # behavior) — only the genuine cross-season case gets the extra tag.
    row = _cross_season_split_row(2026, 2026)
    assert row.has_split_level_sample is True
    assert row.current_level_sample_label == "AA sample: 489 PA"
    assert row.current_level_sample_badge == "AA 489 PA"
    assert (
        row.sample_context_label
        == "AA sample: 489 PA | 2026 total: 526 PA across AA"
    )


def test_card_level_label_prefers_fresh_promoted_level_over_stale_feed(tmp_path):
    # Promoted prospect: current-season sample is at AA, but the feed snapshot
    # still carries the pre-promotion level. Single source of truth: the bars rank
    # the combined AA+A+ season line, so the sub-header names that same combined
    # level — never the stale feed value (the header/profile-grid mismatch bug).
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
    assert row.card_level_label == "AA & A+"  # matches the combined bars line


def test_card_level_label_falls_back_to_feed_without_current_sample(tmp_path):
    # No current-season stat line, but the combined season line still clears the
    # pool floor and drives the bars, so the label names the combined bars level
    # rather than the stale single feed level.
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
    assert row.card_level_label == "AA & A+"


def test_card_level_label_matches_combined_bars_level_over_current_slice(tmp_path):
    # Seth Hernandez regression: feed/current level is the single A+ slice, but the
    # bars rank the combined AAA & AA season line. The sub-header MUST name the
    # combined level so the label and the bars cannot contradict each other.
    rank_payload = _rank_payload()
    board = rank_payload["board"][0]
    board["level"] = "A+"
    board["context_only"]["stat_line_level"] = "A+"
    board["context_only"]["combined_season_stat_line"].update(
        {
            "level": "AAA",
            "levels": ["AAA", "AA"],
            "level_label": "AAA+AA",
        }
    )
    payload = build_snapshot(
        rank_payload,
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))

    row = store.get_by_id("vc_prospect_1_hitter")

    assert row is not None
    assert row.level == "A+"
    assert row.card_level_label == "AAA & AA"


def test_card_level_label_keeps_single_level_combined_label(tmp_path):
    # A single-level combined line is not a contradiction with the current slice,
    # so the fresh current/feed label stands (no spurious " & " join).
    rank_payload = _rank_payload()
    board = rank_payload["board"][0]
    board["context_only"]["combined_season_stat_line"].update(
        {
            "level": "AA",
            "levels": ["AA"],
            "level_label": "AA",
        }
    )
    payload = build_snapshot(
        rank_payload,
        mlb_layer=_mlb_payload(),
        buy_signals=_buy_payload(),
    )
    store = PublicSnapshotStore(_write_snapshot(tmp_path, payload))

    row = store.get_by_id("vc_prospect_1_hitter")

    assert row is not None
    assert row.card_level_label == "AA"


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
    rank_payload = _rank_payload()
    for _row in rank_payload["board"]:
        if _row["mlbam_id"] == 1:
            _row.setdefault("context_only", {})["graduation_context"] = {
                "graduated": True, "status": "graduated"}
    payload = build_snapshot(
        rank_payload,
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


def test_snapshot_bridges_active_mlb_roster_identity_without_mlb_layer_row():
    rank_payload = _rank_payload()
    for _row in rank_payload["board"]:
        if _row["mlbam_id"] == 1:
            _row.setdefault("context_only", {})["graduation_context"] = {
                "graduated": True, "status": "graduated"}
    payload = build_snapshot(
        rank_payload,
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

    assert payload["validation"]["prospects_excluded_by_mlb_identity_count"] == 0
    assert payload["validation"]["active_mlb_callup_bridge_count"] == 1
    assert payload["validation"]["mlb_projection_rows_suppressed_by_prospect_count"] == 0
    # The graduated call-up is bridged onto the MLB surface, not kept as a ranked
    # prospect: the MLB count gains the bridge row and the prospect count loses it.
    assert payload["validation"]["mlb_count"] == 2
    assert payload["validation"]["prospect_count"] == 1
    bridged = next(row for row in payload["players"] if row["mlbam_id"] == 1)
    assert bridged["id"] == "vc_prospect_1_hitter"
    assert bridged["player_type"] == "mlb"
    assert bridged["level"] == "MLB"
    # No prospect_rank: a graduate must never read as a ranked prospect, and he is
    # absent from the prospect board while still queryable on the MLB surface.
    assert bridged["prospect_rank"] is None
    assert bridged["active_mlb_callup_bridge"] is True
    assert 1 not in {
        row["mlbam_id"]
        for row in payload["players"]
        if row["player_type"] == "prospect"
    }
    assert bridged["context"]["graduation_context"] == {
        "status": "active_mlb_callup",
        "graduated": True,
        "surface": "active_mlb_roster_bridge",
        "previous_level": "AA",
        "reason": "official_mlb_active_roster_without_mlb_projection_row",
    }
    assert payload["validation"]["active_mlb_callup_bridge_sample"][0] == {
        "mlbam_id": 1,
        "name": "Model Strong",
        "role": "hitter",
        "level": "MLB",
        "previous_level": "AA",
        "rank": None,
        "reason": "active_mlb_callup_bridge",
    }


def test_snapshot_bridges_retained_active_roster_graduate_not_on_board():
    # A known graduate the morning prospect build already evicted from the ranked board
    # (active MLB roster) and who is NOT yet in the MLB layer (e.g. <40-IP call-up). He
    # lives only in active_mlb_roster_board, so the in-board bridge can't see him; he must
    # still be bridged onto the snapshot instead of vanishing from dynasty/backfields.
    rank = _rank_payload()
    board_ids = {row.get("mlbam_id") for row in rank["board"]}
    assert 555 not in board_ids
    graduate = {**rank["board"][0], "mlbam_id": 555, "name": "Retained Graduate"}
    rank["active_mlb_roster_board"] = [graduate]

    payload = build_snapshot(
        rank,
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
                    "mlbam_id": 555,
                    "name": "Retained Graduate",
                    "team_abbreviation": "BOS",
                    "active_mlb_roster": True,
                    "status_code": "A",
                    "source": "official_mlb_statsapi_active_roster",
                }
            ],
        },
        buy_signals=_buy_payload(),
    )

    bridged = next(row for row in payload["players"] if row["mlbam_id"] == 555)
    # Bridged onto the MLB surface (not a ranked prospect) so he stays visible on
    # dynasty/backfields without appearing on the prospect board.
    assert bridged["player_type"] == "mlb"
    assert bridged["level"] == "MLB"
    assert bridged["prospect_rank"] is None
    assert bridged["active_mlb_callup_bridge"] is True
    assert 555 not in {
        row["mlbam_id"]
        for row in payload["players"]
        if row["player_type"] == "prospect"
    }
    assert (
        bridged["context"]["graduation_context"]["surface"]
        == "active_mlb_roster_bridge"
    )


def test_graduated_callup_absent_from_prospect_board_but_queryable_on_mlb(tmp_path):
    """Stranding check: a graduated call-up is excluded from the ranked prospect board
    yet stays queryable on the MLB/dynasty surface (not stranded), and the remaining
    prospect ranks stay contiguous."""
    rank_payload = _rank_payload()
    for _row in rank_payload["board"]:
        if _row["mlbam_id"] == 1:
            _row.setdefault("context_only", {})["graduation_context"] = {
                "graduated": True, "status": "graduated"}
    payload = build_snapshot(
        rank_payload,
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

    # Visible prospect ranks stay contiguous once the graduate leaves the board.
    assert payload["validation"]["visible_prospect_ranks_contiguous"] is True
    prospect_ids = {
        row["mlbam_id"] for row in payload["players"] if row["player_type"] == "prospect"
    }
    assert 1 not in prospect_ids  # graduate is off the prospect board

    # The payload must still validate and load (no stranded/invalid rows), and the
    # graduate must be queryable on the MLB pool but not the prospect pool.
    path = tmp_path / "public_dynasty_snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    store = PublicSnapshotStore(path)
    assert store.is_available
    mlb_ids = {row.mlbam_id for row in store.filter(pool="mlb")}
    board_ids = {row.mlbam_id for row in store.filter(pool="prospect")}
    assert "1" in mlb_ids
    assert "1" not in board_ids


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


def test_rejects_row_score_source_that_is_dd_derived():
    payload = build_snapshot(_rank_payload())
    payload["players"][0]["score_source"] = "dd_dynasty_value"

    problems = validate_public_snapshot_payload(payload)
    assert any("is DD/external-derived" in problem for problem in problems)
    assert (
        "source_policy.dd_values_used is False but a row score is DD-derived"
        in problems
    )


def test_accepts_valucast_owned_row_sources():
    payload = build_snapshot(_rank_payload())

    problems = validate_public_snapshot_payload(payload)
    assert not any("DD/external-derived" in problem for problem in problems)


def test_snapshot_context_drops_unused_dd_keys_keeps_source_ranks():
    payload = build_snapshot(_rank_payload())
    prospect = next(p for p in payload["players"] if p.get("player_type") == "prospect")
    context = prospect["context"]

    for key in (
        "dd_dynasty_rank",
        "dd_dynasty_value",
        "dd_prospect_rank",
        "has_dd_context",
        "breakout_label",
        "breakout_rank_change",
        "value_history_points",
    ):
        assert key not in context
        assert key not in prospect
    # External-board comparison context is kept (feeds the labeled panel).
    assert "source_ranks" in context


def test_mlb_stat_line_by_id_maps_actuals_to_template_keys():
    from scripts.build_public_dynasty_snapshot import _mlb_stat_line_by_id

    actuals = [
        {"metadata": {"mlbam_id": "100"}, "pool": "hitter",
         "stats": {"PA": 26, "AVG": 0.083, "OPS": 0.487, "HR": 1, "RBI": 3, "R": 2, "SB": 0}},
        # Real actuals use starter/reliever pools, never a "pitcher" pool — both
        # must normalize to the pitcher role so call-up pitcher cards populate.
        {"metadata": {"mlbam_id": "200"}, "pool": "starter",
         "stats": {"IP": 12.0, "ERA": 3.75, "WHIP": 1.25, "SO": 14, "QS": 1, "SV": 0}},
    ]
    by_id = _mlb_stat_line_by_id(actuals)

    assert by_id[("100", "hitter")] == {
        "pa": 26, "avg": 0.083, "ops": 0.487, "hr": 1, "rbi": 3, "r": 2, "sb": 0
    }
    assert by_id[("200", "pitcher")]["k"] == 14  # SO -> k
    assert by_id[("200", "pitcher")]["ip"] == 12.0


def test_snapshot_attaches_mlb_stat_line_from_actuals_not_dd_feed():
    # A called-up prospect's current MLB line now comes from ValuCast-owned actuals,
    # keyed by (mlbam_id, role) — replacing the retired DD feed (which left it None).
    actuals = [
        {"metadata": {"mlbam_id": "1"}, "pool": "hitter",
         "stats": {"PA": 26, "AVG": 0.083, "OPS": 0.487, "HR": 1}},
    ]
    payload = build_snapshot(_rank_payload(), actuals=actuals)
    row = next(p for p in payload["players"] if str(p.get("mlbam_id")) == "1")

    assert row["mlb_stat_line"] == {"pa": 26, "avg": 0.083, "ops": 0.487, "hr": 1}
    # A prospect with no actuals row stays None (no fabricated MLB line).
    other = next(p for p in payload["players"] if str(p.get("mlbam_id")) == "2")
    assert other["mlb_stat_line"] is None


def test_app_selector_goes_unavailable_when_snapshot_not_ready_and_old():
    from app import _select_dynasty_store

    snapshot = SimpleNamespace(
        is_available=True,
        dynasty_ready=False,
        ready_for_live_consumers=False,
        generated_at="2000-01-01",
    )

    selected, source = _select_dynasty_store(snapshot, use_public_snapshot=True)

    assert source == "unavailable"
    assert selected.is_available is False  # never DD


def test_app_selector_serves_stale_snapshot_when_recent():
    from app import _select_dynasty_store

    recent = (date.today() - timedelta(days=1)).isoformat()
    snapshot = SimpleNamespace(
        is_available=True,
        dynasty_ready=False,
        ready_for_live_consumers=False,
        generated_at=recent,
    )

    selected, source = _select_dynasty_store(snapshot, use_public_snapshot=True)

    assert selected is snapshot
    assert source == "valucast_public_snapshot_stale"


def test_app_selector_can_use_ready_public_snapshot():
    from app import _select_dynasty_store

    snapshot = SimpleNamespace(
        is_available=True,
        dynasty_ready=True,
        ready_for_live_consumers=True,
    )

    selected, source = _select_dynasty_store(snapshot, use_public_snapshot=True)

    assert selected is snapshot
    assert source == "valucast_public_snapshot"


def test_app_selector_uses_ready_public_snapshot_by_default(monkeypatch):
    from app import _select_dynasty_store

    snapshot = SimpleNamespace(
        is_available=True,
        dynasty_ready=True,
        ready_for_live_consumers=True,
    )
    monkeypatch.delenv("VALUCAST_USE_PUBLIC_SNAPSHOT", raising=False)

    selected, source = _select_dynasty_store(snapshot)

    assert selected is snapshot
    assert source == "valucast_public_snapshot"


def test_app_selector_disabled_rollout_never_serves_dd(monkeypatch):
    from app import _select_dynasty_store

    snapshot = SimpleNamespace(
        is_available=True,
        dynasty_ready=True,
        ready_for_live_consumers=True,
    )
    monkeypatch.setenv("VALUCAST_USE_PUBLIC_SNAPSHOT", "0")

    selected, source = _select_dynasty_store(snapshot)

    assert source == "unavailable"
    assert selected.is_available is False


def test_snapshot_retains_rookie_eligible_active_roster_callup_as_ranked_prospect():
    """Rookie-rule retention (7/2, the Hughes case): an active-roster call-up who
    has NOT crossed the rookie line stays a ranked prospect; his thin MLB-layer
    row is suppressed so the identity never serves twice."""
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

    rows = [row for row in payload["players"] if row["mlbam_id"] == 1]
    assert len(rows) == 1
    retained = rows[0]
    assert retained["player_type"] == "prospect"
    assert retained["prospect_rank"] is not None
    callup = (retained.get("context") or {}).get("active_mlb_callup") or {}
    assert callup.get("graduated") is False
    assert callup.get("surface") == "prospect_board_rookie_retention"
    assert "Got the call — rookie-eligible" in (retained.get("drivers") or [])
    assert payload["validation"]["active_mlb_callup_bridge_count"] == 0
    assert payload["validation"]["prospect_count"] == 2
