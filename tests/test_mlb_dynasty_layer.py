"""Tests for the shadow ValuCast MLB dynasty layer."""

import json
from dataclasses import replace
from datetime import datetime

import pytest

import mlb.dynasty as dynasty_module
import scraper.season as season_config
from league_values.models import PlayerPool, PlayerProjection, ValuationResult
from mlb.dynasty import (
    FUTURE_RELIABILITY_FLOOR,
    MISSING_MLBAM_EXCEPTIONS_PATH,
    RELIEVER_DYNASTY_SCORE_CAP,
    VALUE_SOURCE,
    _future_reliability_factor,
    _horizon_profile,
    _limited_track_record_discount,
    _role_adjusted_score,
    build_mlb_dynasty_layer,
    load_missing_mlbam_exceptions,
    value_method_id,
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


def _track_record_payload(profile):
    return {
        "artifact": "valucast_mlb_track_record",
        "contract_version": "0.1.0",
        "validation": {
            "ready_for_mlb_dynasty_layer": True,
            "profile_count": 1,
            "coverage_rate": 1.0,
            "blockers": [],
        },
        "profiles": [profile],
    }


def test_projected_pitcher_pool_is_authoritative_over_eligibility():
    for pool, positions, starter, reliever in (
        (PlayerPool.STARTER, ("RP",), True, False),
        (PlayerPool.RELIEVER, ("SP",), False, True),
        (PlayerPool.PITCHER, ("SP",), True, False),
        (PlayerPool.PITCHER, ("RP",), False, True),
        (PlayerPool.PITCHER, ("SP", "RP"), True, False),
    ):
        player = replace(_pitcher(), pool=pool, positions=positions)
        assert dynasty_module._is_starter(player) is starter
        assert dynasty_module._is_reliever_only(player) is reliever
        assert player.positions == positions


def test_starter_eligibility_does_not_change_projected_role_adjustments():
    starter = _pitcher(ip=180, metadata={"age": 24, "stats_actual": {"IP": 90}})
    rp_eligible = replace(starter, positions=("RP",))
    stability = {"current_season_category_value": 10.0, "ros_category_value": 0.0}
    assert dynasty_module._playing_time_reliability(rp_eligible) == dynasty_module._playing_time_reliability(starter)
    assert _role_adjusted_score(rp_eligible, 80.0, stability) == _role_adjusted_score(starter, 80.0, stability)
    assert dynasty_module._established_true_talent_floor(rp_eligible, 2.0, 80.0) == 1.7


def test_nonpositive_ros_cannot_raise_a_projection_above_its_talent():
    player = _pitcher(ip=180, metadata={"age": 24})
    for ros_value in (-2.0, 0.0):
        assert dynasty_module._established_true_talent_floor(player, ros_value, 80.0) is None
    current = ValuationResult(player, -3.0, {}, {}, {})
    ros = ValuationResult(player, -2.0, {}, {}, {})
    adjusted, stability = dynasty_module._stability_adjusted_result(
        current, {dynasty_module.identity_key(player): ros},
    )
    assert round(adjusted.total_value, 4) == -2.6
    assert stability["true_talent_floor_applied"] is False
    assert dynasty_module._established_true_talent_floor(player, 2.0, 80.0) == 1.7
    assert dynasty_module._established_true_talent_floor(player, 2.0, 60.0) is None


def test_unavailable_ros_volume_does_not_create_a_true_talent_line():
    for ros_stats in ({"IP": 0.0, "K": 0.0}, {"IP": -1.0, "K": 10.0}, {"K": 10.0}, {"IP": float("nan"), "K": 10.0}):
        player = _pitcher(ip=180, metadata={"age": 24, "stats_ros": ros_stats})
        assert dynasty_module._annualized_ros_projection_stats(player) == ({}, 1.0)
        assert dynasty_module._ros_players([player]) == []
        lookup = dynasty_module._ros_lookup(dynasty_module.ValuationEngine(), [player])
        current = ValuationResult(player, 8.0, {}, {}, {})
        adjusted, stability = dynasty_module._stability_adjusted_result(current, lookup)
        assert adjusted.total_value == 8.0
        assert stability["ros_category_value"] is None
        assert stability["ros_stability_weight"] == 0.0
    hitter = _hitter(metadata={"stats_ros": {"PA": 0.0, "HR": 0.0}})
    assert dynasty_module._ros_players([hitter]) == []


def test_positive_tiny_ros_annualization_keeps_existing_policy():
    player = _hitter(metadata={"stats_ros": {"PA": 4.0, "HR": 1.0}})
    annualized, scale = dynasty_module._annualized_ros_projection_stats(player)
    assert annualized == {"PA": 600.0, "HR": 150.0}
    assert scale == 150.0


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
    assert payload["layer_version"] == "0.6.2"
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


def test_mlb_layer_records_explicit_projection_source():
    payload = build_mlb_dynasty_layer(
        [_hitter(metadata={"age": 25}), _pitcher(metadata={"age": 28})],
        "2026-06-13",
        projection_source="projections/runs/valucast_hp_2026_v1/projections.json",
        projection_source_kind="valucast_hp_projection_run",
    )

    assert (
        payload["source_policy"]["projection_source"]
        == "projections/runs/valucast_hp_2026_v1/projections.json"
    )
    assert payload["source_policy"]["projection_source_kind"] == "valucast_hp_projection_run"
    assert (
        payload["value_contract"]["projection_source"]
        == "projections/runs/valucast_hp_2026_v1/projections.json"
    )
    assert payload["value_contract"]["projection_source_kind"] == "valucast_hp_projection_run"
    assert payload["players"][0]["stat_line"]["source"] == "valucast_hp_projection_run"
    assert payload["method_id"] == value_method_id(
        payload["value_contract"]["phase"],
        payload["source_policy"]["projection_source_kind"],
    )


def test_value_contract_text_follows_the_season_phase():
    from unittest.mock import patch

    import scraper.season as season

    players = [_hitter(metadata={"age": 25}), _pitcher(metadata={"age": 28})]
    identities = {"1": {"birth_date": "2001-01-01"}, "2": {"birth_date": "1998-01-01"}}
    # Pin both season constants so the test does not depend on the shipped values.
    with patch.object(season, "CONTEXT_SEASON", 2026), patch.object(season, "TARGET_SEASON", 2026):
        in_season = build_mlb_dynasty_layer(players, "2026-06-13", identities=identities)["value_contract"]
    with patch.object(season, "CONTEXT_SEASON", 2026), patch.object(season, "TARGET_SEASON", 2027):
        preseason = build_mlb_dynasty_layer(players, "2026-11-02", identities=identities)["value_contract"]

    assert in_season["phase"] == "in_season"
    assert preseason["phase"] == "preseason"
    # Keys other code reads keep their names and values.
    for key in ("value_kind", "horizon_years", "horizon_year_weights", "age_adjustment"):
        assert preseason[key] == in_season[key]

    # In season the text is what it always was.
    assert in_season["projection_stability"] == (
        "Blends current-season category value with the same player's ROS "
        "true-talent annualized category value; extreme current-over-ROS outliers receive the "
        "largest pullback before dynasty-horizon scaling."
    )
    assert in_season["true_talent_floor"] == (
        "Established high-reliability MLB hitters and starters with positive "
        "annualized ROS category value cannot fall below 85% of that value."
    )
    assert in_season["horizon_production_score"].endswith("after ROS stability adjustment.")
    assert in_season["age_source"] == (
        "projection metadata first, else projections/data/identity.json birth_date by MLBAM ID."
    )

    # Before the season the layer says what is not applied, and why.
    stability = preseason["projection_stability"]
    assert stability.startswith("Not applied before the season: no current-season results exist")
    assert "current-line volatility discounts" in stability
    floor = preseason["true_talent_floor"]
    assert floor.startswith("Not applied before the season")
    assert "track-record floor" in floor and "stays active" in floor
    assert "after ROS stability adjustment" not in preseason["horizon_production_score"]
    assert "no ROS stability adjustment" in preseason["horizon_production_score"]
    assert preseason["age_source"].startswith("projections/data/identity.json birth_date")
    assert "only" in preseason["age_source"] and "metadata" in preseason["age_source"]


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


_EXCEPTION_ENTRY = {
    "name": "Overseas Star",
    "role": "hitter",
    "reason": "Reviewed: signed from overseas, no MLBAM id assigned yet",
    "added": "2026-11-17",
}


def _layer_with_exceptions(players, exceptions, error=None):
    return build_mlb_dynasty_layer(
        players,
        "2026-06-13",
        missing_mlbam_exceptions=exceptions,
        missing_mlbam_exception_error=error,
    )


def test_mlb_layer_listed_missing_mlbam_stays_off_board_and_is_not_blocking():
    payload = _layer_with_exceptions(
        [_hitter(), _hitter("fg-9", "", "Overseas Star")],
        {"fg-9": _EXCEPTION_ENTRY},
    )

    validation = payload["validation"]
    assert [row["mlbam_id"] for row in payload["players"]] == [1]
    assert validation["row_count"] == 1
    assert validation["missing_mlbam_count"] == 1
    assert validation["missing_mlbam_blocking_count"] == 0
    assert validation["missing_mlbam_blocking"] == []
    assert validation["missing_mlbam_excepted"] == [
        {
            "id": "fg-9",
            "name": "Overseas Star",
            "role": "hitter",
            "reason": _EXCEPTION_ENTRY["reason"],
            "added": "2026-11-17",
        }
    ]
    assert validation["unused_missing_mlbam_exceptions"] == []
    assert validation["missing_mlbam_exception_error"] is None


def test_mlb_layer_missing_mlbam_name_match_ignores_case_and_outer_whitespace():
    payload = _layer_with_exceptions(
        [_hitter(), _hitter("fg-9", "", "  OVERSEAS star ")],
        {"fg-9": _EXCEPTION_ENTRY},
    )

    assert payload["validation"]["missing_mlbam_blocking_count"] == 0
    assert len(payload["validation"]["missing_mlbam_excepted"]) == 1


def test_mlb_layer_unlisted_missing_mlbam_still_blocks_and_records_feed_id():
    payload = _layer_with_exceptions(
        [_hitter(), _hitter("fg-7", "", "Someone Else")],
        {"fg-9": _EXCEPTION_ENTRY},
    )

    validation = payload["validation"]
    assert validation["missing_mlbam_count"] == 1
    assert validation["missing_mlbam_blocking_count"] == 1
    assert validation["missing_mlbam_blocking"] == [
        {"id": "fg-7", "name": "Someone Else", "role": "hitter"}
    ]
    assert validation["missing_mlbam_excepted"] == []
    assert validation["unused_missing_mlbam_exceptions"] == [
        {"id": "fg-9", "name": "Overseas Star"}
    ]


def test_mlb_layer_missing_mlbam_exception_does_not_match_on_name_and_role_alone():
    payload = _layer_with_exceptions(
        [_hitter(), _hitter("fg-7", "", "Overseas Star")],
        {"fg-9": _EXCEPTION_ENTRY},
    )

    validation = payload["validation"]
    assert validation["missing_mlbam_blocking_count"] == 1
    assert validation["missing_mlbam_blocking"][0]["id"] == "fg-7"
    assert validation["missing_mlbam_excepted"] == []


@pytest.mark.parametrize(
    "entry",
    [
        dict(_EXCEPTION_ENTRY, name="Different Name"),
        dict(_EXCEPTION_ENTRY, role="pitcher"),
    ],
    ids=["name_differs", "role_differs"],
)
def test_mlb_layer_missing_mlbam_exception_needs_id_name_and_role_to_match(entry):
    payload = _layer_with_exceptions(
        [_hitter(), _hitter("fg-9", "", "Overseas Star")],
        {"fg-9": entry},
    )

    validation = payload["validation"]
    assert validation["missing_mlbam_blocking_count"] == 1
    assert validation["missing_mlbam_blocking"][0]["id"] == "fg-9"
    assert validation["missing_mlbam_excepted"] == []
    assert validation["unused_missing_mlbam_exceptions"] == [
        {"id": "fg-9", "name": entry["name"]}
    ]


def test_mlb_layer_exception_for_player_with_mlbam_id_is_unused_and_changes_nothing():
    players = [_hitter("fg-1", "1", "Overseas Star"), _pitcher()]
    baseline = build_mlb_dynasty_layer(players, "2026-06-13")
    payload = _layer_with_exceptions(players, {"fg-1": _EXCEPTION_ENTRY})

    assert payload["validation"]["unused_missing_mlbam_exceptions"] == [
        {"id": "fg-1", "name": "Overseas Star"}
    ]
    assert payload["validation"]["missing_mlbam_count"] == 0
    assert payload["validation"]["missing_mlbam_blocking_count"] == 0
    assert payload["players"] == baseline["players"]


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        "[]",
        '"text"',
        json.dumps({"fg-9": "not an object"}),
        json.dumps({"fg-9": dict(_EXCEPTION_ENTRY, role="catcher")}),
        json.dumps({"fg-9": dict(_EXCEPTION_ENTRY, reason="")}),
        json.dumps({"fg-9": {k: v for k, v in _EXCEPTION_ENTRY.items() if k != "name"}}),
        json.dumps({"fg-9": dict(_EXCEPTION_ENTRY, added="2026-13-45")}),
        json.dumps({"fg-9": dict(_EXCEPTION_ENTRY, added="2026-1-5")}),
        json.dumps({"fg-9": dict(_EXCEPTION_ENTRY, added=20261117)}),
        # One bad entry rejects the whole file, including the good entry.
        json.dumps({"fg-9": _EXCEPTION_ENTRY, "fg-8": dict(_EXCEPTION_ENTRY, role="")}),
    ],
)
def test_mlb_layer_invalid_exceptions_file_applies_nothing_and_records_error(
    tmp_path, content
):
    path = tmp_path / "missing_mlbam_exceptions.json"
    path.write_text(content, encoding="utf-8")

    exceptions, error = load_missing_mlbam_exceptions(path)
    payload = _layer_with_exceptions(
        [_hitter(), _hitter("fg-9", "", "Overseas Star")], exceptions, error
    )

    validation = payload["validation"]
    assert exceptions == {}
    assert error
    assert validation["missing_mlbam_exception_error"] == error
    assert validation["missing_mlbam_excepted"] == []
    assert validation["missing_mlbam_count"] == 1
    assert validation["missing_mlbam_blocking_count"] == validation["missing_mlbam_count"]


