# Projections Rung 2 — Reliability-Weighted Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Marcel's single global `n_reg` with per-component regression derived from each hitting component's empirical year-to-year reliability, and prove on held-out seasons whether it beats classic Marcel.

**Architecture:** A new `reliability.py` computes leakage-safe, harmonic-PA-weighted year-to-year rate correlations per component. `MarcelParams` gains one knob (`gamma`); `project_hitter` maps `(reliability, n_reg_base, gamma)` → per-component `n_reg_c` with `gamma=0` exactly reproducing Rung 1. The harness gains a classic-Marcel baseline metric and a tuning→scoring carryover guard; tuning uses coordinate descent over two knobs.

**Tech Stack:** Python 3.x, stdlib only (`math`, `statistics`, `glob`, `dataclasses.replace`), `unittest`. Reuses all Rung 1 modules under `projections/`.

**Spec:** `docs/specs/2026-06-02-projections-rung2-reliability-regression-design.md`

**Test command (all tasks):**
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_X.py" -v
```
(`tests/` has no `__init__.py` — must use `discover -p`, not `unittest tests.test_X`.)
Full suite: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests` (baseline 462, must stay green).

---

## File Structure

**Create:**
- `projections/models/reliability.py` — per-component reliability + clamp constants
- Tests for each new/changed module under `tests/`

**Modify:**
- `projections/models/marcel_params.py` — add `gamma` knob (keep `n_reg` working)
- `projections/models/marcel_hitter.py` — optional `reliability` arg → per-component `n_reg_c`
- `projections/data/historical.py` — `available_seasons()` helper
- `projections/export/marcel_run.py` — compute reliability per target, thread through
- `projections/backtest/harness.py` — `vs_classic()` baseline metric
- `projections/backtest/tune.py` — `coordinate_descent()` over `(n_reg_base, gamma)`

**Backward-compatibility invariant (verified in Task 4):** with `reliability=None` or `gamma=0`, every changed function reproduces Rung 1 output exactly, and the existing 462 tests stay green.

---

## Task 1: Reliability module (per-component year-to-year correlation)

**Files:**
- Create: `projections/models/reliability.py`
- Test: `tests/test_reliability.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.models.reliability import compute_reliability, R_FLOOR


def _row(pid, pa, hr, so):
    # Other components constant/zero so only HR and SO matter here.
    return {"mlbam_id": pid, "PA": pa, "HR": hr, "SO": so,
            "1B": 0, "2B": 0, "3B": 0, "BB": 0, "HBP": 0, "SF": 0,
            "SB": 0, "CS": 0, "R": 0, "RBI": 0}


class TestReliability(unittest.TestCase):
    def test_perfectly_correlated_component_is_high(self):
        # HR rate identical across the two seasons for all 3 players -> r = 1.0.
        s2020 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        s2021 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        rel = compute_reliability({2020: s2020, 2021: s2021}, pa_floor=100)
        self.assertAlmostEqual(rel["HR"], 1.0)

    def test_constant_component_floors(self):
        # SO rate is .2 for everyone both years -> zero variance -> r clamped to R_FLOOR.
        s2020 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        s2021 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        rel = compute_reliability({2020: s2020, 2021: s2021}, pa_floor=100)
        self.assertEqual(rel["SO"], R_FLOOR)

    def test_below_floor_pairs_excluded(self):
        # Player 2 below PA floor in 2021 -> only player 1 pairs; <2 points -> floored.
        s2020 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100)]
        s2021 = [_row("1", 500, 10, 100), _row("2", 50, 2, 10)]
        rel = compute_reliability({2020: s2020, 2021: s2021}, pa_floor=100)
        self.assertEqual(rel["HR"], R_FLOOR)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_reliability.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'projections.models.reliability'`.

- [ ] **Step 3: Implement**

`projections/models/reliability.py`:

