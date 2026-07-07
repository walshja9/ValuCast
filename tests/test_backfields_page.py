import json
import os
import re
import time
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
        # 7/1: Backfields stays the minors hub; the prospect value board now ALSO has
        # its own (plain-htab) tab because deep links land there constantly.
        assert 'href="/?mode=prospects" class="htab' in html


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
    # Held-path coverage: with the AOTC hold ON, /buys is suppressed on backfields.
    original = app_module.AHEAD_OF_THE_CURVE_HOLD
    app_module.AHEAD_OF_THE_CURVE_HOLD = True
    try:
        response, html = _html("/backfields")
    finally:
        app_module.AHEAD_OF_THE_CURVE_HOLD = original

    assert response.status_code == 200
    assert 'href="/buys"' not in html
    assert 'href="/scouting' in html


def test_backfields_section_anchors_present():
    response, html = _html("/backfields")

    assert response.status_code == 200
    for anchor in ("rankings", "call-up-desk", "stats", "team-boards"):
        assert f'id="{anchor}"' in html
    # Buys are live (hold off), so the Ahead-of-the-Curve section is present.
    assert 'id="ahead-of-the-curve"' in html


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


def test_backfields_sort_controls_use_columnheader_aria_sort():
    response, html = _html("/backfields")
    source = Path("templates/backfields.html").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert 'data-bf-table role="table"' in html
    assert 'class="bf-sort-cell" role="columnheader" aria-sort="ascending"' in html
    assert re.search(
        r'<span class="bf-sort-cell" role="columnheader" aria-sort="none">\s*'
        r'<button type="button" data-bf-sort="player">',
        html,
    )
    assert 'data-bf-sort="rank" aria-sort' not in html
    assert "closest('[role=\"columnheader\"]')" in source


def test_backfields_detail_drawer_updates_expanded_state_and_focus():
    response, html = _html("/backfields")
    source = Path("templates/backfields.html").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert 'data-bf-detail-panel hidden aria-live="polite" role="region"' in html
    assert 'aria-labelledby="bf-detail-title" tabindex="-1"' in html
    assert 'id="bf-detail-title" data-bf-detail-title' in html
    assert re.search(
        r'<a class="bf-player-link" href="/player/[^"]+" '
        r'data-bf-detail-url="/player/[^"]+" data-bf-player-name="[^"]+" '
        r'aria-expanded="false">',
        html,
    )
    assert "setExpandedLink(link)" in source
    assert "detailPanel.focus({ preventScroll: true })" in source
    assert "lastDetailTrigger.focus({ preventScroll: true })" in source
    # role="region" (non-modal) was chosen over role="dialog" -- that choice only
    # holds up paired with an Escape-to-close handler; a plain Close button click
    # alone isn't enough for a keyboard user who never tabs to it.
    assert "event.key === 'Escape'" in source
    assert re.search(r"function closeDetailPanel\(\)[\s\S]*?detailPanel\.hidden = true", source)


def test_backfields_tier_and_report_badges_are_accessible_tap_targets():
    response, html = _html("/backfields")
    css = Path("static/style.css").read_text(encoding="utf-8")

    assert response.status_code == 200
    assert 'class="bf-tier-badge" aria-label="Prospect tier ' in html
    assert ".backfields-page .bf-tier-badge" in css
    assert ".backfields-page .bf-report-badge" in css
    assert "min-height: 32px" in css
    assert "min-width: 44px" in css


def test_backfields_stat_toggle_does_not_misdeclare_tabs():
    response, html = _html("/backfields")

    assert response.status_code == 200
    assert 'class="bf-stat-tabs" role="tablist"' not in html
    assert 'class="bf-stat-tabs" aria-label="Stat leader type"' in html
    assert 'data-bf-stat-tab="hitting" aria-pressed="true"' in html


