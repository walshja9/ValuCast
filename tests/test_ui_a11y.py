import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestTokens(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_root_token_block_exists(self):
        css = self.client.get("/static/style.css").data.decode("utf-8")
        self.assertIn(":root", css)
        self.assertIn("--c-blue", css)
        self.assertIn("var(--c-blue", css)  # actually used, not just declared


class TestTypeScale(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_no_content_text_below_floor(self):
        css = self.client.get("/static/style.css").data.decode("utf-8")
        offenders = []
        for line in css.splitlines():
            # Catch any size below 0.8rem — single- OR double-digit (0.7rem AND 0.75rem).
            m = re.search(r"font-size:\s*0\.[0-7]\d?rem", line)
            if m and "/* micro */" not in line:
                offenders.append(line.strip())
        self.assertEqual(offenders, [], f"sub-0.8rem content sizes: {offenders}")

    def test_no_alpha_hex_suffix_on_var(self):
        # A hex alpha suffix cannot be appended to a CSS variable (var(--x)22 is invalid).
        css = self.client.get("/static/style.css").data.decode("utf-8")
        bad = re.findall(r"var\(--[a-z-]+\)[0-9a-fA-F]{2}\b", css)
        self.assertEqual(bad, [], f"invalid alpha-suffixed var(): {bad}")


class TestPoolA11y(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_pool_radios_focusable_not_display_none(self):
        css = self.client.get("/static/style.css").data.decode("utf-8")
        self.assertNotIn('.pool-btn input[type="radio"] { display: none', css)
        self.assertIn("clip-path", css)
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('aria-label="Player pool"', html)


class TestSortA11y(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_sort_headers_have_buttons_and_aria_sort(self):
        html = self.client.get("/rankings").data.decode("utf-8")
        self.assertIn("aria-sort", html)
        # a real button inside the sortable header, not onclick on the th
        self.assertRegex(html, r'<th[^>]*aria-sort[^>]*>\s*<button')
        self.assertNotIn("<th class=\"col-name sortable\" onclick", html)


class TestRowA11y(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_no_role_button_on_row_and_has_detail_button(self):
        html = self.client.get("/rankings").data.decode("utf-8")
        self.assertNotIn('class="player-row" role="button"', html)
        self.assertNotIn('role="button"', html)               # rows contain nested buttons
        self.assertIn("aria-expanded", html)                  # detail toggle button
        self.assertIn('class="detail-toggle"', html)
        self.assertRegex(html, r'<button[^>]*class="compare-cb"')  # compare is a button
        self.assertRegex(html, r'aria-label="Add [^"]+ to compare"')

    def test_export_has_href(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertRegex(html, r'<a[^>]*id="export-btn"[^>]*href="')


if __name__ == "__main__":
    unittest.main()
