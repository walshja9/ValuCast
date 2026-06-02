import json
import tempfile
import unittest
from pathlib import Path

from web.projection_catalog import ProjectionCatalog


SAMPLE = [{
    "id": "mlbam_5_H", "name": "Bat", "pool": "hitter", "positions": ["1B"],
    "stats": {"PA": 450, "AB": 405, "H": 112, "HR": 22, "1B": 90, "2B": 0,
              "3B": 0, "R": 70, "RBI": 60, "SB": 0, "CS": 0, "BB": 45,
              "SO": 90, "HBP": 0, "SF": 0, "AVG": 0.277, "OBP": 0.349,
              "SLG": 0.444, "OPS": 0.793},
    "metadata": {"mlbam_id": "5", "source": "marcel"},
}]


class TestProjectionCatalog(unittest.TestCase):
    def test_default_source_is_steamer(self):
        cat = ProjectionCatalog(sources={"steamer": "a.json", "marcel": "b.json"})
        self.assertEqual(cat.default, "steamer")

    def test_store_for_loads_named_source(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "marcel.json"
            path.write_text(json.dumps(SAMPLE), encoding="utf-8")
            cat = ProjectionCatalog(sources={"marcel": str(path)})
            store = cat.store_for("marcel")
            self.assertEqual(store.player_count, 1)
            self.assertEqual(store.get_by_id("mlbam_5_H").name, "Bat")

    def test_unknown_source_raises(self):
        cat = ProjectionCatalog(sources={"steamer": "a.json"})
        with self.assertRaises(KeyError):
            cat.store_for("nope")
