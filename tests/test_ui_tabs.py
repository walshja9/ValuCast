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


class TestModeCarriedByForm(unittest.TestCase):
    """Non-redraft horizons have no mode radios, so the form must carry mode in a
    hidden input — otherwise htmx detail/rankings/export requests drop it and the
    server silently serves the redraft board (live bug found 2026-06-10)."""

    def setUp(self):
        self.client = app.test_client()

    def test_dynasty_form_carries_mode(self):
        html = self.client.get("/?mode=dd_dynasty").data.decode("utf-8")
        self.assertIn('type="hidden" name="mode" value="dd_dynasty"', html)

    def test_prospects_form_carries_mode(self):
        html = self.client.get("/?mode=prospects").data.decode("utf-8")
        self.assertIn('type="hidden" name="mode" value="prospects"', html)

    def test_redraft_form_has_no_hidden_mode(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertNotIn('type="hidden" name="mode"', html)

    def test_rankings_with_mode_returns_dynasty_table(self):
        html = self.client.get("/rankings?mode=dd_dynasty&position=&search=").data.decode("utf-8")
        self.assertIn("dynasty-rankings", html)  # the dynasty table, not redraft
        self.assertIn("col-dollar", html)


if __name__ == "__main__":
    unittest.main()
