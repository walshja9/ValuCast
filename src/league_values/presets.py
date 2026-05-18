from __future__ import annotations

from .models import CategorySpec, Direction, LeagueConfig, PlayerPool, PointRule, ScoringMode


STANDARD_5X5_CATEGORIES: tuple[CategorySpec, ...] = (
    CategorySpec(id="R", label="Runs", pool=PlayerPool.HITTER, stat="R"),
    CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR"),
    CategorySpec(id="RBI", label="RBI", pool=PlayerPool.HITTER, stat="RBI"),
    CategorySpec(id="SB", label="Stolen Bases", pool=PlayerPool.HITTER, stat="SB"),
    CategorySpec(
        id="AVG",
        label="Batting Average",
        pool=PlayerPool.HITTER,
        numerator_stats=("H",),
        denominator_stats=("AB",),
        min_denominator=30.0,
    ),
    CategorySpec(id="W", label="Wins", pool=PlayerPool.PITCHER, stat="W"),
    CategorySpec(id="SV", label="Saves", pool=PlayerPool.PITCHER, stat="SV"),
    CategorySpec(id="K", label="Strikeouts", pool=PlayerPool.PITCHER, stat="K"),
    CategorySpec(
        id="ERA",
        label="ERA",
        pool=PlayerPool.PITCHER,
        numerator_stats=("ER",),
        denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER,
        ratio_multiplier=9.0,
        min_denominator=10.0,
    ),
    CategorySpec(
        id="WHIP",
        label="WHIP",
        pool=PlayerPool.PITCHER,
        numerator_stats=("BB", "H_ALLOWED"),
        denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER,
        min_denominator=10.0,
    ),
)


DEFAULT_POINTS_RULES: tuple[PointRule, ...] = (
    PointRule(stat="R", points=1.0, pool=PlayerPool.HITTER),
    PointRule(stat="RBI", points=1.0, pool=PlayerPool.HITTER),
    PointRule(stat="1B", points=1.0, pool=PlayerPool.HITTER),
    PointRule(stat="2B", points=2.0, pool=PlayerPool.HITTER),
    PointRule(stat="3B", points=3.0, pool=PlayerPool.HITTER),
    PointRule(stat="HR", points=4.0, pool=PlayerPool.HITTER),
    PointRule(stat="BB", points=1.0, pool=PlayerPool.HITTER),
    PointRule(stat="SB", points=2.0, pool=PlayerPool.HITTER),
    PointRule(stat="CS", points=-1.0, pool=PlayerPool.HITTER),
    PointRule(stat="IP", points=3.0, pool=PlayerPool.PITCHER),
    PointRule(stat="K", points=1.0, pool=PlayerPool.PITCHER),
    PointRule(stat="W", points=5.0, pool=PlayerPool.PITCHER),
    PointRule(stat="SV", points=5.0, pool=PlayerPool.PITCHER),
    PointRule(stat="ER", points=-2.0, pool=PlayerPool.PITCHER),
    PointRule(stat="BB", points=-0.5, pool=PlayerPool.PITCHER),
    PointRule(stat="H_ALLOWED", points=-0.5, pool=PlayerPool.PITCHER),
)


def standard_5x5() -> LeagueConfig:
    return LeagueConfig(
        name="Standard 5x5",
        scoring_mode=ScoringMode.CATEGORIES,
        categories=STANDARD_5X5_CATEGORIES,
    )


def default_points() -> LeagueConfig:
    return LeagueConfig(
        name="Default points",
        scoring_mode=ScoringMode.POINTS,
        point_rules=DEFAULT_POINTS_RULES,
    )
