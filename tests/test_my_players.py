import html
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app as app_module
from werkzeug.datastructures import MultiDict

from app import _parse_watch_keys


def test_parse_watch_keys_preserves_roles_order_and_removes_duplicates():
    assert _parse_watch_keys(
        [
            "682634_hitter",
            "682634_pitcher",
            "682634_hitter",
            "800001_hitter",
        ]
    ) == ["682634_hitter", "682634_pitcher", "800001_hitter"]


def test_parse_watch_keys_rejects_malformed_values():
    assert _parse_watch_keys(
        [
            "",
            "0_hitter",
            "-1_pitcher",
            "Aaron_Judge_hitter",
            "682634_catcher",
            "682634_hitter_extra",
            "12345678901_hitter",
            "682634_pitcher",
        ]
    ) == ["682634_pitcher"]


def test_parse_watch_keys_caps_unique_values_at_50():
    values = [f"{700000 + index}_hitter" for index in range(60)]
    assert _parse_watch_keys(values) == values[:50]


def _redraft_watch_case():
    ctx = app_module._build_context(MultiDict())
    for result in ctx["results"]:
        mlbam_id = app_module._mlbam_id(result.player)
        if not mlbam_id:
            continue
        role = app_module._watch_role_for_pool(result.player.pool)
        return ctx, result, f"{mlbam_id}_{role}"
    raise AssertionError("Committed redraft board has no watchable player")


def test_my_players_empty_partial():
    response = app_module.app.test_client().get(
        "/my-players", headers={"HX-Request": "true"}
    )

    assert response.status_code == 200
    assert response.get_data(as_text=True).strip() == ""
    assert response.headers["Cache-Control"] == "private, no-store"


def test_my_players_browser_visit_redirects_home():
    response = app_module.app.test_client().get(
        "/my-players?watch=682634_hitter",
        headers={"Accept": "text/html"},
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_redraft_partial_matches_current_board_rank_and_value():
    ctx, result, key = _redraft_watch_case()

    response = app_module.app.test_client().get(
        "/my-players",
        query_string=[("watch", key)],
        headers={"HX-Request": "true"},
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert html.escape(result.player.name) in body
    assert f"#{ctx['overall_ranks'][result.player.id]}" in body
    assert f"{result.total_value:.2f}" in body
    assert (result.player.metadata.get("team") or "FA") in body
    assert "Unfollow" in body


def test_display_filters_do_not_hide_a_followed_player():
    _ctx, _result, key = _redraft_watch_case()
    client = app_module.app.test_client()
    baseline = client.get(
        "/my-players",
        query_string=[("watch", key), ("cats", "R,HR,RBI,SB,AVG")],
        headers={"HX-Request": "true"},
    ).get_data(as_text=True)
    filtered = client.get(
        "/my-players",
        query_string=[
            ("watch", key),
            ("cats", "R,HR,RBI,SB,AVG"),
            ("pool", "pitcher"),
            ("position", "C"),
            ("search", "definitely-not-this-player"),
            ("callups", "debuted"),
            ("display", "values"),
        ],
        headers={"HX-Request": "true"},
    ).get_data(as_text=True)

    assert filtered == baseline


def test_hitter_and_pitcher_roles_do_not_collapse_in_partial():
    response = app_module.app.test_client().get(
        "/my-players",
        query_string=[
            ("watch", "9999999999_hitter"),
            ("watch", "9999999999_pitcher"),
        ],
        headers={"HX-Request": "true"},
    )
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert body.count('class="my-player-row is-unavailable"') == 2
    assert 'data-watch-key="9999999999_hitter"' in body
    assert 'data-watch-key="9999999999_pitcher"' in body
