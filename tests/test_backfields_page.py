import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

import app as app_module
from app import app


def _html(path):
    response = app.test_client().get(path)
    return response, response.data.decode("utf-8")


def _site_nav(html):
    match = re.search(r'<nav class="site-nav"[^>]*>(.*?)</nav>', html, re.S)
    assert match
    return match.group(1)


def _prospect_url(name):
    return "/?" + urlencode({"mode": "prospects", "search": name})


def _detail_url(player_id):
    return f"/player/{player_id}?mode=prospects"


def _scouting_url(name):
    return "/scouting?" + urlencode({"q": name})


def _team_board_org_from_backfields():
    response, html = _html("/backfields")
    assert response.status_code == 200
    marker = 'href="/backfields/team/'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def _row(name, team, prospect_rank=None, dynasty_rank=None, value=0):
    return SimpleNamespace(
        id=name.lower().replace(" ", "-"),
        mlbam_id=None,
        name=name,
        team=team,
        positions=("SS",),
        position="SS",
        level="AA",
        prospect_rank=prospect_rank,
        dynasty_rank=dynasty_rank,
        dynasty_value=value,
        value=value,
        age=20,
        eta=2027,
        context={},
        metadata={},
        source_ranks={},
    )


def test_backfields_route_returns_200():
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert "Backfields" in html
    assert "Prospects, call-ups, risers, and minor-league signal in one place." in html


def test_backfields_nav_link_and_active_state():
    response, html = _html("/")
    assert response.status_code == 200
    nav = _site_nav(html)
    assert 'href="/backfields">Backfields' in nav
    assert 'href="/buys">Buys' not in nav

    response, html = _html("/backfields")
    assert response.status_code == 200
    assert re.search(r'<a href="/backfields"\s+aria-current="page">Backfields</a>', html)


def test_prospect_neighbor_navigation_points_to_backfields():
    for path in ("/buys", "/map"):
        response, html = _html(path)
        assert response.status_code in {200, 503}
        if response.status_code == 503:
            continue
        assert 'href="/backfields" class="htab htab-prospects">Backfields</a>' in html
        assert 'href="/?mode=prospects" class="htab htab-prospects">Prospects</a>' not in html


def test_primary_nav_uses_backfields_as_prospect_hub():
    response, html = _html("/")
    assert response.status_code == 200
    nav_start = html.index('<nav class="site-nav"')
    nav_end = html.index("</nav>", nav_start)
    nav_html = html[nav_start:nav_end]

    assert 'href="/backfields"' in nav_html
    assert 'href="/buys"' not in nav_html
    assert 'href="/scouting"' not in nav_html


def test_backfields_hides_held_buys_but_keeps_scouting_deep_link():
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert 'href="/buys"' not in html
    assert 'href="/scouting' in html


def test_backfields_section_anchors_present():
    response, html = _html("/backfields")

    assert response.status_code == 200
    for anchor in ("rankings", "call-up-desk", "stats", "team-boards"):
        assert f'id="{anchor}"' in html
    assert 'id="ahead-of-the-curve"' not in html


def test_backfields_warm_css_is_scoped():
    css = Path("static/style.css").read_text(encoding="utf-8")

    assert ".backfields-page" in css
    assert "--bf-amber: #C8923F" in css

    for line in css.splitlines():
        if "#C8923F" in line:
            assert ".backfields-page" in line


def test_backfields_visual_contract_uses_semantic_signals():
    css = Path("static/style.css").read_text(encoding="utf-8")

    assert ".backfields-page .bf-value { color: var(--bf-signal)" in css
    assert ".backfields-page .bf-move-up { color: var(--bf-signal)" in css
    assert ".backfields-page .bf-move-down { color: var(--bf-clay)" in css
    assert ".backfields-page .bf-level" in css
    assert "color: var(--bf-amber)" in css


def test_backfields_degrades_when_artifacts_are_missing(monkeypatch):
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: None)

    response, html = _html("/backfields")

    assert response.status_code == 200
    assert "No reports yet - first looks land here." in html


