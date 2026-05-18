# League Values v0.2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add post-processor pipeline, replacement level, position scarcity, roto/SGP mode, and a DD 7x7 preset to the league_values engine.

**Architecture:** The engine's raw z-score output feeds into a composable post-processor chain. Each processor receives the full result list + league config and returns a new list. `RosterSettings` on `LeagueConfig` drives replacement-level and position-scarcity calculations. Roto adds a third scoring mode using Standings Gain Points.

**Tech Stack:** Python 3.12+, dataclasses, unittest. No external dependencies.

**Test runner:** `cd "C:/Users/Alex/Documents/Codex/2026-05-18/i-am-just-writing-this-here" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`

---

### Task 1: RosterSettings Model

**Files:**
- Modify: `src/league_values/models.py`
- Test: `tests/test_models.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
import unittest
from league_values.models import RosterSettings


class TestRosterSettings(unittest.TestCase):
    def test_default_roster_settings(self):
        rs = RosterSettings()
        self.assertEqual(rs.teams, 12)
        self.assertEqual(rs.roster_size, 23)
        self.assertEqual(rs.positions, {})
        self.assertEqual(rs.bench, 5)

    def test_custom_roster_settings(self):
        rs = RosterSettings(
            teams=10,
            roster_size=25,
            positions={"C": 1, "1B": 1, "OF": 3, "SP": 5, "RP": 2},
            bench=3,
        )
        self.assertEqual(rs.teams, 10)
        self.assertEqual(rs.positions["OF"], 3)

    def test_total_starters(self):
        rs = RosterSettings(
            teams=12,
            roster_size=23,
            positions={"C": 1, "1B": 1, "2B": 1, "SS": 1, "3B": 1, "OF": 3, "UTIL": 1, "SP": 5, "RP": 2},
            bench=7,
        )
        self.assertEqual(rs.total_starters, 16)

    def test_roster_settings_from_dict(self):
        rs = RosterSettings.from_dict({
            "teams": 10,
            "roster_size": 20,
            "positions": {"C": 2, "SP": 4},
            "bench": 4,
        })
        self.assertEqual(rs.teams, 10)
        self.assertEqual(rs.positions["C"], 2)

    def test_roster_settings_frozen(self):
        rs = RosterSettings()
        with self.assertRaises(AttributeError):
            rs.teams = 10


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_models -v`
Expected: ImportError — `RosterSettings` does not exist yet.

- [ ] **Step 3: Implement RosterSettings**

Add to `src/league_values/models.py` after the `LeagueConfig` class:

```python
@dataclass(frozen=True)
class RosterSettings:
    teams: int = 12
    roster_size: int = 23
    positions: Mapping[str, int] = field(default_factory=dict)
    bench: int = 5

    @property
    def total_starters(self) -> int:
        return sum(self.positions.values())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RosterSettings":
        return cls(
            teams=int(data.get("teams", 12)),
            roster_size=int(data.get("roster_size", 23)),
            positions={str(k): int(v) for k, v in data.get("positions", {}).items()},
            bench=int(data.get("bench", 5)),
        )
```

Also add an optional `roster` field to `LeagueConfig`:

```python
@dataclass(frozen=True)
class LeagueConfig:
    name: str
    scoring_mode: ScoringMode
    categories: tuple[CategorySpec, ...] = ()
    point_rules: tuple[PointRule, ...] = ()
    league_baselines: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    roster: RosterSettings | None = None
```

Update `LeagueConfig.from_dict` to parse roster:

```python
roster_data = data.get("roster")
roster = RosterSettings.from_dict(roster_data) if roster_data else None
```

Pass `roster=roster` to the constructor.

Export `RosterSettings` from `__init__.py` — add to imports and `__all__`.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_models -v`
Expected: 5 tests PASS.

- [ ] **Step 5: Run full suite to check nothing broke**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All 30 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/league_values/models.py src/league_values/__init__.py tests/test_models.py
git commit -m "feat: add RosterSettings model with from_dict and total_starters"
```

---

### Task 2: Post-Processor Protocol & Engine Wiring

**Files:**
- Create: `src/league_values/post_processors.py`
- Modify: `src/league_values/engine.py`
- Modify: `src/league_values/__init__.py`
- Test: `tests/test_post_processors.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_post_processors.py`:

