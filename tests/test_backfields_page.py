import re
from pathlib import Path
from urllib.parse import urlencode

import app as app_module
from app import app


def _html(path):
    response = app.test_client().get(path)
    return response, response.data.decode("utf-8")


def _prospect_url(name):
    return "/?" + urlencode({"mode": "prospects", "search": name})


def _detail_url(player_id):
    return f"/player/{player_id}?mode=prospects"


def _scouting_url(name):
    return "/scouting?" + urlencode({"q": name})


def test_backfields_route_returns_200():
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert "Backfields" in html
    assert "Prospects, call-ups, risers, and minor-league signal in one place." in html


def test_backfields_nav_link_and_active_state():
    response, html = _html("/")
    assert response.status_code == 200
    assert 'href="/backfields">Backfields' in html

    response, html = _html("/backfields")
    assert response.status_code == 200
    assert re.search(r'<a href="/backfields"\s+aria-current="page">Backfields</a>', html)


def test_backfields_section_anchors_present():
    response, html = _html("/backfields")

    assert response.status_code == 200
    for anchor in ("rankings", "ahead-of-the-curve", "call-up-desk", "stats"):
        assert f'id="{anchor}"' in html


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


def test_backfields_ahead_of_curve_uses_live_buys_graphic_source():
    ctx = app_module._build_backfields_page_context()
    buys_ctx = app_module._build_buys_page_context()

    expected = [row["name"] for row in buys_ctx["graphic_rows"][:5]]
    actual = [row["name"] for row in ctx["risers"][:5]]

    assert expected
    assert actual == expected
    assert all(row["source"] == "valucast_buys" for row in ctx["risers"])


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
    assert 'href="/?mode=prospects">View full top 100</a>' in html
    assert "/rankings?mode=prospects" not in html
    assert 'class="bf-report-badge" href="/scouting?' in html


def test_backfields_rankings_are_client_sortable():
    response, html = _html("/backfields")

    assert response.status_code == 200
    for sort_key in ("rank", "player", "level", "move", "value"):
        assert f'data-bf-sort="{sort_key}"' in html
    assert "sortRows(sortKey)" in html
    assert "var defaultDir = sortKey === 'value' || sortKey === 'move' ? 'desc' : 'asc';" in html
    assert "data-bf-sort-value" in html


def test_backfields_callup_desk_and_stats_are_deeper_than_reference_stub():
    ctx = app_module._build_backfields_page_context()

    assert len(ctx["callups"]) >= 12
    assert len(ctx["stats"]["hitting"]) >= 12
    assert len(ctx["stats"]["pitching"]) >= 12


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
