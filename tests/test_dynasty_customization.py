import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import _compute_dynasty_dollars, _compute_dynasty_tiers
from web.dynasty_models import DynastyRankingRow
from web.league_settings import LeagueSettings


def _row(i, value):
    return DynastyRankingRow(
        id=f"p{i}", name=f"Player {i}", player_type="mlb", positions=("OF",),
        team="NYY", age=27, dynasty_rank=i, dynasty_value=value,
        status="mlb", mlbam_id=None,
    )


class TestDynastyDollars(unittest.TestCase):
    def setUp(self):
        # 10 players, values 100, 90, ..., 10
        self.rows = [_row(i + 1, 100 - 10 * i) for i in range(10)]

    def test_budget_conserved(self):
        # 2 teams x 3 roster = 6 rostered; total budget 2 x 100 = 200
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        rostered = [dollars[f"p{i}"] for i in range(1, 7)]
        self.assertAlmostEqual(sum(rostered), 200.0, delta=0.5)

    def test_below_cutoff_is_zero(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        for i in range(7, 11):
            self.assertEqual(dollars[f"p{i}"], 0.0)

    def test_rostered_minimum_one_dollar(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        # p6 (value 50) sits AT the cutoff: value - replacement = 0, floor kicks in
        self.assertEqual(dollars["p6"], 1.0)

    def test_hand_computed_top_player(self):
        # replacement value = value at rank 6 = 50.
        # surplus: p1..p5 = 50,40,30,20,10 (sum 150). Budget above the $1 floors
        # = 200 - 6 = 194. p1 = 1 + 50/150 * 194 = 65.67
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        self.assertAlmostEqual(dollars["p1"], 65.7, delta=0.1)

    def test_league_size_moves_dollars(self):
        small = _compute_dynasty_dollars(self.rows, LeagueSettings(2, 100, 3, 0))
        deep = _compute_dynasty_dollars(self.rows, LeagueSettings(2, 100, 5, 0))
        # Deeper league -> more rostered players to share budget -> top player worth less
        self.assertLess(deep["p1"], small["p1"])

    def test_cutoff_beyond_pool_all_rostered(self):
        s = LeagueSettings(teams=12, budget=200, roster=26, pslots=0)  # cutoff 312 > 10 rows
        dollars = _compute_dynasty_dollars(self.rows, s)
        self.assertTrue(all(dollars[f"p{i}"] >= 1.0 for i in range(1, 11)))
        self.assertAlmostEqual(sum(dollars.values()), 12 * 200, delta=1.0)

    def test_unsorted_input_handled(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        expected = _compute_dynasty_dollars(self.rows, s)
        shuffled = list(reversed(self.rows))
        self.assertEqual(_compute_dynasty_dollars(shuffled, s), expected)


class TestTierPool(unittest.TestCase):
    def test_below_cutoff_rows_get_last_tier_not_zero(self):
        rows = [_row(i + 1, 150 - i) for i in range(30)]
        s = LeagueSettings(teams=2, budget=100, roster=10, pslots=0)  # cutoff 20
        from app import _dynasty_tiers_for
        tiers = _dynasty_tiers_for(rows, s)
        max_tier = max(tiers.values())
        for i in range(21, 31):
            self.assertEqual(tiers[f"p{i}"], max_tier)
        self.assertNotIn(0, tiers.values())


if __name__ == "__main__":
    unittest.main()
