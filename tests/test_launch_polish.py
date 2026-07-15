import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import app


class TestLaunchPolish(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    def html(self, path):
        return self.client.get(path).data.decode("utf-8")

    def test_welcome_strip_only_renders_on_customizable_boards(self):
        for path in ("/", "/?mode=dd_dynasty"):
            html = self.html(path)
            self.assertIn('id="welcome-strip"', html)
            self.assertIn("Values for your league — not someone else's.", html)
            self.assertIn(
                "Set your categories, weights, and roster rules — every number re-scores. "
                "Our validation is public, including what didn't work.",
                html,
            )
            self.assertIn("Customize your league", html)
            self.assertIn("How ValuCast works →", html)

        for path in ("/?mode=prospects", "/methodology"):
            self.assertNotIn('id="welcome-strip"', self.html(path))

    def test_welcome_dismissal_uses_throw_safe_storage(self):
        html = self.html("/")
        self.assertIn("vc_welcome_dismissed", html)
        self.assertIn("try { storage = window.localStorage; } catch (e) {}", html)
        self.assertIn("storage.setItem('vc_welcome_dismissed', '1')", html)
        self.assertIn("welcome-strip-hidden", html)
        self.assertIn('aria-label="Dismiss"', html)
        self.assertIn("if (panel && panel.classList.contains('collapsed')) toggleSetup();", html)
        self.assertIn("panel.scrollIntoView", html)

    def test_redraft_mobile_disclosure_contains_secondary_controls(self):
        html = self.html("/")
        self.assertIn(
            '<button type="button" class="toolbar-filters-btn" aria-expanded="false" '
            'aria-controls="toolbar-secondary" onclick="toggleToolbarFilters(this)">'
            "Filters &amp; view</button>",
            html,
        )
        self.assertIn("function toggleToolbarFilters(btn)", html)
        self.assertIn("btn.setAttribute('aria-expanded', panel.classList.contains('open'))", html)

        # Slice through the Customize button (the disclosure's last control) —
        # first-</div> slicing broke once the share menu nested a div inside.
        start = html.index('<div id="toolbar-secondary" class="toolbar-secondary">')
        end = html.index("Customize</button>", start) + len("Customize</button>")
        secondary = html[start:end]
        for marker in ('name="source"', 'name="pool"', 'name="position"',
                       'name="display"', "Export CSV", "Customize"):
            self.assertIn(marker, secondary)

        form = html[html.index('<form id="league-setup"'):html.index("</form>")]
        self.assertIn(secondary, form)

    def test_mobile_disclosure_renders_on_all_board_horizons(self):
        for path in ("/", "/?mode=dd_dynasty", "/?mode=prospects"):
            html = self.html(path)
            self.assertIn('class="toolbar-filters-btn"', html)
            self.assertIn('aria-controls="toolbar-secondary"', html)
            self.assertIn('id="toolbar-secondary"', html)

    def test_disclosure_css_is_desktop_transparent_and_mobile_collapsed(self):
        css = self.html("/static/style.css")
        self.assertIn(".rank-toolbar .toolbar-filters-btn { display: none; }", css)
        self.assertIn(".rank-toolbar .toolbar-secondary { display: contents; }", css)
        self.assertIn(".rank-toolbar .toolbar-secondary { display: none; }", css)
        self.assertIn(".rank-toolbar .toolbar-secondary.open {", css)
        self.assertIn("order: 3;", css)
        self.assertIn("@media (max-width: 640px)", css)

    def test_dynasty_rankings_replace_url_keeps_league_settings(self):
        response = self.client.get(
            "/rankings?mode=dd_dynasty&pool=mlb&teams=14&budget=320"
        )
        url = response.headers.get("HX-Replace-Url", "")
        self.assertIn("pool=mlb", url)
        self.assertIn("teams=14", url)
        self.assertIn("budget=320", url)

    def test_prospect_rankings_replace_url_keeps_cutoff_setting(self):
        response = self.client.get("/rankings?mode=prospects&pslots=8")
        self.assertIn("pslots=8", response.headers.get("HX-Replace-Url", ""))

    def test_hostile_pool_param_falls_back_cleanly(self):
        for path in ("/?pool=garbage", "/?pool=garbage&mode=roto"):
            self.assertEqual(self.client.get(path).status_code, 200)

    def test_customize_and_methodology_link_are_promoted(self):
        # 7/14 declutter: the toolbar "How it works" link is gone on ALL
        # horizons — Methodology stays reachable via site-nav + welcome strip.
        for path in ("/", "/?mode=dd_dynasty"):
            html = self.html(path)
            self.assertIn('class="customize-toggle primary-action"', html)
            self.assertNotIn('class="toolbar-how-link"', html)
            self.assertIn('href="/methodology">Methodology</a>', html)

        prospects = self.html("/?mode=prospects")
        self.assertNotIn('class="customize-toggle primary-action"', prospects)
        self.assertNotIn('class="toolbar-how-link"', prospects)

    def test_empty_category_dashes_use_dimmed_na_class(self):
        html = self.html("/?pool=pitcher")
        self.assertIn('class="col-cat na"', html)
        css = self.html("/static/style.css")
        self.assertIn(".rankings-table td.col-cat.na { opacity: .35; }", css)

    def test_mobile_cards_surface_compact_stat_strip(self):
        html = self.html("/?pool=hitter")
        rows = re.findall(r'<tr class="player-row.*?</tr>', html, re.S)
        self.assertGreater(len(rows), 0)
        strip = re.search(r'<div class="mobile-stat-strip".*?</div>', rows[0], re.S)

        self.assertIsNotNone(strip)
        self.assertGreaterEqual(strip.group(0).count('class="mobile-stat '), 3)
        self.assertLessEqual(strip.group(0).count('class="mobile-stat '), 4)
        self.assertIn("mobile-stat-label", strip.group(0))
        self.assertIn("mobile-stat-value", strip.group(0))

        css = self.html("/static/style.css")
        self.assertIn(".mobile-stat-strip { display: none; }", css)
        self.assertIn("padding: 0.55rem 0.65rem", css)
        self.assertIn("display: inline-flex", css)
        self.assertIn("flex-wrap: wrap", css)

    def test_small_phone_breakpoint_tightens_dense_surfaces(self):
        css = self.html("/static/style.css")
        self.assertIn("@media (max-width: 400px)", css)
        self.assertIn(".buys-row {", css)
        self.assertIn("grid-template-columns: 1.25rem 30px minmax(0, 1fr) 44px;", css)
        self.assertIn(".scouting-proof-strip", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css)
        self.assertIn(".value-map-shell", css)
        self.assertIn("height: 58vh;", css)


if __name__ == "__main__":
    unittest.main()
