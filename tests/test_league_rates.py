import unittest
from projections.models.league_rates import compute_league_rates


class TestLeagueRates(unittest.TestCase):
    def test_weighted_per_pa_rate(self):
        # Two prior seasons, weights 5 then 4. One season-snapshot is a list of
        # player rows. Player below the PA floor is excluded.
        snap_t1 = [
            {"PA": 100, "HR": 10, "BB": 10, "1B": 20, "2B": 0, "3B": 0,
             "HBP": 0, "SF": 0, "SO": 0, "SB": 0, "CS": 0, "R": 0, "RBI": 0},
            {"PA": 5, "HR": 5, "BB": 0, "1B": 0, "2B": 0, "3B": 0,
             "HBP": 0, "SF": 0, "SO": 0, "SB": 0, "CS": 0, "R": 0, "RBI": 0},
        ]
        snap_t2 = [
            {"PA": 100, "HR": 0, "BB": 20, "1B": 20, "2B": 0, "3B": 0,
             "HBP": 0, "SF": 0, "SO": 0, "SB": 0, "CS": 0, "R": 0, "RBI": 0},
        ]
        rates = compute_league_rates(
            [snap_t1, snap_t2], weights=(5.0, 4.0), pa_floor=10,
        )
        # HR: weighted total = 5*10 + 4*0 = 50 ; weighted PA = 5*100 + 4*100 = 900
        self.assertAlmostEqual(rates["HR"], 50 / 900)
        # BB: weighted total = 5*10 + 4*20 = 130 ; / 900
        self.assertAlmostEqual(rates["BB"], 130 / 900)
