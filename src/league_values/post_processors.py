from __future__ import annotations

from dataclasses import replace
from typing import Protocol, runtime_checkable

from .models import LeagueConfig, PlayerPool, ValuationResult


@runtime_checkable
class PostProcessor(Protocol):
    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]: ...


class ReplacementLevel:
    def process(self, results: list[ValuationResult], league: LeagueConfig) -> list[ValuationResult]:
        if not league.roster:
            return results

        hitter_slots = sum(
            slots for pos, slots in league.roster.positions.items()
            if pos not in ("SP", "RP", "P")
        )
        pitcher_slots = sum(
            slots for pos, slots in league.roster.positions.items()
            if pos in ("SP", "RP", "P")
        )

        hitter_repl = self._replacement_value(results, PlayerPool.HITTER, league.roster.teams * hitter_slots)
        pitcher_repl = self._replacement_value(results, PlayerPool.PITCHER, league.roster.teams * pitcher_slots)

        adjusted = []
        for r in results:
            if r.player.pool is PlayerPool.HITTER:
                new_val = r.total_value - hitter_repl
            elif r.player.pool is PlayerPool.PITCHER:
                new_val = r.total_value - pitcher_repl
            else:
                new_val = r.total_value
            adjusted.append(replace(r, total_value=new_val))
        return adjusted

    def _replacement_value(self, results: list[ValuationResult], pool: PlayerPool, n_starters: int) -> float:
        pool_results = sorted(
            [r for r in results if r.player.pool is pool],
            key=lambda r: r.total_value,
            reverse=True,
        )
        if not pool_results or n_starters <= 0:
            return 0.0
        idx = min(n_starters, len(pool_results) - 1)
        return pool_results[idx].total_value


class PositionScarcity:
    def __init__(self, multipliers: dict[str, float]) -> None:
        self.multipliers = multipliers

    def process(self, results: list[ValuationResult], league: LeagueConfig) -> list[ValuationResult]:
        adjusted = []
        for r in results:
            mult = self._best_multiplier(r.player.positions)
            adjusted.append(replace(r, total_value=r.total_value * mult))
        return adjusted

    def _best_multiplier(self, positions: tuple[str, ...]) -> float:
        if not positions:
            return 1.0
        mults = [self.multipliers.get(pos, 1.0) for pos in positions]
        return max(mults)
