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

        secondary = html[
            html.index('<div id="toolbar-secondary" class="toolbar-secondary">'):
            html.index("</div>", html.index('<div id="toolbar-secondary" class="toolbar-secondary">'))
            + len("</div>")
        ]
        for marker in ('name="source"', 'name="pool"', 'name="position"',
                       'name="display"', "Export CSV", "Customize"):
            self.assertIn(marker, secondary)

        form = html[html.index('<form id="league-setup"'):html.index("</form>")]
        self.assertIn(secondary, form)

    def test_disclosure_is_absent_off_redraft(self):
        for path in ("/?mode=dd_dynasty", "/?mode=prospects"):
            html = self.html(path)
            self.assertNotIn('class="toolbar-filters-btn"', html)
            self.assertNotIn('aria-controls="toolbar-secondary"', html)
            self.assertNotIn('id="toolbar-secondary"', html)

    def test_disclosure_css_is_desktop_transparent_and_mobile_collapsed(self):
        css = self.html("/static/style.css")
        self.assertIn(".rank-toolbar-redraft .toolbar-filters-btn { display: none; }", css)
        self.assertIn(".rank-toolbar-redraft .toolbar-secondary { display: contents; }", css)
        self.assertIn(".rank-toolbar-redraft .toolbar-secondary { display: none; }", css)
        self.assertIn(".rank-toolbar-redraft .toolbar-secondary.open {", css)
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

    def test_customize_and_methodology_link_are_promoted(self):
        for path in ("/", "/?mode=dd_dynasty"):
            html = self.html(path)
            self.assertIn('class="customize-toggle primary-action"', html)
            self.assertIn('class="toolbar-how-link" href="/methodology">How it works</a>', html)

        prospects = self.html("/?mode=prospects")
        self.assertNotIn('class="customize-toggle primary-action"', prospects)
        self.assertNotIn('class="toolbar-how-link"', prospects)

    def test_empty_category_dashes_use_dimmed_na_class(self):
        html = self.html("/?pool=pitcher")
        self.assertIn('class="col-cat na"', html)
        css = self.html("/static/style.css")
        self.assertIn(".rankings-table td.col-cat.na { opacity: .35; }", css)


if __name__ == "__main__":
    unittest.main()
