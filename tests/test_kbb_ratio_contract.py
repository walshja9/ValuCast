"""Invented counts exercise live ratio impacts separately from legacy raw ratios."""
from dataclasses import replace
from math import isfinite
from unittest.mock import patch

import pytest

from league_values.engine import ValuationEngine, strikeout_walk_ratio
from league_values.models import CategorySpec, Direction, LeagueConfig, PlayerProjection
from league_values.presets import dd_7x7
from web.category_registry import get_categories, get_split_pitching_categories


def arm(name, k=10, bb=0, pool="starter", **stats):
    return PlayerProjection(name, name, pool, {"K": k, "BB": bb, **stats})


def league(category=None, mode="categories"):
    return LeagueConfig("Invented ratio", mode, (category or get_categories(["K_BB"])[0],))


def indexed(players, config):
    return {r.player.id: r for r in ValuationEngine().value_players(players, config)}


def test_live_registry_uses_counts_and_split_specs_keep_ratio_contract():
    cat = get_categories(["K_BB"])[0]
    assert cat.numerator_stats == ("K",)
    assert cat.denominator_stats == ("BB",)
    assert cat.ratio_multiplier == 1 and cat.min_denominator == 0
    assert cat.applies_to("starter") and cat.applies_to("reliever")
    assert not cat.applies_to("hitter")
    assert all(c.is_ratio for c in get_split_pitching_categories(["K_BB"]))


@pytest.mark.parametrize("mode", ["categories", "roto"])
def test_zero_walks_contribute_strikeouts_without_an_infinite_raw_ratio(mode):
    players = [arm("a"), arm("b", 30, 5), arm("c", 10, 5)]
    engine = ValuationEngine()
    cat = league().categories[0]
    baseline = engine._ratio_baseline(cat, players)
    assert baseline == 5
    assert [engine._category_impact(p, cat, players, baseline) for p in players] == [10, 5, -15]
    results = indexed(players, league(mode=mode))
    assert results["a"].raw_values["K_BB"] is None
    assert results["a"].total_value > results["b"].total_value > results["c"].total_value
    assert all(isfinite(r.total_value) for r in results.values())


@pytest.mark.parametrize("mode", ["categories", "roto"])
@pytest.mark.parametrize("bad_stats", [{"K": 99}, {"BB": 1}, {"K": float("nan"), "BB": 1},
                                      {"K": 1, "BB": float("inf")}, {"K": 1, "BB": -1}])
def test_invalid_counts_are_neutral_and_do_not_change_valid_players(mode, bad_stats):
    players = [arm("a"), arm("b", 30, 5), arm("c", 10, 5)]
    config = league(mode=mode)
    before = indexed(players, config)
    invalid = PlayerProjection("missing", "missing", "reliever", bad_stats)
    after = indexed([*players, invalid], config)
    for key in before:
        assert after[key].total_value == pytest.approx(before[key].total_value)
    assert after["missing"].total_value == 0
    assert after["missing"].raw_values["K_BB"] is None


@pytest.mark.parametrize("mode", ["categories", "roto"])
def test_no_auto_reference_is_neutral_but_explicit_zero_reference_is_valid(mode):
    players = [arm("a", 10), arm("b", 20)]
    cat = replace(league().categories[0], missing_value=123)
    results = indexed(players, league(cat, mode))
    assert all(r.total_value == 0 and r.raw_values[cat.id] is None for r in results.values())
    explicit = indexed(players, league(replace(cat, baseline=0), mode))
    assert explicit["b"].total_value > explicit["a"].total_value
    zero = indexed([arm("a", 0, 1), arm("b", 0, 2)], league(cat, mode))
    assert all(r.total_value == 0 for r in zero.values())


@pytest.mark.parametrize("mode", ["categories", "roto"])
def test_reference_computed_once_per_matching_split_pool(mode):
    players = [arm("sp1", 10), arm("sp2", 20), arm("rp1", 20, 5, "reliever"),
               arm("rp2", 10, 5, "reliever"), arm("bat", 900, 1, "hitter")]
    config = LeagueConfig("split", mode, tuple(get_split_pitching_categories(["K_BB"])))
    engine = ValuationEngine()
    with patch.object(engine, "_ratio_baseline", wraps=engine._ratio_baseline) as baseline:
        rows = {r.player.id: r for r in engine.value_players(players, config)}
    assert baseline.call_count == 2
    assert [[p.id for p in call.args[1]] for call in baseline.call_args_list] == [["sp1", "sp2"], ["rp1", "rp2"]]
    assert rows["sp1"].total_value == rows["sp2"].total_value == rows["bat"].total_value == 0
    assert rows["rp1"].total_value > rows["rp2"].total_value


def test_positive_denominator_algebra_and_existing_minimum_policies():
    engine = ValuationEngine()
    cat = league().categories[0]
    players = [arm("a", 13, 2), arm("b", 9, 3)]
    baseline = 22 / 5
    for p in players:
        assert engine._category_impact(p, cat, players, baseline) == pytest.approx((p.stats["K"] / p.stats["BB"] - baseline) * p.stats["BB"])
    for cid, stats in [("AVG", {"AB": 30, "H": 10}), ("OBP", {"AB": 30, "H": 10}),
                       ("ERA", {"IP": 10, "ER": 3}), ("WHIP", {"IP": 10, "BB": 2, "H_ALLOWED": 9})]:
        c = get_categories([cid])[0]
        p = PlayerProjection(cid, cid, c.pool, stats)
        assert engine._raw_category_value(p, c) is None
        assert engine._category_impact(p, c, [p]) == c.missing_value


def test_legacy_dd_ratios_retain_raw_ratio_units_and_fixed_baselines():
    old = dd_7x7()
    cat = next(c for c in old.categories if c.id == "SP_K_BB")
    assert cat.stat == "K_BB" and not cat.is_ratio
    assert old.league_baselines[cat.id] == (3.17, 1.27)
    p = arm("a", 10, 0, K_BB=0)
    result = indexed([p], old)[p.id]
    assert result.z_scores[cat.id] == pytest.approx(-3.17 / 1.27)
    assert result.raw_values[cat.id] == 0
    assert get_split_pitching_categories(["K_BB"])[0].is_ratio


def test_zero_min_count_ratio_extension_retains_direction_multiplier_and_weight():
    cat = CategorySpec("custom", "Custom count ratio", "pitcher", numerator_stats=("K",),
                       denominator_stats=("BB",), ratio_multiplier=9,
                       direction=Direction.LOWER_IS_BETTER, weight=2)
    players = [arm("a", 10, 0), arm("b", 30, 5)]
    engine = ValuationEngine()
    assert engine._ratio_baseline(cat, players) == 72
    assert engine._category_impact(players[0], cat, players, 72) == -10
    assert engine._category_impact(players[1], cat, players, 72) == 10
    rows = indexed(players, league(cat))
    assert rows["a"].category_values[cat.id] == -2
    assert rows["b"].category_values[cat.id] == 2


@pytest.mark.parametrize("stats,expected", [({"K": 10, "BB": 0, "K_BB": 0}, None),
                                         ({"K": 12, "BB": 2, "K_BB": 999}, 6),
                                         ({"K_BB": 999}, None), ({"K": float("inf"), "BB": 1}, None)])
def test_display_ratio_uses_true_counts_without_mutating_numeric_dto(stats, expected):
    player = PlayerProjection("display", "display", "pitcher", stats)
    before = dict(player.stats)
    assert strikeout_walk_ratio(player.stats) == expected
    assert player.stats == before
    assert all(isinstance(value, float) for value in player.stats.values())
