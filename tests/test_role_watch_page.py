import json

import pytest

import app as app_module
from app import app
from mlb.playing_time_role import build_playing_time_role_tracker
from mlb.playing_time_role import TRACKER_VERSION


@pytest.fixture
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _payload():
    return build_playing_time_role_tracker(
        projections=[
            {
                "name": "Opportunity Arm",
                "team": "SEA",
                "pool": "reliever",
                "positions": ["P"],
                "stats": {"GS": 2.0, "IP": 30.0},
                "metadata": {"mlbam_id": "901", "p_sp": 0.42},
            },
            {
                "name": "Injured Arm",
                "team": "BOS",
                "pool": "reliever",
                "positions": ["P"],
                "stats": {"GS": 3.0, "IP": 35.0},
                "metadata": {"mlbam_id": "902", "p_sp": 0.45},
            },
        ],
        roster_status={
            "profiles": [
                {"mlbam_id": "901", "active_mlb_roster": True},
                {"mlbam_id": "902", "active_mlb_roster": True},
            ]
        },
        availability={
            "profiles": [
                {
                    "mlbam_id": "901",
                    "status": "active_mlb_roster",
                    "active_injury_risk": False,
                },
                {
                    "mlbam_id": "902",
                    "status": "injured",
                    "active_injury_risk": True,
                },
            ]
        },
        generated_at="2026-07-17T12:00:00+00:00",
    )


def _serve(monkeypatch, tmp_path, payload):
    path = tmp_path / "role.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(app_module, "ROLE_WATCH_HOLD", False)
    monkeypatch.setattr(app_module, "_ROLE_WATCH_ARTIFACT_PATH", path)
    app_module._ARTIFACT_CACHE.clear()


def test_role_watch_held_returns_404(client, monkeypatch):
    monkeypatch.setattr(app_module, "ROLE_WATCH_HOLD", True)
    assert client.get("/role-watch").status_code == 404


@pytest.mark.parametrize("mutation", ["version", "ready", "rank", "value", "profile"])
def test_role_watch_invalid_contract_returns_404(client, monkeypatch, tmp_path, mutation):
    payload = _payload()
    if mutation == "version":
        payload["tracker_version"] = "old"
    elif mutation == "ready":
        payload["validation"]["ready_for_role_context"] = False
    elif mutation == "rank":
        payload["source_policy"]["feeds_live_rank"] = True
    elif mutation == "value":
        payload["source_policy"]["feeds_live_value"] = True
    else:
        payload["profiles"][0].pop("source_pool")
    _serve(monkeypatch, tmp_path, payload)
    assert client.get("/role-watch").status_code == 404


def test_role_watch_renders_only_eligible_explainable_rows(client, monkeypatch, tmp_path):
    _serve(monkeypatch, tmp_path, _payload())
    response = client.get("/role-watch")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert "ROLE WATCH · PRIVATE REVIEW" in body
    assert "Projected opportunity, not a conversion grade" in body
    assert "Opportunity Arm" in body
    assert "2.0 starts and 30.0 innings" in body
    assert "Active MLB Roster" in body
    assert "Active Mlb Roster" not in body
    assert "Injured Arm" not in body
    assert "cannot affect rankings, values, caps, or publication decisions" in body


def test_role_watch_has_no_site_navigation_link(client):
    body = client.get("/").data.decode("utf-8")
    assert 'href="/role-watch"' not in body
