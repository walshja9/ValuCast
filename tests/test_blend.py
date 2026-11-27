import os
import unittest
from unittest.mock import patch
from scraper.blend import (
    HITTER_COUNTING, HITTER_RATE, PITCHER_COUNTING, PITCHER_RATE,
    blend_projections, blend_hitters, blend_pitchers,
)


def _complete_hitter(row):
    return {**dict.fromkeys(HITTER_COUNTING + HITTER_RATE, 0.0), **row}


def _complete_pitcher(row):
    return {**dict.fromkeys(PITCHER_COUNTING + PITCHER_RATE, 0.0), **row}

STEAMER_HITTERS = [
    {"playerids": "1", "PlayerName": "Star Hitter", "Team": "NYY",
     "PA": 620, "AB": 560, "H": 168, "HR": 32, "R": 95, "RBI": 90,
     "SB": 15, "SO": 120, "BB": 55, "AVG": 0.300, "OBP": 0.370, "SLG": 0.520, "OPS": 0.890},
    {"playerids": "2", "PlayerName": "Bench Guy", "Team": "BOS",
     "PA": 250, "AB": 220, "H": 55, "HR": 8, "R": 30, "RBI": 28,
     "SB": 3, "SO": 60, "BB": 25, "AVG": 0.250, "OBP": 0.320, "SLG": 0.400, "OPS": 0.720},
]
ZIPS_HITTERS = [
    {"playerids": "1", "PlayerName": "Star Hitter", "Team": "NYY",
     "PA": 640, "AB": 580, "H": 174, "HR": 36, "R": 100, "RBI": 95,
     "SB": 18, "SO": 130, "BB": 55, "AVG": 0.300, "OBP": 0.365, "SLG": 0.540, "OPS": 0.905},
]
STEAMER_PITCHERS = [
    {"playerids": "10", "PlayerName": "Ace Starter", "Team": "LAD",
     "GS": 30, "G": 32, "W": 14, "L": 7, "IP": 190, "SO": 210,
     "BB": 50, "SV": 0, "HLD": 0, "ER": 65, "H": 155, "QS": 18,
     "ERA": 3.08, "WHIP": 1.08},
    {"playerids": "11", "PlayerName": "Shutdown Closer", "Team": "CLE",
     "GS": 0, "G": 65, "W": 4, "L": 2, "IP": 65, "SO": 80,
     "SV": 38, "HLD": 0, "ER": 15, "BB": 15, "H": 40, "QS": 0,
     "ERA": 2.08, "WHIP": 0.85},
]
ZIPS_PITCHERS = [
    {"playerids": "10", "PlayerName": "Ace Starter", "Team": "LAD",
     "GS": 30, "G": 32, "W": 12, "L": 8, "IP": 185, "SO": 200,
     "BB": 55, "SV": 0, "HLD": 0, "ER": 70, "H": 160, "QS": 16,
     "ERA": 3.41, "WHIP": 1.16},
]