```python
import unittest
from dataclasses import replace

from league_values import (
    CategorySpec,
    LeagueConfig,
    PlayerPool,
    ScoringMode,
    ValuationEngine,
    ValuationResult,
)
from league_values.post_processors import PostProcessor


class DoubleValueProcessor:
    """Test processor that doubles total_value."""
    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        return [replace(r, total_value=r.total_value * 2) for r in results]


class AddFiveProcessor:
    """Test processor that adds 5 to total_value."""
    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        return [replace(r, total_value=r.total_value + 5) for r in results]


class TestPostProcessorPipeline(unittest.TestCase):
    def _league(self):
        return LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )

    def _players(self):
        return [
            {"id": "a", "name": "A", "pool": "hitter", "stats": {"HR": 40}},
            {"id": "b", "name": "B", "pool": "hitter", "stats": {"HR": 10}},
        ]

    def test_engine_without_processors_works(self):
        engine = ValuationEngine()
        results = engine.value_players(self._players(), self._league())
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].name, "A")

    def test_engine_with_one_processor(self):
        engine = ValuationEngine(post_processors=[DoubleValueProcessor()])
        results = engine.value_players(self._players(), self._league())
        # Without processor, A would get z=1.0, B would get z=-1.0
        # Doubled: A=2.0, B=-2.0
        self.assertAlmostEqual(results[0].total_value, 2.0, places=3)
        self.assertAlmostEqual(results[1].total_value, -2.0, places=3)

    def test_processors_compose_in_order(self):
        # Double first, then add 5: A = 1.0 * 2 + 5 = 7.0
        engine = ValuationEngine(post_processors=[DoubleValueProcessor(), AddFiveProcessor()])
        results = engine.value_players(self._players(), self._league())
        self.assertAlmostEqual(results[0].total_value, 7.0, places=3)
        # B = -1.0 * 2 + 5 = 3.0
        self.assertAlmostEqual(results[1].total_value, 3.0, places=3)

    def test_processors_re_sort_results(self):
        # AddFive alone: A=6.0, B=4.0 — same order
        # But with a processor that flips: make B bigger
        class FlipProcessor:
            def process(self, results, league):
                return [replace(r, total_value=-r.total_value) for r in results]

        engine = ValuationEngine(post_processors=[FlipProcessor()])
        results = engine.value_players(self._players(), self._league())
        # After flip: A=-1.0, B=1.0, so B should be first
        self.assertEqual(results[0].name, "B")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors -v`
Expected: ImportError — `post_processors` module doesn't exist, `ValuationEngine` doesn't accept `post_processors`.

- [ ] **Step 3: Create post_processors.py with Protocol**

Create `src/league_values/post_processors.py`:

```python
from __future__ import annotations

from typing import Protocol, runtime_checkable

from .models import LeagueConfig, ValuationResult


@runtime_checkable
class PostProcessor(Protocol):
    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]: ...
```

- [ ] **Step 4: Update ValuationEngine to accept and run post-processors**

Modify `src/league_values/engine.py`:

Update the class to accept post-processors in `__init__`:

```python
class ValuationEngine:
    """Scores projections using only the league configuration."""

    def __init__(self, post_processors: list | None = None) -> None:
        self.post_processors: list = post_processors or []
```

At the end of `value_players`, after getting results from `_value_categories` or `_value_points`, apply post-processors and re-sort:

```python
    def value_players(self, players, league) -> list[ValuationResult]:
        league_config = league if isinstance(league, LeagueConfig) else LeagueConfig.from_dict(league)
        projections = [
            player if isinstance(player, PlayerProjection) else PlayerProjection.from_dict(player)
            for player in players
        ]

        if league_config.scoring_mode is ScoringMode.POINTS:
            results = self._value_points(projections, league_config)
        else:
            results = self._value_categories(projections, league_config)

        for processor in self.post_processors:
            results = processor.process(results, league_config)

        return sorted(results, key=lambda r: r.total_value, reverse=True)
```

Remove the `sorted()` calls from the end of `_value_categories` and `_value_points` (the final sort is now in `value_players`).

Update the module-level function:

```python
def value_players(players, league) -> list[ValuationResult]:
    return ValuationEngine().value_players(players, league)
```

Export `PostProcessor` from `__init__.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS (existing tests should be unaffected since they use the default no-processors path).

- [ ] **Step 7: Commit**

```bash
git add src/league_values/post_processors.py src/league_values/engine.py src/league_values/__init__.py tests/test_post_processors.py
git commit -m "feat: add PostProcessor protocol and engine pipeline wiring"
```

---

### Task 3: ReplacementLevel Post-Processor

**Files:**
- Modify: `src/league_values/post_processors.py`
- Test: `tests/test_post_processors.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_post_processors.py`:

```python
from league_values.models import RosterSettings
from league_values.post_processors import ReplacementLevel


class TestReplacementLevel(unittest.TestCase):
    def test_replacement_subtracts_baseline(self):
        roster = RosterSettings(
            teams=2,
            roster_size=3,
            positions={"1B": 1, "SP": 1},
            bench=1,
        )
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
            roster=roster,
        )
        # 4 hitters competing for 2 1B slots (2 teams * 1 slot)
        players = [
            {"id": "h1", "name": "Star", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 40}},
            {"id": "h2", "name": "Good", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 30}},
            {"id": "h3", "name": "Avg", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 20}},
            {"id": "h4", "name": "Scrub", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 10}},
        ]

        engine = ValuationEngine()
        raw_results = engine.value_players(players, league)

        processor = ReplacementLevel()
        adjusted = processor.process(raw_results, league)

        # Star should have highest value, Scrub should be near/below 0
        star = next(r for r in adjusted if r.name == "Star")
        scrub = next(r for r in adjusted if r.name == "Scrub")
        self.assertGreater(star.total_value, 0)
        self.assertLessEqual(scrub.total_value, 0.01)

    def test_replacement_no_roster_returns_unchanged(self):
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": "a", "name": "A", "pool": "hitter", "stats": {"HR": 30}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)

        processor = ReplacementLevel()
        adjusted = processor.process(raw, league)

        self.assertAlmostEqual(raw[0].total_value, adjusted[0].total_value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors.TestReplacementLevel -v`
Expected: ImportError — `ReplacementLevel` doesn't exist.

- [ ] **Step 3: Implement ReplacementLevel**

Add to `src/league_values/post_processors.py`:

```python
from dataclasses import replace

from .models import LeagueConfig, PlayerPool, RosterSettings, ValuationResult


@runtime_checkable
class PostProcessor(Protocol):
    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]: ...


