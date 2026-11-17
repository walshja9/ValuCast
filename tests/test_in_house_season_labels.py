from types import SimpleNamespace

import pytest
from flask import render_template

import app as app_module
from scraper import season
from web.dynasty_models import DynastyRankingRow


NOTE = "In-house line: 2026 season; not a 2027 comparison."


@pytest.fixture(autouse=True)
def preseason(monkeypatch):
    monkeypatch.setattr(season, "TARGET_SEASON", 2027)


def test_template_context_has_both_in_house_and_target_seasons():
    with app_module.app.test_request_context("/"):
        context = app_module._snapshot_staleness()
    assert context["hp_season_context"] == {
        "in_house_season": 2026,
        "target_season": 2027,
        "season_note": NOTE,
    }


def test_role_watch_labels_the_in_house_season():
    with app_module.app.test_request_context("/role-watch"):
        body = render_template("role_watch.html", rows=[], generated_at=None)
    assert NOTE in body


@pytest.mark.parametrize("route", ["/scouting", "/intelligence"])
def test_tracker_summary_labels_the_in_house_season(monkeypatch, route):
    repository = {"summary": {"report_count": 0}, "reports": []}
    monkeypatch.setattr(
        app_module,
        "_load_artifact",
        lambda path: repository if path.name == "valucast_scouting_reports.json" else None,
    )
    response = app_module.app.test_client().get(route)
    assert response.status_code == 200
    assert NOTE in response.get_data(as_text=True)


@pytest.mark.parametrize("player_type", ["mlb", "prospect"])
def test_dynasty_card_opportunity_labels_the_in_house_season(player_type):
    row = DynastyRankingRow(
        id="season-label-fixture", name="Season Label Fixture",
        player_type=player_type, positions=("SP",), team="TST", age=27,
        dynasty_rank=1, dynasty_value=50.0, status="active", mlbam_id="999999",
        level="MLB" if player_type == "mlb" else "AAA",
    )
    with app_module.app.test_request_context("/player/season-label-fixture"):
        body = render_template(
            "partials/player_detail_dynasty.html", row=row,
            role_profile={"projected_role_label": "Rotation Starter", "projected_volume": None},
        )
    assert NOTE in body


def test_dynasty_graphic_read_labels_in_house_opportunity():
    row = SimpleNamespace(
        name="Season Label Fixture", dna="", positions=("SP",),
        dynasty_rank=1, dynasty_value=50.0,
    )
    read = app_module._dynasty_card_read(row, {
        "role_profile": {"projected_role": "rotation_starter", "season_note": NOTE},
    })
    assert read.startswith(NOTE)


def test_card_role_context_stamps_older_tracker_artifacts(monkeypatch):
    row = SimpleNamespace(mlbam_id="999999", role="pitcher")
    profile = {"mlbam_id": "999999", "identity_key": "999999_pitcher"}
    monkeypatch.setattr(app_module, "_ahead_of_consensus_for_key", lambda key: None)
    monkeypatch.setattr(app_module, "_consensus_gap_for_key", lambda key: None)
    monkeypatch.setattr(
        app_module, "_load_artifact",
        lambda path: {"profiles": [profile]} if path.name == "valucast_playing_time_role_tracker.json" else None,
    )
    context = app_module._artifact_context_for_row(row)
    assert context["role_profile"]["season_note"] == NOTE
    assert "season_note" not in profile