```python
"""Per-component year-to-year reliability for stat-specific regression.

Season-level data only: reliability = PA-weighted year-to-year predictive
correlation of a component's per-PA rate, NOT a within-season stabilization
study (that would need game logs). Leakage-safe: caller passes only seasons
strictly before the target."""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from projections.constants import PROJECTED_RATES

R_FLOOR = 0.05      # min reliability (avoids explosive n_reg for noisy stats)
N_REG_MIN = 300     # clamp floor for derived per-component n_reg
N_REG_MAX = 3000    # clamp ceiling for derived per-component n_reg


def _harmonic(a: float, b: float) -> float:
    if a <= 0 or b <= 0:
        return 0.0
    return 2 * a * b / (a + b)


def _weighted_corr(triples: Sequence[tuple[float, float, float]]) -> float:
    """triples = (x, y, w). Weighted Pearson correlation; 0.0 if degenerate."""
    if len(triples) < 2:
        return 0.0
    wsum = sum(w for _, _, w in triples)
    if wsum <= 0:
        return 0.0
    mx = sum(w * x for x, _, w in triples) / wsum
    my = sum(w * y for _, y, w in triples) / wsum
    cov = sum(w * (x - mx) * (y - my) for x, y, w in triples) / wsum
    vx = sum(w * (x - mx) ** 2 for x, _, w in triples) / wsum
    vy = sum(w * (y - my) ** 2 for _, y, w in triples) / wsum
    if vx <= 0 or vy <= 0:
        return 0.0
    return cov / (vx * vy) ** 0.5


def compute_reliability(
    season_to_rows: Mapping[int, Sequence[dict]],
    pa_floor: float,
) -> dict[str, float]:
    """Return {component: clamped year-to-year reliability} over all consecutive
    season pairs in season_to_rows. Both seasons of a pair must have the player
    with PA >= pa_floor."""
    seasons = sorted(season_to_rows)
    # Accumulate (earlier_rate, later_rate, weight) per component across pairs.
    triples: dict[str, list[tuple[float, float, float]]] = {c: [] for c in PROJECTED_RATES}
    for y in seasons:
        if (y + 1) not in season_to_rows:
            continue
        early = {r["mlbam_id"]: r for r in season_to_rows[y]
                 if float(r.get("PA", 0)) >= pa_floor}
        late = {r["mlbam_id"]: r for r in season_to_rows[y + 1]
                if float(r.get("PA", 0)) >= pa_floor}
        for pid in early.keys() & late.keys():
            e, l = early[pid], late[pid]
            pa_e, pa_l = float(e["PA"]), float(l["PA"])
            w = _harmonic(pa_e, pa_l)
            for c in PROJECTED_RATES:
                triples[c].append((float(e.get(c, 0)) / pa_e,
                                   float(l.get(c, 0)) / pa_l, w))
    rel: dict[str, float] = {}
    for c in PROJECTED_RATES:
        r = _weighted_corr(triples[c])
        rel[c] = min(max(r, R_FLOOR), 1.0)
    return rel
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_reliability.py" -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/models/reliability.py tests/test_reliability.py
git commit -m "feat: per-component year-to-year reliability (harmonic-PA-weighted corr)"
```

---

## Task 2: `available_seasons` helper

The reliability estimate needs many consecutive-season pairs, not just the 3 Marcel weight-years. This helper lets the run loader discover every stored season `< T`.

**Files:**
- Modify: `projections/data/historical.py` (append function)
- Test: `tests/test_historical.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_historical.py`:

```python
    def test_available_seasons_lists_stored_years_sorted(self):
        from projections.data.historical import available_seasons
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2019, 2021, 2020):
                store_season(yr, [{"mlbam_id": "1", "season": yr, "HR": 1}], data_dir)
            self.assertEqual(available_seasons(data_dir), [2019, 2020, 2021])

    def test_available_seasons_empty_when_none(self):
        from projections.data.historical import available_seasons
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(available_seasons(Path(d)), [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_historical.py" -v`
Expected: FAIL — `ImportError: cannot import name 'available_seasons'`.

