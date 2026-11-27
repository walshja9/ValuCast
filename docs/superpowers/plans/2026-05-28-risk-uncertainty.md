# Risk / Uncertainty Model v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add transparent risk/uncertainty annotations to Dynasty and Prospects modes — risk score, level, asymmetric value range, and human-readable drivers per player.

**Architecture:** Standalone `src/league_values/risk.py` module with `RiskModel` class. Uses duck typing (no web layer imports). App computes a `{row.id: RiskAssessment}` mapping and passes it to templates alongside existing dynasty rows. No value adjustment or re-ranking — annotation only.

**Tech Stack:** Python dataclasses, unittest, Flask/Jinja2 templates, htmx (existing), CSS badges

**Spec:** `docs/superpowers/specs/2026-05-28-risk-uncertainty-design.md`

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `src/league_values/risk.py` | RiskDriver, RiskAssessment, RISK_LEVELS, RiskModel |
| Create | `tests/test_risk.py` | Unit tests for risk module (~40 tests) |
| Modify | `app.py:103-123` | Compute risk_assessments dict in `_build_dynasty_context` |
| Modify | `app.py:495-523` | Pass risk to player detail route |
| Modify | `app.py:569-602` | Add risk columns to CSV export |
| Modify | `templates/partials/rankings_table_dynasty.html` | Add Risk + Range columns |
| Modify | `templates/partials/player_detail_dynasty.html` | Add risk block below value |
| Modify | `static/style.css` | Risk badge color styles |
| Modify | `tests/test_app.py` | 6 integration tests for risk in UI/CSV |

---

### Task 1: Core Types — RiskDriver, RiskAssessment, RISK_LEVELS

**Files:**
- Create: `src/league_values/risk.py`
- Create: `tests/test_risk.py`

- [ ] **Step 1: Write failing tests for core types**

```python
# tests/test_risk.py
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestRiskDriver(unittest.TestCase):
    def test_frozen_dataclass(self):
        from league_values.risk import RiskDriver
        d = RiskDriver(id="test", label="Test", score_delta=0.1, floor_drag=5, ceiling_lift=3)
        self.assertEqual(d.id, "test")
        self.assertEqual(d.label, "Test")
        self.assertEqual(d.score_delta, 0.1)
        self.assertEqual(d.floor_drag, 5)
        self.assertEqual(d.ceiling_lift, 3)
        with self.assertRaises(AttributeError):
            d.id = "changed"


class TestRiskAssessment(unittest.TestCase):
    def test_frozen_dataclass(self):
        from league_values.risk import RiskAssessment, RiskDriver
        d = RiskDriver(id="a", label="A", score_delta=0.1, floor_drag=5, ceiling_lift=3)
        a = RiskAssessment(risk_score=0.1, risk_level="Low", value_low=50.0, value_high=80.0, drivers=(d,))
        self.assertEqual(a.risk_score, 0.1)
        self.assertEqual(a.risk_level, "Low")
        self.assertEqual(a.value_low, 50.0)
        self.assertEqual(a.value_high, 80.0)
        self.assertEqual(len(a.drivers), 1)

    def test_driver_labels_property(self):
        from league_values.risk import RiskAssessment, RiskDriver
        d1 = RiskDriver(id="a", label="Alpha", score_delta=0.1, floor_drag=5, ceiling_lift=3)
        d2 = RiskDriver(id="b", label="Beta", score_delta=0.2, floor_drag=8, ceiling_lift=6)
        a = RiskAssessment(risk_score=0.3, risk_level="Moderate", value_low=40.0, value_high=90.0, drivers=(d1, d2))
        self.assertEqual(a.driver_labels, ("Alpha", "Beta"))

    def test_to_dict(self):
        from league_values.risk import RiskAssessment, RiskDriver
        d = RiskDriver(id="a", label="Alpha", score_delta=0.1, floor_drag=5, ceiling_lift=3)
        a = RiskAssessment(risk_score=0.1, risk_level="Low", value_low=50.0, value_high=80.0, drivers=(d,))
        result = a.to_dict()
        self.assertEqual(result["risk_score"], 0.1)
        self.assertEqual(result["risk_level"], "Low")
        self.assertEqual(result["value_low"], 50.0)
        self.assertEqual(result["value_high"], 80.0)
        self.assertEqual(result["drivers"], ["Alpha"])

    def test_to_dict_drivers_are_labels_not_objects(self):
        from league_values.risk import RiskAssessment, RiskDriver
        d = RiskDriver(id="a", label="Test Label", score_delta=0.1, floor_drag=5, ceiling_lift=3)
        a = RiskAssessment(risk_score=0.1, risk_level="Low", value_low=50.0, value_high=80.0, drivers=(d,))
        for item in a.to_dict()["drivers"]:
            self.assertIsInstance(item, str)


class TestRiskLevels(unittest.TestCase):
    def test_risk_levels_is_tuple(self):
        from league_values.risk import RISK_LEVELS
        self.assertIsInstance(RISK_LEVELS, tuple)

    def test_risk_levels_has_four_entries(self):
        from league_values.risk import RISK_LEVELS
        self.assertEqual(len(RISK_LEVELS), 4)

    def test_risk_levels_thresholds_ascending(self):
        from league_values.risk import RISK_LEVELS
        thresholds = [t for t, _ in RISK_LEVELS]
        self.assertEqual(thresholds, sorted(thresholds))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_risk -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'league_values.risk'`

- [ ] **Step 3: Implement core types**

