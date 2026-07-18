import json

from mlb.playing_time_role import build_playing_time_role_tracker
from mlb.playing_time_role import role_watch_rows
from mlb.playing_time_role import run_playing_time_role_tracker
from scripts.validate_playing_time_role_tracker import validate_playing_time_role_tracker


def _hitter():
    return {
        "name": "Everyday Bat",
        "pool": "hitter",
        "team": "BOS",
        "positions": ["SS"],
        "stats": {"PA": 585},
        "metadata": {"mlbam_id": "100"},
    }


def _pitcher():
    return {
        "name": "Starter Arm",
        "pool": "starter",
        "team": "SEA",
        "positions": ["SP"],
        "stats": {"IP": 165, "GS": 28},
        "metadata": {"mlbam_id": "200"},
    }


def test_playing_time_tracker_uses_mlbam_keyed_status_context():
    payload = build_playing_time_role_tracker(
        projections=[_hitter(), _pitcher()],
        roster_status={
            "artifact": "valucast_mlb_roster_status",
            "generated_at": "2026-06-16",
            "profiles": [
                {
                    "mlbam_id": 100,
                    "active_mlb_roster": True,
                    "source": "official_mlb_statsapi_active_roster",
                }
            ],
        },
        availability={
            "artifact": "valucast_mlb_availability",
            "generated_at": "2026-06-16",
            "profiles": [
                {
                    "mlbam_id": 200,
                    "status": "rehab",
                    "active_injury_risk": True,
                    "source": "official_mlb_statsapi_transactions",
                }
            ],
        },
        generated_at="2026-06-16T00:00:00+00:00",
    )

    assert payload["artifact"] == "valucast_playing_time_role_tracker"
    assert payload["source_policy"]["name_based_joins_used"] is False
    assert payload["validation"]["ready_for_role_context"] is True
    hitter = next(row for row in payload["profiles"] if row["mlbam_id"] == "100")
    pitcher = next(row for row in payload["profiles"] if row["mlbam_id"] == "200")
    assert hitter["projected_role"] == "everyday_regular"
    assert hitter["identity_key"] == "100_hitter"
    assert hitter["active_mlb_roster"] is True
    assert pitcher["projected_role"] == "rotation_workhorse"
    assert pitcher["active_injury_risk"] is True


def _reliever():
    return {
        "name": "Setup Arm",
        "pool": "reliever",
        "team": "LAD",
        "positions": ["RP"],
        "stats": {"IP": 65, "SV_HLD": 25},
        "metadata": {"mlbam_id": "300"},
    }


def _dynasty_layer():
    return {
        "layer_name": "valucast_mlb_dynasty_layer",
        "generated_at": "2026-06-16",
        "players": [
            {
                "mlbam_id": 100,
                "components": {
                    "playing_time_reliability": 90.0,
                    "availability_risk_discount": 0.0,
                    "role_adjustments": {"track_record_certainty": 80.0},
                    "track_record": {"experience_band": "established"},
                },
            }
        ],
    }


def test_role_v2_shadow_forecast_and_distribution():
    payload = build_playing_time_role_tracker(
        projections=[_hitter(), _reliever()],
        dynasty_layer=_dynasty_layer(),
        generated_at="2026-06-16T00:00:00+00:00",
    )

    hitter = next(row for row in payload["profiles"] if row["mlbam_id"] == "100")
    reliever = next(row for row in payload["profiles"] if row["mlbam_id"] == "300")

    # v1 fields untouched.
    assert hitter["projected_role"] == "everyday_regular"

    v2 = hitter["role_v2"]
    assert v2["feeds_card"] is False
    assert v2["role_probability_source"] == "volume_fan"
    assert abs(sum(v2["role_probabilities"].values()) - 1.0) < 1e-6
    assert v2["signals"]["dynasty_layer_matched"] is True
    assert v2["role_confidence"] == "high"  # 0.55*90 + 0.45*80 = 85.5
    assert v2["volume_forecast"]["low"] < v2["volume_forecast"]["point"]

    # Reliever role is SV/HLD-driven, not forecastable from an innings range.
    rv2 = reliever["role_v2"]
    assert rv2["role_probability_source"] == "save_hold_driven_v1_label"
    assert rv2["role_probabilities"] == {reliever["projected_role"]: 1.0}
    assert rv2["signals"]["dynasty_layer_matched"] is False  # no default match -> neutral

    summary = payload["v2"]
    assert summary["feeds_card"] is False
    assert summary["volume_fan_role_count"] == 1
    assert summary["save_hold_label_count"] == 1
    assert summary["dynasty_layer_matched_count"] == 1


