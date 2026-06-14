"""Tests for the shadow ValuCast MLB dynasty layer."""

from league_values.models import PlayerPool, PlayerProjection
from mlb.dynasty import (
    RELIEVER_DYNASTY_SCORE_CAP,
    VALUE_SOURCE,
    build_mlb_dynasty_layer,
)


def _hitter(
    player_id="h1",
    mlbam_id="1",
    name="Big Bat",
    pa=600,
    hr=35,
    sb=18,
    avg=.290,
    metadata=None,
):
    hits = avg * 500
    base_metadata = {"mlbam_id": mlbam_id, "team": "BOS", "has_ros": True}
    if metadata:
        base_metadata.update(metadata)
    return PlayerProjection(
        id=player_id,
        name=name,
        pool=PlayerPool.HITTER,
        positions=("SS",),
        metadata=base_metadata,
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
    metadata=None,
):
    base_metadata = {"mlbam_id": mlbam_id, "team": "MIL", "has_ros": True}
    if metadata:
        base_metadata.update(metadata)
    return PlayerProjection(
        id=player_id,
        name=name,
        pool=PlayerPool.STARTER,
        positions=("SP",),
        metadata=base_metadata,
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


def _reliever(
    player_id="rp1",
    mlbam_id="4",
    name="Ninth Inning Monster",
    ip=70,
    strikeouts=115,
    era=1.70,
    metadata=None,
):
    base_metadata = {"mlbam_id": mlbam_id, "team": "SDP", "has_ros": True, "age": 27}
    if metadata:
        base_metadata.update(metadata)
    return PlayerProjection(
        id=player_id,
        name=name,
        pool=PlayerPool.RELIEVER,
        positions=("RP",),
        metadata=base_metadata,
        stats={
            "IP": ip,
            "W": 4,
            "QS": 0,
            "SV": 40,
            "HLD": 2,
            "K": strikeouts,
            "ER": era * ip / 9,
            "BB": 18,
            "H_ALLOWED": 40,
            "ERA": era,
            "WHIP": 0.90,
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
    assert payload["players"][0]["value_source"] == VALUE_SOURCE
    assert payload["value_contract"]["value_kind"] == "multi_year_dynasty_horizon"


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


def test_mlb_layer_applies_age_from_valucast_identity_store():
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1")],
        "2026-06-13",
        identities={"1": {"birth_date": "2001-07-01"}},
    )

    row = payload["players"][0]
    assert row["age"] == 24
    assert row["components"]["age_adjustment_status"] == "applied"
    assert row["components"]["age_adjustment"] == 1.4967
    assert row["components"]["age_source"] == "valucast_identity_birth_date"
    assert row["dynasty_horizon_value"] == row["components"]["dynasty_horizon_value"]
    assert len(row["components"]["horizon_years"]) == 3
    assert row["components"]["horizon_years"][0]["season"] == 2026
    assert row["components"]["horizon_years"][1]["age"] == 25
    assert payload["validation"]["age_coverage_count"] == 1
    assert payload["validation"]["age_coverage_rate"] == 1.0
    assert payload["validation"]["horizon_year_count"] == 3
    assert payload["validation"]["ready_for_live_consumers"] is True
    assert payload["promotion"]["live_consumer"] == "candidate_ready"
    assert not any("age coverage" in blocker for blocker in payload["validation"]["blockers"])


def test_mlb_layer_prefers_projection_metadata_age_over_identity():
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1", metadata={"age": 30})],
        "2026-06-13",
        identities={"1": {"birth_date": "2001-07-01"}},
    )

    row = payload["players"][0]
    assert row["age"] == 30
    assert row["components"]["age_source"] == "projection_metadata"
    assert row["components"]["age_adjustment"] == 0.97


def test_mlb_layer_horizon_declines_for_older_player_future_years():
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1", metadata={"age": 34})],
        "2026-06-13",
    )

    years = payload["players"][0]["components"]["horizon_years"]
    assert years[0]["age_factor"] == 1.0
    assert years[1]["age_factor"] < 1.0
    assert years[2]["age_factor"] < years[1]["age_factor"]
    assert years[1]["reliability_factor"] < 1.0


def test_mlb_layer_records_ros_stability_pull_for_current_outlier():
    payload = build_mlb_dynasty_layer(
        [
            _pitcher(
                player_id="outlier",
                mlbam_id="10",
                name="Current Outlier",
                ip=185,
                strikeouts=285,
                era=1.80,
                metadata={
                    "age": 24,
                    "stats_ros": {
                        "IP": 90,
                        "W": 5,
                        "QS": 8,
                        "SV": 0,
                        "HLD": 0,
                        "K": 85,
                        "ER": 36,
                        "BB": 35,
                        "H_ALLOWED": 82,
                        "ERA": 3.60,
                        "WHIP": 1.30,
                    },
                },
            ),
            _pitcher(
                player_id="stable",
                mlbam_id="11",
                name="Stable Ace",
                ip=185,
                strikeouts=220,
                era=2.90,
                metadata={
                    "age": 25,
                    "stats_ros": {
                        "IP": 95,
                        "W": 7,
                        "QS": 10,
                        "SV": 0,
                        "HLD": 0,
                        "K": 115,
                        "ER": 30,
                        "BB": 22,
                        "H_ALLOWED": 74,
                        "ERA": 2.84,
                        "WHIP": 1.01,
                    },
                },
            ),
        ],
        "2026-06-13",
    )

    outlier = next(row for row in payload["players"] if row["name"] == "Current Outlier")
    stability = outlier["components"]["projection_stability"]

    assert stability["ros_category_value"] is not None
    assert stability["ros_stability_weight"] > 0.35
    assert stability["stability_adjustment"] < 0
    assert outlier["projection_value"] == stability["stability_adjusted_category_value"]


