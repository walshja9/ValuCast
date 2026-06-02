# Projections Rung 3 — Statcast Input De-noising Implementation Plan

> **VERDICT (2026-06-02, executed): WIN — Statcast input de-noising beats classic Marcel.**
> First lever in the program to beat classic (Rung 1 + Rung 2 both tied). Tuned α=(contact 0.75,
> power 0.5) on 2018–2019, scored on disjoint 2020–2025 (all targets 3/3 Statcast-covered priors):
> mean MAE ratio vs classic **0.979**, corr-win 0.519, `beats_classic=True`, and the edge **carries**
> (tuning 0.985 → scoring 0.979, same direction). The win is concentrated in the de-noised rate stats —
> **AVG 0.942 (+corr .029), OBP 0.959, SLG 0.960, OPS 0.951 (+corr .048)** — i.e. 4–6% MAE improvement
> on exactly the stats xBA/xSLG target. HR ~neutral (1.001), counting stats untouched (1.000) as
> designed. Modest but real and interpretable. Behavior-neutral until deployed (`α=0` is the default).
> See "Execution Verdict" at the tail.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De-noise Marcel's historical hitting inputs toward Statcast expected stats (`xBA`/`xSLG`) before weighting, and prove on held-out 2020–2025 whether luck-stripped inputs beat classic Marcel.

**Architecture:** A new `statcast.py` pulls immutable Baseball-Savant season snapshots (join by MLBAM id). A new `statcast_denoise.py` blends each historical season's hit components toward `xBA`/`xSLG` and redistributes into 1B/2B/3B/HR by the player's own extra-base mix, with feasibility guards. `MarcelParams` gains two blend knobs (`alpha_contact`, `alpha_power`); `α=0` nests classic exactly and `gamma` stays 0 to isolate the Statcast effect. Tuning reuses coordinate descent over the alphas; the harness verdict uses a Statcast-aware tuning block (2018–19) and the disjoint 2020–25 scoring block.

**Tech Stack:** Python 3.x, stdlib only (`urllib`, `csv`, `io`, `json`, `hashlib`, `dataclasses.replace`), `unittest`. Reuses all Rung 1/2 modules under `projections/`.

**Spec:** `docs/specs/2026-06-02-projections-rung3-statcast-inputs-design.md`

**Test command:** `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_X.py" -v`
(`tests/` has no `__init__.py` — use `discover -p`.) Full suite: `... discover -s tests` (baseline **478**, must stay green).

---

## File Structure

**Create:**
- `projections/data/statcast.py` — Savant pull/parse/store/load + undercoverage guard
- `projections/models/statcast_denoise.py` — league XBH mix + component de-noising bridge
- Tests for each under `tests/`

**Modify:**
- `projections/models/marcel_params.py` — add `alpha_contact`, `alpha_power`
- `projections/export/marcel_run.py` — de-noise the 3 prior seasons before projecting
- `projections/backtest/tune.py` — `coordinate_descent_alpha` (shared private descent)

**Backward-compatibility invariant (verified in Tasks 1 & 6):** with `alpha_contact=alpha_power=0` (default) the build reproduces classic output exactly and the 478-test suite stays green.

---

## Task 1: `MarcelParams` gains the two alpha knobs

**Files:**
- Modify: `projections/models/marcel_params.py`
- Test: `tests/test_marcel_params.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_marcel_params.py`:

```python
    def test_alpha_knobs_default_to_zero(self):
        p = MarcelParams()
        self.assertEqual(p.alpha_contact, 0.0)   # 0 = no de-noising = classic
        self.assertEqual(p.alpha_power, 0.0)

    def test_alpha_knobs_settable(self):
        p = MarcelParams(alpha_contact=0.4, alpha_power=0.6)
        self.assertEqual((p.alpha_contact, p.alpha_power), (0.4, 0.6))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_params.py" -v`
Expected: FAIL — `AttributeError: 'MarcelParams' object has no attribute 'alpha_contact'`.

- [ ] **Step 3: Implement**

In `projections/models/marcel_params.py`, append two fields after `gamma`:

```python
    gamma: float = 0.0             # reliability->regression exponent; 0.0 == classic Marcel
    alpha_contact: float = 0.0     # blend weight: actual hit rate -> xBA; 0.0 == classic
    alpha_power: float = 0.0       # blend weight: actual TB rate -> xSLG; 0.0 == classic
```

