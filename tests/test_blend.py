import os
import unittest
from unittest.mock import patch
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


class TestPitcherHAllowed(unittest.TestCase):
    def test_pitcher_stats_have_h_allowed_not_h(self):
        """Pitcher stats should rename H to H_ALLOWED for WHIP calculation."""
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        for p in result:
            self.assertIn("H_ALLOWED", p["stats"], f"{p['name']} missing H_ALLOWED")
            self.assertNotIn("H", p["stats"], f"{p['name']} still has H (should be H_ALLOWED)")

    def test_h_allowed_value_correct(self):
        """H_ALLOWED value should match the original H value."""
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertAlmostEqual(closer["stats"]["H_ALLOWED"], 40, places=0)


class TestBlendAll(unittest.TestCase):
    @patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"})
    def test_blend_projections_returns_all_players(self):
        raw = {"steamer_hitters": STEAMER_HITTERS, "steamer_pitchers": STEAMER_PITCHERS,
               "zips_hitters": ZIPS_HITTERS, "zips_pitchers": ZIPS_PITCHERS}
        result = blend_projections(raw)
        names = {p["name"] for p in result}
        self.assertIn("Star Hitter", names)
        self.assertIn("Bench Guy", names)
        self.assertIn("Ace Starter", names)
        self.assertIn("Shutdown Closer", names)

    @patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"})
    def test_blend_output_is_list_of_dicts(self):
        raw = {"steamer_hitters": STEAMER_HITTERS, "steamer_pitchers": STEAMER_PITCHERS,
               "zips_hitters": ZIPS_HITTERS, "zips_pitchers": ZIPS_PITCHERS}
        result = blend_projections(raw)
        self.assertIsInstance(result, list)
        for p in result:
            self.assertIsInstance(p, dict)


if __name__ == "__main__":
    unittest.main()

def _fg_hitter(i, hr=20, pa=600):
    return {"playerids": str(i), "PlayerName": f"H{i}", "HR": hr, "PA": pa, "minpos": "OF"}


def _fg_pitcher(i, ip=150):
    return {"playerids": str(i), "PlayerName": f"P{i}", "IP": ip, "GS": 20, "G": 25, "SO": 150}


def test_all_zero_projections_refuse_to_ship():
    # Upstream field rename (HR -> homeRuns): IDs survive, every stat reads 0.0
    # via _safe_float defaults, and the artifact would pass every date/non-empty
    # gate downstream. The blend must fail LOUD instead (7/2 audit).
    import pytest
    from scraper.blend import blend_projections
    zero = {
        "steamer_hitters": [_fg_hitter(i, hr=0, pa=0) for i in range(60)],
        "steamer_pitchers": [_fg_pitcher(i, ip=0) for i in range(60)],
    }
    with pytest.raises(RuntimeError, match="schema drift"):
        blend_projections(zero)


def test_healthy_projections_pass_the_zero_guard():
    from scraper.blend import blend_projections
    raw = {
        "steamer_hitters": [_fg_hitter(i) for i in range(60)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(60)],
    }
    with patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"}):
        assert len(blend_projections(raw)) == 120


def test_truncated_pool_refuses_to_ship():
    # Feed truncated to a couple hundred real hitters is still "live" (nonzero
    # PA/HR on every row), so _assert_not_all_zero passes cleanly -- only the
    # pool floor catches this.
    import pytest
    from scraper.blend import blend_projections
    truncated = {
        "steamer_hitters": [_fg_hitter(i) for i in range(100)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(3600)],
    }
    with pytest.raises(RuntimeError, match="below floor"):
        blend_projections(truncated)


def test_truncated_pool_escape_hatch_suppresses():
    from scraper.blend import blend_projections
    truncated = {
        "steamer_hitters": [_fg_hitter(i) for i in range(100)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(3600)],
    }
    with patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"}):
        assert len(blend_projections(truncated)) == 3700


def test_normal_shaped_pool_passes_the_floor():
    from scraper.blend import blend_projections
    raw = {
        "steamer_hitters": [_fg_hitter(i) for i in range(3000)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(3500)],
    }
    assert len(blend_projections(raw)) == 6500

