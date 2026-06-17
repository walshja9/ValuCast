import csv
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import app, _valuation_players, store


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

    def test_compare_dynasty_snapshot_returns_200(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        rows = dd_store.get_all()
        if len(rows) < 2:
            self.skipTest("Not enough DD rows available")

        response = self.client.get(
            "/compare",
            query_string={"mode": "dd_dynasty", "p1": rows[0].id, "p2": rows[1].id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(rows[0].name.encode(), response.data)
        self.assertIn(rows[1].name.encode(), response.data)
        self.assertIn(b"Dynasty Value", response.data)

    def test_compare_prospects_snapshot_returns_200(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        rows = [row for row in dd_store.get_all() if row.is_prospect]
        if len(rows) < 2:
            self.skipTest("Not enough prospect rows available")

        response = self.client.get(
            "/compare",
            query_string={"mode": "prospects", "p1": rows[0].id, "p2": rows[1].id},
        )
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

    def test_dynasty_replace_url_encodes_search(self):
        response = self.client.get("/rankings?mode=dd_dynasty&search=juan soto")
        url = response.headers.get("HX-Replace-Url", "")
        self.assertNotIn(" ", url)
        self.assertIn("search=juan+soto", url)


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


class TestDynastyMode(unittest.TestCase):
    """Tests for Dynasty and Prospects modes using the DD feed."""
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_dynasty_returns_200(self):
        response = self.client.get("/?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)

    def test_dynasty_shows_dynasty_value_header(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"Dynasty Value", response.data)

    def test_dynasty_no_category_columns(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertNotIn(b"col-cat", response.data)

    def test_dynasty_rankings_returns_200(self):
        response = self.client.get("/rankings?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)

    def test_dynasty_export_csv(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/export?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)
        self.assertIn(b"Overall Dynasty Rank", response.data)

    def test_dynasty_ignores_cats_params(self):
        """Custom category params should be ignored in dynasty mode."""
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        r1 = self.client.get("/?mode=dd_dynasty")
        r2 = self.client.get("/?mode=dd_dynasty&cats=R,HR&pcats=K")
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

    def test_dynasty_compare_bar_hidden_by_default(self):
        """Compare bar element is present in DOM but starts hidden (display:none); JS hides it further in dynasty mode per spec."""
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"compare-bar", response.data)
        self.assertIn(b'style="display:none;"', response.data)

    def test_dynasty_pool_filter_mlb(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/rankings?mode=dd_dynasty&pool=mlb")
        self.assertEqual(response.status_code, 200)

    def test_dynasty_pool_filter_prospect(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/rankings?mode=dd_dynasty&pool=prospect")
        self.assertEqual(response.status_code, 200)

    def test_dynasty_search(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/rankings?mode=dd_dynasty&search=skenes")
        self.assertEqual(response.status_code, 200)

    def test_prospects_returns_200(self):
        response = self.client.get("/?mode=prospects")
        self.assertEqual(response.status_code, 200)

    def test_prospects_shows_prospect_rank_header(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=prospects")
        self.assertIn(b"P#", response.data)

    def test_prospects_count_copy(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=prospects")
        self.assertIn(b"prospects", response.data)

    def test_prospects_rankings_returns_200(self):
        response = self.client.get("/rankings?mode=prospects")
        self.assertEqual(response.status_code, 200)

    def test_prospects_export_csv(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/export?mode=prospects")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response.content_type)

    def test_prospects_position_graphic_preview(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/prospects/share-card?position=SS&limit=10")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)
        self.assertIn(b"Ahead of the Curve", response.data)
        self.assertIn(b"Top 10 SS Prospects", response.data)
        self.assertIn(b"Download PNG", response.data)
        self.assertIn(b"/prospects/share-card.png?limit=10&amp;position=SS", response.data)
        index = self.client.get("/?mode=prospects").data
        self.assertIn(b"/prospects/share-card?limit=10", index)

    def test_prospects_position_graphic_svg(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/prospects/share-card.svg?position=SS&limit=10")
        self.assertEqual(response.status_code, 200)
        self.assertIn("image/svg+xml", response.content_type)
        self.assertIn(b"Filtered from the current prospect board", response.data)
        self.assertIn(b"SS RANK", response.data)
        self.assertNotIn(b"dynasty value", response.data.lower())
        self.assertNotIn(b">DV<", response.data)
        self.assertNotIn(b"PROSPECT RANK", response.data)

    def test_prospects_position_graphic_png(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/prospects/share-card.png?position=SS&limit=10")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("image/png", response.content_type)
        self.assertIn(
            'filename="valucast-top-10-ss-prospects.png"',
            response.headers.get("Content-Disposition", ""),
        )

    def test_value_map_share_card_png(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/map/share-card.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("image/png", response.content_type)
        self.assertIn(
            'filename="valucast-value-map.png"',
            response.headers.get("Content-Disposition", ""),
        )

    def test_value_map_share_card_png_filtered(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/map/share-card.png?pool=prospect&position=SS")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:8], b"\x89PNG\r\n\x1a\n")

    def test_value_map_share_card_preview(self):
        response = self.client.get("/map/share-card")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.content_type)
        self.assertIn(b"Ahead of the Curve", response.data)
        self.assertIn(b'property="og:image"', response.data)
        self.assertIn(b"Download PNG", response.data)
        self.assertIn(b"/map/share-card.png", response.data)
        map_html = self.client.get("/map").data
        self.assertIn(b"/map/share-card", map_html)
        self.assertIn(b"/map/share-card.png", map_html)
        self.assertIn(b"/api/value-map-players", map_html)

    def test_value_map_players_api(self):
        response = self.client.get("/api/value-map-players")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertIn("players", payload)
        self.assertEqual(payload["count"], len(payload["players"]))
        if payload["players"]:
            self.assertIn("name", payload["players"][0])
            self.assertIn("value", payload["players"][0])

    def test_buys_share_card_png_and_preview(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        png = self.client.get("/buys/share-card.png")
        self.assertEqual(png.status_code, 200)
        self.assertEqual(png.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("image/png", png.content_type)
        self.assertIn(
            'filename="valucast-buys.png"',
            png.headers.get("Content-Disposition", ""),
        )

        preview = self.client.get("/buys/share-card")
        self.assertEqual(preview.status_code, 200)
        self.assertIn(b"Ahead of the Curve", preview.data)
        self.assertIn(b'property="og:image"', preview.data)
        self.assertIn(b"/buys/share-card.png", preview.data)

        buys_html = self.client.get("/buys").data
        self.assertIn(b"/buys/share-card.png", buys_html)

    def test_prospects_graphic_limit_20_filename(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/prospects/share-card.png?position=SP&limit=20")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'filename="valucast-top-20-sp-prospects.png"',
            response.headers.get("Content-Disposition", ""),
        )

    def test_prospect_player_card_preview_and_png(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in dd_store.get_all() if r.is_prospect), None)
        if row is None:
            self.skipTest("No prospect rows available")

        preview = self.client.get(f"/prospects/player-card/{row.id}")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("text/html", preview.content_type)
        self.assertIn(b"Ahead of the Curve", preview.data)
        self.assertIn(b"current skill percentiles + peak context", preview.data)
        self.assertIn(b'property="og:image"', preview.data)
        self.assertIn(f"/prospects/player-card/{row.id}.png".encode(), preview.data)

        png = self.client.get(f"/prospects/player-card/{row.id}.png")
        self.assertEqual(png.status_code, 200)
        self.assertEqual(png.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertIn("image/png", png.content_type)
        self.assertIn("valucast-", png.headers.get("Content-Disposition", ""))

    def test_graphic_availability_badge_flags_only_real_risks(self):
        from app import _graphic_availability_badge
        from types import SimpleNamespace

        def row(status):
            return SimpleNamespace(availability_context={"status": status})

        self.assertEqual(_graphic_availability_badge(row("injured")), "INJURED")
        self.assertEqual(
            _graphic_availability_badge(row("stale_or_inactive")), "INACTIVE"
        )
        self.assertIsNone(_graphic_availability_badge(row("available")))
        self.assertIsNone(_graphic_availability_badge(row("thin_current_sample")))
        self.assertIsNone(
            _graphic_availability_badge(SimpleNamespace(availability_context={}))
        )

    def test_player_card_png_renders_for_flagged_availability_row(self):
        from app import dd_store, _graphic_availability_badge
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        flagged = next(
            (
                r
                for r in dd_store.get_all()
                if r.is_prospect and _graphic_availability_badge(r)
            ),
            None,
        )
        if flagged is None:
            self.skipTest("No flagged-availability prospects in snapshot")
        png = self.client.get(f"/prospects/player-card/{flagged.id}.png")
        self.assertEqual(png.status_code, 200)
        self.assertEqual(png.data[:8], b"\x89PNG\r\n\x1a\n")

    def test_prospect_player_card_read_uses_stats_not_stock_blurb(self):
        from types import SimpleNamespace

        from app import _prospect_player_card_read

        row = SimpleNamespace(
            name="Franklin Arias",
            age=20,
            level="AA",
            stat_line={
                "avg": 0.318,
                "obp": 0.397,
                "slg": 0.579,
                "ops": 0.976,
                "iso": 0.261,
                "k_pct": 12.9,
                "bb_pct": 9.8,
                "pa": 224,
            },
        )
        read = _prospect_player_card_read(
            row,
            {
                "ops": 96,
                "iso": 94,
                "k_pct": 96,
                "avg": 95,
                "obp": 84,
                "slg": 96,
                "bb_pct": 32,
            },
            {"stat_line_sample": 224, "stat_line_sample_unit": "PA"},
        )

        self.assertIn(".318/.397/.579", read)
        self.assertIn("224 PA", read)
        self.assertIn(".976 OPS", read)
        self.assertIn(".261 ISO", read)
        self.assertIn("12.9% K rate", read)
        self.assertIn("9.8% walk rate", read)
        self.assertIn("32nd", read)
        self.assertNotIn("open question", read.lower())

    def test_player_card_sample_context_shows_current_and_combined_samples(self):
        from types import SimpleNamespace

        from app import _graphic_sample_context_label

        row = SimpleNamespace(
            level="AA",
            sample_context_label="AA sample: 72 PA | 2026 total: 177 PA across AA+A+",
        )

        label = _graphic_sample_context_label(
            row,
            {
                "stat_line_level": "AA",
                "stat_line_sample": 72,
                "stat_line_sample_unit": "PA",
            },
        )

        self.assertEqual(
            label,
            "AA sample: 72 PA | 2026 total: 177 PA across AA+A+",
        )

    def test_prospect_detail_links_player_share_graphic(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in dd_store.get_all() if r.is_prospect), None)
        if row is None:
            self.skipTest("No prospect rows available")

        response = self.client.get(
            f"/player/{row.id}?mode=prospects",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Share graphic", response.data)
        self.assertIn(f"/prospects/player-card/{row.id}".encode(), response.data)

    def test_prospects_compare_bar_hidden_by_default(self):
        """Compare bar element is present in DOM but starts hidden (display:none)."""
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=prospects")
        self.assertIn(b"compare-bar", response.data)
        self.assertIn(b'style="display:none;"', response.data)

    def test_dynasty_fallback_when_unavailable(self):
        """Direct dynasty URL should work even if feed unavailable — falls back to redraft."""
        response = self.client.get("/?mode=dd_dynasty")
        self.assertEqual(response.status_code, 200)

    def test_redraft_unaffected(self):
        """Redraft modes should be completely unaffected by dynasty features."""
        response = self.client.get("/?mode=categories")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"rankings-table", response.data)
        self.assertIn(b"col-cat", response.data)

        detail = self.client.get(
            "/player/19755?mode=categories",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(detail.status_code, 200)
        self.assertLess(
            detail.data.find(b"The ValuCast Read"),
            detail.data.find(b"Category Breakdown"),
        )


class TestNoRosBadgeCSS(unittest.TestCase):
    def test_no_ros_badge_style_exists(self):
        """Static CSS should define .no-ros-badge styles."""
        css_path = Path(__file__).parent.parent / "static" / "style.css"
        content = css_path.read_text(encoding="utf-8")
        self.assertIn(".no-ros-badge", content)


class TestConfidenceIntegration(unittest.TestCase):
    """Feed confidence integration with dynasty/prospect routes."""
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_dynasty_table_gates_v11_columns_on_v10_feed(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        if dd_store.schema_version == "1.1":
            self.assertIn(b'class="col-confidence"', response.data)
            self.assertIn(b'id="category-fit-panel"', response.data)
        else:
            # v1.0 feed carries no confidence/z-scores: the columns and the
            # Category Fit panel must not render as dead UI. (The inline JS
            # still mentions the class names, so assert on markup forms.)
            self.assertNotIn(b'class="col-confidence"', response.data)
            self.assertNotIn(b'class="col-fit"', response.data)
            self.assertNotIn(b'id="category-fit-panel"', response.data)

    def test_prospects_table_gates_v11_columns_on_v10_feed(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=prospects")
        if dd_store.schema_version == "1.1":
            self.assertIn(b'class="col-confidence"', response.data)
        else:
            self.assertNotIn(b'class="col-confidence"', response.data)

    def test_dynasty_player_detail_hides_missing_confidence(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        rows = dd_store.filter()
        if not rows:
            self.skipTest("No dynasty rows")
        response = self.client.get(f"/player/{rows[0].id}?mode=dd_dynasty", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"risk-block", response.data)

    def test_prospect_player_detail_hides_missing_confidence(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        rows = dd_store.filter(pool="prospect")
        if not rows:
            self.skipTest("No prospect rows")
        response = self.client.get(f"/player/{rows[0].id}?mode=prospects", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"risk-block", response.data)

    def test_dynasty_export_includes_confidence_columns(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/export?mode=dd_dynasty")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertIn("Confidence Level", header)
        self.assertIn("Value Low", header)
        self.assertIn("Value High", header)
        self.assertNotIn("Risk Drivers", header)

    def test_prospects_export_includes_confidence_columns(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/export?mode=prospects")
        text = response.data.decode("utf-8")
        reader = csv.reader(io.StringIO(text))
        header = next(reader)
        self.assertIn("Confidence Level", header)
        self.assertIn("Value Low", header)
        self.assertIn("Value High", header)
        self.assertNotIn("Risk Drivers", header)


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


class TestPlayingTimeFilter(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_filter_shrinks_engine_input(self):
        # The whole point: filler is dropped before valuation.
        full = len(store.get_all())
        filtered = len(_valuation_players())
        self.assertLess(filtered, full)
        self.assertLess(filtered, 2000)   # ~1008 real players vs ~9953 total
        self.assertGreater(filtered, 500)

    def test_subthreshold_player_excluded_from_input(self):
        ids = {p.id for p in _valuation_players()}
        self.assertNotIn("sa3069149", ids)  # Brady Ebel, 1 PA

    def test_always_keep_readds_subthreshold_player(self):
        ids = {p.id for p in _valuation_players({"sa3069149"})}
        self.assertIn("sa3069149", ids)

    def test_qualifying_player_in_input(self):
        ids = {p.id for p in _valuation_players()}
        self.assertIn("19755", ids)  # Ohtani hitter qualifies

    def test_subthreshold_player_present_when_searched(self):
        # End-to-end: search bypass surfaces an otherwise-filtered player.
        response = self.client.get("/?search=Brady+Ebel")
        self.assertIn(b"Brady Ebel", response.data)

    def test_qualifying_player_still_shown(self):
        # End-to-end sanity: a real everyday player still appears by default.
        response = self.client.get("/")
        self.assertIn(b"Ohtani", response.data)

    def test_two_way_detail_value_matches_ranking(self):
        # Ohtani (19755) is two-way; detail/compare must merge like the ranking.
        from app import _merge_two_way_players, engine, _valuation_players
        from web.config_builder import build_config
        cfg = build_config(
            mode="categories", cats=None, pcats=None, rules_str="",
            pt_params=None, split_rp=False, weights=None,
        )
        ranking = _merge_two_way_players(engine.value_players(_valuation_players(), cfg))
        rank_val = next(r.total_value for r in ranking if r.player.id == "19755")
        detail = _merge_two_way_players(
            engine.value_players(_valuation_players({"19755"}), cfg)
        )
        detail_val = next(r.total_value for r in detail if r.player.id == "19755")
        self.assertAlmostEqual(rank_val, detail_val, places=6)


class TestPublicSurface(unittest.TestCase):
    """Launch-facing surface: crawler files, icons, social tags, error pages."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_robots_txt(self):
        r = self.client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"User-agent", r.data)

    def test_favicon(self):
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 200)

    def test_social_preview_tags_on_homepage(self):
        r = self.client.get("/")
        self.assertIn(b'property="og:image"', r.data)
        self.assertIn(b'name="twitter:card"', r.data)
        self.assertIn(b'name="description"', r.data)
        self.assertIn(b'rel="icon"', r.data)

    def test_404_is_branded(self):
        r = self.client.get("/definitely-not-a-page")
        self.assertEqual(r.status_code, 404)
        self.assertIn(b"Back to the rankings", r.data)
        self.assertIn(b"ValuCast", r.data)

    def test_htmx_served_locally(self):
        r = self.client.get("/")
        self.assertIn(b"/static/htmx.min.js", r.data)
        self.assertNotIn(b"unpkg.com", r.data)
        asset = self.client.get("/static/htmx.min.js")
        self.assertEqual(asset.status_code, 200)


class TestInputHardening(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_unknown_mode_falls_back_to_categories(self):
        r = self.client.get("/?mode=garbage-mode")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"rankings-table", r.data)

    def test_non_finite_weight_is_ignored(self):
        r = self.client.get("/?mode=categories&w_HR=inf")
        self.assertEqual(r.status_code, 200)
        r = self.client.get("/?mode=categories&w_HR=nan")
        self.assertEqual(r.status_code, 200)

    def test_csv_formula_cells_are_escaped(self):
        from app import _csv_safe
        self.assertEqual(_csv_safe("=2+2"), "'=2+2")
        self.assertEqual(_csv_safe("@cmd"), "'@cmd")
        self.assertEqual(_csv_safe("Aaron Judge"), "Aaron Judge")
        self.assertEqual(_csv_safe(42), 42)

    def test_security_headers_present(self):
        r = self.client.get("/")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
