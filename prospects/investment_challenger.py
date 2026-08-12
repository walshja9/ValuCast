"""Fixed, research-only investment feature contracts for prospect models."""
from __future__ import annotations


INVESTMENT_FEATURE_MODES = frozenset({"incumbent", "drop_raw_pick_value"})
PITCHER_INVESTMENT_FEATURE_NAMES = (
    "rule4_drafted",
    "draft_record_known",
    "pick_value",
    "inverse_draft_pick",
    "inverse_draft_round",
    "log_signing_bonus",
    "college_drafted",
    "prep_drafted",
)


def _validate_mode(mode: str) -> None:
    if mode not in INVESTMENT_FEATURE_MODES:
        raise ValueError(f"unknown investment feature mode {mode!r}")


def investment_feature_names(role: str, mode: str) -> tuple[str, ...]:
    """Return the fixed investment sub-vector names for ``role`` and ``mode``."""
    _validate_mode(mode)
    if role == "hitter":
        return ()
    if role != "pitcher":
        raise ValueError("role must be hitter or pitcher")
    if mode == "incumbent":
        return PITCHER_INVESTMENT_FEATURE_NAMES
    return tuple(
        name for name in PITCHER_INVESTMENT_FEATURE_NAMES if name != "pick_value"
    )


def investment_feature_vector(
    names: tuple[str, ...] | list[str],
    values: tuple[float, ...] | list[float],
    mode: str,
) -> list[float]:
    """Apply the fixed investment mode without mutating names or values."""
    _validate_mode(mode)
    if len(names) != len(values):
        raise ValueError("investment feature names and values must have equal length")
    if mode == "incumbent":
        return list(values)
    return [value for name, value in zip(names, values) if name != "pick_value"]