def test_missing_mlbam_exceptions_file_absent_means_no_exceptions_and_no_error(tmp_path):
    assert load_missing_mlbam_exceptions(tmp_path / "absent.json") == ({}, None)


def test_missing_mlbam_exceptions_file_saved_with_a_byte_order_mark_is_read(tmp_path):
    # Windows editors often add one; it must not turn a valid list into an error.
    path = tmp_path / "missing_mlbam_exceptions.json"
    path.write_text(json.dumps({"fg-9": _EXCEPTION_ENTRY}), encoding="utf-8-sig")

    assert load_missing_mlbam_exceptions(path) == ({"fg-9": _EXCEPTION_ENTRY}, None)


def test_mlb_layer_empty_exceptions_file_changes_nothing(tmp_path):
    path = tmp_path / "missing_mlbam_exceptions.json"
    path.write_text("{}\n", encoding="utf-8")
    players = [_hitter(), _pitcher(), _hitter("missing", "", "No Id", pa=600)]

    baseline = build_mlb_dynasty_layer(players, "2026-06-13")
    exceptions, error = load_missing_mlbam_exceptions(path)
    payload = _layer_with_exceptions(players, exceptions, error)

    assert (exceptions, error) == ({}, None)
    assert payload == baseline
    assert payload["validation"]["missing_mlbam_count"] == 1
    assert payload["validation"]["missing_mlbam_blocking_count"] == 1
    assert payload["validation"]["missing_mlbam_blocking"] == [
        {"id": "missing", "name": "No Id", "role": "hitter"}
    ]
    assert payload["validation"]["missing_mlbam_exception_error"] is None


