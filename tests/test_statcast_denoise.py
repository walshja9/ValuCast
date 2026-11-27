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


from projections.models.statcast_denoise import denoise_components, denoise_season


class TestDenoiseComponents(unittest.TestCase):
    def setUp(self):
        # 1B=100,2B=20,3B=2,HR=18,AB=500 -> H=140, TB=218, XB=40, m=2.95.
        self.row = {"1B": 100, "2B": 20, "3B": 2, "HR": 18, "AB": 500,
                    "PA": 560, "BB": 50, "SO": 100}

    def test_alpha_zero_is_passthrough(self):
        out = denoise_components(self.row, {"xba": 0.30, "xslg": 0.52},
                                 alpha_contact=0.0, alpha_power=0.0, league_mix=None)
        self.assertEqual(out["1B"], 100)
        self.assertEqual(out["HR"], 18)

    def test_missing_statcast_is_passthrough(self):
        out = denoise_components(self.row, None, 0.5, 0.5, None)
        self.assertEqual(out["HR"], 18)

    def test_hand_computed_redistribution(self):
        # xba=.30, xslg=.52, alpha=.5 each. Hand math:
        # H* = 500*(.5*.28 + .5*.30) = 145 ; TB* = 500*(.5*.436 + .5*.52) = 239
        # XB' = (239-145)/(2.95-1) = 48.205 ; 1B' = 96.795 ; HR' = 48.205*.45 = 21.692
        out = denoise_components(self.row, {"xba": 0.30, "xslg": 0.52}, 0.5, 0.5, None)
        h = out["1B"] + out["2B"] + out["3B"] + out["HR"]
        tb = out["1B"] + 2 * out["2B"] + 3 * out["3B"] + 4 * out["HR"]
        self.assertAlmostEqual(h, 145.0, places=2)
        self.assertAlmostEqual(tb, 239.0, places=2)
        self.assertAlmostEqual(out["1B"], 96.795, places=2)
        self.assertAlmostEqual(out["HR"], 21.692, places=2)
        self.assertEqual(out["AB"], 500)        # AB is a playing-time fact: untouched
        self.assertEqual(out["BB"], 50)         # non-hit components untouched

    def test_hits_clamped_to_ab(self):
        # Impossible xba=2.0 with full weight -> H* clamped to AB.
        out = denoise_components({"1B": 100, "2B": 0, "3B": 0, "HR": 0, "AB": 300},
                                 {"xba": 2.0, "xslg": 2.0}, 1.0, 0.0, ((0.5, 0.0, 0.5), 3.0))
        h = out["1B"] + out["2B"] + out["3B"] + out["HR"]
        self.assertLessEqual(h, 300.0)

    def test_xb_clamp_prioritizes_coherence_over_xslg(self):
        # Huge xslg forces XB' > H* -> clamp to H*, all hits become XB, 1B'=0,
        # realized TB < TB* (coherence kept).
        out = denoise_components(self.row, {"xba": 0.28, "xslg": 1.50}, 0.0, 1.0, None)
        self.assertAlmostEqual(out["1B"], 0.0, places=6)
        h = out["1B"] + out["2B"] + out["3B"] + out["HR"]
        self.assertAlmostEqual(h, 140.0, places=2)   # H unchanged (alpha_contact=0)

    def test_zero_xbh_uses_league_mix_not_hr_lock(self):
        # Player with only singles + high xslg: league mix gives them HR > 0.
        row = {"1B": 120, "2B": 0, "3B": 0, "HR": 0, "AB": 500}
        out = denoise_components(row, {"xba": 0.24, "xslg": 0.45},
                                 0.0, 1.0, ((0.5, 0.05, 0.45), 2.9))
        self.assertGreater(out["HR"], 0.0)

    def test_zero_xbh_no_league_mix_falls_back_classic_power(self):
        row = {"1B": 120, "2B": 0, "3B": 0, "HR": 0, "AB": 500}
        out = denoise_components(row, {"xba": 0.24, "xslg": 0.45}, 0.0, 1.0, None)
        self.assertEqual(out["HR"], 0.0)   # no league mix -> no invented power


class TestDenoiseSeason(unittest.TestCase):
    def test_season_passthrough_at_alpha_zero(self):
        rows = [{"1B": 100, "2B": 20, "3B": 2, "HR": 18, "AB": 500}]
        sc = {"0": {"xba": 0.30, "xslg": 0.52}}
        out = denoise_season(rows, sc, 0.0, 0.0)
        self.assertEqual(out[0]["HR"], 18)

    def test_season_denoises_matched_players(self):
        rows = [{"mlbam_id": "5", "1B": 100, "2B": 20, "3B": 2, "HR": 18, "AB": 500}]
        sc = {"5": {"xba": 0.30, "xslg": 0.52}}
        out = denoise_season(rows, sc, 0.5, 0.5)
        self.assertNotAlmostEqual(out[0]["HR"], 18)   # moved
