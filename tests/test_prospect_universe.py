"""Tests for ValuCast-owned prospect universe construction."""
import pytest

from prospects.universe import build_universe


def _profile(mlbam_id=1, role="hitter", name="Model Prospect", **extra):
    payload = {
        "mlbam_id": mlbam_id,
        "role": role,
        "name": name,
        "normalized_name": name.lower(),
        "position": "SS" if role == "hitter" else "SP",
        "team": "AA Club",
        "level": "AA",
        "age": 20,
        "sample": 200,
        "sample_unit": "PA" if role == "hitter" else "IP",
        "sample_reliability": 0.6,
    }
    payload.update(extra)
    return payload


def _layer(profiles=None):
    return {
        "status": "shadow_only",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "layer_version": "0.1.0",
        "profiles": profiles or [_profile()],
    }


def _universal(profiles=None):
    return {
        "status": "shadow_only",
        "model_version": "0.4.0",
        "profiles": profiles or [_profile()],
    }


def _dd_feed(players=None):
    return {
        "schema_version": "1.1",
        "generated_at": "2026-06-13T12:00:00+00:00",
        "players": players
        or [
            {
                "id": "dd_prospect_model_prospect",
                "player_type": "prospect",
                "name": "Model Prospect",
                "mlbam_id": 1,
                "positions": ["SS"],
                "mlb_team": "BOS",
                "dynasty_rank": 10,
                "dynasty_value": 55.0,
                "prospect_rank": 3,
                "source_ranks": {"pipeline": 4},
                "breakout_label": "rising",
                "breakout_rank_change": 8,
                "value_history": [["2026-06-13", 55.0]],
            }
        ],
    }


def _without_context(payload):
    return [
        {key: value for key, value in row.items() if key != "context_only"}
        for row in payload["players"]
    ]


def test_universe_builds_without_dd_feed():
    payload = build_universe(_layer(), _universal(), dd_feed=None)

    assert payload["artifact"] == "valucast_prospect_universe"
    assert payload["candidate_count"] == 1
    assert payload["source_policy"]["dd_feed_defines_membership"] is False
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["validation"]["duplicate_identity_count"] == 0
    assert payload["validation"]["missing_mlbam_count"] == 0
    assert "context_only" not in payload["players"][0]


def test_universe_backfills_known_mlb_affiliate_from_minor_team():
    payload = build_universe(
        _layer([_profile(team="Somerset Patriots")]),
        _universal(),
        dd_feed=None,
    )

    assert payload["players"][0]["mlb_team"] == "NYY"
    assert "context_only" not in payload["players"][0]


def test_universe_rejects_duplicate_identity():
    profiles = [
        _profile(mlbam_id=1, role="hitter", name="First"),
        _profile(mlbam_id=1, role="hitter", name="Duplicate"),
    ]

    with pytest.raises(ValueError, match="duplicate identities"):
        build_universe(_layer(profiles), _universal(profiles), dd_feed=None)


def test_universe_allows_two_way_role_identities():
    profiles = [
        _profile(mlbam_id=1, role="hitter", name="Two Way Bat"),
        _profile(mlbam_id=1, role="pitcher", name="Two Way Arm"),
    ]

    payload = build_universe(_layer(profiles), _universal(profiles), dd_feed=None)

    assert payload["candidate_count"] == 2
    assert {(row["mlbam_id"], row["role"]) for row in payload["players"]} == {
        (1, "hitter"),
        (1, "pitcher"),
    }


def test_dd_context_does_not_define_membership():
    extra_dd_only = {
        "id": "dd_prospect_context_only",
        "player_type": "prospect",
        "name": "DD Only",
        "mlbam_id": 999,
        "positions": ["SS"],
        "dynasty_rank": 1,
        "dynasty_value": 150.0,
        "prospect_rank": 1,
    }

    payload = build_universe(
        _layer(),
        _universal(),
        dd_feed=_dd_feed(_dd_feed()["players"] + [extra_dd_only]),
    )

    assert payload["candidate_count"] == 1
    assert [row["mlbam_id"] for row in payload["players"]] == [1]
    assert payload["validation"]["dd_context_count"] == 1


def test_public_rank_context_does_not_change_universe_membership():
    original = build_universe(_layer(), _universal(), _dd_feed())
    changed_feed = _dd_feed()
    changed_feed["players"][0]["dynasty_rank"] = 1
    changed_feed["players"][0]["dynasty_value"] = 150.0
    changed_feed["players"][0]["prospect_rank"] = 1
    changed_feed["players"][0]["source_ranks"] = {"pipeline": 1, "cfr": 1}
    changed = build_universe(_layer(), _universal(), changed_feed)

    assert _without_context(changed) == _without_context(original)
    assert changed["players"][0]["context_only"]["dd_dynasty_value"] == 150.0
    assert changed["players"][0]["context_only"]["source_ranks"] == {
        "pipeline": 1,
        "cfr": 1,
    }
