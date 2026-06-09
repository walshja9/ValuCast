import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


def _ohtani_dollars(html):
    # Find the row containing "Ohtani" and pull its $ cell (col-dollars).
    m = re.search(r'Ohtani.*?col-dollars[^>]*>\s*\$?(\d+)', html, re.S)
    return int(m.group(1)) if m and m.group(1) else None


class TestFilterStableMetadata(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_search_does_not_inflate_dollars(self):
        # The classic bug: searching one player handed him the whole $2400 budget.
        full = self.client.get("/rankings").data.decode("utf-8")
        searched = self.client.get("/rankings?search=ohtani").data.decode("utf-8")
        d_full = _ohtani_dollars(full)
        d_search = _ohtani_dollars(searched)
        self.assertIsNotNone(d_full)
        self.assertIsNotNone(d_search)
        self.assertEqual(d_full, d_search, "auction $ changed under search")
        self.assertLess(d_search, 500, "single-player search still shows budget artifact")

    def test_pool_filter_preserves_dollars(self):
        full = self.client.get("/rankings").data.decode("utf-8")
        hitters = self.client.get("/rankings?pool=hitter").data.decode("utf-8")
        self.assertEqual(_ohtani_dollars(full), _ohtani_dollars(hitters))
