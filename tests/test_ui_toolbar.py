import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
import app as app_module
from app import app


class TestToolbar(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def _prospect_board(self, callups=""):
        response = self.client.get("/", query_string={"mode": "prospects", "callups": callups})
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_single_toolbar_element(self):
        html = self.client.get("/").data.decode("utf-8")
        self.assertEqual(html.count('id="rank-toolbar"'), 1)
        # No leftover separate config-bar/filter-bar strips.
        self.assertNotIn('class="config-bar"', html)
        self.assertNotIn('class="filter-bar"', html)

    def test_source_present_in_points(self):
        # The in-house source is paused between seasons; make it current explicitly.
        with patch.object(app_module, "_inhouse_source_current", return_value=True):
            html = self.client.get("/?mode=points").data.decode("utf-8")
        self.assertIn('name="source"', html)             # source works in points
        self.assertNotIn('name="display"', html)         # toggle still cats/roto only

    def test_source_and_toggle_in_categories(self):
        with patch.object(app_module, "_inhouse_source_current", return_value=True):
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
        # Put recorded MLB service on both sides of the unfiltered limit.
        rows = app_module._prospect_rows(limit=None)
        self.assertGreater(len(rows), 201)
        inside = next(row for row in rows[:200] if row.mlbam_id not in (None, ""))
        refill = rows[200]
        outside = next(row for row in rows[201:] if row.mlbam_id not in (None, ""))
        service = {
            str(row.mlbam_id): "1 IP" if row.role == "pitcher" else "4 PA"
            for row in (inside, outside)
        }
        with patch.object(app_module, "_debuted_prospect_ids", return_value=service):
            boards = {view: self._prospect_board(view) for view in ("", "undebuted", "milb", "debuted")}

        for view, count, expected in (
            ("", 200, (True, False, False)),
            ("undebuted", 200, (False, True, False)),
            ("milb", 200, (False, True, False)),
            ("debuted", 2, (True, False, True)),
        ):
            with self.subTest(view=view):
                html = boards[view]
                self.assertEqual(html.count('class="player-row'), count)
                for row, visible in zip((inside, refill, outside), expected):
                    self.assertEqual(f'data-player-id="{row.id}"' in html, visible, row.id)

    def test_prospect_debut_filter_requires_service_for_same_day_pulse(self):
        row = next(row for row in app_module._prospect_rows() if app_module._row_identity_key(row))
        key = app_module._row_identity_key(row)
        player_id = f'data-player-id="{row.id}"'
        service = {str(row.mlbam_id): "1 IP" if row.role == "pitcher" else "4 PA"}
        with (
            patch.object(app_module, "_call_up_pulse_keys", return_value=frozenset({key})),
            patch.object(app_module, "_debuted_prospect_ids") as read_service,
        ):
            read_service.return_value = {}
            self.assertTrue(player_id in self._prospect_board("undebuted"), row.id)
            self.assertFalse(player_id in self._prospect_board("debuted"), row.id)
            read_service.return_value = service
            self.assertFalse(player_id in self._prospect_board("undebuted"), row.id)
            self.assertTrue(player_id in self._prospect_board("debuted"), row.id)

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
