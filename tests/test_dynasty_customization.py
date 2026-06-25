import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import app as app_module
from app import _compute_dynasty_dollars, _compute_dynasty_tiers
from web.dynasty_models import DynastyRankingRow
from web.league_settings import LeagueSettings
from web.public_snapshot_models import PublicSnapshotRow
from werkzeug.datastructures import MultiDict


def _row(i, value):
    return DynastyRankingRow(
        id=f"p{i}", name=f"Player {i}", player_type="mlb", positions=("OF",),
        team="NYY", age=27, dynasty_rank=i, dynasty_value=value,
        status="mlb", mlbam_id=None,
    )


def _snapshot_row(row_id, name, rank, value, positions=("OF",), player_type="mlb",
                  value_by_preset=None):
    return PublicSnapshotRow(
        id=row_id,
        name=name,
        player_type=player_type,
        positions=positions,
        team="NYY",
        age=27,
        rank=rank,
        value=value,
        value_scale="0_150",
        value_source="test",
        confidence=None,
        updated_at="2026-06-24",
        mlbam_id=None,
        value_by_preset=value_by_preset or {},
    )


class _PresetValueStore:
    is_available = True
    generated_at = "2026-06-24T00:00:00Z"
    schema_version = "1.1"

    def __init__(self, rows):
        self._rows = sorted(rows, key=lambda row: row.dynasty_rank)

    def get_all(self):
        return list(self._rows)

    def filter(self, player_type=None, position=None, search=None, pool=None):
        rows = self._rows
        if player_type:
            rows = [row for row in rows if row.player_type == player_type]
        if pool == "prospect":
            rows = [row for row in rows if row.is_prospect]
        elif pool == "mlb":
            rows = [row for row in rows if not row.is_prospect]
        if position:
            rows = [row for row in rows if position in row.positions]
        if search:
            query = search.lower()
            rows = [row for row in rows if query in row.name.lower()]
        return list(rows)


