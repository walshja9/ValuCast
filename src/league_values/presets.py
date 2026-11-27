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
    # Hitting (7 cats) — unchanged
    CategorySpec(id="R", label="Runs", pool=PlayerPool.HITTER, stat="R", weight=0.12),
    CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR", weight=0.16),
    CategorySpec(id="RBI", label="RBI", pool=PlayerPool.HITTER, stat="RBI", weight=0.13),
    CategorySpec(id="SB", label="Stolen Bases", pool=PlayerPool.HITTER, stat="SB", weight=0.10),
    CategorySpec(id="AVG", label="Batting Average", pool=PlayerPool.HITTER, stat="AVG", weight=0.14),
    CategorySpec(id="OPS", label="OPS", pool=PlayerPool.HITTER, stat="OPS", weight=0.25),
    CategorySpec(
        id="SO", label="Strikeouts", pool=PlayerPool.HITTER, stat="SO",
        direction=Direction.LOWER_IS_BETTER, weight=0.14,
    ),
    # SP categories (6) — SP weights from DD's valuation_config.py
    CategorySpec(id="SP_K", label="K (SP)", pool=PlayerPool.STARTER, stat="K", weight=0.20),
    CategorySpec(id="SP_QS", label="QS", pool=PlayerPool.STARTER, stat="QS", weight=0.18),
    CategorySpec(
        id="SP_L", label="Losses (SP)", pool=PlayerPool.STARTER, stat="L",
        direction=Direction.LOWER_IS_BETTER, weight=0.08,
    ),
    CategorySpec(
        id="SP_ERA", label="ERA (SP)", pool=PlayerPool.STARTER, stat="ERA",
        direction=Direction.LOWER_IS_BETTER, weight=0.28,
    ),
    CategorySpec(
        id="SP_WHIP", label="WHIP (SP)", pool=PlayerPool.STARTER, stat="WHIP",
        direction=Direction.LOWER_IS_BETTER, weight=0.25,
    ),
    CategorySpec(id="SP_K_BB", label="K/BB (SP)", pool=PlayerPool.STARTER, stat="K_BB", weight=0.15),
    # RP categories (6) — RP weights from DD's valuation_config.py
    CategorySpec(id="RP_K", label="K (RP)", pool=PlayerPool.RELIEVER, stat="K", weight=0.18),
    CategorySpec(id="RP_SV_HLD", label="SV+HLD", pool=PlayerPool.RELIEVER, stat="SV_HLD", weight=0.18),
    CategorySpec(
        id="RP_L", label="Losses (RP)", pool=PlayerPool.RELIEVER, stat="L",
        direction=Direction.LOWER_IS_BETTER, weight=0.06,
    ),
    CategorySpec(
        id="RP_ERA", label="ERA (RP)", pool=PlayerPool.RELIEVER, stat="ERA",
        direction=Direction.LOWER_IS_BETTER, weight=0.24,
    ),
    CategorySpec(
        id="RP_WHIP", label="WHIP (RP)", pool=PlayerPool.RELIEVER, stat="WHIP",
        direction=Direction.LOWER_IS_BETTER, weight=0.22,
    ),
    CategorySpec(id="RP_K_BB", label="K/BB (RP)", pool=PlayerPool.RELIEVER, stat="K_BB", weight=0.12),
)

DD_7X7_BASELINES: dict[str, tuple[float, float]] = {
    # Hitting
    "R": (75.0, 25.0),
    "HR": (22.0, 12.0),
    "RBI": (72.0, 28.0),
    "SB": (12.0, 15.0),
    "AVG": (0.252, 0.028),
    "OPS": (0.720, 0.085),
    "SO": (140.0, 35.0),
    # SP baselines
    "SP_K": (120.0, 49.0),
    "SP_QS": (9.0, 6.0),
    "SP_L": (7.0, 3.0),
    "SP_ERA": (4.13, 1.07),
    "SP_WHIP": (1.26, 0.18),
    "SP_K_BB": (3.17, 1.27),
    # RP baselines (from DD's LEAGUE_AVG/STD_PITCHING_RP)
    "RP_K": (48.0, 26.0),
    "RP_SV_HLD": (11.0, 11.0),
    "RP_L": (3.0, 2.0),
    "RP_ERA": (4.13, 1.80),
    "RP_WHIP": (1.32, 0.29),
    "RP_K_BB": (2.84, 1.39),
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
    """Legacy fixed-baseline preset; K/BB stays in raw-ratio units.

    Live web presets use count-ratio impacts and are a different contract.
    """
    return LeagueConfig(
        name="DD 7x7",
        scoring_mode=ScoringMode.CATEGORIES,
        categories=DD_7X7_CATEGORIES,
        league_baselines=DD_7X7_BASELINES,
        roster=DD_7X7_ROSTER,
    )
