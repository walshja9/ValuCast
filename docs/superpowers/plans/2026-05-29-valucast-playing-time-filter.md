# ValuCast Playing-Time Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drop ~87% low-sample filler players (median 1 PA / 1 IP) before valuation so category baselines, SGP denominators, and ratio baselines are computed from real players only — with an ID-based bypass that keeps specific players valuable and consistent across the ranking, detail, and compare views.

**Architecture:** A pure `filter_by_playing_time()` function in the `league_values` library filters a `PlayerProjection` list by per-pool PA/IP thresholds, with a two-way-tolerant `always_keep` bypass joined on the shared `base_id`. `app.py` holds the threshold constants and a single `_valuation_players()` helper that every `engine.value_players()` call routes through, passing the IDs each view must retain.

**Tech Stack:** Python 3.10+, Flask, pytest (config in `pyproject.toml`: `pythonpath=["src"]`, `testpaths=["tests"]`), unittest-style test classes. Run tests with `py -m pytest`.

**Spec:** `docs/superpowers/specs/2026-05-29-valucast-playing-time-filter-design.md`

---

## File Structure

- **Create** `src/league_values/playing_time.py` — the pure filter function + `strip_suffix` helper. One responsibility: decide which players survive playing-time thresholds.
- **Create** `tests/test_playing_time.py` — unit tests for the filter function.
- **Modify** `src/league_values/__init__.py` — export `filter_by_playing_time`.
- **Modify** `app.py` — threshold constants, `_valuation_players()` helper, and the three `engine.value_players(store.get_all(), ...)` call sites (ranking in `_build_context`, `/player_detail`, `/compare`).
- **Modify** `tests/test_app.py` — integration tests: sub-threshold player absent by default, present when searched, Ohtani two-way survives.

---

## Task 1: The pure filter function

**Files:**
- Create: `src/league_values/playing_time.py`
- Test: `tests/test_playing_time.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_playing_time.py`:

