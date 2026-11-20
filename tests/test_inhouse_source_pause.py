"""The redraft board pauses the in-house (H+P) source while its run is for another season."""
import json
import re
from urllib.parse import quote

import pytest

import app as app_module
from projections.export.valucast_hp_run import in_house_season_context

PAUSED_LINE = (
    "ValuCast H+P is paused until its 2027 projections are built. Showing the Steamer board."
)


def seasons(in_house, target):
    return lambda: {"in_house_season": in_house, "target_season": target, "season_note": "note"}


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


@pytest.fixture
def paused(monkeypatch):
    monkeypatch.setattr(app_module, "in_house_season_context", seasons(2026, 2027))


@pytest.fixture
def current(monkeypatch):
    monkeypatch.setattr(app_module, "_inhouse_source_current", lambda: True)


def first_player_id(html):
    return re.search(r"toggleDetail\('([^']+)', this\)", html).group(1)


def test_helpers_follow_the_season_context(monkeypatch):
    for in_house, target, is_current in ((2026, 2027, False), (2027, 2027, True)):
        monkeypatch.setattr(app_module, "in_house_season_context", seasons(in_house, target))
        assert app_module._inhouse_source_current() is is_current
        assert app_module._effective_source("valucast") == ("valucast" if is_current else "")
        assert app_module._effective_source("steamer") == "steamer"
        assert app_module._effective_source("") == ""


