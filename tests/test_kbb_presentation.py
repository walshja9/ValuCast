"""The app renders invented zero-walk counts without claiming a zero ratio."""
from collections import OrderedDict
import csv
from io import StringIO
from types import SimpleNamespace

import pytest
from werkzeug.datastructures import MultiDict

import app as app_module
from league_values.models import PlayerProjection


@pytest.fixture
def board(monkeypatch):
    counts = {"IP": 180, "K": 10, "BB": 0, "K_BB": 0}
    players = [PlayerProjection("a", "Invented A", "starter", counts, ("SP",),
                                {"stats_actual": dict(counts), "stats_ros": dict(counts)}),
               PlayerProjection("b", "Invented B", "starter", {**counts, "K": 30, "BB": 5}, ("SP",)),
               PlayerProjection("c", "Invented C", "reliever", {**counts, "K": 10, "BB": 5}, ("RP",)),
               PlayerProjection("bat", "Invented Bat", "hitter", {"PA": 600, "HR": 20}, ("OF",))]
    active = SimpleNamespace(source_metadata={'target_season': 2026, 'projection_phase': 'in_season_outlook', 'data_kind': 'synthetic_fixture'}, as_of='2026-11-07', get_all=lambda: players, player_count=len(players),
                             get_by_id=lambda pid: next((p for p in players if p.id == pid), None), revision="invented-kbb-v1")
    monkeypatch.setattr(app_module, "_active_store", lambda source: active)
    monkeypatch.setattr(app_module, "_ineligible_mlbam_ids", lambda: frozenset())
    monkeypatch.setattr(app_module, "_REDRAFT_BUNDLE_CACHE", OrderedDict())
    monkeypatch.setattr(app_module, "_card_extras", lambda *_: {})
    monkeypatch.setattr(app_module, "_dynasty_snapshot_row_for", lambda *_: None)
    return players


def args(**extra):
    return MultiDict({"cats": "HR", "pcats": "K_BB", **extra})


@pytest.mark.parametrize("split", [False, True])
def test_csv_projection_blank_is_distinct_from_valid_category_value(board, split):
    query = args(**({"split_rp": "on"} if split else {}))
    for display in ("projections", "values"):
        query["display"] = display
        with app_module.app.test_request_context("/export", query_string=query):
            response = app_module.export_csv()
        rows = {r["Player"]: r for r in csv.DictReader(StringIO(response.get_data(as_text=True)))}
        key = "K/BB value" if display == "values" else "K/BB"
        assert rows["Invented Bat"][key] == ""
        if display == "projections":
            assert rows["Invented A"][key] == ""
        else:
            assert float(rows["Invented A"][key]) > 0


