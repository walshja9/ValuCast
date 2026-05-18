import json
import tempfile
import unittest
from pathlib import Path

from league_values import (
    CategorySpec,
    Direction,
    LeagueConfig,
    PlayerPool,
    PlayerProjection,
    PointRule,
    ScoringMode,
    ValuationEngine,
    load_league_config,
    value_players,
)
from league_values.presets import standard_5x5, default_points


class TestCategoryRankings(unittest.TestCase):
    def test_category_configuration_changes_rankings(self):
        players = [
            {"id": "slugger", "name": "Slugger", "pool": "hitter", "stats": {"HR": 42, "SB": 5}},
            {"id": "runner", "name": "Runner", "pool": "hitter", "stats": {"HR": 12, "SB": 47}},
            {"id": "balanced", "name": "Balanced", "pool": "hitter", "stats": {"HR": 24, "SB": 20}},
        ]

        power_league = LeagueConfig(
            name="Power",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="Home Runs", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        speed_league = LeagueConfig(
            name="Speed",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="SB", label="Stolen Bases", pool=PlayerPool.HITTER, stat="SB"),
            ),
        )

        self.assertEqual(value_players(players, power_league)[0].name, "Slugger")
        self.assertEqual(value_players(players, speed_league)[0].name, "Runner")

    def test_weighted_categories_shift_rankings(self):
        players = [
            {"id": "hr", "name": "HR Guy", "pool": "hitter", "stats": {"HR": 40, "SB": 5}},
            {"id": "sb", "name": "SB Guy", "pool": "hitter", "stats": {"HR": 10, "SB": 40}},
        ]
        hr_heavy = LeagueConfig(
            name="HR heavy",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR", weight=3.0),
                CategorySpec(id="SB", label="SB", pool=PlayerPool.HITTER, stat="SB", weight=1.0),
            ),
        )
        results = value_players(players, hr_heavy)
        self.assertEqual(results[0].name, "HR Guy")

    def test_mixed_hitter_pitcher_pool(self):
        players = [
            {"id": "h1", "name": "Hitter", "pool": "hitter", "stats": {"HR": 30}},
            {"id": "p1", "name": "Pitcher", "pool": "pitcher", "stats": {"K": 200}},
        ]
        league = LeagueConfig(
            name="Mixed",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
                CategorySpec(id="K", label="K", pool=PlayerPool.PITCHER, stat="K"),
            ),
        )
        results = value_players(players, league)
        # Both should have values; non-applicable categories get z=0
        hitter = next(r for r in results if r.name == "Hitter")
        pitcher = next(r for r in results if r.name == "Pitcher")
        self.assertEqual(hitter.z_scores["K"], 0.0)
        self.assertEqual(pitcher.z_scores["HR"], 0.0)
        self.assertIsNone(hitter.raw_values["K"])
        self.assertIsNone(pitcher.raw_values["HR"])


