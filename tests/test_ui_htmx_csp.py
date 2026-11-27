"""Browser regression for CSP-safe board triggers."""
import threading
import unittest

try:
    from playwright.sync_api import sync_playwright
    _HAVE_PLAYWRIGHT = True
except Exception:  # noqa: BLE001 - optional browser dependency
    _HAVE_PLAYWRIGHT = False


@unittest.skipUnless(_HAVE_PLAYWRIGHT, "playwright not installed")
class TestHtmxCsp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from app import app
        from werkzeug.serving import make_server

        cls.server = make_server("127.0.0.1", 0, app, threaded=True)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_league_url_change_is_csp_clean_and_does_not_refresh_rankings(self):
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except Exception as exc:  # noqa: BLE001 - optional browser binary
                self.skipTest(f"playwright browser unavailable: {exc}")
            try:
                page = browser.new_page()
                console_errors = []
                rankings_requests = []
                page.on(
                    "console",
                    lambda message: console_errors.append(message.text)
                    if message.type == "error" else None,
                )
                page.on(
                    "request",
                    lambda request: rankings_requests.append(request.url)
                    if "/rankings" in request.url else None,
                )

                page.goto(
                    f"http://127.0.0.1:{self.port}/?mode=dd_dynasty",
                    wait_until="networkidle",
                )
                page.locator("button.customize-toggle").click()
                league_url = page.locator("#league-url-input")
                league_url.fill("https://www.fantrax.com/fantasy/league/test/home")
                league_url.blur()
                page.wait_for_timeout(500)

                self.assertEqual(console_errors, [])
                self.assertEqual(rankings_requests, [])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
