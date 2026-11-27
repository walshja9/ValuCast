import unittest

from web.config_builder import build_config, parse_list, build_url_params
from league_values.models import ScoringMode


class TestParseList(unittest.TestCase):
    def test_comma_separated(self):
        self.assertEqual(parse_list(["R,HR,RBI"]), ["R", "HR", "RBI"])

    def test_repeated_params(self):
        self.assertEqual(parse_list(["R", "HR", "RBI"]), ["R", "HR", "RBI"])

    def test_empty(self):
        self.assertEqual(parse_list([]), [])

    def test_single_value(self):
        self.assertEqual(parse_list(["R"]), ["R"])


class TestBuildConfig(unittest.TestCase):
    def test_categories_mode(self):
        config = build_config(
            mode="categories",
            cats=["R", "HR", "RBI", "SB", "AVG"],
            pcats=["W", "SV", "K", "ERA", "WHIP"],
        )
        self.assertEqual(config.scoring_mode, ScoringMode.CATEGORIES)
        self.assertEqual(len(config.categories), 10)

    def test_roto_mode(self):
        config = build_config(
            mode="roto",
            cats=["R", "HR"],
            pcats=["K", "ERA"],
        )
        self.assertEqual(config.scoring_mode, ScoringMode.ROTO)
        self.assertEqual(len(config.categories), 4)

    def test_points_mode_from_rules_string(self):
        config = build_config(
            mode="points",
            rules_str="HR:4,K:1,ER:-2",
        )
        self.assertEqual(config.scoring_mode, ScoringMode.POINTS)
        self.assertEqual(len(config.point_rules), 3)

    def test_points_mode_from_pt_params(self):
        config = build_config(
            mode="points",
            pt_params={"R": "1", "HR": "4", "K": "1", "ER": "-2"},
        )
        self.assertEqual(config.scoring_mode, ScoringMode.POINTS)
        self.assertEqual(len(config.point_rules), 4)

    def test_points_mode_default_preset(self):
        config = build_config(mode="points")
        self.assertEqual(config.scoring_mode, ScoringMode.POINTS)
        self.assertTrue(len(config.point_rules) > 0)

    def test_unknown_category_skipped(self):
        config = build_config(
            mode="categories",
            cats=["R", "FAKE"],
            pcats=["K"],
        )
        self.assertEqual(len(config.categories), 2)  # R + K

    def test_empty_cats_uses_defaults(self):
        config = build_config(mode="categories")
        self.assertEqual(len(config.categories), 10)  # Default 5x5


class TestBuildUrlParams(unittest.TestCase):
    def test_categories_url(self):
        params = build_url_params(
            mode="categories",
            cats=["R", "HR", "RBI", "SB", "AVG"],
            pcats=["W", "SV", "K", "ERA", "WHIP"],
        )
        # Default 5x5 config — should produce empty string
        self.assertEqual(params, "")

    def test_non_default_config_produces_url(self):
        params = build_url_params(
            mode="categories",
            cats=["R", "HR"],
            pcats=["K", "ERA"],
        )
        self.assertIn("cats=R%2CHR", params)

    def test_default_config_produces_minimal_url(self):
        params = build_url_params(mode="categories")
        self.assertEqual(params, "")

    def test_filters_included(self):
        params = build_url_params(
            mode="categories", pool="hitter", search="judge",
        )
        self.assertIn("pool=hitter", params)
        self.assertIn("search=judge", params)

    def test_points_mode_url(self):
        params = build_url_params(mode="points", rules_str="HR:4,K:1")
        self.assertIn("mode=points", params)
        self.assertIn("rules=HR%3A4%2CK%3A1", params)