def test_html_hx_and_card_keep_zero_walk_category_contribution(board):
    client = app_module.app.test_client()
    response = client.get("/rankings", query_string=args(display="values", search="Invented A"), headers={"HX-Request": "true"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="mobile-stat-label">K_BB</span>' in html
    assert 'col-cat val-pos' in html
    context, status = app_module._build_redraft_player_card_context("a", args())
    assert status == 200
    items = app_module._dynasty_category_card_items(context)
    item = next(item for item in items if item["label"] == "K/BB")
    assert item["raw"] is None and item["value"] > 0
    png = client.get("/redraft/player-card/a.png", query_string=args())
    assert png.status_code == 200 and png.data.startswith(b"\x89PNG\r\n\x1a\n")


def test_detail_projection_actual_ros_never_display_zero_for_undefined_ratio(board):
    response = app_module.app.test_client().get("/player/a", query_string=args(), headers={"HX-Request": "true"})
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    from re import findall
    from html import unescape
    values = findall(r'<span class="stat-label">K_BB</span>\s*<span class="stat-value">\s*([^<]+)', html)
    assert [unescape(v.strip()) for v in values] == ["—", "—", "—"]
    assert '<td>K/BB</td>' in html


def test_two_way_pool_applicability_survives_none_and_genuine_zero(board):
    from dataclasses import replace
    hitter = replace(board[-1], id="two-bat", metadata={"base_id": "two"})
    pitcher = replace(board[0], id="two-arm", metadata={"base_id": "two"})
    config = app_module.build_config(cats=["HR"], pcats=["K_BB"])
    rows = app_module.engine.value_players([hitter, pitcher, *board[1:3]], config)
    merged = next(r for r in app_module._merge_two_way_players(rows) if r.player.id == hitter.id)
    assert merged.raw_values["K_BB"] is None
    items = app_module._dynasty_category_card_items({"dyn_result": merged, "dyn_categories": config.categories})
    assert {item["label"] for item in items} == {"Home Runs", "K/BB"}
    zero_rows = app_module.engine.value_players([hitter, pitcher], config)
    merged = app_module._merge_two_way_players(zero_rows)[0]
    items = app_module._dynasty_category_card_items({"dyn_result": merged, "dyn_categories": config.categories})
    assert next(i for i in items if i["label"] == "K/BB")["value"] == 0


def test_two_way_csv_keeps_an_applicable_neutral_pitching_value(board):
    from dataclasses import replace
    hitter = replace(board[-1], id="two-bat", metadata={"base_id": "two"})
    pitcher = replace(board[0], id="two-arm", metadata={"base_id": "two"})
    board[:] = [hitter, pitcher]
    with app_module.app.test_request_context("/export", query_string=args(display="values")):
        response = app_module.export_csv()
    rows = list(csv.DictReader(StringIO(response.get_data(as_text=True))))
    assert len(rows) == 1
    assert float(rows[0]["K/BB value"]) == 0


def test_compare_shows_valid_value_even_when_raw_ratio_is_undefined(board):
    from re import search
    response = app_module.app.test_client().get("/compare", query_string=args(p1="a", p2="b"))
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    cells = search(r'<td>K/BB</td>\s*<td[^>]*>\s*([^<]+)', html)
    assert cells and float(cells.group(1)) > 0


def test_dynasty_detail_category_and_all_stat_grids_use_count_ratio(board):
    from html import unescape
    from re import findall
    from web.dynasty_models import DynastyRankingRow
    context = app_module._build_context(args())
    result = next(r for r in context["canonical_results"] if r.player.id == "a")
    row = DynastyRankingRow(id="invented-dyn", name="Invented A", player_type="mlb", positions=("SP",),
                           team="TST", age=27, dynasty_rank=1, dynasty_value=50, mlbam_id="1", status="active")
    stats = dict(board[0].stats)
    with app_module.app.test_request_context("/player/invented-dyn?mode=dd_dynasty"):
        html = app_module.render_template("partials/player_detail_dynasty.html", row=row, dyn_result=result,
                dyn_categories=context["active_categories"], mlb_stats=stats, mlb_stats_actual=stats,
                mlb_stats_ros=stats, spark=None)
    assert '<td>K/BB</td>' in html
    values = findall(r'<span class="stat-label">K_BB</span>\s*<span class="stat-value">\s*([^<]+)', html)
    assert [unescape(v.strip()) for v in values] == ["—", "—", "—"]


def test_sample_floor_categories_stay_hidden_while_zero_walk_impact_is_visible(board):
    from dataclasses import replace
    from re import search
    player = replace(board[0], stats={**board[0].stats, "IP": 5, "ER": 2, "H_ALLOWED": 4})
    config = app_module.build_config(cats=["HR"], pcats=["ERA", "WHIP", "K_BB"])
    rows = app_module.engine.value_players([player, *board[1:]], config)
    first = next(r for r in rows if r.player.id == "a")
    second = next(r for r in rows if r.player.id == "b")
    assert first.raw_values["ERA"] is first.raw_values["WHIP"] is first.raw_values["K_BB"] is None
    items = app_module._dynasty_category_card_items({"dyn_result": first, "dyn_categories": config.categories})
    assert {item["label"] for item in items} == {"K/BB"}
    assert items[0]["value"] > 0
    with app_module.app.test_request_context("/compare"):
        html = app_module.render_template("partials/compare_modal.html", r1=first, r2=second,
                                           active_categories=config.categories)
    assert search(r'<td>ERA</td>\s*<td[^>]*>\s*&mdash;', html)
    assert search(r'<td>WHIP</td>\s*<td[^>]*>\s*&mdash;', html)
    assert float(search(r'<td>K/BB</td>\s*<td[^>]*>\s*([^<]+)', html).group(1)) > 0
