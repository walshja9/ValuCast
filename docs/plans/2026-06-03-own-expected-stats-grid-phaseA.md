# Our Own Expected Stats (EV×LA Grid) — Phase A Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build our own empirical EV×LA expected-stats grid from raw Statcast batted balls, compute our own xBA/xSLG per player-season, and prove (corr ≥ 0.95 + calibration) that it reproduces Savant's stored xBA/xSLG — the faithfulness gate before the expensive Phase B.

**Architecture:** A resumable/throttled batted-ball pull (`batted_balls.py`) feeds an empirical 2D EV×LA grid (`expected_stats_grid.py`) with sparse-cell fallback; scoring sums per-ball `p_hit`/`e_bases` over a player's balls divided by full AB (missing-EV imputed at the global rate). A faithfulness harness (`grid_faithfulness.py`) joins our values to Savant's stored snapshots and reports corr (gate) + calibration (slope/intercept/bias) over a qualified population (AB≥200, BIP≥50).

**Tech Stack:** Python 3.x, stdlib only (`urllib`, `csv`, `io`, `json`, `statistics`, `time`), `unittest`. No ML deps — the grid is plain dicts.

**Spec:** `docs/specs/2026-06-03-own-expected-stats-grid-phaseA-design.md`

**Test command:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_X.py" -v` (`tests/` has no `__init__.py`). Full suite: `... discover -s tests` (baseline **533**, must stay green; additive).

---

## File Structure

**Create:**
- `projections/data/batted_balls.py` — Savant `statcast_search` CSV: parse + resumable/throttled chunked pull
- `projections/models/expected_stats_grid.py` — bin keys, grid fit, sparse-cell fallback, scoring, store/load
- `projections/backtest/grid_faithfulness.py` — our-vs-Savant corr + calibration over the qualified population
- Tests for each under `tests/`

**No modifications to existing files.** Phase A is purely additive and behavior-neutral.

---

## Task 1: Batted-ball CSV parsing (pure, no network)

