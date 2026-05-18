import unittest

from league_values import (
    CategorySpec, Direction, LeagueConfig, PlayerPool, ScoringMode, ValuationEngine,
)
from league_values.models import RosterSettings
from league_values.post_processors import AgeCurve, PositionScarcity, ReplacementLevel
from league_values.presets import dd_7x7


class TestFullPipeline(unittest.TestCase):
    """End-to-end test: engine + all post-processors composed."""

    PLAYERS = [
        {
            "id": "trout", "name": "Mike Trout", "pool": "hitter",
            "positions": ["OF"],
            "stats": {"R": 90, "HR": 35, "RBI": 90, "SB": 15, "H": 160, "AB": 520, "OPS": 0.950, "AVG": 0.308, "SO": 130},
            "metadata": {"age": 34},
        },
        {
            "id": "soto", "name": "Juan Soto", "pool": "hitter",
            "positions": ["OF"],
            "stats": {"R": 100, "HR": 30, "RBI": 95, "SB": 5, "H": 155, "AB": 530, "OPS": 0.920, "AVG": 0.292, "SO": 110},
            "metadata": {"age": 27},
        },
        {
            "id": "witt", "name": "Bobby Witt Jr", "pool": "hitter",
            "positions": ["SS"],
            "stats": {"R": 105, "HR": 28, "RBI": 85, "SB": 35, "H": 180, "AB": 600, "OPS": 0.880, "AVG": 0.300, "SO": 100},
            "metadata": {"age": 25},
        },
        {
            "id": "burns", "name": "Corbin Burns", "pool": "pitcher",
            "positions": ["SP"],
            "stats": {"K": 210, "QS": 18, "SV_HLD": 0, "L": 6, "ER": 55, "IP": 195, "BB": 40, "H_ALLOWED": 155, "ERA": 2.54, "WHIP": 1.00, "K_BB": 5.25},
            "metadata": {"age": 31},
        },
        {
            "id": "clase", "name": "Emmanuel Clase", "pool": "pitcher",
            "positions": ["RP"],
            "stats": {"K": 65, "QS": 0, "SV_HLD": 38, "L": 3, "ER": 15, "IP": 65, "BB": 12, "H_ALLOWED": 42, "ERA": 2.08, "WHIP": 0.83, "K_BB": 5.42},
            "metadata": {"age": 28},
        },
        {
            "id": "bench", "name": "Bench Bat", "pool": "hitter",
            "positions": ["1B"],
            "stats": {"R": 40, "HR": 8, "RBI": 35, "SB": 2, "H": 75, "AB": 300, "OPS": 0.650, "AVG": 0.250, "SO": 80},
            "metadata": {"age": 32},
        },
    ]

    def test_raw_engine_only(self):
        config = dd_7x7()
        engine = ValuationEngine()
        results = engine.value_players(self.PLAYERS, config)
        self.assertEqual(len(results), 6)
        names = [r.name for r in results]
        self.assertLess(names.index("Bobby Witt Jr"), names.index("Bench Bat"))

    def test_full_pipeline_with_all_processors(self):
        config = dd_7x7()
        engine = ValuationEngine(post_processors=[
            ReplacementLevel(),
            PositionScarcity(multipliers={
                "C": 1.00, "3B": 1.10, "SS": 1.05, "2B": 1.05,
                "OF": 0.97, "1B": 0.90, "DH": 0.80, "UTIL": 0.80,
                "SP": 1.00, "RP": 0.55,
            }),
            AgeCurve(
                hitter_curve={
                    22: 1.65, 25: 1.42, 27: 1.25, 30: 0.97,
                    32: 0.87, 34: 0.77, 37: 0.48,
                },
                pitcher_curve={
                    22: 1.50, 25: 1.30, 27: 1.15, 30: 0.88,
                    32: 0.78, 34: 0.65, 37: 0.33,
                },
            ),
        ])
        results = engine.value_players(self.PLAYERS, config)
        self.assertEqual(len(results), 6)

        witt = next(r for r in results if r.name == "Bobby Witt Jr")
        bench = next(r for r in results if r.name == "Bench Bat")
        self.assertGreater(witt.total_value, bench.total_value)

        # In DD 7x7, Clase's SV_HLD (38) dominates despite the 0.55 RP scarcity
        # multiplier. Burns lands at replacement level (0.0) because his negative
        # raw z-scores (volume-adjusted WHIP/ERA against few pitchers) put him at
        # the floor, while Clase retains positive value from saves+holds.
        clase = next(r for r in results if r.name == "Emmanuel Clase")
        burns = next(r for r in results if r.name == "Corbin Burns")
        self.assertGreater(clase.total_value, burns.total_value)

        soto = next(r for r in results if r.name == "Juan Soto")
        trout = next(r for r in results if r.name == "Mike Trout")
        self.assertGreater(soto.total_value, trout.total_value)

    def test_to_dict_serialization(self):
        config = dd_7x7()
        engine = ValuationEngine()
        results = engine.value_players(self.PLAYERS, config)
        for r in results:
            d = r.to_dict()
            self.assertIn("total_value", d)
            self.assertIn("z_scores", d)
            self.assertIsInstance(d["z_scores"], dict)


if __name__ == "__main__":
    unittest.main()
