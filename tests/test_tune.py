import tempfile
import unittest
from pathlib import Path

from projections.data.historical import store_season
from projections.backtest.tune import grid_search, default_grid
from projections.models.marcel_params import MarcelParams


def _row(pid, yr, hr):
    return {"mlbam_id": pid, "season": yr, "PA": 500, "AB": 450, "H": 125,
            "1B": 100, "2B": 0, "3B": 0, "HR": hr, "R": 80, "RBI": 70,
            "SB": 0, "CS": 0, "BB": 50, "SO": 100, "HBP": 0, "SF": 0}


class TestTune(unittest.TestCase):
    def test_grid_search_returns_best_params_and_score(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"},
                      "7": {"birth_date": "1990-01-01"}}
            grid = [MarcelParams(n_reg=600.0), MarcelParams(n_reg=1500.0)]
            best, score = grid_search([2022, 2023], data_dir, idents, grid)
            self.assertIn(best.n_reg, (600.0, 1500.0))
            self.assertIsInstance(score, float)

    def test_default_grid_is_nonempty_marcel_params(self):
        grid = default_grid()
        self.assertGreater(len(grid), 1)
        self.assertIsInstance(grid[0], MarcelParams)

    def test_coordinate_descent_returns_params_and_score(self):
        from projections.backtest.tune import coordinate_descent
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"},
                      "7": {"birth_date": "1990-01-01"}}
            best, score = coordinate_descent(
                [2022, 2023], data_dir, idents,
                n_reg_values=(900.0, 1200.0), gamma_values=(0.0, 0.5),
            )
            self.assertIn(best.n_reg, (900.0, 1200.0))
            self.assertIn(best.gamma, (0.0, 0.5))
            self.assertIsInstance(score, float)

    def test_coordinate_descent_starts_from_classic(self):
        # With a single-value grid equal to defaults, it returns classic unchanged.
        from projections.backtest.tune import coordinate_descent
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"}, "7": {"birth_date": "1990-01-01"}}
            best, _ = coordinate_descent(
                [2022, 2023], data_dir, idents,
                n_reg_values=(1200.0,), gamma_values=(0.0,),
            )
            self.assertEqual((best.n_reg, best.gamma), (1200.0, 0.0))

    def test_coordinate_descent_alpha_returns_params_and_score(self):
        from projections.backtest.tune import coordinate_descent_alpha
        from projections.data.statcast import store_statcast_season
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
                store_statcast_season(yr, [
                    {"mlbam_id": "5", "xba": 0.27, "xslg": 0.47, "xwoba": 0.34},
                    {"mlbam_id": "7", "xba": 0.25, "xslg": 0.52, "xwoba": 0.35},
                ], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"}, "7": {"birth_date": "1990-01-01"}}
            best, score = coordinate_descent_alpha(
                [2022, 2023], data_dir, idents,
                ac_values=(0.0, 0.5), ap_values=(0.0, 0.5),
            )
            self.assertIn(best.alpha_contact, (0.0, 0.5))
            self.assertIn(best.alpha_power, (0.0, 0.5))
            self.assertEqual(best.gamma, 0.0)         # gamma stays classic (isolation)
            self.assertIsInstance(score, float)

    def test_existing_coordinate_descent_still_works(self):
        # Refactor must not break the Rung 2 entry point.
        from projections.backtest.tune import coordinate_descent
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in range(2018, 2024):
                store_season(yr, [_row("5", yr, 25), _row("7", yr, 18)], data_dir)
            idents = {"5": {"birth_date": "1992-01-01"}, "7": {"birth_date": "1990-01-01"}}
            best, _ = coordinate_descent(
                [2022, 2023], data_dir, idents,
                n_reg_values=(1200.0,), gamma_values=(0.0,))
            self.assertEqual((best.n_reg, best.gamma), (1200.0, 0.0))
