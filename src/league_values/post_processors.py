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


class VolumeMultiplier:
    """Scale values by playing time: (PA_or_IP / baseline)^0.75.

    Full-time players (PA >= hitter_pa or IP >= sp/rp_ip) get 1.0.
    Partial-season players get a discount. Floor is 0.20.
    RP detection: 'RP' in positions and 'SP' not in positions.
    """

    FLOOR = 0.20
    EXPONENT = 0.75

    def __init__(self, hitter_pa: float = 550, sp_ip: float = 180, rp_ip: float = 65) -> None:
        self.hitter_pa = hitter_pa
        self.sp_ip = sp_ip
        self.rp_ip = rp_ip

    def process(self, results: list[ValuationResult], league: LeagueConfig) -> list[ValuationResult]:
        return [replace(r, total_value=r.total_value * self._multiplier(r)) for r in results]

    def _multiplier(self, result: ValuationResult) -> float:
        player = result.player
        if player.pool is PlayerPool.HITTER:
            pa = player.stats.get("PA", 0.0) or player.stats.get("AB", 0.0)
            return self._compute(pa, self.hitter_pa)
        elif player.pool is PlayerPool.PITCHER:
            ip = player.stats.get("IP", 0.0)
            is_rp = "RP" in player.positions and "SP" not in player.positions
            baseline = self.rp_ip if is_rp else self.sp_ip
            return self._compute(ip, baseline)
        return 1.0

    def _compute(self, volume: float, baseline: float) -> float:
        if volume <= 0:
            return self.FLOOR
        if volume >= baseline:
            return 1.0
        return max(self.FLOOR, (volume / baseline) ** self.EXPONENT)


class AgeCurve:
    def __init__(self, hitter_curve: dict[int, float], pitcher_curve: dict[int, float]) -> None:
        self.hitter_curve = hitter_curve
        self.pitcher_curve = pitcher_curve

    def process(self, results: list[ValuationResult], league: LeagueConfig) -> list[ValuationResult]:
        adjusted = []
        for r in results:
            age = r.player.metadata.get("age")
            if age is None:
                adjusted.append(r)
                continue
            age = int(age)
            curve = self.pitcher_curve if r.player.pool is PlayerPool.PITCHER else self.hitter_curve
            mult = self._interpolate(curve, age)
            adjusted.append(replace(r, total_value=r.total_value * mult))
        return adjusted

    def _interpolate(self, curve: dict[int, float], age: int) -> float:
        if not curve:
            return 1.0
        ages = sorted(curve.keys())
        if age <= ages[0]:
            return curve[ages[0]]
        if age >= ages[-1]:
            return curve[ages[-1]]
        for i in range(len(ages) - 1):
            if ages[i] <= age <= ages[i + 1]:
                lo_age, hi_age = ages[i], ages[i + 1]
                lo_val, hi_val = curve[lo_age], curve[hi_age]
                t = (age - lo_age) / (hi_age - lo_age)
                return lo_val + t * (hi_val - lo_val)
        return 1.0