```python
import unittest

from league_values.models import PlayerProjection
from league_values.playing_time import filter_by_playing_time, strip_suffix


def _hitter(pid, pa=None, ab=None, base_id=None, name="H"):
    stats = {}
    if pa is not None:
        stats["PA"] = pa
    if ab is not None:
        stats["AB"] = ab
    meta = {"base_id": base_id} if base_id else {}
    return PlayerProjection(id=pid, name=name, pool="hitter", stats=stats, metadata=meta)


def _pitcher(pid, ip, pool="starter", base_id=None, name="P"):
    meta = {"base_id": base_id} if base_id else {}
    return PlayerProjection(id=pid, name=name, pool=pool, stats={"IP": ip}, metadata=meta)


THRESH = dict(hitter_pa=100, sp_ip=40, rp_ip=20)


class TestStripSuffix(unittest.TestCase):
    def test_strips_pitcher_suffix(self):
        self.assertEqual(strip_suffix("19755_P"), "19755")

    def test_strips_hitter_suffix(self):
        self.assertEqual(strip_suffix("19755_H"), "19755")

    def test_leaves_plain_id(self):
        self.assertEqual(strip_suffix("19755"), "19755")

    def test_leaves_base_id_namespace(self):
        self.assertEqual(strip_suffix("mlbam_660271"), "mlbam_660271")


class TestPlayingTimeFilter(unittest.TestCase):
    def test_hitter_kept_at_threshold(self):
        kept = filter_by_playing_time([_hitter("a", pa=100)], **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_hitter_dropped_below_threshold(self):
        kept = filter_by_playing_time([_hitter("a", pa=99)], **THRESH)
        self.assertEqual(kept, [])

    def test_hitter_uses_ab_when_pa_missing(self):
        kept = filter_by_playing_time([_hitter("a", ab=150)], **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_hitter_missing_volume_dropped(self):
        kept = filter_by_playing_time([_hitter("a")], **THRESH)
        self.assertEqual(kept, [])

    def test_starter_threshold(self):
        players = [_pitcher("a", 40), _pitcher("b", 39)]
        kept = filter_by_playing_time(players, **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_reliever_threshold(self):
        players = [_pitcher("a", 20, pool="reliever"), _pitcher("b", 19, pool="reliever")]
        kept = filter_by_playing_time(players, **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_generic_pitcher_uses_rp_bar(self):
        # generic 'pitcher' pool: 25 IP clears rp_ip(20) but not sp_ip(40) -> kept
        kept = filter_by_playing_time([_pitcher("a", 25, pool="pitcher")], **THRESH)
        self.assertEqual([p.id for p in kept], ["a"])

    def test_always_keep_retains_subthreshold_by_id(self):
        kept = filter_by_playing_time([_hitter("a", pa=1)], **THRESH, always_keep={"a"})
        self.assertEqual([p.id for p in kept], ["a"])

    def test_two_way_kept_by_display_id(self):
        # both rows share base_id; passing the hitter display id keeps both
        players = [
            _hitter("19755", pa=1, base_id="mlbam_660271"),
            _pitcher("19755_P", 1, base_id="mlbam_660271"),
        ]
        kept = filter_by_playing_time(players, **THRESH, always_keep={"19755"})
        self.assertEqual({p.id for p in kept}, {"19755", "19755_P"})

    def test_two_way_kept_by_suffixed_id(self):
        players = [
            _hitter("19755", pa=1, base_id="mlbam_660271"),
            _pitcher("19755_P", 1, base_id="mlbam_660271"),
        ]
        kept = filter_by_playing_time(players, **THRESH, always_keep={"19755_P"})
        self.assertEqual({p.id for p in kept}, {"19755", "19755_P"})

    def test_two_way_kept_by_base_id(self):
        players = [
            _hitter("19755", pa=1, base_id="mlbam_660271"),
            _pitcher("19755_P", 1, base_id="mlbam_660271"),
        ]
        kept = filter_by_playing_time(players, **THRESH, always_keep={"mlbam_660271"})
        self.assertEqual({p.id for p in kept}, {"19755", "19755_P"})

    def test_subthreshold_without_base_id_kept_by_stripped_id(self):
        # no base_id: matched by its own suffix-stripped id
        kept = filter_by_playing_time([_hitter("99_H", pa=1)], **THRESH, always_keep={"99"})
        self.assertEqual([p.id for p in kept], ["99_H"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `py -m pytest tests/test_playing_time.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'league_values.playing_time'`

- [ ] **Step 3: Write the implementation**

Create `src/league_values/playing_time.py`:

```python
from __future__ import annotations

from typing import Iterable

from .models import PlayerProjection, PlayerPool

_SUFFIXES = ("_P", "_H")


def strip_suffix(player_id: str) -> str:
    """Remove a trailing two-way dedupe suffix (_P / _H) added by ProjectionStore."""
    for suffix in _SUFFIXES:
        if player_id.endswith(suffix):
            return player_id[: -len(suffix)]
    return player_id


def _base(player: PlayerProjection) -> str:
    return player.metadata.get("base_id") or strip_suffix(player.id)


def _meets_threshold(
    player: PlayerProjection,
    hitter_pa: float,
    sp_ip: float,
    rp_ip: float,
) -> bool:
    if player.pool is PlayerPool.HITTER:
        volume = player.stats.get("PA", 0.0) or player.stats.get("AB", 0.0)
        return volume >= hitter_pa
    if player.pool is PlayerPool.STARTER:
        return player.stats.get("IP", 0.0) >= sp_ip
    if player.pool is PlayerPool.RELIEVER:
        return player.stats.get("IP", 0.0) >= rp_ip
    if player.pool is PlayerPool.PITCHER:
        # ambiguous generic pitcher (none in current data): use the lower bar
        return player.stats.get("IP", 0.0) >= rp_ip
    return True


