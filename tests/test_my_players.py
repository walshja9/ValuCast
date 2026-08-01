import html
import sys
from pathlib import Path
from types import SimpleNamespace

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


def test_watch_context_args_keep_settings_and_remove_only_display_narrowing():
    args = MultiDict([
        ("mode", "prospects"),
        ("cats", "OPS"),
        ("cats", "SB"),
        ("teams", "16"),
        ("pool", "hitter"),
        ("position", "SS"),
        ("search", "Made"),
        ("callups", "undebuted"),
        ("display", "values"),
        ("watch", "682634_hitter"),
    ])

    clean = app_module._watch_context_args(args)

    assert clean.get("mode") == "prospects"
    assert clean.getlist("cats") == ["OPS", "SB"]
    assert clean.get("teams") == "16"
    assert set(clean.keys()).isdisjoint({"pool", "position", "search", "callups", "display", "watch"})


def test_same_prospect_identity_resolves_on_dynasty_and_prospect_boards():
    dynasty_ctx = app_module._build_dynasty_context(MultiDict([("mode", "dd_dynasty")]))
    prospect_ctx = app_module._build_dynasty_context(MultiDict([("mode", "prospects")]))
    app_module._apply_prospect_board_context(
        prospect_ctx, MultiDict([("mode", "prospects")])
    )
    prospect_by_key = {
        app_module._row_identity_key(row): row
        for row in prospect_ctx["dd_rows"]
        if app_module._row_identity_key(row)
    }
    row = next(
        row for row in dynasty_ctx["dd_rows"]
        if app_module._row_identity_key(row) in prospect_by_key
    )
    key = app_module._row_identity_key(row)
    client = app_module.app.test_client()

    for mode in ("dd_dynasty", "prospects"):
        body = client.get(
            "/my-players",
            query_string=[("mode", mode), ("watch", key)],
            headers={"HX-Request": "true"},
        ).get_data(as_text=True)
        assert html.escape(row.name) in body
        assert "Not available on this board" not in body


def test_dynasty_now_panel_uses_displayed_dynasty_rank_not_sort_position():
    args = MultiDict([
        ("mode", "dd_dynasty"),
        ("cats", "R,HR,RBI,SB,OBP"),
        ("pcats", "W,SV,K,ERA,WHIP"),
        ("rank_by", "now"),
    ])
    board = app_module._build_dynasty_context(args)
    index, row = next(
        (index, row)
        for index, row in enumerate(board["dd_rows"], 1)
        if row.dynasty_rank != index and app_module._row_identity_key(row)
    )

    panel = app_module._my_players_context(
        args, [app_module._row_identity_key(row)]
    )["watch_rows"][0]

    assert index != row.dynasty_rank
    assert panel["rank_label"] == f"#{row.dynasty_rank}"


def test_custom_prospect_panel_uses_displayed_prospect_rank_not_sort_position():
    args = MultiDict([
        ("mode", "prospects"),
        ("preset", "ops_7x7"),
        ("rank_by", "league"),
    ])
    board = app_module._build_dynasty_context(args)
    app_module._apply_prospect_board_context(board, args)
    assert board["custom_cats_active"] is True
    index, row = next(
        (index, row)
        for index, row in enumerate(board["dd_rows"], 1)
        if row.prospect_rank != index and app_module._row_identity_key(row)
    )

    panel = app_module._my_players_context(
        args, [app_module._row_identity_key(row)]
    )["watch_rows"][0]

    assert index != row.prospect_rank
    assert panel["rank_label"] == f"#{row.prospect_rank}"


def test_watch_controls_reject_malformed_feed_identities():
    bad_player = SimpleNamespace(
        metadata={"mlbam_id": "abc"},
        pool=object(),
    )
    bad_row = SimpleNamespace(mlbam_id=-1, role="pitcher")

    assert app_module._watch_identity_for_player(bad_player) is None
    assert app_module._watch_identity_for_row(bad_row) is None


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


def test_index_places_hidden_live_panel_immediately_before_rankings():
    source = (Path(__file__).parent.parent / "templates" / "index.html").read_text(
        encoding="utf-8"
    )
    panel = '<section id="my-players" class="my-players" aria-live="polite" hidden></section>'

    assert panel in source
    assert source.index(panel) < source.index('<div id="rankings-container">')
    assert not source[source.index(panel) + len(panel):source.index('<div id="rankings-container">')].strip()


def test_board_templates_expose_dormant_watch_buttons_beside_names():
    root = Path(__file__).parent.parent / "templates" / "partials"
    redraft = (root / "rankings_table.html").read_text(encoding="utf-8")
    dynasty = (root / "rankings_table_dynasty.html").read_text(encoding="utf-8")

    for source in (redraft, dynasty):
        assert 'class="watch-toggle"' in source
        assert 'data-watch-key="{{ watch_key }}"' in source
        assert 'aria-pressed="false"' in source
        assert "Follow" in source
        assert " hidden" in source
    assert redraft.index('class="watch-toggle"') < redraft.index("mobile-stat-strip")
    assert dynasty.index('class="watch-toggle"') < dynasty.index("mobile-stat-strip")


def test_base_loads_watchlist_controller_and_controller_contract_is_fail_soft():
    root = Path(__file__).parent.parent
    base = (root / "templates" / "base.html").read_text(encoding="utf-8")
    controller = (root / "static" / "watchlist.js").read_text(encoding="utf-8")

    assert "watchlist.js" in base
    assert "defer" in base
    for token in (
        "vc-watchlist-v1",
        "MAX_ITEMS = 50",
        "localStorage",
        "htmx:afterSwap",
        'addEventListener("storage"',
        'headers: { "HX-Request": "true" }',
        "refreshToken",
        "URLSearchParams",
    ):
        assert token in controller
    for name in ("pool", "position", "search", "callups", "display"):
        assert f'params.delete("{name}")' in controller
    assert 'params.append("watch", key)' in controller
    assert 'fetch("/metrics/event"' not in controller
    # The ranking rows themselves are clickable.  The delegated watch handler
    # must run during capture so following a player cannot also open/close the
    # row detail beneath the button.
    assert 'document.addEventListener("click", handleClick, true)' in controller
    assert 'target.innerHTML = \'<div class="my-players-card glass"><p>My Players is limited' not in controller
    assert 'className = "my-players-limit-notice"' in controller


def test_watch_metrics_observe_capture_phase_before_watch_handler_stops_rows():
    metrics = (Path(__file__).parent.parent / "static" / "metrics.js").read_text(
        encoding="utf-8"
    )

    assert 'closest("[data-metric]")' in metrics
    assert '}, true);' in metrics


def test_my_players_css_has_accessible_responsive_states():
    css = (Path(__file__).parent.parent / "static" / "style.css").read_text(
        encoding="utf-8"
    )

    for selector in (
        ".my-players",
        ".my-player-row",
        ".my-player-numbers",
        ".is-unavailable",
        ".watch-toggle",
        ".watch-toggle:focus-visible",
    ):
        assert selector in css
    assert "min-width: 44px" in css
    assert "min-height: 44px" in css
    assert "overflow-wrap: anywhere" in css
    assert "var(--border)" not in css
    assert "var(--c-green)" not in css
    assert "var(--c-border)" in css
    assert "var(--c-signal)" in css
