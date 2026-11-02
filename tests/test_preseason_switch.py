"""Offline coverage for the explicit projection-season switch."""
import json
import os
from copy import deepcopy
from unittest.mock import patch

import pytest

import scraper.season as season
from league_values.models import PlayerPool, PlayerProjection
from scraper.combine import attach_actuals, combine_outlook
from scraper.fangraphs import fetch_all
from scraper.refresh import refresh
from web.projection_store import ProjectionStore


def test_season_ships_in_season_and_can_be_patched():
    assert getattr(season, "TARGET_SEASON", None) == 2026
    assert season.is_preseason() is False
    with patch.object(season, "TARGET_SEASON", 2027):
        assert season.is_preseason() is True
        with patch.object(season, "CONTEXT_SEASON", 2027):
            assert season.is_preseason() is False


@pytest.mark.parametrize("system", ["steamerr", "steamer"])
def test_fetch_all_passes_system_through(system):
    with patch("scraper.fangraphs.fetch_projections", return_value=[]) as fetch:
        assert fetch_all(delay=0, system=system) == {
            "steamer_hitters": [], "steamer_pitchers": [],
        }
    assert [call.args for call in fetch.call_args_list] == [
        (system, "bat"), (system, "pit"),
    ]


_ROS = [{
    "id": "test", "name": "Test Player", "pool": "hitter", "positions": ["SS"],
    "stats": {"PA": 600, "HR": 30}, "metadata": {"mlbam_id": "1"},
}]
_ACTUALS = [{
    "id": "test", "name": "Test Player", "pool": "hitter",
    "stats": {"PA": 200, "HR": 10}, "metadata": {"mlbam_id": "1"},
}]


@pytest.mark.parametrize("actual_as_of", [None, "2026-09-27"])
def test_attach_actuals_keeps_projection_stats_and_attaches_actual_metadata(actual_as_of):
    ros = deepcopy(_ROS)
    actuals = deepcopy(_ACTUALS)
    ros[0]["metadata"]["as_of"] = "2027-02-01"
    if actual_as_of is not None:
        actuals[0]["metadata"]["as_of"] = actual_as_of

    result = attach_actuals(ros, actuals)

    assert result[0]["stats"] == ros[0]["stats"]
    assert result[0]["metadata"]["stats_actual"] == actuals[0]["stats"]
    assert result[0]["metadata"]["as_of"] == (actual_as_of or "2027-02-01")
    assert result[0]["metadata"]["base_id"] == "mlbam_1"
    assert result[0]["metadata"]["has_ros"] is True
    assert "stats_ros" not in result[0]["metadata"]


@pytest.mark.parametrize("ros_pool,actual_pool", [
    ("starter", "reliever"), ("reliever", "starter"),
])
def test_attach_actuals_joins_two_way_players_by_pool_family(ros_pool, actual_pool):
    ros_pitcher = {
        "id": "test_pitcher", "pool": ros_pool,
        "stats": {"IP": 160, "ERA": 3.5}, "metadata": {"mlbam_id": "1"},
    }
    actual_pitcher = {
        "id": "test_pitcher", "pool": actual_pool,
        "stats": {"IP": 80, "ERA": 3.0}, "metadata": {"mlbam_id": "1"},
    }

    result = attach_actuals(_ROS + [ros_pitcher], [actual_pitcher] + _ACTUALS)

    assert result[0]["metadata"]["stats_actual"] == _ACTUALS[0]["stats"]
    assert result[1]["metadata"]["stats_actual"] == actual_pitcher["stats"]
    assert result[1]["stats"] == ros_pitcher["stats"]


def test_attach_actuals_drops_actuals_only_players():
    actuals_only = {
        "id": "actuals_only", "pool": "hitter",
        "stats": {"PA": 200}, "metadata": {"mlbam_id": "2"},
    }

    result = attach_actuals(_ROS, _ACTUALS + [actuals_only])

    assert [row["id"] for row in result] == ["test"]


def test_attach_actuals_passes_through_rows_without_mlbam_id():
    ros = {"id": "no_id", "pool": "hitter", "stats": {"PA": 500}}

    result = attach_actuals([ros], _ACTUALS)

    assert result == [{**ros, "metadata": {"has_ros": True}}]