```python
# src/league_values/risk.py
"""Risk / Uncertainty model for dynasty and prospect valuations.

Annotation-only: computes risk metadata alongside existing values.
Does not adjust headline value or ranking order.
"""
from __future__ import annotations

from dataclasses import dataclass


RISK_LEVELS: tuple[tuple[float, str], ...] = (
    (0.25, "Low"),
    (0.50, "Moderate"),
    (0.75, "High"),
    (1.00, "Extreme"),
)


@dataclass(frozen=True)
class RiskDriver:
    """One detected risk factor contributing to a player's risk profile."""
    id: str
    label: str
    score_delta: float
    floor_drag: float
    ceiling_lift: float


@dataclass(frozen=True)
class RiskAssessment:
    """Complete risk annotation for a single player."""
    risk_score: float
    risk_level: str
    value_low: float
    value_high: float
    drivers: tuple[RiskDriver, ...]

    @property
    def driver_labels(self) -> tuple[str, ...]:
        return tuple(d.label for d in self.drivers)

    def to_dict(self) -> dict:
        return {
            "risk_score": self.risk_score,
            "risk_level": self.risk_level,
            "value_low": self.value_low,
            "value_high": self.value_high,
            "drivers": [d.label for d in self.drivers],
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_risk -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add src/league_values/risk.py tests/test_risk.py
git commit -m "feat(risk): core types — RiskDriver, RiskAssessment, RISK_LEVELS"
```

---

### Task 2: RiskModel._build_assessment()

**Files:**
- Modify: `src/league_values/risk.py`
- Modify: `tests/test_risk.py`

- [ ] **Step 1: Write failing tests for _build_assessment**

Add to `tests/test_risk.py`:

```python
from datetime import date


class TestBuildAssessment(unittest.TestCase):
    def _model(self):
        from league_values.risk import RiskModel
        return RiskModel(current_year=2026)

    def _driver(self, score=0.1, floor=5, ceil=3):
        from league_values.risk import RiskDriver
        return RiskDriver(id="t", label="T", score_delta=score, floor_drag=floor, ceiling_lift=ceil)

    def test_empty_drivers_returns_zero_score(self):
        a = self._model()._build_assessment(70.0, [])
        self.assertEqual(a.risk_score, 0.0)
        self.assertEqual(a.risk_level, "Low")
        self.assertEqual(a.value_low, 70.0)
        self.assertEqual(a.value_high, 70.0)

    def test_single_driver_adds_score(self):
        d = self._driver(score=0.1, floor=5, ceil=3)
        a = self._model()._build_assessment(70.0, [d])
        self.assertAlmostEqual(a.risk_score, 0.1, places=3)
        self.assertAlmostEqual(a.value_low, 65.0, places=1)
        self.assertAlmostEqual(a.value_high, 73.0, places=1)

    def test_multiple_drivers_stack(self):
        d1 = self._driver(score=0.1, floor=5, ceil=3)
        d2 = self._driver(score=0.2, floor=8, ceil=6)
        a = self._model()._build_assessment(70.0, [d1, d2])
        self.assertAlmostEqual(a.risk_score, 0.3, places=3)
        self.assertAlmostEqual(a.value_low, 57.0, places=1)
        self.assertAlmostEqual(a.value_high, 79.0, places=1)

    def test_score_clamped_at_1(self):
        drivers = [self._driver(score=0.4) for _ in range(4)]
        a = self._model()._build_assessment(70.0, drivers)
        self.assertEqual(a.risk_score, 1.0)

    def test_floor_clamped_at_0(self):
        d = self._driver(score=0.1, floor=100, ceil=3)
        a = self._model()._build_assessment(5.0, [d])
        self.assertEqual(a.value_low, 0.0)

    def test_ceiling_clamped_at_150(self):
        d = self._driver(score=0.1, floor=5, ceil=100)
        a = self._model()._build_assessment(140.0, [d])
        self.assertEqual(a.value_high, 150.0)

    def test_level_low_at_0(self):
        a = self._model()._build_assessment(70.0, [])
        self.assertEqual(a.risk_level, "Low")

    def test_level_low_at_boundary_025(self):
        d = self._driver(score=0.25)
        a = self._model()._build_assessment(70.0, [d])
        self.assertEqual(a.risk_level, "Low")

    def test_level_moderate_above_025(self):
        d = self._driver(score=0.26)
        a = self._model()._build_assessment(70.0, [d])
        self.assertEqual(a.risk_level, "Moderate")

    def test_level_high_above_050(self):
        d = self._driver(score=0.51)
        a = self._model()._build_assessment(70.0, [d])
        self.assertEqual(a.risk_level, "High")

    def test_level_extreme_above_075(self):
        d = self._driver(score=0.76)
        a = self._model()._build_assessment(70.0, [d])
        self.assertEqual(a.risk_level, "Extreme")

    def test_level_extreme_at_1(self):
        d = self._driver(score=1.0)
        a = self._model()._build_assessment(70.0, [d])
        self.assertEqual(a.risk_level, "Extreme")

    def test_rounding_score_3_decimals(self):
        d = self._driver(score=0.33333)
        a = self._model()._build_assessment(70.0, [d])
        self.assertEqual(a.risk_score, 0.333)

    def test_rounding_values_1_decimal(self):
        d = self._driver(score=0.1, floor=3, ceil=7)
        a = self._model()._build_assessment(70.55, [d])
        self.assertEqual(a.value_low, 67.6)  # 70.55 - 3 = 67.55 -> 67.6
        self.assertEqual(a.value_high, 77.6)  # 70.55 + 7 = 77.55 -> 77.6


class TestRiskModelConstructor(unittest.TestCase):
    def test_default_year_is_current(self):
        from league_values.risk import RiskModel
        model = RiskModel()
        self.assertEqual(model.current_year, date.today().year)

    def test_injected_year(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2025)
        self.assertEqual(model.current_year, 2025)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_risk -v`
