import unittest

from web.category_registry import (
    HITTING_CATEGORIES,
    PITCHING_CATEGORIES,
    CATEGORY_PRESETS,
    POINTS_PRESETS,
    get_categories,
    get_point_rules,
)
from league_values.models import Direction, PlayerPool


class TestHittingCategories(unittest.TestCase):
    def test_all_hitting_ids_present(self):
        ids = [c.id for c in HITTING_CATEGORIES]
        for expected in ["R", "HR", "RBI", "SB", "AVG", "OBP", "OPS", "SLG", "H", "BB", "SO", "TB", "NSB"]:
            self.assertIn(expected, ids)

    def test_avg_is_ratio(self):
        avg = next(c for c in HITTING_CATEGORIES if c.id == "AVG")
        self.assertTrue(avg.is_ratio)
        self.assertEqual(avg.numerator_stats, ("H",))
        self.assertEqual(avg.denominator_stats, ("AB",))

    def test_so_is_lower_is_better(self):
        so = next(c for c in HITTING_CATEGORIES if c.id == "SO")
        self.assertEqual(so.direction, Direction.LOWER_IS_BETTER)

    def test_hitter_strikeout_label_is_unambiguous(self):
        so = next(c for c in HITTING_CATEGORIES if c.id == "SO")
        self.assertEqual(so.label, "Strikeouts (batter)")

    def test_all_hitting_cats_are_hitter_pool(self):
        for cat in HITTING_CATEGORIES:
            self.assertEqual(cat.pool, PlayerPool.HITTER, f"{cat.id} has wrong pool")


class TestPitchingCategories(unittest.TestCase):
    def test_all_pitching_ids_present(self):
        ids = [c.id for c in PITCHING_CATEGORIES]
        for expected in ["W", "L", "K", "QS", "SV", "HLD", "SV_HLD", "ERA", "WHIP", "K_BB", "IP", "K_9", "BB_9"]:
            self.assertIn(expected, ids)

    def test_era_is_ratio_lower_is_better(self):
        era = next(c for c in PITCHING_CATEGORIES if c.id == "ERA")
        self.assertTrue(era.is_ratio)
        self.assertEqual(era.direction, Direction.LOWER_IS_BETTER)
        self.assertEqual(era.ratio_multiplier, 9.0)

    def test_all_pitching_cats_are_pitcher_pool(self):
        for cat in PITCHING_CATEGORIES:
            self.assertEqual(cat.pool, PlayerPool.PITCHER, f"{cat.id} has wrong pool")

    def test_pitcher_strikeout_label_is_unambiguous(self):
        strikeouts = next(c for c in PITCHING_CATEGORIES if c.id == "K")
        self.assertEqual(strikeouts.label, "Strikeouts (pitcher)")


class TestPresets(unittest.TestCase):
    def test_5x5_preset(self):
        preset = CATEGORY_PRESETS["5x5"]
        self.assertEqual(set(preset["cats"]), {"R", "HR", "RBI", "SB", "AVG"})
        self.assertEqual(set(preset["pcats"]), {"W", "SV", "K", "ERA", "WHIP"})

    def test_6x6_preset(self):
        preset = CATEGORY_PRESETS["6x6"]
        self.assertIn("OBP", preset["cats"])
        self.assertIn("QS", preset["pcats"])

    def test_default_points_preset(self):
        rules = POINTS_PRESETS["default"]
        self.assertTrue(any(r.stat == "HR" and r.points == 4.0 for r in rules))
        self.assertTrue(any(r.stat == "K" and r.pool == PlayerPool.PITCHER for r in rules))


class TestLookup(unittest.TestCase):
    def test_get_categories_by_ids(self):
        cats = get_categories(["R", "HR", "ERA"])
        self.assertEqual(len(cats), 3)
        self.assertEqual({c.id for c in cats}, {"R", "HR", "ERA"})

    def test_get_categories_skips_unknown(self):
        cats = get_categories(["R", "UNKNOWN"])
        self.assertEqual(len(cats), 1)

    def test_get_categories_empty(self):
        cats = get_categories([])
        self.assertEqual(len(cats), 0)

    def test_get_point_rules_from_string(self):
        rules = get_point_rules("HR:4,K:1,ER:-2")
        self.assertEqual(len(rules), 3)
        hr = next(r for r in rules if r.stat == "HR")
        self.assertEqual(hr.points, 4.0)

    def test_get_point_rules_empty_string(self):
        rules = get_point_rules("")
        self.assertEqual(len(rules), 0)
