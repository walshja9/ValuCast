import json
import os
import tempfile
import unittest
from pathlib import Path

from mlb.dynasty import _generated_at
from web.projection_store import ProjectionStore


ROOT = Path(__file__).resolve().parents[1]


SAMPLE_PLAYERS = [
    {
        "id": "1", "name": "Aaron Judge", "pool": "hitter",
        "positions": ["RF", "DH"], "team": "NYY",
        "stats": {
            "PA": 600, "AB": 520, "H": 150, "HR": 45, "R": 100,
            "RBI": 110, "SB": 5, "SO": 160, "BB": 75,
            "1B": 70, "2B": 25, "3B": 1, "CS": 2,
            "AVG": 0.288, "OBP": 0.400, "SLG": 0.600, "OPS": 1.000,
            "HBP": 5, "SF": 5, "SH": 0, "GDP": 10, "IBB": 10, "G": 150,
        },
        "metadata": {"fangraphs_id": "1", "mlbam_id": "100"},
        "sources": ["steamer", "zips"],
    },
    {
        "id": "2", "name": "Shohei Ohtani", "pool": "hitter",
        "positions": ["DH"], "team": "LAD",
        "stats": {
            "PA": 650, "AB": 560, "H": 165, "HR": 50, "R": 110,
            "RBI": 120, "SB": 20, "SO": 170, "BB": 80,
            "1B": 75, "2B": 30, "3B": 2, "CS": 5,
            "AVG": 0.295, "OBP": 0.410, "SLG": 0.650, "OPS": 1.060,
            "HBP": 5, "SF": 5, "SH": 0, "GDP": 8, "IBB": 15, "G": 155,
        },
        "metadata": {"fangraphs_id": "2", "mlbam_id": "200"},
        "sources": ["steamer", "zips"],
    },
    {
        "id": "3", "name": "Corbin Burnes", "pool": "starter",
        "positions": ["SP"], "team": "ARI",
        "stats": {
            "IP": 190, "K": 200, "W": 14, "L": 8, "QS": 22,
            "SV": 0, "HLD": 0, "ERA": 3.20, "WHIP": 1.10,
            "K_BB": 4.0, "ER": 68, "BB": 50, "H_ALLOWED": 160,
            "SV_HLD": 0, "GS": 32,
        },
        "metadata": {"fangraphs_id": "3", "mlbam_id": "300"},
        "sources": ["steamer", "zips"],
    },
    {
        "id": "4", "name": "Emmanuel Clase", "pool": "reliever",
        "positions": ["RP"], "team": "CLE",
        "stats": {
            "IP": 65, "K": 60, "W": 3, "L": 4, "QS": 0,
            "SV": 35, "HLD": 0, "ERA": 2.50, "WHIP": 0.95,
            "K_BB": 5.0, "ER": 18, "BB": 12, "H_ALLOWED": 50,
            "SV_HLD": 35, "GS": 0,
        },
        "metadata": {"fangraphs_id": "4", "mlbam_id": "400"},
        "sources": ["steamer", "zips"],
    },
]


class TestProjectionStore(unittest.TestCase):
    def setUp(self):
        self.tmpfile = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump(SAMPLE_PLAYERS, self.tmpfile)
        self.tmpfile.close()
        self.store = ProjectionStore(self.tmpfile.name)

    def tearDown(self):
        os.unlink(self.tmpfile.name)

    def test_loads_all_players(self):
        self.assertEqual(self.store.player_count, 4)

    def test_get_all_returns_list(self):
        players = self.store.get_all()
        self.assertEqual(len(players), 4)

    def test_derived_stat_tb(self):
        judge = self.store.get_by_id("1")
        # TB = 1B + 2*2B + 3*3B + 4*HR = 70 + 50 + 3 + 180 = 303
        self.assertAlmostEqual(judge.stats["TB"], 303.0)

    def test_derived_stat_nsb(self):
        judge = self.store.get_by_id("1")
        # NSB = SB - CS = 5 - 2 = 3
        self.assertAlmostEqual(judge.stats["NSB"], 3.0)

    def test_team_in_metadata(self):
        judge = self.store.get_by_id("1")
        self.assertEqual(judge.metadata["team"], "NYY")

    def test_get_by_id_found(self):
        player = self.store.get_by_id("2")
        self.assertEqual(player.name, "Shohei Ohtani")

    def test_get_by_id_missing(self):
        self.assertIsNone(self.store.get_by_id("999"))

    def test_filter_by_pool_hitter(self):
        hitters = self.store.filter(pool="hitter")
        self.assertEqual(len(hitters), 2)

    def test_filter_by_pool_pitcher_includes_starter_reliever(self):
        pitchers = self.store.filter(pool="pitcher")
        self.assertEqual(len(pitchers), 2)
        names = {p.name for p in pitchers}
        self.assertEqual(names, {"Corbin Burnes", "Emmanuel Clase"})

    def test_filter_by_position(self):
        sps = self.store.filter(position="SP")
        self.assertEqual(len(sps), 1)
        self.assertEqual(sps[0].name, "Corbin Burnes")

    def test_filter_by_search(self):
        results = self.store.filter(search="judge")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "Aaron Judge")

    def test_search_case_insensitive(self):
        results = self.store.filter(search="OHTANI")
        self.assertEqual(len(results), 1)

    def test_filter_combined(self):
        results = self.store.filter(pool="hitter", position="DH")
        self.assertEqual(len(results), 2)

    def test_filter_no_match(self):
        results = self.store.filter(search="nobody")
        self.assertEqual(len(results), 0)

    def test_pitcher_derived_stats_not_computed(self):
        """Pitchers shouldn't get TB/NSB — they don't have the source stats."""
        burnes = self.store.get_by_id("3")
        self.assertAlmostEqual(burnes.stats["TB"], 0.0)
        self.assertAlmostEqual(burnes.stats["NSB"], 0.0)


class TestProjectionStoreMetadata(unittest.TestCase):
    def test_as_of_none_when_no_sidecar(self):
        """as_of should be None when metadata.json doesn't exist."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "current.json")
            with open(path, "w") as f:
                json.dump(SAMPLE_PLAYERS, f)
            store = ProjectionStore(path)
            self.assertIsNone(store.as_of)

    def test_as_of_loaded_from_sidecar(self):
        """as_of should load from metadata.json when present."""
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "current.json")
            meta_path = os.path.join(d, "metadata.json")
            with open(path, "w") as f:
                json.dump(SAMPLE_PLAYERS, f)
            with open(meta_path, "w") as f:
                json.dump({"as_of": "2026-05-25"}, f)
            store = ProjectionStore(path)
            self.assertEqual(store.as_of, "2026-05-25")

    def test_valucast_hp_run_sidecar_feeds_dynasty_generated_at(self):
        path = ROOT / "projections" / "runs" / "valucast_hp_2026_v2" / "projections.json"
        store = ProjectionStore(path)

        self.assertIsNotNone(store.as_of)
        self.assertEqual(_generated_at(store), store.as_of)
