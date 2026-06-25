"""Redraft individual player share-card routes."""
from __future__ import annotations

import pytest
from werkzeug.datastructures import MultiDict

import app as app_module

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


def _first_redraft_player_id(role: str) -> str:
    ctx = app_module._build_context(MultiDict())
    for result in ctx["results"]:
        is_pitcher = result.player.pool in app_module._PITCHER_POOLS
        if (role == "pitcher" and is_pitcher) or (role == "hitter" and not is_pitcher):
            return result.player.id
    pytest.skip(f"no valued redraft {role} available")


@pytest.mark.parametrize("role", ["hitter", "pitcher"])
def test_redraft_player_card_png_renders_for_hitters_and_pitchers(client, role):
    player_id = _first_redraft_player_id(role)

    response = client.get(f"/redraft/player-card/{player_id}.png")

    assert response.status_code == 200
    assert response.data[:8] == PNG_MAGIC
    assert "image/png" in response.content_type
    assert len(response.data) > 1000


@pytest.mark.parametrize("role", ["hitter", "pitcher"])
def test_redraft_player_card_preview_renders_for_hitters_and_pitchers(client, role):
    player_id = _first_redraft_player_id(role)

    response = client.get(f"/redraft/player-card/{player_id}")

    assert response.status_code == 200
    assert "text/html" in response.content_type
    assert b"Redraft Value Card" in response.data
    assert f"/redraft/player-card/{player_id}.png".encode() in response.data


def test_redraft_player_detail_share_link_carries_query_string(client):
    player_id = _first_redraft_player_id("hitter")
    query = "mode=categories&cats=R,HR&pcats=K,ERA&source=steamer"

    response = client.get(
        f"/player/{player_id}?{query}",
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="player-share-link"' in html
    assert (
        f'href="/redraft/player-card/{player_id}?'
        "mode=categories&amp;cats=R,HR&amp;pcats=K,ERA&amp;source=steamer"
        '"'
    ) in html


@pytest.mark.skipif(not app_module.dd_store.is_available, reason="needs dynasty feed")
def test_dynasty_player_card_still_renders_after_shared_renderer_refactor(client):
    response = client.get("/dynasty/player-card/vc_mlb_687462_hitter.png")

    assert response.status_code == 200
    assert response.data[:8] == PNG_MAGIC
    assert "image/png" in response.content_type
    assert len(response.data) > 1000
