import tempfile
import unittest
from pathlib import Path

from projections.data.statcast import (
    merge_statcast, store_statcast_season, load_statcast_season,
    assert_coverage, assert_value_coverage, COVERAGE_FLOOR,
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

    def test_value_coverage_passes_when_xba_xslg_present(self):
        rows = [{"mlbam_id": str(i), "xba": 0.25, "xslg": 0.45}
                for i in range(COVERAGE_FLOOR)]
        assert_value_coverage(2023, rows)   # no raise

    def test_value_coverage_raises_on_schema_drift_all_none(self):
        # Rows parse fine but xBA/xSLG are None (est_ba/est_slg renamed upstream).
        rows = [{"mlbam_id": str(i), "xba": None, "xslg": None}
                for i in range(COVERAGE_FLOOR + 50)]
        with self.assertRaises(ValueError):
            assert_value_coverage(2023, rows)

    def test_value_coverage_raises_on_low_share(self):
        # Plenty of rows, plenty usable count, but < MIN_VALUE_SHARE have values.
        good = [{"mlbam_id": str(i), "xba": 0.25, "xslg": 0.45} for i in range(COVERAGE_FLOOR)]
        bad = [{"mlbam_id": f"b{i}", "xba": None, "xslg": None} for i in range(COVERAGE_FLOOR)]
        with self.assertRaises(ValueError):
            assert_value_coverage(2023, good + bad)   # 50% share < 80%
