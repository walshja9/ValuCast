import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestSourceSelection(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def test_default_board_is_steamer(self):
        r = self.client.get("/rankings")
        self.assertEqual(r.status_code, 200)

    def test_valucast_source_loads_combined_board(self):
        r = self.client.get("/rankings?source=valucast")
        self.assertEqual(r.status_code, 200)
        self.assertGreater(len(r.data), 100)

    def test_unknown_source_clear_error(self):
        r = self.client.get("/rankings?source=bogus")
        self.assertEqual(r.status_code, 400)
        self.assertIn(b"source", r.data.lower())

    def test_form_carries_source_selector(self):
        # The form has a source <select> -> source serializes into every filter/
        # detail/compare/export request automatically.
        r = self.client.get("/")
        self.assertIn(b'name="source"', r.data)

    def test_valucast_source_is_sticky_via_replace_url(self):
        # /rankings sets HX-Replace-Url so a refresh keeps the ValuCast board.
        r = self.client.get("/rankings?source=valucast")
        self.assertIn("source=valucast", r.headers.get("HX-Replace-Url", ""))

    def test_full_page_reflects_selected_source(self):
        # Loading /?source=valucast renders the ValuCast radio pre-checked.
        r = self.client.get("/?source=valucast")
        self.assertIn(b'value="valucast" checked', r.data)

    def test_source_control_is_segmented_radios(self):
        # The plain <select> is gone; two name="source" radios remain.
        r = self.client.get("/")
        self.assertNotIn(b'<select name="source"', r.data)
        self.assertIn(b'name="source"', r.data)
        self.assertIn(b'type="radio"', r.data)
        self.assertIn(b'aria-label="Projection source"', r.data)

    def test_source_control_equal_weight_no_valucast_badge(self):
        # Equal visual weight: no ValuCast-only badge/marketing class.
        r = self.client.get("/")
        self.assertNotIn(b'vc-badge', r.data)
        self.assertNotIn(b'IN-HOUSE', r.data)

    def test_source_radios_are_focusable_not_display_none(self):
        # Accessibility: radios hidden via clip (focusable), with a focus ring,
        # NOT display:none (which removes them from tab order).
        css = self.client.get("/static/style.css").data
        self.assertIn(b'.source-seg', css)
        self.assertIn(b'clip-path', css)
        self.assertIn(b':focus-visible', css)
        self.assertNotIn(b'.source-opt input[type="radio"] { display: none', css)

    def test_steamer_default_no_source_in_url(self):
        r = self.client.get("/rankings")
        self.assertNotIn("source=", r.headers.get("HX-Replace-Url", ""))

    def test_valucast_position_filter_returns_players(self):
        # Pre-enrichment this returned zero (empty positions). Now SS filter yields rows.
        r = self.client.get("/rankings?source=valucast&position=SS")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"player-row", r.data)   # non-empty filtered board

    def test_export_honors_source(self):
        r = self.client.get("/export?source=valucast")
        self.assertEqual(r.status_code, 200)

    # Caption anchor: a phrase unique to the caption fragment (not the footer).
    CAPTION_ANCHOR = b'without third-party projection inputs'

    def test_caption_present_on_valucast_response(self):
        r = self.client.get("/rankings?source=valucast")
        self.assertIn(self.CAPTION_ANCHOR, r.data)
        self.assertIn(b'hx-swap-oob', r.data)
        self.assertIn(b'id="source-caption"', r.data)
        self.assertIn(b'/methodology', r.data)

    def test_caption_empty_on_steamer_response(self):
        # OOB element still ships (to clear a stale caption) but carries no text.
        r = self.client.get("/rankings")
        self.assertIn(b'id="source-caption"', r.data)
        self.assertNotIn(self.CAPTION_ANCHOR, r.data)

    def test_caption_absent_in_dynasty(self):
        r = self.client.get("/rankings?mode=dd_dynasty")
        self.assertNotIn(self.CAPTION_ANCHOR, r.data)

    def test_blank_team_dash_in_html_blank_in_export(self):
        # ~26% of ValuCast rows have no team -> HTML shows a dash in the team cell.
        html = self.client.get("/rankings?source=valucast").data.decode("utf-8")
        self.assertIn('class="col-team">—<', html)
        # Export keeps the team blank, never the display dash.
        csv = self.client.get("/export?source=valucast").data.decode("utf-8")
        self.assertNotIn("—", csv)

    def test_footer_valucast_board_no_steamer_claim(self):
        r = self.client.get("/?source=valucast")
        self.assertIn(b'fully ValuCast-built', r.data)
        self.assertNotIn(b'Redraft values use 2026 actual stats + Steamer', r.data)

    def test_footer_steamer_board_unchanged(self):
        r = self.client.get("/")
        self.assertIn(b'Redraft values use 2026 actual stats + Steamer', r.data)

    def test_caption_and_footer_refresh_oob_on_source_switch(self):
        # Both the caption and the footer live OUTSIDE #rankings-container, so an
        # htmx source switch must refresh both via hx-swap-oob (no full reload).
        vc = self.client.get("/rankings?source=valucast").data
        self.assertIn(b'id="source-caption"', vc)
        self.assertIn(b'id="footer-provenance"', vc)
        self.assertIn(b'hx-swap-oob="innerHTML:#footer-provenance"', vc)
        self.assertIn(b'fully ValuCast-built', vc)               # footer OOB content
        self.assertIn(self.CAPTION_ANCHOR, vc)                   # caption OOB content

        st = self.client.get("/rankings").data
        self.assertIn(b'hx-swap-oob="innerHTML:#footer-provenance"', st)
        self.assertIn(b'Redraft values use 2026 actual stats + Steamer', st)  # footer reverts
        self.assertNotIn(self.CAPTION_ANCHOR, st)                            # caption cleared

    def test_methodology_page_renders_honest_statements(self):
        r = self.client.get("/methodology")
        self.assertEqual(r.status_code, 200)
        body = r.data
        # Precise pitching-model provenance: ValuCast-built, no third-party projection.
        self.assertIn(b'built and validated by ValuCast', body)
        self.assertIn(b'does not consume Steamer', body)
        self.assertIn(b'No third-party pitcher projections', body)
        self.assertIn(b'Public MLB statistics', body)  # provenance table row
        self.assertIn(b'Savant xBA/xSLG', body)
        self.assertIn(b'did not clear our validation bar', body)
        self.assertIn(b'ValuCast H+P v1', body)
        self.assertIn(b'June 2026', body)
        # The two-boards distinction (comparison, not a formal backtest).
        self.assertIn(b'not an apples-to-apples', body)
        # Public page must NOT leak the internal correlation figure.
        self.assertNotIn(b'0.87', body)

    def test_methodology_footer_has_no_steamer_redraft_claim(self):
        r = self.client.get("/methodology")
        self.assertNotIn(b'Redraft values use 2026 actual stats + Steamer', r.data)

    def test_internal_methodology_doc_exists(self):
        doc = Path(__file__).parent.parent / "docs" / "valucast-methodology.md"
        self.assertTrue(doc.exists(), "internal methodology doc missing")
        text = doc.read_text(encoding="utf-8")
        for marker in ("ValuCast H+P v1", "SHORTFALL", "rung", "carryover", "0.87"):
            self.assertIn(marker, text)
