import unittest
from projections.models.marcel_pitcher import (
    compute_pitcher_league_rates, compute_role_factors, project_pitcher_rates,
    project_sp_usage, project_rp_usage,
)
from projections.models.pitcher_params import PitcherMarcelParams


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


class TestPitcherRateProjection(unittest.TestCase):
    def test_no_role_change_no_shift(self):
        # Career SP (h_sp=1) projected as SP (p_sp=1): exponent 0 -> no role-shift.
        prior = [{"BF": 800, "K": 200, "BB": 50, "H_ALLOWED": 160, "HR": 22,
                  "ER": 70, "HBP": 6, "GS": 30, "G": 30}]
        league = {c: prior[0][c] / 800 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {c: 1.5 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}  # would matter if shifted
        rates = project_pitcher_rates(prior, league, f, h_sp=1.0, p_sp=1.0,
                                      params=PitcherMarcelParams())
        self.assertAlmostEqual(rates["K"], 0.25, places=6)   # 200/800, no shift

    def test_rp_to_sp_removes_reliever_boost(self):
        # Career RP (h_sp=0) projected as SP (p_sp=1): K rate divided by f (>1).
        prior = [{"BF": 300, "K": 105, "BB": 20, "H_ALLOWED": 50, "HR": 8,
                  "ER": 25, "HBP": 3, "GS": 0, "G": 60}]
        league = {c: prior[0][c] / 300 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {"K": 1.2, "BB": 1.0, "H_ALLOWED": 1.0, "HR": 1.0, "ER": 1.0, "HBP": 1.0}
        rates = project_pitcher_rates(prior, league, f, h_sp=0.0, p_sp=1.0,
                                      params=PitcherMarcelParams())
        # pooled K/BF = 105/300 = 0.35 ; shift f^(0-1)=1/1.2 -> 0.35/1.2
        self.assertAlmostEqual(rates["K"], 0.35 / 1.2, places=5)

    def test_missed_t1_present_t2_offset_preserved(self):
        # index0=T-1 (None, missed), index1=T-2 present. Must not crash; uses T-2.
        season = {"BF": 300, "K": 105, "BB": 20, "H_ALLOWED": 50, "HR": 8,
                  "ER": 25, "HBP": 3, "GS": 0, "G": 60}
        league = {c: 0.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        f = {c: 1.0 for c in ("K","BB","H_ALLOWED","HR","ER","HBP")}
        rates = project_pitcher_rates([None, season], league, f, h_sp=0.0, p_sp=0.0,
                                      params=PitcherMarcelParams(n_reg=0.0))
        # n_reg=0 isolates the rate: 105/300 = 0.35, present season used despite None at T-1.
        self.assertAlmostEqual(rates["K"], 0.35, places=6)


class TestPitcherUsage(unittest.TestCase):
    def test_sp_usage_volume_and_qs(self):
        prior = [{"GS": 30, "G": 30, "BF": 750, "IP": 180.0, "QS": 18} for _ in range(3)]
        u = project_sp_usage(prior, (5.0, 4.0, 3.0))
        self.assertAlmostEqual(u["GS"], 30.0, places=4)
        self.assertAlmostEqual(u["BF"], 750.0, places=2)     # GS * BF/start
        self.assertAlmostEqual(u["IP"], 180.0, places=2)
        self.assertAlmostEqual(u["QS"], 18.0, places=2)

    def test_rp_usage_volume_sv_hld(self):
        prior = [{"G": 60, "GS": 0, "BF": 240, "IP": 60.0, "SV": 30, "HLD": 5} for _ in range(3)]
        u = project_rp_usage(prior, (5.0, 4.0, 3.0))
        self.assertAlmostEqual(u["G"], 60.0, places=4)
        self.assertAlmostEqual(u["BF"], 240.0, places=2)
        self.assertAlmostEqual(u["SV"], 30.0, places=2)
        self.assertAlmostEqual(u["HLD"], 5.0, places=2)
