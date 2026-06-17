"""Best-single-level consumer: card line selection + percentile pool rules.

Regression cases (per the 2026-06-17 best-single-level spec):
  1. current level clears threshold -> use current level line
  2. current thin + best_single_level_stat_line present -> use best, labeled with its level
  3. neither -> no line (preserves the "too small" fallback)
  4. never use translated rates for the raw percentile pool
"""
import unittest
from types import SimpleNamespace

from web.prospect_percentiles import build_pool, card_line, card_percentiles, pool_label


def _row(stat_line=None, best=None, positions=("OF",), is_prospect=True, translated=None):
    return SimpleNamespace(
        is_prospect=is_prospect,
        stat_line=stat_line,
        best_single_level_stat_line=best,
        positions=list(positions),
        stat_line_translated=translated,
    )


def _hitter_line(pa, scale=1.0):
    return {
        "pa": pa, "avg": 0.260 * scale, "obp": 0.330 * scale, "slg": 0.430 * scale,
        "ops": 0.760 * scale, "iso": 0.170 * scale, "k_pct": 20.0, "bb_pct": 9.0,
    }


class TestBestSingleConsumer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A raw "all levels" pool of current-eligible hitters (PA >= 100).
        cls.pool = build_pool([_row(stat_line=_hitter_line(300, 1.0 + 0.03 * i)) for i in range(6)])

    def test_current_clears_uses_current_line(self):
        r = _row(stat_line=_hitter_line(200, 1.15))
        line, level, is_best = card_line(r)
        self.assertIs(line, r.stat_line)
        self.assertIsNone(level)
        self.assertFalse(is_best)
        self.assertTrue(card_percentiles(self.pool, r))            # percentiles from current line
        self.assertNotIn("best", pool_label(r))

    def test_thin_current_uses_best_labeled(self):
        best = {"level": "AA", "sample": 250, "reason": "current_level_too_thin_best_prior_level",
                "avg": 0.300, "obp": 0.380, "slg": 0.520, "ops": 0.900, "iso": 0.220,
                "k_pct": 17.0, "bb_pct": 11.0}
        r = _row(stat_line=_hitter_line(50), best=best)
        line, level, is_best = card_line(r)
        self.assertIs(line, best)
        self.assertEqual(level, "AA")
        self.assertTrue(is_best)
        self.assertTrue(card_percentiles(self.pool, r))            # percentiles come from the best line
        self.assertIn("best AA read", pool_label(r))

    def test_neither_returns_none_and_empty_percentiles(self):
        r = _row(stat_line=_hitter_line(50), best=None)
        line, level, is_best = card_line(r)
        self.assertIsNone(line)
        self.assertFalse(is_best)
        self.assertEqual(card_percentiles(self.pool, r), {})        # preserves "too small" fallback

    def test_thin_best_below_threshold_not_used(self):
        thin_best = {"level": "AA", "sample": 80, "avg": 0.3, "obp": 0.38, "slg": 0.52,
                     "ops": 0.9, "iso": 0.22, "k_pct": 17.0, "bb_pct": 11.0}
        r = _row(stat_line=_hitter_line(50), best=thin_best)
        self.assertIsNone(card_line(r)[0])

    def test_never_uses_translated_for_pool(self):
        # Thin current, no best, but a translated panel exists -> percentiles stay empty
        # (the translated rates must never feed the raw pool).
        r = _row(stat_line=_hitter_line(50), best=None,
                 translated={"stats": [{"key": "k_pct", "mlb": 18.0}]})
        self.assertEqual(card_percentiles(self.pool, r), {})

    def test_non_prospect_returns_none(self):
        r = _row(stat_line=_hitter_line(300), is_prospect=False)
        self.assertIsNone(card_line(r)[0])


if __name__ == "__main__":
    unittest.main()