def test_backfields_mobile_keeps_sort_controls_available():
    css = Path("static/style.css").read_text(encoding="utf-8")

    mobile_idx = css.index("@media (max-width: 640px)")
    backfields_mobile_idx = css.index(".backfields-page", mobile_idx)
    backfields_mobile_end = css.index("/* Mobile board tab-bar", backfields_mobile_idx)
    backfields_mobile_css = css[backfields_mobile_idx:backfields_mobile_end]

    assert ".backfields-page .bf-table-head" in backfields_mobile_css
    assert ".backfields-page .bf-table-head {\n        display: none;" not in backfields_mobile_css
    assert "overflow-x: auto" in backfields_mobile_css


def test_backfields_debut_filter_renumbers_instead_of_leaving_rank_gaps():
    # 7/5: the debut/level pill filters only ever set row.hidden client-side, so the
    # rendered rank badges kept their true board position (row.rank) and a filtered
    # view read "1, 2 ... 8, 11, 13" wherever a hidden row's number used to sit. The
    # main rankings board fixed this exact bug for its own filter in 70ee73d
    # (sequential 1..N while filtered, true rank when unfiltered) -- Backfields has an
    # entirely separate client-side filter and never got the same treatment.
    source = Path("templates/backfields.html").read_text(encoding="utf-8")
    assert "function bfRenumberRankColumn()" in source
    assert "bfApplyRowFilters();" in source
    # Must run after every visibility change (filter click) ...
    filters_idx = source.index("function bfApplyRowFilters()")
    filters_end = source.index("page.querySelectorAll('[data-bf-level]')", filters_idx)
    assert "bfRenumberRankColumn();" in source[filters_idx:filters_end]
    # ... and after every DOM reorder (column sort), or a filtered numbering goes
    # stale in the new row order.
    sort_idx = source.index("function sortRows(")
    sort_end = source.index("page.querySelectorAll('[data-bf-sort]')", sort_idx)
    assert "bfRenumberRankColumn();" in source[sort_idx:sort_end]
    # Scoped to the rankings rows specifically -- must never touch the team board,
    # which reuses data-bf-row-level with an unrelated org_rank.
    assert "querySelectorAll('[data-bf-row-debut]')" in source
    # Restores the true rank when both filters are back to "All".
    assert "row.getAttribute('data-bf-sort-rank')" in source


def test_backfields_detail_fetch_guards_stale_responses():
    # 7/6: the fetch had no generation token, so clicking player B before player A's
    # request resolved could show A's card rendered under B's title if A resolved
    # after B (or repopulate a since-closed panel). A per-panel request counter,
    # checked in both the success and error paths, prevents a stale response from
    # ever being written into the DOM.
    source = Path("templates/backfields.html").read_text(encoding="utf-8")
    open_idx = source.index("page.querySelectorAll('[data-bf-detail-url]')")
    close_idx = source.index("page.querySelectorAll('[data-bf-detail-close]')")
    open_body = source[open_idx:close_idx]
    assert "detailPanel._bfReq" in open_body
    # Guarded in the success path ...
    assert open_body.count("detailPanel._bfReq !== reqId") == 2
    # ... and closing must also invalidate any fetch still in flight. The bump now
    # lives in a shared closeDetailPanel() (reused by the Escape handler), not
    # inline in the close-button listener, so search the whole close-side region
    # rather than a fixed window after the button-registration marker.
    close_region = source[open_idx:close_idx + 400]
    assert "_bfReq = (detailPanel._bfReq || 0) + 1" in close_region


def test_backfields_zero_matches_shows_no_results_message():
    # 7/6: a filter combo matching nothing left the Rankings card silently empty
    # (just header + footer, no explanation) -- the dynasty board has a "no results"
    # affordance for the same case, Backfields' parallel filter never got one.
    response, html = _html("/backfields")
    assert response.status_code == 200
    assert 'data-bf-no-results hidden' in html
    assert "No prospects match these filters." in html
    source = Path("templates/backfields.html").read_text(encoding="utf-8")
    filters_idx = source.index("function bfApplyRowFilters()")
    filters_end = source.index("page.querySelectorAll('[data-bf-level]')", filters_idx)
    body = source[filters_idx:filters_end]
    assert "querySelector('[data-bf-no-results]')" in body
    assert "noResultsEl.hidden = visibleRankingsCount !== 0" in body


