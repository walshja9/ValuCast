import unittest
from pathlib import Path

import app as app_module
from web.dd_feed_store import DDFeedStore


FIXTURE = Path(__file__).parent / "dd_dynasty_feed_v11.json"


class TestDynastyV11UI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_store = app_module.dd_store
        app_module.dd_store = DDFeedStore(FIXTURE)
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.dd_store = cls.original_store

    def test_v11_store_and_category_fit_controls_render(self):
        response = self.client.get("/?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'id="category-fit-panel"', response.data)
        self.assertIn(b'class="col-confidence"', response.data)
        self.assertNotIn(b"Feed v", response.data)  # internal plumbing stays internal
        self.assertIn(b"Category Fit", response.data)
        self.assertIn(b"H2H Categories", response.data)
        self.assertIn(b"5x5 Roto", response.data)
        self.assertIn(b"6x6 OBP/QS", response.data)
        self.assertIn(b"Saves + Holds", response.data)
        self.assertIn(b"Categories without a player z-score are skipped.", response.data)
        self.assertIn(b'data-fit-cat="SLG"', response.data)
        self.assertIn(b"HLD / HD", response.data)
        self.assertIn(b'data-fit-cat="SV+HLD"', response.data)
        self.assertIn(b'data-fit-cat="BB/9"', response.data)
        self.assertIn(b'data-z-scores="{', response.data)

    def test_mlb_card_uses_feed_confidence_and_profile(self):
        response = self.client.get("/player/dd_mlb_power_star?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Range 108", response.data)
        self.assertIn(b"126", response.data)
        self.assertIn(b"Market Comp", response.data)
        self.assertIn(b"Category Profile", response.data)
        self.assertIn(b"Middle-of-the-order power anchor", response.data)
        self.assertNotIn(b"risk-block", response.data)

    def test_prospect_card_groups_stats_and_hides_null_level(self):
        response = self.client.get("/player/dd_prospect_future_bat?mode=prospects")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"ValuCast Rank", response.data)
        self.assertIn(b"ValuCast model rank", response.data)
        self.assertIn(b"Public Consensus", response.data)
        self.assertIn(b"~P#18", response.data)
        self.assertIn(b"MiLB Performance", response.data)
        self.assertIn(b"Proprietary performance signal", response.data)
        self.assertIn(b"View individual public boards", response.data)
        self.assertIn(b"Spread 68", response.data)
        self.assertIn(b"Rate Stats", response.data)
        self.assertIn(b"Plate Discipline", response.data)
        self.assertNotIn(b'<span class="stat-label">Level</span>', response.data)

    def test_prospects_board_uses_dd_prospect_rank_order(self):
        response = self.client.get("/?mode=prospects")
        self.assertEqual(response.status_code, 200)
        self.assertLess(
            response.data.find(b'data-player-id="dd_prospect_future_arm"'),
            response.data.find(b'data-player-id="dd_prospect_future_bat"'),
        )

    def test_category_fit_formula_includes_inverse_and_aliases(self):
        response = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"FIT_INVERSE", response.data)
        self.assertIn(b"FIT_Z_ALIASES", response.data)
        self.assertIn(b"OBP: ['OPS']", response.data)
        self.assertIn(b"W: ['QS']", response.data)
        self.assertIn(b"HLD: ['HD']", response.data)
        self.assertIn(b"'SV+HLD': ['SV_HLD', 'SV+HD', 'SV_HD']", response.data)
        self.assertIn(b"'BB/9': ['BB_9']", response.data)
        self.assertIn(b"normalized 0", response.data)


if __name__ == "__main__":
    unittest.main()