class TestVolumeAdjustedRatios(unittest.TestCase):
    def test_average_category_is_volume_adjusted(self):
        league = LeagueConfig(
            name="AVG",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(
                    id="AVG", label="Average", pool=PlayerPool.HITTER,
                    numerator_stats=("H",), denominator_stats=("AB",), baseline=0.300,
                ),
            ),
        )
        players = [
            {"id": "small", "name": "Small Sample", "pool": "hitter", "stats": {"H": 35, "AB": 100}},
            {"id": "big", "name": "Volume Edge", "pool": "hitter", "stats": {"H": 192, "AB": 600}},
            {"id": "avg", "name": "Baseline", "pool": "hitter", "stats": {"H": 150, "AB": 500}},
        ]
        results = value_players(players, league)
        self.assertEqual(results[0].name, "Volume Edge")
        self.assertGreater(results[0].raw_values["AVG"], results[2].raw_values["AVG"])

    def test_lower_is_better_ratio_values_volume(self):
        league = LeagueConfig(
            name="ERA",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(
                    id="ERA", label="ERA", pool=PlayerPool.PITCHER,
                    numerator_stats=("ER",), denominator_stats=("IP",),
                    ratio_multiplier=9, direction=Direction.LOWER_IS_BETTER, baseline=4.00,
                ),
            ),
        )
        players = [
            {"id": "workhorse", "name": "Workhorse", "pool": "pitcher", "stats": {"ER": 60, "IP": 180}},
            {"id": "short", "name": "Short Burst", "pool": "pitcher", "stats": {"ER": 17, "IP": 60}},
            {"id": "baseline", "name": "Baseline Arm", "pool": "pitcher", "stats": {"ER": 80, "IP": 180}},
        ]
        self.assertEqual(value_players(players, league)[0].name, "Workhorse")

    def test_min_denominator_filters_small_samples(self):
        league = LeagueConfig(
            name="AVG min",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(
                    id="AVG", label="Average", pool=PlayerPool.HITTER,
                    numerator_stats=("H",), denominator_stats=("AB",),
                    baseline=0.260, min_denominator=50.0,
                ),
            ),
        )
        players = [
            {"id": "tiny", "name": "1-for-1", "pool": "hitter", "stats": {"H": 1, "AB": 1}},
            {"id": "real", "name": "Real Player", "pool": "hitter", "stats": {"H": 165, "AB": 550}},
        ]
        results = value_players(players, league)
        # 1-for-1 should get missing_value (0.0) impact, not a massive z-score
        tiny = next(r for r in results if r.name == "1-for-1")
        self.assertIsNone(tiny.raw_values["AVG"])
        self.assertEqual(results[0].name, "Real Player")

    def test_auto_baseline_computed_from_pool(self):
        """When no explicit baseline is set, the engine derives it from the player pool."""
        league = LeagueConfig(
            name="AVG auto",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(
                    id="AVG", label="Average", pool=PlayerPool.HITTER,
                    numerator_stats=("H",), denominator_stats=("AB",),
                ),
            ),
        )
        # All players have .300 AVG — auto baseline should be ~.300
        players = [
            {"id": "a", "name": "A", "pool": "hitter", "stats": {"H": 150, "AB": 500}},
            {"id": "b", "name": "B", "pool": "hitter", "stats": {"H": 180, "AB": 600}},
            {"id": "c", "name": "C", "pool": "hitter", "stats": {"H": 120, "AB": 400}},
        ]
        results = value_players(players, league)
        # All should have similar z-scores since they all hit .300
        for r in results:
            self.assertAlmostEqual(r.z_scores["AVG"], 0.0, places=5)


class TestPointsLeague(unittest.TestCase):
    def test_points_league_uses_point_rules(self):
        league = LeagueConfig(
            name="Points",
            scoring_mode=ScoringMode.POINTS,
            point_rules=(
                PointRule(stat="HR", points=4, pool=PlayerPool.HITTER),
                PointRule(stat="SB", points=2, pool=PlayerPool.HITTER),
                PointRule(stat="CS", points=-1, pool=PlayerPool.HITTER),
            ),
        )
        players = [
            {"id": "power", "name": "Power", "pool": "hitter", "stats": {"HR": 30, "SB": 2, "CS": 0}},
            {"id": "speed", "name": "Speed", "pool": "hitter", "stats": {"HR": 8, "SB": 45, "CS": 10}},
        ]
        results = value_players(players, league)
        self.assertEqual(results[0].name, "Power")
        self.assertEqual(results[0].points, 124)
        self.assertEqual(results[1].points, 112)

    def test_points_pool_filtering(self):
        """Pitcher point rules should not apply to hitters."""
        league = LeagueConfig(
            name="Points",
            scoring_mode=ScoringMode.POINTS,
            point_rules=(
                PointRule(stat="K", points=1, pool=PlayerPool.PITCHER),
                PointRule(stat="HR", points=4, pool=PlayerPool.HITTER),
            ),
        )
        hitter = {"id": "h", "name": "Hitter", "pool": "hitter", "stats": {"HR": 30, "K": 150}}
        results = value_players([hitter], league)
        # K rule is pitcher-only, so hitter's K shouldn't count
        self.assertEqual(results[0].points, 120.0)


