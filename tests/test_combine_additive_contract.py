"""Matching actuals must preserve the declared ROS additive stat contract."""
import pytest

from league_values.engine import ValuationEngine
from league_values.models import LeagueConfig, PointRule
from scraper.combine import combine_outlook


_EXTRA_COUNTS = {
    "hitter": ("GDP", "SH", "IBB"),
    "starter": ("HR", "R", "HBP", "BS", "TBF", "IBB"),
    "reliever": ("HR", "R", "HBP", "BS", "TBF", "IBB"),
}


def _row(pool, stats):
    return {"id": "invented", "name": "Invented Player", "pool": pool,
            "stats": stats, "metadata": {"mlbam_id": "999999"}}


@pytest.mark.parametrize("pool", _EXTRA_COUNTS)
def test_zero_actuals_preserve_ros_additive_counts_and_custom_points(pool):
    counts = {key: float(index + 1) for index, key in enumerate(_EXTRA_COUNTS[pool])}
    ros = _row(pool, counts)
    config = LeagueConfig("Invented points", "points", point_rules=tuple(
        PointRule(stat=key, points=-1) for key in counts
    ))
    ros_only = combine_outlook([ros], [])[0]
    matched = combine_outlook([ros], [_row(pool, {})])[0]
    assert {key: matched["stats"][key] for key in counts} == counts
    engine = ValuationEngine()
    assert engine.value_players([matched], config)[0].points == engine.value_players([ros_only], config)[0].points


@pytest.mark.parametrize("pool", _EXTRA_COUNTS)
def test_extra_counts_add_and_keep_existing_missing_semantics(pool):
    keys = _EXTRA_COUNTS[pool]
    ros = _row(pool, {key: 1.25 for key in keys})
    actual = _row(pool, {key: 2 for key in keys})
    actual["stats"][keys[0]] = None
    del ros["stats"][keys[-1]]
    result = combine_outlook([ros], [actual])[0]
    assert result["stats"][keys[0]] == 1.25
    assert result["stats"][keys[-1]] == 2
    assert all(result["stats"][key] == 3.25 for key in keys[1:-1])


def test_matched_pitcher_recomputes_rates_and_excludes_unknown_keys():
    ros = _row("starter", {"IP": 30, "ER": 10, "BB": 5, "H_ALLOWED": 25,
                           "K": 40, "ERA": 99, "WHIP": 99, "K_BB": 99,
                           "undeclared_count": 100})
    actual = _row("starter", {"IP": 30, "ER": 10, "BB": 5, "H_ALLOWED": 25,
                              "K": 40, "ERA": 99, "WHIP": 99, "K_BB": 99})
    stats = combine_outlook([ros], [actual])[0]["stats"]
    assert (stats["ERA"], stats["WHIP"], stats["K_BB"]) == (3, 1, 8)
    assert "undeclared_count" not in stats
