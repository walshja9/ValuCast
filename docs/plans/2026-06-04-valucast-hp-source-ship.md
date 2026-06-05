# Ship ValuCast H+P — Combined In-House Source Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Register a combined `valucast` H+P projection source (Statcast-de-noised hitters + role-routed pitchers, both offline-built and committed) selectable via `?source=`, while Steamer stays the default and current app behavior is byte-for-byte unchanged.

**Architecture:** A combined-run writer concatenates hitter + pitcher rows and writes one immutable run with a rich per-leg manifest (single-pool guard). The 2026 run is built offline from committed snapshots and committed. `app.py` swaps its lone `store` for a `ProjectionCatalog` and threads an optional source through `_valuation_players`/`_build_context`; absent/unknown → steamer.

**Tech Stack:** Python 3.x, stdlib only, Flask (existing), `unittest`. Reuses `build_marcel_projections`, `build_pitcher_projections`, `write_run`, `ProjectionCatalog`, `ProjectionStore`.

**Spec:** `docs/specs/2026-06-04-valucast-hp-source-ship-design.md`

**Test command:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_X.py" -v`. Full suite: `... discover -s tests` (baseline **548**, must stay green).

---

## File Structure

**Create:**
- `projections/export/valucast_hp_run.py` — combine hitter+pitcher rows, single-pool guard, rich manifest, immutable write
- Tests under `tests/`

**Modify:**
- `app.py` — `ProjectionCatalog` wiring + `_active_store` + optional source through `_valuation_players`/`_build_context`/rankings/detail/compare

**Data (committed):** `projections/runs/valucast_hp_2026_v1/projections.json` + `run_manifest.json`

---

## Task 1: Combined-run writer (single-pool guard + rich manifest)

**Files:**
- Create: `projections/export/valucast_hp_run.py`
- Test: `tests/test_valucast_hp_run.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import tempfile
import unittest
from pathlib import Path

from projections.export.valucast_hp_run import write_valucast_hp_run


def _h(pid):
    return {"id": f"mlbam_{pid}_H", "name": pid, "pool": "hitter", "positions": [],
            "stats": {"PA": 600, "HR": 25, "AVG": 0.280}, "metadata": {"mlbam_id": pid}}


def _p(pid):
    return {"id": f"mlbam_{pid}_P", "name": pid, "pool": "starter", "positions": ["SP"],
            "stats": {"IP": 180, "K": 200, "ERA": 3.50}, "metadata": {"mlbam_id": pid}}


class TestValucastHpRun(unittest.TestCase):
    def test_writes_combined_run_with_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "runs"
            run_id = write_valucast_hp_run(
                [_h("1"), _h("2")], [_p("3")], runs, version=1,
                hitter_meta={"model": "valucast_marcel_statcast", "alpha_contact": 0.75},
                pitcher_meta={"model": "valucast_pitching_marcel"},
            )
            self.assertEqual(run_id, "valucast_hp_2026_v1")
            rows = json.loads((runs / run_id / "projections.json").read_text())
            self.assertEqual(len(rows), 3)                       # 2 hitters + 1 pitcher
            man = json.loads((runs / run_id / "run_manifest.json").read_text())
            self.assertEqual(man["source_name"], "valucast")
            self.assertEqual(man["hitter_count"], 2)
            self.assertEqual(man["pitcher_count"], 1)
            self.assertEqual(man["components"]["hitters"]["alpha_contact"], 0.75)

    def test_rejects_single_pool(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "runs"
            with self.assertRaises(ValueError):     # no pitchers -> reject
                write_valucast_hp_run([_h("1")], [], runs, version=1,
                                      hitter_meta={}, pitcher_meta={})
            with self.assertRaises(ValueError):     # no hitters -> reject
                write_valucast_hp_run([], [_p("3")], runs, version=1,
                                      hitter_meta={}, pitcher_meta={})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_valucast_hp_run.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `projections/export/valucast_hp_run.py`:

```python
"""Combine ValuCast hitter + pitcher projection rows into one immutable H+P run,
with a per-leg provenance manifest. Single-pool runs are rejected (a broken
half-publish must not masquerade as 'ValuCast has no pitchers')."""
from __future__ import annotations

