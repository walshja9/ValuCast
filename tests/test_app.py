import csv
import io
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


class TestExportRoute(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_export_returns_csv(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)

    def test_export_has_attachment_header(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        self.assertIn("valucast-rankings.csv", response.headers.get("Content-Disposition", ""))

    def test_export_has_header_row(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertIn("Rank", header)
        self.assertIn("Player", header)
        self.assertIn("Value", header)

    def test_export_has_data_rows(self):
        response = self.client.get("/export?mode=categories&cats=R,HR&pcats=K,ERA")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        self.assertGreater(len(rows), 1)

    def test_export_respects_pool_filter(self):
        response = self.client.get("/export?pool=hitter&cats=R,HR&pcats=K,ERA")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        pos_col = header.index("Positions")
        for row in reader:
            self.assertNotIn("SP", row[pos_col].split(", "))


class TestDDDynastyMode(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_dd_dynasty_returns_200_if_available(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)

    def test_dd_dynasty_contains_dynasty_value_header(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"Dynasty Value", response.data)

    def test_dd_dynasty_rankings_returns_200(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/rankings?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)

    def test_dd_dynasty_export_csv(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/export?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        self.assertIn(b"Overall Dynasty Rank", response.data)

    def test_dd_dynasty_fallback_when_unavailable(self):
        """Direct dd_dynasty URL should work even if feed unavailable — falls back to redraft."""
        response = self.client.get("/?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)

    def test_redraft_still_works(self):
        """Redraft modes should be completely unaffected."""
        response = self.client.get("/?mode=categories")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"rankings-table", response.data)


class TestNoRosBadgeCSS(unittest.TestCase):
    def test_no_ros_badge_style_exists(self):
        """Static CSS should define .no-ros-badge styles."""
        css_path = Path(__file__).parent.parent / "static" / "style.css"
        content = css_path.read_text(encoding="utf-8")
        self.assertIn(".no-ros-badge", content)


class TestComputeTiers(unittest.TestCase):
    def test_single_player_tier_merges_down(self):
        """If tier 1 has only 1 player, merge it into tier 2."""
        from app import _compute_tiers
        from league_values.models import PlayerProjection, ValuationResult

        players = []
        values = [20.0, 10.0, 9.5, 9.0, 8.5, 8.0, 7.5, 7.0, 6.5, 6.0]
        for i, v in enumerate(values):
            proj = {"id": str(i), "name": f"P{i}", "pool": "hitter", "stats": {"HR": 10}}
            r = ValuationResult(
                player=PlayerProjection.from_dict(proj),
                total_value=v, raw_values={}, z_scores={}, category_values={},
            )
            players.append(r)

        tiers = _compute_tiers(players)
        tier_counts = {}
        for pid, t in tiers.items():
            tier_counts[t] = tier_counts.get(t, 0) + 1
        for tier_num, count in tier_counts.items():
            self.assertGreaterEqual(count, 3, f"Tier {tier_num} has only {count} players")

    def test_all_same_value_single_tier(self):
        """If all players have the same value, one tier."""
        from app import _compute_tiers
        from league_values.models import PlayerProjection, ValuationResult

        players = []
        for i in range(10):
            proj = {"id": str(i), "name": f"P{i}", "pool": "hitter", "stats": {"HR": 10}}
            r = ValuationResult(
                player=PlayerProjection.from_dict(proj),
                total_value=5.0, raw_values={}, z_scores={}, category_values={},
            )
            players.append(r)

        tiers = _compute_tiers(players)
        unique_tiers = set(tiers.values())
        self.assertEqual(len(unique_tiers), 1)

    def test_fewer_than_three_players_ok(self):
        """With < 3 players, tiers are assigned without enforcement."""
        from app import _compute_tiers
        from league_values.models import PlayerProjection, ValuationResult

        players = []
        for i, v in enumerate([10.0, 5.0]):
            proj = {"id": str(i), "name": f"P{i}", "pool": "hitter", "stats": {"HR": 10}}
            r = ValuationResult(
                player=PlayerProjection.from_dict(proj),
                total_value=v, raw_values={}, z_scores={}, category_values={},
            )
            players.append(r)

        tiers = _compute_tiers(players)
        self.assertEqual(len(tiers), 2)
