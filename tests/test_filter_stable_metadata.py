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

    def test_dynasty_metadata_computed_on_full_universe(self):
        from app import (dd_store, _dynasty_metadata,
                         _compute_dynasty_tiers, _compute_dynasty_dollars)
        if not dd_store.is_available:
            self.skipTest("DD feed unavailable")
        dollars, tiers = _dynasty_metadata()
        full_top200 = sorted(dd_store.get_all(),
                             key=lambda r: r.dynasty_value, reverse=True)[:200]
        self.assertEqual(tiers, _compute_dynasty_tiers(full_top200))
        self.assertEqual(dollars, _compute_dynasty_dollars(full_top200))
        self.assertGreater(len(tiers), 100, "metadata pool should be the full top-200")

    def test_dynasty_context_uses_full_universe_metadata_under_filter(self):
        from app import dd_store, _build_dynasty_context, _compute_dynasty_tiers
        if not dd_store.is_available:
            self.skipTest("DD feed unavailable")
        from werkzeug.datastructures import ImmutableMultiDict
        ctx = _build_dynasty_context(ImmutableMultiDict([("position", "SS")]))
        full_top200 = sorted(dd_store.get_all(),
                             key=lambda r: r.dynasty_value, reverse=True)[:200]
        # Tiers must come from the full universe, not the filtered SS subset.
        self.assertEqual(ctx["tiers"], _compute_dynasty_tiers(full_top200))
