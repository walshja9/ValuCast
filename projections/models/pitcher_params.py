"""Pitcher-specific Marcel params. Deliberately separate from hitter MarcelParams:
NO age multipliers and NO alpha/gamma fields leak in. Pitcher skill age is neutral
in v1 (no curve) and flagged for later pitcher-specific tuning."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PitcherMarcelParams:
    season_weights: tuple[float, ...] = (5.0, 4.0, 3.0)  # newest first
    n_reg: float = 300.0     # BF of league-average added for regression (tunable later)
