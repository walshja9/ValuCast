import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from web.league_settings import LeagueSettings, parse_league_settings


class FakeArgs(dict):
    """Mimics request.args.get for the keys we read."""
    def get(self, key, default=None):
        return dict.get(self, key, default)


class TestParseLeagueSettings(unittest.TestCase):
    def test_defaults_when_absent(self):
        s = parse_league_settings(FakeArgs())
        self.assertEqual((s.teams, s.budget, s.roster, s.pslots), (12, 200, 26, 5))

    def test_parses_valid_values(self):
        s = parse_league_settings(FakeArgs(teams="16", budget="400", roster="30", pslots="10"))
        self.assertEqual((s.teams, s.budget, s.roster, s.pslots), (16, 400, 30, 10))

    def test_clamps_out_of_range(self):
        s = parse_league_settings(FakeArgs(teams="99", budget="5", roster="2", pslots="999"))
        self.assertEqual(s.teams, 20)    # max 20
        self.assertEqual(s.budget, 100)  # min 100
        self.assertEqual(s.roster, 10)   # min 10
        self.assertEqual(s.pslots, 20)   # max 20

    def test_garbage_falls_back_to_defaults(self):
        s = parse_league_settings(FakeArgs(teams="abc", budget="", roster="12.5x", pslots=None))
        self.assertEqual((s.teams, s.budget, s.roster, s.pslots), (12, 200, 26, 5))

    def test_roster_cutoff(self):
        s = parse_league_settings(FakeArgs(teams="10", roster="20"))
        self.assertEqual(s.roster_cutoff, 200)

    def test_prospect_cutoff(self):
        s = parse_league_settings(FakeArgs(teams="10", pslots="4"))
        self.assertEqual(s.prospect_cutoff, 40)

    def test_summary(self):
        s = LeagueSettings(teams=12, budget=200, roster=26, pslots=5)
        self.assertEqual(s.summary(), "12 teams · $200 · 26 roster · 5 prospect slots")

    def test_is_default(self):
        self.assertTrue(LeagueSettings(12, 200, 26, 5).is_default)
        self.assertFalse(LeagueSettings(10, 200, 26, 5).is_default)


if __name__ == "__main__":
    unittest.main()