class TestLeagueBaselines(unittest.TestCase):
    def test_fixed_baselines_override_pool_derived(self):
        league = LeagueConfig(
            name="Fixed",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
            league_baselines={"HR": (25.0, 10.0)},
        )
        players = [
            {"id": "a", "name": "Big HR", "pool": "hitter", "stats": {"HR": 45}},
            {"id": "b", "name": "Avg HR", "pool": "hitter", "stats": {"HR": 25}},
        ]
        results = value_players(players, league)
        big = next(r for r in results if r.name == "Big HR")
        avg = next(r for r in results if r.name == "Avg HR")
        # z = (45 - 25) / 10 = 2.0
        self.assertAlmostEqual(big.z_scores["HR"], 2.0, places=5)
        # z = (25 - 25) / 10 = 0.0
        self.assertAlmostEqual(avg.z_scores["HR"], 0.0, places=5)

    def test_fixed_baselines_from_dict(self):
        config = LeagueConfig.from_dict({
            "name": "Fixed",
            "scoring_mode": "categories",
            "categories": [{"id": "HR", "label": "HR", "pool": "hitter", "stat": "HR"}],
            "league_baselines": {"HR": [25.0, 10.0]},
        })
        self.assertEqual(config.league_baselines["HR"], (25.0, 10.0))


class TestEdgeCases(unittest.TestCase):
    def test_empty_player_list(self):
        league = LeagueConfig(
            name="Empty",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        results = value_players([], league)
        self.assertEqual(results, [])

    def test_single_player_gets_zero_zscore(self):
        """With one player, stddev=0, so z-score should be 0."""
        league = LeagueConfig(
            name="Solo",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        results = value_players(
            [{"id": "solo", "name": "Solo", "pool": "hitter", "stats": {"HR": 30}}],
            league,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].z_scores["HR"], 0.0)

    def test_identical_players_get_zero_zscores(self):
        """All players with identical stats should all get z=0."""
        league = LeagueConfig(
            name="Clones",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": f"p{i}", "name": f"Clone {i}", "pool": "hitter", "stats": {"HR": 25}}
            for i in range(5)
        ]
        results = value_players(players, league)
        for r in results:
            self.assertEqual(r.z_scores["HR"], 0.0)

    def test_missing_stat_gets_zero(self):
        """Player missing a stat key should get 0.0 for that category, not error."""
        league = LeagueConfig(
            name="Missing",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": "has", "name": "Has HR", "pool": "hitter", "stats": {"HR": 30}},
            {"id": "missing", "name": "No HR Key", "pool": "hitter", "stats": {"SB": 40}},
        ]
        results = value_players(players, league)
        self.assertEqual(len(results), 2)

    def test_player_in_wrong_pool_excluded_from_category(self):
        """A pitcher should not contribute to hitter-only categories."""
        league = LeagueConfig(
            name="Pool",
            scoring_mode=ScoringMode.CATEGORIES,
            categories=(
                CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),
            ),
        )
        players = [
            {"id": "h", "name": "Hitter", "pool": "hitter", "stats": {"HR": 20}},
            {"id": "p", "name": "Pitcher", "pool": "pitcher", "stats": {"HR": 0}},
        ]
        results = value_players(players, league)
        pitcher = next(r for r in results if r.name == "Pitcher")
        self.assertIsNone(pitcher.raw_values["HR"])
        self.assertEqual(pitcher.z_scores["HR"], 0.0)


