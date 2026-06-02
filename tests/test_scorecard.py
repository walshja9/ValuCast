import unittest
from projections.backtest.scorecard import mae, rmse, correlation, normalized_ratio


class TestScorecard(unittest.TestCase):
    def test_mae_rmse(self):
        self.assertAlmostEqual(mae([1, 2, 3], [1, 2, 5]), 2 / 3)
        self.assertAlmostEqual(rmse([1, 2, 3], [1, 2, 5]), (4 / 3) ** 0.5)

    def test_correlation_perfect(self):
        self.assertAlmostEqual(correlation([1, 2, 3], [2, 4, 6]), 1.0)

    def test_correlation_degenerate_returns_zero(self):
        self.assertEqual(correlation([5, 5, 5], [1, 2, 3]), 0.0)

    def test_normalized_ratio(self):
        # marcel mae 1.0 vs persistence mae 2.0 -> 0.5 (good, <1)
        self.assertAlmostEqual(normalized_ratio(1.0, 2.0), 0.5)
        self.assertEqual(normalized_ratio(1.0, 0.0), float("inf"))