def test_attach_actuals_passes_through_unmatched_projection():
    result = attach_actuals(_ROS, [])

    assert result == [{**_ROS[0], "metadata": {
        "mlbam_id": "1", "base_id": "mlbam_1", "has_ros": True,
    }}]


def test_attach_actuals_does_not_mutate_inputs():
    ros = deepcopy(_ROS)
    ros[0]["metadata"].update({"has_ros": False, "base_id": "source"})
    actuals = deepcopy(_ACTUALS)
    actuals[0]["metadata"]["as_of"] = "2026-09-27"
    before_ros = deepcopy(ros)
    before_actuals = deepcopy(actuals)

    result = attach_actuals(ros, actuals)

    assert ros == before_ros
    assert actuals == before_actuals
    assert result[0] is not ros[0]
    assert result[0]["metadata"] is not ros[0]["metadata"]


def _paths(tmp_path):
    return {name: str(tmp_path / filename) for name, filename in (
        ("output_path", "current.json"), ("ros_output_path", "ros.json"),
        ("actuals_output_path", "actuals.json"), ("metadata_path", "metadata.json"),
        ("raw_dir", "raw"),
    )}


@pytest.mark.parametrize("target,system,phase", [
    (2026, "steamerr", "in_season_outlook"),
    (2027, "steamer", "preseason_full_season"),
])
def test_refresh_phase_keeps_actuals_separate(tmp_path, target, system, phase):
    paths = _paths(tmp_path)
    with patch.object(season, "TARGET_SEASON", target), \
         patch.dict(os.environ, {"VALUCAST_ACTUALS_SEASON": "2026"}), \
         patch("scraper.refresh.fetch_all", return_value={"steamer_hitters": [{}]}) as fetch, \
         patch("scraper.refresh.save_raw"), \
         patch("scraper.refresh.blend_projections", return_value=_ROS), \
         patch("scraper.refresh.build_actuals", return_value=_ACTUALS) as actuals, \
         patch("scraper.refresh.combine_outlook", wraps=combine_outlook) as combine, \
         patch("scraper.refresh.attach_actuals", wraps=attach_actuals) as attach:
        result = refresh(**paths, delay=0)
    assert fetch.call_args.kwargs.get("system", "steamerr") == system
    actuals.assert_called_once()
    assert actuals.call_args.kwargs["season"] == 2026
    if target == 2027:
        attach.assert_called_once_with(_ROS, _ACTUALS)
        combine.assert_not_called()
    else:
        combine.assert_called_once_with(_ROS, _ACTUALS)
        attach.assert_not_called()
    assert json.loads((tmp_path / "actuals.json").read_text()) == _ACTUALS
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["target_season"] == target
    assert metadata["season"] == 2026
    assert metadata["projection_phase"] == phase
    assert metadata["ros_source"] == (
        "fangraphs_steamer_full_season" if target == 2027 else "fangraphs_steamer_ros"
    )
    assert result[0]["stats"]["HR"] == (30 if target == 2027 else 40)
    assert result[0]["metadata"]["stats_actual"] == _ACTUALS[0]["stats"]
    if target == 2027:
        assert result[0]["stats"] == _ROS[0]["stats"]
        assert "stats_ros" not in result[0]["metadata"]


@pytest.mark.parametrize("prior_target", [None, 2026, 2027])
def test_preseason_retained_ros_requires_matching_target(tmp_path, prior_target):
    paths = _paths(tmp_path)
    prior_bytes = (json.dumps(_ROS) + "\n").encode("ascii")
    (tmp_path / "ros.json").write_bytes(prior_bytes)
    (tmp_path / "metadata.json").write_text(json.dumps(
        {} if prior_target is None else {"target_season": prior_target}
    ))
    with patch.object(season, "TARGET_SEASON", 2027), \
         patch("scraper.refresh.fetch_all", return_value={"steamer_hitters": []}), \
         patch("scraper.refresh.regular_season_games_final", return_value=0), \
         patch("scraper.refresh.build_actuals", return_value=_ACTUALS), \
         patch("scraper.refresh.save_raw") as save, \
         patch("scraper.refresh.blend_projections") as blend:
        if prior_target == 2027:
            refresh(**paths, delay=0, season=2026)
            metadata = json.loads((tmp_path / "metadata.json").read_text())
            assert metadata["ros_status"] == "retained"
        else:
            with pytest.raises(RuntimeError, match="target_season"):
                refresh(**paths, delay=0, season=2026)
            assert not (tmp_path / "current.json").exists()
    save.assert_not_called()
    blend.assert_not_called()
    assert (tmp_path / "ros.json").read_bytes() == prior_bytes


