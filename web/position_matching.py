"""Shared row position matching for public board stores."""
from __future__ import annotations

PITCHER_POSITIONS = frozenset({"SP", "RP", "P"})


def has_hitter_position(row) -> bool:
    return any(position not in PITCHER_POSITIONS for position in row.positions)


def has_pitcher_position(row) -> bool:
    return any(position in PITCHER_POSITIONS for position in row.positions)


def matches_position(row, requested_position: str) -> bool:
    if requested_position in row.positions:
        return True

    # Prospect feeds often know only "P", while the UI exposes SP/RP filters.
    # Treat generic prospect pitcher rows as SP-filter eligible unless the row
    # is explicitly marked RP. Keep RP strict so generic P does not masquerade
    # as relief-only.
    if (
        requested_position == "SP"
        and getattr(row, "is_prospect", False)
        and "P" in row.positions
        and "RP" not in row.positions
    ):
        return True

    return False
