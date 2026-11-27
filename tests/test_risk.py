"""Tests for the Risk/Uncertainty model."""

import unittest
from types import SimpleNamespace

from league_values.risk import (
    RiskDriver,
    RiskAssessment,
    RiskModel,
    RISK_LEVELS,
    SOURCE_RANK_MAXES,
    SOURCE_SPREAD_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mlb_row(**kwargs):
    defaults = dict(
        player_type="mlb", positions=("OF",), age=28, dynasty_value=80.0,
        eta=None, level=None, source_ranks=None, breakout_label=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _prospect_row(**kwargs):
    defaults = dict(
        player_type="prospect", positions=("SS",), age=20, dynasty_value=50.0,
        eta=2028, level="AA", source_ranks={"pipeline": 30, "hkb": 45},
        breakout_label=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Task 1: Core types
# ---------------------------------------------------------------------------

class TestRiskDriver(unittest.TestCase):

    def test_frozen_dataclass(self):
        d = RiskDriver("test_id", "Test Label", 0.10, 5.0, 3.0)
        self.assertEqual(d.id, "test_id")
        self.assertEqual(d.label, "Test Label")
        self.assertEqual(d.score_delta, 0.10)
        self.assertEqual(d.floor_drag, 5.0)
        self.assertEqual(d.ceiling_lift, 3.0)

    def test_immutable(self):
        d = RiskDriver("id", "Label", 0.05, 2.0, 1.0)
        with self.assertRaises(Exception):
            d.id = "new_id"  # type: ignore[misc]

    def test_equality(self):
        d1 = RiskDriver("a", "A", 0.1, 1.0, 2.0)
        d2 = RiskDriver("a", "A", 0.1, 1.0, 2.0)
        self.assertEqual(d1, d2)


class TestRiskAssessment(unittest.TestCase):

    def _make(self, drivers=()):
        return RiskAssessment(
            risk_score=0.30,
            risk_level="Moderate",
            value_low=45.0,
            value_high=65.0,
            drivers=tuple(drivers),
        )

    def test_frozen(self):
        ra = self._make()
        with self.assertRaises(Exception):
            ra.risk_score = 0.99  # type: ignore[misc]

    def test_driver_labels_empty(self):
        ra = self._make()
        self.assertEqual(ra.driver_labels, ())

    def test_driver_labels(self):
        d1 = RiskDriver("a", "Alpha", 0.05, 1, 1)
        d2 = RiskDriver("b", "Beta", 0.05, 1, 1)
        ra = self._make(drivers=(d1, d2))
        self.assertEqual(ra.driver_labels, ("Alpha", "Beta"))

    def test_to_dict_keys(self):
        ra = self._make()
        d = ra.to_dict()
        self.assertIn("risk_score", d)
        self.assertIn("risk_level", d)
        self.assertIn("value_low", d)
        self.assertIn("value_high", d)
        self.assertIn("drivers", d)

    def test_to_dict_drivers_list_of_labels(self):
        d1 = RiskDriver("x", "X Label", 0.01, 1, 1)
        ra = self._make(drivers=(d1,))
        result = ra.to_dict()
        self.assertEqual(result["drivers"], ["X Label"])

    def test_to_dict_values(self):
        ra = self._make()
        d = ra.to_dict()
        self.assertEqual(d["risk_score"], 0.30)
        self.assertEqual(d["risk_level"], "Moderate")
        self.assertEqual(d["value_low"], 45.0)
        self.assertEqual(d["value_high"], 65.0)


class TestRiskLevels(unittest.TestCase):

    def test_is_tuple(self):
        self.assertIsInstance(RISK_LEVELS, tuple)

    def test_four_entries(self):
        self.assertEqual(len(RISK_LEVELS), 4)

    def test_ascending_thresholds(self):
        thresholds = [t for t, _ in RISK_LEVELS]
        self.assertEqual(thresholds, sorted(thresholds))

    def test_top_threshold_is_one(self):
        self.assertEqual(RISK_LEVELS[-1][0], 1.00)

    def test_level_names(self):
        names = [n for _, n in RISK_LEVELS]
        self.assertIn("Low", names)
        self.assertIn("Moderate", names)
        self.assertIn("High", names)
        self.assertIn("Extreme", names)


# ---------------------------------------------------------------------------
# Task 2: _build_assessment
# ---------------------------------------------------------------------------

class TestBuildAssessment(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def _build(self, value, drivers):
        return self.model._build_assessment(value, drivers)

    def test_empty_drivers(self):
        ra = self._build(50.0, [])
        self.assertEqual(ra.risk_score, 0.0)
        self.assertEqual(ra.risk_level, "Low")
        self.assertEqual(ra.value_low, 50.0)
        self.assertEqual(ra.value_high, 50.0)

    def test_single_driver_score(self):
        d = RiskDriver("x", "X", 0.20, 5.0, 3.0)
        ra = self._build(60.0, [d])
        self.assertAlmostEqual(ra.risk_score, 0.200)
        self.assertEqual(ra.value_low, 55.0)
        self.assertEqual(ra.value_high, 63.0)

    def test_multiple_drivers_sum(self):
        drivers = [
            RiskDriver("a", "A", 0.10, 4.0, 2.0),
            RiskDriver("b", "B", 0.20, 6.0, 3.0),
        ]
        ra = self._build(80.0, drivers)
        self.assertAlmostEqual(ra.risk_score, 0.300)
        self.assertEqual(ra.value_low, 70.0)
        self.assertEqual(ra.value_high, 85.0)

    def test_score_capped_at_one(self):
        drivers = [RiskDriver(f"d{i}", f"D{i}", 0.40, 0, 0) for i in range(4)]
        ra = self._build(50.0, drivers)
        self.assertEqual(ra.risk_score, 1.0)

    def test_value_low_floor_at_zero(self):
        d = RiskDriver("x", "X", 0.10, 200.0, 0.0)
        ra = self._build(10.0, [d])
        self.assertEqual(ra.value_low, 0.0)

    def test_value_high_ceiling_at_150(self):
        d = RiskDriver("x", "X", 0.10, 0.0, 200.0)
        ra = self._build(140.0, [d])
        self.assertEqual(ra.value_high, 150.0)

    def test_risk_level_low(self):
        d = RiskDriver("x", "X", 0.10, 0, 0)
        ra = self._build(50.0, [d])
        self.assertEqual(ra.risk_level, "Low")

    def test_risk_level_moderate(self):
        d = RiskDriver("x", "X", 0.40, 0, 0)
        ra = self._build(50.0, [d])
        self.assertEqual(ra.risk_level, "Moderate")

    def test_risk_level_high(self):
        d = RiskDriver("x", "X", 0.60, 0, 0)
        ra = self._build(50.0, [d])
        self.assertEqual(ra.risk_level, "High")

    def test_risk_level_extreme(self):
        d = RiskDriver("x", "X", 0.90, 0, 0)
        ra = self._build(50.0, [d])
        self.assertEqual(ra.risk_level, "Extreme")

    def test_risk_level_boundary_low(self):
        # Exactly 0.25 → Low
        d = RiskDriver("x", "X", 0.25, 0, 0)
        ra = self._build(50.0, [d])
        self.assertEqual(ra.risk_level, "Low")

    def test_risk_level_boundary_moderate(self):
        # Exactly 0.50 → Moderate
        d = RiskDriver("x", "X", 0.50, 0, 0)
        ra = self._build(50.0, [d])
        self.assertEqual(ra.risk_level, "Moderate")

    def test_risk_score_rounded_to_3dp(self):
        d = RiskDriver("x", "X", 0.123456789, 0, 0)
        ra = self._build(50.0, [d])
        self.assertEqual(ra.risk_score, round(0.123456789, 3))

    def test_drivers_tuple_in_output(self):
        d = RiskDriver("x", "X", 0.10, 0, 0)
        ra = self._build(50.0, [d])
        self.assertIsInstance(ra.drivers, tuple)
        self.assertEqual(len(ra.drivers), 1)


class TestRiskModelConstructor(unittest.TestCase):

    def test_default_year_is_current(self):
        from datetime import date
        model = RiskModel()
        self.assertEqual(model.current_year, date.today().year)

    def test_injected_year(self):
        model = RiskModel(current_year=2030)
        self.assertEqual(model.current_year, 2030)


# ---------------------------------------------------------------------------
# Task 3: dynasty driver detection
# ---------------------------------------------------------------------------

class TestBaselineDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_for_mlb(self):
        ra = self.model.evaluate_dynasty(_mlb_row())
        self.assertIn("baseline", [d.id for d in ra.drivers])

    def test_fires_for_prospect(self):
        ra = self.model.evaluate_dynasty(_prospect_row())
        self.assertIn("baseline", [d.id for d in ra.drivers])

    def test_baseline_weights(self):
        d = next(d for d in self.model._dynasty_drivers(_mlb_row()) if d.id == "baseline")
        self.assertEqual(d.score_delta, 0.03)
        self.assertEqual(d.floor_drag, 3)
        self.assertEqual(d.ceiling_lift, 3)


class TestPitcherTypeDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_for_sp(self):
        drivers = self.model._dynasty_drivers(_mlb_row(positions=("SP",)))
        self.assertIn("pitcher_type", [d.id for d in drivers])

    def test_fires_for_rp(self):
        drivers = self.model._dynasty_drivers(_mlb_row(positions=("RP",)))
        self.assertIn("pitcher_type", [d.id for d in drivers])

    def test_skips_hitters(self):
        drivers = self.model._dynasty_drivers(_mlb_row(positions=("OF",)))
        self.assertNotIn("pitcher_type", [d.id for d in drivers])

    def test_correct_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_mlb_row(positions=("SP",)))
            if d.id == "pitcher_type"
        )
        self.assertEqual(d.score_delta, 0.05)
        self.assertEqual(d.floor_drag, 5)
        self.assertEqual(d.ceiling_lift, 3)


class TestPitcherProspectDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_requires_both_pitcher_and_prospect(self):
        drivers = self.model._dynasty_drivers(_prospect_row(positions=("SP",)))
        ids = [d.id for d in drivers]
        self.assertIn("pitcher_prospect", ids)
        self.assertIn("pitcher_type", ids)

    def test_skips_for_pitcher_mlb(self):
        drivers = self.model._dynasty_drivers(_mlb_row(positions=("SP",)))
        self.assertNotIn("pitcher_prospect", [d.id for d in drivers])

    def test_skips_for_position_prospect(self):
        drivers = self.model._dynasty_drivers(_prospect_row(positions=("SS",)))
        self.assertNotIn("pitcher_prospect", [d.id for d in drivers])

    def test_correct_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row(positions=("SP",)))
            if d.id == "pitcher_prospect"
        )
        self.assertEqual(d.score_delta, 0.08)
        self.assertEqual(d.floor_drag, 8)
        self.assertEqual(d.ceiling_lift, 6)


class TestProspectStatusDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_for_prospect(self):
        drivers = self.model._dynasty_drivers(_prospect_row())
        self.assertIn("prospect_status", [d.id for d in drivers])

    def test_skips_for_mlb(self):
        drivers = self.model._dynasty_drivers(_mlb_row())
        self.assertNotIn("prospect_status", [d.id for d in drivers])

    def test_correct_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row())
            if d.id == "prospect_status"
        )
        self.assertEqual(d.score_delta, 0.10)
        self.assertEqual(d.floor_drag, 8)
        self.assertEqual(d.ceiling_lift, 10)


class TestEtaDrivers(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_distant_eta_fires_two_plus_years_out(self):
        drivers = self.model._dynasty_drivers(_prospect_row(eta=2028))
        self.assertIn("eta_distant", [d.id for d in drivers])

    def test_distant_eta_fires_exactly_two_out(self):
        drivers = self.model._dynasty_drivers(_prospect_row(eta=2028))
        self.assertIn("eta_distant", [d.id for d in drivers])

    def test_near_eta_fires_one_year_out(self):
        drivers = self.model._dynasty_drivers(_prospect_row(eta=2027))
        self.assertIn("eta_near", [d.id for d in drivers])

    def test_current_year_eta_skips_both(self):
        drivers = self.model._dynasty_drivers(_prospect_row(eta=2026))
        ids = [d.id for d in drivers]
        self.assertNotIn("eta_distant", ids)
        self.assertNotIn("eta_near", ids)

    def test_none_eta_skips(self):
        drivers = self.model._dynasty_drivers(_prospect_row(eta=None))
        ids = [d.id for d in drivers]
        self.assertNotIn("eta_distant", ids)
        self.assertNotIn("eta_near", ids)

    def test_distant_label_contains_eta_year(self):
        drivers = self.model._dynasty_drivers(_prospect_row(eta=2029))
        d = next(d for d in drivers if d.id == "eta_distant")
        self.assertIn("2029", d.label)

    def test_injected_year_respected(self):
        model = RiskModel(current_year=2030)
        drivers = model._dynasty_drivers(_prospect_row(eta=2031))
        self.assertIn("eta_near", [d.id for d in drivers])

    def test_skips_for_mlb(self):
        drivers = self.model._dynasty_drivers(_mlb_row(eta=2030))
        ids = [d.id for d in drivers]
        self.assertNotIn("eta_distant", ids)
        self.assertNotIn("eta_near", ids)

    def test_distant_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row(eta=2028))
            if d.id == "eta_distant"
        )
        self.assertEqual(d.score_delta, 0.12)
        self.assertEqual(d.floor_drag, 8)
        self.assertEqual(d.ceiling_lift, 5)

    def test_near_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row(eta=2027))
            if d.id == "eta_near"
        )
        self.assertEqual(d.score_delta, 0.04)
        self.assertEqual(d.floor_drag, 3)
        self.assertEqual(d.ceiling_lift, 3)


