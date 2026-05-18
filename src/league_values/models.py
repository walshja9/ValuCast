from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ScoringMode(str, Enum):
    CATEGORIES = "categories"
    POINTS = "points"


class PlayerPool(str, Enum):
    ALL = "all"
    HITTER = "hitter"
    PITCHER = "pitcher"


class Direction(str, Enum):
    HIGHER_IS_BETTER = "higher"
    LOWER_IS_BETTER = "lower"

    @property
    def sign(self) -> int:
        return 1 if self is Direction.HIGHER_IS_BETTER else -1


def _enum_value(enum_type: type[Enum], value: Any) -> Enum:
    if isinstance(value, enum_type):
        return value
    return enum_type(value)


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(value)


@dataclass(frozen=True)
class CategorySpec:
    """One configurable league category.

    Counting stats use `stat`.
    Ratio/rate stats use `denominator_stats` plus either `numerator_stats` or `stat`.
    """

    id: str
    label: str
    pool: PlayerPool
    stat: str | None = None
    numerator_stats: tuple[str, ...] = ()
    denominator_stats: tuple[str, ...] = ()
    direction: Direction = Direction.HIGHER_IS_BETTER
    weight: float = 1.0
    ratio_multiplier: float = 1.0
    min_denominator: float = 0.0
    baseline: float | None = None
    missing_value: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "pool", _enum_value(PlayerPool, self.pool))
        object.__setattr__(self, "direction", _enum_value(Direction, self.direction))
        object.__setattr__(self, "numerator_stats", _tuple(self.numerator_stats))
        object.__setattr__(self, "denominator_stats", _tuple(self.denominator_stats))
        if not self.stat and not self.numerator_stats:
            raise ValueError(f"Category '{self.id}' needs a stat or numerator_stats.")
        if self.ratio_multiplier == 0:
            raise ValueError(f"Category '{self.id}' ratio_multiplier cannot be 0.")
        if self.weight < 0:
            raise ValueError(f"Category '{self.id}' weight cannot be negative.")

    @property
    def is_ratio(self) -> bool:
        return bool(self.denominator_stats)

    def applies_to(self, player_pool: PlayerPool | str) -> bool:
        player_pool = _enum_value(PlayerPool, player_pool)
        return self.pool is PlayerPool.ALL or self.pool is player_pool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CategorySpec":
        return cls(
            id=str(data["id"]),
            label=str(data.get("label", data["id"])),
            pool=data.get("pool", PlayerPool.ALL.value),
            stat=data.get("stat"),
            numerator_stats=_tuple(data.get("numerator_stats")),
            denominator_stats=_tuple(data.get("denominator_stats")),
            direction=data.get("direction", Direction.HIGHER_IS_BETTER.value),
            weight=float(data.get("weight", 1.0)),
            ratio_multiplier=float(data.get("ratio_multiplier", 1.0)),
            min_denominator=float(data.get("min_denominator", 0.0)),
            baseline=data.get("baseline"),
            missing_value=float(data.get("missing_value", 0.0)),
        )


@dataclass(frozen=True)
class PointRule:
    stat: str
    points: float
    pool: PlayerPool = PlayerPool.ALL

    def __post_init__(self) -> None:
        object.__setattr__(self, "pool", _enum_value(PlayerPool, self.pool))

    def applies_to(self, player_pool: PlayerPool | str) -> bool:
        player_pool = _enum_value(PlayerPool, player_pool)
        return self.pool is PlayerPool.ALL or self.pool is player_pool

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PointRule":
        return cls(
            stat=str(data["stat"]),
            points=float(data["points"]),
            pool=data.get("pool", PlayerPool.ALL.value),
        )


@dataclass(frozen=True)
class LeagueConfig:
    name: str
    scoring_mode: ScoringMode
    categories: tuple[CategorySpec, ...] = ()
    point_rules: tuple[PointRule, ...] = ()
    league_baselines: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    """Optional fixed (mean, stddev) per category id. When provided, z-scores use these
    instead of pool-derived statistics, making valuations stable across different input sets."""

    def __post_init__(self) -> None:
        object.__setattr__(self, "scoring_mode", _enum_value(ScoringMode, self.scoring_mode))
        object.__setattr__(
            self,
            "categories",
            tuple(c if isinstance(c, CategorySpec) else CategorySpec.from_dict(c) for c in self.categories),
        )
        object.__setattr__(
            self,
            "point_rules",
            tuple(r if isinstance(r, PointRule) else PointRule.from_dict(r) for r in self.point_rules),
        )
        if self.scoring_mode is ScoringMode.CATEGORIES and not self.categories:
            raise ValueError("Category leagues need at least one category.")
        if self.scoring_mode is ScoringMode.POINTS and not self.point_rules:
            raise ValueError("Points leagues need at least one point rule.")

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "LeagueConfig":
        baselines = {}
        for cat_id, pair in data.get("league_baselines", {}).items():
            baselines[cat_id] = (float(pair[0]), float(pair[1]))
        return cls(
            name=str(data["name"]),
            scoring_mode=data["scoring_mode"],
            categories=tuple(CategorySpec.from_dict(item) for item in data.get("categories", ())),
            point_rules=tuple(PointRule.from_dict(item) for item in data.get("point_rules", ())),
            league_baselines=baselines,
        )


@dataclass(frozen=True)
class PlayerProjection:
    id: str
    name: str
    pool: PlayerPool
    stats: Mapping[str, float]
    positions: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "pool", _enum_value(PlayerPool, self.pool))
        object.__setattr__(self, "positions", _tuple(self.positions))
        object.__setattr__(self, "stats", {str(k): float(v) for k, v in self.stats.items()})

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "PlayerProjection":
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            pool=data["pool"],
            positions=_tuple(data.get("positions")),
            stats=data.get("stats", {}),
            metadata=data.get("metadata", {}),
        )


@dataclass(frozen=True)
class ValuationResult:
    player: PlayerProjection
    total_value: float
    raw_values: Mapping[str, float | None]
    z_scores: Mapping[str, float]
    category_values: Mapping[str, float]
    points: float | None = None

    @property
    def name(self) -> str:
        return self.player.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.player.id,
            "name": self.player.name,
            "pool": self.player.pool.value,
            "total_value": self.total_value,
            "raw_values": dict(self.raw_values),
            "z_scores": dict(self.z_scores),
            "category_values": dict(self.category_values),
            "points": self.points,
        }