class TestDynastyDollars(unittest.TestCase):
    def setUp(self):
        # 10 players, values 100, 90, ..., 10
        self.rows = [_row(i + 1, 100 - 10 * i) for i in range(10)]

    def test_budget_conserved(self):
        # 2 teams x 3 roster = 6 rostered; total budget 2 x 100 = 200
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        rostered = [dollars[f"p{i}"] for i in range(1, 7)]
        self.assertAlmostEqual(sum(rostered), 200.0, delta=0.5)

    def test_below_cutoff_is_zero(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        for i in range(7, 11):
            self.assertEqual(dollars[f"p{i}"], 0.0)

    def test_rostered_minimum_one_dollar(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        # p6 (value 50) sits AT the cutoff: value - replacement = 0, floor kicks in
        self.assertEqual(dollars["p6"], 1.0)

    def test_hand_computed_top_player(self):
        # replacement value = value at rank 6 = 50.
        # surplus: p1..p5 = 50,40,30,20,10 (sum 150). Budget above the $1 floors
        # = 200 - 6 = 194. p1 = 1 + 50/150 * 194 = 65.67
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        dollars = _compute_dynasty_dollars(self.rows, s)
        self.assertAlmostEqual(dollars["p1"], 65.7, delta=0.1)

    def test_league_size_moves_dollars(self):
        small = _compute_dynasty_dollars(self.rows, LeagueSettings(2, 100, 3, 0))
        deep = _compute_dynasty_dollars(self.rows, LeagueSettings(2, 100, 5, 0))
        # Deeper league -> more rostered players to share budget -> top player worth less
        self.assertLess(deep["p1"], small["p1"])

    def test_cutoff_beyond_pool_all_rostered(self):
        s = LeagueSettings(teams=12, budget=200, roster=26, pslots=0)  # cutoff 312 > 10 rows
        dollars = _compute_dynasty_dollars(self.rows, s)
        self.assertTrue(all(dollars[f"p{i}"] >= 1.0 for i in range(1, 11)))
        self.assertAlmostEqual(sum(dollars.values()), 12 * 200, delta=1.0)

    def test_unsorted_input_handled(self):
        s = LeagueSettings(teams=2, budget=100, roster=3, pslots=0)
        expected = _compute_dynasty_dollars(self.rows, s)
        shuffled = list(reversed(self.rows))
        self.assertEqual(_compute_dynasty_dollars(shuffled, s), expected)


class TestTierPool(unittest.TestCase):
    def test_below_cutoff_rows_get_last_tier_not_zero(self):
        rows = [_row(i + 1, 150 - i) for i in range(30)]
        s = LeagueSettings(teams=2, budget=100, roster=10, pslots=0)  # cutoff 20
        from app import _dynasty_tiers_for
        tiers = _dynasty_tiers_for(rows, s)
        max_tier = max(tiers.values())
        for i in range(21, 31):
            self.assertEqual(tiers[f"p{i}"], max_tier)
        self.assertNotIn(0, tiers.values())


class TestDynastyPresetValueContext(unittest.TestCase):
    def setUp(self):
        self.original_store = app_module.dd_store
        self.original_flag = os.environ.get("VALUCAST_DYNASTY_PRESET_VALUE")
        app_module.dd_store = _PresetValueStore([
            _snapshot_row("ace", "Default Ace", 1, 120.0, positions=("SP",),
                          value_by_preset={"5x5": 120.0, "sv_hld": 95.0}),
            _snapshot_row("bat", "Default Bat", 2, 110.0,
                          value_by_preset={"5x5": 110.0, "sv_hld": 100.0}),
            _snapshot_row("prospect", "Fallback Prospect", 3, 80.0,
                          player_type="prospect"),
            _snapshot_row("reliever", "Hold Reliever", 4, 70.0, positions=("RP",),
                          value_by_preset={"5x5": 70.0, "sv_hld": 140.0}),
        ])
        self.z_patch = patch("app._dynasty_z_map", return_value={})
        self.z_patch.start()

    def tearDown(self):
        self.z_patch.stop()
        app_module.dd_store = self.original_store
        if self.original_flag is None:
            os.environ.pop("VALUCAST_DYNASTY_PRESET_VALUE", None)
        else:
            os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = self.original_flag

    def _set_flag(self, enabled):
        os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = "1" if enabled else "0"

    def _context(self, *pairs):
        args = MultiDict([
            ("teams", "2"),
            ("budget", "100"),
            ("roster", "2"),
            *pairs,
        ])
        return app_module._build_dynasty_context(args)

    def _ids(self, ctx):
        return [row.id for row in ctx["dd_rows"]]

    def _assert_same_board(self, left, right):
        self.assertEqual(left["dynasty_dollars"], right["dynasty_dollars"])
        self.assertEqual(left["tiers"], right["tiers"])
        self.assertEqual(self._ids(left), self._ids(right))

    def test_enabled_sv_hld_preset_moves_reliever_dollars_and_order(self):
        self._set_flag(True)
        default = self._context()
        sv_hld = self._context(("preset", "sv_hld"))

        self.assertEqual(sv_hld["active_preset"], "sv_hld")
        self.assertTrue(sv_hld["preset_value_enabled"])
        self.assertFalse(sv_hld["custom_cats_active"])
        self.assertEqual(sv_hld["dynasty_value_presets"],
                         ["5x5", "obp", "6x6", "sv_hld", "7x7", "7x7_ops", "points"])
        self.assertGreater(
            sv_hld["dynasty_dollars"]["reliever"],
            default["dynasty_dollars"]["reliever"],
        )
        self.assertGreater(
            self._ids(default).index("reliever"),
            self._ids(sv_hld).index("reliever"),
        )
        self.assertEqual(self._ids(sv_hld)[0], "reliever")
        self.assertEqual(sv_hld["preset_rank_by_id"]["reliever"], 1)

    def test_enabled_5x5_preset_matches_default_order_and_dollars(self):
        self._set_flag(True)
        default = self._context()
        five_by_five = self._context(("preset", "5x5"))

        self.assertEqual(five_by_five["active_preset"], "5x5")
        self._assert_same_board(five_by_five, default)

    def test_flag_off_sv_hld_preset_matches_default(self):
        self._set_flag(False)
        default = self._context()
        sv_hld = self._context(("preset", "sv_hld"))

        self.assertIsNone(sv_hld["active_preset"])
        self.assertFalse(sv_hld["preset_value_enabled"])
        self.assertEqual(sv_hld["preset_rank_by_id"], {})
        self._assert_same_board(sv_hld, default)

    def test_unknown_preset_with_flag_on_matches_default(self):
        self._set_flag(True)
        default = self._context()
        garbage = self._context(("preset", "garbage"))

        self.assertIsNone(garbage["active_preset"])
        self.assertTrue(garbage["preset_value_enabled"])
        self.assertEqual(garbage["preset_rank_by_id"], {})
        self._assert_same_board(garbage, default)


from app import app as flask_app


class TestDynastyRoutes(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        flask_app.config["TESTING"] = True

    def test_dynasty_config_summary_reflects_params(self):
        r = self.client.get("/?mode=dd_dynasty&teams=10&budget=300&roster=20&pslots=4")
        self.assertEqual(r.status_code, 200)
        self.assertIn("10 teams · $300 · 20 roster spots · 4 prospect slots",
                      r.data.decode("utf-8"))

    def test_dynasty_default_summary(self):
        r = self.client.get("/?mode=dd_dynasty")
        self.assertIn("12 teams · $200 · 26 roster spots · 5 prospect slots",
                      r.data.decode("utf-8"))

    def test_dynasty_no_longer_promises_customization(self):
        r = self.client.get("/?mode=dd_dynasty")
        self.assertNotIn("customization is coming", r.data.decode("utf-8").lower())

    def test_rankings_partial_carries_settings(self):
        r = self.client.get("/rankings?mode=dd_dynasty&teams=8&budget=260&roster=25&pslots=3")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"col-dollar", r.data)

    def test_export_carries_settings(self):
        r = self.client.get("/export?mode=dd_dynasty&teams=8&budget=100&roster=12")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"valucast-dynasty-rankings.csv",
                      r.headers["Content-Disposition"].encode())
        # shallow league (96 rostered): below-cutoff players export $0 (rendered 0.0)
        body = r.data.decode("utf-8")
        self.assertIn(",0.0,", body)

    def test_cutoff_divider_renders_when_visible(self):
        # 4x10=40 slots: divider must appear inside the top-200 board.
        # Match the markup, not the bare string — sortTable JS also says "cutoff-row".
        r = self.client.get("/?mode=dd_dynasty&teams=4&roster=10")
        self.assertIn(b'class="cutoff-row"', r.data)

    def test_cutoff_divider_absent_when_beyond_display(self):
        r = self.client.get("/?mode=dd_dynasty")  # 312 > 200 shown
        self.assertNotIn(b'class="cutoff-row"', r.data)

    def test_dynasty_has_customize_button_and_panel(self):
        r = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b"customize-toggle", r.data)
        self.assertIn(b"setup-panel collapsed", r.data)
        for name in (b'name="teams"', b'name="budget"', b'name="roster"', b'name="pslots"'):
            self.assertIn(name, r.data)

    def test_dynasty_panel_inputs_carry_current_values(self):
        r = self.client.get("/?mode=dd_dynasty&teams=14&budget=500")
        body = r.data.decode("utf-8")
        self.assertIn('name="teams" value="14"', body)
        self.assertIn('name="budget" value="500"', body)

    def test_league_url_survives_board_rerender(self):
        r = self.client.get("/rankings?mode=dd_dynasty&teams=10&league_url=https://www.fantrax.com/fantasy/league/abc/home")
        self.assertIn(b"fantrax.com/fantasy/league/abc", r.data)

    def test_dynasty_hidden_mode_input_still_present(self):
        # Guard against the 6/10 P0: form requests MUST carry mode on non-redraft
        r = self.client.get("/?mode=dd_dynasty")
        self.assertIn(b'<input type="hidden" name="mode" value="dd_dynasty">', r.data)

    def test_rankings_oob_swaps_dynasty_panel(self):
        r = self.client.get("/rankings?mode=dd_dynasty&teams=10")
        self.assertIn(b'hx-swap-oob="innerHTML:#setup-panel"', r.data)
        self.assertIn(b'hx-swap-oob="innerHTML:.config-summary"', r.data)

    def test_persistence_script_renders_on_dynasty_only(self):
        dyn = self.client.get("/?mode=dd_dynasty")
        red = self.client.get("/")
        self.assertIn(b"vc-league-settings", dyn.data)
        # Script ships on all pages but self-disables off-dynasty via isDynasty flag
        self.assertIn(b"var isDynasty = false", red.data)

    def test_prospects_has_no_customize_panel(self):
        r = self.client.get("/?mode=prospects")
        self.assertNotIn(b'class="customize-toggle"', r.data)
        r2 = self.client.get("/rankings?mode=prospects")
        self.assertNotIn(b'hx-swap-oob="innerHTML:#setup-panel"', r2.data)