- [ ] **Step 3: Implement**

Append to `projections/data/historical.py`:

```python
def available_seasons(data_dir: Path) -> list[int]:
    """Sorted list of seasons with a stored hitting snapshot."""
    hist = data_dir / "historical"
    if not hist.exists():
        return []
    seasons = []
    for p in hist.glob("hitting_*.json"):
        try:
            seasons.append(int(p.stem.split("_")[1]))
        except (IndexError, ValueError):
            continue
    return sorted(seasons)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_historical.py" -v`
Expected: PASS (existing 3 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add projections/data/historical.py tests/test_historical.py
git commit -m "feat: available_seasons() helper for reliability lookback window"
```

---

## Task 3: `MarcelParams` gains `gamma`

**Files:**
- Modify: `projections/models/marcel_params.py`
- Test: `tests/test_marcel_params.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_marcel_params.py`:

```python
    def test_gamma_defaults_to_zero_classic(self):
        p = MarcelParams()
        self.assertEqual(p.gamma, 0.0)        # gamma=0 == classic Marcel
        self.assertEqual(p.n_reg, 1200.0)     # n_reg is the base level, unchanged

    def test_gamma_is_settable_via_constructor(self):
        p = MarcelParams(gamma=0.5)
        self.assertEqual(p.gamma, 0.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_params.py" -v`
Expected: FAIL — `AttributeError: 'MarcelParams' object has no attribute 'gamma'`.

- [ ] **Step 3: Implement**

In `projections/models/marcel_params.py`, add the `gamma` field (and a docstring note) — `n_reg` is the base level for the reliability mapping:

```python
@dataclass(frozen=True)
class MarcelParams:
    season_weights: tuple[float, ...] = (5.0, 4.0, 3.0)  # newest first
    n_reg: float = 1200.0          # base regression PA (the "n_reg_base" for Rung 2)
    k_young: float = 0.006         # per-year uplift below peak age
    k_old: float = 0.003           # per-year decline above peak age
    pa_w1: float = 0.5             # weight on PA[T-1]
    pa_w2: float = 0.1             # weight on PA[T-2]
    pa_base: float = 200.0         # baseline PA added
    gamma: float = 0.0             # reliability->regression exponent; 0.0 == classic Marcel
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_params.py" -v`
Expected: PASS (existing 2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add projections/models/marcel_params.py tests/test_marcel_params.py
git commit -m "feat: MarcelParams.gamma knob (default 0.0 = classic Marcel)"
```

---

## Task 4: `project_hitter` per-component `n_reg` (backward-compatible)

**Files:**
- Modify: `projections/models/marcel_hitter.py`
- Test: `tests/test_marcel_hitter.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_marcel_hitter.py` (the existing `setUp` provides `self.prior` and `self.league`):

```python
    def test_gamma_zero_with_reliability_matches_classic(self):
        # Passing a reliability map but gamma=0 must equal the classic path exactly.
        rel = {c: 0.5 for c in self.league}
        classic = project_hitter(self.prior, self.league, age=29, params=MarcelParams())
        with_rel = project_hitter(self.prior, self.league, age=29,
                                  params=MarcelParams(gamma=0.0), reliability=rel)
        self.assertEqual(classic, with_rel)

    def test_reliability_differentiates_regression_when_gamma_positive(self):
        # HR very reliable, BB unreliable -> with gamma>0 their regression differs,
        # so the projection changes vs the classic (single-n_reg) path.
        rel = {c: 0.5 for c in self.league}
        rel["HR"], rel["BB"] = 0.9, 0.1
        classic = project_hitter(self.prior, self.league, age=29, params=MarcelParams())
        tuned = project_hitter(self.prior, self.league, age=29,
                               params=MarcelParams(gamma=1.0), reliability=rel)
        # Reliable HR regresses less -> stays closer to the player's own .05 rate;
        # the two paths must differ on at least HR.
        self.assertNotAlmostEqual(classic["HR"], tuned["HR"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_hitter.py" -v`
Expected: FAIL — `project_hitter() got an unexpected keyword argument 'reliability'`.

- [ ] **Step 3: Implement**

In `projections/models/marcel_hitter.py`, add the import and replace the regression block. Add to imports:

```python
from projections.models.reliability import N_REG_MAX, N_REG_MIN, R_FLOOR
```

Change the signature to add a trailing optional `reliability` (keeps all existing positional calls valid):

```python
def project_hitter(
    prior_seasons: Sequence[dict | None],
    league_rates: dict[str, float],
    age: int | None,
    params: MarcelParams,
    reliability: dict[str, float] | None = None,
) -> dict:
```

Replace the regression loop (currently lines ~36-41) with the per-component version:

```python
    use_rel = reliability is not None and params.gamma != 0.0
    if use_rel:
        present = [reliability[c] for c in PROJECTED_RATES if c in reliability]
        rbar = sum(present) / len(present) if present else 1.0

    regressed: dict[str, float] = {}
    for c in PROJECTED_RATES:
        wtot = sum(w * float(s.get(c, 0)) for s, w in pairs)
        if use_rel:
            r = min(max(reliability.get(c, rbar), R_FLOOR), 1.0)
            n_reg_c = params.n_reg * (rbar / r) ** params.gamma
            n_reg_c = min(max(n_reg_c, N_REG_MIN), N_REG_MAX)
        else:
            n_reg_c = params.n_reg
        regressed[c] = (wtot + n_reg_c * league_rates.get(c, 0.0)) / (
            weighted_pa + n_reg_c
        )
```

(Everything below — `_pa`, age mult, composition, invariants — is unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_hitter.py" -v`
Expected: PASS (existing 4 + 2 new). The `gamma=0` equivalence test guards backward compatibility.

- [ ] **Step 5: Commit**

```bash
git add projections/models/marcel_hitter.py tests/test_marcel_hitter.py
git commit -m "feat: per-component n_reg in project_hitter (gamma=0 nests classic exactly)"
```

---

## Task 5: Thread reliability through `build_marcel_projections`

**Files:**
- Modify: `projections/export/marcel_run.py`
- Test: `tests/test_marcel_run.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_marcel_run.py` (uses the existing `_seed` which stores 2021–2023; extend to give reliability enough pairs):

```python
    def _seed_many(self, data_dir):
        # 5 consecutive seasons, two players with differing HR trajectories so
        # reliability is computable.
        traj = {"5": [25, 27, 24, 26, 25], "7": [10, 18, 12, 20, 9]}
        for i, yr in enumerate((2019, 2020, 2021, 2022, 2023)):
            rows = []
            for pid, hrs in traj.items():
                rows.append({"mlbam_id": pid, "season": yr, "PA": 500, "AB": 450,
                             "H": 125, "1B": 100 - hrs[i] + 25, "2B": 0, "3B": 0,
                             "HR": hrs[i], "R": 80, "RBI": 70, "SB": 0, "CS": 0,
                             "BB": 50, "SO": 100, "HBP": 0, "SF": 0})
            store_season(yr, rows, data_dir)

    def test_gamma_positive_changes_projection_vs_classic(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"},
                      "7": {"birth_date": "1994-01-01"}}
            classic = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            tuned = build_marcel_projections(2024, data_dir, MarcelParams(gamma=1.0), idents)
            c = {r["id"]: r["stats"]["HR"] for r in classic}
            t = {r["id"]: r["stats"]["HR"] for r in tuned}
            # At least one player's HR projection moves once reliability differentiates.
            self.assertTrue(any(abs(c[k] - t[k]) > 1e-9 for k in c))

    def test_gamma_zero_matches_prior_behavior(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"}, "7": {"birth_date": "1994-01-01"}}
            a = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            b = build_marcel_projections(2024, data_dir, MarcelParams(gamma=0.0), idents)
            self.assertEqual([r["stats"] for r in a], [r["stats"] for r in b])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_run.py" -v`
Expected: FAIL — `test_gamma_positive_changes_projection_vs_classic` fails (gamma currently ignored; classic == tuned).

- [ ] **Step 3: Implement**

In `projections/export/marcel_run.py`, add imports:

```python
from projections.data.historical import available_seasons, load_season
from projections.models.reliability import compute_reliability
```

(The existing `from projections.data.historical import load_season` line is replaced by the combined import above.)

Inside `build_marcel_projections`, after computing `league` and before the per-player loop, compute the reliability map from all stored seasons `< target_season`, and pass it to `project_hitter`:

```python
    # Reliability uses a WIDE pre-target window (all stored seasons < T), not just
    # the 3 Marcel weight-years — it needs many consecutive pairs. Leakage-safe.
    rel_seasons = [s for s in available_seasons(data_dir) if s < target_season]
    reliability = compute_reliability(
        {s: load_season(s, data_dir) for s in rel_seasons}, pa_floor=MIN_EVAL_PA,
    )
```

Then change the projection call inside the loop from:

```python
        proj = project_hitter(prior_seasons, league, age, params)
```
to:
```python
        proj = project_hitter(prior_seasons, league, age, params, reliability=reliability)
```

(With `gamma=0` default, passing `reliability` is inert — `project_hitter` ignores it — so this is backward-compatible.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_run.py" -v`
Expected: PASS (existing 3 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add projections/export/marcel_run.py tests/test_marcel_run.py
git commit -m "feat: compute reliability per target season and thread into build"
```

---

## Task 6: Harness — classic-Marcel baseline metric

**Files:**
- Modify: `projections/backtest/harness.py` (append function)
- Test: `tests/test_harness.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_harness.py`:

```python
    def test_vs_classic_detects_a_win(self):
        from projections.backtest.harness import vs_classic
        # Candidate has lower marcel_mae and higher corr than classic on HR.
        cand = [{"per_stat": {"HR": {"marcel_mae": 4.0, "marcel_corr": 0.7}}}]
        classic = [{"per_stat": {"HR": {"marcel_mae": 5.0, "marcel_corr": 0.6}}}]
        out = vs_classic(cand, classic)
        self.assertAlmostEqual(out["mean_ratio_vs_classic"], 0.8)
        self.assertEqual(out["corr_win_rate"], 1.0)
        self.assertTrue(out["beats_classic"])

    def test_vs_classic_reports_tie_when_not_better(self):
        from projections.backtest.harness import vs_classic
        cand = [{"per_stat": {"HR": {"marcel_mae": 5.0, "marcel_corr": 0.6}}}]
        classic = [{"per_stat": {"HR": {"marcel_mae": 5.0, "marcel_corr": 0.6}}}]
        out = vs_classic(cand, classic, epsilon=0.0)
        self.assertFalse(out["beats_classic"])   # ratio 1.0 is not < 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_harness.py" -v`
Expected: FAIL — `ImportError: cannot import name 'vs_classic'`.

- [ ] **Step 3: Implement**

Append to `projections/backtest/harness.py`:

```python
def vs_classic(
    candidate_seasons: list[dict],
    classic_seasons: list[dict],
    epsilon: float = 0.0,
) -> dict:
    """Compare a candidate config's per-season scorecards against classic Marcel's
    (both from rolling_origin over the SAME target seasons). Beating classic is the
    Rung 2 bar; persistence is only a sanity floor."""
    ratios: list[float] = []
    corr_wins = corr_total = 0
    for cs, ks in zip(candidate_seasons, classic_seasons):
        for stat, cm in cs["per_stat"].items():
            km = ks["per_stat"].get(stat)
            if not cm or not km or km["marcel_mae"] == 0:
                continue
            ratios.append(cm["marcel_mae"] / km["marcel_mae"])
            corr_total += 1
            if cm["marcel_corr"] > km["marcel_corr"]:
                corr_wins += 1
    mean_ratio = sum(ratios) / len(ratios) if ratios else float("inf")
    cwr = corr_wins / corr_total if corr_total else 0.0
    return {
        "mean_ratio_vs_classic": mean_ratio,
        "corr_win_rate": cwr,
        "beats_classic": mean_ratio < 1.0 - epsilon and cwr > 0.5,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_harness.py" -v`
Expected: PASS (existing 2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add projections/backtest/harness.py tests/test_harness.py
git commit -m "feat: vs_classic harness metric (beat-classic-Marcel bar)"
```

---

## Task 7: Tuning — coordinate descent over `(n_reg_base, gamma)`

**Files:**
- Modify: `projections/backtest/tune.py` (append)
- Test: `tests/test_tune.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tune.py` (reuses module-level `_row`):

```python
    def test_coordinate_descent_returns_params_and_score(self):
        from projections.backtest.tune import coordinate_descent
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"},
                      "7": {"birth_date": "1990-01-01"}}
            best, score = coordinate_descent(
                [2022, 2023], data_dir, idents,
                n_reg_values=(900.0, 1200.0), gamma_values=(0.0, 0.5),
            )
            self.assertIn(best.n_reg, (900.0, 1200.0))
            self.assertIn(best.gamma, (0.0, 0.5))
            self.assertIsInstance(score, float)

    def test_coordinate_descent_starts_from_classic(self):
        # With a single-value grid equal to defaults, it returns classic unchanged.
        from projections.backtest.tune import coordinate_descent
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"}, "7": {"birth_date": "1990-01-01"}}
            best, _ = coordinate_descent(
                [2022, 2023], data_dir, idents,
                n_reg_values=(1200.0,), gamma_values=(0.0,),
            )
            self.assertEqual((best.n_reg, best.gamma), (1200.0, 0.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_tune.py" -v`
Expected: FAIL — `ImportError: cannot import name 'coordinate_descent'`.

- [ ] **Step 3: Implement**

Append to `projections/backtest/tune.py` (add `from dataclasses import replace` at top of file):

```python
from dataclasses import replace


def coordinate_descent(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    n_reg_values: tuple[float, ...],
    gamma_values: tuple[float, ...],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Alternately optimize gamma then n_reg_base (objective: minimize the
    candidate's tuning-block mean_mae_ratio vs persistence). Starts from classic
    Marcel, so it can never do worse than classic on the tuning block. Avoids the
    combinatorial blowup of a dense per-component grid."""
    best = MarcelParams()
    best_score = rolling_origin(tuning_seasons, data_dir, best, identities)["mean_mae_ratio"]
    for _ in range(max_rounds):
        improved = False
        for g in gamma_values:
            cand = replace(best, gamma=g)
            score = rolling_origin(tuning_seasons, data_dir, cand, identities)["mean_mae_ratio"]
            if score < best_score:
                best, best_score, improved = cand, score, True
        for n in n_reg_values:
            cand = replace(best, n_reg=n)
            score = rolling_origin(tuning_seasons, data_dir, cand, identities)["mean_mae_ratio"]
            if score < best_score:
                best, best_score, improved = cand, score, True
        if not improved:
            break
    return best, best_score
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_tune.py" -v`
Expected: PASS (existing 2 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add projections/backtest/tune.py tests/test_tune.py
git commit -m "feat: coordinate-descent tuning over (n_reg_base, gamma)"
```

---

## Task 8: Verdict — beat classic Marcel with carryover (manual run) + regression

**Files:**
- Test: full suite (no new test file)

- [ ] **Step 1: Full-suite regression**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests`
Expected: all green (462 baseline + the new Rung 2 tests). Backward-compat tests (Task 4/5 `gamma=0`) confirm classic path is unchanged.

- [ ] **Step 2: Run the real verdict on held-out data**

Tune on 2014–2019, score on the disjoint 2020–2025 block, and apply the carryover guard.

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.identity import load_identity_store
from projections.backtest.harness import rolling_origin, vs_classic
from projections.backtest.tune import coordinate_descent
from projections.models.marcel_params import MarcelParams
d = Path('projections/data')
idents = load_identity_store(d)
tune_t = list(range(2014, 2020))
score_t = list(range(2020, 2026))
NREG = (300.0, 600.0, 900.0, 1200.0, 1500.0, 2000.0)
GAMMA = (0.0, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0)
best, tune_score = coordinate_descent(tune_t, d, idents, NREG, GAMMA)
print('locked params: n_reg_base', best.n_reg, 'gamma', best.gamma)

# Carryover: compare candidate vs classic on BOTH blocks.
classic = MarcelParams()
tune_cand = rolling_origin(tune_t, d, best, idents)['seasons']
tune_clsc = rolling_origin(tune_t, d, classic, idents)['seasons']
score_cand = rolling_origin(score_t, d, best, idents)['seasons']
score_clsc = rolling_origin(score_t, d, classic, idents)['seasons']
tune_v = vs_classic(tune_cand, tune_clsc)
score_v = vs_classic(score_cand, score_clsc)
print('TUNING block  vs classic:', round(tune_v['mean_ratio_vs_classic'],4), 'beats', tune_v['beats_classic'])
print('SCORING block vs classic:', round(score_v['mean_ratio_vs_classic'],4), 'beats', score_v['beats_classic'])
print('CARRYOVER CONFIRMED:', score_v['beats_classic'])
"
```
Expected — one of two honest outcomes:
- **Win:** `gamma > 0`, `SCORING block beats_classic True` → reliability-weighting beats classic Marcel and it carries. Success criterion #3 (win branch) met.
- **Tie:** `gamma ≈ 0` or `SCORING block beats_classic False` → reliability-weighting does **not** beat classic Marcel; report plainly and conclude Statcast is the next lever. Success criterion #3 (tie branch) met.

**Do not tune the grid until the scoring block "wins."** A win that only appears after grid-fishing on the scoring block is leakage. Report whatever the disjoint split produces.

- [ ] **Step 3: Record the verdict**

Add a short note of the outcome (params + both-block ratios + win/tie) to the spec's tail or a commit message, and commit any uncommitted state:

```bash
git add -A
git commit -m "chore: rung 2 reliability-weighted regression complete — <WIN|TIE> vs classic"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** reliability definition incl. harmonic-PA weight + R_FLOOR clamp (T1); wide leakage-safe lookback (T2 helper + T5 wiring); `n_reg_c = n_reg_base·(r̄/r_c)^gamma` with N_REG_MIN/MAX clamps and `gamma=0` nesting classic (T3+T4); classic-Marcel first-class metric (T6); coordinate-descent tuning, no per-stat grid (T7); carryover guard + honest win/tie verdict (T8). R/RBI noisy-context treatment is inherent (low `r_c` → heavy regression) and surfaced in the T8 per-stat output.
- **Placeholder scan:** no TBD/TODO; every code step shows complete code; T8 expected-output is a genuine branch (win vs tie), not a placeholder.
- **Type consistency:** `compute_reliability(season_to_rows: Mapping[int, Sequence[dict]], pa_floor)` returns `dict[str,float]`, consumed by `project_hitter(..., reliability=)` (T4) and produced in `build_marcel_projections` (T5). `R_FLOOR/N_REG_MIN/N_REG_MAX` defined once in `reliability.py` (T1), imported by `marcel_hitter` (T4). `MarcelParams.gamma` (T3) read in `project_hitter` (T4) and varied via `dataclasses.replace` in `coordinate_descent` (T7). `vs_classic(candidate_seasons, classic_seasons, epsilon)` (T6) consumes the `seasons` list shape returned by `rolling_origin` (Rung 1), used in T8.
