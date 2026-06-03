import unittest
from projections.models.marcel_pitcher import compute_pitcher_league_rates, compute_role_factors


def _p(bf, k, gs, g):
    return {"BF": bf, "K": k, "BB": 0, "H_ALLOWED": 0, "HR": 0, "ER": 0, "HBP": 0,
            "GS": gs, "G": g}


class TestPitcherLeagueRates(unittest.TestCase):
    def test_league_rate_per_bf(self):
        snap = [_p(800, 200, 30, 30), _p(200, 60, 0, 60)]
        rates = compute_pitcher_league_rates([snap], weights=(5.0,), bf_floor=100)
        # K/BF = (200+60)/(800+200) = 260/1000 = 0.26
        self.assertAlmostEqual(rates["K"], 0.26)

    def test_role_factor_rp_over_sp(self):
        # SP-context K/BF = 200/800 = 0.25 ; RP-context K/BF = 60/200 = 0.30
        # f[K] = RP/SP = 0.30/0.25 = 1.2
        snap = [_p(800, 200, 30, 30), _p(200, 60, 0, 60)]
        f = compute_role_factors([snap], bf_floor=100)
        self.assertAlmostEqual(f["K"], 1.2, places=4)

    def test_role_factor_zero_rate_neutralizes(self):
        # SP has HR, RP has zero HR -> naive f[HR]=0 -> f^(negative) blows up. Must be 1.0.
        import math
        snap = [{"BF": 800, "K": 200, "HR": 20, "BB": 0, "H_ALLOWED": 0, "ER": 0, "HBP": 0,
                 "GS": 30, "G": 30},
                {"BF": 200, "K": 60, "HR": 0, "BB": 0, "H_ALLOWED": 0, "ER": 0, "HBP": 0,
                 "GS": 0, "G": 60}]
        f = compute_role_factors([snap], bf_floor=100)
        self.assertEqual(f["HR"], 1.0)
        self.assertTrue(math.isfinite(f["HR"] ** (0.0 - 1.0)))   # f^(neg) finite
