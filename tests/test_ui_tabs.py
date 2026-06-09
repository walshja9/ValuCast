import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app, _horizon_of


class TestHorizonHelper(unittest.TestCase):
    def test_redraft_modes_map_to_redraft(self):
        for m in ("categories", "roto", "points"):
            self.assertEqual(_horizon_of(m), "redraft")

    def test_dynasty_and_prospects(self):
        self.assertEqual(_horizon_of("dd_dynasty"), "dynasty")
        self.assertEqual(_horizon_of("prospects"), "prospects")


class TestTabMarkup(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_horizon_tabs_are_links(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('href="/?mode=dd_dynasty"', html)
        self.assertIn('href="/?mode=prospects"', html)
        self.assertIn('class="horizon-tabs"', html)
        self.assertIn('aria-current="page"', html)

    def test_scoring_row_is_mode_radios_on_redraft(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('class="scoring-seg"', html)
        self.assertIn('name="mode"', html)
        self.assertIn('value="roto"', html)

    def test_no_scoring_row_on_dynasty(self):
        html = self.client.get("/?mode=dd_dynasty").data.decode("utf-8")
        self.assertNotIn('class="scoring-seg"', html)

    def test_redraft_tab_targets_categories(self):
        html = self.client.get("/?mode=dd_dynasty").data.decode("utf-8")
        self.assertRegex(html, r'href="/(?:\?mode=categories)?"[^>]*>\s*Redraft')


if __name__ == "__main__":
    unittest.main()