class TestDynastyPresetValueTemplates(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        flask_app.config["TESTING"] = True
        self.original_store = app_module.dd_store
        self.original_flag = os.environ.get("VALUCAST_DYNASTY_PRESET_VALUE")
        app_module.dd_store = _PresetValueStore([
            _snapshot_row("ace", "Default Ace", 1, 120.0, positions=("SP",),
                          value_by_preset={"5x5": 120.0, "sv_hld": 95.0}),
            _snapshot_row("bat", "Default Bat", 2, 110.0,
                          value_by_preset={"5x5": 110.0, "sv_hld": 100.0}),
            _snapshot_row("prospect", "Fallback Prospect", 3, 80.0,
                          player_type="prospect"),
            _snapshot_row("reliever", "Hold Reliever", 4, 70.0, positions=("RP",),
                          value_by_preset={"5x5": 70.0, "sv_hld": 140.0}),
        ])
        self.z_patch = patch("app._dynasty_z_map", return_value={})
        self.z_patch.start()

    def tearDown(self):
        self.z_patch.stop()
        app_module.dd_store = self.original_store
        if self.original_flag is None:
            os.environ.pop("VALUCAST_DYNASTY_PRESET_VALUE", None)
        else:
            os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = self.original_flag

    def _row_fragment(self, body, player_name):
        marker = f"<strong>{player_name}</strong>"
        name_at = body.index(marker)
        row_start = body.rfind('<tr class="player-row', 0, name_at)
        row_end = body.index("</tr>", name_at)
        return body[row_start:row_end]

    def _button_fragment(self, body, preset_id):
        marker = f'data-value-preset="{preset_id}"'
        start = body.index(marker)
        button_start = body.rfind("<button", 0, start)
        button_end = body.index("</button>", start)
        return body[button_start:button_end]

    def test_flag_on_sv_hld_renders_server_preset_selector(self):
        os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = "1"

        response = self.client.get("/?mode=dd_dynasty&preset=sv_hld")
        body = response.data.decode("utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="preset-value-panel"', body)
        self.assertIn("League scoring", body)
        self.assertIn(
            "Pick your league's scoring. Values and ranks below are scored for your league's categories.",
            body,
        )
        self.assertIn('data-value-preset="sv_hld"', body)
        self.assertIn("active", self._button_fragment(body, "sv_hld"))
        self.assertNotIn('id="category-fit-panel"', body)
        self.assertNotIn('class="fit-category-grid"', body)
        self.assertNotIn("long-term ValuCast value does not change", body)

    def test_flag_on_sv_hld_marks_only_untuned_prospect_values(self):
        os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = "1"

        response = self.client.get("/?mode=dd_dynasty&preset=sv_hld")
        body = response.data.decode("utf-8")
        prospect_row = self._row_fragment(body, "Fallback Prospect")
        mlb_row = self._row_fragment(body, "Hold Reliever")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "+ Prospect values use the ValuCast baseline -- not yet tuned to your league's W/SV categories.",
            body,
        )
        self.assertIn('class="val-untuned-mark"', prospect_row)
        self.assertIn(">+</sup>", prospect_row)
        self.assertNotIn('class="val-untuned-mark"', mlb_row)

    def test_default_scoring_does_not_mark_untuned_values(self):
        os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = "1"

        implicit_response = self.client.get("/?mode=dd_dynasty")
        explicit_response = self.client.get("/?mode=dd_dynasty&preset=5x5")
        implicit_body = implicit_response.data.decode("utf-8")
        explicit_body = explicit_response.data.decode("utf-8")

        self.assertEqual(implicit_response.status_code, 200)
        self.assertEqual(explicit_response.status_code, 200)
        self.assertNotIn("Prospect values use the ValuCast baseline", implicit_body)
        self.assertNotIn('class="val-untuned-mark"', self._row_fragment(implicit_body, "Fallback Prospect"))
        self.assertNotIn("Prospect values use the ValuCast baseline", explicit_body)
        self.assertNotIn('class="val-untuned-mark"', self._row_fragment(explicit_body, "Fallback Prospect"))

    def test_flag_on_sv_hld_value_column_uses_preset_value(self):
        os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = "1"

        response = self.client.get("/?mode=dd_dynasty&preset=sv_hld")
        body = response.data.decode("utf-8")
        row = self._row_fragment(body, "Hold Reliever")

        self.assertEqual(response.status_code, 200)
        self.assertIn('<td class="col-value val-pos">140.0</td>', row)
        self.assertNotIn('<td class="col-value val-pos">70.0</td>', row)

    def test_flag_off_renders_old_category_fit_and_default_value(self):
        os.environ["VALUCAST_DYNASTY_PRESET_VALUE"] = "0"

        response = self.client.get("/?mode=dd_dynasty&preset=sv_hld")
        body = response.data.decode("utf-8")
        row = self._row_fragment(body, "Hold Reliever")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="category-fit-panel"', body)
        self.assertIn('data-fit-preset="svh"', body)
        self.assertIn('class="fit-category-grid"', body)
        self.assertIn("long-term ValuCast value does not change", body)
        self.assertNotIn('id="preset-value-panel"', body)
        self.assertIn('<td class="col-value val-pos">70.0</td>', row)
        self.assertNotIn('<td class="col-value val-pos">140.0</td>', row)


class TestLeagueImportRoute(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        flask_app.config["TESTING"] = True

    def test_import_success_fills_knobs(self):
        with patch("app.import_league", return_value=({"teams": 10, "roster": 30},
                                                      "Imported roster, teams from Fantrax.")):
            r = self.client.get("/league-import?league_url=https://www.fantrax.com/fantasy/league/abc/home&teams=12&budget=350&roster=26&pslots=5")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8")
        self.assertIn('name="teams" value="10"', body)      # imported
        self.assertIn('name="roster" value="30"', body)     # imported
        self.assertIn('name="budget" value="350"', body)    # NOT imported -> user's current value kept
        self.assertIn("Imported roster, teams", body)
        self.assertIn('hx-swap-oob="true"', body)  # notice lands in stable slot
        self.assertIn("league-setup-refresh", body)  # triggers board re-render

    def test_import_failure_keeps_knobs_and_notices(self):
        from web.league_import import ImportError_
        with patch("app.import_league", side_effect=ImportError_("This league is private — enter settings manually.")):
            r = self.client.get("/league-import?league_url=https://fantasy.espn.com/baseball/league?leagueId=1&teams=14")
        self.assertEqual(r.status_code, 200)
        body = r.data.decode("utf-8")
        self.assertIn('name="teams" value="14"', body)      # untouched
        self.assertIn("league is private", body)
        self.assertIn('hx-swap-oob="true"', body)  # notice lands in stable slot
        self.assertNotIn("league-setup-refresh", body)  # no refresh on failure

    def test_import_empty_url(self):
        r = self.client.get("/league-import?teams=12")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Unsupported URL", r.data)

    def test_imported_values_are_clamped(self):
        with patch("app.import_league", return_value=({"teams": 99, "roster": 200}, "Imported.")):
            r = self.client.get("/league-import?league_url=https://www.fantrax.com/fantasy/league/abc/home")
        body = r.data.decode("utf-8")
        self.assertIn('name="teams" value="20"', body)   # clamped to max
        self.assertIn('name="roster" value="50"', body)  # clamped to max

    def test_rankings_oob_panel_does_not_wipe_notice_slot(self):
        # The board-refresh response must not contain an OOB swap for the
        # notice slot — otherwise it would wipe the import notice.
        r = self.client.get("/rankings?mode=dd_dynasty&teams=10")
        self.assertNotIn(b"import-notice-slot", r.data)


if __name__ == "__main__":
    unittest.main()


class TestLeagueImportRateLimit(unittest.TestCase):
    """The throttle is bypassed under TESTING; flip it off to exercise it."""

    def setUp(self):
        import app as app_module
        self.app_module = app_module
        self.client = flask_app.test_client()
        flask_app.config["TESTING"] = False
        app_module._IMPORT_HITS.clear()

    def tearDown(self):
        flask_app.config["TESTING"] = True
        self.app_module._IMPORT_HITS.clear()

    def test_sixth_attempt_within_window_is_throttled(self):
        from web.league_import import ImportError_
        with patch("app.import_league",
                   side_effect=ImportError_("Unsupported URL — nope.")) as mock_imp:
            for i in range(5):
                r = self.client.get("/league-import?league_url=x")
                self.assertEqual(r.status_code, 200, i)
                self.assertNotIn(b"Too many import attempts", r.data)
            r = self.client.get("/league-import?league_url=x")
        self.assertEqual(r.status_code, 200)
        self.assertIn(b"Too many import attempts", r.data)
        self.assertEqual(mock_imp.call_count, 5)  # throttled call never fetches

    def test_throttle_notice_keeps_current_knobs(self):
        self.app_module._IMPORT_HITS["127.0.0.1"] = [
            __import__("time").monotonic()] * 5
        r = self.client.get("/league-import?league_url=x&teams=14")
        body = r.data.decode("utf-8")
        self.assertIn('name="teams" value="14"', body)
        self.assertIn("Too many import attempts", body)
