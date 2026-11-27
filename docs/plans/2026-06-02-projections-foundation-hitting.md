# Projections Foundation + Marcel Hitting Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ValuCast generate its own Marcel-style hitter projections, validated by a leakage-safe backtest harness, and value them through the existing engine alongside Steamer.

**Architecture:** A new `projections/` package (data backbone + models + backtest + export) sits beside `scraper/`. It reuses the existing MLB Stats API helpers, emits engine-native `PlayerProjection` rows, and is wired into the web layer through a minimal `ProjectionCatalog` source seam. Steamer stays the default; Marcel is an additional, archivable source.

**Tech Stack:** Python 3.x, stdlib only (`urllib`, `json`, `hashlib`, `pathlib`, `statistics`), `unittest`. Engine/web reuse: `league_values.engine.ValuationEngine`, `web.projection_store.ProjectionStore`, `scraper.mlb_actuals`.

**Spec:** `docs/specs/2026-06-02-projections-foundation-hitting-design.md`

**Test command (all tasks):**
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest <module> -v
```
Full suite: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v` (must stay green; baseline 428).

---

## File Structure

**Create:**
- `projections/__init__.py` — package marker
- `projections/constants.py` — shared stat-key tuples + floors
- `projections/data/__init__.py`
- `projections/data/identity.py` — birth-date crosswalk + age
- `projections/data/historical.py` — immutable season snapshots + manifest
- `projections/models/__init__.py`
- `projections/models/marcel_params.py` — `MarcelParams` (the tunable knobs)
- `projections/models/league_rates.py` — leakage-safe league-average rates
- `projections/models/marcel_hitter.py` — the projector (component invariants live here)
- `projections/export/__init__.py`
- `projections/export/marcel_run.py` — assemble + archive a run
- `projections/backtest/__init__.py`
- `projections/backtest/scorecard.py` — metrics
- `projections/backtest/harness.py` — rolling-origin replay
- `projections/backtest/tune.py` — leakage-safe grid search (disjoint tune/score blocks)
- `web/projection_catalog.py` — source seam
- Tests mirror each module under `tests/`.

**Modify:**
- `scraper/combine.py:52,90` — carry `sources` through matched players (P2 fix)

---

## Task 1: P2 — provenance carried through `combine.py`

**Files:**
- Modify: `scraper/combine.py:52-61`, `scraper/combine.py:90-99`
- Test: `tests/test_combine.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_combine.py`:

```python
    def test_matched_player_carries_sources(self):
        from scraper.combine import combine_outlook
        ros = [{
            "id": "mlbam_5_H", "name": "Test Bat", "pool": "hitter",
            "positions": ["1B"], "team": "NYY",
            "stats": {"PA": 100, "AB": 90, "H": 30, "HR": 5, "1B": 20,
                      "2B": 4, "3B": 1, "R": 15, "RBI": 18, "SB": 2, "CS": 1,
                      "BB": 8, "SO": 20, "HBP": 1, "SF": 1, "G": 25},
            "metadata": {"mlbam_id": "5"},
            "sources": ["steamer"],
        }]
        actual = [{
            "id": "mlbam_5_H", "name": "Test Bat", "pool": "hitter",
            "stats": {"PA": 50, "AB": 45, "H": 15, "HR": 2, "1B": 10,
                      "2B": 2, "3B": 1, "R": 7, "RBI": 9, "SB": 1, "CS": 0,
                      "BB": 4, "SO": 10, "HBP": 0, "SF": 1, "G": 12},
            "metadata": {"mlbam_id": "5"},
        }]
        out = combine_outlook(ros, actual)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["sources"], ["steamer"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_combine.py" -v`
Expected: FAIL — `KeyError: 'sources'` (matched dict has no `sources`).

- [ ] **Step 3: Implement minimal fix**

In `scraper/combine.py`, the matched-player return in `_combine_hitter` (currently ending at line 61) — add a `sources` key:

```python
    return {
        "id": ros["id"],
        "name": ros["name"],
        "pool": ros["pool"],
        "positions": ros.get("positions", []),
        "team": ros.get("team", ""),
        "stats": {k: round(v, 4) if isinstance(v, float) else int(v)
                  for k, v in combined_stats.items()},
        "metadata": meta,
        "sources": list(ros.get("sources", [])),
    }
```

Apply the identical `"sources": list(ros.get("sources", [])),` line to the `_combine_pitcher` return (currently ending at line 99).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_combine.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scraper/combine.py tests/test_combine.py
git commit -m "fix: carry sources through matched players in combine (P2 provenance)"
```

---

## Task 2: Package skeleton + shared constants

**Files:**
- Create: `projections/__init__.py`, `projections/constants.py`, `projections/data/__init__.py`, `projections/models/__init__.py`, `projections/export/__init__.py`, `projections/backtest/__init__.py`
- Test: `tests/test_projections_constants.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.constants import (
    PROJECTED_RATES, AGE_ADJUSTED_RATES, MIN_EVAL_PA, HEADLINE_STATS,
)


