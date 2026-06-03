import unittest
from projections.constants import (
    PITCHER_COUNTING, PITCHER_SKILL_RATES, PITCHER_HEADLINE_SKILL,
    PITCHER_HEADLINE_CONTEXT, MIN_SP_IP_EVAL, MIN_RP_IP_EVAL,
)
from projections.models.pitcher_params import PitcherMarcelParams


class TestPitcherConstantsAndParams(unittest.TestCase):
    def test_skill_rates_subset_of_counting(self):
        self.assertTrue(set(PITCHER_SKILL_RATES).issubset(set(PITCHER_COUNTING)))

    def test_headline_split(self):
        self.assertIn("ERA", PITCHER_HEADLINE_SKILL)
        self.assertIn("SV", PITCHER_HEADLINE_CONTEXT)   # usage/context cat
        self.assertNotIn("SV", PITCHER_HEADLINE_SKILL)

    def test_eval_floors(self):
        self.assertEqual((MIN_SP_IP_EVAL, MIN_RP_IP_EVAL), (60, 20))

    def test_params_have_no_hitter_leak(self):
        p = PitcherMarcelParams()
        self.assertEqual(p.season_weights, (5.0, 4.0, 3.0))
        self.assertEqual(p.n_reg, 300.0)
        for leaked in ("k_young", "k_old", "alpha_contact", "alpha_power", "gamma"):
            self.assertFalse(hasattr(p, leaked), f"{leaked} leaked into pitcher params")