class TestLevelDrivers(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_low_minors_A(self):
        drivers = self.model._dynasty_drivers(_prospect_row(level="A"))
        self.assertIn("low_minors", [d.id for d in drivers])

    def test_low_minors_Aplus(self):
        drivers = self.model._dynasty_drivers(_prospect_row(level="A+"))
        self.assertIn("low_minors", [d.id for d in drivers])

    def test_low_minors_CPX(self):
        drivers = self.model._dynasty_drivers(_prospect_row(level="CPX"))
        self.assertIn("low_minors", [d.id for d in drivers])

    def test_low_minors_R(self):
        drivers = self.model._dynasty_drivers(_prospect_row(level="R"))
        self.assertIn("low_minors", [d.id for d in drivers])

    def test_mid_minors_AA(self):
        drivers = self.model._dynasty_drivers(_prospect_row(level="AA"))
        self.assertIn("mid_minors", [d.id for d in drivers])

    def test_high_minors_AAA(self):
        drivers = self.model._dynasty_drivers(_prospect_row(level="AAA"))
        self.assertIn("high_minors", [d.id for d in drivers])

    def test_none_level_skips(self):
        drivers = self.model._dynasty_drivers(_prospect_row(level=None))
        ids = [d.id for d in drivers]
        self.assertNotIn("low_minors", ids)
        self.assertNotIn("mid_minors", ids)
        self.assertNotIn("high_minors", ids)

    def test_mlb_skips_all_level_drivers(self):
        drivers = self.model._dynasty_drivers(_mlb_row(level="AA"))
        ids = [d.id for d in drivers]
        self.assertNotIn("low_minors", ids)
        self.assertNotIn("mid_minors", ids)
        self.assertNotIn("high_minors", ids)

    def test_low_minors_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row(level="A"))
            if d.id == "low_minors"
        )
        self.assertEqual(d.score_delta, 0.12)
        self.assertEqual(d.floor_drag, 10)
        self.assertEqual(d.ceiling_lift, 8)


class TestSourceSpreadDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_above_threshold(self):
        # pipeline rank 1/100=0.01, hkb rank 500/719≈0.695 → spread ≈ 0.685 > 0.30
        ranks = {"pipeline": 1, "hkb": 500}
        drivers = self.model._dynasty_drivers(_prospect_row(source_ranks=ranks))
        self.assertIn("source_spread", [d.id for d in drivers])

    def test_skips_below_threshold(self):
        # pipeline 50/100=0.50, hkb 359/719≈0.499 → spread ≈ 0.001 < 0.30
        ranks = {"pipeline": 50, "hkb": 359}
        drivers = self.model._dynasty_drivers(_prospect_row(source_ranks=ranks))
        self.assertNotIn("source_spread", [d.id for d in drivers])

    def test_filters_non_numeric_ranks(self):
        # Only one numeric rank → cannot compute spread
        ranks = {"pipeline": "N/A", "hkb": 100}
        drivers = self.model._dynasty_drivers(_prospect_row(source_ranks=ranks))
        self.assertNotIn("source_spread", [d.id for d in drivers])

    def test_requires_at_least_two_normalized(self):
        # Only one source with a known max
        ranks = {"pipeline": 50}
        drivers = self.model._dynasty_drivers(_prospect_row(source_ranks=ranks))
        self.assertNotIn("source_spread", [d.id for d in drivers])

    def test_none_source_ranks_skips(self):
        drivers = self.model._dynasty_drivers(_prospect_row(source_ranks=None))
        self.assertNotIn("source_spread", [d.id for d in drivers])

    def test_mlb_skips(self):
        ranks = {"pipeline": 1, "hkb": 500}
        drivers = self.model._dynasty_drivers(_mlb_row(source_ranks=ranks))
        self.assertNotIn("source_spread", [d.id for d in drivers])

    def test_correct_weights(self):
        ranks = {"pipeline": 1, "hkb": 500}
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row(source_ranks=ranks))
            if d.id == "source_spread"
        )
        self.assertEqual(d.score_delta, 0.08)
        self.assertEqual(d.floor_drag, 7)
        self.assertEqual(d.ceiling_lift, 4)

    def test_unknown_source_skipped_in_normalization(self):
        # "mystery_source" not in SOURCE_RANK_MAXES → only 1 valid normalized value
        ranks = {"pipeline": 50, "mystery_source": 9999}
        drivers = self.model._dynasty_drivers(_prospect_row(source_ranks=ranks))
        self.assertNotIn("source_spread", [d.id for d in drivers])


class TestAgeYoungDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_for_young_prospect(self):
        drivers = self.model._dynasty_drivers(_prospect_row(age=19))
        self.assertIn("age_young", [d.id for d in drivers])

    def test_boundary_21(self):
        drivers = self.model._dynasty_drivers(_prospect_row(age=21))
        self.assertIn("age_young", [d.id for d in drivers])

    def test_skips_age_22(self):
        drivers = self.model._dynasty_drivers(_prospect_row(age=22))
        self.assertNotIn("age_young", [d.id for d in drivers])

    def test_skips_for_mlb(self):
        drivers = self.model._dynasty_drivers(_mlb_row(age=19))
        self.assertNotIn("age_young", [d.id for d in drivers])

    def test_label_contains_age(self):
        drivers = self.model._dynasty_drivers(_prospect_row(age=18))
        d = next(d for d in drivers if d.id == "age_young")
        self.assertIn("18", d.label)

    def test_correct_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row(age=20))
            if d.id == "age_young"
        )
        self.assertEqual(d.score_delta, 0.06)
        self.assertEqual(d.floor_drag, 5)
        self.assertEqual(d.ceiling_lift, 6)


class TestAgeDeclineDrivers(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_at_33(self):
        drivers = self.model._dynasty_drivers(_mlb_row(age=33))
        self.assertIn("age_decline", [d.id for d in drivers])

    def test_skips_at_32(self):
        drivers = self.model._dynasty_drivers(_mlb_row(age=32))
        self.assertNotIn("age_decline", [d.id for d in drivers])

    def test_deep_decline_stacks_at_36(self):
        drivers = self.model._dynasty_drivers(_mlb_row(age=36))
        ids = [d.id for d in drivers]
        self.assertIn("age_decline", ids)
        self.assertIn("age_deep_decline", ids)

    def test_deep_decline_stacks_at_37(self):
        drivers = self.model._dynasty_drivers(_mlb_row(age=37))
        ids = [d.id for d in drivers]
        self.assertIn("age_decline", ids)
        self.assertIn("age_deep_decline", ids)

    def test_decline_label_contains_age(self):
        drivers = self.model._dynasty_drivers(_mlb_row(age=35))
        d = next(d for d in drivers if d.id == "age_decline")
        self.assertIn("35", d.label)

    def test_none_age_skips(self):
        drivers = self.model._dynasty_drivers(_mlb_row(age=None))
        ids = [d.id for d in drivers]
        self.assertNotIn("age_decline", ids)
        self.assertNotIn("age_deep_decline", ids)

    def test_decline_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_mlb_row(age=33))
            if d.id == "age_decline"
        )
        self.assertEqual(d.score_delta, 0.10)
        self.assertEqual(d.floor_drag, 8)
        self.assertEqual(d.ceiling_lift, 1)

    def test_deep_decline_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_mlb_row(age=36))
            if d.id == "age_deep_decline"
        )
        self.assertEqual(d.score_delta, 0.06)
        self.assertEqual(d.floor_drag, 5)
        self.assertEqual(d.ceiling_lift, 0)

    def test_fires_for_prospect_too(self):
        drivers = self.model._dynasty_drivers(_prospect_row(age=33))
        self.assertIn("age_decline", [d.id for d in drivers])


class TestIncompleteProfileDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_when_single_source(self):
        # One scouting source = genuinely thin coverage.
        drivers = self.model._dynasty_drivers(
            _prospect_row(eta=2028, level="AA", source_ranks={"pipeline": 50})
        )
        self.assertIn("incomplete_profile", [d.id for d in drivers])

    def test_fires_when_source_ranks_missing(self):
        drivers = self.model._dynasty_drivers(
            _prospect_row(eta=2028, level="AA", source_ranks=None)
        )
        self.assertIn("incomplete_profile", [d.id for d in drivers])

    def test_fires_when_source_ranks_empty_dict(self):
        drivers = self.model._dynasty_drivers(
            _prospect_row(eta=2028, level="AA", source_ranks={})
        )
        self.assertIn("incomplete_profile", [d.id for d in drivers])

    def test_does_not_fire_on_null_level_when_well_scouted(self):
        # Regression: a consensus prospect with 3 sources but a null `level`
        # field must NOT be tagged "incomplete scouting profile". `level` is
        # chronically null in the feed and is not a scouting signal.
        drivers = self.model._dynasty_drivers(
            _prospect_row(eta=2026, level=None,
                          source_ranks={"pipeline": 9, "cfr": 168, "hkb": 3})
        )
        self.assertNotIn("incomplete_profile", [d.id for d in drivers])

    def test_does_not_fire_on_null_eta_when_two_sources(self):
        # A null ETA alone no longer triggers the scouting-completeness flag.
        drivers = self.model._dynasty_drivers(
            _prospect_row(eta=None, level=None,
                          source_ranks={"pipeline": 30, "hkb": 45})
        )
        self.assertNotIn("incomplete_profile", [d.id for d in drivers])

    def test_skips_when_two_sources(self):
        drivers = self.model._dynasty_drivers(
            _prospect_row(source_ranks={"pipeline": 30, "hkb": 45})
        )
        self.assertNotIn("incomplete_profile", [d.id for d in drivers])

    def test_skips_for_mlb(self):
        drivers = self.model._dynasty_drivers(
            _mlb_row(eta=None, level=None, source_ranks=None)
        )
        self.assertNotIn("incomplete_profile", [d.id for d in drivers])

    def test_correct_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(
                _prospect_row(source_ranks={"pipeline": 50}))
            if d.id == "incomplete_profile"
        )
        self.assertEqual(d.score_delta, 0.05)
        self.assertEqual(d.floor_drag, 5)
        self.assertEqual(d.ceiling_lift, 3)