(Replace the existing `gamma` line with these three so the field order is explicit.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_params.py" -v`
Expected: PASS (existing 4 + 2 new).

- [ ] **Step 5: Commit**

```bash
git add projections/models/marcel_params.py tests/test_marcel_params.py
git commit -m "feat: MarcelParams alpha_contact/alpha_power knobs (default 0 = classic)"
```

---

## Task 2: Statcast CSV parsing (pure, no network)

**Files:**
- Create: `projections/data/statcast.py`
- Test: `tests/test_statcast_parse.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.data.statcast import parse_expected_stats, parse_quality


# Mimics Savant CSV: BOM + quoted "last_name, first_name" combined field.
EXPECTED_CSV = (
    '﻿"last_name, first_name",player_id,year,pa,bip,ba,est_ba,'
    'est_ba_minus_ba_diff,slg,est_slg,est_slg_minus_slg_diff,woba,est_woba,'
    'est_woba_minus_woba_diff\n'
    '"Semien, Marcus",543760,2023,753,565,0.276,0.258,-0.018,0.478,0.434,'
    '-0.044,0.354,0.330,-0.024\n'
)

QUALITY_CSV = (
    '﻿"last_name, first_name",player_id,attempts,avg_hit_angle,'
    'anglesweetspotpercent,max_hit_speed,avg_hit_speed,ev50,fbld,gb,'
    'max_distance,avg_distance,avg_hr_distance,ev95plus,ev95percent,barrels,'
    'brl_percent,brl_pa\n'
    '"Semien, Marcus",543760,400,12.5,34.0,110.0,89.5,100,50,25,440,180,400,'
    '120,30.0,40,10.0,7.1\n'
)


class TestStatcastParse(unittest.TestCase):
    def test_parse_expected_keys_off_player_id(self):
        out = parse_expected_stats(EXPECTED_CSV)
        self.assertIn("543760", out)
        self.assertAlmostEqual(out["543760"]["xba"], 0.258)
        self.assertAlmostEqual(out["543760"]["xslg"], 0.434)
        self.assertAlmostEqual(out["543760"]["xwoba"], 0.330)

    def test_parse_quality_observe_only_fields(self):
        out = parse_quality(QUALITY_CSV)
        self.assertAlmostEqual(out["543760"]["barrel_pct"], 10.0)
        self.assertAlmostEqual(out["543760"]["avg_ev"], 89.5)
        self.assertAlmostEqual(out["543760"]["hardhit_pct"], 30.0)
        self.assertAlmostEqual(out["543760"]["launch_angle"], 12.5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_parse.py" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'projections.data.statcast'`.

- [ ] **Step 3: Implement (parsing portion of the module)**

Create `projections/data/statcast.py`:

```python
"""Baseball Savant Statcast snapshots (hitting): xBA/xSLG (the de-noising bridge)
plus barrel%/EV (observe-only). Immutable per-season snapshots, joined by MLBAM
id. Pulled once, never scraped at projection time."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen

USER_AGENT = "Mozilla/5.0"
SCHEMA_VERSION = 1
COVERAGE_FLOOR = 250  # raise if a season pull returns fewer rows than this

EXPECTED_URL = (
    "https://baseballsavant.mlb.com/leaderboard/expected_statistics"
    "?type=batter&year={year}&min=1&filterType=bip&csv=true"
)
QUALITY_URL = (
    "https://baseballsavant.mlb.com/leaderboard/statcast"
    "?type=batter&year={year}&min=1&csv=true"
)


def _to_float(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_expected_stats(csv_text: str) -> dict[str, dict]:
    """{mlbam_id: {xba, xslg, xwoba}} from the expected_statistics CSV.

    Savant prepends a UTF-8 BOM and quotes the combined "last_name, first_name"
    field; reading with the BOM already stripped lets csv treat it as one field.
    """
    reader = csv.DictReader(io.StringIO(csv_text))
    out: dict[str, dict] = {}
    for row in reader:
        pid = row.get("player_id")
        if not pid:
            continue
        out[pid] = {
            "xba": _to_float(row.get("est_ba")),
            "xslg": _to_float(row.get("est_slg")),
            "xwoba": _to_float(row.get("est_woba")),
        }
    return out


def parse_quality(csv_text: str) -> dict[str, dict]:
    """{mlbam_id: {barrel_pct, avg_ev, hardhit_pct, launch_angle}} (observe-only)."""
    reader = csv.DictReader(io.StringIO(csv_text))
    out: dict[str, dict] = {}
    for row in reader:
        pid = row.get("player_id")
        if not pid:
            continue
        out[pid] = {
            "barrel_pct": _to_float(row.get("brl_percent")),
            "avg_ev": _to_float(row.get("avg_hit_speed")),
            "hardhit_pct": _to_float(row.get("ev95percent")),
            "launch_angle": _to_float(row.get("avg_hit_angle")),
        }
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_parse.py" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/data/statcast.py tests/test_statcast_parse.py
git commit -m "feat: Statcast CSV parsing (xBA/xSLG + observe-only quality), BOM-safe"
```

---

## Task 3: Statcast snapshot store/load + merge + undercoverage guard

**Files:**
- Modify: `projections/data/statcast.py` (append)
- Test: `tests/test_statcast_store.py`

- [ ] **Step 1: Write the failing test**

```python
import tempfile
import unittest
from pathlib import Path

from projections.data.statcast import (
    merge_statcast, store_statcast_season, load_statcast_season,
    assert_coverage, COVERAGE_FLOOR,
)


class TestStatcastStore(unittest.TestCase):
    def test_merge_joins_expected_and_quality_by_id(self):
        expected = {"5": {"xba": 0.25, "xslg": 0.45, "xwoba": 0.33}}
        quality = {"5": {"barrel_pct": 9.0, "avg_ev": 89.0,
                         "hardhit_pct": 40.0, "launch_angle": 12.0}}
        rows = merge_statcast(expected, quality)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["mlbam_id"], "5")
        self.assertAlmostEqual(r["xba"], 0.25)
        self.assertAlmostEqual(r["barrel_pct"], 9.0)

    def test_store_load_roundtrip_and_immutable_noop(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            rows = [{"mlbam_id": "5", "xba": 0.25, "xslg": 0.45, "xwoba": 0.33,
                     "barrel_pct": 9.0, "avg_ev": 89.0, "hardhit_pct": 40.0,
                     "launch_angle": 12.0}]
            store_statcast_season(2023, rows, data_dir)
            store_statcast_season(2023, rows, data_dir)  # identical -> no-op
            loaded = load_statcast_season(2023, data_dir)
            self.assertAlmostEqual(loaded["5"]["xba"], 0.25)

    def test_store_raises_on_changed_season(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store_statcast_season(2023, [{"mlbam_id": "5", "xba": 0.25}], data_dir)
            with self.assertRaises(ValueError):
                store_statcast_season(2023, [{"mlbam_id": "5", "xba": 0.99}], data_dir)

    def test_assert_coverage_raises_below_floor(self):
        assert_coverage(2023, COVERAGE_FLOOR)        # exactly floor -> ok
        with self.assertRaises(ValueError):
            assert_coverage(2023, COVERAGE_FLOOR - 1)  # below -> raise

    def test_load_missing_season_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_statcast_season(2099, Path(d)), {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_store.py" -v`
Expected: FAIL — `ImportError: cannot import name 'merge_statcast'`.

- [ ] **Step 3: Implement (append to `projections/data/statcast.py`)**

```python
def _fetch(url: str) -> str:
    req = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8-sig", "replace")  # utf-8-sig strips BOM


def merge_statcast(expected: dict[str, dict], quality: dict[str, dict]) -> list[dict]:
    """Join expected + quality by mlbam_id. Expected stats anchor the row;
    quality fields are added when present (observe-only)."""
    rows = []
    for pid, exp in expected.items():
        q = quality.get(pid, {})
        rows.append({"mlbam_id": pid, **exp,
                     "barrel_pct": q.get("barrel_pct"),
                     "avg_ev": q.get("avg_ev"),
                     "hardhit_pct": q.get("hardhit_pct"),
                     "launch_angle": q.get("launch_angle")})
    return rows


def assert_coverage(season: int, row_count: int) -> None:
    """Fail loud on undercoverage — a silent empty/partial pull would masquerade
    as 'classic fallback everywhere' and fake a tie."""
    if row_count < COVERAGE_FLOOR:
        raise ValueError(
            f"Statcast {season}: {row_count} rows < floor {COVERAGE_FLOOR}; "
            "refusing to store a likely broken pull."
        )


def _season_path(season: int, data_dir: Path) -> Path:
    return data_dir / "statcast" / f"hitting_{season}.json"


def store_statcast_season(season: int, rows: list[dict], data_dir: Path) -> None:
    """Immutable per-season snapshot. Identical re-pull is a no-op; a changed
    finalized season raises (compares parsed content, not raw bytes — Windows
    newline-safe, same contract as the MLB backbone)."""
    path = _season_path(season, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) == rows:
            return
        raise ValueError(f"Refusing to overwrite Statcast season {season}: content changed.")
    path.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    _update_manifest(season, rows, data_dir)


def _update_manifest(season: int, rows: list[dict], data_dir: Path) -> None:
    mpath = data_dir / "statcast" / "manifest.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
    manifest[str(season)] = {
        "season": season,
        "row_count": len(rows),
        "schema_version": SCHEMA_VERSION,
        "content_sha256": hashlib.sha256(
            json.dumps(rows, indent=2, sort_keys=True).encode("utf-8")
        ).hexdigest(),
    }
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def load_statcast_season(season: int, data_dir: Path) -> dict[str, dict]:
    """{mlbam_id: statcast_row} for a season; empty dict if not pulled."""
    path = _season_path(season, data_dir)
    if not path.exists():
        return {}
    return {r["mlbam_id"]: r for r in json.loads(path.read_text(encoding="utf-8"))}


def pull_statcast_season(season: int, data_dir: Path) -> int:
    """Fetch both leaderboards, merge, coverage-check, store. Returns row count."""
    expected = parse_expected_stats(_fetch(EXPECTED_URL.format(year=season)))
    quality = parse_quality(_fetch(QUALITY_URL.format(year=season)))
    rows = merge_statcast(expected, quality)
    assert_coverage(season, len(rows))
    store_statcast_season(season, rows, data_dir)
    return len(rows)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_store.py" -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/data/statcast.py tests/test_statcast_store.py
git commit -m "feat: Statcast snapshot store/load/merge + fail-loud undercoverage guard"
```

---

## Task 4: League XBH mix helper

**Files:**
- Create: `projections/models/statcast_denoise.py`
- Test: `tests/test_statcast_denoise.py`

- [ ] **Step 1: Write the failing test**

```python
import unittest
from projections.models.statcast_denoise import league_xbh_mix


class TestLeagueXbhMix(unittest.TestCase):
    def test_mix_proportions_and_m(self):
        # League totals: 2B=200, 3B=20, HR=180 -> XB=400.
        rows = [{"2B": 200, "3B": 20, "HR": 180}]
        props, m = league_xbh_mix(rows)
        self.assertAlmostEqual(props[0], 200 / 400)   # 2B share
        self.assertAlmostEqual(props[2], 180 / 400)   # HR share
        # m = (2*200 + 3*20 + 4*180) / 400 = (400+60+720)/400 = 1180/400 = 2.95
        self.assertAlmostEqual(m, 2.95)

    def test_no_xbh_returns_none(self):
        self.assertIsNone(league_xbh_mix([{"2B": 0, "3B": 0, "HR": 0}]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_denoise.py" -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `projections/models/statcast_denoise.py`:

```python
"""Statcast input de-noising bridge: blend historical hit components toward
xBA/xSLG, redistribute into 1B/2B/3B/HR by the player's own extra-base mix,
with feasibility guards. alpha=0 is an exact passthrough (classic)."""
from __future__ import annotations

from collections.abc import Sequence


def league_xbh_mix(rows: Sequence[dict]) -> tuple[tuple[float, float, float], float] | None:
    """League-average extra-base shape from a season's rows:
    ((2B_share, 3B_share, HR_share), m) where m = total bases per XB hit.
    None if the league has no extra-base hits (degenerate)."""
    d = sum(float(r.get("2B", 0)) for r in rows)
    t = sum(float(r.get("3B", 0)) for r in rows)
    hr = sum(float(r.get("HR", 0)) for r in rows)
    xb = d + t + hr
    if xb <= 0:
        return None
    m = (2 * d + 3 * t + 4 * hr) / xb
    return ((d / xb, t / xb, hr / xb), m)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_denoise.py" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/models/statcast_denoise.py tests/test_statcast_denoise.py
git commit -m "feat: league XBH mix helper for de-noise fallback"
```

---

## Task 5: The de-noise bridge (`denoise_components` + `denoise_season`)

**Files:**
- Modify: `projections/models/statcast_denoise.py` (append)
- Test: `tests/test_statcast_denoise.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_statcast_denoise.py`:

```python
from projections.models.statcast_denoise import denoise_components, denoise_season


class TestDenoiseComponents(unittest.TestCase):
    def setUp(self):
        # 1B=100,2B=20,3B=2,HR=18,AB=500 -> H=140, TB=218, XB=40, m=2.95.
        self.row = {"1B": 100, "2B": 20, "3B": 2, "HR": 18, "AB": 500,
                    "PA": 560, "BB": 50, "SO": 100}

    def test_alpha_zero_is_passthrough(self):
        out = denoise_components(self.row, {"xba": 0.30, "xslg": 0.52},
                                 alpha_contact=0.0, alpha_power=0.0, league_mix=None)
        self.assertEqual(out["1B"], 100)
        self.assertEqual(out["HR"], 18)

    def test_missing_statcast_is_passthrough(self):
        out = denoise_components(self.row, None, 0.5, 0.5, None)
        self.assertEqual(out["HR"], 18)

    def test_hand_computed_redistribution(self):
        # xba=.30, xslg=.52, alpha=.5 each. Hand math:
        # H* = 500*(.5*.28 + .5*.30) = 145 ; TB* = 500*(.5*.436 + .5*.52) = 239
        # XB' = (239-145)/(2.95-1) = 48.205 ; 1B' = 96.795 ; HR' = 48.205*.45 = 21.692
        out = denoise_components(self.row, {"xba": 0.30, "xslg": 0.52}, 0.5, 0.5, None)
        h = out["1B"] + out["2B"] + out["3B"] + out["HR"]
        tb = out["1B"] + 2 * out["2B"] + 3 * out["3B"] + 4 * out["HR"]
        self.assertAlmostEqual(h, 145.0, places=2)
        self.assertAlmostEqual(tb, 239.0, places=2)
        self.assertAlmostEqual(out["1B"], 96.795, places=2)
        self.assertAlmostEqual(out["HR"], 21.692, places=2)
        self.assertEqual(out["AB"], 500)        # AB is a playing-time fact: untouched
        self.assertEqual(out["BB"], 50)         # non-hit components untouched

    def test_hits_clamped_to_ab(self):
        # Impossible xba=2.0 with full weight -> H* clamped to AB.
        out = denoise_components({"1B": 100, "2B": 0, "3B": 0, "HR": 0, "AB": 300},
                                 {"xba": 2.0, "xslg": 2.0}, 1.0, 0.0, ((0.5, 0.0, 0.5), 3.0))
        h = out["1B"] + out["2B"] + out["3B"] + out["HR"]
        self.assertLessEqual(h, 300.0)

    def test_xb_clamp_prioritizes_coherence_over_xslg(self):
        # Huge xslg forces XB' > H* -> clamp to H*, all hits become XB, 1B'=0,
        # realized TB < TB* (coherence kept).
        out = denoise_components(self.row, {"xba": 0.28, "xslg": 1.50}, 0.0, 1.0, None)
        self.assertAlmostEqual(out["1B"], 0.0, places=6)
        h = out["1B"] + out["2B"] + out["3B"] + out["HR"]
        self.assertAlmostEqual(h, 140.0, places=2)   # H unchanged (alpha_contact=0)

    def test_zero_xbh_uses_league_mix_not_hr_lock(self):
        # Player with only singles + high xslg: league mix gives them HR > 0.
        row = {"1B": 120, "2B": 0, "3B": 0, "HR": 0, "AB": 500}
        out = denoise_components(row, {"xba": 0.24, "xslg": 0.45},
                                 0.0, 1.0, ((0.5, 0.05, 0.45), 2.9))
        self.assertGreater(out["HR"], 0.0)

    def test_zero_xbh_no_league_mix_falls_back_classic_power(self):
        row = {"1B": 120, "2B": 0, "3B": 0, "HR": 0, "AB": 500}
        out = denoise_components(row, {"xba": 0.24, "xslg": 0.45}, 0.0, 1.0, None)
        self.assertEqual(out["HR"], 0.0)   # no league mix -> no invented power


class TestDenoiseSeason(unittest.TestCase):
    def test_season_passthrough_at_alpha_zero(self):
        rows = [{"1B": 100, "2B": 20, "3B": 2, "HR": 18, "AB": 500}]
        sc = {"0": {"xba": 0.30, "xslg": 0.52}}
        # mlbam_id keys map rows to statcast; here row has no id -> passthrough anyway,
        # but alpha=0 guarantees identity regardless.
        out = denoise_season(rows, sc, 0.0, 0.0)
        self.assertEqual(out[0]["HR"], 18)

    def test_season_denoises_matched_players(self):
        rows = [{"mlbam_id": "5", "1B": 100, "2B": 20, "3B": 2, "HR": 18, "AB": 500}]
        sc = {"5": {"xba": 0.30, "xslg": 0.52}}
        out = denoise_season(rows, sc, 0.5, 0.5)
        self.assertNotAlmostEqual(out[0]["HR"], 18)   # moved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_denoise.py" -v`
Expected: FAIL — `ImportError: cannot import name 'denoise_components'`.

- [ ] **Step 3: Implement (append to `projections/models/statcast_denoise.py`)**

```python
def denoise_components(
    row: dict,
    statcast: dict | None,
    alpha_contact: float,
    alpha_power: float,
    league_mix: tuple[tuple[float, float, float], float] | None,
) -> dict:
    """Return a copy of `row` with 1B/2B/3B/HR de-noised toward xBA/xSLG.
    Non-hit fields (PA, AB, BB, SO, ...) are preserved. Passthrough when there is
    no Statcast, AB<=0, or both alphas are 0."""
    out = dict(row)
    ab = float(row.get("AB", 0))
    if statcast is None or ab <= 0 or (alpha_contact == 0.0 and alpha_power == 0.0):
        return out

    s, d, t, hr = (float(row.get(k, 0)) for k in ("1B", "2B", "3B", "HR"))
    H = s + d + t + hr
    TB = s + 2 * d + 3 * t + 4 * hr
    xb = d + t + hr
    xba, xslg = statcast.get("xba"), statcast.get("xslg")

    # 1. De-noise the two aggregates (blend actual rate toward expected).
    if xba is not None and alpha_contact > 0:
        h_star = ab * ((1 - alpha_contact) * (H / ab) + alpha_contact * xba)
    else:
        h_star = H
    h_star = min(max(h_star, 0.0), ab)                 # clamp [0, AB]

    if xslg is not None and alpha_power > 0:
        tb_star = ab * ((1 - alpha_power) * (TB / ab) + alpha_power * xslg)
    else:
        tb_star = TB
    tb_star = max(tb_star, h_star)                     # TB >= H

    # 2. Pick the XBH shape: player's own, else league fallback, else classic power.
    if xb > 0:
        m = (2 * d + 3 * t + 4 * hr) / xb
        props = (d / xb, t / xb, hr / xb)
    elif league_mix is not None:
        props, m = league_mix
    else:
        out["1B"], out["2B"], out["3B"], out["HR"] = h_star, 0.0, 0.0, 0.0
        return out                                     # classic power: all singles

    # 3. Redistribute, clamping XB' (coherence over exact xSLG).
    xb_prime = (tb_star - h_star) / (m - 1) if m > 1 else 0.0
    xb_prime = min(max(xb_prime, 0.0), h_star)
    out["1B"] = max(0.0, h_star - xb_prime)
    out["2B"] = max(0.0, xb_prime * props[0])
    out["3B"] = max(0.0, xb_prime * props[1])
    out["HR"] = max(0.0, xb_prime * props[2])
    return out


def denoise_season(
    rows: Sequence[dict],
    statcast_map: dict[str, dict],
    alpha_contact: float,
    alpha_power: float,
) -> list[dict]:
    """De-noise every row in a season. The league XBH mix is computed from the
    season's actual rows (the reference distribution for zero-XBH players)."""
    league_mix = league_xbh_mix(rows)
    return [
        denoise_components(r, statcast_map.get(r.get("mlbam_id")),
                           alpha_contact, alpha_power, league_mix)
        for r in rows
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_statcast_denoise.py" -v`
Expected: PASS (2 mix + 7 component + 2 season = 11 tests).

- [ ] **Step 5: Commit**

```bash
git add projections/models/statcast_denoise.py tests/test_statcast_denoise.py
git commit -m "feat: Statcast de-noise bridge with feasibility guards"
```

---

## Task 6: Wire de-noising into `build_marcel_projections`

**Files:**
- Modify: `projections/export/marcel_run.py`
- Test: `tests/test_marcel_run.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_marcel_run.py` (reuses `_seed_many` from Task 5 of Rung 2):

```python
    def _seed_statcast(self, data_dir):
        from projections.data.statcast import store_statcast_season
        # High xslg for player 7 so de-noising visibly moves their line.
        for yr in (2019, 2020, 2021, 2022, 2023):
            store_statcast_season(yr, [
                {"mlbam_id": "5", "xba": 0.270, "xslg": 0.470, "xwoba": 0.340},
                {"mlbam_id": "7", "xba": 0.250, "xslg": 0.520, "xwoba": 0.350},
            ], data_dir)

    def test_alpha_zero_matches_classic_build(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            self._seed_statcast(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"}, "7": {"birth_date": "1994-01-01"}}
            classic = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            a0 = build_marcel_projections(
                2024, data_dir, MarcelParams(alpha_contact=0.0, alpha_power=0.0), idents)
            self.assertEqual([r["stats"] for r in classic], [r["stats"] for r in a0])

    def test_alpha_positive_changes_projection(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            self._seed_statcast(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"}, "7": {"birth_date": "1994-01-01"}}
            classic = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            tuned = build_marcel_projections(
                2024, data_dir, MarcelParams(alpha_contact=0.5, alpha_power=0.5), idents)
            c = {r["id"]: r["stats"]["SLG"] for r in classic}
            t = {r["id"]: r["stats"]["SLG"] for r in tuned}
            self.assertTrue(any(abs(c[k] - t[k]) > 1e-9 for k in c))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_run.py" -v`
Expected: FAIL — `test_alpha_positive_changes_projection` fails (alphas ignored; classic == tuned).

- [ ] **Step 3: Implement**

In `projections/export/marcel_run.py`, add imports:

```python
from projections.data.statcast import load_statcast_season
from projections.models.statcast_denoise import denoise_season
```

Then, inside `build_marcel_projections`, after `snaps` is built and before `index_maps`, de-noise each prior season using its Statcast snapshot and the params' alphas:

```python
    # Statcast input de-noising (Rung 3): blend each prior season's hit components
    # toward xBA/xSLG before Marcel weights them. alpha=0 -> exact passthrough.
    snaps = [
        denoise_season(snap, load_statcast_season(yr, data_dir),
                       params.alpha_contact, params.alpha_power)
        for yr, snap in zip(prior_years, snaps)
    ]
```

(Place this immediately after the `snaps`/`league` block and before `index_maps = [...]`. The league means in `compute_league_rates` are computed from the *actual* snaps just above; keeping league means on actual rates is intentional — only the per-player inputs are de-noised.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_marcel_run.py" -v`
Expected: PASS (existing 5 + 2 new). `test_alpha_zero_matches_classic_build` guards backward compatibility.

- [ ] **Step 5: Commit**

```bash
git add projections/export/marcel_run.py tests/test_marcel_run.py
git commit -m "feat: de-noise prior seasons in build (alpha=0 nests classic)"
```

---

## Task 7: `coordinate_descent_alpha` tuning

**Files:**
- Modify: `projections/backtest/tune.py`
- Test: `tests/test_tune.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_tune.py`:

```python
    def test_coordinate_descent_alpha_returns_params_and_score(self):
        from projections.backtest.tune import coordinate_descent_alpha
        from projections.data.statcast import store_statcast_season
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
                store_statcast_season(yr, [
                    {"mlbam_id": "5", "xba": 0.27, "xslg": 0.47, "xwoba": 0.34},
                    {"mlbam_id": "7", "xba": 0.25, "xslg": 0.52, "xwoba": 0.35},
                ], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"}, "7": {"birth_date": "1990-01-01"}}
            best, score = coordinate_descent_alpha(
                [2022, 2023], data_dir, idents,
                ac_values=(0.0, 0.5), ap_values=(0.0, 0.5),
            )
            self.assertIn(best.alpha_contact, (0.0, 0.5))
            self.assertIn(best.alpha_power, (0.0, 0.5))
            self.assertEqual(best.gamma, 0.0)         # gamma stays classic (isolation)
            self.assertIsInstance(score, float)

    def test_existing_coordinate_descent_still_works(self):
        # Refactor must not break the Rung 2 entry point.
        from projections.backtest.tune import coordinate_descent
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"}, "7": {"birth_date": "1990-01-01"}}
            best, _ = coordinate_descent(
                [2022, 2023], data_dir, idents,
                n_reg_values=(1200.0,), gamma_values=(0.0,))
            self.assertEqual((best.n_reg, best.gamma), (1200.0, 0.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_tune.py" -v`
Expected: FAIL — `ImportError: cannot import name 'coordinate_descent_alpha'`.

- [ ] **Step 3: Implement (refactor to a shared private descent + two wrappers)**

In `projections/backtest/tune.py`, replace the existing `coordinate_descent` function body with a shared private descent and two thin wrappers. The new code:

```python
def _descend(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    axes: list[tuple[str, tuple[float, ...]]],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Coordinate descent from classic Marcel over the given (field, values) axes.
    Objective: minimize tuning-block mean_mae_ratio vs persistence. Starting at
    classic means it can never do worse than classic on the tuning block."""
    best = MarcelParams()
    best_score = rolling_origin(tuning_seasons, data_dir, best, identities)["mean_mae_ratio"]
    for _ in range(max_rounds):
        improved = False
        for field, values in axes:
            for v in values:
                cand = replace(best, **{field: v})
                score = rolling_origin(tuning_seasons, data_dir, cand, identities)["mean_mae_ratio"]
                if score < best_score:
                    best, best_score, improved = cand, score, True
        if not improved:
            break
    return best, best_score


def coordinate_descent(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    n_reg_values: tuple[float, ...],
    gamma_values: tuple[float, ...],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Rung 2: tune (gamma, n_reg_base)."""
    return _descend(tuning_seasons, data_dir, identities,
                    [("gamma", gamma_values), ("n_reg", n_reg_values)], max_rounds)


def coordinate_descent_alpha(
    tuning_seasons: list[int],
    data_dir: Path,
    identities: dict[str, dict],
    ac_values: tuple[float, ...],
    ap_values: tuple[float, ...],
    max_rounds: int = 3,
) -> tuple[MarcelParams, float]:
    """Rung 3: tune (alpha_contact, alpha_power), gamma/n_reg held classic."""
    return _descend(tuning_seasons, data_dir, identities,
                    [("alpha_contact", ac_values), ("alpha_power", ap_values)], max_rounds)
```

(Delete the old `coordinate_descent` body; keep `default_grid` and `grid_search` untouched. `replace` is already imported from Rung 2.)

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -p "test_tune.py" -v`
Expected: PASS (existing 4 + 2 new). The Rung-2 regression test confirms the refactor preserved `coordinate_descent`.

- [ ] **Step 5: Commit**

```bash
git add projections/backtest/tune.py tests/test_tune.py
git commit -m "feat: coordinate_descent_alpha via shared _descend (Rung 2 entry intact)"
```

---

## Task 8: One-time Statcast data pull (network) + full-suite regression

**Files:**
- Data: `projections/data/statcast/` (committed snapshots)

- [ ] **Step 1: Full-suite regression first**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests`
Expected: all green (478 baseline + the new Rung 3 tests). Backward-compat tests (Tasks 1 & 6 `alpha=0`) confirm the classic path is unchanged.

- [ ] **Step 2: Pull 2015–2025 Statcast snapshots**

Run (network; ~22 requests):
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.statcast import pull_statcast_season
d = Path('projections/data')
for yr in range(2015, 2026):
    print(yr, pull_statcast_season(yr, d))
"
```
Expected: a row count per season (~550–660 normal; 2020 lower for the COVID-short season but well above the 250 floor). If any season raises the undercoverage guard, **stop and investigate the endpoint** — do not lower the floor to force it through.

- [ ] **Step 3: Sanity-check coverage vs the eval population**

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.statcast import load_statcast_season
from projections.data.historical import load_season
d = Path('projections/data')
for yr in (2019, 2020, 2023):
    sc = load_statcast_season(yr, d); hist = {r['mlbam_id'] for r in load_season(yr, d)}
    covered = sum(1 for pid in hist if pid in sc)
    print(yr, 'statcast rows', len(sc), '| historical hitters', len(hist), '| covered', covered)
"
```
Expected: `covered` comfortably exceeds the ~330 qualified-PA eval population each season.

- [ ] **Step 4: Commit the data**

```bash
git add projections/data/statcast/
git commit -m "data: Statcast hitting snapshots 2015-2025 (Savant, min=1)"
```

---

## Task 9: The verdict — beat classic with carryover + coverage report

**Files:** none (manual run + record)

- [ ] **Step 1: Run the held-out verdict (tune 2018–19, score 2020–25)**

Run:
```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "
from pathlib import Path
from projections.data.identity import load_identity_store
from projections.data.statcast import load_statcast_season
from projections.data.historical import load_season
from projections.backtest.harness import rolling_origin, vs_classic
from projections.backtest.tune import coordinate_descent_alpha
from projections.models.marcel_params import MarcelParams
d = Path('projections/data')
idents = load_identity_store(d)

# Statcast-covered prior-season share per target (transparency).
def covered_share(T):
    shares = []
    for t in T:
        cov = sum(1 for yr in (t-1,t-2,t-3) if load_statcast_season(yr, d)) 
        shares.append((t, f'{cov}/3'))
    return shares
print('tuning prior coverage:', covered_share([2018,2019]))
print('scoring prior coverage:', covered_share(list(range(2020,2026))))

tune_t, score_t = [2018, 2019], list(range(2020, 2026))
AC = (0.0, 0.25, 0.5, 0.75, 1.0); AP = (0.0, 0.25, 0.5, 0.75, 1.0)
best, _ = coordinate_descent_alpha(tune_t, d, idents, AC, AP)
print('locked alphas: contact', best.alpha_contact, 'power', best.alpha_power)
classic = MarcelParams()
tv = vs_classic(rolling_origin(tune_t, d, best, idents)['seasons'],
                rolling_origin(tune_t, d, classic, idents)['seasons'])
sv = vs_classic(rolling_origin(score_t, d, best, idents)['seasons'],
                rolling_origin(score_t, d, classic, idents)['seasons'])
print('TUNING  vs classic: ratio', round(tv['mean_ratio_vs_classic'],4), 'corr_win', round(tv['corr_win_rate'],3), 'beats', tv['beats_classic'])
print('SCORING vs classic: ratio', round(sv['mean_ratio_vs_classic'],4), 'corr_win', round(sv['corr_win_rate'],3), 'beats', sv['beats_classic'])
print('VERDICT:', 'WIN' if sv['beats_classic'] else 'TIE')
"
```
Expected — one of two honest outcomes:
- **WIN:** `alpha > 0`, `SCORING beats True` → Statcast de-noising beats classic and carries. Success criterion #4 (win branch).
- **TIE:** `alpha ≈ 0` or scoring doesn't beat → de-noising doesn't beat classic; record plainly. **Do not expand the grid to chase a scoring-block win** (leakage).

- [ ] **Step 2: Record the verdict**

Add a `VERDICT` header + an "Execution Verdict" section to this plan (alphas, both-block ratios, coverage shares, WIN/TIE), mirroring the Rung 2 plan. Then:

```bash
git add docs/plans/2026-06-02-projections-rung3-statcast-inputs.md
git commit -m "chore: rung 3 Statcast de-noising complete — <WIN|TIE> vs classic"
```

---

## Self-Review (completed during authoring)

- **Spec coverage:** data layer with `min=1` + undercoverage guard (T2, T3, T8); immutable snapshots joined by `mlbam_id` (T3); the bridge incl. all four guard families — H* clamp, TB*≥H*, XB' clamp-coherence, zero-XBH league fallback / classic-power fallback, missing-Statcast passthrough (T5); `alpha` knobs with `α=0` nesting classic (T1); `gamma=0` isolation (enforced — `coordinate_descent_alpha` never touches gamma, T7); de-noise wired pre-weighting, league means on actual rates (T6); Statcast-aware tuning 2018–19 / scoring 2020–25 + coverage-share report (T9); barrel%/EV stored observe-only, never read by the bridge (T2/T3). All spec sections map to a task.
- **Placeholder scan:** no TBD/TODO; every code step is complete; T9's expected output is a genuine WIN/TIE branch, not a placeholder.
- **Type consistency:** `parse_expected_stats`/`parse_quality` → `merge_statcast` → `store/load_statcast_season` (returns `{mlbam_id: row}`) consumed by `denoise_season` (T5/T6). `denoise_components(row, statcast, alpha_contact, alpha_power, league_mix)` and `league_xbh_mix(rows) -> ((p2b,p3b,phr), m) | None` consistent across T4/T5/T6. `MarcelParams.alpha_contact/alpha_power` (T1) read in `denoise_season` via `build` (T6) and varied through `replace` in `_descend` (T7). `load_statcast_season` used in T6/T8/T9. `vs_classic`/`rolling_origin` reused from Rung 2 (T9).

---

## Execution Verdict (2026-06-02)

**Outcome: WIN.** Statcast input de-noising beats classic Marcel on held-out data — the first
lever in the program to do so (Rung 1 global-knob tuning and Rung 2 reliability-weighting both tied).

**Setup:** tune `(alpha_contact, alpha_power)` by coordinate descent on **2018–2019**, score on the
disjoint **2020–2025**. Every target in both blocks has 3/3 Statcast-covered prior seasons (so the
result is not diluted by fallback-classic). Grid NOT expanded after seeing the scoring block.

**Locked params:** `alpha_contact = 0.75, alpha_power = 0.5` (substantial — the model genuinely leans
on Statcast, not a near-zero degenerate).

**Held-out result (vs classic):**
- TUNING block: mean MAE ratio 0.9845, corr-win 0.444.
- SCORING block: mean MAE ratio **0.9792**, corr-win 0.519, `beats_classic=True`. Edge carries.

**Per-stat (scoring block) — the win is where it should be:**
| stat | MAE ratio | corr Δ |
|------|-----------|--------|
| AVG  | 0.9416 | +0.0292 |
| OBP  | 0.9585 | +0.0293 |
| SLG  | 0.9598 | +0.0450 |
| OPS  | 0.9513 | +0.0484 |
| HR   | 1.0014 | +0.0076 |
| PA/R/RBI/SB | 1.0000 | +0.0000 (untouched, as designed) |

**Honest read:** a **modest but real** win — 4–6% MAE reduction *plus* better correlation on the
de-noised rate stats (AVG/OBP/SLG/OPS), exactly the stats xBA/xSLG target and where classic Marcel is
weakest. HR is ~neutral (already a reliable stat; the bridge moves it only via mix+xSLG). Counting
stats untouched. The aggregate 0.979 is diluted by the untouched stats — the de-noised-stat
improvement is the real headline. Correlation-win (0.519) is marginal; the robust signal is MAE.

**Consequence:** confirms the program thesis — **better inputs beat regression tuning.** Statcast is
the lever. Natural follow-ups (future rungs): barrel%/EV-driven HR de-noising (HR was the one
de-noised-family stat that didn't move), de-noising + reliability-weighting combined now that Statcast
alone has earned it, and wiring a Statcast-de-noised source into the app behind the existing seam.

**Production impact:** none yet. `alpha_contact=alpha_power=0` is the default; the classic path is
byte-for-byte unchanged (backward-compat tests). Shipping a de-noised run is a deliberate later step.
