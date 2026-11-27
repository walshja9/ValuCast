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

    def test_historical_role_mix_season_and_bf_weighted(self):
        # T-1 SP (w5, BF800), T-2 RP (w4, BF200).
        prior = [{"GS": 30, "G": 30, "BF": 800}, {"GS": 0, "G": 60, "BF": 200}]
        # (5*800*1 + 4*200*0) / (5*800 + 4*200) = 4000/4800 = 0.8333
        self.assertAlmostEqual(historical_role_mix(prior, (5.0, 4.0, 3.0)), 4000/4800, places=4)

    def test_weighted_h_sp_differs_from_unweighted_for_converter(self):
        # Recent RP (T-1, w5, BF200, role 0), older SP (T-3, w3, BF800, role 1); T-2 missing.
        prior = [{"GS": 0, "G": 60, "BF": 200}, None, {"GS": 30, "G": 30, "BF": 800}]
        weighted = historical_role_mix(prior, (5.0, 4.0, 3.0))
        # weighted: (5*200*0 + 3*800*1)/(5*200 + 3*800) = 2400/3400 = 0.7059
        self.assertAlmostEqual(weighted, 2400/3400, places=4)
        # plain BF-only would be 800/1000 = 0.8 -> they MUST differ (the bug we fixed).
        self.assertNotAlmostEqual(weighted, 0.8, places=3)