class TestBreakoutHeliumDriver(unittest.TestCase):

    def setUp(self):
        self.model = RiskModel(current_year=2026)

    def test_fires_for_breakout(self):
        drivers = self.model._dynasty_drivers(_prospect_row(breakout_label="breakout"))
        self.assertIn("breakout_helium", [d.id for d in drivers])

    def test_fires_for_major_breakout(self):
        drivers = self.model._dynasty_drivers(_prospect_row(breakout_label="major_breakout"))
        self.assertIn("breakout_helium", [d.id for d in drivers])

    def test_fires_for_rising(self):
        drivers = self.model._dynasty_drivers(_prospect_row(breakout_label="rising"))
        self.assertIn("breakout_helium", [d.id for d in drivers])

    def test_case_insensitive(self):
        drivers = self.model._dynasty_drivers(_prospect_row(breakout_label="BREAKOUT"))
        self.assertIn("breakout_helium", [d.id for d in drivers])

    def test_skips_negative_label(self):
        drivers = self.model._dynasty_drivers(_prospect_row(breakout_label="declining"))
        self.assertNotIn("breakout_helium", [d.id for d in drivers])

    def test_skips_none(self):
        drivers = self.model._dynasty_drivers(_prospect_row(breakout_label=None))
        self.assertNotIn("breakout_helium", [d.id for d in drivers])

    def test_mlb_with_breakout_fires(self):
        # Breakout fires for any player type, not just prospects
        drivers = self.model._dynasty_drivers(_mlb_row(breakout_label="rising"))
        self.assertIn("breakout_helium", [d.id for d in drivers])

    def test_correct_weights(self):
        d = next(
            d for d in self.model._dynasty_drivers(_prospect_row(breakout_label="breakout"))
            if d.id == "breakout_helium"
        )
        self.assertEqual(d.score_delta, 0.05)
        self.assertEqual(d.floor_drag, 3)
        self.assertEqual(d.ceiling_lift, 8)


class TestArchetypes(unittest.TestCase):
    """Full player profiles matching real dynasty archetypes."""

    def _model(self):
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
        self.assertEqual(assessment.value_high, 150.0)

    def test_prospect_pitcher_mid(self):
        """Trey Yesavage type — 23yo SP prospect, AA, ETA 2028."""
        model = self._model()
        row = _prospect_row(
            age=23, positions=("SP",), dynasty_value=98.2,
            eta=2028, level="AA",
            source_ranks={"pipeline": 9, "hkb": 3},
        )
        assessment = model.evaluate_dynasty(row)
        self.assertIn(assessment.risk_level, ("Moderate", "High"))
        self.assertLess(assessment.value_low, 65.0)
        self.assertGreater(assessment.value_high, 120.0)

    def test_prospect_complex_young(self):
        """17yo A-ball hitter prospect. Many drivers stack -> Moderate (0.48).
        With a pitcher position, would be High due to pitcher_type + pitcher_prospect."""
        model = self._model()
        row = _prospect_row(
            age=17, positions=("SS",), dynasty_value=5.2,
            eta=2030, level="A",
            source_ranks=None,
        )
        assessment = model.evaluate_dynasty(row)
        self.assertIn(assessment.risk_level, ("Moderate", "High"))
        self.assertEqual(assessment.value_low, 0.0)

    def test_mlb_aging_decline(self):
        """37yo veteran hitter. Baseline + decline + deep_decline."""
        model = self._model()
        row = _mlb_row(age=37, positions=("1B",), dynasty_value=60.0)
        assessment = model.evaluate_dynasty(row)
        self.assertEqual(assessment.risk_level, "Low")
        self.assertAlmostEqual(assessment.value_low, 44.0, places=1)
        self.assertAlmostEqual(assessment.value_high, 64.0, places=1)

    def test_evaluate_dynasty_with_explicit_value(self):
        """Passing value kwarg overrides row.dynasty_value."""
        model = self._model()
        row = _mlb_row(dynasty_value=100.0)
        a1 = model.evaluate_dynasty(row)
        a2 = model.evaluate_dynasty(row, value=50.0)
        self.assertAlmostEqual(a1.value_low, 97.0, places=1)
        self.assertAlmostEqual(a2.value_low, 47.0, places=1)

    def test_risk_assessments_keyed_by_row_id(self):
        """Simulate app-level mapping pattern."""
        model = self._model()
        rows = [
            _mlb_row(dynasty_value=100.0),
            _prospect_row(dynasty_value=50.0),
        ]
        rows[0].id = "mlb_judge"
        rows[1].id = "prospect_kid"
        risk_assessments = {row.id: model.evaluate_dynasty(row) for row in rows}
        self.assertIn("mlb_judge", risk_assessments)
        self.assertIn("prospect_kid", risk_assessments)
        self.assertEqual(risk_assessments["mlb_judge"].risk_level, "Low")


if __name__ == "__main__":
    unittest.main()
