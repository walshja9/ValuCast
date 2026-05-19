import unittest
from scraper.blend import blend_projections, blend_hitters, blend_pitchers

STEAMER_HITTERS = [
    {"playerids": "1", "PlayerName": "Star Hitter", "Team": "NYY",
     "PA": 620, "AB": 560, "H": 168, "HR": 32, "R": 95, "RBI": 90,
     "SB": 15, "SO": 120, "BB": 55, "AVG": 0.300, "OBP": 0.370, "SLG": 0.520, "OPS": 0.890},
    {"playerids": "2", "PlayerName": "Bench Guy", "Team": "BOS",
     "PA": 250, "AB": 220, "H": 55, "HR": 8, "R": 30, "RBI": 28,
     "SB": 3, "SO": 60, "BB": 25, "AVG": 0.250, "OBP": 0.320, "SLG": 0.400, "OPS": 0.720},
]
ZIPS_HITTERS = [
    {"playerids": "1", "PlayerName": "Star Hitter", "Team": "NYY",
     "PA": 640, "AB": 580, "H": 174, "HR": 36, "R": 100, "RBI": 95,
     "SB": 18, "SO": 130, "BB": 55, "AVG": 0.300, "OBP": 0.365, "SLG": 0.540, "OPS": 0.905},
]
STEAMER_PITCHERS = [
    {"playerids": "10", "PlayerName": "Ace Starter", "Team": "LAD",
     "GS": 30, "G": 32, "W": 14, "L": 7, "IP": 190, "SO": 210,
     "BB": 50, "SV": 0, "HLD": 0, "ER": 65, "H": 155, "QS": 18,
     "ERA": 3.08, "WHIP": 1.08},
    {"playerids": "11", "PlayerName": "Shutdown Closer", "Team": "CLE",
     "GS": 0, "G": 65, "W": 4, "L": 2, "IP": 65, "SO": 80,
     "SV": 38, "HLD": 0, "ER": 15, "BB": 15, "H": 40, "QS": 0,
     "ERA": 2.08, "WHIP": 0.85},
]
ZIPS_PITCHERS = [
    {"playerids": "10", "PlayerName": "Ace Starter", "Team": "LAD",
     "GS": 30, "G": 32, "W": 12, "L": 8, "IP": 185, "SO": 200,
     "BB": 55, "SV": 0, "HLD": 0, "ER": 70, "H": 160, "QS": 16,
     "ERA": 3.41, "WHIP": 1.16},
]


class TestBlendHitters(unittest.TestCase):
    def test_matched_hitter_averages_counting_stats(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        self.assertAlmostEqual(star["stats"]["PA"], 630, places=0)
        self.assertAlmostEqual(star["stats"]["HR"], 34, places=0)

    def test_unmatched_hitter_uses_single_source(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        bench = next(p for p in result if p["name"] == "Bench Guy")
        self.assertAlmostEqual(bench["stats"]["PA"], 250, places=0)

    def test_hitter_has_correct_pool(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        for p in result:
            self.assertEqual(p["pool"], "hitter")

    def test_hitter_has_required_fields(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        for key in ("id", "name", "pool", "team", "stats", "metadata"):
            self.assertIn(key, star)

    def test_rate_stats_volume_weighted(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        self.assertAlmostEqual(star["stats"]["OPS"], 0.898, places=2)


class TestBlendPitchers(unittest.TestCase):
    def test_starter_has_correct_pool(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertEqual(ace["pool"], "starter")

    def test_closer_has_reliever_pool(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertEqual(closer["pool"], "reliever")

    def test_pitcher_has_derived_stats(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertIn("SV_HLD", closer["stats"])
        self.assertEqual(closer["stats"]["SV_HLD"], 38)
        self.assertIn("K_BB", closer["stats"])

    def test_pitcher_has_K_not_SO(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        for p in result:
            self.assertIn("K", p["stats"])
            self.assertNotIn("SO", p["stats"])

    def test_starter_positions(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertIn("SP", ace["positions"])

    def test_closer_positions(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertIn("RP", closer["positions"])

    def test_matched_pitcher_averages_counting(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertAlmostEqual(ace["stats"]["IP"], 187.5, places=1)
        self.assertAlmostEqual(ace["stats"]["K"], 205, places=0)


class TestBlendAll(unittest.TestCase):
    def test_blend_projections_returns_all_players(self):
        raw = {"steamer_hitters": STEAMER_HITTERS, "steamer_pitchers": STEAMER_PITCHERS,
               "zips_hitters": ZIPS_HITTERS, "zips_pitchers": ZIPS_PITCHERS}
        result = blend_projections(raw)
        names = {p["name"] for p in result}
        self.assertIn("Star Hitter", names)
        self.assertIn("Bench Guy", names)
        self.assertIn("Ace Starter", names)
        self.assertIn("Shutdown Closer", names)

    def test_blend_output_is_list_of_dicts(self):
        raw = {"steamer_hitters": STEAMER_HITTERS, "steamer_pitchers": STEAMER_PITCHERS,
               "zips_hitters": ZIPS_HITTERS, "zips_pitchers": ZIPS_PITCHERS}
        result = blend_projections(raw)
        self.assertIsInstance(result, list)
        for p in result:
            self.assertIsInstance(p, dict)


if __name__ == "__main__":
    unittest.main()
