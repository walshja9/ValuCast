import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestToolbar(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_single_toolbar_element(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertEqual(html.count('id="rank-toolbar"'), 1)
        # No leftover separate config-bar/filter-bar strips.
        self.assertNotIn('class="config-bar"', html)
        self.assertNotIn('class="filter-bar"', html)

    def test_source_present_in_points(self):
        html = self.client.get("/?mode=points").data.decode("utf-8")
        self.assertIn('name="source"', html)             # source works in points
        self.assertNotIn('name="display"', html)         # toggle still cats/roto only

    def test_source_and_toggle_in_categories(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('name="source"', html)
        self.assertIn('name="display"', html)

    def test_dynasty_toolbar_has_no_source_or_toggle(self):
        html = self.client.get("/?mode=dd_dynasty").data.decode("utf-8")
        self.assertNotIn('name="source"', html)
        self.assertNotIn('name="display"', html)
        self.assertIn('value="prospect"', html)          # dynasty-specific pool option

    def test_prospects_toolbar_minimal(self):
        html = self.client.get("/?mode=prospects").data.decode("utf-8")
        self.assertNotIn('name="pool"', html)
        self.assertNotIn('name="source"', html)


class TestStickyOffset(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_sticky_offset_wired(self):
        css = self.client.get("/static/style.css").data.decode("utf-8")
        self.assertIn(".rank-toolbar", css)
        self.assertIn("position: sticky", css)
        self.assertIn("var(--toolbar-h", css)
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn("ResizeObserver", html)


if __name__ == "__main__":
    unittest.main()
