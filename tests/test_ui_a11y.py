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


if __name__ == "__main__":
    unittest.main()
