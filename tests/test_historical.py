import json
import tempfile
import unittest
from pathlib import Path

from projections.data.historical import (
    normalize_season_rows, store_season, load_season, content_hash,
)


class TestHistorical(unittest.TestCase):
    def test_normalize_keeps_only_counting_keys(self):
        raw_player = {
            "id": "mlbam_5_H", "name": "Bat", "pool": "hitter",
            "stats": {"PA": 100, "AB": 90, "H": 30, "1B": 20, "2B": 5,
                      "3B": 1, "HR": 4, "R": 15, "RBI": 18, "SB": 2, "CS": 1,
                      "BB": 8, "SO": 20, "HBP": 1, "SF": 1, "G": 25,
                      "AVG": 0.333, "OPS": 0.9},
            "metadata": {"mlbam_id": "5"},
        }
        rows = normalize_season_rows([raw_player])
        self.assertEqual(rows[0]["mlbam_id"], "5")
        self.assertEqual(rows[0]["HR"], 4)
        self.assertNotIn("AVG", rows[0])   # rates not stored

    def test_store_is_immutable_noop_on_identical_repull(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            rows = [{"mlbam_id": "5", "season": 2020, "PA": 100, "HR": 4}]
            store_season(2020, rows, data_dir)
            first = content_hash(data_dir / "historical" / "hitting_2020.json")
            store_season(2020, rows, data_dir)  # identical re-pull
            second = content_hash(data_dir / "historical" / "hitting_2020.json")
            self.assertEqual(first, second)
            self.assertEqual(load_season(2020, data_dir), rows)

    def test_store_raises_on_changed_finalized_season(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store_season(2020, [{"mlbam_id": "5", "season": 2020, "HR": 4}], data_dir)
            with self.assertRaises(ValueError):
                store_season(2020, [{"mlbam_id": "5", "season": 2020, "HR": 99}], data_dir)
