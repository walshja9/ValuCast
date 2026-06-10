"""Tests for web/statcast_store.py — the committed Savant percentile snapshot
that drives the player-card percentile sliders. (Distinct from
tests/test_statcast_store.py, which covers the projection engine's
xBA/xSLG season data in projections/data/statcast.py.)"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from web.statcast_store import (
    StatcastStore,
    percentile_color,
    BATTER_METRICS,
    PITCHER_METRICS,
)


def _write(tmpdir: str, payload) -> Path:
    path = Path(tmpdir) / "percentiles.json"
    path.write_text(
        payload if isinstance(payload, str) else json.dumps(payload), encoding="utf-8"
    )
    return path


class TestStoreFailSoft(unittest.TestCase):
    def test_missing_file_yields_no_groups(self):
        store = StatcastStore(Path(tempfile.gettempdir()) / "nope" / "missing.json")
        self.assertEqual(store.display_groups("592450"), [])
        self.assertIsNone(store.as_of)

    def test_malformed_json_yields_no_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StatcastStore(_write(tmp, "{not json"))
            self.assertEqual(store.display_groups("592450"), [])

    def test_wrong_shape_yields_no_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StatcastStore(_write(tmp, {"batters": [1, 2], "pitchers": None}))
            self.assertEqual(store.display_groups("592450"), [])

    def test_no_mlbam_id_yields_no_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StatcastStore(
                _write(tmp, {"batters": {"1": {"xwoba": 50}}, "pitchers": {}}))
            self.assertEqual(store.display_groups(None), [])
            self.assertEqual(store.display_groups(""), [])


class TestDisplayGroups(unittest.TestCase):
    def _store(self, tmp):
        return StatcastStore(_write(tmp, {
            "as_of": "2026-06-10",
            "batters": {"100": {"xwoba": 98, "xba": 76, "k_percent": 18,
                                "bogus_metric": 50, "sprint_speed": "fast"}},
            "pitchers": {"100": {"xwoba": 60, "xera": 81},
                         "200": {"k_percent": 140, "bb_percent": -5}},
        }))

    def test_batter_group_curated_and_ordered(self):
        with tempfile.TemporaryDirectory() as tmp:
            groups = self._store(tmp).display_groups("100")
            # two-way: both groups, batting first by default
            self.assertEqual([g["label"] for g in groups], ["Batting", "Pitching"])
            labels = [m["label"] for m in groups[0]["metrics"]]
            # curated order; unknown keys and non-numeric values skipped
            self.assertEqual(labels, ["xwOBA", "xBA", "K %"])

    def test_prefer_pitching_reorders(self):
        with tempfile.TemporaryDirectory() as tmp:
            groups = self._store(tmp).display_groups("100", prefer_pitching=True)
            self.assertEqual([g["label"] for g in groups], ["Pitching", "Batting"])

    def test_single_side_player_gets_one_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            groups = self._store(tmp).display_groups("200", prefer_pitching=True)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["label"], "Pitching")

    def test_percentiles_clamped_to_0_100(self):
        with tempfile.TemporaryDirectory() as tmp:
            metrics = self._store(tmp).display_groups("200")[0]["metrics"]
            by_label = {m["label"]: m["pct"] for m in metrics}
            self.assertEqual(by_label["K %"], 100)
            self.assertEqual(by_label["BB %"], 0)

    def test_as_of_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self._store(tmp).as_of, "2026-06-10")

    def test_int_mlbam_id_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(self._store(tmp).display_groups(100))

    def test_metric_rows_carry_valid_colors(self):
        with tempfile.TemporaryDirectory() as tmp:
            for group in self._store(tmp).display_groups("100"):
                for m in group["metrics"]:
                    self.assertRegex(m["color"], r"^#[0-9a-f]{6}$")


class TestPercentileColor(unittest.TestCase):
    def test_endpoints_and_midpoint(self):
        self.assertEqual(percentile_color(0), "#3661ad")    # blue
        self.assertEqual(percentile_color(50), "#a0a3aa")   # gray
        self.assertEqual(percentile_color(100), "#d6291c")  # red

    def test_out_of_range_clamps(self):
        self.assertEqual(percentile_color(-10), percentile_color(0))
        self.assertEqual(percentile_color(140), percentile_color(100))

    def test_monotonic_red_channel_above_50(self):
        reds = [int(percentile_color(p)[1:3], 16) for p in (50, 60, 70, 80, 90, 100)]
        self.assertEqual(reds, sorted(reds))


class TestCuratedSpecs(unittest.TestCase):
    def test_specs_reference_real_savant_columns(self):
        savant_batter = {
            "xwoba", "xba", "xslg", "xiso", "xobp", "brl", "brl_percent",
            "exit_velocity", "max_ev", "hard_hit_percent", "k_percent", "bb_percent",
            "whiff_percent", "chase_percent", "arm_strength", "sprint_speed", "oaa",
            "bat_speed", "squared_up_rate", "swing_length",
        }
        savant_pitcher = {
            "xwoba", "xba", "xslg", "xiso", "xobp", "brl", "brl_percent",
            "exit_velocity", "max_ev", "hard_hit_percent", "k_percent", "bb_percent",
            "whiff_percent", "chase_percent", "arm_strength", "xera", "fb_velocity",
            "fb_spin", "curve_spin",
        }
        self.assertTrue({k for k, _ in BATTER_METRICS} <= savant_batter)
        self.assertTrue({k for k, _ in PITCHER_METRICS} <= savant_pitcher)


class TestCommittedArtifact(unittest.TestCase):
    """The real committed snapshot must stay loadable and usefully populated."""

    def test_artifact_loads_with_real_players(self):
        store = StatcastStore()  # default committed path
        self.assertIsNotNone(store.as_of)
        judge = store.display_groups("592450")
        self.assertTrue(judge, "Aaron Judge should have batter percentiles")
        self.assertEqual(judge[0]["label"], "Batting")


if __name__ == "__main__":
    unittest.main()