def test_backfields_ahead_of_curve_uses_live_buys_graphic_source(monkeypatch):
    graphic_rows = [
        {
            "id": "buy-1",
            "name": "Buy Signal One",
            "team": "SEA",
            "pos": "SS",
            "level": "AA",
            "score": 57.2,
            "spark": {"points": "0,10 40,5 80,0"},
            "spark_label": "up +1.2 in 7d",
        },
        {
            "id": "buy-2",
            "name": "Buy Signal Two",
            "team": "BOS",
            "pos": "OF",
            "level": "A+",
            "score": 55.8,
            "spark": {"points": "0,10 40,7 80,2"},
            "spark_label": "up +0.5 in 7d",
        },
    ]
    monkeypatch.setattr(
        app_module,
        "_build_buys_page_context",
        lambda *_args, **_kwargs: {
            "graphic_rows": graphic_rows,
            "buy_data_source": "valucast_buys",
        },
    )

    ctx = app_module._build_backfields_page_context()

    expected = [row["name"] for row in graphic_rows]
    actual = [row["name"] for row in ctx["risers"][:5]]

    assert actual == expected
    assert all(row["source"] == "valucast_buys" for row in ctx["risers"])


def test_backfields_ahead_of_curve_is_the_buy_signal_entry_point():
    original = app_module.AHEAD_OF_THE_CURVE_HOLD
    app_module.AHEAD_OF_THE_CURVE_HOLD = False
    try:
        response, html = _html("/backfields")
    finally:
        app_module.AHEAD_OF_THE_CURVE_HOLD = original

    assert response.status_code == 200
    assert "Top buy signals from the current board" in html
    assert "Biggest risers this week" not in html
    assert 'href="/buys"' in html
    assert "Full Ahead of the Curve board" in html


def test_backfields_context_links_visible_names_to_inline_player_detail():
    ctx = app_module._build_backfields_page_context()

    samples = []
    samples.extend(ctx["risers"][:2])
    samples.extend(ctx["rankings"][:2])
    samples.extend(ctx["callups"][:2])
    for leaders in ctx["stats"].values():
        samples.extend(leaders[:1])
    samples.extend(ctx["scouting_reports"][:2])

    assert samples
    for item in samples:
        assert item["url"] == _detail_url(item["id"])
        assert item["detail_url"] == _detail_url(item["id"])

    report_rows = [row for row in ctx["rankings"] if row.get("has_report")]
    assert report_rows
    for row in report_rows[:3]:
        assert row["report_url"] == _scouting_url(row["name"])


def test_backfields_player_links_and_report_links_are_distinct():
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert 'class="bf-player-link"' in html
    assert 'data-bf-detail-url="/player/' in html
    assert 'data-bf-detail-panel' in html
    assert "Showing top 100" in html
    assert 'href="/?mode=prospects">View full top 100</a>' not in html
    assert "/rankings?mode=prospects" not in html
    assert 'class="bf-report-badge" href="/scouting?' in html


def test_backfields_rankings_are_client_sortable():
    response, html = _html("/backfields")
    source = Path("templates/backfields.html").read_text(encoding="utf-8")

    assert response.status_code == 200
    for sort_key in ("rank", "player", "level", "move", "value"):
        assert f'data-bf-sort="{sort_key}"' in html
    assert "function sortRows(btn, sortKey)" in source
    assert "sortRows(btn, btn.getAttribute('data-bf-sort'))" in source
    assert (
        "var defaultDir = sortKey === 'value' || sortKey === 'move' || sortKey === 'level'"
        in html
    )
    assert source.count('data-bf-sort="level"') >= 2
    assert 'data-bf-sort-level="{{ row.level_sort }}"' in source
    assert "data-bf-sort-value" in html