def test_loaded_run_is_the_run_of_the_in_house_season():
    # The pause lifts on the season constant, so the loaded run must be the run of that season.
    season = in_house_season_context()["in_house_season"]
    run = app_module.VALUCAST_HP_PATH.parent
    assert str(season) in run.name
    manifest = json.loads((run / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["as_of_season"] == season


def test_paused_valucast_request_serves_the_steamer_board(client, paused):
    steamer = client.get("/rankings?mode=categories")
    asked = client.get("/rankings?mode=categories&source=valucast")
    assert asked.status_code == 200
    html = asked.get_data(as_text=True)
    assert PAUSED_LINE in html
    assert PAUSED_LINE not in steamer.get_data(as_text=True)
    assert "new-chip" not in html
    assert "fully ValuCast-built" not in html  # footer provenance says Steamer
    assert first_player_id(html) == first_player_id(steamer.get_data(as_text=True))
    assert "source=" not in asked.headers.get("HX-Replace-Url", "")
    # CSV and share labels follow the effective source too.
    assert client.get("/export?source=valucast").data == client.get("/export").data
    assert app_module._redraft_share_labels({"mode": "categories"}, {"source": "valucast"}) == (
        "Categories", "Steamer")


SHARE_NOTE = "ValuCast H+P is paused; showing Steamer"


def test_paused_share_links_say_they_fell_back(client, paused):
    html = client.get("/redraft/share-card?source=valucast").get_data(as_text=True)
    assert "(Steamer)" in html
    assert "(Valucast)" not in html
    assert SHARE_NOTE in html
    assert SHARE_NOTE not in client.get("/redraft/share-card").get_data(as_text=True)
    player = quote(first_player_id(client.get("/rankings").get_data(as_text=True)), safe="")
    card = client.get(f"/redraft/player-card/{player}?source=valucast")
    assert card.status_code == 200
    assert SHARE_NOTE in card.get_data(as_text=True)
    assert SHARE_NOTE not in client.get(f"/redraft/player-card/{player}").get_data(as_text=True)


def test_paused_old_links_never_load_the_in_house_run(client, paused, monkeypatch):
    load = app_module.CATALOG.store_for

    def store_for(source=None):
        assert source != "valucast", "an old H+P link loaded the paused in-house run"
        return load(source)

    monkeypatch.setattr(app_module.CATALOG, "store_for", store_for)
    player = quote(first_player_id(client.get("/rankings").get_data(as_text=True)), safe="")
    for url in (
        "/?source=valucast",
        "/rankings?mode=categories&source=valucast",
        "/export?source=valucast",
        "/redraft/share-card?source=valucast",
        "/redraft/share-card.png?source=valucast",
        "/redraft/share-card.svg?source=valucast",
        f"/redraft/player-card/{player}?source=valucast",
        f"/redraft/player-card/{player}.png?source=valucast",
    ):
        assert client.get(url).status_code == 200, url
    detail = client.get(
        f"/player/{player}?mode=categories&source=valucast", headers={"HX-Request": "true"}
    )
    assert detail.status_code == 200


def test_old_share_link_serves_the_in_house_run_again_when_the_pause_lifts(
    client, current, monkeypatch
):
    load, asked = app_module.CATALOG.store_for, []

    def store_for(source=None):
        asked.append(source)
        return load(source)

    monkeypatch.setattr(app_module.CATALOG, "store_for", store_for)
    html = client.get("/redraft/share-card?source=valucast").get_data(as_text=True)
    assert "valucast" in asked
    assert "(Valucast)" in html
    assert SHARE_NOTE not in html
    assert client.get("/redraft/share-card.png?source=valucast").status_code == 200
    assert 'value="valucast" checked' in client.get("/?source=valucast").get_data(as_text=True)


def test_paused_pages_do_not_offer_the_source_choice(client, paused):
    for path in ("/", "/?source=valucast"):
        html = client.get(path).get_data(as_text=True)
        assert 'name="source"' not in html
        assert 'value="valucast"' not in html
        assert "<span>ValuCast H+P</span>" not in html
        assert "Projection source" not in html
        assert 'name="pool"' in html  # the rest of the toolbar is still there
    assert PAUSED_LINE in client.get("/?source=valucast").get_data(as_text=True)
    assert PAUSED_LINE not in client.get("/").get_data(as_text=True)


def test_paused_methodology_says_h_and_p_returns_when_the_run_is_built(client, paused):
    html = " ".join(client.get("/methodology").get_data(as_text=True).split())
    assert (
        "ValuCast H+P is paused between seasons; its last run covers 2026, and it returns "
        "as an opt-in source when the 2027 run is built."
    ) in html
    assert "available as an opt-in" not in html
    assert "You can value players from two sources" in html
    assert (
        "ValuCast H+P is paused between seasons, so the main board currently shows Steamer only."
    ) in html
    assert "A side-by-side look is useful for eyeballing differences" in html
    assert "Flipping the toggle" not in html
    assert "selectable on the main board" not in html


def test_paused_hub_and_scouting_do_not_call_h_and_p_opt_in_or_available(client, paused):
    hub = client.get("/intelligence").get_data(as_text=True)
    assert ">Paused</span>" in hub
    assert (
        "The ValuCast Hitter + Pitcher source is paused between seasons while the methodology "
        "page publishes the held-out scorecard and what has not been proven yet."
    ) in hub
    assert "stays opt-in" not in hub
    scouting = client.get("/scouting").get_data(as_text=True)
    assert "<span>Paused</span>" in scouting
    assert "<dt>ValuCast source</dt><dd>Paused</dd>" in scouting
    assert "<span>Opt-in</span>" not in scouting
    assert "<dt>ValuCast source</dt><dd>Available</dd>" not in scouting


def test_current_source_is_offered_and_honoured(client, current):
    html = client.get("/").get_data(as_text=True)
    assert 'name="source"' in html
    assert 'value="valucast"' in html
    asked = client.get("/rankings?mode=categories&source=valucast")
    assert asked.status_code == 200
    body = asked.get_data(as_text=True)
    assert PAUSED_LINE not in body
    assert "new-chip" in body
    assert "fully ValuCast-built" in body
    assert "source=valucast" in asked.headers.get("HX-Replace-Url", "")
    assert app_module._redraft_share_labels({"mode": "categories"}, {"source": "valucast"}) == (
        "Categories", "Valucast")
    methodology = " ".join(client.get("/methodology").get_data(as_text=True).split())
    assert "ValuCast H+P is available as an opt-in" in methodology
    assert "paused between seasons" not in methodology
    assert "Flipping the toggle is useful" in methodology
    assert "The projection source for player values is selectable on the main board." in methodology
    hub = client.get("/intelligence").get_data(as_text=True)
    assert "source stays opt-in while the methodology page" in " ".join(hub.split())
    assert ">Paused</span>" not in hub
    scouting = client.get("/scouting").get_data(as_text=True)
    assert "<span>Paused</span>" not in scouting
    assert "<dt>ValuCast source</dt><dd>Paused</dd>" not in scouting
    assert any(
        f"<dt>ValuCast source</dt><dd>{word}</dd>" in scouting for word in ("Available", "Building")
    )