def test_backfields_footer_reflects_visible_count_under_a_filter():
    # 7/6: the "Showing top 100" footer was a static string, never updated by the
    # client filter -- misleading once a filter hides most rows (e.g. reading "top
    # 100" while only 12 rows are visible).
    source = Path("templates/backfields.html").read_text(encoding="utf-8")
    filters_idx = source.index("function bfApplyRowFilters()")
    filters_end = source.index("page.querySelectorAll('[data-bf-level]')", filters_idx)
    body = source[filters_idx:filters_end]
    assert "querySelector('.bf-table-footer')" in body
    assert "'Showing ' + visibleRankingsCount + ' of top 100'" in body
    assert "'Showing top 100'" in body


def test_backfields_filter_pills_scoped_to_rankings_not_team_board():
    # 7/6: bfApplyRowFilters queried [data-bf-row-level] page-wide, which also matched
    # team-board rows (they carry data-bf-row-level for sort but never
    # data-bf-row-debut). Any non-"All" debut pill made `debut === null` fail both
    # '1' and '0' checks, so debutOk was always false and row.hidden = true for the
    # ENTIRE team board -- clicking "Not debuted" on a team page (which renders both
    # sections) silently wiped the team board below it.
    source = Path("templates/backfields.html").read_text(encoding="utf-8")
    filters_idx = source.index("function bfApplyRowFilters()")
    filters_end = source.index("page.querySelectorAll('[data-bf-level]')", filters_idx)
    body = source[filters_idx:filters_end]
    assert "querySelectorAll('[data-bf-row-debut]')" in body
    assert "querySelectorAll('[data-bf-row-level]')" not in body
    # The dead null-check branch (a stand-in for real scoping) must be gone.
    assert "debut === null" not in body