def test_committed_missing_mlbam_exceptions_file_is_well_formed():
    entries = json.loads(MISSING_MLBAM_EXCEPTIONS_PATH.read_text(encoding="utf-8"))

    assert isinstance(entries, dict)
    for feed_id, entry in entries.items():
        assert feed_id.strip()
        assert entry["name"].strip()
        assert entry["role"] in ("hitter", "pitcher")
        assert entry["reason"].strip()
        datetime.strptime(entry["added"], "%Y-%m-%d")
    assert load_missing_mlbam_exceptions(MISSING_MLBAM_EXCEPTIONS_PATH) == (entries, None)


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


def test_mlb_layer_applies_age_from_valucast_identity_store(monkeypatch):
    monkeypatch.setattr(season_config, "TARGET_SEASON", season_config.CONTEXT_SEASON)
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


def test_mlb_layer_prefers_projection_metadata_age_over_identity(monkeypatch):
    monkeypatch.setattr(season_config, "TARGET_SEASON", season_config.CONTEXT_SEASON)
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1", metadata={"age": 30})],
        "2026-06-13",
        identities={"1": {"birth_date": "2001-07-01"}},
    )

    row = payload["players"][0]
    assert row["age"] == 30
    assert row["components"]["age_source"] == "projection_metadata"
    assert row["components"]["age_adjustment"] == 0.97


