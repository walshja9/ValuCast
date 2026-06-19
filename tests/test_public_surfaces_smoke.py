"""Public-surface smoke gate for the daily publish pipeline.

Wired into the validate stage of scripts/run_daily_public_build.py so a clean
checkout fails fast when app.py imports a module that was never committed, or
when a public share-card route stops returning a real PNG. This is the gate
that would have caught web/share_pages.py shipping untracked.
"""
import types
import unittest
from unittest import mock

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
    "/backfields",
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
                # Buys can be a clean 503 when the governor hasn't approved the
                # board — a legitimate temporary state, not a build failure. It
                # must still never crash, and any 200 must be a real PNG.
                if route.startswith("/buys/") and response.status_code == 503:
                    continue
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.data[:8], PNG_MAGIC)
                self.assertIn("image/png", response.content_type)

    def test_health_ready_ignores_buys_block(self):
        """A governor block on Buys must NOT fail readiness: Board/Map/Scouting
        still serve, so Render keeps the deploy healthy. Guards the decoupling."""
        import app as app_module

        if not (
            app_module.public_snapshot_store.is_available
            and app_module.public_snapshot_store.ready_for_live_consumers
        ):
            self.skipTest("core public snapshot not live in this checkout")
        blocked_buys = types.SimpleNamespace(
            is_available=True, ready_for_live_consumers=False
        )
        with mock.patch.object(app_module, "valucast_buy_store", blocked_buys):
            response = self.client.get("/health/ready")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["valucast_buys"]["live"])

    def test_live_dynasty_source_is_valucast_owned(self):
        """When a ValuCast snapshot is live, the served board must be ValuCast-owned,
        never the DD feed. Allowlist (not exact match) so the planned stale source
        is accepted. Skips only when no snapshot is live in this checkout."""
        import app as app_module
        from app import public_snapshot_store

        if not (
            public_snapshot_store.is_available
            and public_snapshot_store.ready_for_live_consumers
        ):
            self.skipTest("ValuCast snapshot not live in this checkout")
        self.assertIn(
            app_module.dynasty_data_source,
            {"valucast_public_snapshot", "valucast_public_snapshot_stale"},
        )
        self.assertNotEqual(app_module.dynasty_data_source, "dd_feed")


if __name__ == "__main__":
    unittest.main()