Expected: FAIL — `AttributeError: module 'league_values.risk' has no attribute 'RiskModel'`

- [ ] **Step 3: Implement RiskModel with _build_assessment**

Add to `src/league_values/risk.py`:

```python
from datetime import date


class RiskModel:
    """Standalone risk assessment for dynasty/prospect valuations.

    Uses duck typing for row input — no web layer imports.
    """

    POSITIVE_BREAKOUT_LABELS = {"major_breakout", "breakout", "rising"}

    def __init__(self, current_year: int | None = None):
        self.current_year = current_year or date.today().year

    def evaluate_dynasty(self, row, value: float | None = None) -> RiskAssessment:
        """Evaluate risk for a dynasty/prospect row.

        Row must have: player_type, positions, age, dynasty_value.
        Optional: eta, level, source_ranks, breakout_label.
        """
        value = getattr(row, "dynasty_value", 0.0) if value is None else value
        drivers = self._dynasty_drivers(row)
        return self._build_assessment(value, drivers)

    def evaluate_redraft(self, player, result=None, metadata=None):
        raise NotImplementedError  # v1.1

    def _dynasty_drivers(self, row) -> list[RiskDriver]:
        return []  # Implemented in Task 3

    def _build_assessment(self, value: float, drivers: list[RiskDriver]) -> RiskAssessment:
        risk_score = min(1.0, sum(d.score_delta for d in drivers))
        floor_drag = sum(d.floor_drag for d in drivers)
        ceiling_lift = sum(d.ceiling_lift for d in drivers)

        value_low = max(0.0, value - floor_drag)
        value_high = min(150.0, value + ceiling_lift)

        risk_level = "Extreme"
        for threshold, level in RISK_LEVELS:
            if risk_score <= threshold:
                risk_level = level
                break

        return RiskAssessment(
            risk_score=round(risk_score, 3),
            risk_level=risk_level,
            value_low=round(value_low, 1),
            value_high=round(value_high, 1),
            drivers=tuple(drivers),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_risk -v`
Expected: All tests PASS (8 from Task 1 + 16 from Task 2 = 24)

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add src/league_values/risk.py tests/test_risk.py
git commit -m "feat(risk): RiskModel with _build_assessment — score, levels, clamping"
```

---

### Task 3: Dynasty Driver Detection

**Files:**
- Modify: `src/league_values/risk.py`
- Modify: `tests/test_risk.py`

- [ ] **Step 1: Write failing tests for driver detection**

Add to `tests/test_risk.py`. Use `types.SimpleNamespace` for duck-typed rows:

```python
from types import SimpleNamespace


def _mlb_row(**kwargs):
    """Build a minimal MLB dynasty row for testing."""
    defaults = dict(
        player_type="mlb", positions=("OF",), age=28, dynasty_value=80.0,
        eta=None, level=None, source_ranks=None, breakout_label=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _prospect_row(**kwargs):
    """Build a minimal prospect dynasty row for testing."""
    defaults = dict(
        player_type="prospect", positions=("SS",), age=20, dynasty_value=50.0,
        eta=2028, level="AA", source_ranks={"pipeline": 30, "hkb": 45},
        breakout_label=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestBaselineDriver(unittest.TestCase):
    def test_baseline_always_fires_mlb(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row())
        ids = [d.id for d in drivers]
        self.assertIn("baseline", ids)

    def test_baseline_always_fires_prospect(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row())
        ids = [d.id for d in drivers]
        self.assertIn("baseline", ids)


class TestPitcherTypeDriver(unittest.TestCase):
    def test_fires_for_sp(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(positions=("SP",)))
        ids = [d.id for d in drivers]
        self.assertIn("pitcher_type", ids)

    def test_fires_for_rp(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(positions=("RP",)))
        ids = [d.id for d in drivers]
        self.assertIn("pitcher_type", ids)

    def test_skips_hitters(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(positions=("OF",)))
        ids = [d.id for d in drivers]
        self.assertNotIn("pitcher_type", ids)

    def test_pitcher_type_weights(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(positions=("SP",)))
        d = next(d for d in drivers if d.id == "pitcher_type")
        self.assertAlmostEqual(d.score_delta, 0.05)
        self.assertAlmostEqual(d.floor_drag, 5)
        self.assertAlmostEqual(d.ceiling_lift, 3)


class TestPitcherProspectDriver(unittest.TestCase):
    def test_fires_for_pitcher_prospect(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(positions=("SP",)))
        ids = [d.id for d in drivers]
        self.assertIn("pitcher_prospect", ids)
        self.assertIn("pitcher_type", ids)  # both fire

    def test_skips_mlb_pitcher(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(positions=("SP",)))
        ids = [d.id for d in drivers]
        self.assertNotIn("pitcher_prospect", ids)

    def test_skips_hitter_prospect(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(positions=("SS",)))
        ids = [d.id for d in drivers]
        self.assertNotIn("pitcher_prospect", ids)


class TestProspectStatusDriver(unittest.TestCase):
    def test_fires_for_prospects(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row())
        ids = [d.id for d in drivers]
        self.assertIn("prospect_status", ids)

    def test_skips_mlb(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row())
        ids = [d.id for d in drivers]
        self.assertNotIn("prospect_status", ids)


class TestEtaDrivers(unittest.TestCase):
    def test_eta_distant_fires(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(eta=2028))
        ids = [d.id for d in drivers]
        self.assertIn("eta_distant", ids)
        self.assertNotIn("eta_near", ids)

    def test_eta_near_fires(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(eta=2027))
        ids = [d.id for d in drivers]
        self.assertIn("eta_near", ids)
        self.assertNotIn("eta_distant", ids)

    def test_eta_current_year_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(eta=2026))
        ids = [d.id for d in drivers]
        self.assertNotIn("eta_distant", ids)
        self.assertNotIn("eta_near", ids)

    def test_eta_none_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(eta=None))
        ids = [d.id for d in drivers]
        self.assertNotIn("eta_distant", ids)
        self.assertNotIn("eta_near", ids)

    def test_eta_mlb_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(eta=2028))
        ids = [d.id for d in drivers]
        self.assertNotIn("eta_distant", ids)

    def test_eta_distant_label_includes_year(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(eta=2029))
        d = next(d for d in drivers if d.id == "eta_distant")
        self.assertEqual(d.label, "ETA 2029")

    def test_injected_year_affects_eta(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2025)
        drivers = model._dynasty_drivers(_prospect_row(eta=2027))
        ids = [d.id for d in drivers]
        self.assertIn("eta_distant", ids)  # 2027 >= 2025+2


