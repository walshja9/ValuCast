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


def fit_grid(balls: Sequence[dict]) -> dict:
    """Build the grid from balls (each {ev, la, events}). Missing-EV balls are
    EXCLUDED from the fit (can't bin), but counted into the global fallback rate."""
    cells: dict[tuple[int, int], dict] = {}
    g_n = g_hits = g_bases = 0
    for b in balls:
        is_hit, bases = outcome_bases(b["events"])
        g_n += 1; g_hits += is_hit; g_bases += bases
        if b["ev"] is None or b["la"] is None:
            continue                       # excluded from binned fit
        k = cell_key(b["ev"], b["la"])
        c = cells.setdefault(k, {"n": 0, "hits": 0, "bases": 0})
        c["n"] += 1; c["hits"] += is_hit; c["bases"] += bases
    g = {"p_hit": g_hits / g_n if g_n else 0.0,
         "e_bases": g_bases / g_n if g_n else 0.0}
    return {"cells": cells, "global": g, "ev_bin": EV_BIN, "la_bin": LA_BIN}


def _neighbor_pool(cells: dict, k: tuple[int, int]) -> dict | None:
    """Pool the 8 immediate EV/LA neighbors; None if their combined sample is thin."""
    ev0, la0 = k
    n = hits = bases = 0
    for dev in (-EV_BIN, 0, EV_BIN):
        for dla in (-LA_BIN, 0, LA_BIN):
            c = cells.get((ev0 + dev, la0 + dla))
            if c:
                n += c["n"]; hits += c["hits"]; bases += c["bases"]
    if n < MIN_CELL_SAMPLE:
        return None
    return {"p_hit": hits / n, "e_bases": bases / n}


def lookup(grid: dict, ev: float | None, la: float | None) -> dict:
    """p_hit / e_bases for a ball. Missing-EV or sparse cell -> fallback chain:
    cell -> neighbor pool -> global."""
    if ev is None or la is None:
        return dict(grid["global"])
    k = cell_key(ev, la)
    c = grid["cells"].get(k)
    if c and c["n"] >= MIN_CELL_SAMPLE:
        return {"p_hit": c["hits"] / c["n"], "e_bases": c["bases"] / c["n"]}
    pooled = _neighbor_pool(grid["cells"], k)
    if pooled is not None:
        return pooled
    return dict(grid["global"])


def store_grid(grid: dict, path: Path) -> None:
    """Immutable artifact: identical re-write is a no-op; changed content raises
    (compare parsed JSON, not raw text — Windows newline-safe, same contract as the
    other backbones)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serial = {"global": grid["global"], "ev_bin": grid["ev_bin"], "la_bin": grid["la_bin"],
              "cells": {f"{k[0]},{k[1]}": v for k, v in grid["cells"].items()}}
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) == serial:
            return
        raise ValueError(f"Refusing to overwrite grid artifact {path.name}: content changed.")
    path.write_text(json.dumps(serial, indent=2, sort_keys=True), encoding="utf-8")


def load_grid(path: Path) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cells = {tuple(int(x) for x in key.split(",")): v for key, v in raw["cells"].items()}
    return {"cells": cells, "global": raw["global"],
            "ev_bin": raw["ev_bin"], "la_bin": raw["la_bin"]}


def score_player(grid: dict, balls: Sequence[dict], ab: int) -> dict:
    """our_xBA = sum(p_hit over the player's BIP) / AB ; our_xSLG = sum(e_bases)/AB.
    Full-AB denominator (matches Savant: strikeouts/outs in AB contribute 0).
    Missing-EV balls are imputed at the grid's global rate (lookup handles it)."""
    exp_hits = exp_bases = 0.0
    missing = 0
    for b in balls:
        if b["ev"] is None or b["la"] is None:
            missing += 1
        cell = lookup(grid, b["ev"], b["la"])
        exp_hits += cell["p_hit"]
        exp_bases += cell["e_bases"]
    n = len(balls)
    return {
        "our_xba": exp_hits / ab if ab > 0 else 0.0,
        "our_xslg": exp_bases / ab if ab > 0 else 0.0,
        "tracked_bip": n,
        "missing_ev_coverage": missing / n if n else 0.0,
    }
