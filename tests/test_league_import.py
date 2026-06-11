# tests/test_league_import.py
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from web.league_import import (
    detect_platform, parse_fantrax, parse_espn, ImportError_, import_league,
)

FIXTURES = Path(__file__).parent / "fixtures"


class TestDetectPlatform(unittest.TestCase):
    def test_fantrax_league_url(self):
        url = "https://www.fantrax.com/fantasy/league/abc123xyz/standings"
        self.assertEqual(detect_platform(url), ("fantrax", "abc123xyz"))

    def test_fantrax_no_trailing_path(self):
        url = "https://www.fantrax.com/fantasy/league/abc123xyz"
        self.assertEqual(detect_platform(url), ("fantrax", "abc123xyz"))

    def test_espn_url(self):
        url = "https://fantasy.espn.com/baseball/league?leagueId=12345"
        self.assertEqual(detect_platform(url), ("espn", "12345"))

    def test_espn_url_with_extra_params(self):
        url = "https://fantasy.espn.com/baseball/team?leagueId=12345&teamId=3&seasonId=2026"
        self.assertEqual(detect_platform(url), ("espn", "12345"))

    def test_garbage_returns_none(self):
        for url in ("not a url", "https://football.fantasysports.yahoo.com/f1/123",
                    "https://www.fantrax.com/home", ""):
            self.assertIsNone(detect_platform(url), url)


class TestParsers(unittest.TestCase):
    def test_parse_fantrax(self):
        data = json.loads((FIXTURES / "fantrax_league_info.json").read_text())
        result = parse_fantrax(data)
        self.assertEqual(result["teams"], 10)
        self.assertEqual(result["roster"], 30)
        self.assertNotIn("budget", result)   # fxea doesn't expose it -> keep default

    def test_parse_espn(self):
        data = json.loads((FIXTURES / "espn_msettings.json").read_text())
        result = parse_espn(data)
        self.assertEqual(result["teams"], 14)
        self.assertEqual(result["roster"], 21)   # sum of lineupSlotCounts
        self.assertEqual(result["budget"], 260)

    def test_parse_fantrax_missing_fields(self):
        result = parse_fantrax({"leagueName": "x"})
        self.assertEqual(result, {})   # nothing readable -> empty partial

    def test_parse_espn_zero_budget_omitted(self):
        data = json.loads((FIXTURES / "espn_msettings.json").read_text())
        data["settings"]["draftSettings"]["auctionBudget"] = 0
        self.assertNotIn("budget", parse_espn(data))


class TestImportLeague(unittest.TestCase):
    def test_unsupported_url_raises(self):
        with self.assertRaises(ImportError_):
            import_league("https://example.com/nope")


FANTRAX_URL = "https://www.fantrax.com/fantasy/league/abc123/home"


class TestFetchErrors(unittest.TestCase):
    @patch("web.league_import.requests.get")
    def test_timeout_raises_couldnt_reach(self, mock_get):
        mock_get.side_effect = requests.exceptions.Timeout()
        with self.assertRaises(ImportError_) as ctx:
            import_league(FANTRAX_URL)
        self.assertIn("Couldn't reach", str(ctx.exception))

    @patch("web.league_import.requests.get")
    def test_403_raises_private(self, mock_get):
        mock_get.return_value.status_code = 403
        with self.assertRaises(ImportError_) as ctx:
            import_league(FANTRAX_URL)
        self.assertIn("private", str(ctx.exception))

    @patch("web.league_import.requests.get")
    def test_bad_json_raises_unexpected(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.side_effect = ValueError("not json")
        with self.assertRaises(ImportError_) as ctx:
            import_league(FANTRAX_URL)
        self.assertIn("Unexpected response", str(ctx.exception))

    @patch("web.league_import.requests.get")
    def test_non_dict_json_raises_unexpected(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = [1, 2, 3]
        with self.assertRaises(ImportError_) as ctx:
            import_league(FANTRAX_URL)
        self.assertIn("Unexpected response", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class TestUpstreamShapeDrift(unittest.TestCase):
    """Surprise third-party response shapes must degrade to the inline notice,
    never a 500 (htmx drops 5xx without swapping, so the button looks dead)."""

    @patch("web.league_import._fetch_json")
    def test_fantrax_rosterinfo_list_degrades_to_notice(self, mock_fetch):
        mock_fetch.return_value = {"teamInfo": {"t1": {}}, "rosterInfo": [1, 2]}
        with self.assertRaises(ImportError_) as ctx:
            import_league(FANTRAX_URL)
        self.assertIn("enter them manually", str(ctx.exception))

    @patch("web.league_import._fetch_json")
    def test_espn_settings_list_degrades_to_notice(self, mock_fetch):
        mock_fetch.return_value = {"settings": [1, 2, 3]}
        with self.assertRaises(ImportError_) as ctx:
            import_league("https://fantasy.espn.com/baseball/league?leagueId=12345")
        self.assertIn("enter them manually", str(ctx.exception))

    @patch("web.league_import._fetch_json")
    def test_espn_infinity_slot_count_degrades_to_notice(self, mock_fetch):
        mock_fetch.return_value = {"settings": {
            "size": 10,
            "rosterSettings": {"lineupSlotCounts": {"0": float("inf")}},
        }}
        with self.assertRaises(ImportError_) as ctx:
            import_league("https://fantasy.espn.com/baseball/league?leagueId=12345")
        self.assertIn("enter them manually", str(ctx.exception))


class TestFetchHardening(unittest.TestCase):
    @patch("web.league_import.requests.get")
    def test_redirects_are_not_followed(self, mock_get):
        mock_get.return_value.status_code = 301
        with self.assertRaises(ImportError_) as ctx:
            import_league(FANTRAX_URL)
        self.assertIn("HTTP 301", str(ctx.exception))
        self.assertFalse(mock_get.call_args.kwargs.get("allow_redirects", True))

    @patch("web.league_import.requests.get")
    def test_oversize_declared_response_degrades_to_notice(self, mock_get):
        mock_get.return_value.status_code = 200
        mock_get.return_value.headers = {"Content-Length": str(10 * 1024 * 1024)}
        with self.assertRaises(ImportError_) as ctx:
            import_league(FANTRAX_URL)
        self.assertIn("Unexpected response", str(ctx.exception))