@pytest.mark.parametrize("preseason", [False, True])
def test_mlb_layer_horizon_declines_for_older_player_future_years(monkeypatch, preseason):
    monkeypatch.setattr(
        season_config, "TARGET_SEASON", season_config.CONTEXT_SEASON + int(preseason)
    )
    # Ageing must hold in both phases. Born 1991-07-01: 34 on April 1, 2026 (agrees
    # with the row age in-season), 35 on April 1, 2027 (the only age preseason uses).
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1", metadata={"age": 34})],
        "2026-06-13",
        identities={"1": {"birth_date": "1991-07-01"}},
    )

    years = payload["players"][0]["components"]["horizon_years"]
    assert years[0]["age_factor"] == 1.0
    assert years[1]["age_factor"] < 1.0
    assert years[2]["age_factor"] < years[1]["age_factor"]
    assert years[1]["reliability_factor"] < 1.0


def test_future_reliability_factor_does_not_compound_across_years():
    # Regression (Bug 2): reliability is sample-size uncertainty, not a
    # per-year decay. It must be applied ONCE, so year-2 must NOT be the
    # square of year-1 (which crushed part-time-but-good players).
    reliability = 60.0  # -> stability 0.60, above the 0.55 floor
    y0 = _future_reliability_factor(reliability, 0)
    y1 = _future_reliability_factor(reliability, 1)
    y2 = _future_reliability_factor(reliability, 2)
    assert y0 == 1.0
    assert y1 == 0.60
    # Flat, not compounded: year-2 equals year-1, and stays well above the
    # old compounded 0.60 ** 2 = 0.36.
    assert y2 == y1
    assert y2 > 0.60 ** 2


def test_horizon_penalty_cannot_improve_a_negative_value():
    result = ValuationResult(
        player=_hitter(metadata={"age": 34}),
        total_value=-5.0,
        raw_values={},
        z_scores={},
        category_values={},
    )

    horizon = _horizon_profile(result, 2026, baseline=-10.0)

    assert horizon["years"][1]["projected_value"] < result.total_value


def test_partial_time_good_player_year2_horizon_not_crushed():
    # End-to-end (Bug 2): a good but part-time hitter's year-2 reliability
    # haircut must equal its year-1 haircut, not the compounded square.
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1", pa=300, metadata={"age": 27})],
        "2026-06-13",
    )
    years = payload["players"][0]["components"]["horizon_years"]
    r1 = years[1]["reliability_factor"]
    r2 = years[2]["reliability_factor"]
    assert r1 < 1.0  # a haircut is applied to future years
    assert r2 == r1  # but it does not compound
    assert r2 >= FUTURE_RELIABILITY_FLOOR


def test_mlb_layer_records_ros_stability_pull_for_current_outlier(monkeypatch):
    monkeypatch.setattr(season_config, "TARGET_SEASON", season_config.CONTEXT_SEASON)
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


def test_mlb_layer_annualizes_ros_as_true_talent_prior_and_applies_star_floor(monkeypatch):
    monkeypatch.setattr(season_config, "TARGET_SEASON", season_config.CONTEXT_SEASON)
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


def test_mlb_layer_track_record_floor_cannot_bypass_reliever_cap():
    player = _reliever()
    score, adjustments = _role_adjusted_score(
        player,
        80.0,
        {},
        {
            "experience_band": "established",
            "track_record_certainty": 80.0,
            "track_record_floor_score": 59.0,
            "volume": {"prior_mlb": 400, "career": 450},
        },
    )

    assert score == RELIEVER_DYNASTY_SCORE_CAP
    assert adjustments["reliever_score_cap"] == RELIEVER_DYNASTY_SCORE_CAP
    assert adjustments["track_record_floor_score"] == 59.0
    assert adjustments["track_record_floor_applied"] is False