**Files:**
- Create: `projections/data/batted_balls.py`
- Test: `tests/test_batted_balls_parse.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.data.batted_balls import parse_batted_balls


CSV = (
    "game_date,launch_speed,launch_angle,events,type,batter,bb_type\n"
    "2023-04-02,98.5,12,single,X,605141,line_drive\n"     # tracked BIP, hit
    "2023-04-02,81.0,-40,field_out,X,605141,ground_ball\n"  # tracked BIP, out
    "2023-04-02,,,strikeout,S,605141,\n"                    # not in play (type!=X) -> dropped
    "2023-04-02,,,field_out,X,592450,\n"                    # in play but MISSING EV -> kept
)


class TestBattedBallParse(unittest.TestCase):
    def test_keeps_only_balls_in_play(self):
        balls = parse_batted_balls(CSV)
        # 3 type=X rows kept; the strikeout (type=S) dropped.
        self.assertEqual(len(balls), 3)

    def test_fields_and_missing_ev(self):
        balls = parse_batted_balls(CSV)
        b0 = balls[0]
        self.assertEqual(b0["batter"], "605141")
        self.assertAlmostEqual(b0["ev"], 98.5)
        self.assertAlmostEqual(b0["la"], 12.0)
        self.assertEqual(b0["events"], "single")
        self.assertEqual(b0["game_year"], "2023")   # season tag for per-year grouping
        # Missing-EV in-play ball: ev/la None, retained (imputed later, not dropped).
        missing = [b for b in balls if b["ev"] is None]
        self.assertEqual(len(missing), 1)
        self.assertEqual(missing[0]["events"], "field_out")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_batted_balls_parse.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement (parsing portion)**

Create `projections/data/batted_balls.py`:

```python
"""Savant statcast_search batted-ball pull (Phase A). Per-ball EV/LA/outcome for
balls in play, keyed by batter (MLBAM id). Resumable, throttled, retrying."""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0"
SEARCH_URL = (
    "https://baseballsavant.mlb.com/statcast_search/csv?all=true&type=details"
    "&game_date_gt={start}&game_date_lt={end}"
)
THROTTLE_SECONDS = 2.0   # be polite to Savant between chunk requests


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_batted_balls(csv_text: str) -> list[dict]:
    """Rows with type=='X' (ball in play). EV/LA may be None (missing tracking).
    Returns {ev, la, events, batter}."""
    reader = csv.DictReader(io.StringIO(csv_text.lstrip("﻿")))
    out = []
    for row in reader:
        if row.get("type") != "X":   # only balls in play
            continue
        out.append({
            "ev": _to_float(row.get("launch_speed")),
            "la": _to_float(row.get("launch_angle")),
            "events": (row.get("events") or "").strip(),
            "batter": (row.get("batter") or "").strip(),
            "game_year": (row.get("game_date") or "")[:4],   # season tag for grouping
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_batted_balls_parse.py" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/data/batted_balls.py tests/test_batted_balls_parse.py
git commit -m "feat: parse Savant statcast_search batted balls (in-play only, missing-EV kept)"
```

---

## Task 2: Resumable chunked pull

**Files:**
- Modify: `projections/data/batted_balls.py` (append)
- Test: `tests/test_batted_balls_pull.py`

- [ ] **Step 1: Write the failing test**

```python
import tempfile
import unittest
from pathlib import Path

from projections.data import batted_balls as bb


class TestChunkedPull(unittest.TestCase):
    def test_date_chunks_5day_windows(self):
        chunks = bb.date_chunks("2023-04-01", "2023-04-12", days=5)
        # [01-05], [06-10], [11-12]
        self.assertEqual(chunks[0], ("2023-04-01", "2023-04-05"))
        self.assertEqual(chunks[1], ("2023-04-06", "2023-04-10"))
        self.assertEqual(chunks[-1], ("2023-04-11", "2023-04-12"))

    def test_pull_window_is_resumable(self):
        # Stub the per-chunk fetch; verify already-fetched chunks are skipped on re-run.
        calls = []

        def fake_fetch(start, end):
            calls.append((start, end))
            return [{"ev": 95.0, "la": 10.0, "events": "single", "batter": "1"}]

        with tempfile.TemporaryDirectory() as d:
            cache = Path(d) / "bb_cache"
            n1 = bb.pull_window("2023-04-01", "2023-04-10", cache, days=5, fetch=fake_fetch)
            self.assertEqual(n1, 2)            # 2 chunks fetched
            self.assertEqual(len(calls), 2)
            # Re-run: chunks already cached -> no new fetches, same count.
            n2 = bb.pull_window("2023-04-01", "2023-04-10", cache, days=5, fetch=fake_fetch)
            self.assertEqual(n2, 2)
            self.assertEqual(len(calls), 2)    # unchanged: resumable, idempotent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_batted_balls_pull.py" -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'date_chunks'`.

- [ ] **Step 3: Implement (append to `batted_balls.py`)**

```python
def date_chunks(start: str, end: str, days: int = 5) -> list[tuple[str, str]]:
    """Inclusive [start,end] split into <=`days`-wide (start,end) windows.
    Sized under Savant's ~25k-row response cap."""
    from datetime import date, timedelta
    y1, m1, d1 = (int(x) for x in start.split("-"))
    y2, m2, d2 = (int(x) for x in end.split("-"))
    cur, last = date(y1, m1, d1), date(y2, m2, d2)
    out = []
    while cur <= last:
        chunk_end = min(cur + timedelta(days=days - 1), last)
        out.append((cur.isoformat(), chunk_end.isoformat()))
        cur = chunk_end + timedelta(days=1)
    return out


def _fetch_chunk(start: str, end: str) -> list[dict]:
    req = Request(SEARCH_URL.format(start=start, end=end), headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=120) as resp:
        return parse_batted_balls(resp.read().decode("utf-8-sig", "replace"))


def pull_window(start: str, end: str, cache_dir: Path, days: int = 5,
                fetch=_fetch_chunk, max_retries: int = 3) -> int:
    """Pull all balls-in-play for [start,end] in chunks, caching each chunk to disk.
    Resumable: cached chunks are skipped. Throttled + retried. Returns chunk count."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    chunks = date_chunks(start, end, days)
    for cstart, cend in chunks:
        path = cache_dir / f"{cstart}_{cend}.json"
        if path.exists():
            continue                       # resumable: already fetched
        last_err = None
        for attempt in range(max_retries):
            try:
                balls = fetch(cstart, cend)
                path.write_text(json.dumps(balls), encoding="utf-8")
                if fetch is _fetch_chunk:
                    time.sleep(THROTTLE_SECONDS)   # only throttle real network
                break
            except Exception as e:         # network/parse failure on this chunk
                last_err = e
                if fetch is _fetch_chunk:
                    time.sleep(THROTTLE_SECONDS * (attempt + 1))
        else:
            raise RuntimeError(f"chunk {cstart}..{cend} failed after {max_retries}: {last_err}")
    return len(chunks)


def load_cached_balls(cache_dir: Path) -> list[dict]:
    """Concatenate all cached chunk files into one ball list."""
    balls = []
    for path in sorted(cache_dir.glob("*.json")):
        balls.extend(json.loads(path.read_text(encoding="utf-8")))
    return balls
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_batted_balls_pull.py" -v`
Expected: PASS (2 tests). The `fetch is _fetch_chunk` guard means the stubbed fetch never sleeps.

- [ ] **Step 5: Commit**

```bash
git add projections/data/batted_balls.py tests/test_batted_balls_pull.py
git commit -m "feat: resumable/throttled/retrying chunked batted-ball pull"
```

---

## Task 3: Grid bin keys + outcome mapping

**Files:**
- Create: `projections/models/expected_stats_grid.py`
- Test: `tests/test_expected_stats_grid.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.models.expected_stats_grid import cell_key, outcome_bases, EV_BIN, LA_BIN


class TestGridKeysAndOutcomes(unittest.TestCase):
    def test_cell_key_bins(self):
        # EV 2mph bins, LA 5deg bins -> floor to bin edge.
        self.assertEqual(cell_key(98.7, 12.0), (98, 10))   # 98.7->98 (2mph), 12->10 (5deg)
        self.assertEqual(cell_key(81.0, -41.0), (80, -45))

    def test_outcome_bases_and_hit(self):
        # (is_hit, total_bases)
        self.assertEqual(outcome_bases("single"), (1, 1))
        self.assertEqual(outcome_bases("double"), (1, 2))
        self.assertEqual(outcome_bases("triple"), (1, 3))
        self.assertEqual(outcome_bases("home_run"), (1, 4))
        self.assertEqual(outcome_bases("field_out"), (0, 0))
        self.assertEqual(outcome_bases("field_error"), (0, 0))   # reached on error: not a hit
        self.assertEqual(outcome_bases("sac_fly"), (0, 0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_expected_stats_grid.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement (start `expected_stats_grid.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_expected_stats_grid.py" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/models/expected_stats_grid.py tests/test_expected_stats_grid.py
git commit -m "feat: EV x LA grid bin keys + hit/total-base outcome mapping"
```

---

## Task 4: Fit the grid + sparse-cell fallback lookup

**Files:**
- Modify: `projections/models/expected_stats_grid.py` (append)
- Test: `tests/test_expected_stats_grid.py` (append)

- [ ] **Step 1: Write the failing test**

```python
from projections.models.expected_stats_grid import fit_grid, lookup


class TestGridFit(unittest.TestCase):
    def _balls(self):
        # Dense "barrel" cell (100mph/12deg): mostly hits. Dense weak-grounder cell
        # (66mph/-30deg): mostly outs. Enough samples to clear MIN_CELL_SAMPLE.
        balls = []
        for _ in range(80):
            balls.append({"ev": 100.0, "la": 12.0, "events": "home_run"})
        for _ in range(20):
            balls.append({"ev": 100.0, "la": 12.0, "events": "field_out"})
        for _ in range(90):
            balls.append({"ev": 66.0, "la": -30.0, "events": "field_out"})
        for _ in range(10):
            balls.append({"ev": 66.0, "la": -30.0, "events": "single"})
        return balls

    def test_dense_cells_reflect_outcomes(self):
        grid = fit_grid(self._balls())
        hot = lookup(grid, 100.0, 12.0)
        cold = lookup(grid, 66.0, -30.0)
        self.assertAlmostEqual(hot["p_hit"], 0.80, places=2)      # 80/100
        self.assertAlmostEqual(hot["e_bases"], 3.20, places=2)    # 80*4 /100
        self.assertAlmostEqual(cold["p_hit"], 0.10, places=2)     # 10/100
        self.assertLess(cold["p_hit"], hot["p_hit"])

    def test_sparse_cell_falls_back_to_global(self):
        grid = fit_grid(self._balls())
        # A never-observed cell (120mph / 60deg) -> global rate, not a crash/zero-div.
        out = lookup(grid, 120.0, 60.0)
        total_hits = 90  # 80 + 10
        self.assertAlmostEqual(out["p_hit"], total_hits / 200, places=3)  # global p_hit

    def test_missing_ev_uses_global(self):
        grid = fit_grid(self._balls())
        out = lookup(grid, None, None)   # missing-EV ball -> global fallback
        self.assertAlmostEqual(out["p_hit"], 90 / 200, places=3)

    def test_store_grid_immutable(self):
        import tempfile
        from pathlib import Path
        from projections.models.expected_stats_grid import store_grid, load_grid
        grid = fit_grid(self._balls())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "grid.json"
            store_grid(grid, p)
            store_grid(grid, p)                       # identical -> no-op
            self.assertEqual(load_grid(p)["global"], grid["global"])
            changed = fit_grid(self._balls() + [{"ev": 105.0, "la": 20.0, "events": "home_run"}])
            with self.assertRaises(ValueError):
                store_grid(changed, p)                # changed content -> raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_expected_stats_grid.py" -v`
Expected: FAIL — `ImportError: cannot import name 'fit_grid'`.

- [ ] **Step 3: Implement (append to `expected_stats_grid.py`)**

```python
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
    # cells keyed by tuple -> JSON-safe "ev,la" strings.
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_expected_stats_grid.py" -v`
Expected: PASS (existing 2 + 3 new).

- [ ] **Step 5: Commit**

```bash
git add projections/models/expected_stats_grid.py tests/test_expected_stats_grid.py
git commit -m "feat: fit EV x LA grid + sparse-cell/missing-EV fallback to global"
```

---

## Task 5: Score players → our xBA / xSLG (full-AB denominator)

**Files:**
- Modify: `projections/models/expected_stats_grid.py` (append)
- Test: `tests/test_expected_stats_grid.py` (append)

- [ ] **Step 1: Write the failing test**

```python
from projections.models.expected_stats_grid import score_player


class TestScorePlayer(unittest.TestCase):
    def test_our_xba_xslg_full_ab_denominator(self):
        # Tiny hand grid: one hot cell (p_hit .8, e_bases 3.2), global p_hit .5/e_bases 1.0.
        grid = {"cells": {(100, 10): {"n": 100, "hits": 80, "bases": 320}},
                "global": {"p_hit": 0.5, "e_bases": 1.0}, "ev_bin": 2, "la_bin": 5}
        balls = [
            {"ev": 100.0, "la": 12.0, "events": "home_run"},  # hot cell -> .8 / 3.2
            {"ev": 100.0, "la": 12.0, "events": "field_out"}, # hot cell -> .8 / 3.2
            {"ev": None, "la": None, "events": "field_out"},  # missing-EV -> global .5 / 1.0
        ]
        # AB=4 (includes a strikeout not represented as a ball) -> full-AB denominator.
        res = score_player(grid, balls, ab=4)
        # expected hits = .8 + .8 + .5 = 2.1 ; xBA = 2.1/4 = 0.525
        self.assertAlmostEqual(res["our_xba"], 2.1 / 4, places=4)
        # expected bases = 3.2 + 3.2 + 1.0 = 7.4 ; xSLG = 7.4/4 = 1.85
        self.assertAlmostEqual(res["our_xslg"], 7.4 / 4, places=4)
        self.assertEqual(res["tracked_bip"], 3)
        self.assertAlmostEqual(res["missing_ev_coverage"], 1/3, places=4)

    def test_zero_ab_safe(self):
        grid = {"cells": {}, "global": {"p_hit": 0.5, "e_bases": 1.0}, "ev_bin": 2, "la_bin": 5}
        res = score_player(grid, [], ab=0)
        self.assertEqual(res["our_xba"], 0.0)
        self.assertEqual(res["our_xslg"], 0.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_expected_stats_grid.py" -v`
Expected: FAIL — `ImportError: cannot import name 'score_player'`.

- [ ] **Step 3: Implement (append to `expected_stats_grid.py`)**

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_expected_stats_grid.py" -v`
Expected: PASS (existing 5 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add projections/models/expected_stats_grid.py tests/test_expected_stats_grid.py
git commit -m "feat: score players -> our xBA/xSLG (full-AB denominator, missing-EV imputed)"
```

---

## Task 6: Faithfulness harness — corr (gate) + calibration

**Files:**
- Create: `projections/backtest/grid_faithfulness.py`
- Test: `tests/test_grid_faithfulness.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.backtest.grid_faithfulness import correlation, calibration


class TestFaithfulnessMetrics(unittest.TestCase):
    def test_correlation_perfect(self):
        self.assertAlmostEqual(correlation([0.2, 0.3, 0.4], [0.2, 0.3, 0.4]), 1.0)

    def test_calibration_detects_affine_bias(self):
        # ours = 0.5*savant + 0.1  -> corr is perfect but slope .5 / intercept .1 / +bias.
        savant = [0.20, 0.30, 0.40]
        ours = [0.5 * s + 0.1 for s in savant]   # [0.20, 0.25, 0.30]
        cal = calibration(ours, savant)
        self.assertAlmostEqual(correlation(ours, savant), 1.0, places=6)  # corr hides it
        self.assertAlmostEqual(cal["slope"], 0.5, places=3)               # calibration catches it
        self.assertAlmostEqual(cal["intercept"], 0.1, places=3)
        # mean signed error (ours - savant) = mean([0,-.05,-.10]) = -0.05
        self.assertAlmostEqual(cal["mean_signed_error"], -0.05, places=3)
        self.assertAlmostEqual(cal["mae"], 0.05, places=3)

    def test_report_fails_loud_on_tiny_population(self):
        from projections.backtest.grid_faithfulness import faithfulness_report
        tiny = [{"our_xba": 0.25, "our_xslg": 0.45,
                 "savant_xba": 0.25, "savant_xslg": 0.45}] * 5  # 5 << MIN_QUALIFIED_PAIRS
        with self.assertRaises(ValueError):
            faithfulness_report(tiny)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_grid_faithfulness.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `projections/backtest/grid_faithfulness.py`:

```python
"""Faithfulness of our grid xBA/xSLG vs Savant's stored values: correlation (gate)
plus calibration (slope/intercept/bias) — corr alone can't catch an affine bias."""
from __future__ import annotations

from collections.abc import Sequence
from statistics import mean, pstdev

MIN_AB = 200            # qualified-population AB floor
MIN_TRACKED_BIP = 50    # qualified-population batted-ball floor
MIN_QUALIFIED_PAIRS = 100  # below this, joins likely failed -> fail loud, not a fake SHORTFALL


def correlation(xs: Sequence[float], ys: Sequence[float]) -> float:
    sx, sy = pstdev(xs), pstdev(ys)
    if sx == 0 or sy == 0:
        return 0.0
    mx, my = mean(xs), mean(ys)
    return mean((a - mx) * (b - my) for a, b in zip(xs, ys)) / (sx * sy)


def calibration(ours: Sequence[float], savant: Sequence[float]) -> dict:
    """Regress ours on savant -> slope/intercept; plus mean signed error + MAE.
    Clean calibration ~ slope 1, intercept 0, bias 0."""
    n = len(ours)
    ms, mo = mean(savant), mean(ours)
    var_s = sum((s - ms) ** 2 for s in savant)
    slope = sum((s - ms) * (o - mo) for s, o in zip(savant, ours)) / var_s if var_s else 0.0
    intercept = mo - slope * ms
    signed = [o - s for o, s in zip(ours, savant)]
    return {
        "slope": slope, "intercept": intercept,
        "mean_signed_error": sum(signed) / n if n else 0.0,
        "mae": sum(abs(x) for x in signed) / n if n else 0.0,
        "n": n,
    }


def qualified(ab: int, tracked_bip: int) -> bool:
    return ab >= MIN_AB and tracked_bip >= MIN_TRACKED_BIP


def faithfulness_report(paired: list[dict]) -> dict:
    """paired: [{our_xba, our_xslg, savant_xba, savant_xslg}] for the QUALIFIED pop.
    Returns corr (gate) + calibration for xBA and xSLG.
    Fails loud below MIN_QUALIFIED_PAIRS: a join failure that pairs ~0 rows must NOT
    silently emit a fake SHORTFALL."""
    if len(paired) < MIN_QUALIFIED_PAIRS:
        raise ValueError(
            f"insufficient qualified pairs: {len(paired)} < {MIN_QUALIFIED_PAIRS} "
            "(likely a join/data failure, not a real faithfulness shortfall)."
        )
    out = {"n": len(paired)}
    for stat in ("xba", "xslg"):
        ours = [p[f"our_{stat}"] for p in paired]
        sav = [p[f"savant_{stat}"] for p in paired]
        corr = correlation(ours, sav)
        out[stat] = {"corr": corr, "passes_gate": corr >= 0.95, **calibration(ours, sav)}
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_grid_faithfulness.py" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/backtest/grid_faithfulness.py tests/test_grid_faithfulness.py
git commit -m "feat: faithfulness metrics — corr gate + calibration (catches affine bias)"
```

---

## Task 7: The pull + grid + verdict (manual) + full-suite regression

**Files:** data — `projections/data/batted_balls_cache/` (raw chunk cache, gitignored), `projections/data/expected_grid_2021_2023.json` (committed artifact)

- [ ] **Step 1: Full-suite regression first**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests`
Expected: all green (533 baseline + new Phase A tests).

- [ ] **Step 2: gitignore the raw chunk cache (do NOT commit ~375k raw balls)**

Append to `.gitignore`:
```
projections/data/batted_balls_cache/
```
Commit:
```bash
git add .gitignore && git commit -m "chore: gitignore raw batted-ball chunk cache"
```

- [ ] **Step 3: Endpoint smoke (one small chunk) — BEFORE the full pull**

Verify Savant's params/schema before filling the cache with junk. Fetch one 5-day 2023 chunk and assert it parses non-empty in-play balls with the fields we need:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from projections.data.batted_balls import _fetch_chunk
balls = _fetch_chunk('2023-07-01', '2023-07-05')
assert len(balls) > 200, f'too few balls: {len(balls)} (schema/params changed?)'
assert all(set(b) >= {'ev','la','events','batter','game_year'} for b in balls), 'missing fields'
assert any(b['ev'] is not None for b in balls), 'no EV values (tracking columns changed?)'
assert all(b['game_year']=='2023' for b in balls), 'game_year not parsed'
print('smoke OK:', len(balls), 'in-play balls; EV present; fields intact')
"
```
Expected: a few hundred in-play balls, fields intact. **If this fails, STOP** — Savant changed params/schema; fix the parser/URL before pulling 150 chunks of junk.

- [ ] **Step 4: Pull 2021–2023 batted balls (network, throttled, resumable)**

Run (several minutes; resumable if interrupted — just re-run):
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.batted_balls import pull_window, load_cached_balls
cache = Path('projections/data/batted_balls_cache')
for yr in (2021, 2022, 2023):
    pull_window(f'{yr}-03-01', f'{yr}-11-15', cache)
    print('pulled through', yr, flush=True)
balls = load_cached_balls(cache)
print('total balls in play:', len(balls))
print('missing-EV share:', round(sum(1 for b in balls if b['ev'] is None)/len(balls), 4))
"
```
Expected: ~375k balls, missing-EV share low (~1–3%). If a chunk fails, re-run — cached chunks are skipped.

- [ ] **Step 5: Fit + store the grid, then run the faithfulness verdict**

Balls carry `game_year` (Task 1), so per player-season grouping is clean. Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.batted_balls import load_cached_balls
from projections.data.historical import load_season            # hitter AB per player-season
from projections.data.statcast import load_statcast_season     # Savant xBA/xSLG (stored)
from projections.models.expected_stats_grid import fit_grid, store_grid, load_grid, score_player
from projections.backtest.grid_faithfulness import faithfulness_report, qualified
d = Path('projections/data')
balls = load_cached_balls(d / 'batted_balls_cache')
grid = fit_grid(balls)
store_grid(grid, d / 'expected_grid_2021_2023.json')

# AB per (mlbam_id, year) from the hitting backbone; Savant xBA/xSLG from snapshots.
ab_by = {}; sav_by = {}
for yr in (2021, 2022, 2023):
    ab_by[yr] = {r['mlbam_id']: r['AB'] for r in load_season(yr, d)}
    sav_by[yr] = load_statcast_season(yr, d)

by = {}
for b in balls:
    yr = b.get('game_year')
    if yr and yr.isdigit():
        by.setdefault((b['batter'], int(yr)), []).append(b)

paired = []
for (pid, yr), pball in by.items():
    ab = ab_by.get(yr, {}).get(pid, 0)
    sc = sav_by.get(yr, {}).get(pid)
    if not sc or sc.get('xba') is None:
        continue
    res = score_player(grid, pball, ab)
    if not qualified(ab, res['tracked_bip']):
        continue
    paired.append({'our_xba': res['our_xba'], 'our_xslg': res['our_xslg'],
                   'savant_xba': sc['xba'], 'savant_xslg': sc['xslg']})

rep = faithfulness_report(paired)
print('qualified player-seasons:', rep['n'])
for stat in ('xba', 'xslg'):
    s = rep[stat]
    print(f\"{stat}: corr {s['corr']:.4f} passes {s['passes_gate']} | slope {s['slope']:.3f} intercept {s['intercept']:.3f} bias {s['mean_signed_error']:+.4f} mae {s['mae']:.4f}\")
print('VERDICT:', 'WIN' if rep['xba']['passes_gate'] and rep['xslg']['passes_gate'] else 'SHORTFALL')
"
```
Expected — one of:
- **WIN:** corr ≥ 0.95 for xBA and xSLG. Report calibration: clean (slope≈1, intercept≈0, small bias) → ready for Phase B as-is; or biased → Phase B applies an affine calibration layer. Either way we've reproduced xBA from our own calculation.
- **SHORTFALL:** corr < 0.95 → EV+LA alone isn't enough; the residual (sprint-speed-dependent) is the finding. Report plainly, do not lower the bar.

- [ ] **Step 6: Commit the grid artifact + verdict**

```bash
git add projections/data/expected_grid_2021_2023.json docs/plans/2026-06-03-own-expected-stats-grid-phaseA.md
git commit -m "data+docs: our EV x LA expected-stats grid 2021-2023 + Phase A verdict <WIN|SHORTFALL>"
```
(Add a `VERDICT` header + Execution Verdict section to this plan first, mirroring prior rungs.)

---

## Self-Review (completed during authoring)

- **Spec coverage:** resumable/throttled/retrying pull (T2); EV×LA empirical grid + sparse-cell fallback (T3, T4); missing-EV excluded-from-fit-but-imputed-at-global, full-AB denominator, missing_ev_coverage (T4, T5); corr-led gate + calibration (slope/intercept/bias) catching affine bias (T6); qualified population AB≥200 & BIP≥50 (T6 `qualified`, T5 verdict); grid stored as immutable artifact, raw balls gitignored not committed (T4, T7); honest WIN/SHORTFALL (T7). Sprint-speed residual is characterized in the verdict notes. All spec sections map to a task.
- **Placeholder scan:** no TBD/TODO; every code step is complete. The one flagged item is the per-season `game_year` on parsed balls — called out explicitly in T7 Step 4's note as a one-line parser addition the implementer must make so balls group by `(batter, season)`. **Fix forward:** add `"game_year": (row.get("game_date") or "")[:4]` to `parse_batted_balls`'s output dict in Task 1 and include `game_date` is in the CSV (it is). Implementer: include this in Task 1.
- **Type consistency:** `parse_batted_balls -> [{ev,la,events,batter(,game_year)}]` consumed by `pull_window`/`fit_grid`/`score_player`. `fit_grid -> {cells,global,ev_bin,la_bin}` consumed by `lookup`/`score_player`/`store_grid`/`load_grid`. `score_player -> {our_xba,our_xslg,tracked_bip,missing_ev_coverage}` consumed in the T7 verdict + `qualified(ab,tracked_bip)`. `faithfulness_report(paired)` expects `{our_xba,our_xslg,savant_xba,savant_xslg}`. Savant snapshot keys `xba`/`xslg` and hitter row `AB`/`mlbam_id` match the existing backbones.
