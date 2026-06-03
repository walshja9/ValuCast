import unittest
from projections.backtest.grid_faithfulness import correlation, calibration


class TestFaithfulnessMetrics(unittest.TestCase):
    def test_correlation_perfect(self):
        self.assertAlmostEqual(correlation([0.2, 0.3, 0.4], [0.2, 0.3, 0.4]), 1.0)

    def test_calibration_detects_affine_bias(self):
        # ours = 0.5*savant + 0.1  -> corr is perfect but slope .5 / intercept .1 / +bias.
        savant = [0.20, 0.30, 0.40]
        ours = [0.5 * s + 0.1 for s in savant]   # [0.20, 0.25, 0.30]
        cal = calibration(ours, savant)
        self.assertAlmostEqual(correlation(ours, savant), 1.0, places=6)  # corr hides it
        self.assertAlmostEqual(cal["slope"], 0.5, places=3)               # calibration catches it
        self.assertAlmostEqual(cal["intercept"], 0.1, places=3)
        # mean signed error (ours - savant) = mean([0,-.05,-.10]) = -0.05
        self.assertAlmostEqual(cal["mean_signed_error"], -0.05, places=3)
        self.assertAlmostEqual(cal["mae"], 0.05, places=3)

    def test_report_fails_loud_on_tiny_population(self):
        from projections.backtest.grid_faithfulness import faithfulness_report
        tiny = [{"our_xba": 0.25, "our_xslg": 0.45,
                 "savant_xba": 0.25, "savant_xslg": 0.45}] * 5  # 5 << MIN_QUALIFIED_PAIRS
        with self.assertRaises(ValueError):
            faithfulness_report(tiny)