def filter_by_playing_time(
    players: Iterable[PlayerProjection],
    *,
    hitter_pa: float,
    sp_ip: float,
    rp_ip: float,
    always_keep: Iterable[str] = frozenset(),
) -> list[PlayerProjection]:
    """Keep players clearing their pool's PA/IP bar, plus any in always_keep.

    The always_keep bypass joins two-way siblings on their shared base_id, so
    passing any identifier of a two-way player (display id, suffixed id, or
    base_id) retains both the hitter and pitcher rows.
    """
    players = list(players)
    keep_ids = set(always_keep)
    keep_bases = {strip_suffix(k) for k in keep_ids}

    # Pass 1: any explicitly kept id contributes its base to the keep set.
    for player in players:
        if player.id in keep_ids:
            keep_bases.add(_base(player))

    # Pass 2: retain by threshold, exact id, or shared base.
    return [
        player
        for player in players
        if _meets_threshold(player, hitter_pa, sp_ip, rp_ip)
        or player.id in keep_ids
        or _base(player) in keep_bases
    ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_playing_time.py -q`
Expected: PASS (16 tests)

- [ ] **Step 5: Commit**

```bash
git add src/league_values/playing_time.py tests/test_playing_time.py
git commit -m "feat: add filter_by_playing_time with two-way-tolerant bypass"
```

---

## Task 2: Export the function from the package

**Files:**
- Modify: `src/league_values/__init__.py`

- [ ] **Step 1: Add the import**

In `src/league_values/__init__.py`, after the `from .post_processors import ...` line (line 16), add:

```python
from .playing_time import filter_by_playing_time
```

- [ ] **Step 2: Add to `__all__`**

In the `__all__` list, add `"filter_by_playing_time",` in alphabetical position (after `"PostProcessor",`):

```python
    "PostProcessor",
    "ReplacementLevel",
    "RosterSettings",
    "ScoringMode",
    "ValuationEngine",
    "ValuationResult",
    "VolumeMultiplier",
    "filter_by_playing_time",
    "load_league_config",
    "value_players",
```

- [ ] **Step 3: Verify the import works**

Run: `py -c "from league_values import filter_by_playing_time; print('ok')"`
(Run from repo root with `src` on path — pytest does this automatically; for the bare command use `py -c "import sys; sys.path.insert(0,'src'); from league_values import filter_by_playing_time; print('ok')"`.)
Expected: `ok`

- [ ] **Step 4: Run the full suite to confirm nothing broke**

Run: `py -m pytest -q`
Expected: PASS (existing 396 + 16 new)

- [ ] **Step 5: Commit**

```bash
git add src/league_values/__init__.py
git commit -m "feat: export filter_by_playing_time from league_values"
```

---

## Task 3: Threshold constants and the shared `_valuation_players()` helper

**Files:**
- Modify: `app.py` (imports near line 15; constants/helper near line 38)

- [ ] **Step 1: Import the filter**

In `app.py`, change the import on line 15 from:

```python
from league_values.post_processors import VolumeMultiplier
```
to:
```python
from league_values.post_processors import VolumeMultiplier
from league_values.playing_time import filter_by_playing_time
```

- [ ] **Step 2: Add constants and helper after the engine is defined**

In `app.py`, immediately after line 38 (`engine = ValuationEngine(post_processors=[VolumeMultiplier()])`), add:

```python
# Playing-time floor: drop low-sample filler before valuation so category
# baselines are computed from real players only. VolumeMultiplier still
# discounts the partial-season players that survive these floors.
MIN_HITTER_PA = 100
MIN_SP_IP = 40
MIN_RP_IP = 20


def _valuation_players(always_keep=None):
    """Engine input: all projections minus sub-threshold filler.

    `always_keep` is a set of player ids (display id, suffixed id, or base_id)
    that are retained regardless of playing time, with two-way siblings joined
    on shared base_id inside filter_by_playing_time.
    """
    return filter_by_playing_time(
        store.get_all(),
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
        always_keep=always_keep or frozenset(),
    )
```

- [ ] **Step 3: Verify the app still imports**

Run: `py -c "import sys; sys.path.insert(0,'.'); sys.path.insert(0,'src'); import app; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: add playing-time thresholds and _valuation_players helper"
```

---

## Task 4: Route the ranking view through the filter (with search bypass)

**Files:**
- Modify: `app.py` (`_build_context`, the `results = engine.value_players(store.get_all(), config)` at line 328)

- [ ] **Step 1: Write the failing integration tests**

Add to `tests/test_app.py` (new test class at the end of the file):

```python
class TestPlayingTimeFilter(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_subthreshold_player_absent_by_default(self):
        # Brady Ebel = 1.0 PA in current.json; must not appear in default rankings
        response = self.client.get("/")
        self.assertNotIn(b"Brady Ebel", response.data)

    def test_subthreshold_player_present_when_searched(self):
        response = self.client.get("/?search=Brady+Ebel")
        self.assertIn(b"Brady Ebel", response.data)

    def test_qualifying_player_still_shown(self):
        # Sanity: a real everyday player still appears by default
        response = self.client.get("/")
        self.assertIn(b"Ohtani", response.data)
```

Note: `/` renders through `_build_context`; the `index` route returns the rendered template containing player names. If the index route name differs, target the route that renders the rankings table (the one calling `_build_context` and rendering `rankings-table`).

- [ ] **Step 2: Run tests to verify the first one fails**

Run: `py -m pytest tests/test_app.py::TestPlayingTimeFilter -q`
Expected: `test_subthreshold_player_absent_by_default` FAILS (Brady Ebel currently appears because no filter exists). The other two may pass or fail depending on current behavior.

- [ ] **Step 3: Apply the filter in `_build_context`**

In `app.py`, replace line 328:

```python
    results = engine.value_players(store.get_all(), config)
```

with:

```python
    search_keep = (
        {p.id for p in store.get_all() if search.lower() in p.name.lower()}
        if search
        else frozenset()
    )
    results = engine.value_players(_valuation_players(search_keep), config)
```

(`search` is already parsed at line 303 of `_build_context`. The existing post-valuation display filter at lines ~342-344 still narrows the table to the search query — unchanged.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `py -m pytest tests/test_app.py::TestPlayingTimeFilter -q`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_app.py
git commit -m "feat: filter rankings by playing time with search bypass"
```

---

## Task 5: Route `/player_detail` through the filter (consistent valuation)

**Files:**
- Modify: `app.py` (`/player_detail` handler, the `all_results = engine.value_players(store.get_all(), config)` fallback at line ~543 and the surrounding result lookup at lines ~538-544)

- [ ] **Step 1: Read the current handler block**

Locate this block in the `/player_detail` route (around lines 534-544):

```python
    player_proj = store.get_by_id(player_id)
    if not player_proj:
        return "<div class='error'>Player not found</div>", 404

    ctx = _build_context(request.args)
    result = next((r for r in ctx["results"] if r.player.id == player_id), None)

    if result is None:
        config = ctx["config"]
        all_results = engine.value_players(store.get_all(), config)
        result = next((r for r in all_results if r.player.id == player_id), None)
```

- [ ] **Step 2: Replace with a single filtered valuation keyed on `player_id`**

Replace that block with:

```python
    player_proj = store.get_by_id(player_id)
    if not player_proj:
        return "<div class='error'>Player not found</div>", 404

    ctx = _build_context(request.args)
    config = ctx["config"]
    # Value against the filtered pool with this player force-kept, so the detail
    # value matches the ranking value whether or not the player cleared the floor.
    detail_results = engine.value_players(_valuation_players({player_id}), config)
    result = next((r for r in detail_results if r.player.id == player_id), None)
```

- [ ] **Step 3: Verify the route works for a qualifying and a sub-threshold player**

Run (from repo root):

```bash
py -c "import sys; sys.path.insert(0,'.'); sys.path.insert(0,'src'); from app import app, store; c=app.test_client(); \
import json; d=json.load(open('data/projections/current.json')); \
sub=next(p for p in d if p.get('name')=='Brady Ebel'); \
r=c.get('/player_detail/'+str(sub['id'])); print('subthreshold status', r.status_code); print('has name', b'Brady Ebel' in r.data)"
```

Expected: `subthreshold status 200` and `has name True` (route path may differ — confirm the actual `/player_detail` URL pattern in `app.py` and adjust the path in this check).

- [ ] **Step 4: Run the full suite**

Run: `py -m pytest -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: value player detail against filtered pool for consistency"
```

---

## Task 6: Route `/compare` through the filter

**Files:**
- Modify: `app.py` (`/compare` handler, the `all_results = engine.value_players(store.get_all(), config)` at line ~565)

- [ ] **Step 1: Replace the compare valuation**

In the `/compare` route, replace line ~565:

```python
    all_results = engine.value_players(store.get_all(), config)
```

with:

```python
    all_results = engine.value_players(_valuation_players({p1_id, p2_id}), config)
```

(`p1_id` and `p2_id` are already parsed earlier in the handler at lines ~560-561.)

- [ ] **Step 2: Verify compare works for two qualifying players**

Run (from repo root, substituting two real ids — e.g. two everyday hitters):

```bash
py -c "import sys; sys.path.insert(0,'.'); sys.path.insert(0,'src'); from app import app; c=app.test_client(); \
r=c.get('/compare?p1=19755&p2=15986'); print('status', r.status_code)"
```

Expected: `status 200` (adjust ids/route to match the actual `/compare` signature; `15986` = Willy Adames, `19755` = Ohtani, both real ids).

- [ ] **Step 3: Run the full suite**

Run: `py -m pytest -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: value compare against filtered pool"
```

---

## Task 7: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm no remaining unfiltered engine call sites**

Run: `py -c "print()"` then grep:

Run: `grep -n "value_players(store.get_all()" app.py`
Expected: no matches (every engine call now uses `_valuation_players(...)`). The only remaining `store.get_all()` use should be the read-only loop near line 518 and inside `_valuation_players` / `search_keep`.

- [ ] **Step 2: Run the full test suite**

Run: `py -m pytest -q`
Expected: PASS — all existing tests plus 16 (Task 1) + 3 (Task 4) new tests.

- [ ] **Step 3: Manual smoke check of player counts**

Run (from repo root):

```bash
py -c "import sys; sys.path.insert(0,'.'); sys.path.insert(0,'src'); from app import _valuation_players; \
print('engine input size:', len(_valuation_players()))"
```

Expected: ~1,008 players (vs 9,953 unfiltered) — confirms the filter is engaged.

- [ ] **Step 4: Commit any final touch-ups (if needed)**

```bash
git add -A
git commit -m "chore: verify playing-time filter wiring"
```

---

## Notes for the implementer

- **Run all tests from the repo root** (`C:\Users\Alex\Documents\Codex\2026-05-18\league-values`) so `pyproject.toml`'s `pythonpath=["src"]` applies. Use `py -m pytest`, not `python`/`python3` (only `py` resolves on this machine).
- **Do not touch `VolumeMultiplier`** — it stays in the post-processor chain and is complementary to this filter.
- **Do not touch the DD dynasty/prospects paths** (`dd_store`, `_build_dynasty_context`, the `/export` dd branch) — they are out of scope and use a different data source.
- If a route's exact URL pattern or variable name differs from what's quoted here (e.g. `player_id` vs `pid`), match the code you find; the design (filter every engine call through `_valuation_players` with the view's required ids) is what matters.
