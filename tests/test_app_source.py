import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestSourceSelection(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_default_board_is_steamer(self):
        r = self.client.get("/rankings")
        self.assertEqual(r.status_code, 200)

    def test_valucast_source_loads_combined_board(self):
        r = self.client.get("/rankings?source=valucast")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.data), 100)

    def test_unknown_source_clear_error(self):
        r = self.client.get("/rankings?source=bogus")
        self.assertEqual(r.status_code, 400)
        self.assertIn(b"source", r.data.lower())
