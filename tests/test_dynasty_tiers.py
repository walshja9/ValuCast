import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import DYNASTY_ELITE_FLOOR, _compute_dynasty_tiers


def _row(pid, val):
    return SimpleNamespace(id=pid, dynasty_value=val)


class TestDynastyEliteTier(unittest.TestCase):
    # Fixtures are pinned to the served 0-100 dynasty value scale: the elite floor is
    # 95, so elites sit at 96/98/100 and the field below it. (The old 140/145/150
    # literals encoded the retired 0-150 scale, on which zero players ever cleared 140.)
    def test_small_elite_band_never_merges_down(self):
        # 3 elites (>=95) then a big cliff: elites must be tier 1 alone, never merged
        # into the group below by the min-3 rule.
        rows = [
            _row("a", 100.0), _row("b", 98.0), _row("c", 96.0),
            _row("d", 80.0), _row("e", 78.0), _row("f", 75.0), _row("g", 72.0),
        ]
        tiers = _compute_dynasty_tiers(rows)
        self.assertEqual({tiers["a"], tiers["b"], tiers["c"]}, {1})
        for pid in "defg":
            self.assertGreaterEqual(tiers[pid], 2, pid)

    def test_two_elites_stay_tier_one(self):
        # Even a 2-player elite band (below the min-3 floor) holds tier 1.
        rows = [_row("a", 100.0), _row("b", 96.0)] + [
            _row(f"r{i}", 85.0 - i) for i in range(6)
        ]
        tiers = _compute_dynasty_tiers(rows)
        self.assertEqual(tiers["a"], 1)
        self.assertEqual(tiers["b"], 1)
        for i in range(6):
            self.assertGreaterEqual(tiers[f"r{i}"], 2)

    def test_no_elites_gap_tiering_unchanged(self):
        # Prospect-scale values (max ~78, below the 95 floor): elite band empty,
        # gap tiering starts at 1.
        rows = [_row(f"p{i}", 78.0 - 3 * i) for i in range(12)]
        tiers = _compute_dynasty_tiers(rows)
        self.assertEqual(min(tiers.values()), 1)
        self.assertGreater(max(tiers.values()), 1)

    def test_elite_floor_is_live_on_the_served_scale(self):
        # Tripwire: a value at/above the floor must land in tier 1 via the elite branch
        # (not just gap tiering), so a stale floor can't silently go dead again.
        self.assertLessEqual(DYNASTY_ELITE_FLOOR, 100.0)
        rows = [_row("elite", DYNASTY_ELITE_FLOOR)] + [
            _row(f"p{i}", 80.0 - 2 * i) for i in range(8)
        ]
        tiers = _compute_dynasty_tiers(rows)
        self.assertEqual(tiers["elite"], 1)


if __name__ == "__main__":
    unittest.main()