def test_mlb_layer_annualizes_ros_as_true_talent_prior_and_applies_star_floor():
    payload = build_mlb_dynasty_layer(
        [
            _hitter(
                player_id="star",
                mlbam_id="20",
                name="Established Star",
                pa=400,
                hr=8,
                sb=3,
                avg=.230,
                metadata={
                    "age": 29,
                    "stats_ros": {
                        "PA": 200,
                        "AB": 170,
                        "H": 48,
                        "HR": 14,
                        "R": 36,
                        "RBI": 38,
                        "SB": 6,
                        "BB": 32,
                        "SO": 55,
                        "1B": 25,
                        "2B": 8,
                        "3B": 1,
                        "AVG": .282,
                        "OBP": .395,
                        "OPS": .930,
                    },
                },
            ),
            _hitter(
                "anchor",
                "21",
                "Anchor Bat",
                pa=600,
                hr=24,
                sb=8,
                avg=.270,
                metadata={
                    "age": 28,
                    "stats_ros": {
                        "PA": 300,
                        "AB": 260,
                        "H": 65,
                        "HR": 8,
                        "R": 34,
                        "RBI": 32,
                        "SB": 4,
                        "BB": 28,
                        "SO": 70,
                        "1B": 42,
                        "2B": 12,
                        "3B": 3,
                        "AVG": .250,
                        "OBP": .325,
                        "OPS": .725,
                    },
                },
            ),
            _pitcher(metadata={"age": 28}),
        ],
        "2026-06-13",
    )

    row = next(item for item in payload["players"] if item["name"] == "Established Star")
    stability = row["components"]["projection_stability"]

    assert stability["ros_value_kind"] == "annualized_true_talent"
    assert stability["ros_true_talent_annualization_scale"] == 3.0
    assert stability["true_talent_floor_value"] is not None
    assert stability["true_talent_floor_applied"] is True
    assert stability["stability_adjusted_category_value"] > stability["current_season_category_value"]


def test_mlb_layer_caps_pure_reliever_dynasty_score():
    payload = build_mlb_dynasty_layer(
        [
            _reliever(),
            _hitter(metadata={"age": 25}),
            _pitcher(metadata={"age": 28}),
        ],
        "2026-06-13",
    )

    row = next(item for item in payload["players"] if item["name"] == "Ninth Inning Monster")
    adjustments = row["components"]["role_adjustments"]

    assert adjustments["reliever_score_cap"] == RELIEVER_DYNASTY_SCORE_CAP
    assert adjustments["score_before_role_adjustment"] >= RELIEVER_DYNASTY_SCORE_CAP
    assert row["value"] <= RELIEVER_DYNASTY_SCORE_CAP


def test_mlb_layer_discounts_young_starter_current_line_volatility():
    payload = build_mlb_dynasty_layer(
        [
            _pitcher(
                player_id="young",
                mlbam_id="30",
                name="Young Current Spike",
                ip=170,
                strikeouts=245,
                era=1.90,
                metadata={
                    "age": 23,
                    "stats_actual": {"IP": 55},
                    "stats_ros": {
                        "IP": 95,
                        "W": 6,
                        "QS": 8,
                        "SV": 0,
                        "HLD": 0,
                        "K": 90,
                        "ER": 38,
                        "BB": 35,
                        "H_ALLOWED": 85,
                        "ERA": 3.60,
                        "WHIP": 1.28,
                    },
                },
            ),
            _hitter(metadata={"age": 25}),
            _pitcher(
                "stable",
                "31",
                "Stable Veteran",
                metadata={
                    "age": 29,
                    "stats_ros": {
                        "IP": 100,
                        "W": 8,
                        "QS": 12,
                        "SV": 0,
                        "HLD": 0,
                        "K": 120,
                        "ER": 30,
                        "BB": 24,
                        "H_ALLOWED": 78,
                        "ERA": 2.70,
                        "WHIP": 1.02,
                    },
                },
            ),
        ],
        "2026-06-13",
    )

    row = next(item for item in payload["players"] if item["name"] == "Young Current Spike")
    adjustments = row["components"]["role_adjustments"]

    assert adjustments["young_sp_volatility_discount"] > 0
    assert row["value"] < adjustments["score_before_role_adjustment"]