class TestLevelDrivers(unittest.TestCase):
    def test_low_minors_a(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level="A"))
        ids = [d.id for d in drivers]
        self.assertIn("low_minors", ids)

    def test_low_minors_cpx(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level="CPX"))
        ids = [d.id for d in drivers]
        self.assertIn("low_minors", ids)

    def test_low_minors_a_plus(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level="A+"))
        ids = [d.id for d in drivers]
        self.assertIn("low_minors", ids)

    def test_low_minors_r(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level="R"))
        ids = [d.id for d in drivers]
        self.assertIn("low_minors", ids)

    def test_mid_minors_aa(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level="AA"))
        ids = [d.id for d in drivers]
        self.assertIn("mid_minors", ids)
        self.assertNotIn("low_minors", ids)
        self.assertNotIn("high_minors", ids)

    def test_high_minors_aaa(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level="AAA"))
        ids = [d.id for d in drivers]
        self.assertIn("high_minors", ids)
        self.assertNotIn("low_minors", ids)
        self.assertNotIn("mid_minors", ids)

    def test_level_none_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level=None))
        ids = [d.id for d in drivers]
        for lvl in ("low_minors", "mid_minors", "high_minors"):
            self.assertNotIn(lvl, ids)

    def test_level_mlb_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(level="AA"))
        ids = [d.id for d in drivers]
        self.assertNotIn("mid_minors", ids)


class TestSourceSpreadDriver(unittest.TestCase):
    def test_fires_above_threshold(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        # Spread 0.38 on normalized scale (pipeline max=100, hkb max=719)
        # 10/100=0.10 vs 400/719=0.56 -> spread 0.46 > 0.30
        drivers = model._dynasty_drivers(_prospect_row(source_ranks={"pipeline": 10, "hkb": 400}))
        ids = [d.id for d in drivers]
        self.assertIn("source_spread", ids)

    def test_skips_below_threshold(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        # Very tight agreement
        drivers = model._dynasty_drivers(_prospect_row(source_ranks={"pipeline": 10, "hkb": 12}))
        ids = [d.id for d in drivers]
        self.assertNotIn("source_spread", ids)

    def test_filters_non_numeric(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(source_ranks={"a": "N/A", "b": 10}))
        ids = [d.id for d in drivers]
        self.assertNotIn("source_spread", ids)  # only 1 numeric, needs 2

    def test_requires_two_values(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(source_ranks={"pipeline": 10}))
        ids = [d.id for d in drivers]
        self.assertNotIn("source_spread", ids)

    def test_none_source_ranks_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(source_ranks=None))
        ids = [d.id for d in drivers]
        self.assertNotIn("source_spread", ids)

    def test_mlb_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(source_ranks={"a": 10, "b": 400}))
        ids = [d.id for d in drivers]
        self.assertNotIn("source_spread", ids)


class TestAgeYoungDriver(unittest.TestCase):
    def test_fires_for_young_prospect(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(age=19))
        ids = [d.id for d in drivers]
        self.assertIn("age_young", ids)

    def test_fires_at_boundary_21(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(age=21))
        ids = [d.id for d in drivers]
        self.assertIn("age_young", ids)

    def test_skips_age_22_prospect(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(age=22))
        ids = [d.id for d in drivers]
        self.assertNotIn("age_young", ids)

    def test_skips_young_mlb(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(age=21))
        ids = [d.id for d in drivers]
        self.assertNotIn("age_young", ids)

    def test_label_includes_age(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(age=18))
        d = next(d for d in drivers if d.id == "age_young")
        self.assertEqual(d.label, "Age 18 (young)")


class TestAgeDeclineDrivers(unittest.TestCase):
    def test_decline_fires_at_33(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(age=33))
        ids = [d.id for d in drivers]
        self.assertIn("age_decline", ids)
        self.assertNotIn("age_deep_decline", ids)

    def test_decline_skips_32(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(age=32))
        ids = [d.id for d in drivers]
        self.assertNotIn("age_decline", ids)

    def test_deep_decline_stacks_at_36(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(age=36))
        ids = [d.id for d in drivers]
        self.assertIn("age_decline", ids)
        self.assertIn("age_deep_decline", ids)

    def test_deep_decline_stacks_at_37(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(age=37))
        ids = [d.id for d in drivers]
        self.assertIn("age_decline", ids)
        self.assertIn("age_deep_decline", ids)

    def test_decline_label_includes_age(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(age=34))
        d = next(d for d in drivers if d.id == "age_decline")
        self.assertEqual(d.label, "Age 34 (decline)")

    def test_age_none_skipped(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(age=None))
        ids = [d.id for d in drivers]
        self.assertNotIn("age_decline", ids)
        self.assertNotIn("age_deep_decline", ids)