class TestBlendHitters(unittest.TestCase):
    def test_matched_hitter_averages_counting_stats(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        self.assertAlmostEqual(star["stats"]["PA"], 630, places=0)
        self.assertAlmostEqual(star["stats"]["HR"], 34, places=0)

    def test_unmatched_hitter_uses_single_source(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        bench = next(p for p in result if p["name"] == "Bench Guy")
        self.assertAlmostEqual(bench["stats"]["PA"], 250, places=0)

    def test_hitter_has_correct_pool(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        for p in result:
            self.assertEqual(p["pool"], "hitter")

    def test_hitter_has_required_fields(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        for key in ("id", "name", "pool", "team", "stats", "metadata"):
            self.assertIn(key, star)

    def test_rate_stats_volume_weighted(self):
        result = blend_hitters(STEAMER_HITTERS, ZIPS_HITTERS)
        star = next(p for p in result if p["name"] == "Star Hitter")
        self.assertAlmostEqual(star["stats"]["OPS"], 0.898, places=2)


class TestBlendPitchers(unittest.TestCase):
    def test_zero_starts_without_saves_or_holds_is_reliever(self):
        missing = {"playerids": "12", "IP": 50, "SV": 0, "HLD": 0}
        zero = {**missing, "GS": 0}
        for steamer, zips in (([zero], []), ([], [zero]), ([zero], [zero]),
                              ([missing], [zero]), ([zero], [missing])):
            with self.subTest(steamer=steamer, zips=zips):
                pitcher = blend_pitchers(steamer, zips)[0]
                self.assertEqual(pitcher["pool"], "reliever")
                self.assertEqual(pitcher["positions"], ["RP"])

    def test_absent_starts_keep_starter_default(self):
        pitcher = {"playerids": "12", "IP": 50, "SV": 0, "HLD": 0}
        for steamer, zips in (([pitcher], []), ([], [pitcher]), ([pitcher], [pitcher])):
            with self.subTest(steamer=steamer, zips=zips):
                row = blend_pitchers(steamer, zips)[0]
                self.assertEqual(row["pool"], "starter")
                self.assertEqual(row["positions"], ["SP"])

    def test_fractional_starts_keep_starter_pool_and_position(self):
        pitcher = {"playerids": "12", "IP": 50, "GS": 0.5, "SV": 0, "HLD": 0}
        for steamer, zips in (([pitcher], []), ([], [pitcher]), ([pitcher], [pitcher])):
            with self.subTest(steamer=steamer, zips=zips):
                row = blend_pitchers(steamer, zips)[0]
                self.assertEqual(row["pool"], "starter")
                self.assertEqual(row["positions"], ["SP"])

    def test_starter_has_correct_pool(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertEqual(ace["pool"], "starter")

    def test_closer_has_reliever_pool(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertEqual(closer["pool"], "reliever")

    def test_pitcher_has_derived_stats(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertIn("SV_HLD", closer["stats"])
        self.assertEqual(closer["stats"]["SV_HLD"], 38)
        self.assertIn("K_BB", closer["stats"])

    def test_pitcher_has_K_not_SO(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        for p in result:
            self.assertIn("K", p["stats"])
            self.assertNotIn("SO", p["stats"])

    def test_starter_positions(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertIn("SP", ace["positions"])

    def test_closer_positions(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertIn("RP", closer["positions"])

    def test_matched_pitcher_averages_counting(self):
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        ace = next(p for p in result if p["name"] == "Ace Starter")
        self.assertAlmostEqual(ace["stats"]["IP"], 187.5, places=1)
        self.assertAlmostEqual(ace["stats"]["K"], 205, places=0)


class TestPitcherHAllowed(unittest.TestCase):
    def test_pitcher_stats_have_h_allowed_not_h(self):
        """Pitcher stats should rename H to H_ALLOWED for WHIP calculation."""
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        for p in result:
            self.assertIn("H_ALLOWED", p["stats"], f"{p['name']} missing H_ALLOWED")
            self.assertNotIn("H", p["stats"], f"{p['name']} still has H (should be H_ALLOWED)")

    def test_h_allowed_value_correct(self):
        """H_ALLOWED value should match the original H value."""
        result = blend_pitchers(STEAMER_PITCHERS, ZIPS_PITCHERS)
        closer = next(p for p in result if p["name"] == "Shutdown Closer")
        self.assertAlmostEqual(closer["stats"]["H_ALLOWED"], 40, places=0)


class TestBlendAll(unittest.TestCase):
    @patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"})
    def test_blend_projections_returns_all_players(self):
        raw = {"steamer_hitters": [_complete_hitter(row) for row in STEAMER_HITTERS],
               "steamer_pitchers": [_complete_pitcher(row) for row in STEAMER_PITCHERS],
               "zips_hitters": [_complete_hitter(row) for row in ZIPS_HITTERS],
               "zips_pitchers": [_complete_pitcher(row) for row in ZIPS_PITCHERS]}
        result = blend_projections(raw)
        names = {p["name"] for p in result}
        self.assertIn("Star Hitter", names)
        self.assertIn("Bench Guy", names)
        self.assertIn("Ace Starter", names)
        self.assertIn("Shutdown Closer", names)

    @patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"})
    def test_blend_output_is_list_of_dicts(self):
        raw = {"steamer_hitters": [_complete_hitter(row) for row in STEAMER_HITTERS],
               "steamer_pitchers": [_complete_pitcher(row) for row in STEAMER_PITCHERS],
               "zips_hitters": [_complete_hitter(row) for row in ZIPS_HITTERS],
               "zips_pitchers": [_complete_pitcher(row) for row in ZIPS_PITCHERS]}
        result = blend_projections(raw)
        self.assertIsInstance(result, list)
        for p in result:
            self.assertIsInstance(p, dict)


if __name__ == "__main__":
    unittest.main()

def _fg_hitter(i, hr=20, pa=600):
    return _complete_hitter({"playerids": str(i), "PlayerName": f"H{i}", "HR": hr, "PA": pa, "minpos": "OF"})


def _fg_pitcher(i, ip=150):
    return _complete_pitcher({"playerids": str(i), "PlayerName": f"P{i}", "IP": ip, "GS": 20, "G": 25, "SO": 150})


@patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"})
class TestProjectionSourceContract(unittest.TestCase):
    def raw(self):
        return {"steamer_hitters": [_fg_hitter("shared")],
                "steamer_pitchers": [_fg_pitcher("shared")]}

    def test_source_lists_and_rows_have_expected_shape(self):
        for rows in (None, {"unexpected": "object"}, [None], [1]):
            raw = self.raw()
            raw["steamer_hitters"] = rows
            with self.subTest(rows_type=type(rows).__name__), self.assertRaisesRegex(RuntimeError, "steamer_hitters"):
                blend_projections(raw)

    def test_missing_hitter_hits_fail_before_zero_filling(self):
        for source in ("steamer_hitters", "zips_hitters"):
            raw = self.raw()
            raw[source] = [_fg_hitter("shared")]
            del raw[source][0]["H"]
            with self.subTest(source=source), self.assertRaisesRegex(RuntimeError, source + r".*\bH\b"):
                blend_projections(raw)

    def test_missing_pitcher_earned_runs_fail_before_zero_filling(self):
        for source in ("steamer_pitchers", "zips_pitchers"):
            raw = self.raw()
            raw[source] = [_fg_pitcher("shared")]
            del raw[source][0]["ER"]
            with self.subTest(source=source), self.assertRaisesRegex(RuntimeError, source + r".*\bER\b"):
                blend_projections(raw)

    def test_null_and_invalid_required_components_are_rejected(self):
        for source, field in (("steamer_hitters", "H"), ("steamer_pitchers", "WHIP")):
            for value in (None, float("nan"), float("inf"), -float("inf"), "invalid", True):
                raw = self.raw()
                raw[source][0][field] = value
                with self.subTest(source=source, field=field), self.assertRaisesRegex(RuntimeError, source + ".*" + field):
                    blend_projections(raw)

    def test_volume_is_always_required_and_finite(self):
        for source, field in (("steamer_hitters", "PA"), ("steamer_pitchers", "IP")):
            for value in (None, float("nan"), float("inf"), -float("inf"), "invalid", False):
                raw = self.raw()
                raw[source][0][field] = value
                with self.subTest(source=source), self.assertRaisesRegex(RuntimeError, source + ".*" + field):
                    blend_projections(raw)
            raw = self.raw()
            del raw[source][0][field]
            with self.assertRaisesRegex(RuntimeError, source + ".*" + field):
                blend_projections(raw)

    def test_negative_plate_appearances_and_innings_are_rejected(self):
        for source, field in (("steamer_hitters", "PA"), ("steamer_pitchers", "IP")):
            for value in (-1.0, "-1"):
                raw = self.raw()
                raw[source][0][field] = value
                with self.subTest(source=source), self.assertRaisesRegex(RuntimeError, source + ".*" + field):
                    blend_projections(raw)

    def test_source_identities_must_be_usable(self):
        for value in (None, "", " ", False, True, 0, [], {}, float("nan"), float("inf")):
            raw = self.raw()
            raw["steamer_hitters"][0]["playerids"] = value
            with self.subTest(identity_type=type(value).__name__), self.assertRaisesRegex(RuntimeError, "steamer_hitters.*playerids"):
                blend_projections(raw)

    def test_duplicate_identities_are_rejected_per_source_list(self):
        for source in ("steamer_hitters", "zips_hitters", "steamer_pitchers", "zips_pitchers"):
            raw = self.raw()
            factory = _fg_hitter if source.endswith("hitters") else _fg_pitcher
            raw[source] = [factory(37), factory(37)]
            raw[source][0]["playerids"] = 37
            with self.subTest(source=source), self.assertRaisesRegex(RuntimeError, source + ".*duplicate.*playerids"):
                blend_projections(raw)

    def test_identity_overlap_across_sources_and_roles_is_allowed(self):
        raw = self.raw()
        raw["zips_hitters"] = [_fg_hitter("shared")]
        raw["zips_pitchers"] = [_fg_pitcher("shared")]
        self.assertEqual(len(blend_projections(raw)), 2)

    def test_numeric_strings_explicit_zeroes_and_optional_omissions_are_allowed(self):
        raw = self.raw()
        for source, volume, optional in (("steamer_hitters", "PA", "GDP"), ("steamer_pitchers", "IP", "BS")):
            row = raw[source][0]
            del row[optional]
            for field, value in list(row.items()):
                if isinstance(value, (int, float)):
                    row[field] = str(value)
            self.assertGreater(float(row[volume]), 0.0)
        self.assertEqual(len(blend_projections(raw)), 2)

    def test_zero_volume_allows_undefined_nonvolume_components(self):
        raw = {"steamer_hitters": [{"playerids": "shared", "PA": "0"}],
               "steamer_pitchers": [{"playerids": "shared", "IP": 0}]}
        self.assertEqual(len(blend_projections(raw)), 2)

    def test_zero_volume_nonnull_components_are_validated_before_matching(self):
        for source, volume, fields in (
            ("zips_hitters", "PA", ("HR", "OBP")),
            ("zips_pitchers", "IP", ("SO", "WHIP")),
        ):
            for field in fields:
                for value in (float("nan"), float("inf"), -float("inf"), "NaN", "inf", "invalid", True, False):
                    raw = self.raw()
                    raw[source] = [{"playerids": "shared", volume: 0, field: value}]
                    with self.subTest(source=source, field=field, value=repr(value)), self.assertRaisesRegex(RuntimeError, source + ".*" + field):
                        blend_projections(raw)

    def test_present_optional_components_are_validated_at_any_volume(self):
        for source, volume, optional, factory in (
            ("steamer_hitters", "PA", "GDP", _fg_hitter),
            ("zips_hitters", "PA", "GDP", _fg_hitter),
            ("steamer_pitchers", "IP", "BS", _fg_pitcher),
            ("zips_pitchers", "IP", "BS", _fg_pitcher),
        ):
            for exposure in (0, 100):
                for value in (float("nan"), float("inf"), -float("inf"), "NaN", "inf", "invalid", True, False):
                    raw = self.raw()
                    raw[source] = [{**factory("shared"), volume: exposure, optional: value}]
                    with self.subTest(source=source, exposure=exposure, value=repr(value)), self.assertRaisesRegex(RuntimeError, source + ".*" + optional):
                        blend_projections(raw)

    def test_zero_volume_nulls_and_finite_optional_components_are_allowed(self):
        for value in (None, 0, "0", 1.5, "1.5"):
            raw = self.raw()
            raw["zips_hitters"] = [{"playerids": "shared", "PA": "0", "HR": value, "OBP": value, "GDP": value}]
            raw["zips_pitchers"] = [{"playerids": "shared", "IP": 0, "SO": value, "WHIP": value, "BS": value}]
            raw["steamer_hitters"][0]["GDP"] = value
            raw["steamer_pitchers"][0]["BS"] = value
            with self.subTest(value=value):
                self.assertEqual(len(blend_projections(raw)), 2)

    def test_identity_conversion_keeps_existing_string_representation(self):
        raw = self.raw()
        raw["steamer_hitters"] = [_fg_hitter("integer"), _fg_hitter("float")]
        raw["steamer_hitters"][0]["playerids"] = 1
        raw["steamer_hitters"][1]["playerids"] = 1.0
        self.assertEqual({row["id"] for row in blend_projections(raw) if row["pool"] == "hitter"}, {"1", "1.0"})

    def test_partial_generic_helpers_keep_existing_behavior(self):
        self.assertEqual(len(blend_hitters([{"playerids": "partial", "PA": 100}], [])), 1)
        self.assertEqual(len(blend_pitchers([{"playerids": "partial", "IP": 100}], [])), 1)

    def test_population_escape_flags_do_not_skip_source_validation(self):
        raw = self.raw()
        del raw["steamer_hitters"][0]["H"]
        with patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_ZERO_GUARD": "1"}):
            with self.assertRaisesRegex(RuntimeError, r"steamer_hitters.*\bH\b"):
                blend_projections(raw)


def test_all_zero_projections_refuse_to_ship():
    # Upstream field rename (HR -> homeRuns): IDs survive, every stat reads 0.0
    # via _safe_float defaults, and the artifact would pass every date/non-empty
    # gate downstream. The blend must fail LOUD instead (7/2 audit).
    import pytest
    from scraper.blend import blend_projections
    zero = {
        "steamer_hitters": [_fg_hitter(i, hr=0, pa=0) for i in range(60)],
        "steamer_pitchers": [_fg_pitcher(i, ip=0) for i in range(60)],
    }
    with pytest.raises(RuntimeError, match="schema drift"):
        blend_projections(zero)


def test_healthy_projections_pass_the_zero_guard():
    from scraper.blend import blend_projections
    raw = {
        "steamer_hitters": [_fg_hitter(i) for i in range(60)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(60)],
    }
    with patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"}):
        assert len(blend_projections(raw)) == 120


def test_truncated_pool_refuses_to_ship():
    # Feed truncated to a couple hundred real hitters is still "live" (nonzero
    # PA/HR on every row), so _assert_not_all_zero passes cleanly -- only the
    # pool floor catches this.
    import pytest
    from scraper.blend import blend_projections
    truncated = {
        "steamer_hitters": [_fg_hitter(i) for i in range(100)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(3600)],
    }
    with pytest.raises(RuntimeError, match="below floor"):
        blend_projections(truncated)


def test_truncated_pool_escape_hatch_suppresses():
    from scraper.blend import blend_projections
    truncated = {
        "steamer_hitters": [_fg_hitter(i) for i in range(100)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(3600)],
    }
    with patch.dict(os.environ, {"VALUCAST_SKIP_BLEND_POOL_FLOOR": "1"}):
        assert len(blend_projections(truncated)) == 3700


def test_normal_shaped_pool_passes_the_floor():
    from scraper.blend import blend_projections
    raw = {
        "steamer_hitters": [_fg_hitter(i) for i in range(3000)],
        "steamer_pitchers": [_fg_pitcher(i) for i in range(3500)],
    }
    assert len(blend_projections(raw)) == 6500

