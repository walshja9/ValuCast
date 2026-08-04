import csv
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app as app_module
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

    def test_index_registers_htmx_error_handler_and_detail_retry(self):
        response = self.client.get("/")
        html = response.data.decode("utf-8")
        self.assertIn("htmx:responseError", html)
        self.assertIn(".then(function () {\n            detailRow.dataset.loaded = 'true';", html)


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

    def test_rankings_browser_visit_redirects_to_board(self):
        response = self.client.get(
            "/rankings?mode=prospects&search=Jenkins",
            headers={"Accept": "text/html"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/?mode=prospects&search=Jenkins", response.headers["Location"])

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
        self.assertNotIn(b"<div class='error'>Player not found</div>", response.data)
        self.assertIn(b"ValuCast", response.data)

    def test_projected_rotation_starter_phrase_uses_a_rotation(self):
        phrase = app_module._projected_role_phrase({"projected_role": "rotation_starter"})
        self.assertTrue(phrase.startswith("a rotation"))


class TestPlayerCardDecisionHierarchy(unittest.TestCase):
    GUIDE = (
        "<p><strong>Skill</strong> is what the performance evidence supports. "
        "<strong>Opportunity</strong> is projected playing time, role, and availability. "
        "<strong>ValuCast Value</strong> turns both into the fantasy decision for this format. "
        "<strong>Confidence</strong> shows how stable that read is; if it is absent, "
        "ValuCast has not rated it.</p>"
    )

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def assert_reading_guide(self, body):
        self.assertIn(
            '<section class="detail-section card-reading-guide" '
            'aria-label="How to read this card">',
            body,
        )
        self.assertIn(self.GUIDE, body)
        self.assertNotIn("Bust risk", body)

    def render_mlb_without_role_or_availability(self):
        from flask import render_template
        from web.dynasty_models import DynastyRankingRow

        row = DynastyRankingRow(
            id="missing-role-mlb",
            name="Missing Role MLB",
            player_type="mlb",
            positions=("OF",),
            team="TST",
            age=27,
            dynasty_rank=1,
            dynasty_value=50.0,
            status="active",
            mlbam_id="999999",
            level="MLB",
        )
        with app.test_request_context("/player/missing-role-mlb"):
            return render_template(
                "partials/player_detail_dynasty.html",
                row=row,
                mlb_stats={"PA": 500},
            )

    def test_reading_guides_are_semantic(self):
        redraft = self.client.get(
            "/player/19755?mode=categories",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(redraft.status_code, 200)
        for body in (redraft.data.decode(), self.render_mlb_without_role_or_availability()):
            self.assert_reading_guide(body)

    def test_prospect_card_explains_the_decision_hierarchy(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next(
            (r for r in dd_store.get_all() if r.is_prospect and r.has_peak_projection),
            None,
        )
        if row is None:
            self.skipTest("No prospect rows available")
        response = self.client.get(
            f"/player/{row.id}?mode=prospects",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertTrue(row.has_peak_projection)
        self.assertIn('<span class="profile-card-kicker">Skill</span>', body)
        self.assertIn("<h4>What his performance supports</h4>", body)
        self.assertIn('<span class="profile-card-kicker">Opportunity</span>', body)
        self.assertIn("<h4>Role, playing time &amp; availability</h4>", body)
        self.assertIn("<h4>Confidence</h4>", body)
        self.assertIn(
            "scouting reference only, never used in ValuCast rank or value",
            body,
        )
        self.assertNotIn("Four-year MLB outlook.", body)
        self.assertNotIn("attribution-mix", body)
        self.assertNotIn("Peak Outlook", body)
        self.assertNotIn("<b>Ceiling scenario</b>", body)
        self.assertNotIn("<b>Floor scenario</b>", body)
        self.assertNotIn("<b>Evidence strength</b>", body)
        self.assertNotIn("<b>Peak</b>", body)
        self.assertNotIn("<b>Upside</b>", body)
        self.assertNotIn("<b>Risk</b>", body)
        self.assertNotIn("peak-trajectory-note", body)
        for item in row.peak_role_probability_items:
            self.assertNotIn(f"<span>{item['label']}</span>", body)
        self.assert_reading_guide(body)

    def test_public_scouting_adapter_hides_uncalibrated_peak_summary(self):
        public = app_module._scouting_display_report({
            "report": "Observed performance read.",
            "peak_summary": "Projection: starter with low risk.",
        })

        self.assertEqual(public["display_report"], "Observed performance read.")
        self.assertNotIn("peak_summary", public)

    def test_mlb_dynasty_card_explains_the_decision_hierarchy(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in dd_store.get_all() if not r.is_prospect), None)
        if row is None:
            self.skipTest("No MLB dynasty rows available")
        response = self.client.get(
            f"/player/{row.id}?mode=dd_dynasty",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn(
            '<span class="headline-value"><span>ValuCast Value ',
            body,
        )
        self.assertIn('<span class="headline-context">Dynasty', body)
        self.assertIn('<span class="profile-card-kicker">Skill</span>', body)
        self.assertIn("<h4>Projected performance</h4>", body)
        self.assertIn(
            "<strong>Opportunity:</strong> PA/IP show projected playing time. "
            "If role or availability is absent, ValuCast has not rated it.",
            body,
        )
        self.assertNotIn("<h4>2026 Season Outlook</h4>", body)
        self.assertIn("Projected production (Steamer)", body)
        self.assertIn("via Baseball Savant", body)
        self.assert_reading_guide(body)

    def test_mlb_dynasty_card_rates_pa_as_opportunity_without_role_or_availability(self):
        body = self.render_mlb_without_role_or_availability()

        self.assertIn('<span class="profile-card-kicker">Skill</span>', body)
        self.assertIn("<h4>Projected performance</h4>", body)
        self.assertIn(
            "<strong>Opportunity:</strong> PA/IP show projected playing time. "
            "If role or availability is absent, ValuCast has not rated it.",
            body,
        )
        self.assertIn('<span class="stat-label">PA</span>', body)
        self.assertRegex(body, r'<span class="stat-value">\s*500\s*</span>')
        self.assertNotIn('<span class="stat-label">Projected Role</span>', body)
        self.assertNotIn('<span class="stat-label">Roster Context</span>', body)

    def test_redraft_card_explains_the_decision_hierarchy(self):
        response = self.client.get(
            "/player/19755?mode=categories",
            headers={"HX-Request": "true"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.data.decode()
        self.assertIn("ValuCast Value: ", body)
        self.assertIn('<span class="profile-card-kicker">ValuCast Value</span>', body)
        self.assertIn("<h4>What this means in your league</h4>", body)
        self.assertIn('<span class="profile-card-kicker">Skill</span>', body)
        self.assertIn("<h4>Projected performance</h4>", body)
        self.assertIn(
            "<strong>Opportunity:</strong> PA/IP show projected playing time. "
            "If role or availability is absent, ValuCast has not rated it.",
            body,
        )
        self.assertIn("Rest-of-Season Projection (Steamer)", body)
        self.assertIn("via Baseball Savant", body)
        self.assert_reading_guide(body)


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

    def test_dynasty_shows_projected_stat_columns(self):
        # 7/2: the Redraft stat columns were "completely missing in the dynasty
        # section" -- the board carries them now, populated from the matched
        # projections the Category Fit panel already uses. Columns follow the
        # active category selection (default 7x7 here).
        from app import DYNASTY_DEFAULT_CATS, DYNASTY_DEFAULT_PCATS, _CAT_DISPLAY_LABELS, dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get("/?mode=dd_dynasty")
        html = response.data.decode("utf-8")
        for cat in DYNASTY_DEFAULT_CATS + DYNASTY_DEFAULT_PCATS:
            label = _CAT_DISPLAY_LABELS.get(cat, cat)
            self.assertIn(f'full-season line">{label}</th>', html)
        # At least one row renders real numbers, not just em-dash placeholders.
        self.assertIn('<td class="col-cat">', html)

    def test_dynasty_stat_columns_follow_category_selection(self):
        # 7/2: swapping presets left the stat columns frozen -- they were pinned
        # to a hardcoded tuple instead of the selected cats/pcats.
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        response = self.client.get(
            "/?mode=dd_dynasty&cats=R,HR,RBI,SB,AVG&pcats=W,SV,K,ERA,WHIP")
        html = response.data.decode("utf-8")
        self.assertIn('full-season line">W</th>', html)
        self.assertNotIn('full-season line">OPS</th>', html)
        self.assertNotIn('full-season line">K/BB</th>', html)

    def test_dynasty_preset_rerank_is_announced(self):
        # 7/3 Batch 1: preset swaps re-rank silently — "tuned to your league"
        # must be shown, not just claimed.
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        preset = self.client.get("/rankings?mode=dd_dynasty&preset=points").data.decode("utf-8")
        default = self.client.get("/rankings?mode=dd_dynasty").data.decode("utf-8")
        self.assertIn("re-ranked for points", preset)
        self.assertNotIn("re-ranked for", default)

    def test_dynasty_cutoff_divider_at_most_one_under_reordered_views(self):
        # 7/3 review: preset re-sorts make dynasty_rank non-monotonic down the
        # page, and the replacement-level divider fired on dozens of arbitrary
        # rows (41 dividers under preset=points at teams=8/roster=20).
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        for url in (
            "/rankings?mode=dd_dynasty&teams=8&roster=20",
            "/rankings?mode=dd_dynasty&teams=8&roster=20&preset=points",
            "/rankings?mode=dd_dynasty&teams=8&roster=20&preset=5x5",
        ):
            html = self.client.get(url).data.decode("utf-8")
            self.assertLessEqual(html.count('class="cutoff-row"'), 1, url)

    def test_prospect_league_rank_shows_role_prefixed_ordinals(self):
        # 7/3 review: adapter ranks are within-role (hitters 1..H, pitchers
        # 1..P) — a bare interleaved column read 1,1,2,2 like a broken rank.
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        html = self.client.get("/?mode=prospects&preset=ops_7x7&rank_by=league").data.decode("utf-8")
        if "col-league-rank" not in html:
            self.skipTest("league re-rank not active for current data")
        self.assertIn("H#1", html)
        self.assertIn("P#1", html)

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

    def test_dynasty_share_card_graphic(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        preview = self.client.get("/dynasty/share-card?limit=50")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("text/html", preview.content_type)
        self.assertIn(b"<title>ValuCast Dynasty Top 50 | ValuCast</title>", preview.data)
        self.assertIn(b"Top 50 Dynasty", preview.data)
        self.assertIn(b"/dynasty/share-card.png?limit=50", preview.data)
        for limit in (20, 50, 100):
            png = self.client.get(f"/dynasty/share-card.png?limit={limit}")
            self.assertEqual(png.status_code, 200)
            self.assertIn("image/png", png.content_type)
        index = self.client.get("/?mode=dd_dynasty").data
        self.assertIn(b"/dynasty/share-card?limit=50", index)

    def test_redraft_share_card_graphic(self):
        preview = self.client.get("/redraft/share-card?limit=50")
        self.assertEqual(preview.status_code, 200)
        self.assertIn("text/html", preview.content_type)
        self.assertIn(b"<title>ValuCast Redraft Top 50 | ValuCast</title>", preview.data)
        self.assertIn(b"Top 50 Redraft", preview.data)
        self.assertIn(b"/redraft/share-card.png?limit=50", preview.data)
        for limit in (20, 50, 100):
            png = self.client.get(f"/redraft/share-card.png?limit={limit}")
            self.assertEqual(png.status_code, 200)
            self.assertIn("image/png", png.content_type)
        index = self.client.get("/").data
        self.assertIn(b"/redraft/share-card?limit=50", index)

    def test_redraft_share_card_png_uses_redraft_as_of_for_subtitle(self):
        calls = []

        def fake_graphic(rows, **kwargs):
            calls.append(kwargs)
            return b"png"

        with patch.object(
            app_module,
            "_build_context",
            return_value={
                "mode": "categories",
                "results": [],
                "as_of": "2026-06-21T00:00:00+00:00",
            },
        ), patch.object(app_module, "_prospect_graphic_png", side_effect=fake_graphic):
            response = self.client.get("/redraft/share-card.png?limit=20")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls[0]["as_of"], "2026-06-21T00:00:00+00:00")

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

    def test_value_map_tooltip_uses_text_nodes(self):
        source = Path("templates/value_map.html").read_text(encoding="utf-8")

        self.assertNotIn("tooltip.innerHTML", source)
        self.assertIn("tooltip.replaceChildren", source)
        self.assertIn("nameEl.textContent = player.name", source)
        self.assertIn("metaEl.textContent =", source)

    def test_buys_share_card_png_and_preview(self):
        # Held-path coverage: the "returns later this week" share card + placeholder
        # render when the AOTC hold is ON (the live default is now hold off).
        import app as _app
        original = _app.AHEAD_OF_THE_CURVE_HOLD
        _app.AHEAD_OF_THE_CURVE_HOLD = True
        try:
            png = self.client.get("/buys/share-card.png")
            self.assertEqual(png.status_code, 200)
            self.assertEqual(png.data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn("image/png", png.content_type)
            self.assertIn(
                'filename="valucast-aotc-hold.png"',
                png.headers.get("Content-Disposition", ""),
            )

            preview = self.client.get("/buys/share-card")
            self.assertEqual(preview.status_code, 200)
            self.assertIn(b"Ahead of the Curve", preview.data)
            self.assertIn(b"returns later this week", preview.data)
            self.assertIn(b'property="og:image"', preview.data)
            self.assertIn(b"/buys/share-card.png", preview.data)

            buys_html = self.client.get("/buys").data
            self.assertIn(b"/buys/share-card.png", buys_html)
            self.assertIn(b"Ahead of the Curve returns later this week", buys_html)
            self.assertNotIn(b'class="buys-row"', buys_html)
        finally:
            _app.AHEAD_OF_THE_CURVE_HOLD = original

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

    def test_prospects_graphic_extended_limits_png_and_preview(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")

        top20 = self.client.get("/prospects/share-card.png?limit=20")
        self.assertEqual(top20.status_code, 200)

        for limit in (50, 100):
            png = self.client.get(f"/prospects/share-card.png?limit={limit}")
            self.assertEqual(png.status_code, 200)
            self.assertEqual(png.data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertIn("image/png", png.content_type)
            self.assertGreater(len(png.data), len(top20.data))
            self.assertIn(
                f'filename="valucast-top-{limit}-all-prospects.png"',
                png.headers.get("Content-Disposition", ""),
            )

            preview = self.client.get(f"/prospects/share-card?limit={limit}")
            self.assertEqual(preview.status_code, 200)
            self.assertIn("text/html", preview.content_type)
            self.assertIn(f"Top {limit} Prospects".encode(), preview.data)
            self.assertIn(f"/prospects/share-card.png?limit={limit}".encode(), preview.data)

    def test_graphic_support_tag_y_moves_down_for_wrapped_names(self):
        one_line_y = app_module._graphic_support_tag_y(200, 1, one_line_offset=76, wrapped_offset=92)
        wrapped_y = app_module._graphic_support_tag_y(200, 2, one_line_offset=76, wrapped_offset=92)
        self.assertEqual(one_line_y, 276)
        self.assertEqual(wrapped_y, 292)

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

    def test_prospect_player_share_card_hides_uncalibrated_peak_outlook(self):
        from PIL import ImageDraw

        from app import dd_store

        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        row = next((r for r in dd_store.get_all() if r.name == "Kade Anderson"), None)
        if row is None:
            self.skipTest("Kade Anderson not available")

        rendered = []
        original_text = ImageDraw.ImageDraw.text

        def capture_text(draw, xy, value, *args, **kwargs):
            rendered.append(str(value))
            return original_text(draw, xy, value, *args, **kwargs)

        with patch.object(ImageDraw.ImageDraw, "text", new=capture_text):
            png = app_module._prospect_player_card_png(row)

        self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
        rendered_text = " ".join(rendered)
        self.assertTrue(row.has_peak_projection)
        for label in ("PEAK OUTLOOK", "CEILING SCENARIO", "FLOOR SCENARIO"):
            self.assertNotIn(label, rendered_text)
        self.assertNotIn("BUST RISK", rendered_text)

    def test_share_graphics_do_not_embed_qr_codes(self):
        repo_root = Path(__file__).parent.parent
        app_source = (repo_root / "app.py").read_text(encoding="utf-8")
        project = (repo_root / "pyproject.toml").read_text(encoding="utf-8")
        requirements = (repo_root / "requirements.txt").read_text(encoding="utf-8")

        for marker in ("_graphic_qr", "_graphic_place_qr", "qr_url", "_qrcode"):
            self.assertNotIn(marker, app_source)
        self.assertNotIn("qrcode", project.lower())
        self.assertNotIn("qrcode", requirements.lower())

    def test_graphic_availability_badge_flags_only_real_risks(self):
        from app import _graphic_availability_badge
        from types import SimpleNamespace

        def row(status):
            return SimpleNamespace(availability_context={"status": status})

        self.assertEqual(_graphic_availability_badge(row("injured")), "INJURED")
        self.assertEqual(_graphic_availability_badge(row("rehab")), "REHAB")
        self.assertEqual(
            _graphic_availability_badge(row("stale_or_inactive")), "INACTIVE"
        )
        self.assertIsNone(_graphic_availability_badge(row("available")))
        self.assertIsNone(_graphic_availability_badge(row("thin_current_sample")))
        self.assertIsNone(
            _graphic_availability_badge(SimpleNamespace(availability_context={}))
        )

    def test_graphic_read_calls_rehab_a_rehab(self):
        from app import _graphic_read_intro
        from types import SimpleNamespace

        row = SimpleNamespace(
            age=25,
            availability_context={"status": "rehab"},
            is_prospect=True,
            level="AAA",
            metadata={},
        )

        read = _graphic_read_intro(
            row,
            "Joyce",
            "a 3.00 ERA",
            " over 12 IP",
            {"stat_line_source_kind": "current_season"},
        )

        self.assertIn("currently rehabbing", read)

    def test_prospect_detail_lists_rehab_as_availability_state(self):
        source = Path("templates/partials/player_detail_dynasty.html").read_text(
            encoding="utf-8"
        )

        self.assertIn("('injured', 'rehab', 'stale_or_inactive')", source)

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

    def test_prospect_player_card_read_prefers_valid_scouting_report(self):
        from types import SimpleNamespace

        from app import _prospect_player_card_read

        row = SimpleNamespace(
            name="Franklin Arias",
            age=20,
            level="AA",
            stat_line={
                "avg": 0.307,
                "obp": 0.393,
                "slg": 0.559,
                "ops": 0.952,
                "iso": 0.252,
                "k_pct": 13.2,
                "bb_pct": 10.7,
                "pa": 234,
            },
        )
        read = _prospect_player_card_read(
            row,
            {
                "ops": 96,
                "iso": 94,
                "k_pct": 97,
                "avg": 94,
                "obp": 85,
                "slg": 96,
                "bb_pct": 41,
            },
            {"stat_line_sample": 234, "stat_line_sample_unit": "PA"},
            scouting_report={
                "report": "Deterministic report.",
                "report_llm": {
                    "valid": True,
                    "text": "Arias owns the zone and gets to power without selling out.",
                },
            },
        )

        self.assertEqual(
            read,
            "Arias owns the zone and gets to power without selling out.",
        )

    def test_player_card_share_read_clamps_long_reports_cleanly(self):
        from PIL import Image, ImageDraw

        from app import _graphic_font, _graphic_wrap_read_text

        draw = ImageDraw.Draw(Image.new("RGB", (1080, 1350)))
        font = _graphic_font(22)
        long_report = (
            "Franklin Arias is a 20-year-old shortstop showing elite bat speed "
            "and power projection; his .252 ISO at AA ranks in the 94th percentile "
            "of the ValuCast hitter pool, and he's maintaining a .307 average with "
            "a .393 OBP across 234 plate appearances this season. The primary risk "
            "is swing-and-miss: his 13.2 K% in the current sample can still stretch "
            "against better pitching, so the profile needs continued contact proof."
        )

        lines = _graphic_wrap_read_text(draw, long_report, font, 890, max_lines=4)

        self.assertLessEqual(len(lines), 4)
        rendered = " ".join(lines)
        self.assertNotRegex(rendered, r"\b(in|the|and|of|a|an|to|with|his|her)$")
        self.assertTrue(rendered.endswith((".", "!", "?", "...")))

    def test_player_card_sample_context_shows_current_and_combined_samples(self):
        from types import SimpleNamespace

        from app import _graphic_sample_context_label

        row = SimpleNamespace(
            level="AA",
            sample_context_label="Combined 2026 line - AA+A+ - 177 PA",
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
            "Combined 2026 line - AA+A+ - 177 PA",
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
            self.assertIn(b'id="preset-value-panel"', response.data)
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


class TestRedraftPitcherAnchor(unittest.TestCase):
    def _result(self, player_id, name, pool, total_value, positions=(), metadata=None):
        from league_values.models import PlayerProjection, ValuationResult

        return ValuationResult(
            player=PlayerProjection.from_dict({
                "id": player_id,
                "name": name,
                "pool": pool,
                "positions": positions,
                "stats": {},
                "metadata": metadata or {},
            }),
            total_value=total_value,
            raw_values={"K": 1.0},
            z_scores={"K": 2.0},
            category_values={"K": 3.0},
        )

    def test_apply_redraft_pitcher_anchor_only_demotes_positive_pitchers(self):
        positive_pitcher = self._result("p1", "Positive Pitcher", "pitcher", 10.0)
        negative_pitcher = self._result("p2", "Negative Pitcher", "pitcher", -6.0)
        hitter = self._result("h1", "Hitter", "hitter", 10.0)

        anchored = app_module._apply_redraft_pitcher_anchor(
            [positive_pitcher, negative_pitcher, hitter]
        )

        self.assertAlmostEqual(anchored[0].total_value, 9.2)
        self.assertIs(anchored[0].category_values, positive_pitcher.category_values)
        self.assertIs(anchored[0].z_scores, positive_pitcher.z_scores)
        self.assertIs(anchored[1], negative_pitcher)
        self.assertIs(anchored[2], hitter)

    def test_redraft_board_anchor_can_move_comparable_hitter_above_pitcher(self):
        from league_values.models import PlayerProjection
        from werkzeug.datastructures import ImmutableMultiDict

        players = [
            PlayerProjection.from_dict({
                "id": "elite-hitter",
                "name": "Elite Hitter",
                "pool": "hitter",
                "positions": ("OF",),
                "stats": {"PA": 550, "HR": 45},
            }),
            PlayerProjection.from_dict({
                "id": "floor-hitter",
                "name": "Floor Hitter",
                "pool": "hitter",
                "positions": ("OF",),
                "stats": {"PA": 550, "HR": 0},
            }),
            PlayerProjection.from_dict({
                "id": "elite-pitcher",
                "name": "Elite Pitcher",
                "pool": "pitcher",
                "positions": ("SP",),
                "stats": {"IP": 180, "K": 205},
            }),
            PlayerProjection.from_dict({
                "id": "floor-pitcher",
                "name": "Floor Pitcher",
                "pool": "pitcher",
                "positions": ("SP",),
                "stats": {"IP": 180, "K": 0},
            }),
        ]

        class FakeStore:
            player_count = len(players)
            as_of = "test"

            def get_all(self):
                return players

        args = ImmutableMultiDict([
            ("cats", "HR"),
            ("pcats", "K"),
            ("w_K", "1.05"),
        ])
        with patch.object(app_module, "_active_store", return_value=FakeStore()):
            ctx = app_module._build_context(args)

        raw_results = app_module._merge_two_way_players(
            app_module.engine.value_players(players, ctx["config"])
        )
        raw_pitcher = next(r for r in raw_results if r.player.id == "elite-pitcher")
        raw_hitter = next(r for r in raw_results if r.player.id == "elite-hitter")
        anchored_pitcher = next(
            r for r in ctx["results"] if r.player.id == "elite-pitcher"
        )
        anchored_hitter = next(
            r for r in ctx["results"] if r.player.id == "elite-hitter"
        )

        self.assertGreater(raw_pitcher.total_value, raw_hitter.total_value)
        self.assertLess(anchored_pitcher.total_value, raw_pitcher.total_value)
        self.assertGreaterEqual(anchored_hitter.total_value, anchored_pitcher.total_value)
        self.assertLessEqual(
            ctx["overall_ranks"]["elite-hitter"],
            ctx["overall_ranks"]["elite-pitcher"],
        )

    def test_redraft_value_players_merges_two_way_before_anchor(self):
        hitter = self._result(
            "shohei_H", "Shohei", "hitter", 10.0, metadata={"base_id": "shohei"}
        )
        pitcher = self._result(
            "shohei_P", "Shohei", "pitcher", 5.0,
            positions=("SP",), metadata={"base_id": "shohei"}
        )

        with patch.object(app_module.engine, "value_players", return_value=[pitcher, hitter]):
            results = app_module._redraft_value_players([], object())

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].player.pool, app_module.PlayerPool.HITTER)
        self.assertAlmostEqual(results[0].total_value, 15.0)


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

    def test_inactive_projection_only_player_not_readded_by_search(self):
        # Search can bypass PA/IP floors, but not official inactive/rehab context.
        # Pick a currently-inactive projection-only player DYNAMICALLY so this
        # never drifts when someone comes off the IL (Jason Foley did on 7/13).
        from app import (
            store, _mlb_availability_by_id, _mlbam_id,
            _has_current_actual_stats, _PROJECTION_ONLY_UNAVAILABLE_STATUSES,
        )
        byid = _mlb_availability_by_id()
        inactive = next(
            (p for p in store.get_all()
             if getattr(p, "name", None)
             and not _has_current_actual_stats(p)
             and str((byid.get(_mlbam_id(p)) or {}).get("status") or "").lower()
                 in _PROJECTION_ONLY_UNAVAILABLE_STATUSES),
            None,
        )
        if inactive is None:
            self.skipTest("no inactive projection-only player in current data")
        response = self.client.get("/?search=" + inactive.name.replace(" ", "+"))
        self.assertNotIn(
            f"Add {inactive.name} to compare".encode(), response.data)

    def test_qualifying_player_still_shown(self):
        # End-to-end sanity: a real everyday player still appears by default.
        response = self.client.get("/")
        self.assertIn(b"Ohtani", response.data)

    def test_two_way_detail_value_matches_ranking(self):
        # Ohtani (19755) is two-way; detail/compare must merge like the ranking.
        from app import _redraft_value_players, _valuation_players
        from web.config_builder import build_config
        cfg = build_config(
            mode="categories", cats=None, pcats=None, rules_str="",
            pt_params=None, split_rp=False, weights=None,
        )
        ranking = _redraft_value_players(_valuation_players(), cfg)
        rank_val = next(r.total_value for r in ranking if r.player.id == "19755")
        detail = _redraft_value_players(_valuation_players({"19755"}), cfg)
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
        csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("default-src 'self'", csp)
        # Fonts are self-hosted (plan 008): no Google origins anywhere in the CSP.
        self.assertNotIn("fonts.googleapis.com", csp)
        self.assertNotIn("fonts.gstatic.com", csp)
        # Directives still present, now scoped to 'self'.
        self.assertIn("style-src 'self' 'unsafe-inline'", csp)
        self.assertIn("font-src 'self' data:", csp)

    def test_self_hosted_font_is_served(self):
        r = self.client.get("/static/fonts/Archivo[wght].woff2")
        self.assertEqual(r.status_code, 200)
        self.assertIn("font", r.headers.get("Content-Type", ""))

    def test_html_is_gzipped_when_requested(self):
        r = self.client.get("/", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(r.headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", r.headers.get("Vary", ""))

    def test_png_responses_are_publicly_cacheable(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        r = self.client.get("/prospects/share-card.png?limit=20")
        self.assertEqual(r.status_code, 200)
        # 10 min (7/2): 6h edge caching served stale share cards after layout
        # fixes and held yesterday's board past the daily refresh.
        self.assertEqual(r.headers.get("Cache-Control"), "public, max-age=600")


def test_prospects_board_flags_rookie_eligible_players_with_prior_mlb_taste():
    """7/1: a cup-of-coffee call-up (e.g. Carson Whisenhunt, recalled then optioned
    right back down) still ranks as a prospect -- correctly, per MLB's rookie-service
    rule -- but without any indicator, it can look like the board doesn't know he's
    already touched the majors. Surface it instead of hiding it."""
    client = app.test_client()
    html = client.get("/?mode=prospects").data.decode("utf-8")
    idx = html.find("Whisenhunt")
    assert idx != -1, "Whisenhunt should still be on the prospects board"
    row_html = html[idx:idx + 2000]
    # Live-data test: the chip family upgrades as his status changes ("MLB taste"
    # when previously optioned back down; "Called up"/"In MLB" while on an active
    # roster, as on 7/9 when the afternoon pulse caught his recall). The invariant
    # is that a rookie-eligible player with MLB time is never rendered unmarked.
    assert (
        "MLB taste" in row_html or "Called up" in row_html or "In MLB" in row_html
    ), "Whisenhunt must carry a call-up family chip"
    assert "callup-chip" in row_html


class _GateOverrideStore:
    """Wraps the real served store, delegating everything (rows, generated_at,
    filter, ...) but overriding only the two surface-gate dicts the banner reads."""

    def __init__(self, real, surface_readiness, surface_blockers):
        self._real = real
        self._surface_readiness = surface_readiness
        self._surface_blockers = surface_blockers

    @property
    def surface_readiness(self):
        return self._surface_readiness

    @property
    def surface_blockers(self):
        return self._surface_blockers

    def __getattr__(self, name):
        return getattr(self._real, name)


def _prospect_ctx_with_gate(monkeypatch, surface_readiness, surface_blockers):
    """Drive _apply_prospect_board_context with a served store whose surface
    readiness/blockers are swapped, keeping the real row path intact."""
    from werkzeug.datastructures import ImmutableMultiDict

    fake = _GateOverrideStore(app_module.dd_store, surface_readiness, surface_blockers)
    monkeypatch.setattr(app_module, "dd_store", fake)
    args = ImmutableMultiDict([("mode", "prospects")])
    ctx = app_module._build_dynasty_context(args)
    app_module._apply_prospect_board_context(ctx, args)
    return ctx


def test_prospect_gate_banner_fires_when_surface_not_ready(monkeypatch):
    """7/9 claims-register gap (a): the per-surface readiness verdict must bind on
    the served board -- when surface_readiness.prospects is False, the board says
    'Preliminary -- publication gate not met: <blocker>' instead of shipping as if
    it passed."""
    blocker = "Top prospect board is too pitcher-heavy for public promotion."
    ctx = _prospect_ctx_with_gate(
        monkeypatch,
        {"dynasty": True, "prospects": False},
        {"prospects": [blocker]},
    )
    notice = ctx.get("prospect_gate_notice")
    assert notice, "banner must fire when the prospects surface gate is False"
    assert "Preliminary" in notice
    assert "pitcher-heavy" in notice


def test_prospect_gate_banner_silent_when_ready_or_unknown(monkeypatch):
    """The banner uses `is False`, not falsy: a passing gate (True) or a MISSING
    prospects key (older schema / unavailable store) must NOT raise a spurious
    'gate not met' notice."""
    ctx_ready = _prospect_ctx_with_gate(
        monkeypatch, {"dynasty": True, "prospects": True}, {}
    )
    assert not ctx_ready.get("prospect_gate_notice")

    ctx_absent = _prospect_ctx_with_gate(monkeypatch, {"dynasty": True}, {})
    assert not ctx_absent.get("prospect_gate_notice")


class TestBulletproofing(unittest.TestCase):
    """7/2 hardening batch: input abuse, cache-key abuse, staleness honesty."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_points_params_garbage_does_not_500(self):
        r = self.client.get("/?mode=points&pt_HR=abc")
        self.assertEqual(r.status_code, 200)

    def test_points_params_nonfinite_are_dropped(self):
        # inf/nan parse as floats; the isfinite guard must drop them before
        # they poison the valuation. (Board renders 200 with defaults.)
        r = self.client.get("/?mode=points&pt_HR=inf&pt_R=nan")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn(b"$nan", r.data.lower())
        self.assertNotIn(b"$inf", r.data.lower())

    def test_share_prospects_bad_n_does_not_500(self):
        r = self.client.get("/share/prospects/SS.png?n=abc")
        self.assertIn(r.status_code, (200, 404))  # bad param never a 500

    def test_png_cache_key_ignores_junk_params(self):
        from app import _png_cache_key
        with app.test_request_context("/movers/share-card.png?limit=20&z=1&junk=x"):
            noisy = _png_cache_key()
        with app.test_request_context("/movers/share-card.png?limit=20"):
            clean = _png_cache_key()
        self.assertEqual(noisy, clean)

    def test_png_cache_key_ignores_junk_prefix_params(self):
        # w_junk/pt_junk suffixes must NOT fold into the key -- keying on the
        # bare w_/pt_ prefix let `?w_junk1=1&w_junk2=1...` mint unlimited keys
        # (guaranteed miss + full render per request, evicting all 32 real
        # entries). Unknown suffixes now collapse to the canonical key.
        from app import _png_cache_key
        with app.test_request_context(
            "/dynasty/share-card.png?limit=20&w_zzz=1&w_zzz2=3&pt_bogus=9"
        ):
            noisy = _png_cache_key()
        with app.test_request_context("/dynasty/share-card.png?limit=20"):
            clean = _png_cache_key()
        self.assertEqual(noisy, clean)

    def test_png_cache_key_honors_legit_weight_suffixes(self):
        # A real category weight IS render-affecting: it must stay in the key so
        # two legitimately different cards don't collapse to one cached image.
        from app import _png_cache_key
        with app.test_request_context("/dynasty/share-card.png?limit=20&w_HR=2"):
            w2 = _png_cache_key()
        with app.test_request_context("/dynasty/share-card.png?limit=20&w_HR=3"):
            w3 = _png_cache_key()
        with app.test_request_context("/dynasty/share-card.png?limit=20"):
            base = _png_cache_key()
        self.assertNotEqual(w2, w3)   # different weight -> different key
        self.assertNotEqual(w2, base)  # weighted -> distinct from unweighted

    def test_png_cache_key_honors_legit_point_suffixes(self):
        # A real point-rule stat (incl. points-UI stats like pt_QS/pt_HLD that
        # aren't in the default preset) is render-affecting and must key.
        from app import _png_cache_key
        with app.test_request_context(
            "/dynasty/share-card.png?mode=points&pt_HR=4"
        ):
            p4 = _png_cache_key()
        with app.test_request_context(
            "/dynasty/share-card.png?mode=points&pt_HR=5"
        ):
            p5 = _png_cache_key()
        with app.test_request_context(
            "/dynasty/share-card.png?mode=points&pt_QS=2"
        ):
            pqs = _png_cache_key()
        self.assertNotEqual(p4, p5)
        self.assertNotEqual(p4, pqs)

    def test_unknown_pt_stat_is_render_inert_and_collapses_key(self):
        # pt_AB names a REAL key in player.stats -- the engine's
        # `stats.get(rule.stat)` would score it -- but AB is outside
        # _POINT_STAT_IDS, so the cache collapses `?pt_AB=1` to the canonical
        # key. If the parse KEPT it, the differently-rendered card would be
        # cached under the canonical key and served to every legit request
        # (cache poisoning). The parse must drop it so the collapse is sound.
        from werkzeug.datastructures import MultiDict
        from app import _build_context, _png_cache_key

        poisoned = _build_context(MultiDict({"mode": "points", "pt_AB": "1"}))
        clean = _build_context(MultiDict({"mode": "points"}))
        self.assertEqual(poisoned["pt_params"], clean["pt_params"])  # AB dropped
        self.assertEqual(  # identical board, not just identical params
            [(r.player.name, r.total_value) for r in poisoned["results"][:25]],
            [(r.player.name, r.total_value) for r in clean["results"][:25]],
        )
        kept = _build_context(MultiDict({"mode": "points", "pt_HR": "4"}))
        self.assertEqual(kept["pt_params"], {"HR": 4.0})  # legit stat still parses

        with app.test_request_context(
            "/dynasty/share-card.png?mode=points&pt_AB=1"
        ):
            noisy = _png_cache_key()
        with app.test_request_context("/dynasty/share-card.png?mode=points"):
            canonical = _png_cache_key()
        self.assertEqual(noisy, canonical)

    def test_maybe_cache_png_store_survives_emptied_cache(self):
        # Regression for the thread race: the store path used to do
        # `_PNG_CACHE[key]=...` then `move_to_end(key)`; a concurrent pop between
        # them raised KeyError inside after_request -> a 500 on an already-valid
        # PNG. The locked pop+insert must never touch an absent key.
        import app as app_module

        try:
            was_testing = app.config.get("TESTING")
            app.config["TESTING"] = False
            app_module._PNG_CACHE.clear()
            with app.test_request_context("/dynasty/share-card.png?limit=20"):
                resp = app_module.make_response(b"\x89PNG\r\n\x1a\npayload")
                resp.headers["Content-Type"] = "image/png"
                # Simulate a concurrent pop having already emptied the dict:
                app_module._PNG_CACHE.clear()
                out = app_module._maybe_cache_png(resp)  # must not raise
            self.assertEqual(out.status_code, 200)
            self.assertEqual(len(app_module._PNG_CACHE), 1)
        finally:
            app_module._PNG_CACHE.clear()
            app.config["TESTING"] = was_testing

    def test_ready_but_ancient_snapshot_wears_the_stale_label(self):
        # "Ready" is baked in at build time and says nothing about age: a
        # broken refresh must not serve week-old values labeled current.
        from app import _select_dynasty_store

        class _Candidate:
            is_available = True
            dynasty_ready = True
            generated_at = "2020-01-01T00:00:00+00:00"

        _, source = _select_dynasty_store(_Candidate(), use_public_snapshot=True)
        self.assertEqual(source, "valucast_public_snapshot_stale")

    def test_ready_fresh_snapshot_serves_normally(self):
        from datetime import date
        from app import _select_dynasty_store

        class _Candidate:
            is_available = True
            dynasty_ready = True
            generated_at = date.today().isoformat()

        _, source = _select_dynasty_store(_Candidate(), use_public_snapshot=True)
        self.assertEqual(source, "valucast_public_snapshot")

    def test_buys_graphic_empty_rows_degrade_not_500(self):
        from flask import render_template
        with app.test_request_context("/buys"):
            html = render_template(
                "partials/_buys_graphic.html",
                graphic_rows=[], buy_source_label="ValuCast", dd_generated_at=None,
            )
        self.assertIn("No buy signals", html)



class TestIneligiblePlayers(unittest.TestCase):
    """Manual ineligible list (data/manual/ineligible_players.json): restricted-list
    players carry no roster/IL status in the availability feeds, so nothing
    upstream excludes them and their stale projections keep generating value.
    7/12: Emmanuel Clase (MLB restricted list) surfaced on board search — the
    always_keep search path retains sub-threshold players past the playing-time
    filter, so the ineligible gate must sit after it."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_manual_list_loads(self):
        from app import _ineligible_mlbam_ids
        self.assertIn("661403", _ineligible_mlbam_ids())

    def test_ineligible_player_never_reaches_a_board_surface(self):
        body = self.client.get("/rankings?mode=categories&search=Clase").data.decode()
        self.assertNotIn("Emmanuel", body)
        self.assertIn("Jonatan", body)   # same-surname ACTIVE player must survive
        payload = self.client.get("/api/value-map-players").data.decode()
        self.assertNotIn("Emmanuel Clase", payload)


class TestTradeAnalyzer(unittest.TestCase):
    """Free /trade page (plan 022): two-sided verdict from served values plus the
    three non-negotiable honesty features and the PNG cache poisoning guard."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    @staticmethod
    def _row(value, is_prospect=False):
        from types import SimpleNamespace
        return SimpleNamespace(dynasty_value=value, is_prospect=is_prospect)

    # --- Step 1: the pure verdict function -------------------------------
    def test_verdict_inside_noise_calls_it_even(self):
        from app import _trade_verdict
        v = _trade_verdict([self._row(80)], [self._row(82)])  # margin 2 <= 9
        self.assertTrue(v["inside_noise"])
        self.assertIn("call it even", v["headline"])
        self.assertIsNone(v["favored_side"])

    def test_verdict_clear_margin_names_a_winner(self):
        from app import _trade_verdict
        v = _trade_verdict([self._row(80)], [self._row(95)])  # margin 15 > 9
        self.assertFalse(v["inside_noise"])
        self.assertEqual(v["favored_side"], "get")
        self.assertNotIn("call it even", v["headline"])

    def test_verdict_band_boundary_is_inclusive(self):
        # margin == noise is INSIDE; margin == noise + 0.1 is OUTSIDE.
        from app import _trade_verdict, _TRADE_NOISE_PER_PLAYER
        band = _TRADE_NOISE_PER_PLAYER  # n == 1 here
        at = _trade_verdict([self._row(50)], [self._row(50 + band)])
        just_over = _trade_verdict([self._row(50)], [self._row(50 + band + 0.1)])
        self.assertTrue(at["inside_noise"])
        self.assertFalse(just_over["inside_noise"])

    def test_verdict_band_scales_with_side_size(self):
        # A 2-for-2 gets a wider band (noise = 9 * 2) than a 1-for-1.
        from app import _trade_verdict
        v = _trade_verdict(
            [self._row(50), self._row(50)],
            [self._row(58), self._row(58)],   # margin 16 <= 18
        )
        self.assertTrue(v["inside_noise"])

    def test_verdict_count_mismatch_flag(self):
        from app import _trade_verdict
        v = _trade_verdict([self._row(40), self._row(40)], [self._row(85)])
        self.assertTrue(v["count_mismatch"])
        even = _trade_verdict([self._row(40)], [self._row(41)])
        self.assertFalse(even["count_mismatch"])

    def test_verdict_cross_universe_flag(self):
        from app import _trade_verdict
        mixed = _trade_verdict(
            [self._row(80, is_prospect=False)],
            [self._row(70, is_prospect=True)],
        )
        self.assertTrue(mixed["crosses_universes"])
        same = _trade_verdict([self._row(80)], [self._row(70)])
        self.assertFalse(same["crosses_universes"])

    def test_verdict_can_sum_supplied_values_without_changing_default(self):
        from app import _trade_verdict
        give = self._row(80)
        get = self._row(95)
        self.assertEqual(_trade_verdict([give], [get])["margin"], 15.0)
        custom = {id(give): 10.0, id(get): 30.0}
        self.assertEqual(
            _trade_verdict(
                [give], [get], value_of=lambda row: custom[id(row)]
            )["margin"],
            20.0,
        )

    def test_trade_league_depth_changes_adjusted_totals(self):
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store

        mlb = sorted(
            (
                row for row in dd_store.get_all()
                if not row.is_prospect and row.dynasty_value
            ),
            key=lambda row: row.dynasty_value,
            reverse=True,
        )
        common = [("league", "1"), ("give", mlb[0].id), ("get", mlb[1].id)]
        shallow = _build_trade_page_context(
            MultiDict(common + [("teams", "4"), ("roster", "10")])
        )
        deep = _build_trade_page_context(
            MultiDict(common + [("teams", "20"), ("roster", "50")])
        )

        self.assertTrue(shallow["league_context"]["enabled"])
        self.assertNotEqual(
            shallow["league_context"]["replacement_value"],
            deep["league_context"]["replacement_value"],
        )
        self.assertNotEqual(
            shallow["verdict"]["give_total"], deep["verdict"]["give_total"]
        )
        self.assertNotEqual(
            shallow["verdict"]["get_total"], deep["verdict"]["get_total"]
        )

    def test_trade_mlb_preset_uses_preset_values(self):
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store

        candidates = [
            row for row in dd_store.get_all()
            if not row.is_prospect
            and row.value_for("7x7_ops") != row.dynasty_value
        ]
        give, get = candidates[:2]
        ctx = _build_trade_page_context(MultiDict([
            ("league", "1"),
            ("teams", "12"),
            ("roster", "26"),
            ("preset", "7x7_ops"),
            ("give", give.id),
            ("get", get.id),
        ]))
        replacement = ctx["league_context"]["replacement_value"]

        self.assertTrue(ctx["league_context"]["preset_applied"])
        # The app subtracts the UNROUNDED replacement (app.py `value_of`) but
        # exposes replacement_value rounded to 1dp, and rounds each piece
        # value to 1dp as well — so recomputing from the exposed replacement
        # can differ by up to 0.05 (replacement rounding) + 0.05 (piece
        # rounding) = 0.10 on rounding-boundary days (first tripped by the
        # 2026-07-30 refresh data). Assert within that combined
        # display-rounding bound instead of exact equality.
        self.assertAlmostEqual(
            ctx["give_pieces"][0]["value"],
            max(0.0, give.value_for("7x7_ops") - replacement),
            delta=0.101,
        )
        self.assertAlmostEqual(
            ctx["get_pieces"][0]["value"],
            max(0.0, get.value_for("7x7_ops") - replacement),
            delta=0.101,
        )

    def test_trade_mixed_preset_falls_back_for_every_piece(self):
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store

        rows = dd_store.get_all()
        mlb = next(
            row for row in rows
            if not row.is_prospect
            and row.value_for("7x7_ops") != row.dynasty_value
        )
        prospect = next(row for row in rows if row.is_prospect)
        common = [
            ("league", "1"),
            ("teams", "12"),
            ("roster", "26"),
            ("give", mlb.id),
            ("get", prospect.id),
        ]
        base = _build_trade_page_context(MultiDict(common))
        requested = _build_trade_page_context(
            MultiDict(common + [("preset", "7x7_ops")])
        )

        self.assertFalse(requested["league_context"]["preset_applied"])
        self.assertTrue(requested["league_context"]["preset_fell_back"])
        self.assertEqual(requested["give_pieces"], base["give_pieces"])
        self.assertEqual(requested["get_pieces"], base["get_pieces"])
        self.assertEqual(requested["verdict"], base["verdict"])

    def test_trade_window_and_prospect_slots_do_not_change_values(self):
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store

        give, get = dd_store.get_all()[:2]
        common = [
            ("league", "1"),
            ("teams", "12"),
            ("roster", "26"),
            ("give", give.id),
            ("get", get.id),
        ]
        balanced = _build_trade_page_context(
            MultiDict(common + [("pslots", "5"), ("window", "balanced")])
        )
        changed = _build_trade_page_context(
            MultiDict(common + [("pslots", "20"), ("window", "rebuild")])
        )

        self.assertEqual(balanced["give_pieces"], changed["give_pieces"])
        self.assertEqual(balanced["get_pieces"], changed["get_pieces"])
        self.assertEqual(balanced["verdict"], changed["verdict"])

    def test_trade_invalid_league_settings_fail_closed(self):
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store

        give, get = dd_store.get_all()[:2]
        ctx = _build_trade_page_context(MultiDict([
            ("league", "1"),
            ("teams", "abc"),
            ("roster", "999"),
            ("pslots", "-3"),
            ("preset", "invented"),
            ("window", "tomorrow"),
            ("give", give.id),
            ("get", get.id),
        ]))
        league = ctx["league_context"]

        self.assertEqual(league["teams"], 12)
        self.assertEqual(league["roster"], 50)
        self.assertEqual(league["pslots"], 0)
        self.assertIsNone(league["preset"])
        self.assertFalse(league["preset_applied"])
        self.assertEqual(league["window"], "balanced")

    # --- Step 2/5: the route -------------------------------------------
    def test_trade_empty_state_renders_search(self):
        r = self.client.get("/trade")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode()
        self.assertIn("/api/value-map-players", body)
        self.assertIn("search", body.lower())
        # free-forever framing is on the page copy
        self.assertIn("free, like every ValuCast number", body)

    def test_trade_scope_note_on_empty_result_and_preview(self):
        from app import dd_store
        scope = (
            "Player-only verdict: draft picks, FAAB, roster spots, and league "
            "context are not included."
        )
        self.assertIn(scope, self.client.get("/trade").data.decode())

        give, get = dd_store.get_all()[:2]
        query = f"give={give.id}&get={get.id}"
        result = self.client.get(f"/trade?{query}").data.decode()
        self.assertGreaterEqual(result.count(scope), 2)
        preview = self.client.get(f"/trade/share-card?{query}").data.decode()
        self.assertIn(scope, preview)

    def test_trade_v2_form_renders_canonical_clamped_state(self):
        body = self.client.get(
            "/trade?league=1&teams=99&roster=2&pslots=999"
            "&preset=invented&window=tomorrow"
        ).data.decode()

        self.assertIn('name="league" value="1"', body)
        self.assertRegex(body, r'name="teams"[^>]*value="20"')
        self.assertRegex(body, r'name="roster"[^>]*value="10"')
        self.assertRegex(body, r'name="pslots"[^>]*value="20"')
        self.assertRegex(body, r'<option value="balanced"[^>]*selected')
        self.assertNotRegex(body, r'<option value="invented"[^>]*selected')
        self.assertNotIn("League-aware version coming", body)

    def test_trade_v2_result_shows_summary_and_fallback_disclosures(self):
        from app import dd_store

        rows = dd_store.get_all()
        mlb = next(row for row in rows if not row.is_prospect)
        prospect = next(row for row in rows if row.is_prospect)
        body = self.client.get(
            f"/trade?league=1&teams=12&roster=26&pslots=5"
            f"&preset=7x7_ops&window=contend&give={mlb.id}&get={prospect.id}"
        ).data.decode()

        self.assertIn(
            "12 teams · 26 roster spots · 5 prospect slots · "
            "7x7 OPS · Contending",
            body,
        )
        self.assertIn("Scoring preset not applied:", body)
        self.assertIn(
            "Prospect slots are roster-depth context only and do not change "
            "the totals.",
            body,
        )
        self.assertIn(
            "Competitive window is context only and does not change the totals.",
            body,
        )

    def test_trade_v2_mlb_result_labels_applied_preset(self):
        from app import dd_store

        mlb = [row for row in dd_store.get_all() if not row.is_prospect][:2]
        body = self.client.get(
            f"/trade?league=1&preset=5x5&give={mlb[0].id}&get={mlb[1].id}"
        ).data.decode()

        self.assertIn("Scoring preset applied to every player.", body)
        self.assertNotIn("Scoring preset not applied:", body)

    def test_trade_v2_share_links_preserve_canonical_state(self):
        import html
        import re
        from urllib.parse import parse_qs, urlparse
        from app import dd_store

        give, get = dd_store.get_all()[:2]
        body = self.client.get(
            f"/trade?league=1&teams=12&roster=26&pslots=5"
            f"&preset=7x7_ops&window=contend&give={give.id}&get={get.id}"
        ).data.decode()
        href = html.unescape(re.search(
            r'href="([^"]*/trade/share-card\.png\?[^"]+)"',
            body,
        ).group(1))

        self.assertEqual(
            parse_qs(urlparse(href).query, keep_blank_values=True),
            {
                "league": ["1"],
                "teams": ["12"],
                "roster": ["26"],
                "pslots": ["5"],
                "preset": ["7x7_ops"],
                "window": ["contend"],
                "give": [give.id],
                "get": [get.id],
            },
        )

    def test_trade_v2_js_preserves_context_when_players_change(self):
        body = self.client.get(
            "/trade?league=1&teams=16&roster=30&pslots=8"
            "&preset=5x5&window=rebuild"
        ).data.decode()

        self.assertIn("var tradeParams =", body)
        self.assertIn('"league": "1"', body)
        self.assertIn('"teams": "16"', body)
        self.assertIn("new URLSearchParams(tradeParams)", body)

    def test_trade_v2_search_labels_picker_numbers_as_base_values(self):
        body = self.client.get("/trade?league=1").data.decode()
        self.assertIn('var searchValuePrefix = "Base value ";', body)

    def test_trade_from_params_renders_verdict(self):
        from app import dd_store
        rows = dd_store.get_all()
        mlb = next(x for x in rows if not x.is_prospect)
        pros = next(x for x in rows if x.is_prospect)
        r = self.client.get(f"/trade?give={mlb.id}&get={pros.id}")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode()
        # 4c cross-universe disclosure + methodology link (mlb + prospect mix)
        self.assertIn("comparable in ballpark, not to the decimal", body)
        self.assertIn("/methodology#dynasty-value-scale", body)

    def test_trade_inside_noise_shows_no_false_winner(self):
        # Two near-identical MLB values -> "call it even", never a winner headline.
        from app import dd_store
        mlbs = sorted(
            (x for x in dd_store.get_all() if not x.is_prospect and x.dynasty_value),
            key=lambda x: -x.dynasty_value,
        )
        pair = next(
            (mlbs[i], mlbs[i + 1]) for i in range(len(mlbs) - 1)
            if abs(mlbs[i].dynasty_value - mlbs[i + 1].dynasty_value) <= 3
        )
        r = self.client.get(f"/trade?give={pair[0].id}&get={pair[1].id}")
        body = r.data.decode()
        self.assertIn("call it even", body)
        self.assertNotIn("You come out ahead", body)
        self.assertNotIn("You give up more than you get", body)

    def test_trade_count_mismatch_note(self):
        from app import dd_store
        mlbs = [x for x in dd_store.get_all() if not x.is_prospect and x.dynasty_value]
        give = f"{mlbs[30].id},{mlbs[42].id}"
        get = mlbs[4].id
        r = self.client.get(f"/trade?give={give}&get={get}")
        self.assertEqual(r.status_code, 200)
        self.assertIn("different player counts", r.data.decode())

    def test_trade_junk_ids_dropped_not_fatal(self):
        from app import dd_store
        real = dd_store.get_all()[0].id
        r = self.client.get(f"/trade?give=nonsense123,{real}")
        self.assertEqual(r.status_code, 200)

    def test_trade_side_cap_at_six(self):
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store
        ids = ",".join(r.id for r in dd_store.get_all()[:8])
        ctx = _build_trade_page_context(MultiDict([("give", ids), ("get", "")]))
        self.assertEqual(len(ctx["give_pieces"]), 6)

    def test_trade_one_sided_never_renders_a_verdict(self):
        # 7/12 audit F7: give-only input renders the add-players empty state,
        # never "You give up more than you get" against an empty side.
        from app import dd_store
        real = dd_store.get_all()[0].id
        r = self.client.get(f"/trade?give={real}")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode()
        self.assertIn("Add at least one player to each side", body)
        self.assertNotIn("You give up more than you get", body)
        self.assertNotRegex(body, r"YOU GIVE\s*&middot;\s*</h2>")
        # ...and the directly-fetchable PNG refuses to draw the same non-trade.
        png = self.client.get(f"/trade/share-card.png?give={real}")
        self.assertEqual(png.status_code, 404)

    def test_trade_same_player_both_sides_cancels_to_empty(self):
        # 7/12 audit F8 (degenerate case): give A / get A is no trade at all
        # once the duplicate cancels -- empty state, not a padded noise band.
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store
        a, b = dd_store.get_all()[:2]
        ctx = _build_trade_page_context(
            MultiDict([("give", a.id), ("get", f"{a.id},{b.id}")]))
        self.assertEqual(ctx["give_ids"], [])
        self.assertEqual(ctx["get_ids"], [b.id])
        self.assertIsNone(ctx["verdict"])          # one side left -> no verdict

    def test_trade_cross_side_cancel_scores_the_real_remainder(self):
        # 7/12 audit F8: give A,C / get A,B is really C-for-B. The duplicate
        # must not survive to widen the band (2v2 = +/-18) around a 1v1 trade.
        from werkzeug.datastructures import MultiDict
        from app import _build_trade_page_context, dd_store
        a, b, c = dd_store.get_all()[:3]
        ctx = _build_trade_page_context(
            MultiDict([("give", f"{a.id},{c.id}"), ("get", f"{a.id},{b.id}")]))
        self.assertEqual(ctx["give_ids"], [c.id])
        self.assertEqual(ctx["get_ids"], [b.id])
        self.assertIsNotNone(ctx["verdict"])
        self.assertEqual(ctx["verdict"]["noise"], 9.0)   # 1v1 band, not 2v2

    def test_trade_no_per_source_ranks_leak(self):
        # ToS: the page shows ValuCast value/rank ONLY -- no outside-board source.
        from app import dd_store
        mlb = next(x for x in dd_store.get_all() if not x.is_prospect)
        pros = next(x for x in dd_store.get_all() if x.is_prospect)
        body = self.client.get(f"/trade?give={mlb.id}&get={pros.id}").data.decode().lower()
        for token in ("hkb", "pipeline", "fg_ord", "source_ranks"):
            self.assertNotIn(token, body)

    # --- Step 6: the share card + the poisoning guard ------------------
    def test_trade_share_png_renders(self):
        from app import dd_store, _trade_share_card_png
        ids = [r.id for r in dd_store.get_all()[:3]]
        png = _trade_share_card_png(ids[:1], ids[1:3])
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertGreater(len(png), 0)

    def test_trade_scope_note_is_rendered_into_png(self):
        import app as app_module
        from unittest.mock import patch

        give, get = app_module.dd_store.get_all()[:2]
        with patch.object(
            app_module,
            "_graphic_wrap_text",
            wraps=app_module._graphic_wrap_text,
        ) as wrap:
            png = app_module._trade_share_card_png([give.id], [get.id])

        wrapped_text = [
            call.args[1] for call in wrap.call_args_list if len(call.args) > 1
        ]
        self.assertIn(app_module._TRADE_SCOPE_NOTE, wrapped_text)
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_trade_v2_png_receives_summary_and_disclosures(self):
        import app as app_module
        from unittest.mock import patch
        from werkzeug.datastructures import MultiDict

        rows = app_module.dd_store.get_all()
        mlb = next(row for row in rows if not row.is_prospect)
        prospect = next(row for row in rows if row.is_prospect)
        args = MultiDict([
            ("league", "1"),
            ("teams", "12"),
            ("roster", "26"),
            ("pslots", "5"),
            ("preset", "7x7_ops"),
            ("window", "contend"),
        ])
        with patch.object(
            app_module,
            "_graphic_wrap_text",
            wraps=app_module._graphic_wrap_text,
        ) as wrap:
            png = app_module._trade_share_card_png(
                [mlb.id],
                [prospect.id],
                league_args=args,
            )

        wrapped = [call.args[1] for call in wrap.call_args_list]
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(any("12 teams" in text for text in wrapped))
        self.assertTrue(
            any("Scoring preset not applied:" in text for text in wrapped)
        )
        self.assertTrue(
            any("Prospect slots are roster-depth context" in text for text in wrapped)
        )
        self.assertTrue(
            any("Competitive window is context only" in text for text in wrapped)
        )

    def test_trade_v2_preview_preserves_canonical_state(self):
        from app import dd_store

        give, get = dd_store.get_all()[:2]
        query = (
            f"league=1&teams=12&roster=26&pslots=5&preset=5x5"
            f"&window=balanced&give={give.id}&get={get.id}"
        )
        body = self.client.get(f"/trade/share-card?{query}").data.decode()

        for token in (
            "league=1",
            "teams=12",
            "roster=26",
            "pslots=5",
            "preset=5x5",
            "window=balanced",
            f"give={give.id}",
            f"get={get.id}",
        ):
            self.assertIn(token, body)
        self.assertIn("12 teams", body)

    def test_trade_v2_png_cache_key_distinguishes_league_mode(self):
        from app import _png_cache_key

        common = (
            "teams=12&roster=26&pslots=5&preset=5x5"
            "&window=balanced&give=a&get=b"
        )
        with app.test_request_context(f"/trade/share-card.png?{common}"):
            legacy = _png_cache_key()
        with app.test_request_context(
            f"/trade/share-card.png?league=1&{common}"
        ):
            tuned = _png_cache_key()

        self.assertNotEqual(legacy, tuned)

    def test_trade_png_cache_ignores_inert_league_values(self):
        from app import _png_cache_key

        path = "/trade/share-card.png?give=a&get=b"
        with app.test_request_context(path):
            legacy = _png_cache_key()
        with app.test_request_context(f"{path}&league=not-enabled"):
            inert = _png_cache_key()

        self.assertEqual(legacy, inert)

    def test_trade_png_cache_uses_first_league_value_for_duplicate_params(self):
        from app import _png_cache_key

        path = "/trade/share-card.png?give=a&get=b"
        with app.test_request_context(path):
            legacy = _png_cache_key()
        with app.test_request_context(f"{path}&league=1"):
            tuned = _png_cache_key()
        with app.test_request_context(f"{path}&league=0&league=1"):
            duplicate = _png_cache_key()

        self.assertEqual(legacy, duplicate)
        self.assertNotEqual(tuned, duplicate)

    def test_trade_png_cache_key_distinguishes_trades(self):
        # THE poisoning guard: different trades MUST produce different cache keys.
        # If someone drops give/get from _PNG_CACHE_PARAMS, both collapse to one key
        # and the first-rendered card is served to everyone (cross-user poisoning).
        from app import _png_cache_key
        with app.test_request_context("/trade/share-card.png?give=a&get=b"):
            k1 = _png_cache_key()
        with app.test_request_context("/trade/share-card.png?give=c&get=d"):
            k2 = _png_cache_key()
        self.assertNotEqual(k1, k2)

    def test_trade_png_cache_key_stable_for_same_trade(self):
        from app import _png_cache_key
        with app.test_request_context("/trade/share-card.png?give=a&get=b"):
            k1 = _png_cache_key()
        with app.test_request_context("/trade/share-card.png?give=a&get=b"):
            k2 = _png_cache_key()
        self.assertEqual(k1, k2)

    def test_give_get_in_png_cache_vocabulary(self):
        from app import _PNG_CACHE_PARAMS
        self.assertIn("give", _PNG_CACHE_PARAMS)
        self.assertIn("get", _PNG_CACHE_PARAMS)
        self.assertIn("league", _PNG_CACHE_PARAMS)

    def test_movers_png_cache_key_distinguishes_window(self):
        # 7/12 audit: window changes the movers card's rows/subtitle/footer, so it
        # MUST be in the key or a 21d request gets served the cached 7d image
        # (cross-user poisoning). Different windows -> different keys.
        from app import _png_cache_key, _PNG_CACHE_PARAMS
        self.assertIn("window", _PNG_CACHE_PARAMS)
        with app.test_request_context("/movers/share-card.png?window=7"):
            k7 = _png_cache_key()
        with app.test_request_context("/movers/share-card.png?window=21"):
            k21 = _png_cache_key()
        self.assertNotEqual(k7, k21)

    def test_trade_template_renders(self):
        import jinja2
        env = jinja2.Environment(loader=jinja2.FileSystemLoader("templates"))
        env.get_template("trade.html")  # raises TemplateNotFound / syntax error on failure


class TestTodayStrip(unittest.TestCase):
    """Front-door "Today on ValuCast" digest (7/3 landscape review, Batch 1)."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_front_door_carries_daily_digest_and_ledger_counts(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn("Today on ValuCast", html)
        self.assertIn("calls tracked publicly", html)
        self.assertIn("Receipts open", html)
        # 7/14 declutter: the freshness badge is gone from the front door — the
        # prov-line and toolbar "Updated" stamps carry freshness now.
        self.assertNotIn("freshness-badge", html)
        # The strip must never leak a pre-gate success RATE — counts only.
        import re
        strip = re.search(r'class="today-ledger".*?</a>', html, re.S)
        self.assertIsNotNone(strip)
        self.assertNotIn("%", strip.group(0))

    def test_digest_renders_on_all_horizons(self):
        for url in ("/?mode=dd_dynasty", "/?mode=prospects"):
            html = self.client.get(url).data.decode("utf-8")
            self.assertIn("Today on ValuCast", html, url)

    def test_digest_degrades_to_nothing_when_artifacts_missing(self):
        import app as app_module
        from unittest.mock import patch
        with patch.object(app_module, "_load_movers_payload", return_value={}), \
             patch.object(app_module, "_load_artifact", return_value=None):
            self.assertEqual(app_module._front_door_digest(), {})
            html = self.client.get("/").data.decode("utf-8")
        self.assertEqual(html.count("today-strip"), 0)
        # Page itself still healthy.
        self.assertIn("rankings-table", html)

    def test_digest_today_cells_render_when_present_and_fail_soft(self):
        """Two "logged today" cells (receipts logged, gaps claims resolved) appear
        only when their count is > 0, carry NO percent sign, and drop cleanly when
        the artifact is absent."""
        from datetime import date
        today = date.today().isoformat()

        receipts_artifact = {"receipts": [
            {"logged_at": today + "T01:00:00+00:00"},
            {"logged_at": today + "T02:00:00+00:00"},
            {"logged_at": "2026-01-01T00:00:00+00:00"},  # a different day, excluded
        ]}
        gaps_ledger = {"claims": [
            {"resolved_date": today}, {"resolved_date": today}, {"resolved_date": today},
            {"resolved_date": "2026-01-01"},  # excluded
            {"resolved_date": None},          # excluded
        ]}

        def fake_load(path):
            p = str(path)
            if "valucast_call_up_receipts.json" in p:
                return receipts_artifact
            return None

        with patch.object(app_module, "_load_artifact", side_effect=fake_load), \
             patch.object(app_module, "_load_gaps_ledger", return_value=gaps_ledger):
            digest = app_module._front_door_digest()
        self.assertEqual(digest.get("receipts_today"), 2)
        self.assertEqual(digest.get("gaps_resolved_today"), 3)

        # Render: cells present, no percent sign leaks in.
        with patch.object(app_module, "_load_artifact", side_effect=fake_load), \
             patch.object(app_module, "_load_gaps_ledger", return_value=gaps_ledger):
            html = self.client.get("/").data.decode("utf-8")
        self.assertIn("Receipts logged today", html)
        self.assertIn("Claims resolved today", html)

        # Fail-soft: absent artifacts -> no cells, no crash.
        with patch.object(app_module, "_load_movers_payload", return_value={}), \
             patch.object(app_module, "_load_artifact", return_value=None), \
             patch.object(app_module, "_load_gaps_ledger", return_value={}):
            digest = app_module._front_door_digest()
        self.assertNotIn("receipts_today", digest)
        self.assertNotIn("gaps_resolved_today", digest)

    def test_top_buy_cell_hides_when_aotc_held(self):
        # 7/17 nav audit P1: the today-strip's "Top buy" cell linked /buys
        # unconditionally, while the primary nav + backfields.html both
        # correctly gate the same destination on aotc_hold.
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('href="/buys"', html)
        self.assertIn("Top buy", html)

        original = app_module.AHEAD_OF_THE_CURVE_HOLD
        app_module.AHEAD_OF_THE_CURVE_HOLD = True
        try:
            held_html = self.client.get("/").data.decode("utf-8")
        finally:
            app_module.AHEAD_OF_THE_CURVE_HOLD = original
        self.assertNotIn("Top buy", held_html)
        # The rest of the strip (movers/callups) still renders.
        self.assertIn("Today on ValuCast", held_html)


class TestFamiliarNameOnRamp(unittest.TestCase):
    """"Where we differ from the field" home on-ramp (3 recognizable names)."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_onramp_selects_three_by_field_prominence(self):
        scorecard = {"calls": [
            {"name": "Prominent", "valucast_now": 20, "consensus_now": 45, "days_tracked": 30},
            {"name": "Less Prominent", "valucast_now": 30, "consensus_now": 60, "days_tracked": 20},
            {"name": "Deep Cut", "valucast_now": 40, "consensus_now": 80, "days_tracked": 15},
            {"name": "Fourth", "valucast_now": 50, "consensus_now": 90, "days_tracked": 15},
            {"name": "Too Fresh", "valucast_now": 10, "consensus_now": 40, "days_tracked": 3},   # < 7 days
            {"name": "Too Close", "valucast_now": 44, "consensus_now": 50, "days_tracked": 30},  # < 20 divergence
            {"name": "No Field", "valucast_now": 5, "consensus_now": None, "days_tracked": 30},  # no consensus
        ]}
        with patch.object(app_module, "_load_scorecard_payload", return_value=scorecard):
            picks = app_module._front_door_onramp()
        self.assertEqual([p["name"] for p in picks], ["Prominent", "Less Prominent", "Deep Cut"])
        # Aggregate median only — never a per-source/third-party board rank field.
        for p in picks:
            self.assertEqual(set(p.keys()), {"name", "valucast_now", "consensus_now"})

    def test_onramp_renders_rows_and_carries_no_per_source_rank(self):
        scorecard = {"calls": [
            {"name": "Alpha Guy", "valucast_now": 20, "consensus_now": 45, "days_tracked": 30},
            {"name": "Beta Guy", "valucast_now": 30, "consensus_now": 60, "days_tracked": 20},
            {"name": "Gamma Guy", "valucast_now": 40, "consensus_now": 80, "days_tracked": 15},
        ]}
        # 7/14 declutter: the on-ramp strip no longer renders on the front door —
        # render the partial directly (it stays available for other surfaces).
        from flask import render_template
        with patch.object(app_module, "_load_scorecard_payload", return_value=scorecard):
            front = self.client.get("/").data.decode("utf-8")
            with app.test_request_context("/"):
                html = render_template(
                    "partials/_onramp_strip.html",
                    onramp_names=app_module._front_door_onramp(),
                )
        self.assertEqual(front.count("onramp-strip"), 0)
        self.assertIn("Where we differ from the field", html)
        self.assertIn("Alpha Guy", html)
        self.assertIn("#20 here", html)
        self.assertIn("~#45 field median", html)
        # No per-source board attribution anywhere in the on-ramp markup.
        import re
        strip = re.search(r'class="onramp-strip[^"]*".*?</section>', html, re.S)
        self.assertIsNotNone(strip)
        for banned in ("consensus_rank", "source_rank", "board_rank", "per_source", "third_party"):
            self.assertNotIn(banned, strip.group(0))

    def test_onramp_hides_when_scorecard_missing(self):
        with patch.object(app_module, "_load_scorecard_payload", return_value=None):
            self.assertEqual(app_module._front_door_onramp(), [])
            html = self.client.get("/").data.decode("utf-8")
        self.assertEqual(html.count("onramp-strip"), 0)


class TestProspectsRedirect(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_prospects_redirects_301_to_canonical_board(self):
        response = self.client.get("/prospects")
        self.assertEqual(response.status_code, 301)
        self.assertIn("/?mode=prospects", response.headers.get("Location", ""))


class TestTrustGrammarAndCards(unittest.TestCase):
    """Batch 2 trust grammar + Batch 3 cards gallery (7/3 landscape review)."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_buys_shows_qualification_funnel_and_why_lines(self):
        html = self.client.get("/buys").data.decode("utf-8")
        # Scarcity + funnel disclosure at point of use.
        self.assertIn("of the pool by design", html)
        self.assertIn("active-MLB call-ups excluded", html)
        # Why-line: joined from the existing deterministic scouting reads.
        self.assertIn("buys-why", html)
        # Form-curve window presets render with All active by default.
        self.assertIn("buys-window-pills", html)
        self.assertIn(">7d</a>", html)

    def test_buys_window_param_trims_form_curves(self):
        import re as _re

        def spans(html):
            return [int(m) for m in _re.findall(r'aria-label="(\d+)-day value trend', html)]

        default_spans = spans(self.client.get("/buys").data.decode("utf-8"))
        windowed = self.client.get("/buys?window=7")
        self.assertEqual(windowed.status_code, 200)
        seven_spans = spans(windowed.data.decode("utf-8"))
        if seven_spans:
            self.assertLessEqual(max(seven_spans), 7)
        # Junk window falls back to the default view, never a 500.
        junk = self.client.get("/buys?window=999").data.decode("utf-8")
        self.assertEqual(spans(junk), default_spans)

    def test_movers_shows_qualification_thresholds(self):
        # 7/14 declutter: the qualification fineprint describes rows on the board,
        # so it renders only when movers exist; empty states carry their own honest
        # drought/sparse copy instead of caveats about rows that don't exist. The
        # expectation reads the committed artifact so the lock holds in both states.
        import json
        from pathlib import Path as _Path

        payload = json.loads(
            _Path("data/models/valucast_prospect_movers.json").read_text(encoding="utf-8")
        )
        mover_count = len(payload.get("rising") or []) + len(payload.get("cooling") or [])
        html = self.client.get("/movers").data.decode("utf-8")
        if mover_count:
            # Plan 013: the cap fineprint is two-sided — Rising capped at the current
            # top-N, Cooling qualified at the window start (a faller can drop past it).
            self.assertIn("Rank cap", html)
            self.assertIn("at the window start", html)
            self.assertIn("tracked prospects", html)
        else:
            self.assertNotIn("Rank cap", html)
            self.assertIn("0 movers", html)

    def test_provenance_line_on_every_board(self):
        for path in ("/", "/movers", "/ledger", "/cards"):
            html = self.client.get(path).data.decode("utf-8")
            self.assertIn("publicly scored", html, path)
            self.assertIn("free, no login", html, path)

    def test_ledger_hero_carries_metadata_subtitle(self):
        html = self.client.get("/ledger").data.decode("utf-8")
        self.assertIn("calls tracked since", html)

    def test_new_chip_on_opt_in_valucast_source(self):
        html = self.client.get("/?source=valucast").data.decode("utf-8")
        self.assertIn("new-chip", html)

    def test_cards_gallery_indexes_share_cards(self):
        import app as app_module
        html = self.client.get("/cards").data.decode("utf-8")
        self.assertIn("THE CARD SHOP", html)
        self.assertIn("The Ledger", html)
        self.assertIn("Prospect Movers", html)
        self.assertIn("/ledger/share-card.png", html)
        # Held boards stay out of the gallery while held.
        if app_module.RECEIPTS_HOLD:
            self.assertNotIn("/receipts/share-card", html)
        if not app_module.AHEAD_OF_THE_CURVE_HOLD:
            self.assertIn("/buys/share-card.png", html)

    def test_ledger_share_card_renders_png_counts_only(self):
        r = self.client.get("/ledger/share-card.png")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(self.client.get("/ledger/share-card").status_code, 200)


class TestLlmsTxt(unittest.TestCase):
    """LLM-citation discoverability file (dynatyze review, 7/3)."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_llms_txt_serves_plain_text_with_citation_rules(self):
        r = self.client.get("/llms.txt")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/plain", r.headers["Content-Type"])
        body = r.data.decode("utf-8")
        self.assertIn("# ValuCast", body)
        # The pre-gate honesty rule travels with the citation guidance.
        self.assertIn("Do not state or estimate a success rate", body)
        self.assertIn("https://valucast.app/ledger", body)


class TestConsensusLabelsAndYoungBadge(unittest.TestCase):
    """Batch 4 display-only pair (7/3): source labels + young-for-level badge."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_young_for_level_cut_is_exceptional_not_common(self):
        from web.prospect_percentiles import exceptionally_young_for_level
        self.assertTrue(exceptionally_young_for_level(19, "AA"))
        self.assertFalse(exceptionally_young_for_level(20, "AA"))   # plain young != badge
        self.assertFalse(exceptionally_young_for_level(None, "AA"))
        self.assertFalse(exceptionally_young_for_level(19, None))
        self.assertFalse(exceptionally_young_for_level(21, "MLB"))  # majors never badge
        self.assertFalse(exceptionally_young_for_level(19, "Rk"))   # unknown level -> no badge

    def test_young_badge_renders_on_prospect_board(self):
        html = self.client.get("/?mode=prospects").data.decode("utf-8")
        self.assertIn("Young for", html)

    def test_player_detail_keeps_source_initials_and_shows_gap(self):
        """Alex ruling 7/3: external boards stay initials-only ("HKB", never
        the full name) — but the gap vs the field renders on every card."""
        import app as app_module
        row = next(
            r for r in app_module.dd_store.get_all()
            if r.prospect_rank is not None
            and r.public_source_consensus is not None
            and "hkb" in (r.public_source_ranks or {})
        )
        html = self.client.get(
            f"/player/{row.id}?mode=prospects",
            headers={"HX-Request": "true"},       # direct hits redirect to the board
        ).data.decode("utf-8")
        self.assertIn("HKB", html)                # initials only
        self.assertNotIn("Harry Knows Ball", html)
        self.assertIn("the field", html)          # gap note vs consensus


class TestServingCaches(unittest.TestCase):
    """Generation-keyed caches across the serving layer (plan 005): the caches
    change WHEN work happens, never WHAT is served."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_home_page_byte_identical_across_repeat_requests(self):
        first = self.client.get("/")
        second = self.client.get("/")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.status_code, second.status_code)
        self.assertEqual(first.data, second.data)

    def test_value_map_api_stable_across_calls(self):
        first = self.client.get("/api/value-map-players")
        second = self.client.get("/api/value-map-players")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.data, second.data)

    def test_redraft_bundle_cache_hits_then_misses_on_new_generation(self):
        # Repeated identical (source, generation, config) keys return the SAME
        # cached bundle object; a new generation stamp must MISS and recompute.
        config = app_module.build_config(mode="categories")
        default_key = (
            "categories",
            tuple(app_module.DEFAULT_CATS), tuple(app_module.DEFAULT_PCATS),
            "", (), False, (),
        )
        b1 = app_module._redraft_board_bundle(
            store, config, "steamer", store.as_of, *default_key)
        b2 = app_module._redraft_board_bundle(
            store, config, "steamer", store.as_of, *default_key)
        self.assertIs(b1, b2)  # cache HIT: same object, no recompute
        b3 = app_module._redraft_board_bundle(
            store, config, "steamer", "9999-99-99", *default_key)
        self.assertIsNot(b1, b3)  # new generation -> MISS

    def test_value_map_cache_misses_on_new_generation(self):
        if not app_module.dd_store.is_available:
            self.skipTest("dd snapshot not available")
        players_a = app_module._value_map_payload()
        players_again = app_module._value_map_payload()
        self.assertIs(players_a, players_again)  # HIT: identical list object
        # generated_at is a read-only property over _generated_at — patch the
        # backing field to simulate a daily refresh restamping the feed.
        original = app_module.dd_store._generated_at
        try:
            app_module.dd_store._generated_at = "0000-00-00"
            players_b = app_module._value_map_payload()
            self.assertIsNot(players_a, players_b)  # MISS: recomputed
        finally:
            app_module.dd_store._generated_at = original
            app_module._value_map_payload()  # restore cache to the real generation


class TestPlateDisciplineReaderStructural(unittest.TestCase):
    """Structural locks that need NO data and must never skip."""

    def test_reader_is_network_free(self):
        """The serving reader imports no network library (fetch lives only in
        scripts/build_pitch_discipline.py)."""
        import inspect
        import web.pitch_discipline_store as reader
        src = inspect.getsource(reader)
        for banned in ("import urllib", "import requests", "import http", "urlopen"):
            self.assertNotIn(banned, src)


class TestPlateDisciplineCardRows(unittest.TestCase):
    """Pure row-builder for the share-PNG strip: labels, est flags, pct-None."""

    def _group(self, level="AA"):
        return {
            "level": level, "pitches": 811, "estimated": True,
            "metrics": [
                # Swing% mirrors the store's contextual shape: a cohort POSITION
                # (positional=True), not a quality grade.
                {"key": "swing_pct", "label": "Swing%", "display": "37.4%", "pct": 55, "positional": True, "estimated": False},
                {"key": "whiff_pct", "label": "Whiff%", "display": "24.8%", "pct": 60, "estimated": False},
                {"key": "swstr_pct", "label": "SwStr%", "display": "9.2%", "pct": 83, "estimated": False},
                {"key": "chase_pct", "label": "Chase%", "display": "15.8%", "pct": 99, "estimated": True},
                {"key": "z_swing_pct", "label": "Z-Swing%", "display": "64.3%", "pct": None, "estimated": True},
                {"key": "z_contact_pct", "label": "Z-Contact%", "display": "80.6%", "pct": 34, "estimated": True},
                {"key": "zone_pct", "label": "Zone%", "display": "44.5%", "pct": None, "estimated": True},
            ],
        }

    def test_headline_metrics_in_order_with_est_flags(self):
        rows = app_module._prospect_discipline_card_rows([self._group()])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["level"], "AA")
        self.assertEqual(row["pitches"], 811)
        # The five headline metrics, in order; z_swing/zone stay page-only.
        self.assertEqual([m["label"] for m in row["metrics"]],
                         ["Swing%", "Whiff%", "SwStr%", "Chase%", "Z-Contact%"])
        self.assertEqual([m["est"] for m in row["metrics"]],
                         [False, False, False, True, True])
        self.assertTrue(row["any_est"])

    def test_pct_none_passes_through_for_contextual_metric(self):
        group = self._group()
        group["metrics"][0] = {  # a Swing% bucket the reader gave no pct at all
            "key": "swing_pct", "label": "Swing%", "display": "37.4%",
            "pct": None, "estimated": False,
        }
        rows = app_module._prospect_discipline_card_rows([group])
        by_key = {m["key"]: m for m in rows[0]["metrics"]}
        self.assertIsNone(by_key["swing_pct"]["pct"])   # renderer draws no chip
        self.assertEqual(by_key["swstr_pct"]["pct"], 83)

    def test_positional_flag_carries_through_to_png_rows(self):
        # Audit F2: the store marks contextual metrics positional (a cohort
        # position, not a grade) and the web card renders them neutral. The PNG
        # rows must carry that flag so the renderer can refuse to grade them too.
        rows = app_module._prospect_discipline_card_rows([self._group()])
        by_key = {m["key"]: m for m in rows[0]["metrics"]}
        self.assertTrue(by_key["swing_pct"]["positional"])
        self.assertFalse(by_key["whiff_pct"]["positional"])
        self.assertFalse(by_key["chase_pct"]["positional"])

    def test_positional_chip_renders_neutral_not_graded(self):
        # The chip-color rule the PNG renderer uses: positional percentiles get
        # the neutral color regardless of magnitude; graded ones tier by pct.
        elite, mid, low, neutral = "E", "M", "L", "N"
        self.assertEqual(
            app_module._discipline_chip_color(99, True, elite, mid, low, neutral),
            neutral,
        )
        self.assertEqual(
            app_module._discipline_chip_color(99, False, elite, mid, low, neutral),
            elite,
        )
        self.assertEqual(
            app_module._discipline_chip_color(50, False, elite, mid, low, neutral),
            mid,
        )
        self.assertEqual(
            app_module._discipline_chip_color(10, False, elite, mid, low, neutral),
            low,
        )

    def test_max_two_levels(self):
        rows = app_module._prospect_discipline_card_rows(
            [self._group("AAA"), self._group("AA"), self._group("A+")]
        )
        self.assertEqual([r["level"] for r in rows], ["AAA", "AA"])

    def test_empty_and_missing_metrics(self):
        self.assertEqual(app_module._prospect_discipline_card_rows([]), [])
        self.assertEqual(app_module._prospect_discipline_card_rows(None), [])
        # A group missing one headline metric omits just that metric.
        group = self._group()
        group["metrics"] = [m for m in group["metrics"] if m["key"] != "chase_pct"]
        rows = app_module._prospect_discipline_card_rows([group])
        self.assertEqual([m["key"] for m in rows[0]["metrics"]],
                         ["swing_pct", "whiff_pct", "swstr_pct", "z_contact_pct"])


class TestPlateDisciplineCard(unittest.TestCase):
    """The plate-discipline card section renders (or doesn't) off the reader.

    Uses a fixture-backed PitchDisciplineStore so the test is independent of whether
    the committed artifact has been built — the reviewer builds the full artifact
    after review, and the card must still render correctly against a known fixture.
    The prospect is selected dynamically (any prospect row with an mlbam id) so the
    tests keep running when individual players rotate out of the nightly universe.
    """

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True
        if not app_module.dd_store.is_available:
            self.skipTest("dd snapshot not available")
        row = next(
            (r for r in app_module.dd_store.get_all()
             if getattr(r, "is_prospect", False) and getattr(r, "mlbam_id", None)),
            None,
        )
        if row is None:
            self.skipTest("No prospect rows with an mlbam id available")
        self.prospect_id = row.id
        self.mlbam = str(row.mlbam_id)

    def _fixture_store(self, tmp, *, qualifies=True, zone_estimated=True):
        import json
        from web.pitch_discipline_store import PitchDisciplineStore
        payload = {
            "artifact": "valucast_pitch_discipline",
            "as_of": "2026-07-10",
            "metric_labels": {
                "swing_pct": "Swing%", "whiff_pct": "Whiff%", "swstr_pct": "SwStr%",
                "chase_pct": "Chase%", "z_swing_pct": "Z-Swing%",
                "z_contact_pct": "Z-Contact%", "zone_pct": "Zone%",
            },
            "cohorts": {"min_pitches": 300, "zone_metrics_shipped": True},
            "players": {self.mlbam: {"AA": {
                "pitches": 811, "qualifies": qualifies, "zone_estimated": zone_estimated,
                "rates": {"swing_pct": 37.4, "whiff_pct": 24.8, "swstr_pct": 9.2,
                          "chase_pct": 15.8, "z_swing_pct": 64.3, "z_contact_pct": 80.6,
                          "zone_pct": 44.5},
                "percentiles": {"whiff_pct": 75, "swstr_pct": 75, "chase_pct": 60,
                                "z_contact_pct": 25},
            }}},
        }
        path = tmp / "disc.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return PitchDisciplineStore(path=path)

    def _render(self, store):
        with patch.object(app_module, "pitch_discipline_store", store):
            return self.client.get(
                f"/player/{self.prospect_id}?mode=prospects",
                headers={"HX-Request": "true"},
            )

    def test_card_renders_section_with_data(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            store = self._fixture_store(Path(td))
            r = self._render(store)
            self.assertEqual(r.status_code, 200)
            html = r.data.decode("utf-8", "replace")
            self.assertIn("Plate Discipline", html)
            self.assertIn("/methodology#plate-discipline", html)
            self.assertIn("Computed from MLB play-by-play feeds", html)
            self.assertIn("37.4%", html)   # exact Swing% value

    def test_estimated_rows_tagged(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            store = self._fixture_store(Path(td), zone_estimated=True)
            html = self._render(store).data.decode("utf-8", "replace")
            self.assertIn("est.", html)
            self.assertIn("pd-est-tag", html)

    def test_no_section_without_data(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # A qualifying=False bucket -> no group -> no card shell.
            store = self._fixture_store(Path(td), qualifies=False)
            html = self._render(store).data.decode("utf-8", "replace")
            self.assertNotIn("plate-discipline-card", html)

    def _share_png(self, store):
        with patch.object(app_module, "pitch_discipline_store", store):
            return self.client.get(f"/prospects/player-card/{self.prospect_id}.png")

    def test_share_png_renders_without_discipline_data(self):
        # Empty store path: the share PNG renders exactly as before the strip
        # existed (200, valid PNG, no exception).
        from web.pitch_discipline_store import PitchDisciplineStore
        empty = PitchDisciplineStore(path=Path("definitely-missing") / "no.json")
        response = self._share_png(empty)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data[:8], b"\x89PNG\r\n\x1a\n")

    def test_share_png_with_discipline_data_is_taller(self):
        # Same prospect with vs without discipline data: the with-data render
        # carries the strip, so the canvas is taller (never crowds sections).
        import struct
        import tempfile
        from web.pitch_discipline_store import PitchDisciplineStore
        empty = PitchDisciplineStore(path=Path("definitely-missing") / "no.json")
        base = self._share_png(empty)
        self.assertEqual(base.status_code, 200)
        with tempfile.TemporaryDirectory() as td:
            with_data = self._share_png(self._fixture_store(Path(td)))
        self.assertEqual(with_data.status_code, 200)
        self.assertEqual(with_data.data[:8], b"\x89PNG\r\n\x1a\n")
        base_height = struct.unpack(">I", base.data[20:24])[0]
        data_height = struct.unpack(">I", with_data.data[20:24])[0]
        self.assertGreater(data_height, base_height)


class TestPlateDisciplineLeaders(unittest.TestCase):
    """Public leaders board stays per-level, display-only, and fail-soft."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True
        if not app_module.dd_store.is_available:
            self.skipTest("dd snapshot not available")
        row = next(
            (r for r in app_module.dd_store.get_all()
             if getattr(r, "is_prospect", False) and getattr(r, "mlbam_id", None)),
            None,
        )
        if row is None:
            self.skipTest("No prospect rows with an mlbam id available")
        self.player_id = row.id
        self.mlbam = str(row.mlbam_id)

    def _fixture_store(self, tmp):
        import json
        from web.pitch_discipline_store import PitchDisciplineStore
        payload = {
            "artifact": "valucast_pitch_discipline",
            "as_of": "2026-07-10",
            "metric_labels": {
                "swing_pct": "Swing%", "whiff_pct": "Whiff%",
                "swstr_pct": "SwStr%", "chase_pct": "Chase%",
                "z_swing_pct": "Z-Swing%", "z_contact_pct": "Z-Contact%",
                "zone_pct": "Zone%",
            },
            "estimated_metrics": [
                "chase_pct", "z_swing_pct", "z_contact_pct", "zone_pct",
            ],
            "cohorts": {
                "min_pitches": 300,
                "cohort_sizes": {"AA": 1, "A+": 1, "A": 1, "AAA": 1},
                "lower_is_better": ["chase_pct", "whiff_pct", "swstr_pct"],
                "higher_is_better": ["z_contact_pct"],
            },
            "players": {
                self.mlbam: {
                    level: {
                        "pitches": 450,
                        "qualifies": True,
                        "zone_estimated": level != "AAA",
                        "rates": {
                            "swing_pct": 39.0, "whiff_pct": 18.0,
                            "swstr_pct": 7.0, "chase_pct": 20.0,
                            "z_swing_pct": 62.0, "z_contact_pct": 90.0,
                            "zone_pct": 45.0,
                        },
                        "percentiles": {
                            "whiff_pct": 92, "swstr_pct": 94,
                            "chase_pct": 96, "z_contact_pct": 91,
                        },
                    }
                    for level in ("AA", "A+", "A", "AAA")
                }
            },
        }
        path = tmp / "discipline.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return PitchDisciplineStore(path=path)

    def _get(self, store, query=""):
        with patch.object(app_module, "pitch_discipline_store", store):
            return self.client.get(f"/discipline-leaders{query}")

    def test_default_board_renders_contract_and_player_link(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            response = self._get(self._fixture_store(Path(td)))
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8", "replace")
        self.assertIn("minimum 300 pitches", html)
        self.assertIn("1 qualifying AA hitter", html)
        self.assertIn("2026-07-10", html)
        self.assertIn("Computed from MLB play-by-play feeds", html)
        self.assertIn(f"/player/{self.player_id}?mode=prospects", html)
        self.assertIn("rankings-table", html)

    def test_slug_validation_and_a_plus_contract(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            store = self._fixture_store(Path(td))
            a_plus = self._get(store, "?level=a-plus&metric=whiff")
            junk = self._get(store, "?level=../etc&metric=%2BDROP")
            plus_trap = self._get(store, "?level=A+&metric=chase")
        self.assertEqual(a_plus.status_code, 200)
        self.assertIn('data-level="A+"', a_plus.data.decode("utf-8", "replace"))
        for response in (junk, plus_trap):
            html = response.data.decode("utf-8", "replace")
            self.assertEqual(response.status_code, 200)
            self.assertIn('data-level="AA"', html)
            self.assertNotIn("../etc", html)
            self.assertNotIn("+DROP", html)

    def test_estimated_split_matches_level(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            store = self._fixture_store(Path(td))
            aa = self._get(store, "?level=aa&metric=chase").data
            aaa = self._get(store, "?level=aaa&metric=chase").data
        self.assertIn(b'class="pd-est-tag"', aa)
        self.assertIn(b"/methodology#plate-discipline", aa)
        self.assertNotIn(b'class="pd-est-tag"', aaa)

    def test_mixed_level_marks_only_estimated_rows(self):
        import json
        import tempfile
        from web.pitch_discipline_store import PitchDisciplineStore

        with tempfile.TemporaryDirectory() as td:
            store = self._fixture_store(Path(td))
            payload = json.loads(store._path.read_text(encoding="utf-8"))
            payload["players"]["999999999"] = {
                "AAA": {
                    "pitches": 500,
                    "qualifies": True,
                    "zone_estimated": True,
                    "rates": {"chase_pct": 11.0},
                    "percentiles": {"chase_pct": 99},
                }
            }
            store._path.write_text(json.dumps(payload), encoding="utf-8")
            mixed = PitchDisciplineStore(path=store._path)
            html = self._get(
                mixed, "?level=aaa&metric=chase"
            ).data.decode("utf-8", "replace")

        self.assertIn(
            '11.0% <span class="pd-est-tag">est.</span>',
            html,
        )
        self.assertNotIn(
            '20.0% <span class="pd-est-tag">est.</span>',
            html,
        )
        self.assertIn("Rows marked", html)

    def test_contextual_metrics_and_valuation_columns_are_absent(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            html = self._get(
                self._fixture_store(Path(td))
            ).data.decode("utf-8", "replace")
        self.assertNotIn("Z-Swing%", html)
        self.assertNotIn(">Swing%<", html)
        self.assertNotIn(">Zone%<", html)
        self.assertNotIn("Dynasty Value", html)
        self.assertNotIn('class="col-value"', html)

    def test_missing_artifact_is_honest_empty_state(self):
        from web.pitch_discipline_store import PitchDisciplineStore
        empty = PitchDisciplineStore(path=Path("definitely-missing") / "no.json")
        response = self._get(empty)
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8", "replace")
        self.assertIn("Leaders unavailable", html)
        self.assertNotIn("rankings-table", html)

    def test_footer_and_methodology_explain_the_board(self):
        footer = (
            Path(app_module.app.template_folder)
            / "partials" / "_footer_provenance.html"
        ).read_text(encoding="utf-8")
        self.assertGreaterEqual(footer.count('href="/discipline-leaders"'), 4)
        methodology = self.client.get("/methodology")
        self.assertEqual(methodology.status_code, 200)
        html = methodology.data.decode("utf-8", "replace")
        self.assertIn('href="/discipline-leaders">Discipline Leaders</a>', html)
        self.assertIn("ranks only hitters", html)
        self.assertIn("Chase%, Whiff%, SwStr%, and Z-Contact%", html)

    def test_share_card_params_are_cache_safe(self):
        self.assertIn("level", app_module._PNG_CACHE_PARAMS)
        self.assertIn("metric", app_module._PNG_CACHE_PARAMS)
        with app.test_request_context(
            "/discipline-leaders/share-card.png?level=aa&metric=chase"
        ):
            first = app_module._png_cache_key()
        with app.test_request_context(
            "/discipline-leaders/share-card.png?level=aaa&metric=whiff"
        ):
            second = app_module._png_cache_key()
        with app.test_request_context(
            "/discipline-leaders/share-card.png?metric=chase&level=aa"
        ):
            same = app_module._png_cache_key()
        self.assertNotEqual(first, second)
        self.assertEqual(first, same)

    def test_share_card_png_and_page_use_the_same_defaults(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            store = self._fixture_store(Path(td))
            with patch.object(app_module, "pitch_discipline_store", store):
                default = self.client.get("/discipline-leaders/share-card.png")
                junk = self.client.get(
                    "/discipline-leaders/share-card.png?level=bad&metric=bad"
                )
                preview = self.client.get("/discipline-leaders/share-card")
        self.assertEqual(default.status_code, 200)
        self.assertEqual(default.data[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(junk.data, default.data)
        self.assertEqual(preview.status_code, 200)
        self.assertIn(
            b"/discipline-leaders/share-card.png?level=aa&amp;metric=chase",
            preview.data,
        )

    def test_cards_gallery_lists_discipline_leaders(self):
        response = self.client.get("/cards")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Plate-Discipline Leaders", response.data)
        self.assertIn(b"/discipline-leaders", response.data)


class TestAttributionPanel(unittest.TestCase):
    """Lane B stage 2: the 'How ValuCast graded him' attribution panel on the
    prospect card, and the no-per-feature-weight-percent rule."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def _first_prospect_with_signal(self):
        # outcome_mix is intentionally empty since the 2026-07-29 probability
        # disposition stripped dynasty_signal from the serving plane; any
        # prospect row exercises the attribution panel.
        from app import dd_store
        if not dd_store.is_available:
            return None
        for row in dd_store.get_all():
            if row.is_prospect:
                return row
        return None

    def test_panel_renders_high_on_prospect_card(self):
        row = self._first_prospect_with_signal()
        if row is None:
            self.skipTest("No prospect with a dynasty_signal available")
        resp = self.client.get(
            "/player/" + row.id + "?mode=prospects", headers={"HX-Request": "true"}
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("How ValuCast graded him", body)
        self.assertNotIn("attribution-mix", body)
        self.assertNotIn("Four-year MLB outlook", body)
        self.assertNotIn("not a career verdict", body)
        self.assertNotIn("Bust risk", body)
        # Placed HIGH: before the deep stat sections (e.g. MiLB Stats details).
        if "MiLB Stats" in body:
            self.assertLess(body.index("How ValuCast graded him"), body.index("MiLB Stats"))

    def test_panel_has_no_per_feature_weight_percent(self):
        import re
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        checked = 0
        for row in dd_store.get_all():
            if not row.is_prospect:
                continue
            body = self.client.get(
                "/player/" + row.id + "?mode=prospects", headers={"HX-Request": "true"}
            ).data.decode()
            self.assertIsNone(
                re.search(r"weight[^<]{0,20}\d+\s*%", body, re.I),
                "per-feature weight percent leaked on " + row.id,
            )
            checked += 1
            if checked >= 25:
                break
        self.assertGreater(checked, 0)

    def test_panel_absent_on_mlb_card(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        mlb = next((r for r in dd_store.get_all() if not r.is_prospect), None)
        if mlb is None:
            self.skipTest("No MLB row available")
        body = self.client.get(
            "/player/" + mlb.id + "?mode=dd_dynasty", headers={"HX-Request": "true"}
        ).data.decode()
        self.assertNotIn("How ValuCast graded him", body)

    def test_model_context_relabelled_to_confidence_adjustment(self):
        from app import dd_store
        if not dd_store.is_available:
            self.skipTest("DD feed not available")
        target = next(
            (r for r in dd_store.get_all() if r.is_prospect and r.bucket_calibration_label),
            None,
        )
        if target is None:
            self.skipTest("No prospect with a bucket-calibration label available")
        body = self.client.get(
            "/player/" + target.id + "?mode=prospects", headers={"HX-Request": "true"}
        ).data.decode()
        self.assertIn("Confidence adjustment", body)
        self.assertNotIn(">Model Context<", body)


class TestOutcomeMixHelper(unittest.TestCase):
    def test_outcome_mix_partitions_to_100(self):
        from web.prospect_context import outcome_mix
        segs = outcome_mix({
            "role_or_better_probability": 0.36,
            "bust_risk": 0.64,
            "star_ceiling_probability": 0.08,
        })
        self.assertEqual(sum(s["pct"] for s in segs), 100)
        labels = [s["label"] for s in segs]
        self.assertEqual(
            labels,
            ["Impact season", "Established MLB role", "Not established by Year 4"],
        )
        self.assertNotIn("Star ceiling", labels)
        self.assertNotIn("Everyday role", labels)
        self.assertNotIn("Bust risk", labels)

    def test_outcome_mix_empty_on_missing_signal(self):
        from web.prospect_context import outcome_mix
        self.assertEqual(outcome_mix(None), ())
        self.assertEqual(outcome_mix({}), ())

    def test_attribution_components_real_effects_and_context_flag(self):
        from web.prospect_context import attribution_components
        items = attribution_components({
            "availability_risk_discount": 0.10,
            "availability": {"note": "risk priced in", "risk_discount": 0.10},
            "bucket_calibration": {"adjustment": -0.82, "reason": "thin sample"},
            "sample_reliability": 44.9,
        })
        by_label = {i["label"]: i for i in items}
        self.assertEqual(by_label["Availability discount"]["effect"], "-10.0%")
        self.assertFalse(by_label["Availability discount"]["context_only"])
        self.assertEqual(by_label["Bucket calibration"]["effect"], "-0.82 pts")
        self.assertTrue(by_label["Sample sufficiency"]["context_only"])


class TestModelsRegistryPage(unittest.TestCase):
    """Plan 024 /models page: renders, mobile-stacked structure, fail-soft, and the
    per-row EVIDENCE UNAVAILABLE broken-link state (never a benign empty state)."""

    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_models_page_renders_with_verdicts(self):
        resp = self.client.get("/models")
        self.assertEqual(resp.status_code, 200)
        body = resp.data.decode()
        self.assertIn("Model Verdicts", body)
        self.assertIn("VALIDATED", body)
        self.assertIn("REJECTED", body)
        self.assertIn("/ledger", body)
        self.assertIn("/receipts", body)

    def test_peak_projection_does_not_claim_to_feed_value(self):
        body = self.client.get("/models").data.decode()
        peak_row = body[body.index("Peak Projection v1"):]
        peak_row = peak_row[:peak_row.index("</tr>")]
        self.assertNotIn("feeds value", peak_row)

    def test_models_table_is_mobile_stacked_not_scroll(self):
        body = self.client.get("/models").data.decode()
        for label in ("Model", "Verdict", "Why", "Evidence", "As of"):
            self.assertIn('data-label="' + label + '"', body)

    def test_models_page_fail_soft_on_missing_registry(self):
        import app as app_mod
        orig = app_mod._MODEL_REGISTRY_PATH
        app_mod._MODEL_REGISTRY_PATH = Path("data/models/__does_not_exist__.json")
        app_mod._ARTIFACT_CACHE.clear()
        try:
            resp = self.client.get("/models")
            self.assertEqual(resp.status_code, 200)
            self.assertIn(b"not available right now", resp.data)
        finally:
            app_mod._MODEL_REGISTRY_PATH = orig
            app_mod._ARTIFACT_CACHE.clear()

    def test_models_evidence_unavailable_is_distinct_broken_state(self):
        import app as app_mod
        import json
        import tempfile
        tmp = Path(tempfile.mkdtemp()) / "reg.json"
        tmp.write_text(json.dumps({
            "generated_at": "2026-07-16",
            "entries": [{
                "id": "x", "name": "Broken Model", "verdict": "PROVISIONAL",
                "verdict_reason": "reason", "evidence": "data/models/__missing__.json",
                "evidence_label": "ev", "source_module": "prospects/rank_v1.py",
            }],
        }), encoding="utf-8")
        orig = app_mod._MODEL_REGISTRY_PATH
        app_mod._MODEL_REGISTRY_PATH = tmp
        app_mod._ARTIFACT_CACHE.clear()
        try:
            body = self.client.get("/models").data.decode()
            self.assertIn("models-evidence-broken", body)
            self.assertIn("Evidence unavailable", body)
            self.assertNotIn(">ev</a>", body)
        finally:
            app_mod._MODEL_REGISTRY_PATH = orig
            app_mod._ARTIFACT_CACHE.clear()

    def test_footer_links_models_on_board_page(self):
        self.assertIn(b"/models", self.client.get("/ledger").data)

    def test_methodology_cross_links_models(self):
        body = self.client.get("/methodology").data.decode()
        self.assertIn('id="model-verdicts"', body)
        self.assertIn("/models", body)

    def test_receipts_link_hidden_on_models_and_methodology_when_held(self):
        # 7/17 nav audit P1: /models and /methodology linked /receipts
        # unconditionally while base.html's primary nav correctly gates it
        # on receipts_hold. Flipping the hold must un-light both.
        import app as app_mod
        self.assertIn('href="/receipts"', self.client.get("/models").data.decode())
        self.assertIn('href="/receipts"', self.client.get("/methodology").data.decode())

        original = app_mod.RECEIPTS_HOLD
        app_mod.RECEIPTS_HOLD = True
        try:
            models_body = self.client.get("/models").data.decode()
            methodology_body = self.client.get("/methodology").data.decode()
        finally:
            app_mod.RECEIPTS_HOLD = original
        self.assertNotIn('href="/receipts"', models_body)
        self.assertNotIn('href="/receipts"', methodology_body)
        # The Ledger link is a separate, unheld surface and must stay.
        self.assertIn("/ledger", models_body)
        self.assertIn("/ledger", methodology_body)


class TestModelRegistryValidator(unittest.TestCase):
    def test_real_registry_validates_clean(self):
        from scripts.validate_model_registry import validate
        self.assertEqual(validate(), [])

    def test_missing_evidence_fails(self):
        import json
        import tempfile
        from scripts.validate_model_registry import validate
        tmp = Path(tempfile.mkdtemp()) / "reg.json"
        tmp.write_text(json.dumps({"entries": [{
            "id": "x", "verdict": "PROVISIONAL", "evidence": "data/nope.json",
            "source_module": "prospects/rank_v1.py",
        }]}), encoding="utf-8")
        errs = validate(tmp)
        self.assertTrue(any("missing evidence" in e for e in errs))

    def test_bad_verdict_label_fails(self):
        import json
        import tempfile
        from scripts.validate_model_registry import validate
        tmp = Path(tempfile.mkdtemp()) / "reg.json"
        tmp.write_text(json.dumps({"entries": [{
            "id": "x", "verdict": "MAYBE",
            "evidence": "data/models/valucast_prospect_comps.json",
            "source_module": "prospects/comps.py",
        }]}), encoding="utf-8")
        errs = validate(tmp)
        self.assertTrue(any("bad verdict" in e for e in errs))

    def test_validated_over_not_proven_artifact_fails(self):
        import json
        import tempfile
        from scripts.validate_model_registry import validate
        tmp = Path(tempfile.mkdtemp()) / "reg.json"
        tmp.write_text(json.dumps({"entries": [{
            "id": "x", "verdict": "VALIDATED",
            "evidence": "data/models/valucast_universal_prospect_index_backtest.json",
            "source_module": "prospects/universal.py",
        }]}), encoding="utf-8")
        errs = validate(tmp)
        self.assertTrue(any("not-yet-proven" in e for e in errs))

    def test_feeds_value_cannot_contradict_display_only_evidence(self):
        import json
        import tempfile
        from scripts.validate_model_registry import validate
        tmp = Path(tempfile.mkdtemp()) / "reg.json"
        tmp.write_text(json.dumps({"entries": [{
            "id": "peak", "verdict": "PROVISIONAL", "feeds_value": True,
            "evidence": "data/models/valucast_prospect_peak_projection_calibration.json",
            "source_module": "prospects/peak_projection.py",
        }]}), encoding="utf-8")
        errs = validate(tmp)
        self.assertTrue(any("feeds_value contradicts display-only evidence" in e for e in errs))


class TestBoardTimeMachineRoute(unittest.TestCase):
    """Board Time Machine route (plan 026): as-of banner + today link, quality
    disclosure, honest unavailable state, aggregate-only consensus (no
    per-source leak), and the path-traversal belt. Uses a fixture archive dir
    swapped into the app's store so the tests stay date-stable as the real
    archive grows, and derives its dates from the imported epoch so a future
    re-baseline does not break them."""

    def setUp(self):
        import tempfile
        from datetime import date, timedelta

        from web.board_time_machine_store import EPOCH_DATE, BoardTimeMachineStore

        self.client = app.test_client()
        app.config["TESTING"] = True
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fixture_dir = Path(tmp.name)

        def shift(days):
            return (date.fromisoformat(EPOCH_DATE) + timedelta(days=days)).isoformat()

        self.pre_date = shift(-1)
        self.post_date = shift(1)
        for day in (self.pre_date, self.post_date):
            self._write_board(day)
        self._orig_store = app_module.board_time_machine_store
        app_module.board_time_machine_store = BoardTimeMachineStore(self.fixture_dir)
        self.addCleanup(self._restore_store)

    def _write_board(self, day):
        import json

        source_ranks = {"fg_ord": 15, "hkb": 8, "pipeline": 3, "pl": 17, "sts": 3}
        rows = [
            {
                "rank": rank,
                "name": f"Fixture Player {rank}",
                "role": "hitter",
                "mlbam_id": str(700000 + rank),
                "mlb_team": "SEA",
                "level": "AA",
                "age": 20,
                "positions": ["SS"],
                "score": 60.0 - rank,
                "confidence": "medium",
                "eta": None,
                "eta_window": "one_to_two_years",
                "context_only": {"source_ranks": source_ranks},
            }
            for rank in (1, 2)
        ]
        (self.fixture_dir / f"{day}.json").write_text(
            json.dumps({
                "board": rows,
                "candidate_count": len(rows),
                "date": day,
                "generated_at": f"{day}T08:00:00",
                "rank_version": "9.9.9",
                "ranked_count": len(rows),
                "validation": {},
            }),
            encoding="utf-8",
        )

    @staticmethod
    def _editorial(iso):
        # Mirrors the editorial_date macro ("JULY 15, 2026") without strftime's
        # locale dependence or zero-padded days.
        from datetime import date

        months = [
            "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY",
            "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
        ]
        d = date.fromisoformat(iso)
        return f"{months[d.month - 1]} {d.day}, {d.year}"

    def _restore_store(self):
        app_module.board_time_machine_store = self._orig_store

    def _get(self, path):
        response = self.client.get(path)
        return response, response.data.decode("utf-8")

    def test_clean_date_renders_as_of_banner_and_today_link(self):
        response, html = self._get(f"/board/{self.post_date}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("BOARD AS OF", html)
        self.assertIn("View today's board", html)
        self.assertIn('href="/"', html)
        self.assertIn("9.9.9", html)            # the archive's own rank_version
        self.assertIn("Fixture Player 1", html)

    def test_pre_baseline_date_shows_disclosure_flag(self):
        response, html = self._get(f"/board/{self.pre_date}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Pre-baseline date", html)
        self.assertIn("/methodology#board-time-machine", html)

    def test_clean_date_has_no_pre_baseline_notice(self):
        _, html = self._get(f"/board/{self.post_date}")
        self.assertNotIn("Pre-baseline date", html)

    def test_unknown_date_renders_honest_unavailable_state(self):
        response, html = self._get("/board/2019-01-01")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No board was published", html)
        self.assertIn(self.pre_date, html)       # real archive range disclosed
        self.assertIn(self.post_date, html)
        self.assertIn("today's board", html)
        # Never a fabricated board: no fixture rows render on the unavailable page.
        self.assertNotIn("Fixture Player", html)

    def test_nearest_date_offered_as_itself_not_substituted(self):
        _, html = self._get("/board/2019-01-01")
        self.assertIn(f'href="/board/{self.pre_date}"', html)
        self.assertNotIn("BOARD AS OF", html)

    def test_no_per_source_ranks_in_html(self):
        _, html = self._get(f"/board/{self.post_date}")
        self.assertIn("~P#8", html)              # aggregate median renders
        self.assertIn("5 boards", html)          # with the board count
        for token in ("fg_ord", "hkb", "source_ranks"):
            self.assertNotIn(token, html)

    def test_path_traversal_and_junk_dates_fail_soft(self):
        for path in (
            "/board/..%2f..%2fetc",
            "/board/....",
            "/board/not-a-date",
            f"/board/{self.post_date}%2F..%2Fx",
            "/board/%2e%2e%2f%2e%2e",
        ):
            response = self.client.get(path)
            self.assertIn(response.status_code, (200, 404), path)
            if response.status_code == 200:
                html = response.data.decode("utf-8")
                self.assertIn("No board was published", html, path)
                self.assertNotIn("Fixture Player", html, path)

    def test_board_landing_shows_latest_available_date(self):
        response, html = self._get("/board")
        self.assertEqual(response.status_code, 200)
        self.assertIn("BOARD AS OF", html)
        self.assertIn("Fixture Player 1", html)

    def test_date_form_get_redirects_to_canonical_path(self):
        response = self.client.get(f"/board?date={self.post_date}")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers["Location"].endswith(f"/board/{self.post_date}"))

    def test_invalid_form_date_is_honest_not_500(self):
        response, html = self._get("/board?date=not-a-date")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No board was published", html)

    def test_empty_archive_renders_honest_empty_state(self):
        import tempfile

        from web.board_time_machine_store import BoardTimeMachineStore

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        app_module.board_time_machine_store = BoardTimeMachineStore(Path(tmp.name))
        response, html = self._get("/board")
        self.assertEqual(response.status_code, 200)
        self.assertIn("archive is empty", html)

    def test_prev_next_omitted_at_archive_ends_never_dead(self):
        # Oldest archived date: next only — no prev link exists at all.
        _, html = self._get(f"/board/{self.pre_date}")
        self.assertIn(f'rel="next" href="/board/{self.post_date}"', html)
        self.assertNotIn('rel="prev"', html)
        # Newest archived date: prev only — no next link exists at all.
        _, html = self._get(f"/board/{self.post_date}")
        self.assertIn(f'rel="prev" href="/board/{self.pre_date}"', html)
        self.assertNotIn('rel="next"', html)

    def test_prev_next_step_adjacent_entries_mid_archive(self):
        from web.board_time_machine_store import EPOCH_DATE

        # EPOCH_DATE sits between the pre (-1) / post (+1) fixtures; links must
        # step to adjacent archive ENTRIES, not calendar days.
        self._write_board(EPOCH_DATE)
        _, html = self._get(f"/board/{EPOCH_DATE}")
        self.assertIn(f'rel="prev" href="/board/{self.pre_date}"', html)
        self.assertIn(f'rel="next" href="/board/{self.post_date}"', html)

    def test_era_chip_on_pre_baseline_heading_only(self):
        _, html = self._get(f"/board/{self.pre_date}")
        self.assertIn("PRE-BASELINE ERA", html)
        self.assertIn("Pre-baseline date", html)   # chip points, notice remains
        _, html = self._get(f"/board/{self.post_date}")
        self.assertNotIn("PRE-BASELINE ERA", html)

    def test_picker_options_human_text_iso_values(self):
        _, html = self._get(f"/board/{self.post_date}")
        self.assertIn(
            f'<option value="{self.post_date}" selected>'
            f"{self._editorial(self.post_date)}</option>",
            html,
        )
        self.assertIn(
            f'<option value="{self.pre_date}">{self._editorial(self.pre_date)}</option>',
            html,
        )

    def test_archive_span_fineprint(self):
        _, html = self._get("/board")
        self.assertIn("2 boards archived", html)
        self.assertIn(
            f"{self._editorial(self.pre_date)} &rarr; {self._editorial(self.post_date)}", html
        )

    def test_methodology_has_board_time_machine_section(self):
        response, html = self._get("/methodology")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id="board-time-machine"', html)
        self.assertIn("<h3>The Archives: committed boards, replayed</h3>", html)
        self.assertIn('href="/board">Archives</a>', html)
        self.assertNotIn("Board Time Machine", html)
        self.assertIn("re-baseline", html)

    def test_site_nav_links_time_machine(self):
        _, html = self._get("/board")
        self.assertIn('href="/board" aria-current="page">Archives</a>', html)
        self.assertIn("<title>The Archives | ValuCast</title>", html)
        self.assertIn("THE ARCHIVES", html)
        self.assertNotIn("Time Machine", html)
