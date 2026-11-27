from __future__ import annotations

from math import isfinite, sqrt
from typing import Iterable, Mapping

from .models import (
    CategorySpec,
    LeagueConfig,
    PlayerProjection,
    ScoringMode,
    ValuationResult,
)


class ValuationEngine:
    """Scores projections using only the league configuration."""

    def __init__(self, post_processors: list | None = None) -> None:
        self.post_processors = post_processors or []

    def value_players(
        self,
        players: Iterable[PlayerProjection | Mapping[str, object]],
        league: LeagueConfig | Mapping[str, object],
    ) -> list[ValuationResult]:
        league_config = league if isinstance(league, LeagueConfig) else LeagueConfig.from_dict(league)
        projections = [
            player if isinstance(player, PlayerProjection) else PlayerProjection.from_dict(player)
            for player in players
        ]

        if league_config.scoring_mode is ScoringMode.POINTS:
            results = self._value_points(projections, league_config)
        elif league_config.scoring_mode is ScoringMode.ROTO:
            results = self._value_roto(projections, league_config)
        else:
            results = self._value_categories(projections, league_config)

        for processor in self.post_processors:
            results = processor.process(results, league_config)

        return sorted(results, key=lambda result: result.total_value, reverse=True)

    def _value_points(
        self,
        players: list[PlayerProjection],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        results: list[ValuationResult] = []
        for player in players:
            points_by_rule: dict[str, float] = {}
            total = 0.0
            for rule in league.point_rules:
                if not rule.applies_to(player.pool):
                    continue
                value = player.stats.get(rule.stat, 0.0) * rule.points
                points_by_rule[rule.stat] = points_by_rule.get(rule.stat, 0.0) + value
                total += value
            results.append(
                ValuationResult(
                    player=player,
                    total_value=total,
                    raw_values={},
                    z_scores={},
                    category_values=points_by_rule,
                    points=total,
                )
            )
        return results

    def _value_categories(
        self,
        players: list[PlayerProjection],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        raw_values: dict[str, dict[str, float | None]] = {player.id: {} for player in players}
        z_scores: dict[str, dict[str, float]] = {player.id: {} for player in players}
        category_values: dict[str, dict[str, float]] = {player.id: {} for player in players}

        for category in league.categories:
            eligible_players = [player for player in players if category.applies_to(player.pool)]

            impacts = self._category_impacts(category, eligible_players)

            # Use fixed league baselines if provided, otherwise derive from pool.
            # league_baselines are in "raw stat space" — for non-ratio stats with
            # LOWER_IS_BETTER direction, transform mean to match impact space
            # (impacts have direction.sign applied).
            if category.id in league.league_baselines:
                mean, stddev = league.league_baselines[category.id]
                if not category.is_ratio:
                    mean = category.direction.sign * mean
            else:
                mean, stddev = _mean_stddev([v for v in impacts.values() if v is not None])

            for player in players:
                raw_values[player.id][category.id] = (
                    self._raw_category_value(player, category)
                    if category.applies_to(player.pool)
                    else None
                )
                if not category.applies_to(player.pool) or impacts.get(player.id) is None or stddev == 0:
                    z = 0.0
                else:
                    z = (impacts[player.id] - mean) / stddev
                z_scores[player.id][category.id] = z
                category_values[player.id][category.id] = z * category.weight

        results = [
            ValuationResult(
                player=player,
                total_value=sum(category_values[player.id].values()),
                raw_values=raw_values[player.id],
                z_scores=z_scores[player.id],
                category_values=category_values[player.id],
            )
            for player in players
        ]
        return results

    def _value_roto(
        self,
        players: list[PlayerProjection],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        raw_values: dict[str, dict[str, float | None]] = {p.id: {} for p in players}
        sgp_values: dict[str, dict[str, float]] = {p.id: {} for p in players}

        for category in league.categories:
            eligible = [p for p in players if category.applies_to(p.pool)]

            impacts = self._category_impacts(category, eligible)

            sorted_impacts = sorted((v for v in impacts.values() if v is not None), reverse=True)
            if len(sorted_impacts) >= 2:
                gaps = [sorted_impacts[i] - sorted_impacts[i + 1] for i in range(len(sorted_impacts) - 1)]
                sgp_denom = sum(gaps) / len(gaps) if gaps else 1.0
                if sgp_denom == 0:
                    sgp_denom = 1.0
            else:
                sgp_denom = None  # single-player pool: no standings gain possible

            for player in players:
                raw_values[player.id][category.id] = (
                    self._raw_category_value(player, category)
                    if category.applies_to(player.pool)
                    else None
                )
                if not category.applies_to(player.pool) or impacts.get(player.id) is None or sgp_denom is None:
                    sgp_values[player.id][category.id] = 0.0
                else:
                    sgp_values[player.id][category.id] = impacts[player.id] * category.weight / sgp_denom

        results = [
            ValuationResult(
                player=player,
                total_value=sum(sgp_values[player.id].values()),
                raw_values=raw_values[player.id],
                z_scores={},
                category_values=sgp_values[player.id],
            )
            for player in players
        ]
        return results

    def _category_impacts(
        self, category: CategorySpec, pool: list[PlayerProjection],
    ) -> dict[str, float | None]:
        baseline = category.baseline
        if category.is_ratio and baseline is None:
            baseline = self._ratio_baseline(category, pool)
        if _zero_min_count_ratio(category) and baseline is None:
            # No observed denominator in this pool: no automatic reference.
            return {player.id: None for player in pool}
        return {player.id: self._category_impact(player, category, pool, baseline) for player in pool}

    def _category_impact(
        self,
        player: PlayerProjection,
        category: CategorySpec,
        pool: list[PlayerProjection],
        precomputed_baseline: float | None = None,
    ) -> float | None:
        if not category.is_ratio:
            raw = self._raw_category_value(player, category)
            return category.direction.sign * (raw if raw is not None else category.missing_value)

        if _zero_min_count_ratio(category):
            counts = _ratio_counts(player.stats, category.numerator_stats, category.denominator_stats)
            if counts is None:
                return None
            baseline = category.baseline if category.baseline is not None else precomputed_baseline
            if baseline is None:
                baseline = self._ratio_baseline(category, pool)
            if baseline is None:
                return None
            numerator, denominator = counts
            impact = category.direction.sign * (numerator - baseline * denominator / category.ratio_multiplier)
            return impact if isfinite(impact) else None

        denominator = _sum_stats(player.stats, category.denominator_stats)
        if denominator <= category.min_denominator:
            return category.missing_value

        raw = self._raw_category_value(player, category)
        if raw is None:
            return category.missing_value

        baseline = category.baseline
        if baseline is None:
            baseline = precomputed_baseline if precomputed_baseline is not None else self._ratio_baseline(category, pool)

        return category.direction.sign * (raw - baseline) * denominator / category.ratio_multiplier

    def _ratio_baseline(self, category: CategorySpec, pool: list[PlayerProjection]) -> float | None:
        if category.baseline is not None:
            return category.baseline

        if _zero_min_count_ratio(category):
            counts = [_ratio_counts(p.stats, category.numerator_stats, category.denominator_stats) for p in pool]
            numerator = sum(pair[0] for pair in counts if pair is not None)
            denominator = sum(pair[1] for pair in counts if pair is not None)
            if denominator == 0:
                return None
            baseline = numerator * category.ratio_multiplier / denominator
            return baseline if isfinite(baseline) else None

        if category.numerator_stats:
            numerator = sum(_sum_stats(player.stats, category.numerator_stats) for player in pool)
            denominator = sum(_sum_stats(player.stats, category.denominator_stats) for player in pool)
            if denominator == 0:
                return 0.0
            return numerator * category.ratio_multiplier / denominator

        weighted_sum = 0.0
        denominator_sum = 0.0
        for player in pool:
            denominator = _sum_stats(player.stats, category.denominator_stats)
            value = player.stats.get(category.stat or "", category.missing_value)
            if denominator <= category.min_denominator:
                continue
            weighted_sum += value * denominator
            denominator_sum += denominator
        if denominator_sum == 0:
            return 0.0
        return weighted_sum / denominator_sum

    def _raw_category_value(
        self,
        player: PlayerProjection,
        category: CategorySpec,
    ) -> float | None:
        if not category.is_ratio:
            return player.stats.get(category.stat or "", category.missing_value)

        if _zero_min_count_ratio(category):
            return _count_ratio_value(player.stats, category.numerator_stats, category.denominator_stats, category.ratio_multiplier)

        denominator = _sum_stats(player.stats, category.denominator_stats)
        if denominator <= category.min_denominator:
            return None

        if category.numerator_stats:
            numerator = _sum_stats(player.stats, category.numerator_stats)
            return numerator * category.ratio_multiplier / denominator

        if category.stat:
            return player.stats.get(category.stat, category.missing_value)

        return None


def _zero_min_count_ratio(category: CategorySpec) -> bool:
    return bool(category.numerator_stats and category.denominator_stats and category.min_denominator == 0)


def _ratio_counts(
    stats: Mapping[str, float], numerator_keys: tuple[str, ...], denominator_keys: tuple[str, ...],
) -> tuple[float, float] | None:
    """Require observed finite counts; an absent count is not an observed zero."""
    values = [stats.get(key) for key in numerator_keys + denominator_keys]
    if any(not isinstance(value, (int, float)) or not isfinite(value) or value < 0 for value in values):
        return None
    numerator = sum(stats[key] for key in numerator_keys)
    denominator = sum(stats[key] for key in denominator_keys)
    return (numerator, denominator) if isfinite(numerator) and isfinite(denominator) else None


def _count_ratio_value(stats, numerator_keys, denominator_keys, multiplier=1.0) -> float | None:
    counts = _ratio_counts(stats, numerator_keys, denominator_keys)
    if counts is None or counts[1] == 0:
        return None
    value = counts[0] * multiplier / counts[1]
    return value if isfinite(value) else None


def strikeout_walk_ratio(stats: Mapping[str, float]) -> float | None:
    """Display K/BB from true counts; undefined ratios remain absent from views."""
    return _count_ratio_value(stats, ("K",), ("BB",))


def value_players(
    players: Iterable[PlayerProjection | Mapping[str, object]],
    league: LeagueConfig | Mapping[str, object],
) -> list[ValuationResult]:
    return ValuationEngine().value_players(players, league)


def _sum_stats(stats: Mapping[str, float], keys: tuple[str, ...]) -> float:
    return sum(float(stats.get(key, 0.0)) for key in keys)


def _mean_stddev(values: list[float]) -> tuple[float, float]:
    if not values:
        return 0.0, 0.0
    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return mean, sqrt(variance)
