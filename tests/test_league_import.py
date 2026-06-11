# tests/test_league_import.py
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


if __name__ == "__main__":
    unittest.main()
