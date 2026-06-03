"""Our own expected-stats model: an empirical EV x LA grid. Plain dicts, stdlib only.
A cell's p_hit / e_bases are the league outcome rates for balls in that EV/LA bucket."""
from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

EV_BIN = 2     # mph
LA_BIN = 5     # degrees
MIN_CELL_SAMPLE = 50   # below this, fall back (neighbors -> EV marginal -> global)

_HIT_BASES = {"single": 1, "double": 2, "triple": 3, "home_run": 4}


def cell_key(ev: float, la: float) -> tuple[int, int]:
    """Floor EV/LA to their bin edges."""
    return (int(math.floor(ev / EV_BIN) * EV_BIN), int(math.floor(la / LA_BIN) * LA_BIN))


def outcome_bases(events: str) -> tuple[int, int]:
    """(is_hit 0/1, total_bases) from the Savant `events` outcome. Non-hits (outs,
    errors, sacrifices, fielders_choice) are 0/0 — only the four hit types count."""
    b = _HIT_BASES.get(events)
    return (1, b) if b is not None else (0, 0)
