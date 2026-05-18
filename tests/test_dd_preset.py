import unittest
from league_values import ScoringMode, value_players
from league_values.presets import dd_7x7


class TestDD7x7Preset(unittest.TestCase):
    def test_dd_7x7_loads(self):
        config = dd_7x7()
        self.assertEqual(config.name, "DD 7x7")
        self.assertEqual(config.scoring_mode, ScoringMode.CATEGORIES)
        self.assertEqual(len(config.categories), 14)

    def test_dd_7x7_has_correct_hitting_cats(self):
        config = dd_7x7()
        hitting_ids = {c.id for c in config.categories if c.pool.value == "hitter"}
        self.assertEqual(hitting_ids, {"R", "HR", "RBI", "SB", "AVG", "OPS", "SO"})

    def test_dd_7x7_has_correct_pitching_cats(self):
        config = dd_7x7()
        pitching_ids = {c.id for c in config.categories if c.pool.value == "pitcher"}
        self.assertEqual(pitching_ids, {"K", "QS", "SV_HLD", "L", "ERA", "WHIP", "K_BB"})

    def test_dd_7x7_inverse_cats(self):
        config = dd_7x7()
        inverse_ids = {c.id for c in config.categories if c.direction.value == "lower"}
        self.assertEqual(inverse_ids, {"SO", "L", "ERA", "WHIP"})

    def test_dd_7x7_has_league_baselines(self):
        config = dd_7x7()
        self.assertIn("HR", config.league_baselines)
        self.assertIn("ERA", config.league_baselines)
        self.assertEqual(config.league_baselines["HR"], (22.0, 12.0))

    def test_dd_7x7_has_roster_settings(self):
        config = dd_7x7()
        self.assertIsNotNone(config.roster)
        self.assertEqual(config.roster.teams, 12)

    def test_dd_7x7_produces_results(self):
        config = dd_7x7()
        players = [
            {
                "id": "h1", "name": "Hitter", "pool": "hitter",
                "stats": {"R": 80, "HR": 25, "RBI": 80, "SB": 10,
                    "H": 150, "AB": 550, "OPS": 0.790, "AVG": 0.273, "SO": 120},
            },
            {
                "id": "p1", "name": "Pitcher", "pool": "pitcher",
                "stats": {"K": 180, "QS": 15, "SV_HLD": 0, "L": 8,
                    "ER": 60, "IP": 180, "BB": 45, "H_ALLOWED": 150,
                    "ERA": 3.00, "WHIP": 1.08, "K_BB": 4.0},
            },
        ]
        results = value_players(players, config)
        self.assertEqual(len(results), 2)


if __name__ == "__main__":
    unittest.main()