def test_role_v2_falls_back_to_neutral_signals_without_dynasty_layer():
    payload = build_playing_time_role_tracker(
        projections=[_hitter()],
        generated_at="2026-06-16T00:00:00+00:00",
    )
    v2 = payload["profiles"][0]["role_v2"]
    assert v2["signals"]["dynasty_layer_matched"] is False
    assert v2["signals"]["reliability"] is None  # neutral default applied internally
    assert v2["role_confidence"] in {"low", "moderate", "high"}
    assert isinstance(v2["role_probabilities"], dict) and v2["role_probabilities"]


def test_run_and_validate_role_tracker(tmp_path):
    projection_path = tmp_path / "hp.json"
    roster_path = tmp_path / "roster.json"
    availability_path = tmp_path / "availability.json"
    dynasty_path = tmp_path / "dynasty.json"
    artifact_path = tmp_path / "role.json"
    archive_dir = tmp_path / "archive"
    projection_path.write_text(json.dumps([_hitter(), _pitcher()]), encoding="utf-8")
    roster_path.write_text(json.dumps({"profiles": []}), encoding="utf-8")
    availability_path.write_text(json.dumps({"profiles": []}), encoding="utf-8")
    dynasty_path.write_text(json.dumps(_dynasty_layer()), encoding="utf-8")

    result = run_playing_time_role_tracker(
        projection_path=projection_path,
        roster_status_path=roster_path,
        availability_path=availability_path,
        dynasty_layer_path=dynasty_path,
        artifact_path=artifact_path,
        archive_dir=archive_dir,
    )
    _, problems = validate_playing_time_role_tracker(artifact_path)

    assert result["ready_for_role_context"] is True
    assert result["archive_changed"] is True
    assert problems == []


def test_midseason_ros_volume_is_annualized_before_role_thresholds():
    """7/2 regression (the Bobby Witt Jr. case): thresholds are full-season volumes
    but the projection source is rest-of-season — mid-season, a franchise player at
    ~280 ROS PA must NOT decay to bench_or_depth."""
    from mlb.playing_time_role import build_playing_time_role_tracker

    star = {
        "mlbam_id": 1, "name": "Franchise Star", "pool": "hitter",
        "positions": ["SS"], "stats": {"PA": 280.0},
    }
    payload = build_playing_time_role_tracker(
        projections=[star], generated_at="2026-07-02T12:00:00+00:00",
    )
    profile = payload["profiles"][0]
    assert profile["projected_role"] in ("everyday_regular", "regular")
    assert profile["projected_volume"] == 280.0        # display stays honest ROS
    assert profile["season_pace_factor"] > 1.5

    # Pre-season the same PA line is genuinely part-time — no annualization.
    payload_pre = build_playing_time_role_tracker(
        projections=[star], generated_at="2026-03-01T12:00:00+00:00",
    )
    assert payload_pre["profiles"][0]["projected_role"] == "part_time_or_strong_side"
    assert payload_pre["profiles"][0]["season_pace_factor"] == 1.0


def _role_row(*, pool="reliever", ip=60.0, gs=0.0, p_sp=0.2, mlbam_id="901"):
    return {
        "name": "Role Test Arm",
        "pool": pool,
        "team": "SEA",
        "positions": ["P"],
        "stats": {"IP": ip, "GS": gs, "SV_HLD": 0.0},
        "metadata": {"mlbam_id": mlbam_id, "p_sp": p_sp},
    }


def test_high_ip_reliever_with_zero_starts_stays_relief():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(ip=70.0, gs=0.0)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    profile = payload["profiles"][0]
    assert profile["projected_role"] == "middle_relief"
    assert profile["source_pool"] == "reliever"
    assert profile["starter_probability"] == 0.2
    assert profile["projected_starts_ros"] == 0.0
    assert profile["projected_innings_ros"] == 70.0
    assert profile["role_context_status"] == "ready"
    assert profile["role_context_blockers"] == []


