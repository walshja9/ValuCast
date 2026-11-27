"""Sort interaction: the announced aria-sort must match the actual row order.
Requires a JS runtime, so this uses Playwright + a threaded server; skipped when
Playwright (or its browser) isn't installed."""
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from playwright.sync_api import sync_playwright
    _HAVE_PW = True
except Exception:  # noqa: BLE001
    _HAVE_PW = False


@unittest.skipUnless(_HAVE_PW, "playwright not installed")
class TestSortInteraction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from werkzeug.serving import make_server
        from app import app
        cls.port = 5094
        cls.srv = make_server("127.0.0.1", cls.port, app, threaded=True)
        cls.t = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.t.start()
        time.sleep(0.8)

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def test_aria_sort_matches_row_order(self):
        base = f"http://127.0.0.1:{self.port}"
        try:
            pw = sync_playwright().start()
            browser = pw.chromium.launch()
        except Exception as e:  # noqa: BLE001 - no browser binary
            self.skipTest(f"playwright browser unavailable: {e}")
        try:
            pg = browser.new_page()
            pg.goto(base + "/", wait_until="networkidle")
            # The Value column (index 6) is numeric. Click its sort button.
            value_btn = pg.locator('th.col-value .sort-btn')

            def order_state():
                aria = pg.locator('th.col-value').get_attribute("aria-sort")
                vals = pg.eval_on_selector_all(
                    "tr.player-row td.col-value",
                    "els => els.slice(0,30).map(e => parseFloat(e.textContent)).filter(x => !isNaN(x))",
                )
                ascending_order = all(vals[i] <= vals[i + 1] for i in range(len(vals) - 1))
                descending_order = all(vals[i] >= vals[i + 1] for i in range(len(vals) - 1))
                return aria, ascending_order, descending_order

            value_btn.click()
            pg.wait_for_timeout(150)
            aria, asc, desc = order_state()
            if aria == "ascending":
                self.assertTrue(asc, "aria-sort=ascending but rows not ascending")
            else:
                self.assertEqual(aria, "descending")
                self.assertTrue(desc, "aria-sort=descending but rows not descending")

            value_btn.click()  # toggle
            pg.wait_for_timeout(150)
            aria2, asc2, desc2 = order_state()
            self.assertNotEqual(aria, aria2, "second click did not toggle aria-sort")
            if aria2 == "ascending":
                self.assertTrue(asc2)
            else:
                self.assertTrue(desc2)
        finally:
            browser.close()
            pw.stop()


if __name__ == "__main__":
    unittest.main()