class TestIncompleteProfileDriver(unittest.TestCase):
    def test_fires_missing_eta(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(eta=None))
        ids = [d.id for d in drivers]
        self.assertIn("incomplete_profile", ids)

    def test_fires_missing_level(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(level=None))
        ids = [d.id for d in drivers]
        self.assertIn("incomplete_profile", ids)

    def test_fires_missing_source_ranks(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(source_ranks=None))
        ids = [d.id for d in drivers]
        self.assertIn("incomplete_profile", ids)

    def test_skips_complete_profile(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(eta=2028, level="AA", source_ranks={"a": 10}))
        ids = [d.id for d in drivers]
        self.assertNotIn("incomplete_profile", ids)

    def test_skips_mlb(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row())
        ids = [d.id for d in drivers]
        self.assertNotIn("incomplete_profile", ids)


class TestBreakoutHeliumDriver(unittest.TestCase):
    def test_fires_for_major_breakout(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(breakout_label="major_breakout"))
        ids = [d.id for d in drivers]
        self.assertIn("breakout_helium", ids)

    def test_fires_for_breakout(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(breakout_label="breakout"))
        ids = [d.id for d in drivers]
        self.assertIn("breakout_helium", ids)

    def test_fires_for_rising(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(breakout_label="rising"))
        ids = [d.id for d in drivers]
        self.assertIn("breakout_helium", ids)

    def test_skips_steady(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(breakout_label="steady"))
        ids = [d.id for d in drivers]
        self.assertNotIn("breakout_helium", ids)

    def test_skips_slipping(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(breakout_label="slipping"))
        ids = [d.id for d in drivers]
        self.assertNotIn("breakout_helium", ids)

    def test_skips_falling(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(breakout_label="falling"))
        ids = [d.id for d in drivers]
        self.assertNotIn("breakout_helium", ids)

    def test_skips_none(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_prospect_row(breakout_label=None))
        ids = [d.id for d in drivers]
        self.assertNotIn("breakout_helium", ids)

    def test_skips_mlb(self):
        from league_values.risk import RiskModel
        model = RiskModel(current_year=2026)
        drivers = model._dynasty_drivers(_mlb_row(breakout_label="breakout"))
        ids = [d.id for d in drivers]
        # breakout can fire for MLB too if they have the field
        # just testing the label check works regardless of player type
        self.assertIn("breakout_helium", ids)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_risk -v 2>&1 | tail -5`
Expected: Many FAILs — drivers list is empty from stub

- [ ] **Step 3: Implement _dynasty_drivers**

Replace the stub `_dynasty_drivers` in `src/league_values/risk.py` with the full implementation.

Source spread uses **percentile normalization**: each rank is divided by a per-source max constant (derived from feed data analysis). Spread threshold: 0.30.

```python
# Add near top of file, after RISK_LEVELS
SOURCE_RANK_MAXES: dict[str, float] = {
    "pipeline": 100,
    "cfr": 5232,
    "hkb": 719,
    "milb_perf": 500,
    "milb_breakout": 205,
}
SOURCE_SPREAD_THRESHOLD = 0.30
```

Full `_dynasty_drivers` implementation:

```python
    def _dynasty_drivers(self, row) -> list[RiskDriver]:
        drivers: list[RiskDriver] = []
        player_type = getattr(row, "player_type", "mlb")
        positions = getattr(row, "positions", ()) or ()
        age = getattr(row, "age", None)
        eta = getattr(row, "eta", None)
        level = getattr(row, "level", None)
        source_ranks = getattr(row, "source_ranks", None)
        breakout_label = getattr(row, "breakout_label", None)

        is_prospect = player_type == "prospect"
        is_pitcher = any(p in ("SP", "RP") for p in positions)

        # Baseline — always fires
        drivers.append(RiskDriver("baseline", "Baseline uncertainty", 0.03, 3, 3))

        # Pitcher volatility
        if is_pitcher:
            drivers.append(RiskDriver("pitcher_type", "Pitcher volatility", 0.05, 5, 3))

        # Pitcher prospect (stacks with pitcher_type)
        if is_pitcher and is_prospect:
            drivers.append(RiskDriver("pitcher_prospect", "Pitcher prospect", 0.08, 8, 6))

        # Prospect status
        if is_prospect:
            drivers.append(RiskDriver("prospect_status", "Prospect", 0.10, 8, 10))

        # ETA (prospects only, mutually exclusive)
        if is_prospect and eta is not None:
            if eta >= self.current_year + 2:
                drivers.append(RiskDriver("eta_distant", f"ETA {eta}", 0.12, 8, 5))
            elif eta == self.current_year + 1:
                drivers.append(RiskDriver("eta_near", f"ETA {eta}", 0.04, 3, 3))

        # Level (prospects only, mutually exclusive)
        if is_prospect and level is not None:
            if level in ("A", "A+", "CPX", "R"):
                drivers.append(RiskDriver("low_minors", "Low-minors level", 0.12, 10, 8))
            elif level == "AA":
                drivers.append(RiskDriver("mid_minors", "Mid-minors level", 0.06, 5, 4))
            elif level == "AAA":
                drivers.append(RiskDriver("high_minors", "Upper-minors level", 0.03, 3, 3))

        # Source rank spread (prospects only, percentile-normalized)
        if is_prospect and source_ranks:
            normalized = []
            for src, rank in source_ranks.items():
                if isinstance(rank, (int, float)):
                    max_val = SOURCE_RANK_MAXES.get(src)
                    if max_val and max_val > 0:
                        normalized.append(rank / max_val)
            if len(normalized) >= 2:
                spread = max(normalized) - min(normalized)
                if spread > SOURCE_SPREAD_THRESHOLD:
                    drivers.append(RiskDriver("source_spread", "High source-rank spread", 0.08, 7, 4))

        # Age: young prospect
        if is_prospect and age is not None and age <= 21:
            drivers.append(RiskDriver("age_young", f"Age {age} (young)", 0.06, 5, 6))

        # Age: decline (any player)
        if age is not None and age >= 33:
            drivers.append(RiskDriver("age_decline", f"Age {age} (decline)", 0.10, 8, 1))

        # Age: deep decline (stacks with age_decline)
        if age is not None and age >= 36:
            drivers.append(RiskDriver("age_deep_decline", f"Age {age} (deep decline)", 0.06, 5, 0))

        # Incomplete profile (prospects missing key data)
        if is_prospect:
            if eta is None or level is None or not source_ranks:
                drivers.append(RiskDriver("incomplete_profile", "Incomplete scouting profile", 0.05, 5, 3))

        # Breakout / helium (positive labels only)
        if breakout_label and breakout_label.lower() in self.POSITIVE_BREAKOUT_LABELS:
            drivers.append(RiskDriver("breakout_helium", "Breakout / helium", 0.05, 3, 8))

        return drivers
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_risk -v 2>&1 | tail -5`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add src/league_values/risk.py tests/test_risk.py
git commit -m "feat(risk): dynasty driver detection — 14 drivers with percentile-normalized source spread"
```

