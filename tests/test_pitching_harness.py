import tempfile
import unittest
from pathlib import Path

from projections.data.pitching_historical import store_pitching_season
from projections.backtest.pitching_harness import backtest_pitching_season
from projections.models.pitcher_params import PitcherMarcelParams


def _sp(pid, yr, er):
    return {"mlbam_id": pid, "season": yr, "BF": 750, "IP": 180.0, "ER": er,
            "H_ALLOWED": 150, "BB": 45, "HBP": 5, "K": 200, "HR": 22,
            "W": 14, "L": 8, "SV": 0, "HLD": 0, "GS": 30, "G": 30, "GF": 0, "QS": 18}


class TestPitchingHarness(unittest.TestCase):
    def test_scores_eval_population(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2020, 2021, 2022, 2023):
                store_pitching_season(yr, [_sp("600", yr, 70)], data_dir)
            result = backtest_pitching_season(2023, data_dir, PitcherMarcelParams())
            self.assertEqual(result["eval_n"], 1)
            self.assertIn("marcel_mae", result["per_stat"]["ERA"])
            self.assertIn("persistence_mae", result["per_stat"]["ERA"])

    def test_low_ip_excluded(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2020, 2021, 2022):
                store_pitching_season(yr, [_sp("600", yr, 70)], data_dir)
            # target-year actual below SP IP floor -> excluded
            low = _sp("600", 2023, 70); low["IP"] = 20.0
            store_pitching_season(2023, [low], data_dir)
            result = backtest_pitching_season(2023, data_dir, PitcherMarcelParams())
            self.assertEqual(result["eval_n"], 0)