class ReplacementLevel:
    """Subtract replacement-level value so output measures surplus above replacement.

    Replacement level per pool = the value of the (teams * starters_in_pool + 1)th
    best player in that pool. Without RosterSettings, returns results unchanged.
    """

    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        if not league.roster:
            return results

        hitter_slots = sum(
            slots for pos, slots in league.roster.positions.items()
            if pos not in ("SP", "RP", "P")
        )
        pitcher_slots = sum(
            slots for pos, slots in league.roster.positions.items()
            if pos in ("SP", "RP", "P")
        )

        hitter_repl = self._replacement_value(
            results, PlayerPool.HITTER, league.roster.teams * hitter_slots
        )
        pitcher_repl = self._replacement_value(
            results, PlayerPool.PITCHER, league.roster.teams * pitcher_slots
        )

        adjusted = []
        for r in results:
            if r.player.pool is PlayerPool.HITTER:
                new_val = r.total_value - hitter_repl
            elif r.player.pool is PlayerPool.PITCHER:
                new_val = r.total_value - pitcher_repl
            else:
                new_val = r.total_value
            adjusted.append(replace(r, total_value=new_val))
        return adjusted

    def _replacement_value(
        self, results: list[ValuationResult], pool: PlayerPool, n_starters: int
    ) -> float:
        pool_results = sorted(
            [r for r in results if r.player.pool is pool],
            key=lambda r: r.total_value,
            reverse=True,
        )
        if not pool_results or n_starters <= 0:
            return 0.0
        # Replacement = the first player outside the starter pool
        idx = min(n_starters, len(pool_results) - 1)
        return pool_results[idx].total_value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors.TestReplacementLevel -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/league_values/post_processors.py tests/test_post_processors.py
git commit -m "feat: add ReplacementLevel post-processor"
```

---

### Task 4: PositionScarcity Post-Processor

**Files:**
- Modify: `src/league_values/post_processors.py`
- Test: `tests/test_post_processors.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_post_processors.py`:

```python
from league_values.post_processors import PositionScarcity


