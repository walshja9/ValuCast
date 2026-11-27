"""Redraft callers reuse the full canonical board, independent of display filters."""
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from werkzeug.datastructures import MultiDict

import app as app_module
from league_values.models import PlayerProjection


@pytest.fixture
def synthetic_board(monkeypatch):
    players = [
        PlayerProjection(
            id=f"canonical-{index}", name=f"Canonical {index}", pool="hitter",
            positions=("OF",) if index == 0 else ("SS",),
            stats={"PA": 400, "HR": index + 1},
        )
        for index in range(201)
    ]
    below_floor = PlayerProjection(
        id="below-floor", name="Below Floor", pool="hitter", positions=("OF",),
        stats={"PA": 1, "HR": 0},
    )
    players.append(below_floor)
    by_id = {player.id: player for player in players}
    active = SimpleNamespace(
        as_of="synthetic-canonical-reuse", player_count=len(players),
        get_all=lambda: list(players), get_by_id=by_id.get,
    )
    monkeypatch.setattr(app_module, "_active_store", lambda source: active)
    monkeypatch.setattr(app_module, "_ineligible_mlbam_ids", lambda: frozenset())
    monkeypatch.setattr(app_module, "_REDRAFT_BUNDLE_CACHE", OrderedDict())
    monkeypatch.setattr(app_module, "_card_extras", lambda *args: {})
    monkeypatch.setattr(app_module, "_dynasty_snapshot_row_for", lambda *args: None)
    monkeypatch.setattr(app_module, "render_template", lambda template, **ctx: ctx)
    valuation = Mock(wraps=app_module._redraft_value_players)
    monkeypatch.setattr(app_module, "_redraft_value_players", valuation)
    return players[0], below_floor, valuation


def _serve(consumer, player_id, args):
    with app_module.app.test_request_context(
        "/", query_string=args, headers={"HX-Request": "true"},
    ):
        if consumer == "detail":
            ctx = app_module.player_detail(player_id)
            return ctx["result"], ctx
        if consumer == "compare":
            ctx = app_module.compare()
            assert ctx["r1"] is ctx["r2"]
            return ctx["r1"], ctx
        ctx, status = app_module._build_redraft_player_card_context(player_id, args)
        assert status == 200
        return ctx["dyn_result"], ctx


@pytest.mark.parametrize("consumer", ["detail", "compare", "card"])
def test_canonical_consumer_values_once_cold_and_reuses_filtered_full_board(
    synthetic_board, consumer,
):
    target, _, valuation = synthetic_board
    args = MultiDict({"cats": "HR", "pcats": "K", "position": "SS",
                      "p1": target.id, "p2": target.id})

    result, served = _serve(consumer, target.id, args)

    assert valuation.call_count == 1
    ctx = app_module._build_context(args)
    assert len(ctx["results"]) == 200
    assert len(ctx["canonical_results"]) == 201
    assert target.id not in {row.player.id for row in ctx["results"]}
    assert ctx["canonical_results"][-1].player.id == target.id
    assert result is ctx["canonical_results"][-1]
    if consumer == "card":
        assert served["redraft_value_scale"] is ctx["redraft_value_scale"]

    valuation.reset_mock()
    args["position"] = "OF"
    repeated, _ = _serve(consumer, target.id, args)

    assert valuation.call_count == 0
    assert repeated is result
    assert len(ctx["canonical_results"]) == 201


@pytest.mark.parametrize("consumer", ["detail", "compare", "card"])
def test_search_extra_stays_below_floor_for_canonical_consumers(
    synthetic_board, consumer,
):
    _, below_floor, valuation = synthetic_board
    args = MultiDict({"cats": "HR", "pcats": "K", "search": below_floor.name,
                      "p1": below_floor.id, "p2": below_floor.id})
    ctx = app_module._build_context(args)
    assert [row.player.id for row in ctx["results"]] == [below_floor.id]
    assert below_floor.id not in ctx["canonical_ids"]
    valuation.reset_mock()

    result, _ = _serve(consumer, below_floor.id, args)

    assert result is None
    # Search still values its explicit display extra; there is no second full-board run.
    assert valuation.call_count == 1
    assert len(ctx["canonical_results"]) == 201
    assert all(row.player.id != below_floor.id for row in ctx["canonical_results"])