@pytest.mark.parametrize("target,expected,source", [
    (2026, 20, "projection_metadata"),
    (2027, 26, "valucast_identity_birth_date"),
])
def test_dynasty_age_uses_target_birth_date_only_in_preseason(target, expected, source):
    from mlb.dynasty import _player_age

    player = PlayerProjection(
        id="test", name="Test", pool=PlayerPool.HITTER,
        stats={}, metadata={"mlbam_id": "1", "age": 20},
    )
    with patch.object(season, "TARGET_SEASON", target):
        assert _player_age(player, {"1": {"birth_date": "2000-04-02"}}, target) == (
            expected, source,
        )


@pytest.mark.parametrize("target", [2026, 2027])
def test_dynasty_horizon_starts_at_projection_season(target):
    from mlb.dynasty import build_mlb_dynasty_layer
    from test_mlb_dynasty_layer import _hitter, _pitcher

    with patch.object(season, "TARGET_SEASON", target), \
         patch("mlb.dynasty._ros_lookup", return_value={}) as ros:
        payload = build_mlb_dynasty_layer(
            [_hitter(metadata={"age": 25}), _pitcher(metadata={"age": 28})],
            "2026-11-02", identities={
                "1": {"birth_date": "2001-01-01"},
                "2": {"birth_date": "1998-01-01"},
            },
        )
    assert payload["players"]
    for row in payload["players"]:
        assert row["components"]["horizon_years"][0]["season"] == target
        stability = row["components"]["projection_stability"]
        assert stability["ros_category_value"] is None
        assert stability["ros_stability_weight"] == 0
    assert ros.call_count > 0 if target == 2026 else ros.call_count == 0


@pytest.mark.parametrize("metadata", [{}, {
    "target_season": 2027, "projection_phase": "preseason_full_season",
}])
def test_projection_store_exposes_phase_metadata(tmp_path, metadata):
    (tmp_path / "current.json").write_text("[]")
    (tmp_path / "metadata.json").write_text(json.dumps(metadata))
    store = ProjectionStore(tmp_path / "current.json")
    assert store.target_season == metadata.get("target_season")
    assert store.projection_phase == metadata.get("projection_phase")


def test_redraft_footer_uses_published_phase():
    import app as app_module

    with patch.object(app_module.store, "_projection_phase", "preseason_full_season"), \
         patch.object(app_module.store, "_target_season", 2027), \
         patch.object(app_module.store, "_ros_status", "retained"):
        response = app_module.app.test_client().get("/rankings?mode=categories&horizon=redraft")
    assert response.status_code == 200
    assert b"Redraft values use Steamer 2027 full-season projections, scored against your league's categories and weights." in response.data


@pytest.mark.parametrize("count,expected", [(50, "live"), (49, "not_live"), (0, "unknown")])
def test_feed_verdict_thresholds(count, expected):
    from scripts.check_steamer_season import verdict

    rows = [{"xMLBAMID": i} for i in range(count)]
    assert verdict(rows, set(range(50))) == expected


def test_feed_verdict_counts_both_id_keys():
    from scripts.check_steamer_season import verdict

    rows = [{"xMLBAMID": str(i)} for i in range(25)]
    rows += [{"MLBAMID": str(i)} for i in range(25, 50)]
    assert verdict(rows, set(range(50))) == "live"
    assert verdict([{"xMLBAMID": 999}], set(range(50))) == "not_live"
