import unittest

from league_values import (
    CategorySpec, Direction, LeagueConfig, PlayerPool, ScoringMode, value_players,
)


class TestRotoSGP(unittest.TestCase):
    def test_roto_mode_ranks_by_sgp(self):
        league = LeagueConfig(
            name="Roto", scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
                CategorySpec(id="SB", label="SB", pool=PlayerPool.HITTER, stat="SB"),
            ),
        )
        players = [
            {"id": "power", "name": "Power", "pool": "hitter", "stats": {"HR": 40, "SB": 5}},
            {"id": "speed", "name": "Speed", "pool": "hitter", "stats": {"HR": 10, "SB": 40}},
            {"id": "balanced", "name": "Balanced", "pool": "hitter", "stats": {"HR": 25, "SB": 22}},
        ]
        results = value_players(players, league)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertIsNotNone(r.total_value)

    def test_roto_lower_is_better(self):
        league = LeagueConfig(
            name="Roto ERA", scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(
                    id="ERA", label="ERA", pool=PlayerPool.PITCHER,
                    numerator_stats=("ER",), denominator_stats=("IP",),
                    ratio_multiplier=9, direction=Direction.LOWER_IS_BETTER, baseline=4.00,
                ),
            ),
        )
        players = [
            {"id": "ace", "name": "Ace", "pool": "pitcher", "stats": {"ER": 50, "IP": 180}},
            {"id": "bad", "name": "Bad", "pool": "pitcher", "stats": {"ER": 90, "IP": 180}},
        ]
        results = value_players(players, league)
        self.assertEqual(results[0].name, "Ace")

    def test_roto_mixed_pools(self):
        league = LeagueConfig(
            name="Roto Mixed", scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
                CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),
            ),
        )
        players = [
            {"id": "h1", "name": "Hitter", "pool": "hitter", "stats": {"HR": 30}},
            {"id": "p1", "name": "Pitcher", "pool": "pitcher", "stats": {"K": 200}},
        ]
        results = value_players(players, league)
        self.assertEqual(len(results), 2)

    def test_roto_single_player_gets_zero(self):
        league = LeagueConfig(
            name="Roto Solo", scoring_mode=ScoringMode.ROTO,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        results = value_players(
            [{"id": "solo", "name": "Solo", "pool": "hitter", "stats": {"HR": 30}}],
            league,
        )
        self.assertEqual(results[0].total_value, 0.0)


if __name__ == "__main__":
    unittest.main()
