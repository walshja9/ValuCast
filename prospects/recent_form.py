"""Display-only recent-form momentum from ValuCast-owned MiLB stat lines."""
from __future__ import annotations

from typing import Any


_NONE_RESULT = {"momentum_score": None, "momentum_label": None}
_HITTER_MIN_PA = 40.0
_PITCHER_MIN_IP = 10.0

# Display-selectivity threshold. Calibrated against the live board so ~17% of
# scored prospects flag as moving; the original 0.6 flagged a noisy ~44%, which
# made "Heating Up" meaningless. This is DISPLAY calibration, NOT outcome
# calibration -- there is no historical trailing-window dataset to validate
# momentum against realized outcomes (same blocker as the thin-sample outcome
# gate), so momentum must never feed the score until that backtest exists.
MOMENTUM_LABEL_THRESHOLD = 1.2


def _clean_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _line_sample(line: dict | None, role: str) -> float:
    if not isinstance(line, dict):
        return 0.0
    key = "innings_pitched" if role == "pitcher" else "plate_appearances"
    fallback = "ip" if role == "pitcher" else "pa"
    return _clean_float(line.get(key, line.get(fallback))) or 0.0


def _normalized_delta(
    season_line: dict | None,
    recent_line: dict | None,
    season_key: str,
    recent_key: str,
    scale: float,
    *,
    invert: bool = False,
) -> float | None:
    if not isinstance(season_line, dict) or not isinstance(recent_line, dict):
        return None
    season_value = _clean_float(season_line.get(season_key))
    recent_value = _clean_float(recent_line.get(recent_key))
    if season_value is None or recent_value is None or not scale:
        return None
    delta = season_value - recent_value if invert else recent_value - season_value
    return delta / scale


def _weighted_score(terms: tuple[tuple[float, float | None], ...]) -> float | None:
    present = [(weight, value) for weight, value in terms if value is not None]
    total_weight = sum(weight for weight, _value in present)
    if total_weight <= 0:
        return None
    raw = sum(weight * value for weight, value in present) / total_weight
    return round(max(-3.0, min(3.0, raw)), 3)


def _label(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= MOMENTUM_LABEL_THRESHOLD:
        return "Heating Up"
    if score <= -MOMENTUM_LABEL_THRESHOLD:
        return "Cooling Off"
    return "Steady"


def compute_momentum(season_line: dict | None, recent_line: dict | None, role: str) -> dict:
    """Return display-only momentum score/label for a season line plus trailing line.

    The weights/thresholds are DISPLAY-ONLY heuristics; recalibrate via
    prospects/gate.py decide_gate.
    """
    role = str(role or "").lower()
    if role not in {"hitter", "pitcher"}:
        return dict(_NONE_RESULT)

    sample = _line_sample(recent_line, role)
    if role == "hitter":
        if sample < _HITTER_MIN_PA:
            return dict(_NONE_RESULT)
        score = _weighted_score(
            (
                (
                    0.40,
                    _normalized_delta(season_line, recent_line, "ops", "ops", 0.150),
                ),
                (
                    0.25,
                    _normalized_delta(season_line, recent_line, "iso", "iso", 0.050),
                ),
                (
                    0.20,
                    _normalized_delta(season_line, recent_line, "k_pct", "k_pct", 5.0, invert=True),
                ),
                (
                    0.15,
                    _normalized_delta(season_line, recent_line, "bb_pct", "bb_pct", 3.0),
                ),
            )
        )
    else:
        if sample < _PITCHER_MIN_IP:
            return dict(_NONE_RESULT)
        score = _weighted_score(
            (
                (
                    0.40,
                    _normalized_delta(season_line, recent_line, "k_bb_pct", "k_bb_pct", 5.0),
                ),
                (
                    0.25,
                    _normalized_delta(season_line, recent_line, "k_per_9", "k_per_9", 1.5),
                ),
                (
                    0.15,
                    _normalized_delta(
                        season_line,
                        recent_line,
                        "bb_per_9",
                        "bb_per_9",
                        1.0,
                        invert=True,
                    ),
                ),
                (
                    0.20,
                    _normalized_delta(season_line, recent_line, "era", "era", 1.5, invert=True),
                ),
            )
        )

    return {"momentum_score": score, "momentum_label": _label(score)}