class TestProjectionsConstants(unittest.TestCase):
    def test_age_adjusted_is_subset_of_projected(self):
        self.assertTrue(set(AGE_ADJUSTED_RATES).issubset(set(PROJECTED_RATES)))

    def test_age_adjusted_excludes_lower_is_better(self):
        for stat in ("SO", "CS", "SF"):
            self.assertNotIn(stat, AGE_ADJUSTED_RATES)

    def test_floor_and_headline(self):
        self.assertEqual(MIN_EVAL_PA, 200)
        self.assertIn("OPS", HEADLINE_STATS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_projections_constants.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'projections'`.

- [ ] **Step 3: Create the package files**

Each `__init__.py` is empty. Create `projections/constants.py`:

```python
"""Shared stat-key contracts for the projection layer."""
from __future__ import annotations

# Per-PA rate components Marcel projects. AB and H are DERIVED, not projected.
PROJECTED_RATES: tuple[str, ...] = (
    "1B", "2B", "3B", "HR", "BB", "HBP", "SF", "SO", "SB", "CS", "R", "RBI",
)

# Only production-skill rates receive the age multiplier. SO/CS/SF must NOT,
# or an aging decline would quietly help lower-is-better categories.
AGE_ADJUSTED_RATES: tuple[str, ...] = (
    "1B", "2B", "3B", "HR", "BB", "HBP", "SB",
)

# Counting stats stored in each historical snapshot row.
HISTORICAL_COUNTING: tuple[str, ...] = (
    "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI",
    "SB", "CS", "BB", "SO", "HBP", "SF",
)

# Categories the backtest scores (mixed-scale; never sum raw MAE across them).
HEADLINE_STATS: tuple[str, ...] = (
    "PA", "HR", "R", "RBI", "SB", "AVG", "OBP", "SLG", "OPS",
)

PEAK_AGE = 29
MIN_EVAL_PA = 200  # qualified actual-PA floor for backtest eval population
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_projections_constants.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/ tests/test_projections_constants.py
git commit -m "feat: projections package skeleton + shared stat constants"
```

---

## Task 3: Marcel tunable parameters

**Files:**
- Create: `projections/models/marcel_params.py`
- Test: `tests/test_marcel_params.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.models.marcel_params import MarcelParams


class TestMarcelParams(unittest.TestCase):
    def test_defaults_match_classic_marcel(self):
        p = MarcelParams()
        self.assertEqual(p.season_weights, (5.0, 4.0, 3.0))
        self.assertEqual(p.n_reg, 1200.0)
        self.assertAlmostEqual(p.k_young, 0.006)
        self.assertAlmostEqual(p.k_old, 0.003)
        self.assertEqual((p.pa_w1, p.pa_w2, p.pa_base), (0.5, 0.1, 200.0))

    def test_is_frozen(self):
        p = MarcelParams()
        with self.assertRaises(Exception):
            p.n_reg = 5.0  # type: ignore
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_params.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/models/marcel_params.py`:

```python
"""Tunable Marcel constants. Defaults reproduce classic Marcel; the harness
tunes them — that is where we beat textbook Marcel."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarcelParams:
    season_weights: tuple[float, ...] = (5.0, 4.0, 3.0)  # newest first
    n_reg: float = 1200.0          # PA of league-average added for regression
    k_young: float = 0.006         # per-year uplift below peak age
    k_old: float = 0.003           # per-year decline above peak age
    pa_w1: float = 0.5             # weight on PA[T-1]
    pa_w2: float = 0.1             # weight on PA[T-2]
    pa_base: float = 200.0         # baseline PA added
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_params.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/models/marcel_params.py tests/test_marcel_params.py
git commit -m "feat: MarcelParams tunable knobs (defaults = classic Marcel)"
```

---

## Task 4: Leakage-safe league rates

**Files:**
- Create: `projections/models/league_rates.py`
- Test: `tests/test_league_rates.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.models.league_rates import compute_league_rates


class TestLeagueRates(unittest.TestCase):
    def test_weighted_per_pa_rate(self):
        # Two prior seasons, weights 5 then 4. One season-snapshot is a list of
        # player rows. Player below the PA floor is excluded.
        snap_t1 = [
            {"PA": 100, "HR": 10, "BB": 10, "1B": 20, "2B": 0, "3B": 0,
             "HBP": 0, "SF": 0, "SO": 0, "SB": 0, "CS": 0, "R": 0, "RBI": 0},
            {"PA": 5, "HR": 5, "BB": 0, "1B": 0, "2B": 0, "3B": 0,
             "HBP": 0, "SF": 0, "SO": 0, "SB": 0, "CS": 0, "R": 0, "RBI": 0},
        ]
        snap_t2 = [
            {"PA": 100, "HR": 0, "BB": 20, "1B": 20, "2B": 0, "3B": 0,
             "HBP": 0, "SF": 0, "SO": 0, "SB": 0, "CS": 0, "R": 0, "RBI": 0},
        ]
        rates = compute_league_rates(
            [snap_t1, snap_t2], weights=(5.0, 4.0), pa_floor=10,
        )
        # HR: weighted total = 5*10 + 4*0 = 50 ; weighted PA = 5*100 + 4*100 = 900
        self.assertAlmostEqual(rates["HR"], 50 / 900)
        # BB: weighted total = 5*10 + 4*20 = 130 ; / 900
        self.assertAlmostEqual(rates["BB"], 130 / 900)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_league_rates.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/models/league_rates.py`:

```python
"""League-average per-PA component rates, computed ONLY from pre-target
seasons (leakage-safe)."""
from __future__ import annotations

from collections.abc import Sequence

from projections.constants import PROJECTED_RATES


def compute_league_rates(
    prior_snapshots: Sequence[Sequence[dict]],
    weights: Sequence[float],
    pa_floor: float,
) -> dict[str, float]:
    """prior_snapshots newest-first; weights aligned to it.

    Returns {component: weighted league total / weighted league PA}.
    """
    totals = {c: 0.0 for c in PROJECTED_RATES}
    pa_total = 0.0
    for snap, w in zip(prior_snapshots, weights):
        for row in snap:
            if float(row.get("PA", 0)) < pa_floor:
                continue
            pa_total += w * float(row.get("PA", 0))
            for c in PROJECTED_RATES:
                totals[c] += w * float(row.get(c, 0))
    if pa_total <= 0:
        return {c: 0.0 for c in PROJECTED_RATES}
    return {c: totals[c] / pa_total for c in PROJECTED_RATES}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_league_rates.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/models/league_rates.py tests/test_league_rates.py
git commit -m "feat: leakage-safe weighted league-average rates"
```

---

## Task 5: Marcel hitter projector + component invariants

**Files:**
- Create: `projections/models/marcel_hitter.py`
- Test: `tests/test_marcel_hitter.py`

- [ ] **Step 1: Write the failing test (hand-computed)**

The example is rigged so league rates equal the player's rates (regression is identity) and `age == PEAK_AGE` (age_mult = 1.0), isolating the PA-projection + composition + invariants math.

```python
import unittest
from projections.models.marcel_hitter import project_hitter
from projections.models.marcel_params import MarcelParams


class TestMarcelHitter(unittest.TestCase):
    def setUp(self):
        # One prior season, PA=500.
        self.prior = [{
            "PA": 500, "AB": 450, "H": 125, "1B": 100, "2B": 0, "3B": 0,
            "HR": 25, "R": 80, "RBI": 70, "SB": 0, "CS": 0,
            "BB": 50, "SO": 100, "HBP": 0, "SF": 0,
        }]
        # League rates == player's per-PA rates -> regression leaves rates intact.
        self.league = {
            "1B": 100 / 500, "2B": 0.0, "3B": 0.0, "HR": 25 / 500,
            "BB": 50 / 500, "HBP": 0.0, "SF": 0.0, "SO": 100 / 500,
            "SB": 0.0, "CS": 0.0, "R": 80 / 500, "RBI": 70 / 500,
        }

    def test_pa_projection_and_composition(self):
        out = project_hitter(self.prior, self.league, age=29, params=MarcelParams())
        # PA_proj = 0.5*500 + 0.1*0 + 200 = 450
        self.assertAlmostEqual(out["PA"], 450.0)
        # HR = (25/500) * 450 = 22.5  (age_mult = 1.0)
        self.assertAlmostEqual(out["HR"], 22.5)
        # BB = (50/500)*450 = 45 ; AB = 450 - 45 - 0 - 0 = 405
        self.assertAlmostEqual(out["AB"], 405.0)
        # 1B = 90 ; H = 90 + 0 + 0 + 22.5 = 112.5
        self.assertAlmostEqual(out["H"], 112.5)
        # TB = 90 + 4*22.5 = 180 ; SLG = 180/405
        self.assertAlmostEqual(out["TB"], 180.0)
        self.assertAlmostEqual(out["SLG"], round(180 / 405, 3))
        # SO is NOT age-adjusted: (100/500)*450 = 90
        self.assertAlmostEqual(out["SO"], 90.0)

    def test_age_decline_only_touches_production(self):
        young = project_hitter(self.prior, self.league, age=29, params=MarcelParams())
        old = project_hitter(self.prior, self.league, age=39, params=MarcelParams())
        self.assertLess(old["HR"], young["HR"])      # production declines
        self.assertAlmostEqual(old["SO"], young["SO"])  # SO unchanged by age

    def test_counts_clamped_nonnegative(self):
        out = project_hitter(self.prior, self.league, age=120, params=MarcelParams())
        for key in ("HR", "1B", "BB", "AB", "H"):
            self.assertGreaterEqual(out[key], 0.0)

    def test_missing_t1_uses_t2_offset_weight_and_pa(self):
        # Offset-aligned: index 0 = T-1 (missing), index 1 = T-2 (present).
        out = project_hitter([None, self.prior[0]], self.league, age=29, params=MarcelParams())
        # T-2 carries its offset weight (4), not T-1's. PA_proj = 0.5*0 + 0.1*500 + 200 = 250.
        self.assertAlmostEqual(out["PA"], 250.0)
        # Regression is identity here, so HR = (25/500) * 250 = 12.5.
        self.assertAlmostEqual(out["HR"], 12.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_hitter.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/models/marcel_hitter.py`:

```python
"""Marcel-style hitter projector. Projects per-PA component rates, then
composes counting stats under strict invariants (see spec §4)."""
from __future__ import annotations

from collections.abc import Sequence

from projections.constants import (
    AGE_ADJUSTED_RATES, PEAK_AGE, PROJECTED_RATES,
)
from projections.models.marcel_params import MarcelParams


def _age_mult(age: int | None, params: MarcelParams) -> float:
    if age is None:
        return 1.0
    if age < PEAK_AGE:
        return 1.0 + params.k_young * (PEAK_AGE - age)
    return 1.0 + params.k_old * (PEAK_AGE - age)  # (PEAK-age) negative -> decline


def project_hitter(
    prior_seasons: Sequence[dict | None],
    league_rates: dict[str, float],
    age: int | None,
    params: MarcelParams,
) -> dict:
    """prior_seasons is OFFSET-ALIGNED: index 0 = season T-1, 1 = T-2, 2 = T-3.
    A missing season is None and KEEPS its slot, so each present season gets the
    weight and PA role of its true offset (a player who missed T-1 but played T-2
    must not get T-1's weight). Returns a full stat dict."""
    pairs = [
        (s, w) for s, w in zip(prior_seasons, params.season_weights) if s is not None
    ]

    weighted_pa = sum(w * float(s.get("PA", 0)) for s, w in pairs)
    regressed: dict[str, float] = {}
    for c in PROJECTED_RATES:
        wtot = sum(w * float(s.get(c, 0)) for s, w in pairs)
        regressed[c] = (wtot + params.n_reg * league_rates.get(c, 0.0)) / (
            weighted_pa + params.n_reg
        )

    def _pa(i: int) -> float:
        if i < len(prior_seasons) and prior_seasons[i] is not None:
            return float(prior_seasons[i].get("PA", 0))
        return 0.0

    pa_proj = params.pa_w1 * _pa(0) + params.pa_w2 * _pa(1) + params.pa_base

    mult = _age_mult(age, params)
    counts: dict[str, float] = {}
    for c in PROJECTED_RATES:
        v = regressed[c] * pa_proj
        if c in AGE_ADJUSTED_RATES:
            v *= mult
        counts[c] = max(0.0, v)

    bb, hbp, sf = counts["BB"], counts["HBP"], counts["SF"]
    ab = max(0.0, pa_proj - bb - hbp - sf)
    h = counts["1B"] + counts["2B"] + counts["3B"] + counts["HR"]
    tb = counts["1B"] + 2 * counts["2B"] + 3 * counts["3B"] + 4 * counts["HR"]
    nsb = counts["SB"] - counts["CS"]

    pa_denom = ab + bb + hbp + sf
    avg = round(h / ab, 3) if ab > 0 else 0.0
    obp = round((h + bb + hbp) / pa_denom, 3) if pa_denom > 0 else 0.0
    slg = round(tb / ab, 3) if ab > 0 else 0.0

    out = dict(counts)
    out.update({
        "PA": pa_proj, "AB": ab, "H": h, "TB": tb, "NSB": nsb,
        "AVG": avg, "OBP": obp, "SLG": slg, "OPS": round(obp + slg, 3),
    })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_hitter.py" -v`
Expected: PASS (all three tests).

- [ ] **Step 5: Commit**

```bash
git add projections/models/marcel_hitter.py tests/test_marcel_hitter.py
git commit -m "feat: Marcel hitter projector with component invariants"
```

---

## Task 6: Player identity / age crosswalk

**Files:**
- Create: `projections/data/identity.py`
- Test: `tests/test_identity.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.data.identity import age_for, parse_people_payload


class TestIdentity(unittest.TestCase):
    def test_age_as_of_april_first(self):
        # Born 1995-06-01 -> as of 2026-04-01 has NOT had 2026 birthday: age 30.
        self.assertEqual(age_for("1995-06-01", 2026), 30)
        # Born 1995-03-01 -> already had birthday by Apr 1: age 31.
        self.assertEqual(age_for("1995-03-01", 2026), 31)

    def test_missing_birthdate_returns_none(self):
        self.assertIsNone(age_for("", 2026))
        self.assertIsNone(age_for(None, 2026))

    def test_parse_people_payload(self):
        payload = {"people": [
            {"id": 660271, "fullName": "X", "birthDate": "1994-07-05",
             "batSide": {"code": "L"}, "pitchHand": {"code": "R"}},
        ]}
        out = parse_people_payload(payload)
        self.assertEqual(out["660271"]["birth_date"], "1994-07-05")
        self.assertEqual(out["660271"]["bats"], "L")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_identity.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/data/identity.py`:

```python
"""Player identity / age crosswalk from MLB Stats API /people."""
from __future__ import annotations

from datetime import date

from scraper.mlb_actuals import MLB_API_BASE, _fetch_json

REFERENCE_MONTH_DAY = (4, 1)  # age computed as of April 1 of the projection season


def age_for(birth_date: str | None, season: int) -> int | None:
    """Age as of April 1 of `season`. None if birth_date missing/unparseable."""
    if not birth_date:
        return None
    try:
        y, m, d = (int(x) for x in birth_date.split("-"))
    except (ValueError, AttributeError):
        return None
    ref = date(season, *REFERENCE_MONTH_DAY)
    age = ref.year - y - ((ref.month, ref.day) < (m, d))
    return age


def parse_people_payload(payload: dict) -> dict[str, dict]:
    """Convert an MLB /people response into {mlbam_id: identity record}."""
    out: dict[str, dict] = {}
    for person in payload.get("people", []):
        out[str(person["id"])] = {
            "mlbam_id": str(person["id"]),
            "name": person.get("fullName", ""),
            "birth_date": person.get("birthDate", ""),
            "bats": person.get("batSide", {}).get("code", ""),
            "throws": person.get("pitchHand", {}).get("code", ""),
        }
    return out


def fetch_identities(mlbam_ids: list[str]) -> dict[str, dict]:
    """Batch-fetch identity records. Chunks ids to keep URLs sane."""
    result: dict[str, dict] = {}
    for i in range(0, len(mlbam_ids), 100):
        chunk = mlbam_ids[i : i + 100]
        url = f"{MLB_API_BASE}/people?personIds={','.join(chunk)}"
        result.update(parse_people_payload(_fetch_json(url)))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_identity.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/data/identity.py tests/test_identity.py
git commit -m "feat: player identity/age crosswalk (April-1 age, /people batch fetch)"
```

---

## Task 7: Immutable historical backbone + manifest

**Files:**
- Create: `projections/data/historical.py`
- Test: `tests/test_historical.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import tempfile
import unittest
from pathlib import Path

from projections.data.historical import (
    normalize_season_rows, store_season, load_season, content_hash,
)


class TestHistorical(unittest.TestCase):
    def test_normalize_keeps_only_counting_keys(self):
        raw_player = {
            "id": "mlbam_5_H", "name": "Bat", "pool": "hitter",
            "stats": {"PA": 100, "AB": 90, "H": 30, "1B": 20, "2B": 5,
                      "3B": 1, "HR": 4, "R": 15, "RBI": 18, "SB": 2, "CS": 1,
                      "BB": 8, "SO": 20, "HBP": 1, "SF": 1, "G": 25,
                      "AVG": 0.333, "OPS": 0.9},
            "metadata": {"mlbam_id": "5"},
        }
        rows = normalize_season_rows([raw_player])
        self.assertEqual(rows[0]["mlbam_id"], "5")
        self.assertEqual(rows[0]["HR"], 4)
        self.assertNotIn("AVG", rows[0])   # rates not stored

    def test_store_is_immutable_noop_on_identical_repull(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            rows = [{"mlbam_id": "5", "season": 2020, "PA": 100, "HR": 4}]
            store_season(2020, rows, data_dir)
            first = content_hash(data_dir / "historical" / "hitting_2020.json")
            store_season(2020, rows, data_dir)  # identical re-pull
            second = content_hash(data_dir / "historical" / "hitting_2020.json")
            self.assertEqual(first, second)
            self.assertEqual(load_season(2020, data_dir), rows)

    def test_store_raises_on_changed_finalized_season(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store_season(2020, [{"mlbam_id": "5", "season": 2020, "HR": 4}], data_dir)
            with self.assertRaises(ValueError):
                store_season(2020, [{"mlbam_id": "5", "season": 2020, "HR": 99}], data_dir)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_historical.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/data/historical.py`:

```python
"""Immutable historical season snapshots (hitting) + manifest."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from projections.constants import HISTORICAL_COUNTING
from scraper.mlb_actuals import fetch_actuals, normalize_hitter

SCHEMA_VERSION = 1


def normalize_season_rows(players: list[dict]) -> list[dict]:
    """Reduce engine-schema hitter dicts to bare counting rows keyed by mlbam_id."""
    rows = []
    for p in players:
        if p.get("pool") != "hitter":
            continue
        stats = p.get("stats", {})
        row = {"mlbam_id": p["metadata"]["mlbam_id"]}
        for key in HISTORICAL_COUNTING:
            row[key] = int(stats.get(key, 0))
        rows.append(row)
    return rows


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _season_path(season: int, data_dir: Path) -> Path:
    return data_dir / "historical" / f"hitting_{season}.json"


def store_season(season: int, rows: list[dict], data_dir: Path) -> None:
    """Write a season snapshot immutably. Identical re-pull is a no-op;
    a changed finalized season raises."""
    path = _season_path(season, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rows, indent=2, sort_keys=True)
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() == hashlib.sha256(
            payload.encode("utf-8")
        ).hexdigest():
            return  # identical -> no-op
        raise ValueError(
            f"Refusing to overwrite finalized season {season}: content changed."
        )
    path.write_text(payload, encoding="utf-8")
    _update_manifest(season, rows, data_dir)


def _update_manifest(season: int, rows: list[dict], data_dir: Path) -> None:
    manifest_path = data_dir / "manifest.json"
    manifest = {}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[str(season)] = {
        "season": season,
        "row_count": len(rows),
        "schema_version": SCHEMA_VERSION,
        "content_sha256": hashlib.sha256(
            json.dumps(rows, indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def load_season(season: int, data_dir: Path) -> list[dict]:
    return json.loads(_season_path(season, data_dir).read_text(encoding="utf-8"))


def pull_season(season: int, data_dir: Path) -> int:
    """Fetch one season from MLB Stats API, normalize, store. Returns row count."""
    raw = fetch_actuals(season)
    players = [normalize_hitter(e, as_of=f"{season}-final") for e in raw["hitters"]]
    rows = normalize_season_rows(players)
    for r in rows:
        r["season"] = season
    store_season(season, rows, data_dir)
    return len(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_historical.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/data/historical.py tests/test_historical.py
git commit -m "feat: immutable historical hitting snapshots + manifest"
```

- [ ] **Step 6: One-time data pull (manual, not a test)**

Run (network; ~16 calls):
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.historical import pull_season
d = Path('projections/data')
for yr in range(2010, 2026):
    print(yr, pull_season(yr, d))
"
```
Expected: a row count printed per season (≈600–900 hitters each), files under `projections/data/historical/`.

```bash
git add projections/data/historical/ projections/data/manifest.json
git commit -m "data: historical hitting snapshots 2010-2025"
```

---

## Task 8: Marcel run assembly + export to PlayerProjection rows

**Files:**
- Create: `projections/export/marcel_run.py`
- Test: `tests/test_marcel_run.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import tempfile
import unittest
from pathlib import Path

from projections.data.historical import store_season
from projections.export.marcel_run import build_marcel_projections, write_run
from projections.models.marcel_params import MarcelParams


class TestMarcelRun(unittest.TestCase):
    def _seed(self, data_dir):
        for yr in (2021, 2022, 2023):
            store_season(yr, [{
                "mlbam_id": "5", "season": yr, "PA": 500, "AB": 450, "H": 125,
                "1B": 100, "2B": 0, "3B": 0, "HR": 25, "R": 80, "RBI": 70,
                "SB": 0, "CS": 0, "BB": 50, "SO": 100, "HBP": 0, "SF": 0,
            }], data_dir)

    def test_build_emits_engine_shaped_rows(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed(data_dir)
            rows = build_marcel_projections(
                2024, data_dir, MarcelParams(),
                identities={"5": {"name": "Test Bat", "birth_date": "1995-06-01"}},
            )
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual(r["id"], "mlbam_5_H")
            self.assertEqual(r["name"], "Test Bat")        # identity wired through
            self.assertEqual(r["pool"], "hitter")
            self.assertEqual(r["metadata"]["source"], "marcel")
            self.assertEqual(r["metadata"]["model"], "valucast_marcel")
            self.assertEqual(r["metadata"]["as_of_season"], 2024)
            self.assertFalse(r["metadata"]["age_unknown"])
            self.assertIn("HR", r["stats"])
            self.assertIn("OPS", r["stats"])

    def test_write_run_is_self_describing(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            runs_dir = data_dir / "runs"
            self._seed(data_dir)
            rows = build_marcel_projections(
                2024, data_dir, MarcelParams(),
                identities={"5": {"name": "Test Bat", "birth_date": "1995-06-01"}},
            )
            run_id = write_run(rows, runs_dir, model="marcel", as_of_season=2024, version=1)
            self.assertEqual(run_id, "marcel_2024_v1")
            run_path = runs_dir / run_id
            self.assertTrue((run_path / "projections.json").exists())
            manifest = json.loads((run_path / "run_manifest.json").read_text())
            self.assertEqual(manifest["as_of_season"], 2024)
            self.assertEqual(manifest["row_count"], 1)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_run.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/export/marcel_run.py`:

```python
"""Assemble a Marcel hitting run and archive it immutably."""
from __future__ import annotations

import json
from pathlib import Path

from projections.constants import MIN_EVAL_PA
from projections.data.historical import load_season
from projections.data.identity import age_for
from projections.models.league_rates import compute_league_rates
from projections.models.marcel_hitter import project_hitter
from projections.models.marcel_params import MarcelParams

# Engine-native export contract: every stats dict carries these keys.
EXPORT_KEYS = (
    "PA", "AB", "H", "1B", "2B", "3B", "HR", "R", "RBI", "SB", "CS",
    "BB", "SO", "HBP", "SF", "TB", "NSB", "AVG", "OBP", "SLG", "OPS",
)


def build_marcel_projections(
    target_season: int,
    data_dir: Path,
    params: MarcelParams,
    identities: dict[str, dict],
) -> list[dict]:
    """Project all hitters with >=1 prior season, using data < target_season.

    `identities` maps mlbam_id -> {name, birth_date, ...}; it supplies real
    names and the per-target-season age (age_for resolves age as of season T).
    """
    prior_years = [target_season - 1, target_season - 2, target_season - 3]
    snaps: list[list[dict]] = []
    for yr in prior_years:
        try:
            snaps.append(load_season(yr, data_dir))
        except FileNotFoundError:
            snaps.append([])

    weights = params.season_weights[: len(snaps)]
    league = compute_league_rates(snaps, weights=weights, pa_floor=MIN_EVAL_PA)

    # Offset-aligned priors: index 0 = T-1, 1 = T-2, 2 = T-3. Missing = None,
    # so weights/PA roles stay pinned to the correct year (see project_hitter).
    index_maps = [{r["mlbam_id"]: r for r in snap} for snap in snaps]
    all_ids = {pid for m in index_maps for pid in m}

    rows: list[dict] = []
    for mlbam_id in all_ids:
        prior_seasons = [m.get(mlbam_id) for m in index_maps]
        if all(s is None for s in prior_seasons):
            continue
        ident = identities.get(mlbam_id, {})
        age = age_for(ident.get("birth_date"), target_season)
        proj = project_hitter(prior_seasons, league, age, params)
        stats = {k: round(float(proj.get(k, 0.0)), 4) for k in EXPORT_KEYS}
        rows.append({
            "id": f"mlbam_{mlbam_id}_H",
            "name": ident.get("name") or mlbam_id,
            "pool": "hitter",
            "positions": [],
            "stats": stats,
            "sources": ["marcel"],
            "metadata": {
                "mlbam_id": mlbam_id,
                "base_id": f"mlbam_{mlbam_id}",
                "source": "marcel",
                "model": "valucast_marcel",
                "model_version": 1,
                "as_of_season": target_season,
                "age_unknown": age is None,
            },
        })
    return rows


def write_run(
    rows: list[dict],
    runs_dir: Path,
    model: str,
    as_of_season: int,
    version: int,
) -> str:
    run_id = f"{model}_{as_of_season}_v{version}"
    run_path = runs_dir / run_id
    run_path.mkdir(parents=True, exist_ok=True)
    (run_path / "projections.json").write_text(
        json.dumps(rows, indent=2), encoding="utf-8"
    )
    (run_path / "run_manifest.json").write_text(
        json.dumps({
            "run_id": run_id,
            "model": model,
            "model_version": version,
            "as_of_season": as_of_season,
            "row_count": len(rows),
        }, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return run_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_run.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/export/marcel_run.py tests/test_marcel_run.py
git commit -m "feat: assemble + archive a Marcel hitting run (engine-native export)"
```

---

## Task 9: Scorecard metrics

**Files:**
- Create: `projections/backtest/scorecard.py`
- Test: `tests/test_scorecard.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.backtest.scorecard import mae, rmse, correlation, normalized_ratio


class TestScorecard(unittest.TestCase):
    def test_mae_rmse(self):
        self.assertAlmostEqual(mae([1, 2, 3], [1, 2, 5]), 2 / 3)
        self.assertAlmostEqual(rmse([1, 2, 3], [1, 2, 5]), (4 / 3) ** 0.5)

    def test_correlation_perfect(self):
        self.assertAlmostEqual(correlation([1, 2, 3], [2, 4, 6]), 1.0)

    def test_correlation_degenerate_returns_zero(self):
        self.assertEqual(correlation([5, 5, 5], [1, 2, 3]), 0.0)

    def test_normalized_ratio(self):
        # marcel mae 1.0 vs persistence mae 2.0 -> 0.5 (good, <1)
        self.assertAlmostEqual(normalized_ratio(1.0, 2.0), 0.5)
        self.assertEqual(normalized_ratio(1.0, 0.0), float("inf"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_scorecard.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/backtest/scorecard.py`:

```python
"""Backtest metrics. Mixed-scale stats are never summed as raw MAE; compare
via normalized error ratio vs a baseline."""
from __future__ import annotations

from collections.abc import Sequence
from statistics import mean, pstdev


def mae(pred: Sequence[float], actual: Sequence[float]) -> float:
    return mean(abs(p - a) for p, a in zip(pred, actual))


def rmse(pred: Sequence[float], actual: Sequence[float]) -> float:
    return (mean((p - a) ** 2 for p, a in zip(pred, actual))) ** 0.5


def correlation(pred: Sequence[float], actual: Sequence[float]) -> float:
    sp, sa = pstdev(pred), pstdev(actual)
    if sp == 0 or sa == 0:
        return 0.0
    mp, ma = mean(pred), mean(actual)
    cov = mean((p - mp) * (a - ma) for p, a in zip(pred, actual))
    return cov / (sp * sa)


def normalized_ratio(model_mae: float, baseline_mae: float) -> float:
    """<1.0 means the model beats the baseline on this stat."""
    if baseline_mae == 0:
        return float("inf") if model_mae > 0 else 0.0
    return model_mae / baseline_mae
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_scorecard.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/backtest/scorecard.py tests/test_scorecard.py
git commit -m "feat: backtest scorecard metrics (mae/rmse/corr/normalized ratio)"
```

---

## Task 10: Rolling-origin backtest harness

**Files:**
- Create: `projections/backtest/harness.py`
- Test: `tests/test_harness.py`

- [ ] **Step 1: Write the failing test**

```python
import tempfile
import unittest
from pathlib import Path

from projections.data.historical import store_season
from projections.backtest.harness import backtest_season
from projections.models.marcel_params import MarcelParams


class TestHarness(unittest.TestCase):
    def test_backtest_season_scores_eval_population(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            # Player 5: 3 priors + a qualified actual in target year.
            for yr in (2020, 2021, 2022, 2023):
                store_season(yr, [{
                    "mlbam_id": "5", "season": yr, "PA": 500, "AB": 450,
                    "H": 125, "1B": 100, "2B": 0, "3B": 0, "HR": 25,
                    "R": 80, "RBI": 70, "SB": 0, "CS": 0, "BB": 50,
                    "SO": 100, "HBP": 0, "SF": 0,
                }], data_dir)
            result = backtest_season(
                2023, data_dir, MarcelParams(),
                identities={"5": {"birth_date": "1994-01-01"}},
            )
            self.assertEqual(result["eval_n"], 1)
            self.assertIn("marcel_mae", result["per_stat"]["HR"])
            self.assertIn("persistence_mae", result["per_stat"]["HR"])
            self.assertIn("marcel_rmse", result["per_stat"]["HR"])

    def test_low_pa_player_excluded_from_eval(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2020, 2021, 2022):
                store_season(yr, [{"mlbam_id": "9", "season": yr, "PA": 500,
                    "AB": 450, "H": 125, "1B": 100, "2B": 0, "3B": 0, "HR": 25,
                    "R": 80, "RBI": 70, "SB": 0, "CS": 0, "BB": 50, "SO": 100,
                    "HBP": 0, "SF": 0}], data_dir)
            # target-year actual below MIN_EVAL_PA -> excluded
            store_season(2023, [{"mlbam_id": "9", "season": 2023, "PA": 50,
                "AB": 45, "H": 12, "1B": 10, "2B": 0, "3B": 0, "HR": 2,
                "R": 8, "RBI": 9, "SB": 0, "CS": 0, "BB": 5, "SO": 10,
                "HBP": 0, "SF": 0}], data_dir)
            result = backtest_season(
                2023, data_dir, MarcelParams(),
                identities={"9": {"birth_date": "1994-01-01"}},
            )
            self.assertEqual(result["eval_n"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_harness.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/backtest/harness.py`:

```python
"""Rolling-origin backtest: project season T from data < T, score vs actuals
on the qualified eval population. Compares Marcel against a persistence
baseline (T-1 = T)."""
from __future__ import annotations

from pathlib import Path

from projections.constants import HEADLINE_STATS, MIN_EVAL_PA
from projections.data.historical import load_season
from projections.export.marcel_run import build_marcel_projections
from projections.backtest.scorecard import correlation, mae, normalized_ratio, rmse
from projections.models.marcel_params import MarcelParams


def _rates(row: dict) -> dict:
    pa = float(row.get("PA", 0))
    ab = float(row.get("AB", 0))
    h = float(row.get("H", 0))
    bb, hbp, sf = (float(row.get(k, 0)) for k in ("BB", "HBP", "SF"))
    tb = (float(row.get("1B", 0)) + 2 * float(row.get("2B", 0))
          + 3 * float(row.get("3B", 0)) + 4 * float(row.get("HR", 0)))
    denom = ab + bb + hbp + sf
    avg = h / ab if ab > 0 else 0.0
    obp = (h + bb + hbp) / denom if denom > 0 else 0.0
    slg = tb / ab if ab > 0 else 0.0
    return {**row, "AVG": avg, "OBP": obp, "SLG": slg, "OPS": obp + slg}


def backtest_season(
    target_season: int,
    data_dir: Path,
    params: MarcelParams,
    identities: dict[str, dict],
) -> dict:
    actual_rows = {r["mlbam_id"]: _rates(r) for r in load_season(target_season, data_dir)}
    try:
        prev_rows = {r["mlbam_id"]: _rates(r)
                     for r in load_season(target_season - 1, data_dir)}
    except FileNotFoundError:
        prev_rows = {}

    marcel = {r["metadata"]["mlbam_id"]: r["stats"]
              for r in build_marcel_projections(target_season, data_dir, params, identities)}

    # Eval population: qualified actual PA AND projectable AND has persistence baseline.
    eval_ids = [
        pid for pid, a in actual_rows.items()
        if a.get("PA", 0) >= MIN_EVAL_PA and pid in marcel and pid in prev_rows
    ]

    per_stat: dict[str, dict] = {}
    for stat in HEADLINE_STATS:
        if not eval_ids:
            per_stat[stat] = {}
            continue
        act = [actual_rows[pid][stat] for pid in eval_ids]
        mar = [marcel[pid].get(stat, 0.0) for pid in eval_ids]
        per = [prev_rows[pid].get(stat, 0.0) for pid in eval_ids]
        m_mae, p_mae = mae(mar, act), mae(per, act)
        per_stat[stat] = {
            "marcel_mae": m_mae,
            "persistence_mae": p_mae,
            "marcel_rmse": rmse(mar, act),
            "persistence_rmse": rmse(per, act),
            "mae_ratio": normalized_ratio(m_mae, p_mae),
            "marcel_corr": correlation(mar, act),
            "persistence_corr": correlation(per, act),
        }
    return {"target_season": target_season, "eval_n": len(eval_ids), "per_stat": per_stat}


def rolling_origin(
    target_seasons: list[int],
    data_dir: Path,
    params: MarcelParams,
    identities: dict[str, dict],
) -> dict:
    """Run backtest_season across many targets; aggregate the pass-bar verdict."""
    seasons = [backtest_season(t, data_dir, params, identities) for t in target_seasons]
    ratios, corr_wins, corr_total = [], 0, 0
    for s in seasons:
        for stat, m in s["per_stat"].items():
            if not m:
                continue
            ratios.append(m["mae_ratio"])
            corr_total += 1
            if m["marcel_corr"] > m["persistence_corr"]:
                corr_wins += 1
    mean_ratio = sum(ratios) / len(ratios) if ratios else float("inf")
    return {
        "seasons": seasons,
        "mean_mae_ratio": mean_ratio,
        "corr_win_rate": corr_wins / corr_total if corr_total else 0.0,
        "beats_persistence": mean_ratio < 1.0 and (corr_wins / corr_total if corr_total else 0) > 0.5,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_harness.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/backtest/harness.py tests/test_harness.py
git commit -m "feat: rolling-origin backtest harness vs persistence baseline"
```

- [ ] **Step 6: Smoke run on real data (harness wiring, not the pass bar)**

Confirms the harness runs end-to-end on the pulled snapshots and reports RMSE.
The actual v1 pass-bar verdict (tuned vs untuned vs persistence) is Task 11.

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.historical import load_season
from projections.data.identity import fetch_identities
from projections.backtest.harness import rolling_origin
from projections.models.marcel_params import MarcelParams
d = Path('projections/data')
ids = sorted({r['mlbam_id'] for yr in range(2010,2026) for r in load_season(yr, d)})
idents = fetch_identities(ids)   # age_for resolves per target season inside build
res = rolling_origin([2023, 2024, 2025], d, MarcelParams(), idents)
print('mean_mae_ratio', round(res['mean_mae_ratio'], 4))
print('eval_n by season', [(s['target_season'], s['eval_n']) for s in res['seasons']])
print('HR rmse (marcel vs persistence)',
      round(res['seasons'][0]['per_stat']['HR']['marcel_rmse'], 2),
      round(res['seasons'][0]['per_stat']['HR']['persistence_rmse'], 2))
"
```
Expected: non-trivial `eval_n` per season and finite metrics. Identities now carry per-target-season ages directly — no flat-age hack.

---

## Task 11: Leakage-safe parameter tuning (grid search)

The spec keeps tuning in v1 and requires tuning seasons be **provably disjoint**
from scored seasons. Design: grid-search params on an early block of targets,
lock the winner, then report the pass bar on a later, untouched block.

**Files:**
- Create: `projections/backtest/tune.py`
- Test: `tests/test_tune.py`

- [ ] **Step 1: Write the failing test**

```python
import tempfile
import unittest
from pathlib import Path

from projections.data.historical import store_season
from projections.backtest.tune import grid_search, default_grid
from projections.models.marcel_params import MarcelParams


def _row(pid, yr, hr):
    return {"mlbam_id": pid, "season": yr, "PA": 500, "AB": 450, "H": 125,
            "1B": 100, "2B": 0, "3B": 0, "HR": hr, "R": 80, "RBI": 70,
            "SB": 0, "CS": 0, "BB": 50, "SO": 100, "HBP": 0, "SF": 0}


class TestTune(unittest.TestCase):
    def test_grid_search_returns_best_params_and_score(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"},
                      "7": {"birth_date": "1990-01-01"}}
            grid = [MarcelParams(n_reg=600.0), MarcelParams(n_reg=1500.0)]
            best, score = grid_search([2022, 2023], data_dir, idents, grid)
            self.assertIn(best.n_reg, (600.0, 1500.0))
            self.assertIsInstance(score, float)

    def test_default_grid_is_nonempty_marcel_params(self):
        grid = default_grid()
        self.assertGreater(len(grid), 1)
        self.assertIsInstance(grid[0], MarcelParams)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_tune.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`projections/backtest/tune.py`:

```python
"""Leakage-safe Marcel tuning. Grid search scored ONLY on the seasons passed in
(callers must keep tuning seasons disjoint from the seasons they later score)."""
from __future__ import annotations

from pathlib import Path

from projections.backtest.harness import rolling_origin
from projections.models.marcel_params import MarcelParams


def default_grid() -> list[MarcelParams]:
    grid: list[MarcelParams] = []
    for n_reg in (600.0, 900.0, 1200.0, 1500.0):
        for pa_base in (150.0, 200.0, 250.0):
            grid.append(MarcelParams(n_reg=n_reg, pa_base=pa_base))
    return grid


def grid_search(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    grid: list[MarcelParams],
) -> tuple[MarcelParams, float]:
    """Return (best_params, best_mean_mae_ratio) over the tuning seasons."""
    best_params: MarcelParams | None = None
    best_score: float | None = None
    for params in grid:
        score = rolling_origin(tuning_seasons, data_dir, params, identities)["mean_mae_ratio"]
        if best_score is None or score < best_score:
            best_params, best_score = params, score
    return best_params, best_score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_tune.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add projections/backtest/tune.py tests/test_tune.py
git commit -m "feat: leakage-safe Marcel grid search"
```

- [ ] **Step 6: Real pass-bar verification (tuning block disjoint from scoring block)**

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.historical import load_season
from projections.data.identity import fetch_identities
from projections.backtest.harness import rolling_origin
from projections.backtest.tune import grid_search, default_grid
from projections.models.marcel_params import MarcelParams
d = Path('projections/data')
ids = sorted({r['mlbam_id'] for yr in range(2010,2026) for r in load_season(yr, d)})
idents = fetch_identities(ids)
tune_targets = list(range(2014, 2020))    # tuning block
score_targets = list(range(2020, 2026))   # held-out scoring block (disjoint)
best, _ = grid_search(tune_targets, d, idents, default_grid())
tuned = rolling_origin(score_targets, d, best, idents)
untuned = rolling_origin(score_targets, d, MarcelParams(), idents)
print('locked params: n_reg', best.n_reg, 'pa_base', best.pa_base)
print('TUNED   beats_persistence', tuned['beats_persistence'], 'ratio', round(tuned['mean_mae_ratio'], 4))
print('UNTUNED beats_persistence', untuned['beats_persistence'], 'ratio', round(untuned['mean_mae_ratio'], 4))
"
```
Expected (v1 success criterion #3): **`TUNED beats_persistence True`**, and `tuned ratio <= untuned ratio` (tuning helped or tied). If tuned does NOT beat persistence, that is a finding to investigate — report it, do not paper over it. The 2014–2019 tuning block never overlaps the 2020–2025 scoring block, so the result is leakage-free.

---

## Task 12: ProjectionCatalog source seam

**Files:**
- Create: `web/projection_catalog.py`
- Test: `tests/test_projection_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import tempfile
import unittest
from pathlib import Path

from web.projection_catalog import ProjectionCatalog


SAMPLE = [{
    "id": "mlbam_5_H", "name": "Bat", "pool": "hitter", "positions": ["1B"],
    "stats": {"PA": 450, "AB": 405, "H": 112, "HR": 22, "1B": 90, "2B": 0,
              "3B": 0, "R": 70, "RBI": 60, "SB": 0, "CS": 0, "BB": 45,
              "SO": 90, "HBP": 0, "SF": 0, "AVG": 0.277, "OBP": 0.349,
              "SLG": 0.444, "OPS": 0.793},
    "metadata": {"mlbam_id": "5", "source": "marcel"},
}]


class TestProjectionCatalog(unittest.TestCase):
    def test_default_source_is_steamer(self):
        cat = ProjectionCatalog(sources={"steamer": "a.json", "marcel": "b.json"})
        self.assertEqual(cat.default, "steamer")

    def test_store_for_loads_named_source(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "marcel.json"
            path.write_text(json.dumps(SAMPLE), encoding="utf-8")
            cat = ProjectionCatalog(sources={"marcel": str(path)})
            store = cat.store_for("marcel")
            self.assertEqual(store.player_count, 1)
            self.assertEqual(store.get_by_id("mlbam_5_H").name, "Bat")

    def test_unknown_source_raises(self):
        cat = ProjectionCatalog(sources={"steamer": "a.json"})
        with self.assertRaises(KeyError):
            cat.store_for("nope")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_projection_catalog.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`web/projection_catalog.py`:

```python
"""Named projection-source registry. Lets ValuCast value Steamer or Marcel
through the same engine. Default stays Steamer so current behavior is intact.
No UI — this is the seam a later spec exposes."""
from __future__ import annotations

from web.projection_store import ProjectionStore


class ProjectionCatalog:
    def __init__(self, sources: dict[str, str], default: str = "steamer") -> None:
        self._sources = dict(sources)
        self._default = default if default in self._sources else next(iter(self._sources))
        self._cache: dict[str, ProjectionStore] = {}

    @property
    def default(self) -> str:
        return self._default

    @property
    def names(self) -> list[str]:
        return list(self._sources)

    def store_for(self, source: str | None = None) -> ProjectionStore:
        name = source or self._default
        if name not in self._sources:
            raise KeyError(f"Unknown projection source: {name!r}")
        if name not in self._cache:
            self._cache[name] = ProjectionStore(self._sources[name])
        return self._cache[name]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_projection_catalog.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/projection_catalog.py tests/test_projection_catalog.py
git commit -m "feat: ProjectionCatalog source seam (steamer default, marcel selectable)"
```

---

## Task 13: End-to-end — engine values a Marcel run

**Files:**
- Test: `tests/test_projections_integration.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import tempfile
import unittest
from pathlib import Path

from league_values.engine import ValuationEngine
from league_values.post_processors import VolumeMultiplier
from league_values.presets import standard_5x5
from projections.data.historical import store_season
from projections.export.marcel_run import build_marcel_projections, write_run
from projections.models.marcel_params import MarcelParams
from web.projection_catalog import ProjectionCatalog


class TestProjectionsIntegration(unittest.TestCase):
    def test_engine_values_marcel_source_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2021, 2022, 2023):
                store_season(yr, [
                    {"mlbam_id": "5", "season": yr, "PA": 600, "AB": 540,
                     "H": 170, "1B": 110, "2B": 30, "3B": 2, "HR": 28,
                     "R": 95, "RBI": 92, "SB": 8, "CS": 2, "BB": 55,
                     "SO": 120, "HBP": 4, "SF": 5},
                    {"mlbam_id": "7", "season": yr, "PA": 580, "AB": 520,
                     "H": 140, "1B": 95, "2B": 25, "3B": 1, "HR": 19,
                     "R": 70, "RBI": 65, "SB": 15, "CS": 4, "BB": 50,
                     "SO": 110, "HBP": 3, "SF": 4},
                ], data_dir)
            rows = build_marcel_projections(
                2024, data_dir, MarcelParams(),
                identities={"5": {"name": "Bat Five", "birth_date": "1996-01-01"},
                            "7": {"name": "Bat Seven", "birth_date": "1993-01-01"}},
            )
            runs_dir = data_dir / "runs"
            run_id = write_run(rows, runs_dir, model="marcel", as_of_season=2024, version=1)

            cat = ProjectionCatalog(
                sources={"marcel": str(runs_dir / run_id / "projections.json")},
                default="marcel",
            )
            store = cat.store_for("marcel")
            engine = ValuationEngine(post_processors=[VolumeMultiplier()])
            results = engine.value_players(store.get_all(), standard_5x5())

            self.assertEqual(len(results), 2)
            # Engine produced finite values and a ranking.
            values = sorted((r.value for r in results), reverse=True)
            self.assertGreater(values[0], values[1])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_projections_integration.py" -v`
Expected: FAIL — initially `ModuleNotFoundError` for the not-yet-imported run/catalog modules if run out of order; once Tasks 8 & 12 are done it should pass without new code. If `ValuationResult` has no `.value` attribute, inspect `src/league_values/models.py` `ValuationResult` and use the correct ranked-value field name, then re-run.

- [ ] **Step 3: Make it pass**

No new production code expected — this wires existing pieces. If it fails on the value-field name, adjust the assertion to the actual attribute (do not change the engine).

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_projections_integration.py" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_projections_integration.py
git commit -m "test: engine values a Marcel run end-to-end via ProjectionCatalog"
```

---

## Task 14: Full-suite regression + spec sign-off

- [ ] **Step 1: Run the entire suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v`
Expected: all tests pass (baseline 428 + the new tests from this plan). Steamer path untouched → existing tests still green (success criterion #5).

- [ ] **Step 2: Confirm success criteria**

Walk the spec's Success Criteria section and confirm each:
1. Snapshots immutable + manifested (Task 7, re-pull no-op test).
2. Marcel math verified by hand example (Task 5).
3. Rolling-origin scorecard (MAE/RMSE/corr), **tuned** Marcel beats persistence on a held-out block disjoint from the tuning block (Task 11 Step 6 → `TUNED beats_persistence True`).
4. Engine values `source="marcel"` end-to-end (Task 13).
5. Steamer intact, 428 green, `sources` carried (Tasks 1 + 14 Step 1).

- [ ] **Step 3: Commit any final docs/notes**

```bash
git add -A
git commit -m "chore: projections foundation + Marcel hitting complete"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** identity wired into export (T6 + T8), normalized schema + immutable backbone + run archive (T7, T8), Marcel math + invariants + offset-aligned gap handling + leakage-safe league means (T4, T5), rolling-origin harness with MAE/RMSE/corr (T9, T10), leakage-safe tuning on a disjoint block (T11), full component export (T8 `EXPORT_KEYS`), source seam + naming discipline + P1 store-selector (T12), P2 provenance (T1). All spec sections map to a task.
- **Placeholder scan:** no TBD/TODO; every code step shows complete code; the one runtime unknown (`ValuationResult` value-field name) is flagged with an explicit fallback instruction rather than left vague.
- **Type consistency:** `MarcelParams` field names (`season_weights`, `n_reg`, `k_young`, `k_old`, `pa_w1/pa_w2/pa_base`) used identically in Tasks 3/5/8/10/11. `project_hitter` takes an **offset-aligned** `Sequence[dict | None]` in T5 and is fed offset-aligned lists in T8. `build_marcel_projections(target_season, data_dir, params, identities)` and `backtest_season(target_season, data_dir, params, identities)` both take `identities` (not `ages`) across T8/T10/T11/T13. `write_run(rows, runs_dir, model, as_of_season, version)` consistent across T8/T13. `store_season`/`load_season` consistent across T7/T8/T10/T11. `PROJECTED_RATES`/`AGE_ADJUSTED_RATES` defined once (T2), consumed everywhere.

---

## Execution Deltas (what shipped vs. this plan)

Recorded after inline execution on 2026-06-02. The plan above is the as-designed
spec; these are the deviations made during the build. All 14 tasks shipped; full
suite ended at **462 tests green** (428 baseline + 34 new).

**Preflight hardening (added before Task 9, at reviewer request):**
- **`write_run` made immutable.** Original Task 8 used `mkdir(exist_ok=True)` and
  could overwrite an archived run. Now an existing `run_id` is a no-op if contents
  are identical and raises if they differ (bump the version instead). Mirrors
  `store_season`. (`projections/export/marcel_run.py`, +1 test.)
- **`identity.json` persisted, not re-fetched.** Added `build_identity_store()` /
  `load_identity_store()` so identity is fetched once from the historical id union
  (4366 players, 100% birth dates) and stored as a fact; harness/tuning load it
  instead of hitting the network per run. (`projections/data/identity.py`, +2 tests.)
- **`content_hash` → `file_byte_hash`.** Renamed with a docstring clarifying it is
  a raw on-disk byte hash (platform-newline-dependent), distinct from the manifest's
  canonical-JSON `content_sha256`. (`projections/data/historical.py`.)

**Windows newline bug (found during Task 7):**
- `store_season`'s immutability check originally byte-hashed the on-disk file vs the
  in-memory payload. Text-mode writes translate `\n`→`\r\n` on Windows, so an
  identical re-pull falsely raised "content changed." Fixed to compare **parsed
  JSON content** — also the more correct definition of "finalized season changed."

**Tuning result (Task 11 Step 6):**
- Held-out verification (tune 2014–2019, score 2020–2025, disjoint) passed:
  `beats_persistence=True`, mean MAE ratio **0.7729**, correlation-win **94.4%**.
- The grid selected the **classic Marcel constants** (`n_reg=1200, pa_base=200`),
  so **tuned == untuned** — tuning tied rather than improved on textbook Marcel.
  Useful negative result: the 2-knob grid found no gain over Tango's constants.
  Real edge must come from a wider/finer grid (incl. `k_young/k_old`) or the
  Statcast inputs in later rungs — not from these two knobs.

**Other:**
- Plan test commands were corrected from `unittest tests.test_X` to
  `unittest discover -s tests -p "test_X.py"` — `tests/` has no `__init__.py`.
- `ValuationResult`'s ranked-value field is `total_value` (the T13 fallback note
  resolved here); the integration test asserts on `total_value`.
