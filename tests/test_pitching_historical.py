import tempfile
import unittest
from pathlib import Path

from projections.data.pitching_historical import (
    normalize_pitching_rows, store_pitching_season, load_pitching_season,
    available_pitching_seasons,
)


class TestPitchingBackbone(unittest.TestCase):
    def test_normalize_extracts_bf_and_converts_ip(self):
        raw = [{
            "player": {"id": 600, "fullName": "Arm"},
            "stat": {"battersFaced": 800, "inningsPitched": "180.2",
                     "earnedRuns": 70, "hits": 160, "baseOnBalls": 50,
                     "hitByPitch": 6, "strikeOuts": 200, "homeRuns": 22,
                     "wins": 14, "losses": 8, "saves": 0, "holds": 0,
                     "gamesStarted": 30, "gamesPitched": 30, "gamesFinished": 0},
        }]
        rows = normalize_pitching_rows(raw, qs_map={"600": 18})
        r = rows[0]
        self.assertEqual(r["mlbam_id"], "600")
        self.assertEqual(r["BF"], 800)
        self.assertAlmostEqual(r["IP"], 180 + 2/3, places=3)  # 180.2 -> 180.667
        self.assertEqual(r["H_ALLOWED"], 160)
        self.assertEqual(r["QS"], 18)
        self.assertEqual(r["GS"], 30)

    def test_store_immutable_noop_and_change_raises(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            rows = [{"mlbam_id": "600", "season": 2020, "BF": 800, "IP": 180.0}]
            store_pitching_season(2020, rows, data_dir)
            store_pitching_season(2020, rows, data_dir)  # identical -> no-op
            self.assertEqual(load_pitching_season(2020, data_dir), rows)
            with self.assertRaises(ValueError):
                store_pitching_season(2020, [{"mlbam_id": "600", "season": 2020, "BF": 999}], data_dir)

    def test_available_seasons_sorted(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2019, 2021, 2020):
                store_pitching_season(yr, [{"mlbam_id": "1", "season": yr}], data_dir)
            self.assertEqual(available_pitching_seasons(data_dir), [2019, 2020, 2021])