class TestConfigLoading(unittest.TestCase):
    def test_league_config_from_dict(self):
        config = LeagueConfig.from_dict({
            "name": "OBP power",
            "scoring_mode": "categories",
            "categories": [
                {"id": "HR", "label": "Home Runs", "pool": "hitter", "stat": "HR", "weight": 2},
                {
                    "id": "OBP", "label": "On Base Percentage", "pool": "hitter",
                    "numerator_stats": ["H", "BB"],
                    "denominator_stats": ["AB", "BB"],
                },
            ],
        })
        self.assertEqual(config.name, "OBP power")
        self.assertEqual(config.categories[0].weight, 2)
        self.assertEqual(config.categories[1].id, "OBP")

    def test_load_league_config_from_json_file(self):
        data = {
            "name": "Test League",
            "scoring_mode": "categories",
            "categories": [
                {"id": "HR", "label": "HR", "pool": "hitter", "stat": "HR"},
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            f.flush()
            config = load_league_config(f.name)
        self.assertEqual(config.name, "Test League")
        self.assertEqual(len(config.categories), 1)

    def test_invalid_config_raises(self):
        with self.assertRaises(ValueError):
            LeagueConfig(name="Bad", scoring_mode=ScoringMode.CATEGORIES, categories=())
        with self.assertRaises(ValueError):
            LeagueConfig(name="Bad", scoring_mode=ScoringMode.POINTS, point_rules=())
        with self.assertRaises(ValueError):
            CategorySpec(id="X", label="X", pool=PlayerPool.HITTER, weight=-1)
        with self.assertRaises(ValueError):
            CategorySpec(id="X", label="X", pool=PlayerPool.HITTER, ratio_multiplier=0)


class TestPresets(unittest.TestCase):
    def test_standard_5x5_loads(self):
        config = standard_5x5()
        self.assertEqual(config.name, "Standard 5x5")
        self.assertEqual(config.scoring_mode, ScoringMode.CATEGORIES)
        self.assertEqual(len(config.categories), 10)
        ids = {c.id for c in config.categories}
        self.assertEqual(ids, {"R", "HR", "RBI", "SB", "AVG", "W", "SV", "K", "ERA", "WHIP"})

    def test_default_points_loads(self):
        config = default_points()
        self.assertEqual(config.name, "Default points")
        self.assertEqual(config.scoring_mode, ScoringMode.POINTS)
        self.assertGreater(len(config.point_rules), 0)

    def test_5x5_min_denominators_set(self):
        config = standard_5x5()
        avg = next(c for c in config.categories if c.id == "AVG")
        era = next(c for c in config.categories if c.id == "ERA")
        whip = next(c for c in config.categories if c.id == "WHIP")
        self.assertGreater(avg.min_denominator, 0)
        self.assertGreater(era.min_denominator, 0)
        self.assertGreater(whip.min_denominator, 0)

    def test_5x5_preset_produces_results(self):
        config = standard_5x5()
        players = [
            {
                "id": "h1", "name": "Hitter", "pool": "hitter",
                "stats": {"R": 80, "HR": 25, "RBI": 80, "SB": 10, "H": 150, "AB": 550},
            },
            {
                "id": "p1", "name": "Pitcher", "pool": "pitcher",
                "stats": {"W": 12, "SV": 0, "K": 180, "ER": 60, "IP": 180, "BB": 45, "H_ALLOWED": 150},
            },
        ]
        results = value_players(players, config)
        self.assertEqual(len(results), 2)


class TestValuationResult(unittest.TestCase):
    def test_to_dict(self):
        player = PlayerProjection(id="1", name="Test", pool=PlayerPool.HITTER, stats={"HR": 30})
        result = ValuationEngine().value_players(
            [player],
            LeagueConfig(
                name="T", scoring_mode=ScoringMode.CATEGORIES,
                categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),),
            ),
        )[0]
        d = result.to_dict()
        self.assertEqual(d["id"], "1")
        self.assertEqual(d["name"], "Test")
        self.assertEqual(d["pool"], "hitter")
        self.assertIn("total_value", d)
        self.assertIn("z_scores", d)


class TestValuationEngineClass(unittest.TestCase):
    def test_class_and_module_function_give_same_results(self):
        league = LeagueConfig(
            name="T", scoring_mode=ScoringMode.CATEGORIES,
            categories=(CategorySpec(id="HR", label="HR", pool=PlayerPool.HITTER, stat="HR"),),
        )
        players = [
            {"id": "a", "name": "A", "pool": "hitter", "stats": {"HR": 30}},
            {"id": "b", "name": "B", "pool": "hitter", "stats": {"HR": 15}},
        ]
        class_results = ValuationEngine().value_players(players, league)
        func_results = value_players(players, league)
        for cr, fr in zip(class_results, func_results):
            self.assertEqual(cr.name, fr.name)
            self.assertAlmostEqual(cr.total_value, fr.total_value)


if __name__ == "__main__":
    unittest.main()