---

### Task 4: Archetype Integration Tests

**Files:**
- Modify: `tests/test_risk.py`

- [ ] **Step 1: Write archetype tests**

Add to `tests/test_risk.py`:

```python
class TestArchetypes(unittest.TestCase):
    """Full player profiles matching real dynasty archetypes."""

    def _model(self):
        from league_values.risk import RiskModel
        return RiskModel(current_year=2026)

    def test_mlb_veteran_stable(self):
        """Aaron Judge type — 33yo OF. Baseline + age_decline -> Low."""
        model = self._model()
        row = _mlb_row(age=33, positions=("OF",), dynasty_value=121.5)
        assessment = model.evaluate_dynasty(row)
        self.assertEqual(assessment.risk_level, "Low")
        self.assertAlmostEqual(assessment.risk_score, 0.13, places=2)
        self.assertLessEqual(assessment.value_low, 111.0)
        self.assertGreaterEqual(assessment.value_high, 125.0)

    def test_mlb_pitcher_young(self):
        """Paul Skenes type — 23yo SP MLB. Baseline + pitcher_type -> Low."""
        model = self._model()
        row = _mlb_row(age=23, positions=("SP",), dynasty_value=148.0)
        assessment = model.evaluate_dynasty(row)
        self.assertEqual(assessment.risk_level, "Low")
        # Ceiling clamped at 150
        self.assertEqual(assessment.value_high, 150.0)

    def test_prospect_pitcher_mid(self):
        """Trey Yesavage type — 23yo SP prospect, AA, ETA 2028."""
        model = self._model()
        row = _prospect_row(
            age=23, positions=("SP",), dynasty_value=98.2,
            eta=2028, level="AA",
            source_ranks={"pipeline": 9, "cfr": 168.0, "hkb": 3},
        )
        assessment = model.evaluate_dynasty(row)
        # baseline + pitcher_type + pitcher_prospect + prospect_status + eta_distant + mid_minors + source_spread
        self.assertIn(assessment.risk_level, ("Moderate", "High"))
        self.assertLess(assessment.value_low, 65.0)
        self.assertGreater(assessment.value_high, 120.0)

    def test_prospect_complex_young(self):
        """17yo A-ball hitter prospect. Many drivers stack -> High/Extreme."""
        model = self._model()
        row = _prospect_row(
            age=17, positions=("SS",), dynasty_value=5.2,
            eta=2030, level="A",
            source_ranks=None,  # incomplete profile too
        )
        assessment = model.evaluate_dynasty(row)
        self.assertIn(assessment.risk_level, ("High", "Extreme"))
        self.assertEqual(assessment.value_low, 0.0)  # clamped

    def test_mlb_aging_decline(self):
        """37yo veteran hitter. Baseline + decline + deep_decline."""
        model = self._model()
        row = _mlb_row(age=37, positions=("1B",), dynasty_value=60.0)
        assessment = model.evaluate_dynasty(row)
        # score = 0.03 + 0.10 + 0.06 = 0.19 -> Low
        self.assertEqual(assessment.risk_level, "Low")
        # Floor heavily dragged: 60 - 3 - 8 - 5 = 44
        self.assertAlmostEqual(assessment.value_low, 44.0, places=1)
        # Ceiling barely lifted: 60 + 3 + 1 + 0 = 64
        self.assertAlmostEqual(assessment.value_high, 64.0, places=1)

    def test_evaluate_dynasty_with_explicit_value(self):
        """Passing value kwarg overrides row.dynasty_value."""
        model = self._model()
        row = _mlb_row(dynasty_value=100.0)
        a1 = model.evaluate_dynasty(row)
        a2 = model.evaluate_dynasty(row, value=50.0)
        self.assertAlmostEqual(a1.value_low, 97.0, places=1)  # 100 - 3
        self.assertAlmostEqual(a2.value_low, 47.0, places=1)  # 50 - 3

    def test_risk_assessments_keyed_by_row_id(self):
        """Simulate app-level mapping pattern."""
        model = self._model()
        rows = [
            _mlb_row(dynasty_value=100.0),
            _prospect_row(dynasty_value=50.0),
        ]
        # Give them distinct IDs
        rows[0].id = "mlb_judge"
        rows[1].id = "prospect_kid"
        risk_assessments = {row.id: model.evaluate_dynasty(row) for row in rows}
        self.assertIn("mlb_judge", risk_assessments)
        self.assertIn("prospect_kid", risk_assessments)
        self.assertEqual(risk_assessments["mlb_judge"].risk_level, "Low")
```

