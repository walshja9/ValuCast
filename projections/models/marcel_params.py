"""Tunable Marcel constants. Defaults reproduce classic Marcel; the harness
tunes them — that is where we beat textbook Marcel."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarcelParams:
    season_weights: tuple[float, ...] = (5.0, 4.0, 3.0)  # newest first
    n_reg: float = 1200.0          # PA of league-average added for regression
    k_young: float = 0.006         # per-year uplift below peak age
    k_old: float = 0.003           # per-year decline above peak age
    pa_w1: float = 0.5             # weight on PA[T-1]
    pa_w2: float = 0.1             # weight on PA[T-2]
    pa_base: float = 200.0         # baseline PA added