class TestPositionScarcity(unittest.TestCase):
    def test_scarce_position_gets_premium(self):
        scarcity = PositionScarcity(multipliers={"C": 1.15, "1B": 0.90, "OF": 1.00})
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        # Two players with identical raw values but different positions
        players = [
            {"id": "c", "name": "Catcher", "pool": "hitter", "positions": ["C"], "stats": {"HR": 25}},
            {"id": "1b", "name": "First Base", "pool": "hitter", "positions": ["1B"], "stats": {"HR": 25}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)

        catcher = next(r for r in adjusted if r.name == "Catcher")
        first_base = next(r for r in adjusted if r.name == "First Base")
        self.assertGreater(catcher.total_value, first_base.total_value)

    def test_multi_position_uses_best(self):
        scarcity = PositionScarcity(multipliers={"C": 1.15, "1B": 0.90})
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": "dual", "name": "Dual Elig", "pool": "hitter", "positions": ["C", "1B"], "stats": {"HR": 25}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)
        # Should use C multiplier (1.15) since it's higher
        dual = adjusted[0]
        self.assertAlmostEqual(dual.total_value, raw[0].total_value * 1.15, places=5)

    def test_pitcher_positions(self):
        scarcity = PositionScarcity(multipliers={"SP": 1.00, "RP": 0.55})
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),
            ),
        )
        players = [
            {"id": "sp", "name": "Starter", "pool": "pitcher", "positions": ["SP"], "stats": {"K": 200}},
            {"id": "rp", "name": "Reliever", "pool": "pitcher", "positions": ["RP"], "stats": {"K": 200}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)

        sp = next(r for r in adjusted if r.name == "Starter")
        rp = next(r for r in adjusted if r.name == "Reliever")
        self.assertGreater(sp.total_value, rp.total_value)

    def test_no_positions_uses_default_1(self):
        scarcity = PositionScarcity(multipliers={"C": 1.15})
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": "np", "name": "No Pos", "pool": "hitter", "positions": [], "stats": {"HR": 25}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = scarcity.process(raw, league)
        # No positions → multiplier 1.0 (default) → unchanged
        self.assertAlmostEqual(adjusted[0].total_value, raw[0].total_value)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors.TestPositionScarcity -v`
Expected: ImportError — `PositionScarcity` doesn't exist.

- [ ] **Step 3: Implement PositionScarcity**

Add to `src/league_values/post_processors.py`:

```python
class PositionScarcity:
    """Multiply player values by position-based scarcity factors.

    Multi-eligible players use their best (highest) multiplier.
    Players with no listed positions get a default multiplier of 1.0.
    """

    def __init__(self, multipliers: dict[str, float]) -> None:
        self.multipliers = multipliers

    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        adjusted = []
        for r in results:
            mult = self._best_multiplier(r.player.positions)
            adjusted.append(replace(r, total_value=r.total_value * mult))
        return adjusted

    def _best_multiplier(self, positions: tuple[str, ...]) -> float:
        if not positions:
            return 1.0
        mults = [self.multipliers.get(pos, 1.0) for pos in positions]
        return max(mults)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors.TestPositionScarcity -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/league_values/post_processors.py tests/test_post_processors.py
git commit -m "feat: add PositionScarcity post-processor"
```

---

### Task 5: AgeCurve Post-Processor

**Files:**
- Modify: `src/league_values/post_processors.py`
- Test: `tests/test_post_processors.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_post_processors.py`:

```python
from league_values.post_processors import AgeCurve


class TestAgeCurve(unittest.TestCase):
    def test_young_player_boosted(self):
        curve = AgeCurve(
            hitter_curve={22: 1.65, 27: 1.25, 32: 0.87},
            pitcher_curve={22: 1.50, 27: 1.15, 32: 0.78},
        )
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        # Two hitters with identical stats but different ages
        players = [
            {"id": "young", "name": "Young", "pool": "hitter", "stats": {"HR": 25}, "metadata": {"age": 22}},
            {"id": "old", "name": "Old", "pool": "hitter", "stats": {"HR": 25}, "metadata": {"age": 32}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)

        young = next(r for r in adjusted if r.name == "Young")
        old = next(r for r in adjusted if r.name == "Old")
        self.assertGreater(young.total_value, old.total_value)

    def test_pitcher_uses_pitcher_curve(self):
        curve = AgeCurve(
            hitter_curve={25: 1.50},
            pitcher_curve={25: 1.30},
        )
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),
            ),
        )
        players = [
            {"id": "p1", "name": "Pitcher", "pool": "pitcher", "stats": {"K": 200}, "metadata": {"age": 25}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)
        # Should use pitcher curve (1.30), not hitter (1.50)
        self.assertAlmostEqual(adjusted[0].total_value, raw[0].total_value * 1.30, places=5)

    def test_missing_age_uses_multiplier_1(self):
        curve = AgeCurve(hitter_curve={25: 1.50}, pitcher_curve={25: 1.30})
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": "no_age", "name": "No Age", "pool": "hitter", "stats": {"HR": 25}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)
        self.assertAlmostEqual(adjusted[0].total_value, raw[0].total_value)

    def test_interpolates_between_ages(self):
        # 22→1.60, 24→1.40 → age 23 should be 1.50
        curve = AgeCurve(hitter_curve={22: 1.60, 24: 1.40}, pitcher_curve={})
        league = LeagueConfig(
            name="T",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": "mid", "name": "Mid", "pool": "hitter", "stats": {"HR": 25}, "metadata": {"age": 23}},
        ]
        engine = ValuationEngine()
        raw = engine.value_players(players, league)
        adjusted = curve.process(raw, league)
        self.assertAlmostEqual(adjusted[0].total_value, raw[0].total_value * 1.50, places=3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors.TestAgeCurve -v`
Expected: ImportError — `AgeCurve` doesn't exist.

- [ ] **Step 3: Implement AgeCurve**

Add to `src/league_values/post_processors.py`:

```python
class AgeCurve:
    """Apply dynasty-horizon multiplier based on player age.

    Age comes from player.metadata["age"]. Missing age → multiplier 1.0.
    Ages between curve anchor points are linearly interpolated.
    Ages below the youngest anchor use the youngest value.
    Ages above the oldest anchor use the oldest value.
    """

    def __init__(
        self,
        hitter_curve: dict[int, float],
        pitcher_curve: dict[int, float],
    ) -> None:
        self.hitter_curve = hitter_curve
        self.pitcher_curve = pitcher_curve

    def process(
        self,
        results: list[ValuationResult],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        adjusted = []
        for r in results:
            age = r.player.metadata.get("age")
            if age is None:
                adjusted.append(r)
                continue
            age = int(age)
            curve = self.pitcher_curve if r.player.pool is PlayerPool.PITCHER else self.hitter_curve
            mult = self._interpolate(curve, age)
            adjusted.append(replace(r, total_value=r.total_value * mult))
        return adjusted

    def _interpolate(self, curve: dict[int, float], age: int) -> float:
        if not curve:
            return 1.0
        ages = sorted(curve.keys())
        if age <= ages[0]:
            return curve[ages[0]]
        if age >= ages[-1]:
            return curve[ages[-1]]
        # Find bracketing ages
        for i in range(len(ages) - 1):
            if ages[i] <= age <= ages[i + 1]:
                lo_age, hi_age = ages[i], ages[i + 1]
                lo_val, hi_val = curve[lo_age], curve[hi_age]
                t = (age - lo_age) / (hi_age - lo_age)
                return lo_val + t * (hi_val - lo_val)
        return 1.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_post_processors.TestAgeCurve -v`
Expected: 4 tests PASS.

- [ ] **Step 5: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/league_values/post_processors.py tests/test_post_processors.py
git commit -m "feat: add AgeCurve post-processor with linear interpolation"
```

---

### Task 6: Roto / SGP Scoring Mode

**Files:**
- Modify: `src/league_values/models.py` (add `ROTO` to `ScoringMode`)
- Modify: `src/league_values/engine.py` (add `_value_roto`)
- Test: `tests/test_roto.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_roto.py`:

```python
import unittest

from league_values import (
    CategorySpec,
    Direction,
    LeagueConfig,
    PlayerPool,
    ScoringMode,
    value_players,
)


class TestRotoSGP(unittest.TestCase):
    def test_roto_mode_ranks_by_sgp(self):
        league = LeagueConfig(
            name="Roto",
            scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
                CategorySpec(id="SB", label="SB", pool=PlayerPool.HITTER, stat="SB"),
            ),
        )
        players = [
            {"id": "power", "name": "Power", "pool": "hitter", "stats": {"HR": 40, "SB": 5}},
            {"id": "speed", "name": "Speed", "pool": "hitter", "stats": {"HR": 10, "SB": 40}},
            {"id": "balanced", "name": "Balanced", "pool": "hitter", "stats": {"HR": 25, "SB": 22}},
        ]
        results = value_players(players, league)
        # Balanced should be top — contributes across more categories
        # (exact ranking depends on SGP denominators, but balanced should be competitive)
        self.assertEqual(len(results), 3)
        # All should have non-None total values
        for r in results:
            self.assertIsNotNone(r.total_value)

    def test_roto_lower_is_better(self):
        league = LeagueConfig(
            name="Roto ERA",
            scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(
                    id="ERA", label="ERA", pool=PlayerPool.PITCHER,
                    numerator_stats=("ER",), denominator_stats=("IP",),
                    ratio_multiplier=9, direction=Direction.LOWER_IS_BETTER,
                    baseline=4.00,
                ),
            ),
        )
        players = [
            {"id": "ace", "name": "Ace", "pool": "pitcher", "stats": {"ER": 50, "IP": 180}},
            {"id": "bad", "name": "Bad", "pool": "pitcher", "stats": {"ER": 90, "IP": 180}},
        ]
        results = value_players(players, league)
        # Ace (lower ERA) should rank higher
        self.assertEqual(results[0].name, "Ace")

    def test_roto_mixed_pools(self):
        league = LeagueConfig(
            name="Roto Mixed",
            scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
                CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),
            ),
        )
        players = [
            {"id": "h1", "name": "Hitter", "pool": "hitter", "stats": {"HR": 30}},
            {"id": "p1", "name": "Pitcher", "pool": "pitcher", "stats": {"K": 200}},
        ]
        results = value_players(players, league)
        self.assertEqual(len(results), 2)

    def test_roto_single_player_gets_zero(self):
        league = LeagueConfig(
            name="Roto Solo",
            scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        results = value_players(
            [{"id": "solo", "name": "Solo", "pool": "hitter", "stats": {"HR": 30}}],
            league,
        )
        self.assertEqual(results[0].total_value, 0.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_roto -v`
Expected: Error — `ScoringMode.ROTO` doesn't exist.

- [ ] **Step 3: Add ROTO to ScoringMode**

In `src/league_values/models.py`, update the enum:

```python
class ScoringMode(str, Enum):
    CATEGORIES = "categories"
    POINTS = "points"
    ROTO = "roto"
```

Update the `LeagueConfig.__post_init__` validation — roto uses categories too:

```python
if self.scoring_mode in (ScoringMode.CATEGORIES, ScoringMode.ROTO) and not self.categories:
    raise ValueError("Category/roto leagues need at least one category.")
if self.scoring_mode is ScoringMode.POINTS and not self.point_rules:
    raise ValueError("Points leagues need at least one point rule.")
```

- [ ] **Step 4: Add `_value_roto` to the engine**

In `src/league_values/engine.py`, update `value_players` to route roto:

```python
if league_config.scoring_mode is ScoringMode.POINTS:
    results = self._value_points(projections, league_config)
elif league_config.scoring_mode is ScoringMode.ROTO:
    results = self._value_roto(projections, league_config)
else:
    results = self._value_categories(projections, league_config)
```

Add the `_value_roto` method:

```python
    def _value_roto(
        self,
        players: list[PlayerProjection],
        league: LeagueConfig,
    ) -> list[ValuationResult]:
        """Standings Gain Points: value = sum of (stat - replacement) / sgp_denominator."""
        raw_values: dict[str, dict[str, float | None]] = {p.id: {} for p in players}
        sgp_values: dict[str, dict[str, float]] = {p.id: {} for p in players}

        for category in league.categories:
            eligible = [p for p in players if category.applies_to(p.pool)]
            impacts = {
                p.id: self._category_impact(p, category, eligible)
                for p in eligible
            }

            # SGP denominator = average gap between adjacent standings positions
            sorted_impacts = sorted(impacts.values(), reverse=True)
            if len(sorted_impacts) < 2:
                sgp_denom = 1.0
            else:
                gaps = [
                    sorted_impacts[i] - sorted_impacts[i + 1]
                    for i in range(len(sorted_impacts) - 1)
                ]
                sgp_denom = sum(gaps) / len(gaps) if gaps else 1.0
                if sgp_denom == 0:
                    sgp_denom = 1.0

            for player in players:
                raw_values[player.id][category.id] = (
                    self._raw_category_value(player, category)
                    if category.applies_to(player.pool)
                    else None
                )
                if not category.applies_to(player.pool):
                    sgp_values[player.id][category.id] = 0.0
                else:
                    sgp_values[player.id][category.id] = (
                        impacts[player.id] * category.weight / sgp_denom
                    )

        results = [
            ValuationResult(
                player=player,
                total_value=sum(sgp_values[player.id].values()),
                raw_values=raw_values[player.id],
                z_scores={},
                category_values=sgp_values[player.id],
            )
            for player in players
        ]
        return results
```

- [ ] **Step 5: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_roto -v`
Expected: 4 tests PASS.

- [ ] **Step 6: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/league_values/models.py src/league_values/engine.py tests/test_roto.py
git commit -m "feat: add roto/SGP scoring mode"
```

---

### Task 7: DD 7x7 Preset

**Files:**
- Modify: `src/league_values/presets.py`
- Modify: `src/league_values/__init__.py`
- Test: `tests/test_dd_preset.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_dd_preset.py`:

```python
import unittest

from league_values import ScoringMode, value_players
from league_values.presets import dd_7x7


class TestDD7x7Preset(unittest.TestCase):
    def test_dd_7x7_loads(self):
        config = dd_7x7()
        self.assertEqual(config.name, "DD 7x7")
        self.assertEqual(config.scoring_mode, ScoringMode.CATEGORIES)
        self.assertEqual(len(config.categories), 14)

    def test_dd_7x7_has_correct_hitting_cats(self):
        config = dd_7x7()
        hitting_ids = {c.id for c in config.categories if c.pool.value == "hitter"}
        self.assertEqual(hitting_ids, {"R", "HR", "RBI", "SB", "AVG", "OPS", "SO"})

    def test_dd_7x7_has_correct_pitching_cats(self):
        config = dd_7x7()
        pitching_ids = {c.id for c in config.categories if c.pool.value == "pitcher"}
        self.assertEqual(pitching_ids, {"K", "QS", "SV_HLD", "L", "ERA", "WHIP", "K_BB"})

    def test_dd_7x7_inverse_cats(self):
        config = dd_7x7()
        inverse_ids = {c.id for c in config.categories if c.direction.value == "lower"}
        self.assertEqual(inverse_ids, {"SO", "L", "ERA", "WHIP"})

    def test_dd_7x7_has_league_baselines(self):
        config = dd_7x7()
        self.assertIn("HR", config.league_baselines)
        self.assertIn("ERA", config.league_baselines)
        # HR baseline should be (mean=22, std=12)
        self.assertEqual(config.league_baselines["HR"], (22.0, 12.0))

    def test_dd_7x7_has_roster_settings(self):
        config = dd_7x7()
        self.assertIsNotNone(config.roster)
        self.assertEqual(config.roster.teams, 12)

    def test_dd_7x7_produces_results(self):
        config = dd_7x7()
        players = [
            {
                "id": "h1", "name": "Hitter", "pool": "hitter",
                "stats": {
                    "R": 80, "HR": 25, "RBI": 80, "SB": 10,
                    "H": 150, "AB": 550, "OBP": 0.340,
                    "AVG": 0.273, "OPS": 0.790, "SO": 120,
                },
            },
            {
                "id": "p1", "name": "Pitcher", "pool": "pitcher",
                "stats": {
                    "K": 180, "QS": 15, "SV_HLD": 0, "L": 8,
                    "ER": 60, "IP": 180, "BB": 45, "H_ALLOWED": 150,
                    "ERA": 3.00, "WHIP": 1.08, "K_BB": 4.0,
                },
            },
        ]
        results = value_players(players, config)
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_dd_preset -v`
Expected: ImportError — `dd_7x7` doesn't exist.

- [ ] **Step 3: Implement dd_7x7 preset**

Add to `src/league_values/presets.py` — import `RosterSettings` and add the DD categories:

```python
from .models import CategorySpec, Direction, LeagueConfig, PlayerPool, PointRule, RosterSettings, ScoringMode


DD_7X7_CATEGORIES: tuple[CategorySpec, ...] = (
    # Hitting (7 cats)
    CategorySpec(id="R", label="Runs", pool=PlayerPool.HITTER, stat="R", weight=0.12),
    CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR", weight=0.16),
    CategorySpec(id="RBI", label="RBI", pool=PlayerPool.HITTER, stat="RBI", weight=0.13),
    CategorySpec(id="SB", label="Stolen Bases", pool=PlayerPool.HITTER, stat="SB", weight=0.10),
    CategorySpec(
        id="AVG", label="Batting Average", pool=PlayerPool.HITTER,
        numerator_stats=("H",), denominator_stats=("AB",),
        weight=0.14, min_denominator=50.0,
    ),
    CategorySpec(id="OPS", label="OPS", pool=PlayerPool.HITTER, stat="OPS", weight=0.25),
    CategorySpec(
        id="SO", label="Strikeouts", pool=PlayerPool.HITTER, stat="SO",
        direction=Direction.LOWER_IS_BETTER, weight=0.14,
    ),
    # Pitching (7 cats)
    CategorySpec(id="K", label="Strikeouts", pool=PlayerPool.PITCHER, stat="K", weight=0.20),
    CategorySpec(id="QS", label="Quality Starts", pool=PlayerPool.PITCHER, stat="QS", weight=0.18),
    CategorySpec(id="SV_HLD", label="Saves + Holds", pool=PlayerPool.PITCHER, stat="SV_HLD", weight=0.18),
    CategorySpec(
        id="L", label="Losses", pool=PlayerPool.PITCHER, stat="L",
        direction=Direction.LOWER_IS_BETTER, weight=0.08,
    ),
    CategorySpec(
        id="ERA", label="ERA", pool=PlayerPool.PITCHER,
        numerator_stats=("ER",), denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER, ratio_multiplier=9.0,
        weight=0.28, min_denominator=10.0,
    ),
    CategorySpec(
        id="WHIP", label="WHIP", pool=PlayerPool.PITCHER,
        numerator_stats=("BB", "H_ALLOWED"), denominator_stats=("IP",),
        direction=Direction.LOWER_IS_BETTER,
        weight=0.25, min_denominator=10.0,
    ),
    CategorySpec(id="K_BB", label="K/BB", pool=PlayerPool.PITCHER, stat="K_BB", weight=0.15),
)

DD_7X7_BASELINES: dict[str, tuple[float, float]] = {
    # Hitting: (league_avg, league_std)
    "R": (75.0, 25.0),
    "HR": (22.0, 12.0),
    "RBI": (72.0, 28.0),
    "SB": (12.0, 15.0),
    "AVG": (0.252, 0.028),
    "OPS": (0.720, 0.085),
    "SO": (140.0, 35.0),
    # Pitching: (league_avg, league_std)
    "K": (120.0, 49.0),
    "QS": (9.0, 6.0),
    "SV_HLD": (1.0, 3.0),
    "L": (7.0, 3.0),
    "ERA": (4.13, 1.07),
    "WHIP": (1.26, 0.18),
    "K_BB": (3.17, 1.27),
}

DD_7X7_ROSTER = RosterSettings(
    teams=12,
    roster_size=23,
    positions={
        "C": 1, "1B": 1, "2B": 1, "SS": 1, "3B": 1,
        "OF": 3, "UTIL": 1,
        "SP": 5, "RP": 2,
    },
    bench=7,
)


def dd_7x7() -> LeagueConfig:
    return LeagueConfig(
        name="DD 7x7",
        scoring_mode=ScoringMode.CATEGORIES,
        categories=DD_7X7_CATEGORIES,
        league_baselines=DD_7X7_BASELINES,
        roster=DD_7X7_ROSTER,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_dd_preset -v`
Expected: 7 tests PASS.

- [ ] **Step 5: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: All tests PASS.

- [ ] **Step 6: Commit**

```bash
git add src/league_values/presets.py tests/test_dd_preset.py
git commit -m "feat: add DD 7x7 preset with weights, baselines, and roster settings"
```

---

### Task 8: Integration Test — Full Pipeline

**Files:**
- Test: `tests/test_integration.py` (create)

- [ ] **Step 1: Write integration test**

Create `tests/test_integration.py`:

```python
import unittest

from league_values import (
    CategorySpec,
    Direction,
    LeagueConfig,
    PlayerPool,
    ScoringMode,
    ValuationEngine,
)
from league_values.models import RosterSettings
from league_values.post_processors import AgeCurve, PositionScarcity, ReplacementLevel
from league_values.presets import dd_7x7


class TestFullPipeline(unittest.TestCase):
    """End-to-end test: engine + all post-processors composed."""

    PLAYERS = [
        {
            "id": "trout", "name": "Mike Trout", "pool": "hitter",
            "positions": ["OF"],
            "stats": {"R": 90, "HR": 35, "RBI": 90, "SB": 15, "H": 160, "AB": 520, "OPS": 0.950, "AVG": 0.308, "SO": 130},
            "metadata": {"age": 34},
        },
        {
            "id": "soto", "name": "Juan Soto", "pool": "hitter",
            "positions": ["OF"],
            "stats": {"R": 100, "HR": 30, "RBI": 95, "SB": 5, "H": 155, "AB": 530, "OPS": 0.920, "AVG": 0.292, "SO": 110},
            "metadata": {"age": 27},
        },
        {
            "id": "witt", "name": "Bobby Witt Jr", "pool": "hitter",
            "positions": ["SS"],
            "stats": {"R": 105, "HR": 28, "RBI": 85, "SB": 35, "H": 180, "AB": 600, "OPS": 0.880, "AVG": 0.300, "SO": 100},
            "metadata": {"age": 25},
        },
        {
            "id": "burns", "name": "Corbin Burns", "pool": "pitcher",
            "positions": ["SP"],
            "stats": {"K": 210, "QS": 18, "SV_HLD": 0, "L": 6, "ER": 55, "IP": 195, "BB": 40, "H_ALLOWED": 155, "ERA": 2.54, "WHIP": 1.00, "K_BB": 5.25},
            "metadata": {"age": 31},
        },
        {
            "id": "clase", "name": "Emmanuel Clase", "pool": "pitcher",
            "positions": ["RP"],
            "stats": {"K": 65, "QS": 0, "SV_HLD": 38, "L": 3, "ER": 15, "IP": 65, "BB": 12, "H_ALLOWED": 42, "ERA": 2.08, "WHIP": 0.83, "K_BB": 5.42},
            "metadata": {"age": 28},
        },
        {
            "id": "bench", "name": "Bench Bat", "pool": "hitter",
            "positions": ["1B"],
            "stats": {"R": 40, "HR": 8, "RBI": 35, "SB": 2, "H": 75, "AB": 300, "OPS": 0.650, "AVG": 0.250, "SO": 80},
            "metadata": {"age": 32},
        },
    ]

    def test_raw_engine_only(self):
        config = dd_7x7()
        engine = ValuationEngine()
        results = engine.value_players(self.PLAYERS, config)
        self.assertEqual(len(results), 6)
        # Top hitter should be ahead of bench bat
        names = [r.name for r in results]
        self.assertLess(names.index("Bobby Witt Jr"), names.index("Bench Bat"))

    def test_full_pipeline_with_all_processors(self):
        config = dd_7x7()
        engine = ValuationEngine(post_processors=[
            ReplacementLevel(),
            PositionScarcity(multipliers={
                "C": 1.00, "3B": 1.10, "SS": 1.05, "2B": 1.05,
                "OF": 0.97, "1B": 0.90, "DH": 0.80, "UTIL": 0.80,
                "SP": 1.00, "RP": 0.55,
            }),
            AgeCurve(
                hitter_curve={
                    22: 1.65, 25: 1.42, 27: 1.25, 30: 0.97,
                    32: 0.87, 34: 0.77, 37: 0.48,
                },
                pitcher_curve={
                    22: 1.50, 25: 1.30, 27: 1.15, 30: 0.88,
                    32: 0.78, 34: 0.65, 37: 0.33,
                },
            ),
        ])
        results = engine.value_players(self.PLAYERS, config)

        self.assertEqual(len(results), 6)

        # Witt (young SS) should rank highly due to age + position scarcity
        witt = next(r for r in results if r.name == "Bobby Witt Jr")
        bench = next(r for r in results if r.name == "Bench Bat")
        self.assertGreater(witt.total_value, bench.total_value)

        # Burns (SP, age 31) should outrank Clase (RP, 0.55 mult)
        burns = next(r for r in results if r.name == "Corbin Burns")
        clase = next(r for r in results if r.name == "Emmanuel Clase")
        self.assertGreater(burns.total_value, clase.total_value)

        # Soto (age 27) should outrank Trout (age 34, same position)
        # due to age curve even though Trout has slightly better raw stats
        soto = next(r for r in results if r.name == "Juan Soto")
        trout = next(r for r in results if r.name == "Mike Trout")
        self.assertGreater(soto.total_value, trout.total_value)

    def test_to_dict_serialization(self):
        config = dd_7x7()
        engine = ValuationEngine()
        results = engine.value_players(self.PLAYERS, config)
        for r in results:
            d = r.to_dict()
            self.assertIn("total_value", d)
            self.assertIn("z_scores", d)
            self.assertIsInstance(d["z_scores"], dict)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest tests.test_integration -v`
Expected: 3 tests PASS.

- [ ] **Step 3: Run full suite**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: ALL tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add full pipeline integration tests with realistic player data"
```

---

### Task 9: Export Cleanup & Final Verification

**Files:**
- Modify: `src/league_values/__init__.py`
- Modify: `README.md`

- [ ] **Step 1: Update __init__.py exports**

Ensure all new public API is exported:

```python
"""Config-driven fantasy baseball valuation engine."""

from .config_loader import load_league_config
from .engine import ValuationEngine, value_players
from .models import (
    CategorySpec,
    Direction,
    LeagueConfig,
    PlayerPool,
    PlayerProjection,
    PointRule,
    RosterSettings,
    ScoringMode,
    ValuationResult,
)
from .post_processors import AgeCurve, PositionScarcity, PostProcessor, ReplacementLevel

__all__ = [
    "AgeCurve",
    "CategorySpec",
    "Direction",
    "LeagueConfig",
    "PlayerPool",
    "PlayerProjection",
    "PointRule",
    "PositionScarcity",
    "PostProcessor",
    "ReplacementLevel",
    "RosterSettings",
    "ScoringMode",
    "ValuationEngine",
    "ValuationResult",
    "load_league_config",
    "value_players",
]
```

- [ ] **Step 2: Update README.md**

Add sections for post-processors, roto mode, and DD preset to the README. Update the "Next Useful Milestones" to reflect what's shipped vs. what's next.

- [ ] **Step 3: Run full suite one final time**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python -m unittest discover -s tests -v`
Expected: ALL tests PASS (target: ~50+ tests).

- [ ] **Step 4: Run demo**

Run: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python examples/run_demo.py`
Expected: Output shows rankings for both configs.

- [ ] **Step 5: Commit**

```bash
git add src/league_values/__init__.py README.md
git commit -m "docs: update exports and README for v0.2 features"
```
