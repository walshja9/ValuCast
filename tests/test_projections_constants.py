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
