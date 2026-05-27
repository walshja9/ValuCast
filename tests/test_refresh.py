import json
import os
import tempfile
import unittest
from unittest.mock import patch

from scraper.refresh import refresh

_FAKE_ROS_HITTER = {
    "name": "Test Player",
    "pool": "hitter",
    "stats": {"PA": 400, "AB": 360, "H": 108, "HR": 20, "R": 60, "RBI": 55,
              "SB": 8, "SO": 80, "BB": 36, "AVG": 0.300, "OBP": 0.370,
              "SLG": 0.500, "OPS": 0.870},
    "metadata": {"playerids": "1", "team": "NYY"},
}

_FAKE_ACTUAL_HITTER = {
    "name": "Test Player",
    "pool": "hitter",
    "mlbam_id": "999",
    "stats": {"PA": 200, "AB": 180, "H": 54, "HR": 10, "R": 30, "RBI": 28,
              "SB": 4, "SO": 40, "BB": 18, "AVG": 0.300, "OBP": 0.370,
              "SLG": 0.500, "OPS": 0.870},
    "metadata": {"as_of": "2026-05-25"},
}

_FAKE_OUTLOOK = [
    {
        "name": "Test Player",
        "pool": "hitter",
        "stats": {"PA": 600, "HR": 30},
        "metadata": {"has_ros": True},
    }
]

_RAW_RETURN = {
    "steamer_hitters": [
        {"playerids": "1", "PlayerName": "Test Player", "Team": "NYY",
         "PA": 400, "AB": 360, "H": 108, "HR": 20, "R": 60, "RBI": 55,
         "SB": 8, "SO": 80, "BB": 36, "AVG": 0.300, "OBP": 0.370,
         "SLG": 0.500, "OPS": 0.870},
    ],
    "steamer_pitchers": [],
    "zips_hitters": [],
    "zips_pitchers": [],
}


def _run_refresh(tmpdir, **extra_kwargs):
    """Helper: run refresh with all external calls mocked, returning (outlook, tmpdir)."""
    output = os.path.join(tmpdir, "current.json")
    ros_output = os.path.join(tmpdir, "ros.json")
    actuals_output = os.path.join(tmpdir, "actuals", "current.json")
    metadata_path = os.path.join(tmpdir, "metadata.json")
    raw_dir = os.path.join(tmpdir, "raw")

    with patch("scraper.refresh.fetch_all", return_value=_RAW_RETURN), \
         patch("scraper.refresh.build_actuals", return_value=[_FAKE_ACTUAL_HITTER]), \
         patch("scraper.refresh.combine_outlook", return_value=_FAKE_OUTLOOK):
        result = refresh(
            output_path=output,
            ros_output_path=ros_output,
            actuals_output_path=actuals_output,
            metadata_path=metadata_path,
            raw_dir=raw_dir,
            delay=0,
            **extra_kwargs,
        )
    return result, output, ros_output, actuals_output, metadata_path, raw_dir


class TestRefresh(unittest.TestCase):

    def test_refresh_writes_current_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, output, *_ = _run_refresh(tmpdir)
            self.assertTrue(os.path.exists(output))
            with open(output) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "Test Player")

    def test_refresh_writes_ros_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, ros_output, *_ = _run_refresh(tmpdir)
            self.assertTrue(os.path.exists(ros_output))
            with open(ros_output) as f:
                data = json.load(f)
            # blend_projections is NOT mocked; it runs on the fake raw data
            self.assertIsInstance(data, list)

    def test_refresh_writes_actuals_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, actuals_output, *_ = _run_refresh(tmpdir)
            self.assertTrue(os.path.exists(actuals_output))
            with open(actuals_output) as f:
                data = json.load(f)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["name"], "Test Player")

    def test_refresh_writes_metadata_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, _, metadata_path, _ = _run_refresh(tmpdir)
            self.assertTrue(os.path.exists(metadata_path))
            with open(metadata_path) as f:
                meta = json.load(f)
            self.assertIn("as_of", meta)
            self.assertEqual(meta["actuals_source"], "mlb_stats_api")
            self.assertEqual(meta["ros_source"], "fangraphs_steamer_ros")
            self.assertEqual(meta["outlook_players"], 1)
            self.assertEqual(meta["players_without_ros"], 0)

    def test_refresh_saves_raw_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, _, _, raw_dir = _run_refresh(tmpdir)
            self.assertTrue(os.path.exists(os.path.join(raw_dir, "steamer_hitters.json")))

    def test_refresh_returns_outlook_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result, *_ = _run_refresh(tmpdir)
            self.assertIsInstance(result, list)
            self.assertEqual(len(result), 1)

    def test_refresh_staged_publish_no_tmp_left(self):
        """Ensure .tmp files are cleaned up after atomic replace."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_refresh(tmpdir)
            for root, _, files in os.walk(tmpdir):
                for fname in files:
                    self.assertFalse(fname.endswith(".tmp"),
                                     f"Leftover .tmp file: {os.path.join(root, fname)}")

    def test_refresh_metadata_counts(self):
        """Metadata hitter/pitcher counts reflect actual_players list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            _, _, _, _, metadata_path, _ = _run_refresh(tmpdir)
            with open(metadata_path) as f:
                meta = json.load(f)
            # _FAKE_ACTUAL_HITTER has pool=="hitter"
            self.assertEqual(meta["actuals_hitters"], 1)
            self.assertEqual(meta["actuals_pitchers"], 0)


if __name__ == "__main__":
    unittest.main()
