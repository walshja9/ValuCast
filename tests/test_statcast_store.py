import tempfile
import unittest
from pathlib import Path

from projections.data.statcast import (
    merge_statcast, store_statcast_season, load_statcast_season,
    assert_coverage, COVERAGE_FLOOR,
)


class TestStatcastStore(unittest.TestCase):
    def test_merge_joins_expected_and_quality_by_id(self):
        expected = {"5": {"xba": 0.25, "xslg": 0.45, "xwoba": 0.33}}
        quality = {"5": {"barrel_pct": 9.0, "avg_ev": 89.0,
                         "hardhit_pct": 40.0, "launch_angle": 12.0}}
        rows = merge_statcast(expected, quality)
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["mlbam_id"], "5")
        self.assertAlmostEqual(r["xba"], 0.25)
        self.assertAlmostEqual(r["barrel_pct"], 9.0)

    def test_store_load_roundtrip_and_immutable_noop(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            rows = [{"mlbam_id": "5", "xba": 0.25, "xslg": 0.45, "xwoba": 0.33,
                     "barrel_pct": 9.0, "avg_ev": 89.0, "hardhit_pct": 40.0,
                     "launch_angle": 12.0}]
            store_statcast_season(2023, rows, data_dir)
            store_statcast_season(2023, rows, data_dir)  # identical -> no-op
            loaded = load_statcast_season(2023, data_dir)
            self.assertAlmostEqual(loaded["5"]["xba"], 0.25)

    def test_store_raises_on_changed_season(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            store_statcast_season(2023, [{"mlbam_id": "5", "xba": 0.25}], data_dir)
            with self.assertRaises(ValueError):
                store_statcast_season(2023, [{"mlbam_id": "5", "xba": 0.99}], data_dir)

    def test_assert_coverage_raises_below_floor(self):
        assert_coverage(2023, COVERAGE_FLOOR)        # exactly floor -> ok
        with self.assertRaises(ValueError):
            assert_coverage(2023, COVERAGE_FLOOR - 1)  # below -> raise

    def test_load_missing_season_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_statcast_season(2099, Path(d)), {})
