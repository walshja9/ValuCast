import unittest

from prospects.milb_translation import (
    best_single_level_stat_line,
    combined_season_stat_line,
    translate_peripherals,
)


class TestTranslatePeripherals(unittest.TestCase):
    def test_single_level_hitter_math(self):
        # AAA, 200 PA, k_pct 25 / bb_pct 12 / iso .200. shrink = 200/(200+200) = 0.5.
        rows = [{"role": "hitter", "season": 2026, "level": "AAA",
                 "plate_appearances": 200, "k_pct": 25.0, "bb_pct": 12.0, "iso": 0.200}]
        out = translate_peripherals(rows, "hitter")
        self.assertIsNotNone(out)
        self.assertEqual(out["level"], "AAA")
        self.assertEqual(out["level_label"], "AAA")
        self.assertEqual(out["sample"], 200)
        self.assertEqual(out["sample_unit"], "PA")
        self.assertFalse(out["low_sample"])
        self.assertEqual(out["confidence"], "high")  # AAA + 200 >= 120*1.5
        by_key = {s["key"]: s for s in out["stats"]}
        # k_pct: 22.0 + (25*1.08 - 22.0)*0.5 = 24.5 ; milb raw = 25.0
        self.assertAlmostEqual(by_key["k_pct"]["mlb"], 24.5, places=3)
        self.assertAlmostEqual(by_key["k_pct"]["milb"], 25.0, places=3)
        # bb_pct: 8.5 + (12*0.92 - 8.5)*0.5 = 9.77 -> 9.8
        self.assertAlmostEqual(by_key["bb_pct"]["mlb"], 9.8, places=3)
        # iso: 0.150 + (0.200*0.80 - 0.150)*0.5 = 0.155
        self.assertAlmostEqual(by_key["iso"]["mlb"], 0.155, places=3)
        self.assertEqual(by_key["iso"]["mlb_avg"], 0.150)

    def test_single_level_pitcher_math(self):
        # AA, 80 IP. shrink = 80/(80+50).
        rows = [{"role": "pitcher", "season": 2026, "level": "AA",
                 "innings_pitched": 80, "k_per_9": 10.0, "bb_per_9": 3.0, "k_bb_pct": 20.0}]
        out = translate_peripherals(rows, "pitcher")
        self.assertEqual(out["sample_unit"], "IP")
        self.assertEqual(out["confidence"], "moderate")  # AA, sample over floor but not AAA
        by_key = {s["key"]: s for s in out["stats"]}
        self.assertAlmostEqual(by_key["k_per_9"]["mlb"], 8.4, places=3)
        self.assertAlmostEqual(by_key["bb_per_9"]["mlb"], 3.3, places=3)
        self.assertAlmostEqual(by_key["k_bb_pct"]["mlb"], 14.1, places=3)

    def test_multi_level_blend_and_label(self):
        # Latest season spans AAA (50 PA) + AA (150 PA): PA-weighted blend, labels both.
        rows = [
            {"role": "hitter", "season": 2026, "level": "AAA", "plate_appearances": 50, "k_pct": 30.0},
            {"role": "hitter", "season": 2026, "level": "AA", "plate_appearances": 150, "k_pct": 20.0},
        ]
        out = translate_peripherals(rows, "hitter")
        self.assertEqual(out["level"], "AAA")          # top level by rank
        self.assertEqual(out["levels"], ["AAA", "AA"])
        self.assertEqual(out["level_label"], "AAA+AA")
        self.assertEqual(out["sample"], 200)
        by_key = {s["key"]: s for s in out["stats"]}
        # equiv = (30*1.08*50 + 20*1.15*150)/200 = 25.35 ; mlb = 22 + (25.35-22)*0.5 = 23.675
        self.assertAlmostEqual(by_key["k_pct"]["mlb"], 23.7, places=2)
        self.assertAlmostEqual(by_key["k_pct"]["milb"], 22.5, places=3)

    def test_low_sample_confidence(self):
        rows = [{"role": "hitter", "season": 2026, "level": "AA",
                 "plate_appearances": 40, "k_pct": 20.0}]
        out = translate_peripherals(rows, "hitter")
        self.assertTrue(out["low_sample"])             # 40 < floor 120
        self.assertEqual(out["confidence"], "low")

    def test_guards_return_none(self):
        self.assertIsNone(translate_peripherals([], "hitter"))
        self.assertIsNone(translate_peripherals([{"season": 2026}], "catcher"))
        self.assertIsNone(translate_peripherals(
            [{"role": "hitter", "season": 2026, "level": "AAA", "plate_appearances": 0}], "hitter"))
        # rows present but no translatable stat -> None
        self.assertIsNone(translate_peripherals(
            [{"role": "hitter", "season": 2026, "level": "AAA", "plate_appearances": 100}], "hitter"))