def test_generic_pitcher_with_starter_volume_is_rotation_starter():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(pool="pitcher", ip=60.0, gs=8.0)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    assert payload["profiles"][0]["projected_role"] in {
        "rotation_starter", "rotation_workhorse"
    }


def test_projected_starts_with_zero_innings_blocks_role_context():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(pool="starter", ip=0.0, gs=7.0, p_sp=0.95)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    profile = payload["profiles"][0]
    assert profile["role_context_status"] == "blocked"
    assert "projected_starts_without_innings" in profile["role_context_blockers"]


def test_invalid_probability_and_negative_volume_block_role_context():
    payload = build_playing_time_role_tracker(
        projections=[_role_row(ip=-1.0, gs=-1.0, p_sp=1.2)],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    blockers = payload["profiles"][0]["role_context_blockers"]
    assert blockers == [
        "starter_probability_out_of_range",
        "negative_projected_starts",
        "negative_projected_innings",
    ]


def test_validator_checks_profiles_after_first_200(tmp_path):
    payload = build_playing_time_role_tracker(
        projections=[
            _role_row(mlbam_id=str(10_000 + index), p_sp=0.2)
            for index in range(201)
        ],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    payload["profiles"][200].pop("source_pool")
    path = tmp_path / "role.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, problems = validate_playing_time_role_tracker(path)
    assert any("profile 201 missing source_pool" in problem for problem in problems)


def test_validator_rejects_incoherent_status_and_blockers(tmp_path):
    payload = build_playing_time_role_tracker(
        projections=[_role_row()],
        generated_at="2026-07-17T12:00:00+00:00",
    )
    payload["profiles"][0]["role_context_status"] = "ready"
    payload["profiles"][0]["role_context_blockers"] = ["contradiction"]
    path = tmp_path / "role.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    _, problems = validate_playing_time_role_tracker(path)
    assert any("ready profile has blockers" in problem for problem in problems)


def _watch_profile(**overrides):
    profile = {
        "name": "Opportunity Arm",
        "source_pool": "reliever",
        "starter_probability": 0.42,
        "projected_starts_ros": 2.0,
        "projected_innings_ros": 30.0,
        "active_mlb_roster": True,
        "active_injury_risk": False,
        "availability_status": "active_mlb_roster",
        "role_context_status": "ready",
        "role_context_blockers": [],
    }
    profile.update(overrides)
    return profile


def test_role_watch_includes_only_explainable_active_opportunity():
    rows = role_watch_rows([_watch_profile()])
    assert len(rows) == 1
    assert "2.0 starts and 30.0 innings" in rows[0]["opportunity_explanation"]
    assert "42%" in rows[0]["opportunity_explanation"]


def test_role_watch_suppresses_injury_inactive_noise_and_blockers():
    rows = role_watch_rows([
        _watch_profile(name="Injured", active_injury_risk=True),
        _watch_profile(name="Inactive", active_mlb_roster=False),
        _watch_profile(name="Unknown", availability_status="unknown"),
        _watch_profile(name="Fractional", projected_starts_ros=0.9),
        _watch_profile(name="No innings", projected_innings_ros=0.0),
        _watch_profile(name="No probability", starter_probability=None),
        _watch_profile(name="Blocked", role_context_status="blocked",
                       role_context_blockers=["contradiction"]),
        _watch_profile(name="Starter pool", source_pool="starter"),
    ])
    assert rows == []


def test_role_watch_orders_by_projected_starts_then_name_without_mutation():
    profiles = [
        _watch_profile(name="Zulu", projected_starts_ros=2.0),
        _watch_profile(name="Alpha", projected_starts_ros=2.0),
        _watch_profile(name="First", projected_starts_ros=3.0),
    ]
    rows = role_watch_rows(profiles)
    assert [row["name"] for row in rows] == ["First", "Alpha", "Zulu"]
    assert all("opportunity_explanation" not in row for row in profiles)

