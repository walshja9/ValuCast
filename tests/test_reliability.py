import unittest
from projections.models.reliability import compute_reliability, R_FLOOR


def _row(pid, pa, hr, so):
    # Other components constant/zero so only HR and SO matter here.
    return {"mlbam_id": pid, "PA": pa, "HR": hr, "SO": so,
            "1B": 0, "2B": 0, "3B": 0, "BB": 0, "HBP": 0, "SF": 0,
            "SB": 0, "CS": 0, "R": 0, "RBI": 0}


class TestReliability(unittest.TestCase):
    def test_perfectly_correlated_component_is_high(self):
        # HR rate identical across the two seasons for all 3 players -> r = 1.0.
        s2020 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        s2021 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        rel = compute_reliability({2020: s2020, 2021: s2021}, pa_floor=100)
        self.assertAlmostEqual(rel["HR"], 1.0)

    def test_constant_component_floors(self):
        # SO rate is .2 for everyone both years -> zero variance -> r clamped to R_FLOOR.
        s2020 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        s2021 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100), _row("3", 500, 30, 100)]
        rel = compute_reliability({2020: s2020, 2021: s2021}, pa_floor=100)
        self.assertEqual(rel["SO"], R_FLOOR)

    def test_below_floor_pairs_excluded(self):
        # Player 2 below PA floor in 2021 -> only player 1 pairs; <2 points -> floored.
        s2020 = [_row("1", 500, 10, 100), _row("2", 500, 20, 100)]
        s2021 = [_row("1", 500, 10, 100), _row("2", 50, 2, 10)]
        rel = compute_reliability({2020: s2020, 2021: s2021}, pa_floor=100)
        self.assertEqual(rel["HR"], R_FLOOR)
