import unittest
from projections.models.statcast_denoise import league_xbh_mix


class TestLeagueXbhMix(unittest.TestCase):
    def test_mix_proportions_and_m(self):
        # League totals: 2B=200, 3B=20, HR=180 -> XB=400.
        rows = [{"2B": 200, "3B": 20, "HR": 180}]
        props, m = league_xbh_mix(rows)
        self.assertAlmostEqual(props[0], 200 / 400)   # 2B share
        self.assertAlmostEqual(props[2], 180 / 400)   # HR share
        # m = (2*200 + 3*20 + 4*180) / 400 = (400+60+720)/400 = 1180/400 = 2.95
        self.assertAlmostEqual(m, 2.95)

    def test_no_xbh_returns_none(self):
        self.assertIsNone(league_xbh_mix([{"2B": 0, "3B": 0, "HR": 0}]))
