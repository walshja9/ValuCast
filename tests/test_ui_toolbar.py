import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from app import app


class TestToolbar(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_single_toolbar_element(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertEqual(html.count('id="rank-toolbar"'), 1)
        # No leftover separate config-bar/filter-bar strips.
        self.assertNotIn('class="config-bar"', html)
        self.assertNotIn('class="filter-bar"', html)

    def test_source_present_in_points(self):
        html = self.client.get("/?mode=points").data.decode("utf-8")
        self.assertIn('name="source"', html)             # source works in points
        self.assertNotIn('name="display"', html)         # toggle still cats/roto only

    def test_source_and_toggle_in_categories(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn('name="source"', html)
        self.assertIn('name="display"', html)

    def test_dynasty_toolbar_has_no_source_or_toggle(self):
        html = self.client.get("/?mode=dd_dynasty").data.decode("utf-8")
        self.assertNotIn('name="source"', html)
        self.assertNotIn('name="display"', html)
        self.assertIn('value="prospect"', html)          # dynasty-specific pool option

    def test_prospects_toolbar_minimal(self):
        html = self.client.get("/?mode=prospects").data.decode("utf-8")
        self.assertNotIn('name="pool"', html)
        self.assertNotIn('name="source"', html)
        self.assertIn('name="callups"', html)          # MiLB-only view filter
        self.assertIn("Share graphic", html)
        self.assertIn('class="graphic-menu"', html)
        self.assertIn("/prospects/share-card?limit=20", html)
        self.assertIn("/prospects/share-card?limit=10", html)
        self.assertIn("/prospects/share-card?limit=50", html)
        self.assertIn("/prospects/share-card?limit=100", html)
        self.assertIn("openProspectGraphic", html)

    def test_prospects_debut_filter_hides_and_isolates_debuted_players(self):
        # Debuted players carry SOME callup-chip variant ("Called up · TEAM" when
        # the same-day pulse has them, "In MLB · rookie-eligible" otherwise,
        # "MLB taste" for optioned-back guys) — assert on the chip class, not one
        # wording, so pulse freshness can't flake this test.
        default = self.client.get("/?mode=prospects").data.decode("utf-8")
        undebuted = self.client.get("/?mode=prospects&callups=undebuted").data.decode("utf-8")
        if 'class="callup-chip"' not in default:
            self.skipTest("no debuted prospects in current data")
        # The not-debuted view has no debuted players, hence no callup chips.
        self.assertNotIn('class="callup-chip"', undebuted)
        # Legacy param value keeps working for any shared URLs.
        legacy = self.client.get("/?mode=prospects&callups=milb").data.decode("utf-8")
        self.assertNotIn('class="callup-chip"', legacy)
        # Filtering runs BEFORE the top-200 slice, so the not-debuted view
        # repopulates to full depth instead of leaving a shorter board.
        self.assertEqual(
            default.count('class="player-row'),
            undebuted.count('class="player-row'),
        )
        # The debuted view surfaces retained call-ups from BEYOND the unfiltered
        # top-200 (62 active-roster retainees exist; only ~2 dozen rank inside it).
        debuted = self.client.get("/?mode=prospects&callups=debuted").data.decode("utf-8")
        self.assertGreater(debuted.count('class="player-row'), 30)

    def test_prospect_debut_filter_reads_same_day_pulse(self):
        # 7/3 Jarvis bug: a player called up AFTER the morning build exists only
        # in the call-up pulse -- the debut filter must read the pulse the badge
        # reads, or "Not debuted" shows players the UI badges CALLED UP.
        import app as app_module
        pulse_keys = app_module._call_up_pulse_keys()
        pulse_rows = [
            r for r in app_module.dd_store.filter(pool="prospect")
            if (app_module._row_identity_key(r) or "") in pulse_keys
        ]
        if not pulse_rows:
            self.skipTest("no same-day pulse call-ups on the current board")
        undebuted = self.client.get("/?mode=prospects&callups=undebuted").data.decode("utf-8")
        debuted = self.client.get("/?mode=prospects&callups=debuted").data.decode("utf-8")
        for row in pulse_rows:
            self.assertNotIn(f'data-player-id="{row.id}"', undebuted)
        self.assertTrue(
            any(f'data-player-id="{row.id}"' in debuted for row in pulse_rows),
            "pulse call-ups missing from the Debuted view",
        )

    def test_got_the_call_includes_same_day_pulse(self):
        # Backfields "Got the Call" read only the morning feed flag -- same-day
        # pulse call-ups (Jim Jarvis, 7/3) were invisible for a full day.
        import app as app_module
        pulse = app_module._load_artifact(
            Path(app_module.__file__).parent / "data" / "models" / "valucast_call_up_pulse.json"
        ) or {}
        by_identity = pulse.get("by_identity") or {}
        if not by_identity:
            self.skipTest("no call-up pulse entries in current data")
        app_module._ACTIVE_ROSTER_ROWS = None  # reset process cache
        names = {r.get("name") for r in app_module._active_mlb_roster_rows()}
        missing = [e.get("name") for e in by_identity.values()
                   if isinstance(e, dict) and e.get("name") not in names]
        self.assertEqual(missing, [])

    def test_scoring_switch_updates_display_slot_oob(self):
        # P1 fix: switching Categories<->Points must restructure the toolbar (the
        # Category-value toggle), not just the table. The OOB #display-slot does it.
        cats = self.client.get("/rankings?mode=categories").data.decode("utf-8")
        self.assertIn('id="display-slot" hx-swap-oob', cats)
        self.assertIn('name="display"', cats)              # toggle present for categories
        pts = self.client.get("/rankings?mode=points").data.decode("utf-8")
        self.assertIn('id="display-slot" hx-swap-oob', pts)  # slot still emitted...
        self.assertNotIn('name="display"', pts)              # ...but emptied for points


class TestStickyOffset(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_sticky_offset_wired(self):
        css = self.client.get("/static/style.css").data.decode("utf-8")
        self.assertIn(".rank-toolbar", css)
        self.assertIn("position: sticky", css)
        self.assertIn("var(--toolbar-h", css)
        html = self.client.get("/").data.decode("utf-8")
        self.assertIn("ResizeObserver", html)


if __name__ == "__main__":
    unittest.main()