def test_backfields_rankings_repopulate_undebuted_beyond_the_top_100_slice(monkeypatch):
    # 7/6: prospect_rows was a naive _prospect_rows()[:100] slice computed BEFORE any
    # debut filtering, so a "Not debuted" view could only ever show whatever survived
    # after hiding debuted rows out of that fixed top-100 window -- if the top 100
    # happened to be all-debuted, the filtered view showed ZERO rows even though
    # plenty of genuinely top-100-worthy undebuted prospects existed just past rank
    # 100. The main board already solved this for its own filter (row_filter applied
    # BEFORE the slice, in _apply_prospect_board_context) -- Backfields never got it.
    rows = []
    for rank in range(1, 101):
        row = _row(f"Debuted {rank}", "BOS", prospect_rank=rank)
        row.active_mlb_callup = True
        rows.append(row)
    for rank in range(101, 161):
        row = _row(f"Prospect {rank}", "BOS", prospect_rank=rank)
        row.active_mlb_callup = False
        rows.append(row)
    fake_store = SimpleNamespace(
        generated_at="2026-07-06",
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
    monkeypatch.setattr(app_module, "_debuted_prospect_ids", lambda: {})
    monkeypatch.setattr(app_module, "_call_up_pulse_keys", lambda: frozenset())

    ctx = app_module._build_backfields_page_context()
    rankings = ctx["rankings"]
    undebuted = [row for row in rankings if not row["debuted"]]
    debuted = [row for row in rankings if row["debuted"]]

    # All 60 undebuted prospects must be present -- the old top-100-first slice would
    # have shown 0, since ranks 1-100 are entirely debuted in this fixture.
    assert len(undebuted) == 60
    assert {row["name"] for row in undebuted} == {f"Prospect {r}" for r in range(101, 161)}
    # The debuted subset is still capped at 100 (matches the pre-existing "top 100"
    # contract for that filter state) and true rank is preserved, not re-enumerated.
    assert len(debuted) == 100
    assert sorted(row["rank"] for row in rankings) == list(range(1, 161))


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


def test_backfields_callup_desk_excludes_already_debuted_prospects(monkeypatch):
    # 7/6: callup_rows never applied _prospect_has_debuted, so a rookie-eligible
    # player already on an MLB roster (or in the same-day call-up pulse) still showed
    # up "On the doorstep" -- a live self-contradiction with the same player being
    # flagged debuted=True in the rankings a few sections up on the same page.
    rows = []
    for rank, (name, debuted) in enumerate(
        [("On Deck", False), ("Already Debuted", True), ("Also Waiting", False)], 1
    ):
        row = _row(name, "BOS", prospect_rank=rank)
        row.level = "AAA"
        row.active_mlb_callup = debuted
        rows.append(row)
    fake_store = SimpleNamespace(
        generated_at="2026-07-06",
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
    monkeypatch.setattr(app_module, "_debuted_prospect_ids", lambda: {})
    monkeypatch.setattr(app_module, "_call_up_pulse_keys", lambda: frozenset())

    ctx = app_module._build_backfields_page_context()

    desk_names = {c["name"] for c in ctx["callups"]}
    assert "Already Debuted" not in desk_names
    assert {"On Deck", "Also Waiting"} <= desk_names


def test_backfields_early_calls_preserve_archive_start_hedge_flag(monkeypatch):
    # 7/6: _shape_aotc dropped ahead_since_is_archive_start, so
    # templates/backfields.html's honest "tracked since ... may predate our records"
    # branch (for a streak that reaches back to day one of the tracking archive, whose
    # true length is unknown) was permanently dead -- every row rendered the stronger
    # "since ... unbroken streak, verifiable in the dated archive" claim instead.
    rows = [_row("Rank One", "BOS", prospect_rank=1)]
    fake_store = SimpleNamespace(
        generated_at="2026-07-06",
        is_available=True,
        get_all=lambda: rows,
        get_by_id=lambda _player_id: None,
    )
    aotc_payload = {
        "ahead_of_consensus": [
            {
                "name": "Rank One",
                "mlbam_id": None,
                "role": "hitter",
                "valucast_rank": 1,
                "consensus_rank": 50,
                "divergence": 49,
                "board_count": 3,
                "ahead_since": "2026-06-13",
                "ahead_since_is_archive_start": True,
                "days_ahead": 22,
            }
        ],
        "ahead_of_consensus_thin": [],
    }

    def fake_load_artifact(path):
        if str(path).endswith("valucast_ahead_of_consensus.json"):
            return aotc_payload
        return {}

    monkeypatch.setattr(app_module, "dd_store", fake_store)
    monkeypatch.setattr(app_module, "_prospect_rows", lambda *args, **kwargs: rows)
    monkeypatch.setattr(app_module, "_prospect_tiers", lambda: {})
    monkeypatch.setattr(app_module, "_build_buys_page_context", lambda _size: {"graphic_rows": []})
    monkeypatch.setattr(app_module, "_build_team_board_context", lambda *args, **kwargs: {})
    monkeypatch.setattr(app_module, "_load_artifact", fake_load_artifact)
    monkeypatch.setattr(app_module, "_debuted_prospect_ids", lambda: {})
    monkeypatch.setattr(app_module, "_call_up_pulse_keys", lambda: frozenset())

    ctx = app_module._build_backfields_page_context()

    calls = ctx.get("ahead_of_consensus") or []
    assert calls, "expected at least one shaped ahead_of_consensus row"
    assert calls[0]["ahead_since_is_archive_start"] is True


def test_active_mlb_roster_rows_invalidates_on_pulse_mtime_change(monkeypatch, tmp_path):
    # 7/6: _ACTIVE_ROSTER_ROWS cached its entire result forever (compute-once
    # global), while the call-up pulse file it reads refreshes intraday independent
    # of the morning build (confirmed live mtime skew between the pulse and the rest
    # of the daily build). A long-lived worker's first request would freeze "Got the
    # Call" from before a same-day promotion, even though the rankings' debuted flag
    # (which reads the pulse through the already-mtime-aware _load_artifact) would
    # correctly start flagging the newly-pulsed player -- two facts about the same
    # player disagreeing purely from cache-freshness skew, not real data.
    pulse_path = tmp_path / "valucast_call_up_pulse.json"
    pulse_path.write_text('{"by_identity": {}}', encoding="utf-8")
    monkeypatch.setattr(app_module, "_ACTIVE_ROSTER_PULSE_PATH", pulse_path)
    monkeypatch.setattr(app_module, "_ACTIVE_ROSTER_ROWS", None)
    monkeypatch.setattr(app_module, "dd_store", SimpleNamespace(is_available=True, get_all=lambda: []))

    assert app_module._active_mlb_roster_rows() == []

    pulse_path.write_text(
        json.dumps({"by_identity": {"1_hitter": {"name": "Fresh Callup"}}}),
        encoding="utf-8",
    )
    # Force a distinct mtime -- coarse filesystem mtime resolution could otherwise
    # make a same-tick rewrite look unchanged, which would mask the bug this test
    # exists to catch rather than exercise the real invalidation path.
    now_ns = time.time_ns()
    os.utime(pulse_path, ns=(now_ns, now_ns + 10_000_000_000))

    names = {r.get("name") for r in app_module._active_mlb_roster_rows()}
    assert names == {"Fresh Callup"}


def test_debuted_prospect_ids_invalidates_on_model_inputs_mtime_change(monkeypatch, tmp_path):
    # Same cache-freshness bug, same fix, applied to _debuted_prospect_ids: it also
    # cached forever in a bare "compute once" global.
    inputs_path = tmp_path / "prospect_model_inputs.json"
    inputs_path.write_text('{"mlb_service": []}', encoding="utf-8")
    monkeypatch.setattr(app_module, "_DEBUTED_PROSPECT_IDS_PATH", inputs_path)
    monkeypatch.setattr(app_module, "_DEBUTED_PROSPECT_IDS", None)

    assert app_module._debuted_prospect_ids() == {}

    inputs_path.write_text(
        json.dumps({"mlb_service": [{"mlbam_id": 42, "pa": 5, "graduated": False}]}),
        encoding="utf-8",
    )
    now_ns = time.time_ns()
    os.utime(inputs_path, ns=(now_ns, now_ns + 10_000_000_000))

    assert app_module._debuted_prospect_ids() == {"42": "5 PA"}


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


def test_team_board_pool_dedups_two_way_players_by_identity():
    # 7/6: a two-way player has separate hitter/pitcher store rows sharing one
    # mlbam_id (confirmed live: Sean Barnett, SDP, mlbam 826141). Undeduped, the org
    # pool count, picker pill, and top-N slice all double-counted him, and any
    # two-way player ranked inside an org's top-N would render as two identical rows.
    hitter = _row("Two Way Guy", "BOS", prospect_rank=5, dynasty_rank=5, value=40)
    hitter.mlbam_id = 999001
    pitcher = _row("Two Way Guy", "BOS", prospect_rank=2300, dynasty_rank=2300, value=5)
    pitcher.mlbam_id = 999001
    other = _row("Someone Else", "BOS", prospect_rank=10, dynasty_rank=10, value=30)
    other.mlbam_id = 999002

    ordered = app_module._team_board_prospect_rows([hitter, pitcher, other])

    assert len(ordered) == 2
    assert [row.name for row in ordered] == ["Two Way Guy", "Someone Else"]
    # The better-ranked (hitter) role is the one kept.
    assert ordered[0] is hitter


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
