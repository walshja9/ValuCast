from __future__ import annotations

from .models import CategorySpec, Direction, LeagueConfig, PlayerPool, PointRule, RosterSettings, ScoringMode


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


DD_7X7_CATEGORIES: tuple[CategorySpec, ...] = (
    # Hitting (7 cats)
    CategorySpec(id="R", label="Runs", pool=PlayerPool.HITTER, stat="R", weight=0.12),
    CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR", weight=0.16),
    CategorySpec(id="RBI", label="RBI", pool=PlayerPool.HITTER, stat="RBI", weight=0.13),
    CategorySpec(id="SB", label="Stolen Bases", pool=PlayerPool.HITTER, stat="SB", weight=0.10),
    CategorySpec(
        id="AVG", label="Batting Average", pool=PlayerPool.HITTER,
        numerator_stats=("H",), denominator_stats=("AB",),
        weight=0.14, min_denominator=50.0,
    ),
    CategorySpec(id="OPS", label="OPS", pool=PlayerPool.HITTER, stat="OPS", weight=0.25),
    CategorySpec(
        id="SO", label="Strikeouts", pool=PlayerPool.HITTER, stat="SO",
        direction=Direction.LOWER_IS_BETTER, weight=0.14,
    ),
    # Pitching (7 cats)
    CategorySpec(id="K", label="Strikeouts", pool=PlayerPool.PITCHER, stat="K", weight=0.20),
    CategorySpec(id="QS", label="Quality Starts", pool=PlayerPool.PITCHER, stat="QS", weight=0.18),
    CategorySpec(id="SV_HLD", label="Saves + Holds", pool=PlayerPool.PITCHER, stat="SV_HLD", weight=0.18),
    CategorySpec(
        id="L", label="Losses", pool=PlayerPool.PITCHER, stat="L",
        direction=Direction.LOWER_IS_BETTER, weight=0.08,
    ),
    CategorySpec(
        id="ERA", label="ERA", pool=PlayerPool.PITCHER,
        numerator_stats=("ER",), denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER, ratio_multiplier=9.0,
        weight=0.28, min_denominator=10.0,
    ),
    CategorySpec(
        id="WHIP", label="WHIP", pool=PlayerPool.PITCHER,
        numerator_stats=("BB", "H_ALLOWED"), denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER,
        weight=0.25, min_denominator=10.0,
    ),
    CategorySpec(id="K_BB", label="K/BB", pool=PlayerPool.PITCHER, stat="K_BB", weight=0.15),
)

DD_7X7_BASELINES: dict[str, tuple[float, float]] = {
    "R": (75.0, 25.0),
    "HR": (22.0, 12.0),
    "RBI": (72.0, 28.0),
    "SB": (12.0, 15.0),
    "AVG": (0.252, 0.028),
    "OPS": (0.720, 0.085),
    "SO": (140.0, 35.0),
    "K": (120.0, 49.0),
    "QS": (9.0, 6.0),
    "SV_HLD": (1.0, 3.0),
    "L": (7.0, 3.0),
    "ERA": (4.13, 1.07),
    "WHIP": (1.26, 0.18),
    "K_BB": (3.17, 1.27),
}

DD_7X7_ROSTER = RosterSettings(
    teams=12,
    roster_size=23,
    positions={
        "C": 1, "1B": 1, "2B": 1, "SS": 1, "3B": 1,
        "OF": 3, "UTIL": 1,
        "SP": 5, "RP": 2,
    },
    bench=7,
)


def dd_7x7() -> LeagueConfig:
    return LeagueConfig(
        name="DD 7x7",
        scoring_mode=ScoringMode.CATEGORIES,
        categories=DD_7X7_CATEGORIES,
        league_baselines=DD_7X7_BASELINES,
        roster=DD_7X7_ROSTER,
    )