class TestBestSingleLevel(unittest.TestCase):
    def _aa_row(self):
        return {"role": "hitter", "season": 2026, "level": "AA", "pa": 250,
                "avg": 0.290, "obp": 0.360, "slg": 0.480, "ops": 0.840,
                "iso": 0.190, "k_pct": 20.0, "bb_pct": 9.0}

    def test_thin_current_returns_best_other_level(self):
        out = best_single_level_stat_line(
            current_line={"pa": 50}, current_level="AAA",
            history_rows=[self._aa_row()], role="hitter", season=2026)
        self.assertIsNotNone(out)
        self.assertEqual(out["level"], "AA")
        self.assertEqual(out["sample"], 250)
        self.assertEqual(out["sample_unit"], "PA")
        self.assertEqual(out["reason"], "current_level_too_thin_best_prior_level")
        self.assertAlmostEqual(out["ops"], 0.84, places=3)
        self.assertNotIn("pa", out)  # sample carried as `sample`, not the rate-line `pa`

    def test_current_clears_threshold_returns_none(self):
        out = best_single_level_stat_line(
            current_line={"pa": 150}, current_level="AAA",
            history_rows=[self._aa_row()], role="hitter", season=2026)
        self.assertIsNone(out)

    def test_no_qualifying_other_level_returns_none(self):
        thin_aa = {**self._aa_row(), "pa": 80}  # below the 100 PA threshold
        out = best_single_level_stat_line(
            current_line={"pa": 50}, current_level="AAA",
            history_rows=[thin_aa], role="hitter", season=2026)
        self.assertIsNone(out)

    def test_same_level_not_selected(self):
        # An other-season AA line must not qualify (wrong season).
        old = {**self._aa_row(), "season": 2025}
        out = best_single_level_stat_line(
            current_line={"pa": 50}, current_level="AAA",
            history_rows=[old], role="hitter", season=2026)
        self.assertIsNone(out)


class TestCombinedSeasonStatLine(unittest.TestCase):
    def test_hitter_combines_levels_with_full_metric_set(self):
        rows = [
            {
                "role": "hitter", "season": 2026, "level": "AAA",
                "plate_appearances": 80, "at_bats": 70, "hits": 21,
                "home_runs": 4, "stolen_bases": 2, "walks": 8,
                "avg": 0.300, "obp": 0.375, "slg": 0.520, "ops": 0.895,
                "iso": 0.220, "babip": 0.340, "k_pct": 18.0, "bb_pct": 10.0,
            },
            {
                "role": "hitter", "season": 2026, "level": "AA",
                "plate_appearances": 120, "at_bats": 105, "hits": 28,
                "home_runs": 5, "stolen_bases": 4, "walks": 12,
                "avg": 0.267, "obp": 0.342, "slg": 0.470, "ops": 0.812,
                "iso": 0.203, "babip": 0.310, "k_pct": 22.0, "bb_pct": 10.0,
            },
        ]

        out = combined_season_stat_line(rows, "hitter", 2026)

        self.assertIsNotNone(out)
        self.assertEqual(out["role"], "hitter")
        self.assertEqual(out["season"], 2026)
        self.assertEqual(out["level"], "AAA")
        self.assertEqual(out["levels"], ["AAA", "AA"])
        self.assertEqual(out["level_label"], "AAA+AA")
        self.assertEqual(out["sample"], 200)
        self.assertEqual(out["sample_unit"], "PA")
        self.assertEqual(out["pa"], 200)
        for key in ("avg", "obp", "slg", "ops", "iso", "babip", "k_pct", "bb_pct"):
            self.assertIn(key, out)
        for key in ("home_runs", "stolen_bases", "walks", "hits", "at_bats", "plate_appearances"):
            self.assertIn(key, out)
        self.assertEqual(out["home_runs"], 9)
        self.assertEqual(out["stolen_bases"], 6)
        self.assertEqual(out["walks"], 20)
        self.assertAlmostEqual(out["iso"], (0.220 * 80 + 0.203 * 120) / 200, places=3)
        self.assertAlmostEqual(out["babip"], (0.340 * 80 + 0.310 * 120) / 200, places=3)

    def test_pitcher_combines_levels_with_full_metric_set(self):
        rows = [
            {
                "role": "pitcher", "season": 2026, "level": "AA",
                "innings_pitched": 12.0, "strikeouts": 20, "walks": 5,
                "batters_faced": 50, "games_started": 2,
                "era": 2.25, "whip": 1.00, "k_per_9": 15.0,
                "bb_per_9": 3.75, "k_bb_pct": 30.0,
            },
            {
                "role": "pitcher", "season": 2026, "level": "A+",
                "innings_pitched": 18.0, "strikeouts": 18, "walks": 6,
                "batters_faced": 75, "games_started": 3,
                "era": 3.50, "whip": 1.20, "k_per_9": 9.0,
                "bb_per_9": 3.0, "k_bb_pct": 16.0,
            },
        ]

        out = combined_season_stat_line(rows, "pitcher", 2026)

        self.assertIsNotNone(out)
        self.assertEqual(out["level"], "AA")
        self.assertEqual(out["levels"], ["AA", "A+"])
        self.assertEqual(out["level_label"], "AA+A+")
        self.assertEqual(out["sample"], 30.0)
        self.assertEqual(out["sample_unit"], "IP")
        self.assertEqual(out["ip"], 30.0)
        for key in ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct"):
            self.assertIn(key, out)
        for key in ("strikeouts", "walks", "innings_pitched", "batters_faced", "games_started"):
            self.assertIn(key, out)
        self.assertEqual(out["strikeouts"], 38)
        self.assertEqual(out["walks"], 11)
        self.assertEqual(out["batters_faced"], 125)
        self.assertEqual(out["games_started"], 5)
        self.assertAlmostEqual(out["k_per_9"], (15.0 * 12 + 9.0 * 18) / 30, places=3)
        self.assertAlmostEqual(out["bb_per_9"], (3.75 * 12 + 3.0 * 18) / 30, places=3)


if __name__ == "__main__":
    unittest.main()
