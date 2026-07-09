"""Buys board (2026-06-12): buy_score terms, board assembly, /buys route.

Unit tests pin the post-critique resolutions — gap-spanning step detection,
the momentum denominator floor, the consensus-gap clamp, None-safe
tie-breaks. Route tests run against the real committed feed (same precedent
as test_polish_jun12)."""
import unittest
from types import SimpleNamespace
from unittest import mock

import app as app_module
from web import buy_score


def _row(**kw):
    base = dict(
        id="p1", name="Test Prospect", player_type="prospect",
        is_prospect=True, positions=("SS",), team="MIL", age=20,
        dynasty_value=50.0, mlbam_id=123456, prospect_rank=10,
        level="AA", eta=2027, source_ranks={}, breakout_label="steady",
        value_history=(),
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _daily(values, start_day=1, month=6):
    return tuple((f"2026-{month:02d}-{day:02d}", v)
                 for day, v in enumerate(values, start=start_day))


class TestCleanTail(unittest.TestCase):
    def test_clean_series_kept_whole(self):
        hist = _daily([50.0, 50.4, 50.9, 51.2, 51.0])
        self.assertEqual(len(buy_score.clean_tail(hist)), 5)

    def test_step_mid_series_stops_walk(self):
        hist = _daily([50.0, 50.5, 64.0, 64.2, 64.5])  # +13.5 step on day 3
        tail = buy_score.clean_tail(hist)
        self.assertEqual([v for _, v in tail], [64.0, 64.2, 64.5])

    def test_step_at_edge_leaves_single_point(self):
        hist = _daily([50.0, 50.5, 64.0])
        self.assertEqual(len(buy_score.clean_tail(hist)), 1)

    def test_step_across_denylist_gap_detected(self):
        # The real 6/3 shape: 65.6 on 6/1, 76.2 on 6/3 — 6/2 denylisted.
        # A per-day rate (10.6/2 = 5.3 < 6) would slip through; the
        # consecutive-point rule must not.
        hist = (("2026-05-30", 65.2), ("2026-05-31", 65.4),
                ("2026-06-01", 65.6), ("2026-06-03", 76.2),
                ("2026-06-04", 76.5), ("2026-06-05", 76.4))
        tail = buy_score.clean_tail(hist)
        self.assertEqual(tail[0], ("2026-06-03", 76.2))

    def test_sparse_gap_breaks_tail(self):
        hist = (("2026-06-01", 50.0), ("2026-06-08", 50.5),
                ("2026-06-09", 50.6))
        self.assertEqual(len(buy_score.clean_tail(hist)), 2)

    def test_window_capped_at_14_days_from_latest(self):
        # 20 daily points 5/24..6/12; only the last 14 days may feed momentum
        hist = tuple(
            [(f"2026-05-{day:02d}", 50.0 + (day - 24) * 0.1)
             for day in range(24, 32)] +
            [(f"2026-06-{day:02d}", 50.8 + day * 0.1)
             for day in range(1, 13)])
        tail = buy_score.clean_tail(hist)
        self.assertEqual(tail[0][0], "2026-05-29")

    def test_short_history(self):
        self.assertEqual(buy_score.clean_tail(()), [])
        self.assertEqual(len(buy_score.clean_tail((("2026-06-12", 50.0),))), 1)


class TestMomentum(unittest.TestCase):
    def test_short_history_neutral(self):
        self.assertEqual(buy_score.momentum_score(()), 0.4)
        self.assertEqual(
            buy_score.momentum_score((("2026-06-12", 50.0),)), 0.4)

    def test_flat_maps_to_neutral(self):
        hist = _daily([80.0, 80.0, 80.0])
        self.assertAlmostEqual(buy_score.momentum_score(hist), 0.4)

    def test_full_clamp_saturates_to_one(self):
        # +15% over the tail with no single step beyond the threshold
        hist = _daily([80.0, 85.5, 91.5, 92.0])
        self.assertAlmostEqual(buy_score.momentum_score(hist), 1.0)

    def test_negative_clamp_floors_to_zero(self):
        hist = _daily([80.0, 76.0, 72.0])  # -10% -> clamp floor
        self.assertAlmostEqual(buy_score.momentum_score(hist), 0.0)

    def test_low_value_noise_damped_by_denominator_floor(self):
        # +0.4 on a value-3 prospect is noise, not a 13% surge. The
        # denominator floor keeps it near neutral instead of 1.0.
        hist = _daily([3.0, 3.2, 3.4])
        self.assertAlmostEqual(buy_score.momentum_score(hist), 0.453, places=3)


class TestBreakout(unittest.TestCase):
    def test_tier_map(self):
        self.assertEqual(buy_score.breakout_score("major_breakout"), 1.0)
        self.assertEqual(buy_score.breakout_score("breakout"), 0.75)
        self.assertEqual(buy_score.breakout_score("rising"), 0.5)
        self.assertEqual(buy_score.breakout_score("steady"), 0.15)
        self.assertEqual(buy_score.breakout_score(""), 0.10)
        self.assertEqual(buy_score.breakout_score(None), 0.10)
        self.assertEqual(buy_score.breakout_score("slipping"), -0.15)
        self.assertEqual(buy_score.breakout_score("falling"), -0.30)

    def test_unknown_label_neutral(self):
        self.assertEqual(buy_score.breakout_score("surging"), 0.10)


class TestConsensusGap(unittest.TestCase):
    def test_pipeline_unranked_strong_perf(self):
        # The Bolte shape: Pipeline-unranked, hkb 30.
        score = buy_score.consensus_gap_score({"hkb": 30, "milb_perf": 90})
        self.assertAlmostEqual(score, 0.955, places=2)

    def test_no_perf_ranks_no_signal(self):
        self.assertEqual(buy_score.consensus_gap_score({}), 0.0)
        self.assertEqual(buy_score.consensus_gap_score(None), 0.0)
        self.assertEqual(buy_score.consensus_gap_score({"cfr": 1}), 0.0)

    def test_pipeline_ahead_of_perf_no_signal(self):
        self.assertEqual(
            buy_score.consensus_gap_score({"pipeline": 5, "hkb": 40}), 0.0)

    def test_gap_beyond_150_clamps_to_one(self):
        score = buy_score.consensus_gap_score({"pipeline": 400, "hkb": 1})
        self.assertEqual(score, 1.0)

    def test_min_of_present_perf_ranks(self):
        a = buy_score.consensus_gap_score({"pipeline": 100, "hkb": 20})
        b = buy_score.consensus_gap_score(
            {"pipeline": 100, "hkb": 20, "milb_perf": 5})
        self.assertGreater(b, a)


class TestRunway(unittest.TestCase):
    def test_table_spot_checks(self):
        self.assertAlmostEqual(buy_score.runway_score(19, "A"), 0.95)
        self.assertAlmostEqual(buy_score.runway_score(24, "AAA"), 0.25)
        self.assertAlmostEqual(buy_score.runway_score(16, "A"), 1.0)
        self.assertAlmostEqual(buy_score.runway_score(30, "AAA"), 0.25)

    def test_missing_age_and_level_neutral(self):
        self.assertAlmostEqual(buy_score.runway_score(None, None), 0.5)

    def test_unknown_level_code_neutral(self):
        self.assertAlmostEqual(buy_score.runway_score(18, "Rk"), 0.75)


class TestEligibility(unittest.TestCase):
    def test_mlb_level_excluded(self):
        self.assertFalse(buy_score.eligible(_row(level="MLB")))
        self.assertTrue(buy_score.eligible(_row(level="AAA")))
        self.assertTrue(buy_score.eligible(_row(level=None)))

    def test_non_prospects_excluded(self):
        self.assertFalse(buy_score.eligible(
            _row(player_type="mlb", is_prospect=False)))

    def test_exclude_ids_operator_guard(self):
        with mock.patch.object(buy_score, "EXCLUDE_IDS", frozenset({"p1"})):
            self.assertFalse(buy_score.eligible(_row(id="p1")))
            self.assertTrue(buy_score.eligible(_row(id="p2")))

    def test_mlb_level_flippable(self):
        with mock.patch.object(buy_score, "INCLUDE_MLB_LEVEL", True):
            self.assertTrue(buy_score.eligible(_row(level="MLB")))


class TestBoard(unittest.TestCase):
    def _rows(self):
        surge = _daily([60.0, 62.0, 64.0, 66.0])
        flat = _daily([60.0, 60.0, 60.1, 60.0])
        return [
            _row(id="a", name="A Surger", breakout_label="major_breakout",
                 value_history=surge, age=19, level="A+",
                 source_ranks={"hkb": 20}),
            _row(id="b", name="B Riser", breakout_label="rising",
                 value_history=flat, age=20, level="AA",
                 source_ranks={"pipeline": 40, "hkb": 30}),
            _row(id="c", name="C Steady", breakout_label="steady",
                 value_history=flat, age=23, level="AAA",
                 source_ranks={"pipeline": 10, "hkb": 50}),
            _row(id="d", name="D Fader", breakout_label="falling",
                 value_history=flat, age=24, level="AAA",
                 source_ranks={}),
        ]

    def test_synthetic_ranking_order(self):
        board = buy_score.build_board(self._rows())
        self.assertEqual([r["name"] for r in board],
                         ["A Surger", "B Riser", "C Steady", "D Fader"])
        self.assertEqual([r["rank"] for r in board], [1, 2, 3, 4])

    def test_deterministic(self):
        a = buy_score.build_board(self._rows())
        b = buy_score.build_board(self._rows())
        self.assertEqual(a, b)

    def test_none_dynasty_value_tiebreak_does_not_crash(self):
        rows = [_row(id="x", name="Zed", dynasty_value=None),
                _row(id="y", name="Abe", dynasty_value=None),
                _row(id="z", name="Mid", dynasty_value=30.0)]
        board = buy_score.build_board(rows)
        # identical scores: dynasty_value desc (None -> 0), then name asc
        self.assertEqual([r["name"] for r in board], ["Mid", "Abe", "Zed"])

    def test_display_score_floor_and_silhouette_id(self):
        board = buy_score.build_board(
            [_row(breakout_label="falling", mlbam_id=None, team="FA",
                  value_history=_daily([60.0, 55.0, 52.0]))])
        self.assertGreaterEqual(board[0]["score"], 0.0)
        self.assertIn("/people/0/", board[0]["headshot_url"])
        self.assertIsNone(board[0]["logo_url"])

    def test_graphic_logo_aliases_include_fantasy_team_codes(self):
        teams = {"WSN": 120, "KCR": 118, "SDP": 135, "SFG": 137, "TBR": 139}
        rows = [
            _row(id=team, name=f"{team} Prospect", team=team, value_history=_daily([60.0, 60.1]))
            for team in teams
        ]
        board_by_team = {row["team"]: row for row in buy_score.build_board(rows)}
        for team, team_id in teams.items():
            self.assertIn(f"/team/{team_id}/spots/64", board_by_team[team]["logo_url"])

    def test_valucast_board_graphic_logo_aliases_include_fantasy_team_codes(self):
        rows = [{
            "rank": 1,
            "player_id": "clemmey",
            "name": "Alex Clemmey",
            "team": "WSN",
            "positions": ["P"],
            "level": "AA",
            "age": 20,
            "score": 57.0,
            "terms": {},
            "score_history": _daily([56.0, 56.4, 56.8, 57.0]),
        }]
        board = buy_score.build_valucast_board(rows)
        self.assertIn("/team/120/spots/64", board[0]["logo_url"])

    def _long_history_row(self):
        # 24 clean daily points 5/24..6/16, each step < STEP_THRESHOLD and no
        # gap > MAX_POINT_GAP_DAYS, so only the window edge can truncate it.
        hist = tuple(
            [(f"2026-05-{day:02d}", 50.0 + (day - 24) * 0.1)
             for day in range(24, 32)] +
            [(f"2026-06-{day:02d}", 50.8 + day * 0.1)
             for day in range(1, 17)])
        return {
            "rank": 1,
            "player_id": "wide",
            "name": "Wide History",
            "team": "MIL",
            "positions": ["SS"],
            "level": "AA",
            "age": 20,
            "score": 55.0,
            "terms": {},
            "score_history": hist,
        }

    def test_valucast_board_window_days_widens_curve_pills_are_not_inert(self):
        # Regression: the /buys window pills were inert because the board build
        # never threaded window_days into clean_tail, hard-capping every curve at
        # MOMENTUM_WINDOW_DAYS (14). Default caps at 14d; a 30d window re-spans.
        row = self._long_history_row()
        default_hist = buy_score.build_valucast_board([row])[0]["value_history"]
        wide_hist = buy_score.build_valucast_board(
            [row], window_days=30)[0]["value_history"]

        self.assertGreater(len(wide_hist), len(default_hist))
        # Default reach is 14 days back from the latest point (6/16 -> 6/02).
        self.assertEqual(default_hist[0][0], "2026-06-02")
        # 30d reach spans the whole clean series back to its first point (5/24).
        self.assertEqual(wide_hist[0][0], "2026-05-24")

    def test_valucast_board_default_window_matches_bare_clean_tail(self):
        # window_days=None must be identical to today's behavior for every
        # existing caller (share-card PNG stays on the canonical 14d view).
        row = self._long_history_row()
        default_hist = buy_score.build_valucast_board([row])[0]["value_history"]
        self.assertEqual(
            default_hist, buy_score.clean_tail(row["score_history"]))

    def test_graphic_presentation_fields(self):
        board = buy_score.build_board(self._rows())
        self.assertEqual(board[0]["initials"], "AS")
        self.assertEqual(board[0]["reason"], "Rank gap")
        self.assertEqual(buy_score.graphic_initials("Single"), "S")
        self.assertEqual(buy_score.graphic_initials(""), "VC")

    def test_n_clamping(self):
        self.assertEqual(buy_score.clamp_n(5), 10)
        self.assertEqual(buy_score.clamp_n(999), 60)
        self.assertEqual(buy_score.clamp_n("25"), 25)
        self.assertEqual(buy_score.clamp_n("junk"), 40)
        self.assertEqual(buy_score.clamp_n(None), 40)


class TestBuysGraphicCopy(unittest.TestCase):
    def test_spark_label_turns_history_into_urgency_copy(self):
        spark = {
            "delta": 3.6,
            "first_date": "2026-06-13",
            "last_date": "2026-06-16",
        }
        self.assertEqual(app_module._buy_spark_label(spark), "UP +3.6 OVER 3D")

    def test_spark_label_handles_flat_and_missing(self):
        self.assertEqual(
            app_module._buy_spark_label({
                "delta": 0,
                "first_date": "2026-06-13",
                "last_date": "2026-06-16",
            }),
            "FLAT OVER 3D",
        )
        self.assertEqual(app_module._buy_spark_label(None), "")


class _RealAppCase(unittest.TestCase):
    """Shared client over the real committed stores."""

    @classmethod
    def setUpClass(cls):
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()
        cls.dd_rows = app_module.dd_store.get_all()


class TestBuysRoute(_RealAppCase):
    def test_page_renders_list_and_graphic(self):
        with mock.patch.object(app_module, "AHEAD_OF_THE_CURVE_HOLD", False), \
             mock.patch.object(app_module, "dynasty_data_source", "valucast_public_snapshot"):
            r = self.client.get("/buys")
        self.assertEqual(r.status_code, 200)
        html = r.data.decode("utf-8")
        self.assertIn('class="buys-list', html)
        self.assertIn("Ahead of the Curve | ValuCast", html)
        self.assertIn('class="buys-heading-arc"', html)
        self.assertIn("The 40 best prospect buys by signal, not reputation", html)
        self.assertIn("html2canvas.min.js", html)
        self.assertIn("AHEAD OF THE CURVE", html)
        self.assertIn("Source:</strong> ValuCast buy signal", html)
        self.assertIn('class="bg-mark"', html)
        # Phase 2 retune: poster team-logo watermark removed from the share graphic.
        self.assertNotIn('class="bg-team-mark', html)
        self.assertIn("Top 40 prospect buys by signal, not reputation", html)
        self.assertIn("Ranks prospects by model strength, momentum, buy window, and runway", html)
        self.assertIn("buy score = model strength + momentum + buy window + runway", html)
        # Graphic node included twice: 5 featured + 35 compact each.
        self.assertEqual(html.count('class="bg-featured-card'), 10)
        self.assertEqual(html.count('class="bg-cell"'), 70)
        # Phase 2 retune: monogram/headshot avatars removed; cards lead with the name.
        self.assertEqual(html.count('class="bg-face bg-headshot-candidate"'), 0)
        self.assertEqual(html.count('class="bg-monogram"'), 0)
        self.assertEqual(html.count('class="bg-hero-name"'), 2)
        self.assertEqual(html.count('class="bg-support-name"'), 8)
        self.assertEqual(html.count('class="buys-row"'), 40)

    def test_n_shrinks_list_but_never_the_graphic(self):
        with mock.patch.object(app_module, "AHEAD_OF_THE_CURVE_HOLD", False), \
             mock.patch.object(app_module, "dynasty_data_source", "valucast_public_snapshot"):
            html = self.client.get("/buys?n=10").data.decode("utf-8")
        self.assertEqual(html.count('class="buys-row"'), 10)
        self.assertEqual(html.count('class="bg-featured-card'), 10)
        self.assertEqual(html.count('class="bg-cell"'), 70)

    def test_buys_context_fineprint_reach_tracks_selected_window(self):
        # The fineprint reach must equal the pill window (not a hardcoded 14),
        # and the false "June 13 / tracked value history" copy must be gone.
        ctx_30 = app_module._build_buys_page_context(spark_window=30)
        self.assertEqual(ctx_30["buy_curve_max_days"], 30)
        self.assertEqual(
            ctx_30["buy_curve_all_days"], buy_score.MOMENTUM_WINDOW_DAYS)
        # "All" (window None) falls back to the 14d momentum window.
        ctx_all = app_module._build_buys_page_context(spark_window=None)
        self.assertEqual(
            ctx_all["buy_curve_max_days"], buy_score.MOMENTUM_WINDOW_DAYS)

    def test_no_callups_and_prospects_only(self):
        board = buy_score.build_board(self.dd_rows)
        self.assertEqual(len(board), 40)
        ids = {r["id"] for r in board}
        for row in self.dd_rows:
            if row.level == "MLB" or not row.is_prospect:
                self.assertNotIn(row.id, ids)

    def test_dd_unavailable_fallback(self):
        stub = SimpleNamespace(is_available=False, generated_at=None)
        with mock.patch.object(app_module, "AHEAD_OF_THE_CURVE_HOLD", False), \
             mock.patch.object(app_module, "dd_store", stub), \
             mock.patch.object(app_module, "valucast_buy_store", stub):
            r = self.client.get("/buys")
        self.assertEqual(r.status_code, 200)
        html = r.data.decode("utf-8")
        self.assertIn("unavailable", html)
        self.assertNotIn('class="bg-cell"', html)

    def test_nav_links_present(self):
        # Buys is consolidated under Backfields, the prospect-hub nav entry
        # point present on every page; the standalone /buys link was retired.
        self.assertIn('href="/backfields"',
                      self.client.get("/map").data.decode("utf-8"))
        for mode in ("dd_dynasty", "prospects"):
            html = self.client.get(f"/?mode={mode}").data.decode("utf-8")
            self.assertIn('href="/backfields"', html)

    def test_aotc_hold_renders_intentional_hold_state(self):
        with mock.patch.object(app_module, "AHEAD_OF_THE_CURVE_HOLD", True), \
             mock.patch.object(app_module, "dynasty_data_source", "valucast_public_snapshot"):
            r = self.client.get("/buys")

        self.assertEqual(r.status_code, 200)
        html = r.data.decode("utf-8")
        self.assertIn("Ahead of the Curve returns later this week", html)
        self.assertIn("Ahead of the Curve | ValuCast", html)
        self.assertNotIn('class="buys-row"', html)
        self.assertNotIn('class="bg-cell"', html)
        self.assertNotIn("Boston Bateman", html)
        self.assertNotIn("Juneiker Caceres", html)

    def test_aotc_hold_hides_public_navigation_and_backfields_surface(self):
        with mock.patch.object(app_module, "AHEAD_OF_THE_CURVE_HOLD", True):
            map_html = self.client.get("/map").data.decode("utf-8")
            backfields_html = self.client.get("/backfields").data.decode("utf-8")

        self.assertNotIn('href="/buys"', map_html)
        self.assertNotIn('href="/buys"', backfields_html)
        # The held surface is the /buys "Ahead of the Curve" buy-signals board (its
        # risers section + the /buys link). The Backfields divergence list is a
        # separate, live surface intentionally branded "Ahead of the Curve", so the
        # hold gates the buy-board section -- not the brand string outright.
        self.assertNotIn('id="ahead-of-the-curve"', backfields_html)
        self.assertNotIn("Full Ahead of the Curve board", backfields_html)

    def test_aotc_hold_is_reversible_by_single_flag(self):
        if (
            not app_module.valucast_buy_store.is_available
            or not app_module.valucast_buy_store.ready_for_live_consumers
        ):
            self.skipTest("ValuCast buys feed not available")

        with mock.patch.object(app_module, "AHEAD_OF_THE_CURVE_HOLD", False), \
             mock.patch.object(app_module, "dynasty_data_source", "valucast_public_snapshot"):
            buys_html = self.client.get("/buys").data.decode("utf-8")
            map_html = self.client.get("/map").data.decode("utf-8")
            backfields_html = self.client.get("/backfields").data.decode("utf-8")

        self.assertIn('class="buys-row"', buys_html)
        self.assertIn('href="/buys"', map_html)
        self.assertIn('id="ahead-of-the-curve"', backfields_html)
        self.assertIn("Full Ahead of the Curve board", backfields_html)


if __name__ == "__main__":
    unittest.main()
