import unittest
from projections.models.pitcher_role import (
    role_share, project_p_sp, is_mixed, historical_role_mix,
)


class TestPitcherRole(unittest.TestCase):
    def test_role_share(self):
        self.assertEqual(role_share({"GS": 30, "G": 30}), 1.0)   # pure SP
        self.assertEqual(role_share({"GS": 0, "G": 60}), 0.0)    # pure RP
        self.assertEqual(role_share({"GS": 0, "G": 0}), 0.0)     # no appearances

    def test_project_p_sp_weighted(self):
        # newest-first; weights 5/4/3. T-1 pure SP, T-2 pure RP.
        prior = [{"GS": 30, "G": 30}, {"GS": 0, "G": 60}]
        # (5*1 + 4*0) / (5+4) = 0.5556
        self.assertAlmostEqual(project_p_sp(prior, (5.0, 4.0, 3.0)), 5/9, places=4)

    def test_is_mixed_band(self):
        self.assertTrue(is_mixed(0.5))
        self.assertFalse(is_mixed(0.95))
        self.assertFalse(is_mixed(0.05))

    def test_historical_role_mix_bf_weighted(self):
        prior = [{"GS": 30, "G": 30, "BF": 800}, {"GS": 0, "G": 60, "BF": 200}]
        # (800*1 + 200*0) / 1000 = 0.8
        self.assertAlmostEqual(historical_role_mix(prior), 0.8, places=4)