def test_mlb_layer_discounts_young_starter_current_line_volatility(monkeypatch):
    monkeypatch.setattr(season_config, "TARGET_SEASON", season_config.CONTEXT_SEASON)
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


def test_mlb_layer_discounts_young_hitter_current_line_volatility(monkeypatch):
    monkeypatch.setattr(season_config, "TARGET_SEASON", season_config.CONTEXT_SEASON)
    payload = build_mlb_dynasty_layer(
        [
            _hitter(
                player_id="young_bat",
                mlbam_id="40",
                name="Young Current Spike Bat",
                pa=690,
                hr=48,
                sb=28,
                avg=.330,
                metadata={
                    "age": 24,
                    "stats_actual": {"PA": 260},
                    "stats_ros": {
                        "PA": 350,
                        "AB": 310,
                        "H": 65,
                        "HR": 6,
                        "R": 32,
                        "RBI": 30,
                        "SB": 3,
                        "BB": 30,
                        "SO": 75,
                        "1B": 49,
                        "2B": 14,
                        "3B": 1,
                        "AVG": .210,
                        "OBP": .285,
                        "OPS": .620,
                    },
                },
            ),
            _hitter("steady", "41", "Steady Bat", metadata={"age": 28}),
            _pitcher(metadata={"age": 28}),
        ],
        "2026-06-13",
    )

    row = next(item for item in payload["players"] if item["name"] == "Young Current Spike Bat")
    adjustments = row["components"]["role_adjustments"]

    assert adjustments["young_hitter_volatility_discount"] > 0
    assert adjustments["actual_mlb_pa"] == 260


def test_mlb_layer_discounts_limited_sample_starter_spike_after_young_age_band():
    player = _pitcher(
        player_id="starter_spike",
        mlbam_id="50",
        name="Limited Starter Spike",
        metadata={"age": 25, "stats_actual": {"IP": 82}},
    )
    score, adjustments = _role_adjusted_score(
        player,
        80.0,
        {
            "current_season_category_value": 10.0,
            "ros_category_value": 4.0,
        },
    )

    assert score < 80.0
    assert adjustments["young_sp_volatility_discount"] == 0
    assert adjustments["starter_volatility_discount"] > 0
    assert adjustments["actual_mlb_ip"] == 82


def test_mlb_layer_applies_established_track_record_floor():
    player = _hitter(metadata={"age": 31})
    score, adjustments = _role_adjusted_score(
        player,
        42.0,
        {},
        {
            "experience_band": "established",
            "track_record_certainty": 78.0,
            "track_record_floor_score": 58.0,
            "volume": {"prior_mlb": 3200, "career": 3500},
        },
    )

    assert score == 58.0
    assert adjustments["track_record_floor_applied"] is True
    assert adjustments["track_record_floor_score"] == 58.0
    assert adjustments["track_record_certainty"] == 78.0


def test_mlb_layer_blocks_track_record_floor_when_current_and_ros_are_weak():
    player = _hitter(metadata={"age": 35})
    score, adjustments = _role_adjusted_score(
        player,
        10.0,
        {
            "current_season_category_value": -1.4,
            "ros_category_value": -1.7,
            "stability_adjusted_category_value": -1.5,
        },
        {
            "experience_band": "established",
            "track_record_certainty": 63.0,
            "track_record_floor_score": 50.0,
            "volume": {"prior_mlb": 1600, "career": 1750},
        },
    )

    assert score == 10.0
    assert adjustments["track_record_floor_applied"] is False
    assert adjustments["track_record_floor_score"] == 50.0
    assert adjustments["track_record_floor_blocked_reason"] == "weak_current_and_ros_projection"


def test_mlb_layer_allows_track_record_floor_when_ros_is_still_positive():
    player = _hitter(metadata={"age": 33})
    score, adjustments = _role_adjusted_score(
        player,
        40.0,
        {
            "current_season_category_value": -2.0,
            "ros_category_value": 2.5,
            "stability_adjusted_category_value": -0.2,
        },
        {
            "experience_band": "established",
            "track_record_certainty": 70.0,
            "track_record_floor_score": 54.0,
            "volume": {"prior_mlb": 2200, "career": 2500},
        },
    )

    assert score == 54.0
    assert adjustments["track_record_floor_applied"] is True
    assert adjustments["track_record_floor_blocked_reason"] is None


def test_mlb_layer_blocks_track_record_floor_for_aged_out_hitter():
    player = _hitter(metadata={"age": 34})
    score, adjustments = _role_adjusted_score(
        player,
        40.0,
        {
            "current_season_category_value": 1.2,
            "ros_category_value": 2.5,
            "stability_adjusted_category_value": 1.8,
        },
        {
            "experience_band": "established",
            "track_record_certainty": 70.0,
            "track_record_floor_score": 54.0,
            "volume": {"prior_mlb": 2200, "career": 2500},
        },
    )

    assert score == 40.0
    assert adjustments["track_record_floor_applied"] is False
    assert adjustments["track_record_floor_blocked_reason"] == "aged_out_of_track_record_floor"