- [ ] **Step 2: Run all tests**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.test_risk -v 2>&1 | tail -5`
Expected: All tests PASS (no new implementation needed — validates Tasks 2+3)

- [ ] **Step 3: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add tests/test_risk.py
git commit -m "test(risk): archetype integration tests — Judge, Skenes, Yesavage, complex prospect"
```

---

### Task 5: Wire Risk Into App Routes

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add risk import and model instantiation**

At top of `app.py`, add import:

```python
from league_values.risk import RiskModel
```

After the `dd_store = DDFeedStore(...)` line (~line 43), add:

```python
# Risk model for dynasty/prospect annotations
risk_model = RiskModel()
```

- [ ] **Step 2: Add risk_assessments to _build_dynasty_context**

In `_build_dynasty_context` (around line 103), after `rows = rows[:200]`, compute risk assessments and add to the returned dict:

```python
def _build_dynasty_context(args):
    """Build template context for DD Dynasty mode. Bypasses engine entirely."""
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")
    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    rows = rows[:200]
    dynasty_dollars = _compute_dynasty_dollars(rows)
    tiers = _compute_dynasty_tiers(rows)
    risk_assessments = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
    return {
        "mode": "dd_dynasty",
        "pool": pool,
        "position": position,
        "search": search,
        "dd_rows": rows,
        "dynasty_dollars": dynasty_dollars,
        "tiers": tiers,
        "risk_assessments": risk_assessments,
        "dd_available": dd_store.is_available,
        "dd_generated_at": dd_store.generated_at,
        "as_of": store.as_of,
    }
```

- [ ] **Step 3: Add risk to prospects mode context**

In the `index()` route (around line 426-436), after re-filtering prospect rows, recompute risk:

```python
        if mode == "prospects":
            rows = dd_store.filter(
                pool="prospect",
                position=ctx.get("position") or None,
                search=ctx.get("search") or None,
            )
            rows = rows[:200]
            ctx["dd_rows"] = rows
            ctx["dynasty_dollars"] = _compute_dynasty_dollars(rows)
            ctx["tiers"] = _compute_dynasty_tiers(rows)
            ctx["risk_assessments"] = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
            ctx["mode"] = "prospects"
```

Apply the same pattern in the `rankings()` route (around line 457-465):

```python
            if mode == "prospects":
                rows = dd_store.filter(
                    pool="prospect",
                    position=ctx.get("position") or None,
                    search=ctx.get("search") or None,
                )
                rows = rows[:200]
                ctx["dd_rows"] = rows
                ctx["dynasty_dollars"] = _compute_dynasty_dollars(rows)
                ctx["tiers"] = _compute_dynasty_tiers(rows)
                ctx["risk_assessments"] = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
                ctx["mode"] = "prospects"
```

- [ ] **Step 4: Add risk to player detail route**

In the `player_detail()` route (around line 499-523), compute risk for the single row and pass to template:

```python
    if mode in ("dd_dynasty", "prospects") and dd_store.is_available:
        dd_row = dd_store.get_by_id(player_id)
        if dd_row is None:
            return "<div class='error'>Player not found</div>", 404

        risk = risk_model.evaluate_dynasty(dd_row)

        mlb_stats = None
        mlb_stats_actual = None
        mlb_stats_ros = None
        if not dd_row.is_prospect:
            name_lower = dd_row.name.lower()
            for proj in store.get_all():
                if proj.name.lower() == name_lower:
                    mlb_stats = proj.stats
                    mlb_stats_actual = proj.metadata.get("stats_actual")
                    mlb_stats_ros = proj.metadata.get("stats_ros")
                    break

        return render_template(
            "partials/player_detail_dynasty.html",
            row=dd_row,
            risk=risk,
            mlb_stats=mlb_stats,
            mlb_stats_actual=mlb_stats_actual,
            mlb_stats_ros=mlb_stats_ros,
        )
```

- [ ] **Step 5: Verify app starts without errors**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -c "from app import app; print('OK')"
Expected: `OK` (no import errors)

- [ ] **Step 6: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add app.py
git commit -m "feat(risk): wire risk_assessments into dynasty/prospect routes"
```

---

### Task 6: Template & CSS Updates

**Files:**
- Modify: `templates/partials/rankings_table_dynasty.html`
- Modify: `templates/partials/player_detail_dynasty.html`
- Modify: `static/style.css`

- [ ] **Step 1: Add Risk and Range columns to rankings table**

In `templates/partials/rankings_table_dynasty.html`, add two header columns after the Dynasty Value `<th>`:

```html
            <th class="col-risk sortable" onclick="sortTable(6)">Risk</th>
            <th class="col-range">Range</th>
```

Update the `colspan` on the detail row from 6 to 8.

In the `<tbody>` row, after the dynasty value `<td>`, add:

```html
            {% set risk = risk_assessments.get(row.id) if risk_assessments is defined else None %}
            <td class="col-risk">
                {% if risk %}
                <span class="risk-badge risk-{{ risk.risk_level | lower }}">{{ risk.risk_level }}</span>
                {% endif %}
            </td>
            <td class="col-range">
                {% if risk %}
                {{ "%.0f" | format(risk.value_low) }}–{{ "%.0f" | format(risk.value_high) }}
                {% endif %}
            </td>
