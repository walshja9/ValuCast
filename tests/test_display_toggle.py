import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestDisplayToggle(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_default_shows_projected_stats(self):
        html = self.client.get("/rankings").data.decode("utf-8")
        self.assertRegex(html, r'col-cat[^>]*>\s*\.\d{3}\s*<')

    def test_value_view_uses_value_headers(self):
        html = self.client.get("/rankings?display=values").data.decode("utf-8")
        self.assertIn("HR value", html)

    def test_default_header_has_no_value_suffix(self):
        html = self.client.get("/rankings").data.decode("utf-8")
        self.assertNotIn("HR value", html)

    def test_toggle_is_accessible_and_present(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('name="display"', html)
        self.assertIn('aria-label="Column display"', html)

    def test_display_sticky_in_replace_url(self):
        r = self.client.get("/rankings?display=values")
        self.assertIn("display=values", r.headers.get("HX-Replace-Url", ""))

    def test_default_display_not_in_url(self):
        r = self.client.get("/rankings")
        self.assertNotIn("display=", r.headers.get("HX-Replace-Url", ""))

    def test_export_default_has_projected_stats(self):
        csv = self.client.get("/export").data.decode("utf-8")
        self.assertRegex(csv, r'(^|,)\.\d{3}(,|\r|\n)')


if __name__ == "__main__":
    unittest.main()
