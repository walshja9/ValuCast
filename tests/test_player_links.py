"""Tests for web/player_links.py — outbound FanGraphs/Savant card links."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from web.player_links import build_player_links, fangraphs_url, savant_url


class TestSlugAndUrls(unittest.TestCase):
    def test_fangraphs_url_slugs_accents_and_spaces(self):
        self.assertEqual(
            fangraphs_url("José Ramírez", 13510),
            "https://www.fangraphs.com/players/jose-ramirez/13510",
        )

    def test_fangraphs_url_handles_minor_league_ids(self):
        self.assertEqual(
            fangraphs_url("Brady Ebel", "sa3069149"),
            "https://www.fangraphs.com/players/brady-ebel/sa3069149",
        )

    def test_fangraphs_url_none_without_id(self):
        self.assertIsNone(fangraphs_url("Somebody", None))
        self.assertIsNone(fangraphs_url("Somebody", ""))

    def test_savant_url_requires_numeric_mlbam(self):
        self.assertEqual(
            savant_url(592450), "https://baseballsavant.mlb.com/savant-player/592450")
        self.assertIsNone(savant_url("sa3069149"))
        self.assertIsNone(savant_url(None))
        self.assertIsNone(savant_url(""))


class TestBuildPlayerLinks(unittest.TestCase):
    def test_both_links_when_both_ids(self):
        links = build_player_links("Aaron Judge", mlbam_id=592450, fangraphs_id=15640)
        self.assertEqual([l["label"] for l in links], ["Baseball Savant", "FanGraphs"])

    def test_no_ids_no_links(self):
        self.assertEqual(build_player_links("Jesus Made"), [])

    def test_partial_ids_partial_links(self):
        links = build_player_links("Brady Ebel", mlbam_id="sa-x", fangraphs_id="sa3069149")
        self.assertEqual([l["label"] for l in links], ["FanGraphs"])


class TestCardRoutes(unittest.TestCase):
    """End-to-end: cards render percentile sliders + links where ids exist."""

    @classmethod
    def setUpClass(cls):
        from app import app
        cls.client = app.test_client()

    def test_redraft_card_has_statcast_and_links(self):
        html = self.client.get("/player/15640", headers={"HX-Request": "true"}).data.decode("utf-8")  # Judge
        self.assertIn("statcast-section", html)
        self.assertIn("pct-row", html)
        self.assertIn("player-links", html)
        self.assertIn("savant-player/592450", html)
        self.assertIn("fangraphs.com/players/aaron-judge/15640", html)

    def test_redraft_card_has_zscore_bars(self):
        html = self.client.get("/player/15640", headers={"HX-Request": "true"}).data.decode("utf-8")
        self.assertIn("zbar-fill", html)

    def test_prospect_card_has_neither(self):
        from app import dd_store
        prospect = next(r for r in dd_store.get_all() if r.is_prospect)
        html = self.client.get(
            f"/player/{prospect.id}?mode=prospects",
            headers={"HX-Request": "true"}).data.decode("utf-8")
        self.assertNotIn("statcast-section", html)
        self.assertNotIn("player-links", html)

    def test_dynasty_mlb_card_has_statcast_via_name_join(self):
        from app import dd_store
        row = next(r for r in dd_store.get_all() if r.name == "Shohei Ohtani")
        html = self.client.get(
            f"/player/{row.id}?mode=dd_dynasty",
            headers={"HX-Request": "true"}).data.decode("utf-8")
        self.assertIn("statcast-section", html)
        # two-way: both groups labeled
        self.assertIn("pct-group-label", html)


if __name__ == "__main__":
    unittest.main()
