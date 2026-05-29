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
        return []  # Placeholder — implemented in Task 3

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
