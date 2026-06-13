"""Tests for the ValuCast public dynasty snapshot gate."""
import json
from types import SimpleNamespace

from scripts.build_public_dynasty_snapshot import build_snapshot
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


def _mlb_payload(mlbam_id=99, role="hitter"):
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
                "rank": 1,
                "value": 90.0,
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


def _write_snapshot(tmp_path, payload):
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_build_snapshot_is_valid_but_not_live_ready():
    payload = build_snapshot(_rank_payload(), mlb_layer=_mlb_payload())
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
    assert payload["validation"]["cross_universe_value_scale_calibrated"] is False
    assert "shadow-only" in payload["validation"]["blockers"][0]


def test_public_snapshot_store_loads_valid_shadow_snapshot(tmp_path):
    payload = build_snapshot(_rank_payload(), mlb_layer=_mlb_payload())
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
    assert row.prospect_rank == 1
    assert row.breakout_label == "rising"
    assert row.public_source_consensus == 10


def test_snapshot_excludes_prospect_duplicate_when_mlb_identity_exists():
    payload = build_snapshot(_rank_payload(), mlb_layer=_mlb_payload(mlbam_id=1))

    assert payload["validation"]["prospects_excluded_by_mlb_identity_count"] == 1
    assert payload["validation"]["duplicate_identity_count"] == 0
    assert payload["validation"]["mlb_count"] == 1
    assert payload["validation"]["prospect_count"] == 1
    assert [row["id"] for row in payload["players"] if row["mlbam_id"] == 1] == [
        "vc_mlb_1_hitter"
    ]


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