def test_mlb_layer_blocks_track_record_floor_when_production_gap_is_large():
    player = _hitter(metadata={"age": 27})
    score, adjustments = _role_adjusted_score(
        player,
        20.0,
        {
            "current_season_category_value": 1.2,
            "ros_category_value": 2.5,
            "stability_adjusted_category_value": 1.8,
        },
        {
            "experience_band": "established",
            "track_record_certainty": 70.0,
            "track_record_floor_score": 55.0,
            "volume": {"prior_mlb": 2200, "career": 2500},
        },
    )

    assert score == 20.0
    assert adjustments["track_record_floor_applied"] is False
    assert (
        adjustments["track_record_floor_blocked_reason"]
        == "production_far_below_track_record_floor"
    )


def test_mlb_layer_discounts_high_score_with_limited_track_record():
    player = _hitter(metadata={"age": 23})
    score, adjustments = _role_adjusted_score(
        player,
        92.0,
        {},
        {
            "experience_band": "current_year_only_or_limited",
            "track_record_certainty": 8.0,
            "track_record_floor_score": 22.0,
            "volume": {"prior_mlb": 0, "career": 300},
        },
    )

    assert score < 92.0
    assert adjustments["limited_mlb_track_record_discount"] > 0
    assert adjustments["track_record_floor_applied"] is False


def test_limited_track_record_discount_decreases_with_prior_volume():
    for player, full_history in ((_hitter(), 600), (_pitcher(), 180)):
        discounts = [_limited_track_record_discount(player, 95.0, {})]
        discounts.extend(
            _limited_track_record_discount(
                player,
                95.0,
                {"track_record_certainty": 30.0, "volume": {"prior_mlb": volume}},
            )
            for volume in (0, 1, full_history / 2, full_history)
        )

        assert discounts[0] > 0
        assert discounts == sorted(discounts, reverse=True)
        assert discounts[-1] == 0


def test_mlb_layer_discounts_missing_profile_only_with_nonempty_lookup():
    players = [
        _hitter(metadata={"age": 28}),
        _hitter("h2", "3", "Bench Bat", pa=180, hr=4, sb=2, avg=.230),
        _pitcher(metadata={"age": 28}),
        _pitcher("p2", "4", "Weak Arm", strikeouts=80, era=6.00),
    ]
    baseline = build_mlb_dynasty_layer(players, "2026-06-13")
    empty = build_mlb_dynasty_layer(players, "2026-06-13", track_record={"profiles": []})
    loaded = build_mlb_dynasty_layer(
        players,
        "2026-06-13",
        track_record=_track_record_payload({"mlbam_id": 999, "role": "hitter"}),
    )

    for payload in (baseline, empty):
        for row in payload["players"]:
            assert row["components"]["role_adjustments"]["limited_mlb_track_record_discount"] == 0
    for mlbam_id in (1, 2):
        row = next(row for row in loaded["players"] if row["mlbam_id"] == mlbam_id)
        assert row["components"]["role_adjustments"]["limited_mlb_track_record_discount"] > 0
        assert row["components"]["track_record"]["present"] is False


def test_limited_track_record_discount_preserves_no_artifact_score_and_reliever_guards():
    for player in (_hitter(), _pitcher()):
        assert _limited_track_record_discount(player, 95.0, None) == 0
        for score in (54.0, 55.0):
            assert _limited_track_record_discount(player, score, {}) == 0
    assert _limited_track_record_discount(_reliever(), 95.0, {}) == 0


def test_mlb_layer_embeds_track_record_context_when_artifact_is_present():
    payload = build_mlb_dynasty_layer(
        [
            _hitter(mlbam_id="60", metadata={"age": 30}),
            _pitcher(metadata={"age": 28}),
        ],
        "2026-06-13",
        track_record=_track_record_payload(
            {
                "mlbam_id": 60,
                "role": "hitter",
                "experience_band": "established",
                "track_record_certainty": 74.0,
                "track_record_floor_score": 56.0,
                "volume": {"prior_mlb": 2400, "career": 2700},
                "source": "mlb_stats_api_year_by_year_and_current_actuals",
            }
        ),
    )

    row = next(item for item in payload["players"] if item["mlbam_id"] == 60)
    track_record = row["components"]["track_record"]

    assert payload["validation"]["track_record_present"] is True
    assert payload["validation"]["track_record_ready"] is True
    assert track_record["present"] is True
    assert track_record["experience_band"] == "established"
    assert track_record["track_record_certainty"] == 74.0


def test_mlb_layer_applies_official_availability_discount_by_mlbam():
    players = [
        _pitcher(mlbam_id="70", metadata={"age": 27}),
        _hitter(mlbam_id="71", metadata={"age": 28}),
    ]
    baseline = build_mlb_dynasty_layer(players, "2026-06-13")
    payload = build_mlb_dynasty_layer(
        players,
        "2026-06-13",
        availability={
            "artifact": "valucast_mlb_availability",
            "validation": {
                "ready_for_mlb_dynasty_layer": True,
                "profile_count": 1,
                "risk_profile_count": 1,
            },
            "profiles": [
                {
                    "mlbam_id": 70,
                    "name": "Ace Arm",
                    "status": "injured",
                    "active_injury_risk": True,
                    "list_type": "60-day injured list",
                    "transaction_id": 1,
                    "transaction_date": "2026-06-01",
                    "effective_date": "2026-06-01",
                    "description": "Milwaukee Brewers transferred RHP Ace Arm from the 15-day injured list to the 60-day injured list.",
                    "source": "official_mlb_statsapi_transactions",
                }
            ],
        },
    )

    baseline_row = next(row for row in baseline["players"] if row["mlbam_id"] == 70)
    row = next(row for row in payload["players"] if row["mlbam_id"] == 70)
    components = row["components"]

    assert payload["source_policy"]["official_mlb_transactions_used_for_availability"] is True
    assert payload["validation"]["availability_present"] is True
    assert payload["validation"]["availability_adjusted_count"] == 1
    assert row["value"] < baseline_row["value"]
    assert components["availability_adjusted"] is True
    assert components["availability_risk_discount"] == 0.12
    assert components["availability"]["status"] == "injured"
    assert components["availability"]["source"] == "official_mlb_statsapi_transactions"


