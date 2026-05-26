import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import app


class TestIndexRoute(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_index_returns_200(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_index_contains_valucast(self):
        response = self.client.get("/")
        self.assertIn(b"ValuCast", response.data)

    def test_index_contains_mode_selector(self):
        response = self.client.get("/")
        self.assertIn(b'name="mode"', response.data)

    def test_index_contains_category_checkboxes(self):
        response = self.client.get("/")
        self.assertIn(b'name="cats"', response.data)
        self.assertIn(b'name="pcats"', response.data)

    def test_index_contains_rankings_table(self):
        response = self.client.get("/")
        self.assertIn(b"rankings-table", response.data)

    def test_index_default_shows_players(self):
        response = self.client.get("/")
        self.assertIn(b"col-value", response.data)

    def test_index_contains_config_summary(self):
        """Default page load should show the config summary line."""
        response = self.client.get("/")
        self.assertIn(b"config-summary", response.data)

    def test_index_setup_panel_collapsed_by_default(self):
        """Setup panel should have the collapsed class by default."""
        response = self.client.get("/")
        self.assertIn(b"setup-panel collapsed", response.data)

    def test_index_contains_customize_button(self):
        """Page should have a Customize toggle button."""
        response = self.client.get("/")
        self.assertIn(b"customize-toggle", response.data)


class TestRankingsRoute(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_rankings_returns_200(self):
        response = self.client.get("/rankings?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertEqual(response.status_code, 200)

    def test_rankings_contains_table(self):
        response = self.client.get("/rankings?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertIn(b"rankings-table", response.data)

    def test_rankings_sets_replace_url(self):
        response = self.client.get("/rankings?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertIn("HX-Replace-Url", response.headers)

    def test_rankings_oob_setup_panel(self):
        response = self.client.get("/rankings?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertIn(b'hx-swap-oob="innerHTML:#setup-panel"', response.data)

    def test_rankings_roto_mode(self):
        response = self.client.get("/rankings?mode=roto&cats=R,HR&pcats=K,ERA")
        self.assertEqual(response.status_code, 200)

    def test_rankings_points_mode(self):
        response = self.client.get("/rankings?mode=points&rules=HR:4,K:1")
        self.assertEqual(response.status_code, 200)

    def test_rankings_pool_filter(self):
        response = self.client.get("/rankings?pool=hitter")
        self.assertEqual(response.status_code, 200)

    def test_rankings_position_filter(self):
        response = self.client.get("/rankings?position=SP")
        self.assertEqual(response.status_code, 200)

    def test_rankings_search(self):
        response = self.client.get("/rankings?search=judge")
        self.assertEqual(response.status_code, 200)

    def test_rankings_different_cats(self):
        r1 = self.client.get("/rankings?cats=R,HR,RBI,SB,AVG&pcats=W,SV,K,ERA,WHIP")
        r2 = self.client.get("/rankings?cats=R,HR,RBI,SB,OBP&pcats=W,QS,SV,K,ERA,WHIP")
        self.assertNotEqual(r1.data, r2.data)

    def test_shared_url_renders(self):
        response = self.client.get("/?mode=roto&cats=R,HR,SB&pcats=K,ERA")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'value="roto"', response.data)


class TestPlayerDetail(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_missing_player_returns_404(self):
        response = self.client.get("/player/NONEXISTENT?mode=categories&cats=R&pcats=K")
        self.assertEqual(response.status_code, 404)


class TestCompareRoute(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_compare_returns_200(self):
        response = self.client.get("/compare?p1=1&p2=2&mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertEqual(response.status_code, 200)


class TestPointsMode(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_points_mode_full_page(self):
        response = self.client.get("/?mode=points")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"points-table", response.data)

    def test_points_mode_rankings(self):
        response = self.client.get("/rankings?mode=points&pt_HR=4&pt_K=1&pt_ER=-2")
        self.assertEqual(response.status_code, 200)

    def test_points_mode_with_rules_string(self):
        response = self.client.get("/rankings?mode=points&rules=HR:4,K:1,ER:-2")
        self.assertEqual(response.status_code, 200)


class TestUrlSharing(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_shared_url_5x5(self):
        response = self.client.get("/?cats=R,HR,RBI,SB,AVG&pcats=W,SV,K,ERA,WHIP")
        self.assertEqual(response.status_code, 200)

    def test_shared_url_points(self):
        response = self.client.get("/?mode=points&rules=HR:4,K:1,ER:-2")
        self.assertEqual(response.status_code, 200)

    def test_shared_url_with_filters(self):
        response = self.client.get("/?cats=R,HR&pcats=K,ERA&pool=hitter&search=soto")
        self.assertEqual(response.status_code, 200)

    def test_rankings_replace_url_header(self):
        response = self.client.get("/rankings?mode=roto&cats=R,HR,SB&pcats=K,ERA")
        url = response.headers.get("HX-Replace-Url", "")
        self.assertIn("mode=roto", url)
