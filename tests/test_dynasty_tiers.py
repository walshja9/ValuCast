import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import _compute_dynasty_tiers


def _row(pid, val):
    return SimpleNamespace(id=pid, dynasty_value=val)


class TestDynastyEliteTier(unittest.TestCase):
    def test_small_elite_band_never_merges_down(self):
        # 3 elites (>=140) then a 16-point cliff: elites must be tier 1 alone,
        # never merged into the 120s group by the min-3 rule.
        rows = [
            _row("a", 148.0), _row("b", 145.7), _row("c", 145.0),
            _row("d", 129.0), _row("e", 127.0), _row("f", 124.0), _row("g", 121.0),
        ]
        tiers = _compute_dynasty_tiers(rows)
        self.assertEqual({tiers["a"], tiers["b"], tiers["c"]}, {1})
        for pid in "defg":
            self.assertGreaterEqual(tiers[pid], 2, pid)

    def test_two_elites_stay_tier_one(self):
        # Even a 2-player elite band (below the min-3 floor) holds tier 1.
        rows = [_row("a", 150.0), _row("b", 145.0)] + [
            _row(f"r{i}", 130.0 - i) for i in range(6)
        ]
        tiers = _compute_dynasty_tiers(rows)
        self.assertEqual(tiers["a"], 1)
        self.assertEqual(tiers["b"], 1)
        for i in range(6):
            self.assertGreaterEqual(tiers[f"r{i}"], 2)

    def test_no_elites_gap_tiering_unchanged(self):
        # Prospect-scale values (max ~78): elite band empty, tiers start at 1.
        rows = [_row(f"p{i}", 78.0 - 3 * i) for i in range(12)]
        tiers = _compute_dynasty_tiers(rows)
        self.assertEqual(min(tiers.values()), 1)
        self.assertGreater(max(tiers.values()), 1)


if __name__ == "__main__":
    unittest.main()