# Preseason twins of the in-season tests above. The phase is set explicitly (target
# season one above the context season), not left to the shipped default. Preseason
# takes a player's age only from the identity birth date as of April 1 of the
# target season and uses no rest-of-season data, so ages come from birth dates here.
@pytest.fixture
def preseason_phase(monkeypatch):
    monkeypatch.setattr(season_config, "CONTEXT_SEASON", 2026)
    monkeypatch.setattr(season_config, "TARGET_SEASON", 2027)


def _born_aged(age):
    # Identity record whose birth date makes a player `age` on April 1, 2027.
    return {"birth_date": f"{2026 - age}-07-01"}


_OUTLIER_ROS = {
    "IP": 90, "W": 5, "QS": 8, "SV": 0, "HLD": 0, "K": 85, "ER": 36, "BB": 35, "H_ALLOWED": 82,
    "ERA": 3.60, "WHIP": 1.30,
}
_STABLE_ROS = {
    "IP": 95, "W": 7, "QS": 10, "SV": 0, "HLD": 0, "K": 115, "ER": 30, "BB": 22,
    "H_ALLOWED": 74, "ERA": 2.84, "WHIP": 1.01,
}
_STAR_ROS = {
    "PA": 200, "AB": 170, "H": 48, "HR": 14, "R": 36, "RBI": 38, "SB": 6, "BB": 32, "SO": 55,
    "1B": 25, "2B": 8, "3B": 1, "AVG": .282, "OBP": .395, "OPS": .930,
}
_ANCHOR_ROS = {
    "PA": 300, "AB": 260, "H": 65, "HR": 8, "R": 34, "RBI": 32, "SB": 4, "BB": 28, "SO": 70,
    "1B": 42, "2B": 12, "3B": 3, "AVG": .250, "OBP": .325, "OPS": .725,
}
_YOUNG_SP_ROS = {
    "IP": 95, "W": 6, "QS": 8, "SV": 0, "HLD": 0, "K": 90, "ER": 38, "BB": 35, "H_ALLOWED": 85,
    "ERA": 3.60, "WHIP": 1.28,
}
_VETERAN_SP_ROS = {
    "IP": 100, "W": 8, "QS": 12, "SV": 0, "HLD": 0, "K": 120, "ER": 30, "BB": 24,
    "H_ALLOWED": 78, "ERA": 2.70, "WHIP": 1.02,
}
_YOUNG_BAT_ROS = {
    "PA": 350, "AB": 310, "H": 65, "HR": 6, "R": 32, "RBI": 30, "SB": 3, "BB": 30, "SO": 75,
    "1B": 49, "2B": 14, "3B": 1, "AVG": .210, "OBP": .285, "OPS": .620,
}


def test_mlb_layer_preseason_takes_age_from_birth_date_for_target_season(preseason_phase):
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1")],
        "2026-11-16",
        identities={"1": {"birth_date": "2001-07-01"}},
    )

    row = payload["players"][0]
    # 24 on April 1, 2026 (the in-season twin), 25 on April 1, 2027.
    assert row["age"] == 25
    assert row["components"]["age_adjustment_status"] == "applied"
    assert row["components"]["age_adjustment"] == 1.42
    assert row["components"]["age_source"] == "valucast_identity_birth_date"
    horizon_years = row["components"]["horizon_years"]
    assert [year["season"] for year in horizon_years] == [2027, 2028, 2029]
    assert [year["age"] for year in horizon_years] == [25, 26, 27]
    assert payload["validation"]["age_coverage_count"] == 1
    assert payload["validation"]["age_coverage_rate"] == 1.0


def test_mlb_layer_preseason_ignores_projection_row_age_when_birth_date_present(preseason_phase):
    payload = build_mlb_dynasty_layer(
        [_hitter(mlbam_id="1", metadata={"age": 30})],
        "2026-11-16",
        identities={"1": {"birth_date": "2001-07-01"}},
    )

    row = payload["players"][0]
    # The in-season twin keeps the row's 30 (projection_metadata, 0.97).
    assert row["age"] == 25
    assert row["components"]["age_source"] == "valucast_identity_birth_date"
    assert row["components"]["age_adjustment"] == 1.42


