import sys
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import app as app_module
from app import app, context_season, store


@contextmanager
def published_phase(phase, target):
    """Serve pages as if the projection feed had been published with this phase and target season."""
    with patch.object(store, "_projection_phase", phase), \
         patch.object(store, "_target_season", target):
        yield


def valued_age_years():
    """(label, phase, target season, year the valued-age sentence must name).

    The MLB dynasty value uses age on April 1 of ONE season: the target season before a
    season starts, otherwise the context season. In season the expected year is computed
    the way the page computes it, never typed in; the preseason target is the literal the
    preseason tests patch in."""
    context = context_season()
    return (
        ("in season", "in_season_outlook", context, context),
        ("before a season", "preseason_full_season", 2027, 2027),
    )


class TestSourceSelection(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True
        # The in-house source is paused while its run's season differs from the target
        # season. These tests exercise the opt-in source itself, so make it current
        # (the paused behaviour is covered in test_inhouse_source_pause.py).
        patcher = patch.object(app_module, "_inhouse_source_current", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

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
        with patch.object(store, "_ros_status", "fetched"), \
             patch.object(store, "_projection_phase", "in_season_outlook"):
            r = self.client.get("/")
        self.assertIn(b'Redraft values use 2026 actual stats + Steamer', r.data)
        self.assertIn(
            b'all built in-house by ValuCast',
            r.data,
        )

    def test_footer_steamer_board_preseason_names_the_target_season(self):
        with patch.object(store, "_ros_status", "fetched"), \
             patch.object(store, "_projection_phase", "preseason_full_season"), \
             patch.object(store, "_target_season", 2027):
            r = self.client.get("/")
        self.assertIn(
            b"Redraft values use Steamer 2027 full-season projections, "
            b"scored against your league's categories and weights.",
            r.data,
        )
        self.assertNotIn(b'Redraft values use 2026 actual stats + Steamer', r.data)

    def test_caption_and_footer_refresh_oob_on_source_switch(self):
        # Both the caption and the footer live OUTSIDE #rankings-container, so an
        # htmx source switch must refresh both via hx-swap-oob (no full reload).
        vc = self.client.get("/rankings?source=valucast").data
        self.assertIn(b'id="source-caption"', vc)
        self.assertIn(b'id="footer-provenance"', vc)
        self.assertIn(b'hx-swap-oob="innerHTML:#footer-provenance"', vc)
        self.assertIn(b'fully ValuCast-built', vc)               # footer OOB content
        self.assertIn(self.CAPTION_ANCHOR, vc)                   # caption OOB content

        with patch.object(store, "_ros_status", "fetched"), \
             patch.object(store, "_projection_phase", "in_season_outlook"):
            st = self.client.get("/rankings").data
        self.assertIn(b'hx-swap-oob="innerHTML:#footer-provenance"', st)
        self.assertIn(b'Redraft values use 2026 actual stats + Steamer', st)  # footer reverts
        self.assertIn(b'all built in-house by ValuCast', st)
        self.assertNotIn(self.CAPTION_ANCHOR, st)                            # caption cleared

    def test_methodology_page_renders_honest_statements(self):
        # The full Group-E methodology page is exhaustively covered by
        # test_methodology_validation.py; this keeps the core honesty markers in the
        # source-feature suite, updated to the rewritten page's wording.
        r = self.client.get("/methodology")
        self.assertEqual(r.status_code, 200)
        body = r.data
        self.assertIn(b'no third-party projection', body)        # pitching provenance
        self.assertIn(b'Public MLB statistics', body)            # provenance table row
        self.assertIn(b'Savant xBA/xSLG', body)
        self.assertIn(b'ValuCast H+P v1', body)
        self.assertIn(b'June 2026', body)
        self.assertIn(b'not an apples-to-apples', body)
        self.assertNotIn(b'0.87', body)                          # no internal corr leak

    @staticmethod
    def age_basis(year):
        return (f"Age shown is the player's age on the board date. "
                f"MLB dynasty values use age on April 1, {year}.")

    def test_dynasty_and_prospect_footers_state_the_age_basis(self):
        for label, phase, target, year in valued_age_years():
            with published_phase(phase, target):
                for mode in ("dd_dynasty", "prospects"):
                    with self.subTest(phase=label, mode=mode):
                        body = self.client.get(f"/?mode={mode}").data.decode("utf-8")
                        self.assertIn(self.age_basis(year), body)
                        if year != context_season():
                            # The target season wins before a season: never the context year.
                            self.assertNotIn(self.age_basis(context_season()), body)
                # Said once, on the dynasty/prospect footer: not on the redraft board.
                with self.subTest(phase=label, mode="redraft"):
                    self.assertNotIn(
                        self.age_basis(year), self.client.get("/").data.decode("utf-8"))

    def test_methodology_states_the_dynasty_board_age_basis(self):
        for label, phase, target, year in valued_age_years():
            with self.subTest(phase=label), published_phase(phase, target):
                body = " ".join(self.client.get("/methodology").data.decode("utf-8").split())
                self.assertIn("Age on the dynasty board.", body)
                self.assertIn(self.age_basis(year), body)
                if year != context_season():
                    self.assertNotIn(self.age_basis(context_season()), body)
                # Scoped to the dynasty board: the H+P pitching sentence is unchanged.
                self.assertIn("the v1 pitching model has no aging curve", body)

    def test_methodology_footer_has_no_steamer_redraft_claim(self):
        r = self.client.get("/methodology")
        self.assertNotIn(b'Redraft values use 2026 actual stats + Steamer', r.data)

    def test_internal_methodology_doc_exists(self):
        doc = Path(__file__).parent.parent / "docs" / "valucast-methodology.md"
        self.assertTrue(doc.exists(), "internal methodology doc missing")
        text = doc.read_text(encoding="utf-8")
        for marker in ("ValuCast H+P v1", "SHORTFALL", "rung", "carryover", "0.87"):
            self.assertIn(marker, text)
