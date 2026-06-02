import tempfile
import unittest
from pathlib import Path

from projections.data.historical import store_season
from projections.backtest.harness import backtest_season
from projections.models.marcel_params import MarcelParams


class TestHarness(unittest.TestCase):
    def test_backtest_season_scores_eval_population(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            # Player 5: 3 priors + a qualified actual in target year.
            for yr in (2020, 2021, 2022, 2023):
                store_season(yr, [{
                    "mlbam_id": "5", "season": yr, "PA": 500, "AB": 450,
                    "H": 125, "1B": 100, "2B": 0, "3B": 0, "HR": 25,
                    "R": 80, "RBI": 70, "SB": 0, "CS": 0, "BB": 50,
                    "SO": 100, "HBP": 0, "SF": 0,
                }], data_dir)
            result = backtest_season(
                2023, data_dir, MarcelParams(),
                identities={"5": {"birth_date": "1994-01-01"}},
            )
            self.assertEqual(result["eval_n"], 1)
            self.assertIn("marcel_mae", result["per_stat"]["HR"])
            self.assertIn("persistence_mae", result["per_stat"]["HR"])
            self.assertIn("marcel_rmse", result["per_stat"]["HR"])

    def test_low_pa_player_excluded_from_eval(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2020, 2021, 2022):
                store_season(yr, [{"mlbam_id": "9", "season": yr, "PA": 500,
                    "AB": 450, "H": 125, "1B": 100, "2B": 0, "3B": 0, "HR": 25,
                    "R": 80, "RBI": 70, "SB": 0, "CS": 0, "BB": 50, "SO": 100,
                    "HBP": 0, "SF": 0}], data_dir)
            # target-year actual below MIN_EVAL_PA -> excluded
            store_season(2023, [{"mlbam_id": "9", "season": 2023, "PA": 50,
                "AB": 45, "H": 12, "1B": 10, "2B": 0, "3B": 0, "HR": 2,
                "R": 8, "RBI": 9, "SB": 0, "CS": 0, "BB": 5, "SO": 10,
                "HBP": 0, "SF": 0}], data_dir)
            result = backtest_season(
                2023, data_dir, MarcelParams(),
                identities={"9": {"birth_date": "1994-01-01"}},
            )
            self.assertEqual(result["eval_n"], 0)

    def test_vs_classic_detects_a_win(self):
        from projections.backtest.harness import vs_classic
        # Candidate has lower marcel_mae and higher corr than classic on HR.
        cand = [{"per_stat": {"HR": {"marcel_mae": 4.0, "marcel_corr": 0.7}}}]
        classic = [{"per_stat": {"HR": {"marcel_mae": 5.0, "marcel_corr": 0.6}}}]
        out = vs_classic(cand, classic)
        self.assertAlmostEqual(out["mean_ratio_vs_classic"], 0.8)
        self.assertEqual(out["corr_win_rate"], 1.0)
        self.assertTrue(out["beats_classic"])

    def test_vs_classic_reports_tie_when_not_better(self):
        from projections.backtest.harness import vs_classic
        cand = [{"per_stat": {"HR": {"marcel_mae": 5.0, "marcel_corr": 0.6}}}]
        classic = [{"per_stat": {"HR": {"marcel_mae": 5.0, "marcel_corr": 0.6}}}]
        out = vs_classic(cand, classic, epsilon=0.0)
        self.assertFalse(out["beats_classic"])   # ratio 1.0 is not < 1.0
