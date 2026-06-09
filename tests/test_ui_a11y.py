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
            m = re.search(r"font-size:\s*0\.(6\d|7\d)rem", line)
            if m and "/* micro */" not in line:
                offenders.append(line.strip())
        self.assertEqual(offenders, [], f"sub-0.8rem content sizes: {offenders}")


if __name__ == "__main__":
    unittest.main()
