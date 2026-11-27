"""Risk / Uncertainty model for dynasty and prospect valuations.

Annotation-only: computes risk metadata alongside existing values.
Does not adjust headline value or ranking order.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


RISK_LEVELS: tuple[tuple[float, str], ...] = (
    (0.25, "Low"),
    (0.50, "Moderate"),
    (0.75, "High"),
    (1.00, "Extreme"),
)

SOURCE_RANK_MAXES: dict[str, float] = {
    "pipeline": 100,
    "hkb": 719,
}
SOURCE_SPREAD_THRESHOLD = 0.30


@dataclass(frozen=True)
class RiskDriver:
    """One detected risk factor contributing to a player's risk profile."""
    id: str
    label: str
    score_delta: float
    floor_drag: float
    ceiling_lift: float


@dataclass(frozen=True)
class RiskAssessment:
    """Complete risk annotation for a single player."""
    risk_score: float
    risk_level: str
    value_low: float
    value_high: float
    drivers: tuple[RiskDriver, ...]

    @property
    def driver_labels(self) -> tuple[str, ...]:
        return tuple(d.label for d in self.drivers)

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "value_low": self.value_low,
            "value_high": self.value_high,
            "drivers": [d.label for d in self.drivers],
        }


class RiskModel:
    """Standalone risk assessment for dynasty/prospect valuations.

    Uses duck typing for row input — no web layer imports.
    """

    POSITIVE_BREAKOUT_LABELS = {"major_breakout", "breakout", "rising"}

    def __init__(self, current_year: int | None = None):
        self.current_year = current_year or date.today().year

    def evaluate_dynasty(self, row, value: float | None = None) -> RiskAssessment:
        """Evaluate risk for a dynasty/prospect row.

        Row must have: player_type, positions, age, dynasty_value.
        Optional: eta, level, source_ranks, breakout_label.
        """
        value = getattr(row, "dynasty_value", 0.0) if value is None else value
        drivers = self._dynasty_drivers(row)
        return self._build_assessment(value, drivers)

    def evaluate_redraft(self, player, result=None, metadata=None):
        raise NotImplementedError  # v1.1

    def _dynasty_drivers(self, row) -> list[RiskDriver]:
        drivers: list[RiskDriver] = []
        player_type = getattr(row, "player_type", "mlb")
        positions = getattr(row, "positions", ()) or ()
        age = getattr(row, "age", None)
        eta = getattr(row, "eta", None)
        level = getattr(row, "level", None)
        source_ranks = getattr(row, "source_ranks", None)
        breakout_label = getattr(row, "breakout_label", None)

        is_prospect = player_type == "prospect"
        is_pitcher = any(p in ("SP", "RP") for p in positions)

        # Baseline — always fires
        drivers.append(RiskDriver("baseline", "Baseline uncertainty", 0.03, 3, 3))

        # Pitcher volatility
        if is_pitcher:
            drivers.append(RiskDriver("pitcher_type", "Pitcher volatility", 0.05, 5, 3))

        # Pitcher prospect (stacks with pitcher_type)
        if is_pitcher and is_prospect:
            drivers.append(RiskDriver("pitcher_prospect", "Pitcher prospect", 0.08, 8, 6))

        # Prospect status
        if is_prospect:
            drivers.append(RiskDriver("prospect_status", "Prospect", 0.10, 8, 10))

        # ETA (prospects only, mutually exclusive)
        if is_prospect and eta is not None:
            if eta >= self.current_year + 2:
                drivers.append(RiskDriver("eta_distant", f"ETA {eta}", 0.12, 8, 5))
            elif eta == self.current_year + 1:
                drivers.append(RiskDriver("eta_near", f"ETA {eta}", 0.04, 3, 3))

        # Level (prospects only, mutually exclusive)
        if is_prospect and level is not None:
            if level in ("A", "A+", "CPX", "R"):
                drivers.append(RiskDriver("low_minors", "Low-minors level", 0.12, 10, 8))
            elif level == "AA":
                drivers.append(RiskDriver("mid_minors", "Mid-minors level", 0.06, 5, 4))
            elif level == "AAA":
                drivers.append(RiskDriver("high_minors", "Upper-minors level", 0.03, 3, 3))

        # Source rank spread (prospects only, percentile-normalized)
        if is_prospect and source_ranks:
            normalized = []
            for src, rank in source_ranks.items():
                if isinstance(rank, (int, float)):
                    max_val = SOURCE_RANK_MAXES.get(src)
                    if max_val and max_val > 0:
                        normalized.append(rank / max_val)
            if len(normalized) >= 2:
                spread = max(normalized) - min(normalized)
                if spread > SOURCE_SPREAD_THRESHOLD:
                    drivers.append(RiskDriver("source_spread", "External rank disagreement", 0.08, 7, 4))

        # Age: young prospect
        if is_prospect and age is not None and age <= 21:
            drivers.append(RiskDriver("age_young", f"Age {age} (young)", 0.06, 5, 6))

        # Age: decline (any player)
        if age is not None and age >= 33:
            drivers.append(RiskDriver("age_decline", f"Age {age} (decline)", 0.10, 8, 1))

        # Age: deep decline (stacks with age_decline)
        if age is not None and age >= 36:
            drivers.append(RiskDriver("age_deep_decline", f"Age {age} (deep decline)", 0.06, 5, 0))

        # Incomplete profile — thin scouting coverage (fewer than 2 ranking
        # sources). Keyed on source count, NOT on `level`/`eta`: those fields
        # are chronically null in the feed, so a well-scouted consensus prospect
        # (multiple sources) should not be tagged "incomplete" for lacking them.
        if is_prospect:
            n_sources = sum(
                1 for rank in (source_ranks or {}).values()
                if isinstance(rank, (int, float))
            )
            if n_sources < 2:
                drivers.append(RiskDriver("incomplete_profile", "Incomplete scouting profile", 0.05, 5, 3))

        # Breakout / helium (positive labels only)
        if breakout_label and breakout_label.lower() in self.POSITIVE_BREAKOUT_LABELS:
            drivers.append(RiskDriver("breakout_helium", "Breakout / helium", 0.05, 3, 8))

        return drivers

    def _build_assessment(self, value: float, drivers: list[RiskDriver]) -> RiskAssessment:
        risk_score = min(1.0, sum(d.score_delta for d in drivers))
        floor_drag = sum(d.floor_drag for d in drivers)
        ceiling_lift = sum(d.ceiling_lift for d in drivers)

        value_low = max(0.0, value - floor_drag)
        value_high = min(150.0, value + ceiling_lift)

        risk_level = "Extreme"
        for threshold, level in RISK_LEVELS:
            if risk_score <= threshold:
                risk_level = level
                break

        return RiskAssessment(
            risk_score=round(risk_score, 3),
            risk_level=risk_level,
            value_low=round(value_low, 1),
            value_high=round(value_high, 1),
            drivers=tuple(drivers),
        )
