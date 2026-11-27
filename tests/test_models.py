"""Tests for RosterSettings model."""

import unittest

from league_values.models import RosterSettings, LeagueConfig, CategorySpec, PlayerPool, Direction


class TestRosterSettings(unittest.TestCase):

    def test_default_roster_settings(self):
        rs = RosterSettings()
        self.assertEqual(rs.teams, 12)
        self.assertEqual(rs.roster_size, 23)
        self.assertEqual(rs.positions, {})
        self.assertEqual(rs.bench, 5)

    def test_custom_roster_settings(self):
        rs = RosterSettings(teams=10, roster_size=25, positions={"C": 2, "SP": 5}, bench=4)
        self.assertEqual(rs.teams, 10)
        self.assertEqual(rs.roster_size, 25)
        self.assertEqual(rs.positions, {"C": 2, "SP": 5})
        self.assertEqual(rs.bench, 4)

    def test_total_starters(self):
        positions = {"C": 1, "1B": 1, "2B": 1, "SS": 1, "3B": 1, "OF": 3, "UTIL": 1, "SP": 5, "RP": 2}
        rs = RosterSettings(positions=positions)
        self.assertEqual(rs.total_starters, 16)

    def test_roster_settings_from_dict(self):
        data = {"teams": 10, "roster_size": 20, "positions": {"C": 2, "SP": 4}, "bench": 4}
        rs = RosterSettings.from_dict(data)
        self.assertEqual(rs.teams, 10)
        self.assertEqual(rs.roster_size, 20)
        self.assertEqual(rs.positions, {"C": 2, "SP": 4})
        self.assertEqual(rs.bench, 4)

    def test_roster_settings_frozen(self):
        rs = RosterSettings()
        with self.assertRaises(AttributeError):
            rs.teams = 99


class TestLeagueConfigRoster(unittest.TestCase):

    def _base_cat_config(self):
        return {
            "name": "TestLeague",
            "scoring_mode": "categories",
            "categories": [
                {"id": "HR", "label": "HR", "pool": "hitter", "stat": "HR"}
            ],
        }

    def test_league_config_roster_none_by_default(self):
        data = self._base_cat_config()
        cfg = LeagueConfig.from_dict(data)
        self.assertIsNone(cfg.roster)

    def test_league_config_roster_parsed(self):
        data = self._base_cat_config()
        data["roster"] = {"teams": 10, "roster_size": 20, "positions": {"C": 1, "SP": 4}, "bench": 3}
        cfg = LeagueConfig.from_dict(data)
        self.assertIsNotNone(cfg.roster)
        self.assertEqual(cfg.roster.teams, 10)
        self.assertEqual(cfg.roster.roster_size, 20)
        self.assertEqual(cfg.roster.bench, 3)
        self.assertEqual(cfg.roster.total_starters, 5)


class TestPlayerPoolRP(unittest.TestCase):
    def test_starter_and_reliever_exist(self):
        self.assertEqual(PlayerPool.STARTER.value, "starter")
        self.assertEqual(PlayerPool.RELIEVER.value, "reliever")

    def test_pitcher_category_applies_to_starter(self):
        cat = CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K")
        self.assertTrue(cat.applies_to(PlayerPool.STARTER))
        self.assertTrue(cat.applies_to(PlayerPool.RELIEVER))
        self.assertTrue(cat.applies_to(PlayerPool.PITCHER))

    def test_starter_only_category(self):
        cat = CategorySpec(id="QS", label="QS", pool=PlayerPool.STARTER, stat="QS")
        self.assertTrue(cat.applies_to(PlayerPool.STARTER))
        self.assertFalse(cat.applies_to(PlayerPool.RELIEVER))
        self.assertFalse(cat.applies_to(PlayerPool.HITTER))

    def test_reliever_only_category(self):
        cat = CategorySpec(id="SV", label="SV", pool=PlayerPool.RELIEVER, stat="SV")
        self.assertTrue(cat.applies_to(PlayerPool.RELIEVER))
        self.assertFalse(cat.applies_to(PlayerPool.STARTER))
        self.assertFalse(cat.applies_to(PlayerPool.HITTER))


if __name__ == "__main__":
    unittest.main()