@pytest.mark.parametrize(
    "identities",
    [None, {"9": {"birth_date": "2001-07-01"}}, {"1": {}}],
    ids=["no_identity_store", "no_identity_record", "record_without_birth_date"],
)
def test_mlb_layer_preseason_row_age_without_birth_date_gets_no_age_adjustment(
    preseason_phase, identities
):
    """Owner decision 2026-11-17 for the flip: birth date only, no fallback to the
    age on the projection row. This documents current behaviour, not a permanent
    policy; a visible warning and alert for missing birth dates are designed apart."""

    def build(metadata):
        return build_mlb_dynasty_layer(
            [
                _hitter(mlbam_id="1", metadata=metadata),
                _hitter("h2", "3", "Other Bat", hr=20, sb=8, avg=.260),
                _pitcher(),
            ],
            "2026-11-16",
            identities=identities,
        )

    payload = build({"age": 30})
    row = next(item for item in payload["players"] if item["mlbam_id"] == 1)
    control = next(item for item in build({})["players"] if item["mlbam_id"] == 1)

    assert row["age"] is None
    assert row["components"]["age_source"] == "missing_identity_birth_date"
    assert row["components"]["age_adjustment_status"] == "missing_age"
    assert row["components"]["age_adjustment"] is None
    assert [year["age_factor"] for year in row["components"]["horizon_years"]] == [1.0, 1.0, 1.0]
    assert payload["validation"]["age_coverage_count"] == 0
    # An age of 30 reaching the engine would move the value.
    assert row["components"]["season_category_value"] == control["components"]["season_category_value"]
    assert row["dynasty_horizon_value"] == control["dynasty_horizon_value"]


def test_mlb_layer_preseason_values_rows_without_their_rest_of_season_stats(preseason_phase):
    payload = build_mlb_dynasty_layer(
        [
            _pitcher(
                player_id="outlier",
                mlbam_id="10",
                name="Current Outlier",
                ip=185,
                strikeouts=285,
                era=1.80,
                metadata={"stats_ros": _OUTLIER_ROS},
            ),
            _pitcher(
                player_id="stable",
                mlbam_id="11",
                name="Stable Ace",
                ip=185,
                strikeouts=220,
                era=2.90,
                metadata={"stats_ros": _STABLE_ROS},
            ),
            _hitter(
                player_id="star",
                mlbam_id="20",
                name="Established Star",
                pa=400,
                hr=8,
                sb=3,
                avg=.230,
                metadata={"stats_ros": _STAR_ROS},
            ),
            _hitter(
                "anchor",
                "21",
                "Anchor Bat",
                pa=600,
                hr=24,
                sb=8,
                avg=.270,
                metadata={"stats_ros": _ANCHOR_ROS},
            ),
            _pitcher(),
        ],
        "2026-11-16",
        identities={
            "10": _born_aged(24),
            "11": _born_aged(25),
            "20": _born_aged(29),
            "21": _born_aged(28),
            "2": _born_aged(28),
        },
    )

    assert len(payload["players"]) == 5
    for row in payload["players"]:
        stability = row["components"]["projection_stability"]
        assert stability["ros_category_value"] is None
        assert stability["ros_true_talent_annualization_scale"] is None
        assert stability["ros_stability_weight"] == 0
        assert stability["stability_adjustment"] == 0
        assert stability["true_talent_floor_value"] is None
        assert stability["true_talent_floor_applied"] is False
        assert row["projection_value"] == stability["current_season_category_value"]


def test_mlb_layer_preseason_does_not_discount_young_starter_for_current_line_volatility(preseason_phase):
    payload = build_mlb_dynasty_layer(
        [
            _pitcher(
                player_id="young",
                mlbam_id="30",
                name="Young Current Spike",
                ip=170,
                strikeouts=245,
                era=1.90,
                metadata={"stats_actual": {"IP": 55}, "stats_ros": _YOUNG_SP_ROS},
            ),
            _hitter(),
            _pitcher(
                "stable",
                "31",
                "Stable Veteran",
                metadata={"stats_ros": _VETERAN_SP_ROS},
            ),
        ],
        "2026-11-16",
        identities={"30": _born_aged(23), "1": _born_aged(25), "31": _born_aged(29)},
    )

    row = next(item for item in payload["players"] if item["name"] == "Young Current Spike")
    adjustments = row["components"]["role_adjustments"]

    assert row["age"] == 23  # in the young band, so a zero discount can only come from the absent rest-of-season data
    assert adjustments["young_sp_volatility_discount"] == 0
    assert adjustments["starter_volatility_discount"] == 0


def test_mlb_layer_preseason_does_not_discount_young_hitter_for_current_line_volatility(preseason_phase):
    payload = build_mlb_dynasty_layer(
        [
            _hitter(
                player_id="young_bat",
                mlbam_id="40",
                name="Young Current Spike Bat",
                pa=690,
                hr=48,
                sb=28,
                avg=.330,
                metadata={"stats_actual": {"PA": 260}, "stats_ros": _YOUNG_BAT_ROS},
            ),
            _hitter("steady", "41", "Steady Bat"),
            _pitcher(),
        ],
        "2026-11-16",
        identities={"40": _born_aged(24), "41": _born_aged(28), "2": _born_aged(28)},
    )

    row = next(item for item in payload["players"] if item["name"] == "Young Current Spike Bat")
    adjustments = row["components"]["role_adjustments"]

    assert row["age"] == 24  # in the young band, so a zero discount can only come from the absent rest-of-season data
    assert adjustments["young_hitter_volatility_discount"] == 0
