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

    def test_form_carries_source_selector(self):
        # The form has a source <select> -> source serializes into every filter/
        # detail/compare/export request automatically.
        r = self.client.get("/")
        self.assertIn(b'name="source"', r.data)

    def test_valucast_source_is_sticky_via_replace_url(self):
        # /rankings sets HX-Replace-Url so a refresh keeps the ValuCast board.
        r = self.client.get("/rankings?source=valucast")
        self.assertIn("source=valucast", r.headers.get("HX-Replace-Url", ""))

    def test_full_page_reflects_selected_source(self):
        # Loading /?source=valucast renders the form with ValuCast pre-selected.
        r = self.client.get("/?source=valucast")
        self.assertIn(b'value="valucast" selected', r.data)

    def test_steamer_default_no_source_in_url(self):
        r = self.client.get("/rankings")
        self.assertNotIn("source=", r.headers.get("HX-Replace-Url", ""))

    def test_valucast_position_filter_returns_players(self):
        # Pre-enrichment this returned zero (empty positions). Now SS filter yields rows.
        r = self.client.get("/rankings?source=valucast&position=SS")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"player-row", r.data)   # non-empty filtered board

    def test_export_honors_source(self):
        r = self.client.get("/export?source=valucast")
        self.assertEqual(r.status_code, 200)
