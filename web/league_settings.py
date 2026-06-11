"""League settings for dynasty customization — parse, clamp, summarize.

Stateless by design: settings ride the URL as plain form params (teams, budget,
roster, pslots) exactly like every other board option. Invalid or absent values
fall back to defaults so a mangled URL can never 500 the board.
"""
from __future__ import annotations

from dataclasses import dataclass

DEFAULT_TEAMS = 12
DEFAULT_BUDGET = 200
DEFAULT_ROSTER = 26
DEFAULT_PSLOTS = 5

# (min, max) clamps per spec.
_BOUNDS = {
    "teams": (4, 20),
    "budget": (100, 1000),
    "roster": (10, 50),
    "pslots": (0, 20),
}


@dataclass(frozen=True)
class LeagueSettings:
    teams: int = DEFAULT_TEAMS
    budget: int = DEFAULT_BUDGET
    roster: int = DEFAULT_ROSTER
    pslots: int = DEFAULT_PSLOTS

    @property
    def roster_cutoff(self) -> int:
        """Total rostered players league-wide = the replacement-level rank."""
        return self.teams * self.roster

    @property
    def prospect_cutoff(self) -> int:
        """Total prospect slots league-wide (prospects-board divider only)."""
        return self.teams * self.pslots

    @property
    def total_budget(self) -> int:
        return self.teams * self.budget

    @property
    def is_default(self) -> bool:
        return (self.teams, self.budget, self.roster, self.pslots) == (
            DEFAULT_TEAMS, DEFAULT_BUDGET, DEFAULT_ROSTER, DEFAULT_PSLOTS)

    def summary(self) -> str:
        return (f"{self.teams} teams · ${self.budget} · "
                f"{self.roster} roster spots · {self.pslots} prospect slots")


def _clamp_int(raw, field: str, default: int) -> int:
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    lo, hi = _BOUNDS[field]
    return max(lo, min(hi, value))


def parse_league_settings(args) -> LeagueSettings:
    """Parse request args into LeagueSettings. Garbage -> defaults, extremes -> clamped."""
    return LeagueSettings(
        teams=_clamp_int(args.get("teams"), "teams", DEFAULT_TEAMS),
        budget=_clamp_int(args.get("budget"), "budget", DEFAULT_BUDGET),
        roster=_clamp_int(args.get("roster"), "roster", DEFAULT_ROSTER),
        pslots=_clamp_int(args.get("pslots"), "pslots", DEFAULT_PSLOTS),
    )
