"""Shared stat-key contracts for the projection layer."""
from __future__ import annotations

# Per-PA rate components Marcel projects. AB and H are DERIVED, not projected.
PROJECTED_RATES: tuple[str, ...] = (
    "1B", "2B", "3B", "HR", "BB", "HBP", "SF", "SO", "SB", "CS", "R", "RBI",
)

# Only production-skill rates receive the age multiplier. SO/CS/SF must NOT,
# or an aging decline would quietly help lower-is-better categories.
AGE_ADJUSTED_RATES: tuple[str, ...] = (
    "1B", "2B", "3B", "HR", "BB", "HBP", "SB",
)

# Counting stats stored in each historical snapshot row.
HISTORICAL_COUNTING: tuple[str, ...] = (
    "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI",
    "SB", "CS", "BB", "SO", "HBP", "SF",
)

# Categories the backtest scores (mixed-scale; never sum raw MAE across them).
HEADLINE_STATS: tuple[str, ...] = (
    "PA", "HR", "R", "RBI", "SB", "AVG", "OBP", "SLG", "OPS",
)

PEAK_AGE = 29
MIN_EVAL_PA = 200  # qualified actual-PA floor for backtest eval population
