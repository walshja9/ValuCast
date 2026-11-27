import unittest
from league_values import ScoringMode, value_players
from league_values.models import PlayerPool
from league_values.presets import dd_7x7


class TestDD7x7Preset(unittest.TestCase):
    def test_dd_7x7_loads(self):
        config = dd_7x7()
        self.assertEqual(config.name, "DD 7x7")
        self.assertEqual(config.scoring_mode, ScoringMode.CATEGORIES)
        # 7 hitting + 6 SP + 6 RP = 19
        self.assertEqual(len(config.categories), 19)

    def test_dd_7x7_has_correct_hitting_cats(self):
        config = dd_7x7()
        hitting_ids = {c.id for c in config.categories if c.pool is PlayerPool.HITTER}
        self.assertEqual(hitting_ids, {"R", "HR", "RBI", "SB", "AVG", "OPS", "SO"})

    def test_dd_7x7_has_correct_sp_cats(self):
        config = dd_7x7()
        sp_ids = {c.id for c in config.categories if c.pool is PlayerPool.STARTER}
        self.assertEqual(sp_ids, {"SP_K", "SP_QS", "SP_L", "SP_ERA", "SP_WHIP", "SP_K_BB"})

    def test_dd_7x7_has_correct_rp_cats(self):
        config = dd_7x7()
        rp_ids = {c.id for c in config.categories if c.pool is PlayerPool.RELIEVER}
        self.assertEqual(rp_ids, {"RP_K", "RP_SV_HLD", "RP_L", "RP_ERA", "RP_WHIP", "RP_K_BB"})

    def test_dd_7x7_inverse_cats(self):
        config = dd_7x7()
        inverse_ids = {c.id for c in config.categories if c.direction.value == "lower"}
        self.assertEqual(inverse_ids, {"SO", "SP_L", "SP_ERA", "SP_WHIP", "RP_L", "RP_ERA", "RP_WHIP"})

    def test_dd_7x7_has_sp_baselines(self):
        config = dd_7x7()
        self.assertIn("SP_K", config.league_baselines)
        self.assertIn("SP_ERA", config.league_baselines)
        self.assertEqual(config.league_baselines["SP_K"], (120.0, 49.0))

    def test_dd_7x7_has_rp_baselines(self):
        config = dd_7x7()
        self.assertIn("RP_K", config.league_baselines)
        self.assertIn("RP_ERA", config.league_baselines)
        self.assertEqual(config.league_baselines["RP_K"], (48.0, 26.0))

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
                "id": "sp1", "name": "Starter", "pool": "starter",
                "stats": {"K": 180, "QS": 15, "SV_HLD": 0, "L": 8,
                    "ER": 60, "IP": 180, "BB": 45, "H_ALLOWED": 150,
                    "ERA": 3.00, "WHIP": 1.08, "K_BB": 4.0},
            },
            {
                "id": "rp1", "name": "Reliever", "pool": "reliever",
                "stats": {"K": 65, "QS": 0, "SV_HLD": 35, "L": 2,
                    "ERA": 2.50, "WHIP": 1.00, "K_BB": 4.0},
            },
        ]
        results = value_players(players, config)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertNotEqual(r.total_value, 0.0, f"{r.name} got zero value")


if __name__ == "__main__":
    unittest.main()