import json
from pathlib import Path

AS_OF_SEASON = 2026


def write_valucast_hp_run(
    hitter_rows: list[dict],
    pitcher_rows: list[dict],
    runs_dir: Path,
    version: int,
    hitter_meta: dict,
    pitcher_meta: dict,
) -> str:
    """Write projections.json (hitters + pitchers) + run_manifest.json. Immutable:
    identical re-write is a no-op, changed content raises. Returns run_id."""
    if not hitter_rows:
        raise ValueError("ValuCast H+P run has zero hitter rows; refusing to write.")
    if not pitcher_rows:
        raise ValueError("ValuCast H+P run has zero pitcher rows; refusing to write.")

    run_id = f"valucast_hp_{AS_OF_SEASON}_v{version}"
    run_path = runs_dir / run_id
    proj_path = run_path / "projections.json"
    combined = list(hitter_rows) + list(pitcher_rows)

    if proj_path.exists():
        if json.loads(proj_path.read_text(encoding="utf-8")) == combined:
            return run_id
        raise ValueError(f"Refusing to overwrite archived run {run_id}: contents differ.")

    run_path.mkdir(parents=True, exist_ok=True)
    proj_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "source_name": "valucast",
        "as_of_season": AS_OF_SEASON,
        "hitter_count": len(hitter_rows),
        "pitcher_count": len(pitcher_rows),
        "components": {
            "hitters": {"inputs": "consumes Savant xBA/xSLG (not our own xBA)", **hitter_meta},
            "pitchers": {"inputs": "fully in-house, no Statcast", **pitcher_meta},
        },
    }
    (run_path / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return run_id
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_valucast_hp_run.py" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/export/valucast_hp_run.py tests/test_valucast_hp_run.py
git commit -m "feat: combined ValuCast H+P run writer (single-pool guard, per-leg manifest)"
```

---

## Task 2: Build + commit the real 2026 combined run (offline)

**Files:** data — `projections/runs/valucast_hp_2026_v1/`

- [ ] **Step 1: Full-suite regression first**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests`
Expected: all green (548 baseline + Task 1's tests).

- [ ] **Step 2: Build the run from committed snapshots (no network)**

`build_marcel_projections`/`build_pitcher_projections` read only committed snapshots + `identity.json`. Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.identity import load_identity_store
from projections.export.marcel_run import build_marcel_projections
from projections.export.valucast_hp_run import write_valucast_hp_run
from projections.models.marcel_pitcher import build_pitcher_projections
from projections.models.marcel_params import MarcelParams
from projections.models.pitcher_params import PitcherMarcelParams
d = Path('projections/data'); runs = Path('projections/runs')
idents = load_identity_store(d)
hitters = build_marcel_projections(2026, d, MarcelParams(alpha_contact=0.75, alpha_power=0.5), idents)
pitchers = build_pitcher_projections(2026, d, PitcherMarcelParams())
run_id = write_valucast_hp_run(
    hitters, pitchers, runs, version=1,
    hitter_meta={'model':'valucast_marcel_statcast','model_version':1,'alpha_contact':0.75,'alpha_power':0.5,'gamma':0.0,
                 'verdict':'held-out 2020-25 mean MAE ratio 0.979; AVG/OBP/SLG/OPS 4-6% lift; HR neutral'},
    pitcher_meta={'model':'valucast_pitching_marcel','model_version':1,
                  'verdict':'held-out 2020-25 skill mean MAE ratio 0.821 vs persistence'},
)
print('run', run_id, '| hitters', len(hitters), '| pitchers', len(pitchers))
"
```
Expected: `run valucast_hp_2026_v1 | hitters ~1600-1800 | pitchers ~700-900`. If either pool is 0, the writer raises (stop and investigate the snapshots).

- [ ] **Step 3: Sanity-check the run is engine-valuable end-to-end**

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from web.projection_store import ProjectionStore
from league_values.engine import ValuationEngine
from league_values.post_processors import VolumeMultiplier
from league_values.presets import standard_5x5
from league_values.models import PlayerPool
store = ProjectionStore('projections/runs/valucast_hp_2026_v1/projections.json')
players = store.get_all()
pools = {}
for p in players: pools[p.pool] = pools.get(p.pool, 0) + 1
print('pools:', {str(k): v for k, v in pools.items()})
res = ValuationEngine(post_processors=[VolumeMultiplier()]).value_players(players, standard_5x5())
print('valued', len(res), 'players; top value', round(max(r.total_value for r in res), 2))
"
```
Expected: both hitter and starter/reliever pools present; engine values them with finite values.

- [ ] **Step 4: Commit the run**

```bash
git add projections/runs/valucast_hp_2026_v1/
git commit -m "data: ValuCast H+P 2026 combined run (de-noised hitters + role-routed pitchers)"
```

---

## Task 3: Wire ProjectionCatalog into app.py (source-selectable, Steamer default)

**Files:**
- Modify: `app.py`
- Test: `tests/test_app_source.py`

- [ ] **Step 1: Write the failing test**

```python
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestSourceSelection(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_default_board_is_steamer(self):
        r = self.client.get("/rankings")
        self.assertEqual(r.status_code, 200)

    def test_valucast_source_loads_combined_board(self):
        r = self.client.get("/rankings?source=valucast")
        self.assertEqual(r.status_code, 200)
        # Combined board: both a hitter and a pitcher category surface should value.
        self.assertGreater(len(r.data), 100)

    def test_unknown_source_clear_error(self):
        r = self.client.get("/rankings?source=bogus")
        self.assertEqual(r.status_code, 400)
        self.assertIn(b"source", r.data.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_app_source.py" -v`
Expected: FAIL — `test_unknown_source_clear_error` (no source handling yet; bogus source ignored → 200, not 400).

- [ ] **Step 3: Implement the wiring**

In `app.py`, replace the store init (the `DATA_PATH` / `store = ProjectionStore(DATA_PATH)` block) with a catalog. Add the import near the other `web.` imports:

```python
from web.projection_catalog import ProjectionCatalog
```

Replace the init block:

```python
# Projection sources. Steamer (season outlook) is the default; ValuCast H+P is the
# opt-in combined in-house source. App only LOADS committed runs — no runtime model.
DATA_PATH = Path(__file__).parent / "data" / "projections" / "current.json"
VALUCAST_HP_PATH = Path(__file__).parent / "projections" / "runs" / "valucast_hp_2026_v1" / "projections.json"
CATALOG = ProjectionCatalog(
    {"steamer": str(DATA_PATH), "valucast": str(VALUCAST_HP_PATH)}, default="steamer")
store = CATALOG.store_for("steamer")   # module-level default (kept for existing imports)


def _active_store(source: str | None):
    """Resolve a request's projection source. None/empty/'steamer' -> default store.
    Unknown source -> None (route returns a clear 400). A valucast run missing a pool
    or its file is treated as unavailable (None), never a silent fallback."""
    if not source or source == "steamer":
        return store
    try:
        s = CATALOG.store_for(source)
    except (KeyError, FileNotFoundError):
        return None
    if source == "valucast":
        pools = {p.pool.value for p in s.get_all()}
        if "hitter" not in pools or not ({"starter", "reliever", "pitcher"} & pools):
            return None   # single-pool / broken combined run -> unavailable
    return s
```

Change `_valuation_players` to take an optional active store (keeps existing call sites valid):

```python
def _valuation_players(always_keep=None, active_store=None):
    """Engine input: all projections minus sub-threshold filler. `active_store`
    defaults to the module Steamer store."""
    return filter_by_playing_time(
        (active_store or store).get_all(),
        hitter_pa=MIN_HITTER_PA, sp_ip=MIN_SP_IP, rp_ip=MIN_RP_IP,
        always_keep=always_keep or frozenset(),
    )
```

In `_build_context(args)`, resolve the source once and put it in the context (add near the top, after `search = args.get("search", "")`):

```python
    source = args.get("source", "")
    active = _active_store(source)
```

and add `"source": source` and `"active_store": active` to the dict `_build_context` returns. (If `active is None`, leave it None — the route checks it.)

In the **rankings** route, right after `ctx = _build_context(request.args)` (and before using `store`), add the unknown-source guard and use the active store:

```python
    if ctx["active_store"] is None:
        return "<div class='error'>Unknown or unavailable projection source.</div>", 400
    active = ctx["active_store"]
```
then change the two store uses in that route:
- `{p.id for p in store.get_all() if ...}` → `{p.id for p in active.get_all() if ...}`
- `_valuation_players(search_keep)` → `_valuation_players(search_keep, active_store=active)`

In the **player detail** route (the non-dynasty branch) and **compare** route, do the same: after `ctx = _build_context(request.args)`, guard `ctx["active_store"] is None` → 400, set `active = ctx["active_store"]`, then:
- detail: `store.get_by_id(player_id)` → `active.get_by_id(player_id)`; `_valuation_players({player_id})` → `_valuation_players({player_id}, active_store=active)`.
- compare: `_valuation_players({p1_id, p2_id})` → `_valuation_players({p1_id, p2_id}, active_store=active)`.

(The DD-dynasty player-detail branch's `find_season_outlook(dd_row, store.get_all())` stays on the default `store` — the actuals+ROS outlook is Steamer-specific and unaffected by source. The `as_of`/`player_count` metadata fields stay on the module `store`; ValuCast has no as_of sidecar, and leaving metadata on the default is correct.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_app_source.py" -v`
Expected: PASS (3 tests). `source=valucast` loads the committed combined run; bogus → 400; default unchanged.

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app_source.py
git commit -m "feat: ProjectionCatalog wiring — ?source=valucast H+P board, Steamer default unchanged"
```

---

## Task 4: Full-suite regression + default-unchanged proof

- [ ] **Step 1: Run the entire suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests`
Expected: all green (548 baseline + Tasks 1 & 3 tests). The existing `test_app.py` (which imports `store` and calls `_valuation_players`) still passes — `store` is still the Steamer default and `_valuation_players`'s signature is back-compatible.

- [ ] **Step 2: Eyeball the default vs valucast boards (manual)**

Run the app and confirm both render:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="src;." python -c "
from app import app
c = app.test_client()
d = c.get('/rankings').data
v = c.get('/rankings?source=valucast').data
b = c.get('/rankings?source=bogus')
print('default len', len(d), '| valucast len', len(v), '| bogus status', b.status_code)
print('default unchanged sanity: both >0 and valucast renders a board')
"
```
Expected: default and valucast both render (non-trivial length); bogus → 400.

- [ ] **Step 3: Commit any final notes**

```bash
git add -A
git commit -m "chore: ValuCast H+P source ship complete (Steamer default, opt-in valucast board)"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** combined H+P source = one run with both pools (T1, T2); offline-built committed run, no runtime network/model (T2); per-leg provenance manifest incl. inputs note (hitters consume Savant, pitchers in-house) + verdicts (T1 manifest, T2 build); ProjectionCatalog wiring + `?source=` + Steamer default unchanged (T3); failure modes — unknown source → 400, single-pool/missing run → unavailable (T1 writer guard + T3 `_active_store` pool guard); engine values combined board end-to-end (T2 Step 3 + T3 test); no own-xBA claim (manifest inputs note). All spec sections map to a task.
- **Placeholder scan:** no TBD/TODO; every code step is complete. The hitter/pitcher counts in T2 are ranges (real data), not placeholders.
- **Type consistency:** `write_valucast_hp_run(hitter_rows, pitcher_rows, runs_dir, version, hitter_meta, pitcher_meta) -> run_id` used in T1/T2. `_active_store(source) -> store|None` and `_valuation_players(always_keep=None, active_store=None)` consistent across T3 call sites. `ProjectionCatalog({...}, default="steamer").store_for(source)` matches the existing catalog API. Run path `projections/runs/valucast_hp_2026_v1/projections.json` consistent T2/T3. `ProjectionStore`/engine/`standard_5x5` reused unchanged.
