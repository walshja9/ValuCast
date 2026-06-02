import unittest
from projections.models.marcel_hitter import project_hitter
from projections.models.marcel_params import MarcelParams


class TestMarcelHitter(unittest.TestCase):
    def setUp(self):
        # One prior season, PA=500.
        self.prior = [{
            "PA": 500, "AB": 450, "H": 125, "1B": 100, "2B": 0, "3B": 0,
            "HR": 25, "R": 80, "RBI": 70, "SB": 0, "CS": 0,
            "BB": 50, "SO": 100, "HBP": 0, "SF": 0,
        }]
        # League rates == player's per-PA rates -> regression leaves rates intact.
        self.league = {
            "1B": 100 / 500, "2B": 0.0, "3B": 0.0, "HR": 25 / 500,
            "BB": 50 / 500, "HBP": 0.0, "SF": 0.0, "SO": 100 / 500,
            "SB": 0.0, "CS": 0.0, "R": 80 / 500, "RBI": 70 / 500,
        }

    def test_pa_projection_and_composition(self):
        out = project_hitter(self.prior, self.league, age=29, params=MarcelParams())
        # PA_proj = 0.5*500 + 0.1*0 + 200 = 450
        self.assertAlmostEqual(out["PA"], 450.0)
        # HR = (25/500) * 450 = 22.5  (age_mult = 1.0)
        self.assertAlmostEqual(out["HR"], 22.5)
        # BB = (50/500)*450 = 45 ; AB = 450 - 45 - 0 - 0 = 405
        self.assertAlmostEqual(out["AB"], 405.0)
        # 1B = 90 ; H = 90 + 0 + 0 + 22.5 = 112.5
        self.assertAlmostEqual(out["H"], 112.5)
        # TB = 90 + 4*22.5 = 180 ; SLG = 180/405
        self.assertAlmostEqual(out["TB"], 180.0)
        self.assertAlmostEqual(out["SLG"], round(180 / 405, 3))
        # SO is NOT age-adjusted: (100/500)*450 = 90
        self.assertAlmostEqual(out["SO"], 90.0)

    def test_age_decline_only_touches_production(self):
        young = project_hitter(self.prior, self.league, age=29, params=MarcelParams())
        old = project_hitter(self.prior, self.league, age=39, params=MarcelParams())
        self.assertLess(old["HR"], young["HR"])      # production declines
        self.assertAlmostEqual(old["SO"], young["SO"])  # SO unchanged by age

    def test_counts_clamped_nonnegative(self):
        out = project_hitter(self.prior, self.league, age=120, params=MarcelParams())
        for key in ("HR", "1B", "BB", "AB", "H"):
            self.assertGreaterEqual(out[key], 0.0)

    def test_missing_t1_uses_t2_offset_weight_and_pa(self):
        # Offset-aligned: index 0 = T-1 (missing), index 1 = T-2 (present).
        out = project_hitter([None, self.prior[0]], self.league, age=29, params=MarcelParams())
        # T-2 carries its offset weight (4), not T-1's. PA_proj = 0.5*0 + 0.1*500 + 200 = 250.
        self.assertAlmostEqual(out["PA"], 250.0)
        # Regression is identity here, so HR = (25/500) * 250 = 12.5.
        self.assertAlmostEqual(out["HR"], 12.5)

    def test_gamma_zero_with_reliability_matches_classic(self):
        # Passing a reliability map but gamma=0 must equal the classic path exactly.
        rel = {c: 0.5 for c in self.league}
        classic = project_hitter(self.prior, self.league, age=29, params=MarcelParams())
        with_rel = project_hitter(self.prior, self.league, age=29,
                                  params=MarcelParams(gamma=0.0), reliability=rel)
        self.assertEqual(classic, with_rel)

    def test_reliability_differentiates_regression_when_gamma_positive(self):
        # Regression only bites when the league rate DIFFERS from the player's rate.
        # Player HR rate is .05; set league HR rate to .03 so shrinkage matters, then a
        # different n_reg (from reliability weighting) yields a different projection.
        league = dict(self.league)
        league["HR"] = 0.03
        rel = {c: 0.5 for c in league}
        rel["HR"], rel["BB"] = 0.9, 0.1   # HR reliable (less shrink), BB noisy (more)
        classic = project_hitter(self.prior, league, age=29, params=MarcelParams())
        tuned = project_hitter(self.prior, league, age=29,
                               params=MarcelParams(gamma=1.0), reliability=rel)
        # Reliable HR regresses less toward .03 -> stays closer to the player's .05.
        self.assertNotAlmostEqual(classic["HR"], tuned["HR"])
        self.assertGreater(tuned["HR"], classic["HR"])
