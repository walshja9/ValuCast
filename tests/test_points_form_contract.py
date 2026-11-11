"""The points form must preserve separate batting and pitching rules."""
from collections import OrderedDict
import csv
from html.parser import HTMLParser
from io import StringIO
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlsplit

import pytest
from werkzeug.datastructures import MultiDict

import app as app_module
from league_values.engine import ValuationEngine
from league_values.models import PlayerProjection
from web.config_builder import build_config


class _Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name", "").startswith("pt_"):
            self.fields.append((attrs["name"], attrs["value"]))


@pytest.fixture
def points_board(monkeypatch):
    players = [
        PlayerProjection("bat", "Invented Bat", "hitter", {"PA": 600, "BB": 10, "HR": 2, "R": 3}),
        PlayerProjection("arm", "Invented Starter", "starter", {"IP": 180, "BB": 10, "HR": 2, "R": 3}),
        PlayerProjection("pen", "Invented Reliever", "reliever", {"IP": 65, "BB": 10}),
    ]
    active = SimpleNamespace(source_metadata={'target_season': 2026, 'projection_phase': 'in_season_outlook', 'data_kind': 'synthetic_fixture'}, as_of='2026-11-07', get_all=lambda: players, player_count=3, revision="invented-points-v1")
    monkeypatch.setattr(app_module, "_active_store", lambda source: active)
    monkeypatch.setattr(app_module, "_ineligible_mlbam_ids", lambda: frozenset())
    monkeypatch.setattr(app_module, "_REDRAFT_BUNDLE_CACHE", OrderedDict())
    return players


def _form_args(pt_params=None):
    with app_module.app.test_request_context("/"):
        html = app_module.render_template("partials/setup_points.html", pt_params=pt_params or {})
    fields = _Inputs(html).fields
    assert len({name for name, _ in fields}) == len(fields), "Points fields must have unique names"
    return MultiDict([("mode", "points"), *fields])


def _scores(config, players):
    return {r.player.id: r.points for r in ValuationEngine().value_players(players, config)}


def test_default_points_form_roundtrips_the_preset(points_board):
    args = _form_args()
    context = app_module._build_context(args)
    assert args["pt_BB"] == "1"
    assert args["pt_BB_P"] == "-0.5"
    assert _scores(context["config"], points_board) == _scores(build_config(mode="points"), points_board)


def test_zero_points_form_stays_zero_after_reload(points_board):
    args = _form_args()
    for field in args:
        if field.startswith("pt_"):
            args[field] = "0"
    context = app_module._build_context(args)
    assert _scores(context["config"], points_board) == {"bat": 0, "arm": 0, "pen": 0}
    with app_module.app.test_request_context("/rankings", query_string=args, headers={"HX-Request": "true"}):
        response = app_module.rankings()
    restored = MultiDict(parse_qsl(urlsplit(response.headers["HX-Replace-Url"]).query))
    assert restored.keys() == args.keys()
    assert all(float(value) == 0 for field, value in restored.items() if field.startswith("pt_"))
    assert _scores(app_module._build_context(restored)["config"], points_board) == {
        "bat": 0, "arm": 0, "pen": 0,
    }


@pytest.mark.parametrize("field,affected,delta", [("pt_BB", {"bat"}, 20), ("pt_BB_P", {"arm", "pen"}, -15)])
def test_walk_controls_change_only_their_role(points_board, field, affected, delta):
    args = _form_args()
    before = _scores(app_module._build_context(args)["config"], points_board)
    args[field] = "3" if field == "pt_BB" else "-2"
    context = app_module._build_context(args)
    after = _scores(context["config"], points_board)
    assert {key: after[key] - before[key] for key in before} == {
        key: delta if key in affected else 0 for key in before
    }
    assert float(_form_args(context["pt_params"])[field]) == float(args[field])
    assert _scores(app_module._build_context(MultiDict(args.items()))["config"], points_board) == after


def test_pitcher_walk_alias_has_a_distinct_card_cache_identity(points_board):
    with app_module.app.test_request_context("/redraft/share-card.png?mode=points&pt_BB_P=-0.5"):
        original = app_module._png_cache_key()
    with app_module.app.test_request_context("/redraft/share-card.png?mode=points&pt_BB_P=-2"):
        changed = app_module._png_cache_key()
    assert original != changed


def test_legacy_rules_keep_their_explicit_all_pool_contract(points_board):
    assert _scores(build_config(mode="points", rules_str="BB:2"), points_board) == {
        "bat": 20, "arm": 20, "pen": 20,
    }


def test_points_url_preserves_controls_for_reload_and_share(points_board):
    args = _form_args()
    args["pt_BB_P"] = "-2"
    with app_module.app.test_request_context("/rankings", query_string=args, headers={"HX-Request": "true"}):
        response = app_module.rankings()
    restored = MultiDict(parse_qsl(urlsplit(response.headers["HX-Replace-Url"]).query))
    assert restored["pt_BB_P"] == "-2.0"
    assert _scores(app_module._build_context(restored)["config"], points_board) == _scores(
        app_module._build_context(args)["config"], points_board
    )


def test_points_compare_and_csv_reuse_the_board(points_board, monkeypatch):
    args = _form_args()
    args["pt_BB_P"] = "-2"
    expected = {r.player.id: r for r in app_module._build_context(args)["canonical_results"]}
    with app_module.app.test_request_context("/export", query_string=args):
        response = app_module.export_csv()
    rows = {row["Player"]: row for row in csv.DictReader(StringIO(response.get_data(as_text=True)))}
    for result in expected.values():
        assert float(rows[result.player.name]["Value"]) == round(result.total_value, 2)
    args.update({"p1": "bat", "p2": "arm"})
    monkeypatch.setattr(app_module, "render_template", lambda template, **ctx: ctx)
    with app_module.app.test_request_context("/compare", query_string=args):
        compared = app_module.compare()
    assert compared["r1"] is expected["bat"]
    assert compared["r2"] is expected["arm"]