```

- [ ] **Step 2: Add risk block to player detail**

In `templates/partials/player_detail_dynasty.html`, after the `<span class="detail-value val-pos">` block (line 9-11), add:

```html
        {% if risk %}
        <div class="risk-block">
            <span class="risk-badge risk-{{ risk.risk_level | lower }}">{{ risk.risk_level }}</span>
            <span class="risk-range">Range: {{ "%.0f" | format(risk.value_low) }}–{{ "%.0f" | format(risk.value_high) }}</span>
            {% if risk.driver_labels %}
            <div class="risk-drivers">{{ risk.driver_labels | join(', ') }}</div>
            {% endif %}
        </div>
        {% endif %}
```

- [ ] **Step 3: Add risk badge CSS**

Append to `static/style.css`:

```css
/* Risk badges */
.risk-badge {
    display: inline-block;
    font-size: 0.65rem;
    font-weight: 700;
    color: #fff;
    border-radius: 3px;
    padding: 0.1rem 0.35rem;
    vertical-align: middle;
}
.risk-low { background: #059669; }
.risk-moderate { background: #d97706; }
.risk-high { background: #ea580c; }
.risk-extreme { background: #dc2626; }

.col-risk { text-align: center; white-space: nowrap; }
.col-range { text-align: center; white-space: nowrap; font-size: 0.85rem; color: #6b7280; }

.risk-block {
    margin-top: 0.5rem;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
}
.risk-range {
    font-size: 0.85rem;
    color: #6b7280;
}
.risk-drivers {
    width: 100%;
    font-size: 0.78rem;
    color: #9ca3af;
    margin-top: 0.15rem;
}
```

- [ ] **Step 4: Verify in browser**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python app.py`
Open `http://localhost:5001/?mode=dd_dynasty` — verify Risk and Range columns appear.
Click a player — verify risk block shows in detail modal.
Check `http://localhost:5001/?mode=prospects` — verify same columns.

- [ ] **Step 5: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add templates/partials/rankings_table_dynasty.html templates/partials/player_detail_dynasty.html static/style.css
git commit -m "feat(risk): dynasty/prospect table Risk+Range columns, detail risk block, badge CSS"
```

---

### Task 7: CSV Export + App Integration Tests

**Files:**
- Modify: `app.py` (export route)
- Modify: `tests/test_app.py`

- [ ] **Step 1: Add risk columns to CSV export**

In the `export_csv()` function (around line 569-602), in the dynasty/prospects CSV branch, update the header and row writer:

Replace the current dynasty CSV header:

```python
        writer.writerow(["Overall Dynasty Rank", "Player", "Type", "Positions", "Team",
                         "Age", "Dynasty Value", "Dynasty $", "Prospect Rank", "Level", "ETA"])
```

With:

```python
        risk_assessments = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
        writer.writerow(["Overall Dynasty Rank", "Player", "Type", "Positions", "Team",
                         "Age", "Dynasty Value", "Dynasty $", "Risk Level", "Value Low",
                         "Value High", "Risk Drivers", "Prospect Rank", "Level", "ETA"])
```

Replace the row writer:

```python
        for row in rows:
            risk = risk_assessments.get(row.id)
            writer.writerow([
                row.dynasty_rank, row.name, row.player_type.upper(),
                ", ".join(row.positions) or "", row.team, row.age or "",
                row.dynasty_value, dynasty_dollars.get(row.id, 0),
                risk.risk_level if risk else "",
                risk.value_low if risk else "",
                risk.value_high if risk else "",
                ", ".join(risk.driver_labels) if risk else "",
                row.prospect_rank or "", row.level or "", row.eta or "",
            ])
```

- [ ] **Step 2: Write app integration tests**

Add to `tests/test_app.py`:

```python
class TestRiskIntegration(unittest.TestCase):
    """Risk model integration with dynasty/prospect routes."""
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_dynasty_table_shows_risk_column(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"col-risk", response.data)
        self.assertIn(b"risk-badge", response.data)

    def test_prospects_table_shows_risk_column(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=prospects")
        self.assertIn(b"col-risk", response.data)
        self.assertIn(b"risk-badge", response.data)

    def test_dynasty_player_detail_shows_risk_block(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        rows = dd_store.filter()
        if not rows:
            self.skipTest("No dynasty rows")
        response = self.client.get(f"/player/{rows[0].id}?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"risk-block", response.data)

    def test_prospect_player_detail_shows_risk_block(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        rows = dd_store.filter(pool="prospect")
        if not rows:
            self.skipTest("No prospect rows")
        response = self.client.get(f"/player/{rows[0].id}?mode=prospects")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"risk-block", response.data)

    def test_dynasty_export_includes_risk_columns(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/export?mode=dd_dynasty")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertIn("Risk Level", header)
        self.assertIn("Value Low", header)
        self.assertIn("Value High", header)
        self.assertIn("Risk Drivers", header)

    def test_prospects_export_includes_risk_columns(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/export?mode=prospects")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertIn("Risk Level", header)
        self.assertIn("Value Low", header)
        self.assertIn("Value High", header)
        self.assertIn("Risk Drivers", header)
```

- [ ] **Step 3: Run full test suite**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v 2>&1 | tail -10`
Expected: All tests PASS (existing + new risk + new app integration)

- [ ] **Step 4: Commit**

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git add app.py tests/test_app.py
git commit -m "feat(risk): CSV export risk columns + app integration tests"
```

- [ ] **Step 5: Run full suite one more time, push**

Run: `cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values" && PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest discover -s tests -v 2>&1 | tail -5`
Expected: All PASS

```bash
cd "C:/Users/Alex/Documents/Codex/2026-05-18/league-values"
git push
```
