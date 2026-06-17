"""Public-surface smoke gate for the daily publish pipeline.

Wired into the validate stage of scripts/run_daily_public_build.py so a clean
checkout fails fast when app.py imports a module that was never committed, or
when a public share-card route stops returning a real PNG. This is the gate
that would have caught web/share_pages.py shipping untracked.
"""
import unittest

from app import app

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

PNG_ROUTES = (
    "/buys/share-card.png",
    "/map/share-card.png",
    "/prospects/share-card.png?limit=20",
)

HTML_ROUTES = (
    "/buys",
    "/map",
)


class TestPublicSurfacesSmoke(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config["TESTING"] = True

    @staticmethod
    def _dd_ready():
        from app import dd_store

        return dd_store.is_available

    def test_public_html_routes_render(self):
        if not self._dd_ready():
            self.skipTest("DD feed not available")
        for route in HTML_ROUTES:
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

    def test_public_png_routes_return_png(self):
        if not self._dd_ready():
            self.skipTest("DD feed not available")
        for route in PNG_ROUTES:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data[:8], PNG_MAGIC)
                self.assertIn("image/png", response.content_type)


if __name__ == "__main__":
    unittest.main()
