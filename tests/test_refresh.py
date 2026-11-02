import json
import os
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from scraper.mlb_actuals import regular_season_games_final
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

    # Fixture pools are tiny by design; skip the population-floor guards so
    # these tests keep exercising refresh plumbing (floors have their own
    # tests in tests/test_blend.py).
    with patch("scraper.refresh.fetch_all", return_value=_RAW_RETURN), \
         patch("scraper.refresh.build_actuals", return_value=[_FAKE_ACTUAL_HITTER]), \
         patch("scraper.refresh.combine_outlook", return_value=_FAKE_OUTLOOK), \
         patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"}):
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
            self.assertEqual(meta["ros_status"], "fetched")
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

    def test_refresh_season_defaults_to_current_year(self):
        """With no season arg and no env override, season derives from today."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("VALUCAST_ACTUALS_SEASON", None)
            with tempfile.TemporaryDirectory() as tmpdir:
                _, _, _, _, metadata_path, _ = _run_refresh(tmpdir)
                with open(metadata_path) as f:
                    meta = json.load(f)
                self.assertEqual(meta["season"], date.today().year)

    def test_refresh_season_env_override_respected(self):
        """VALUCAST_ACTUALS_SEASON overrides the derived current-year season."""
        with patch.dict(os.environ, {"VALUCAST_ACTUALS_SEASON": "2027"}):
            with tempfile.TemporaryDirectory() as tmpdir:
                _, _, _, _, metadata_path, _ = _run_refresh(tmpdir)
                with open(metadata_path) as f:
                    meta = json.load(f)
                self.assertEqual(meta["season"], 2027)


class TestEmptyRosRefresh(unittest.TestCase):

    def setUp(self):
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        self.paths = {
            "output_path": os.path.join(tmpdir.name, "current.json"),
            "ros_output_path": os.path.join(tmpdir.name, "ros.json"),
            "actuals_output_path": os.path.join(tmpdir.name, "actuals", "current.json"),
            "metadata_path": os.path.join(tmpdir.name, "metadata.json"),
            "raw_dir": os.path.join(tmpdir.name, "raw"),
        }
        for target, value in (
            ("scraper.refresh.fetch_all", {key: [] for key in _RAW_RETURN}),
            ("scraper.refresh.build_actuals", [_FAKE_ACTUAL_HITTER]),
            ("scraper.refresh.combine_outlook", _FAKE_OUTLOOK),
        ):
            patcher = patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env_patch = patch.dict(os.environ)
        env_patch.start()
        self.addCleanup(env_patch.stop)
        os.environ.pop("VALUCAST_SKIP_BLEND_POOL_FLOOR", None)

    def _write_prior_ros(self):
        prior_bytes = (json.dumps([_FAKE_ROS_HITTER]) + "\n").encode("utf-8")
        with open(self.paths["ros_output_path"], "wb") as f:
            f.write(prior_bytes)
        return prior_bytes

    def _assert_ros_unchanged(self, prior_bytes):
        with open(self.paths["ros_output_path"], "rb") as f:
            self.assertEqual(f.read(), prior_bytes)

    def test_empty_feeds_without_final_games_retain_prior_ros(self):
        prior_bytes = self._write_prior_ros()
        with patch("scraper.refresh.regular_season_games_final", return_value=0) as games, \
             patch("scraper.refresh.date", wraps=date) as mock_date, \
             patch("scraper.refresh.blend_projections", return_value=[_FAKE_ROS_HITTER]) as blend, \
             patch("scraper.refresh.save_raw") as save, \
             patch("scraper.refresh.combine_outlook", return_value=_FAKE_OUTLOOK) as combine, \
             patch("builtins.print") as print_mock:
            mock_date.today.return_value = date(2026, 5, 10)
            result = refresh(**self.paths, delay=0)

        self.assertEqual(result, _FAKE_OUTLOOK)
        self._assert_ros_unchanged(prior_bytes)
        games.assert_called_once_with("2026-05-03", "2026-05-10")
        blend.assert_not_called()
        save.assert_not_called()
        combine.assert_called_once_with([_FAKE_ROS_HITTER], [_FAKE_ACTUAL_HITTER])
        self.assertTrue(os.path.exists(self.paths["output_path"]))
        self.assertTrue(os.path.exists(self.paths["actuals_output_path"]))
        with open(self.paths["metadata_path"]) as f:
            self.assertEqual(json.load(f)["ros_status"], "retained")
        warnings = [call.args[0] for call in print_mock.call_args_list
                    if call.args and call.args[0].startswith("::warning::")]
        self.assertEqual(len(warnings), 1)
        self.assertIn("last 7 days", warnings[0])
        self.assertIn("prior ros.json", warnings[0])

    def test_empty_feeds_with_final_games_reach_real_floor(self):
        prior_bytes = self._write_prior_ros()
        with patch("scraper.refresh.regular_season_games_final", return_value=1), \
             patch("scraper.refresh.save_raw") as save:
            with self.assertRaisesRegex(RuntimeError, "only 0 hitters, below floor"):
                refresh(**self.paths, delay=0)
        save.assert_called_once()
        self._assert_ros_unchanged(prior_bytes)
        self.assertFalse(os.path.exists(self.paths["output_path"]))

    def test_partial_feed_reaches_real_floor_without_schedule_call(self):
        prior_bytes = self._write_prior_ros()
        with patch("scraper.refresh.fetch_all", return_value=_RAW_RETURN), \
             patch("scraper.refresh.regular_season_games_final") as games, \
             patch("scraper.refresh.save_raw") as save:
            with self.assertRaisesRegex(RuntimeError, "only 1 hitters, below floor"):
                refresh(**self.paths, delay=0)
        games.assert_not_called()
        save.assert_called_once()
        self._assert_ros_unchanged(prior_bytes)
        self.assertFalse(os.path.exists(self.paths["output_path"]))

    def test_empty_feeds_without_prior_ros_raise(self):
        with patch("scraper.refresh.regular_season_games_final", return_value=0), \
             patch("scraper.refresh.blend_projections") as blend, \
             patch("scraper.refresh.save_raw") as save:
            with self.assertRaises(RuntimeError):
                refresh(**self.paths, delay=0)
        blend.assert_not_called()
        save.assert_not_called()
        self.assertFalse(os.path.exists(self.paths["output_path"]))
        self.assertFalse(os.path.exists(self.paths["ros_output_path"]))

    def test_empty_feeds_with_invalid_prior_ros_raise(self):
        for prior_bytes in (b"[]", b"{}", b"null", b'"players"', b"invalid JSON", b"\xff"):
            with self.subTest(prior_bytes=prior_bytes):
                with open(self.paths["ros_output_path"], "wb") as f:
                    f.write(prior_bytes)
                with patch("scraper.refresh.regular_season_games_final", return_value=0):
                    with self.assertRaises(RuntimeError):
                        refresh(**self.paths, delay=0)
                self._assert_ros_unchanged(prior_bytes)
                self.assertFalse(os.path.exists(self.paths["output_path"]))

    def test_empty_feeds_with_unreadable_prior_ros_raise(self):
        prior_bytes = self._write_prior_ros()
        with patch("scraper.refresh.regular_season_games_final", return_value=0), \
             patch("builtins.open", side_effect=PermissionError("unreadable ROS")):
            with self.assertRaises(RuntimeError):
                refresh(**self.paths, delay=0)
        self._assert_ros_unchanged(prior_bytes)
        self.assertFalse(os.path.exists(self.paths["output_path"]))

    def test_schedule_failure_propagates(self):
        prior_bytes = self._write_prior_ros()
        failure = OSError("schedule unavailable")
        with patch("scraper.refresh.regular_season_games_final", side_effect=failure), \
             patch("scraper.refresh.save_raw") as save:
            with self.assertRaises(OSError) as raised:
                refresh(**self.paths, delay=0)
        self.assertIs(raised.exception, failure)
        save.assert_not_called()
        self._assert_ros_unchanged(prior_bytes)
        self.assertFalse(os.path.exists(self.paths["output_path"]))


class TestRegularSeasonGamesFinal(unittest.TestCase):

    def test_counts_only_final_games_across_dates(self):
        schedule = {"dates": [
            {"games": [{"status": {"abstractGameState": "Final"}},
                       {"status": {"abstractGameState": "Preview", "detailedState": "Scheduled"}}]},
            {"games": [{"status": {"abstractGameState": "Final"}},
                       {"status": {"abstractGameState": "Live"}},
                       {"status": {"abstractGameState": "Preview", "detailedState": "Cancelled"}}]},
        ]}
        with patch("scraper.mlb_actuals._fetch_json", return_value=schedule) as fetch:
            self.assertEqual(regular_season_games_final("2026-05-03", "2026-05-10"), 2)
        fetch.assert_called_once_with(
            "https://statsapi.mlb.com/api/v1/schedule?"
            "sportId=1&gameType=R&startDate=2026-05-03&endDate=2026-05-10"
        )

    def test_empty_schedule_returns_zero(self):
        with patch("scraper.mlb_actuals._fetch_json", return_value={"dates": []}):
            self.assertEqual(regular_season_games_final("2026-05-03", "2026-05-10"), 0)

    def test_fetch_failure_propagates(self):
        failure = OSError("schedule unavailable")
        with patch("scraper.mlb_actuals._fetch_json", side_effect=failure):
            with self.assertRaises(OSError) as raised:
                regular_season_games_final("2026-05-03", "2026-05-10")
        self.assertIs(raised.exception, failure)


if __name__ == "__main__":
    unittest.main()
