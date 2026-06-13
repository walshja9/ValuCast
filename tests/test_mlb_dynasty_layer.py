"""Tests for the shadow ValuCast MLB dynasty layer."""

from league_values.models import PlayerPool, PlayerProjection
from mlb.dynasty import build_mlb_dynasty_layer


def _hitter(
    player_id="h1",
    mlbam_id="1",
    name="Big Bat",
    pa=600,
    hr=35,
    sb=18,
    avg=.290,
):
    hits = avg * 500
    return PlayerProjection(
        id=player_id,
        name=name,
        pool=PlayerPool.HITTER,
        positions=("SS",),
        metadata={"mlbam_id": mlbam_id, "team": "BOS", "has_ros": True},
        stats={
            "PA": pa,
            "AB": 500,
            "H": hits,
            "HR": hr,
            "R": 90,
            "RBI": 95,
            "SB": sb,
            "SO": 120,
            "BB": 70,
            "1B": hits - hr - 30,
            "2B": 28,
            "3B": 2,
            "CS": 3,
            "AVG": avg,
            "OBP": .370,
            "OPS": .900,
        },
    )


def _pitcher(
    player_id="p1",
    mlbam_id="2",
    name="Ace Arm",
    ip=180,
    strikeouts=210,
    era=3.10,
):
    return PlayerProjection(
        id=player_id,
        name=name,
        pool=PlayerPool.STARTER,
        positions=("SP",),
        metadata={"mlbam_id": mlbam_id, "team": "MIL", "has_ros": True},
        stats={
            "IP": ip,
            "W": 14,
            "QS": 20,
            "SV": 0,
            "HLD": 0,
            "K": strikeouts,
            "ER": era * ip / 9,
            "BB": 45,
            "H_ALLOWED": 140,
            "ERA": era,
            "WHIP": 1.03,
        },
    )


def test_mlb_layer_is_shadow_only_and_independent():
    payload = build_mlb_dynasty_layer(
        [
            _hitter(),
            _pitcher(),
            _hitter("h2", "3", "Bench Bat", pa=180, hr=4, sb=2, avg=.230),
        ],
        "2026-06-13",
    )

    assert payload["status"] == "shadow_only"
    assert payload["source_policy"]["dd_values_used"] is False
    assert payload["source_policy"]["dd_ranks_used"] is False
    assert payload["source_policy"]["external_rankings_used_for_score"] is False
    assert payload["validation"]["row_count"] == 3
    assert payload["validation"]["missing_mlbam_count"] == 0
    assert payload["validation"]["duplicate_identity_count"] == 0
    assert payload["validation"]["ranks_contiguous"] is True
    assert payload["validation"]["ready_for_live_consumers"] is False
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["players"][0]["rank"] == 1
    assert payload["players"][0]["value_source"] == "valucast_mlb_projection_index_v0_1"


def test_mlb_layer_skips_missing_mlbam_and_records_blocker_context():
    payload = build_mlb_dynasty_layer(
        [
            _hitter(),
            _hitter("missing", "", "No Id", pa=600),
        ],
        "2026-06-13",
    )

    assert payload["validation"]["row_count"] == 1
    assert payload["validation"]["missing_mlbam_count"] == 1
    assert payload["players"][0]["mlbam_id"] == 1


def test_mlb_layer_dedupes_same_mlbam_role_to_best_projection():
    payload = build_mlb_dynasty_layer(
        [
            _hitter("low", "1", "Same Player", pa=250, hr=4, sb=1, avg=.220),
            _hitter("high", "1", "Same Player", pa=650, hr=35, sb=18, avg=.290),
            _pitcher(),
        ],
        "2026-06-13",
    )

    hitters = [row for row in payload["players"] if row["role"] == "hitter"]
    assert len(hitters) == 1
    assert payload["validation"]["duplicate_identity_count"] == 1
    assert hitters[0]["stat_line"]["stats"]["PA"] == 650
