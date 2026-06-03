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

# --- Pitching ---
# Stored counting stats per pitcher-season (backbone).
PITCHER_COUNTING: tuple[str, ...] = (
    "BF", "IP", "ER", "H_ALLOWED", "BB", "HBP", "K", "HR",
    "W", "L", "SV", "HLD", "GS", "G", "GF", "QS",
)
# Per-batter-faced skill components Marcel projects.
PITCHER_SKILL_RATES: tuple[str, ...] = ("K", "BB", "H_ALLOWED", "HR", "ER", "HBP")
# Skill categories the backtest bar is measured on.
PITCHER_HEADLINE_SKILL: tuple[str, ...] = ("IP", "K", "ERA", "WHIP", "K_9", "BB_9")
# Usage/team-context categories — projected, reported, NOT tuned toward.
PITCHER_HEADLINE_CONTEXT: tuple[str, ...] = ("W", "SV", "QS", "HLD")
# Backtest eval-population innings floors (distinct from app valuation floors).
MIN_SP_IP_EVAL = 60
MIN_RP_IP_EVAL = 20
