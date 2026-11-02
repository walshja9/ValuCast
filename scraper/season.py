"""Which MLB season the pipeline serves."""
from __future__ import annotations

from datetime import date

# The last MLB season whose data the pipeline serves. The calendar can't decide
# this: Jan 1 comes months before 2027 data exists, and a lockout could push it
# further. Flip it by hand once 2027 data exists.
CONTEXT_SEASON = 2026


def context_season(year: int | None = None) -> int:
    """Cap a year, or today's year, at CONTEXT_SEASON. Earlier years pass through."""
    return min(year or date.today().year, CONTEXT_SEASON)
