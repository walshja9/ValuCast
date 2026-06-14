"""Tests for the ValuCast public dynasty snapshot gate."""
import json
from types import SimpleNamespace

from scripts.build_public_dynasty_snapshot import COMMON_VALUE_SCALE, build_snapshot
from web.public_snapshot_store import (
    PublicSnapshotStore,
    validate_public_snapshot_payload,
)


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
                    "stat_line_translated": {"stats": {"OPS": 0.760}},
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
                "context_only": {},
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
    assert top_prospect["context"]["cross_universe_calibration"]["raw_value"] == 55.5
    assert (
        top_prospect["context"]["cross_universe_calibration"]["calibrated_value_scale"]
        == COMMON_VALUE_SCALE
    )


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
    assert row.stat_line_translated == {"stats": {"OPS": 0.760}}
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
            "sample": 90,
            "sample_unit": "PA",
        },
        "bucket_calibration": {
            "bucket": "lower_minors_pedigree_score_source",
            "adjustment": -1.0,
            "reason": "Lower-minors pedigree-only profile.",
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
    assert row.availability_sample_label == "90 PA"
    assert row.availability_note == "Thin sample."
    assert row.bucket_calibration_adjusted is True
    assert row.bucket_calibration_label == "Lower-minors context"


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