def test_backfields_rankings_expose_numeric_level_sort_weight(monkeypatch):
    rows = []
    for index, level in enumerate(("MLB", "AAA", "AA", "A+", "A", "CPX", None), 1):
        row = _row(f"{level or 'Unknown'} Prospect", "BOS", prospect_rank=index)
        row.level = level
        rows.append(row)
    fake_store = SimpleNamespace(
        generated_at="2026-06-25",
        is_available=True,
        get_all=lambda: rows,
        get_by_id=lambda _player_id: None,
    )
    monkeypatch.setattr(app_module, "dd_store", fake_store)
    monkeypatch.setattr(app_module, "_prospect_rows", lambda *args, **kwargs: rows)
    monkeypatch.setattr(app_module, "_prospect_tiers", lambda: {})
    monkeypatch.setattr(app_module, "_build_buys_page_context", lambda _size: {"graphic_rows": []})
    monkeypatch.setattr(app_module, "_build_team_board_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: {})

    ctx = app_module._build_backfields_page_context()

    assert {
        row["level"]: row["level_sort"] for row in ctx["rankings"]
    } == {
        "MLB": 7,
        "AAA": 6,
        "AA": 5,
        "A+": 4,
        "A": 3,
        "CPX": 2,
        "-": 0,
    }


def test_backfields_callup_desk_and_stats_are_deeper_than_reference_stub():
    ctx = app_module._build_backfields_page_context()

    assert len(ctx["callups"]) >= 12
    assert len(ctx["stats"]["hitting"]) >= 12
    assert len(ctx["stats"]["pitching"]) >= 12


def test_team_board_org_normalization():
    assert app_module._canonical_team_board_org("KC") == "KC"
    assert app_module._canonical_team_board_org("KCR") == "KC"
    assert app_module._canonical_team_board_org("kcr") == "KC"
    assert app_module._canonical_team_board_org("ATH") == "ATH"
    assert app_module._canonical_team_board_org("FA") is None
    assert app_module._canonical_team_board_org("") is None
    assert app_module._canonical_team_board_org(None) is None


def test_team_board_pool_uses_full_prospect_pool_not_top_200_slice():
    rows = [
        _row("Top Public", "BOS", prospect_rank=1, dynasty_rank=1, value=60),
        _row("Deep Prospect", "BOS", prospect_rank=650, dynasty_rank=650, value=12),
    ]

    ordered = app_module._team_board_prospect_rows(rows)

    assert [row.name for row in ordered] == ["Top Public", "Deep Prospect"]
    assert len(ordered) == 2


def test_team_board_sort_places_ranked_rows_before_fallback_rows():
    rows = [
        _row("Dynasty Only", "BOS", prospect_rank=None, dynasty_rank=20, value=20),
        _row("Ranked Prospect", "BOS", prospect_rank=5, dynasty_rank=50, value=50),
    ]

    ordered = app_module._team_board_prospect_rows(rows)

    assert [row.name for row in ordered] == ["Ranked Prospect", "Dynasty Only"]


def test_team_board_context_groups_by_mlb_org_not_affiliate(monkeypatch):
    rows = [
        _row("Portland Guy", "BOS", prospect_rank=1, dynasty_rank=1, value=60),
        _row("Worcester Guy", "BOS", prospect_rank=2, dynasty_rank=2, value=55),
        _row("Kansas City Guy", "KCR", prospect_rank=3, dynasty_rank=3, value=50),
        _row("Free Agent Guy", "FA", prospect_rank=4, dynasty_rank=4, value=45),
    ]
    rows[0].context = {"stat_line_team": "Portland Sea Dogs"}
    rows[1].context = {"stat_line_team": "Worcester Red Sox"}
    rows[2].context = {"stat_line_team": "Omaha Storm Chasers"}

    monkeypatch.setattr(app_module, "_team_board_prospect_rows", lambda rows_arg=None: rows)
    monkeypatch.setattr(app_module, "_team_board_movements", lambda: {})

    board = app_module._build_team_board_context("BOS", limit=20)
    assert board["selected"]["org"] == "BOS"
    assert [row["name"] for row in board["rows"]] == ["Portland Guy", "Worcester Guy"]
    assert board["rows"][0]["affiliate"] == "Portland Sea Dogs"
    assert board["rows"][0]["team"] == "BOS"
    assert board["rows"][0]["org_rank"] == 1
    assert board["rows"][1]["org_rank"] == 2

    kc_board = app_module._build_team_board_context("KCR", limit=20)
    assert kc_board["selected"]["org"] == "KC"
    assert [row["name"] for row in kc_board["rows"]] == ["Kansas City Guy"]

    all_teams = {team["org"] for team in board["teams"]}
    assert "FA" not in all_teams


def test_team_board_prefers_current_affiliate_org_over_stale_snapshot_team(monkeypatch):
    rows = [
        _row("David Sandlin", "BOS", prospect_rank=1, dynasty_rank=1, value=40),
    ]
    rows[0].context = {"stat_line_team": "Charlotte Knights"}

    monkeypatch.setattr(app_module, "_team_board_prospect_rows", lambda rows_arg=None: rows)
    monkeypatch.setattr(app_module, "_team_board_movements", lambda: {})

    white_sox = app_module._build_team_board_context("CHW", limit=20)
    assert white_sox["selected"]["org"] == "CHW"
    assert [row["name"] for row in white_sox["rows"]] == ["David Sandlin"]
    assert white_sox["rows"][0]["team"] == "CHW"
    assert white_sox["rows"][0]["affiliate"] == "Charlotte Knights"

    with pytest.raises(KeyError):
        app_module._build_team_board_context("BOS", limit=20)


def test_team_board_prefers_current_roster_org_over_historical_affiliate(monkeypatch):
    rows = [
        _row("Brandon Clarke", "BOS", prospect_rank=1, dynasty_rank=1, value=40),
    ]
    rows[0].context = {
        "stat_line_team": "Greenville Drive",
        "stat_line_sample_season": 2025,
        "stat_line_source_kind": "latest_milb_history",
    }

    monkeypatch.setattr(app_module, "_team_board_prospect_rows", lambda rows_arg=None: rows)
    monkeypatch.setattr(app_module, "_team_board_movements", lambda: {})
    monkeypatch.setattr(app_module, "_team_board_current_roster_org", lambda row: "STL", raising=False)

    cardinals = app_module._build_team_board_context("STL", limit=20)
    assert cardinals["selected"]["org"] == "STL"
    assert [row["name"] for row in cardinals["rows"]] == ["Brandon Clarke"]
    assert cardinals["rows"][0]["team"] == "STL"
    assert cardinals["rows"][0]["affiliate"] == "Greenville Drive"

    with pytest.raises(KeyError):
        app_module._build_team_board_context("BOS", limit=20)


def test_team_board_does_not_assign_org_from_historical_affiliate(monkeypatch):
    rows = [
        _row("Orelvis Martinez", "FA", prospect_rank=1, dynasty_rank=1, value=40),
    ]
    rows[0].context = {
        "stat_line_team": "Buffalo Bisons",
        "stat_line_sample_season": 2025,
        "stat_line_source_kind": "latest_milb_history",
    }

    monkeypatch.setattr(app_module, "_team_board_prospect_rows", lambda rows_arg=None: rows)
    monkeypatch.setattr(app_module, "_team_board_movements", lambda: {})
    monkeypatch.setattr(app_module, "_team_board_current_roster_org", lambda row: None)

    assert app_module._team_board_org_for(rows[0]) is None
    with pytest.raises(KeyError):
        app_module._build_team_board_context("TOR", limit=20)


def test_team_board_includes_org_callups_and_reports(monkeypatch):
    rows = [
        _row("Portland Guy", "BOS", prospect_rank=1, dynasty_rank=1, value=60),
        _row("Worcester Guy", "BOS", prospect_rank=2, dynasty_rank=2, value=55),
        _row("Kansas City Guy", "KCR", prospect_rank=3, dynasty_rank=3, value=50),
    ]
    rows[0].level = "AAA"
    rows[0].eta = date.today().year  # This year -> On the doorstep
    repository = {
        "generated_at": "2026-06-22",
        "reports": [
            {
                "identity_key": "name:portland guy|team:BOS",
                "name": "Portland Guy",
                "positions": ["SS"],
                "level": "AAA",
                "team": "BOS",
                "report_status": "fresh_look",
                "report": "Smooth actions, advanced bat.",
            }
        ],
    }
    monkeypatch.setattr(app_module, "_team_board_prospect_rows", lambda rows_arg=None: rows)
    monkeypatch.setattr(app_module, "_team_board_movements", lambda: {})
    monkeypatch.setattr(app_module, "_load_artifact", lambda _path: repository)

    board = app_module._build_team_board_context("BOS", limit=20)

    callup_names = [c["name"] for c in board["callups"]]
    assert "Portland Guy" in callup_names
    assert "Kansas City Guy" not in callup_names  # org-filtered
    doorstep = next(c for c in board["callups"] if c["name"] == "Portland Guy")
    assert doorstep["status"] == "On the doorstep"

    assert [r["name"] for r in board["reports"]] == ["Portland Guy"]
    assert board["reports"][0]["line"] == "Smooth actions, advanced bat."
    assert board["reports"][0]["report_url"] == _scouting_url("Portland Guy")

    empty = app_module._build_team_board_context()
    assert empty["callups"] == []
    assert empty["reports"] == []


def test_team_board_rows_expose_numeric_level_sort_weight():
    rows = []
    for index, level in enumerate(("MLB", "AAA", "AA", "A+", "A", "CPX", None), 1):
        row = _row(f"{level or 'Unknown'} Prospect", "BOS", prospect_rank=index)
        row.level = level
        rows.append(row)

    rendered = [
        app_module._team_board_row(row, index, {}, {})
        for index, row in enumerate(rows, 1)
    ]

    assert {
        row["level"]: row["level_sort"] for row in rendered
    } == {
        "MLB": 7,
        "AAA": 6,
        "AA": 5,
        "A+": 4,
        "A": 3,
        "CPX": 2,
        "-": 0,
    }


def test_team_board_current_roster_org_reads_unique_fantrax_team(tmp_path, monkeypatch):
    path = tmp_path / "fantrax.csv"
    path.write_text(
        '"ID","Player","Team","Position","Roster Status"\n'
        '"*1*","Brandon Clarke","STL","SP","Minors"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(app_module, "_TEAM_BOARD_FANTRAX_FILES", (path,))
    app_module._team_board_current_roster_org_lookup.cache_clear()
    try:
        assert app_module._team_board_current_roster_org(_row("Brandon Clarke", "BOS")) == "STL"
    finally:
        app_module._team_board_current_roster_org_lookup.cache_clear()


def test_backfields_exposes_team_boards_module():
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert "Team Boards" in html
    assert "/backfields/team/" in html


def test_team_board_card_offers_top_10_and_top_20_downloads():
    org = _team_board_org_from_backfields()
    response, html = _html(f"/backfields/team/{org}")

    assert response.status_code == 200
    assert f'href="/backfields/team/{org}/share-card.png?n=10">Download Top 10 PNG' in html
    assert f'href="/backfields/team/{org}/share-card.png?n=20">Download Top 20 PNG' in html


def test_team_board_route_serves_known_org_and_alias():
    org = _team_board_org_from_backfields()

    response, html = _html(f"/backfields/team/{org}")
    assert response.status_code == 200
    assert "Team Boards" in html

    alias_response, _ = _html("/backfields/team/KCR")
    assert alias_response.status_code == 200


def test_unknown_team_board_returns_404():
    response, _ = _html("/backfields/team/NOTREAL")

    assert response.status_code == 404


def test_team_board_share_preview_and_png():
    org = _team_board_org_from_backfields()

    preview, preview_html = _html(f"/backfields/team/{org}/share-card")
    assert preview.status_code == 200
    assert "Download Top 10 PNG" in preview_html
    assert "Download Top 20 PNG" in preview_html
    assert "ValuCast prospect order" in preview_html
    assert "consensus" not in preview_html.lower()

    png = app.test_client().get(f"/backfields/team/{org}/share-card.png?n=10")
    assert png.status_code == 200
    assert png.content_type == "image/png"
    assert png.data.startswith(b"\x89PNG")

    png_20 = app.test_client().get(f"/backfields/team/{org}/share-card.png?n=20")
    assert png_20.status_code == 200
    assert png_20.data.startswith(b"\x89PNG")


def test_team_board_share_png_rejects_invalid_n():
    org = _team_board_org_from_backfields()
    response = app.test_client().get(f"/backfields/team/{org}/share-card.png?n=11")

    assert response.status_code == 400


def test_team_board_share_png_renderer_uses_compact_backfields_export_language():
    source = Path("app.py").read_text(encoding="utf-8")
    start = source.index("def _team_board_share_card_png")
    end = source.index('@app.route("/backfields/team/<org>/share-card.png")', start)
    block = source[start:end]

    assert "ValuCast team board" in block
    assert "prospects in pool" in block
    assert "BACKFIELDS TEAM BOARD" in block
    assert 'row["affiliate"]' not in block
    assert 'f"UP {move.get' not in block
    assert 'f"DOWN {move.get' not in block


def test_backfields_callup_desk_explains_why_each_player_is_listed():
    ctx = app_module._build_backfields_page_context()
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert 'class="bf-callup-why"' in html
    assert 'class="bf-callup-status"' in html
    assert ctx["callups"]
    for player in ctx["callups"][:8]:
        assert player["sort_score"] > 0
        assert player["status"] in {"On the doorstep", "Near-term watch", "Monitor"}
        assert player["why"]
        assert player["value"] in player["why"]
        assert player["why"] in html


def test_backfields_scouting_feed_has_enough_latest_looks():
    ctx = app_module._build_backfields_page_context()

    assert len(ctx["scouting_reports"]) >= 6
