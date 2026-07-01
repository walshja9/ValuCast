"""Live URL-driven prospect league re-ranking (P2 Slice 1, presets only).

Covers the route surface (every path 200, ops_7x7 re-orders + renders the re-rank
column, roto_5x5 refuses partial coverage and keeps the default order, garbage
params degrade to the default board) and the re-scorer's category canonicalization
plus the row join.
"""
import re
import unittest

import app


def _player_names(html, limit=10):
    return re.findall(r"<strong>([^<]+)</strong>", html)[:limit]


class TestProspectLeagueAdapterRoute(unittest.TestCase):
    def setUp(self):
        self.client = app.app.test_client()
        app.app.config["TESTING"] = True

    @staticmethod
    def _board_ready():
        return app.dd_store.is_available and app._UNIVERSAL_PROSPECT_AVAILABLE

    def test_ops_7x7_reorders_and_renders_rerank_column(self):
        if not self._board_ready():
            self.skipTest("prospect board / universal model not available")
        default = self.client.get("/?mode=prospects")
        league = self.client.get("/?mode=prospects&preset=ops_7x7&rank_by=league")
        self.assertEqual(default.status_code, 200)
        self.assertEqual(league.status_code, 200)
        default_html = default.get_data(as_text=True)
        league_html = league.get_data(as_text=True)
        # The re-rank is a labeled column, not a $/value, and the default board
        # never shows it.
        self.assertIn("Your League #", league_html)
        self.assertNotIn("Your League #", default_html)
        # The re-ranked order differs from the model's default P# order.
        self.assertNotEqual(
            _player_names(default_html), _player_names(league_html)
        )
        # Independence/anchor caption is surfaced to the user.
        self.assertIn("Not a dollar value", league_html)

    def test_roto_5x5_falls_back_to_default_order_with_coverage_notice(self):
        if not self._board_ready():
            self.skipTest("prospect board / universal model not available")
        default = self.client.get("/?mode=prospects")
        roto = self.client.get("/?mode=prospects&preset=roto_5x5&rank_by=league")
        self.assertEqual(roto.status_code, 200)
        roto_html = roto.get_data(as_text=True)
        # The universal model has no W / SV projections, so roto must refuse to
        # re-rank: coverage notice shown, NO partial re-rank column, default order.
        self.assertIn("coverage-notice", roto_html)
        self.assertNotIn("Your League #", roto_html)
        self.assertEqual(
            _player_names(default.get_data(as_text=True)),
            _player_names(roto_html),
        )

    def test_garbage_preset_degrades_to_default_board(self):
        if not self._board_ready():
            self.skipTest("prospect board / universal model not available")
        for query in (
            "/?mode=prospects&preset=zzz&rank_by=league",
            "/?mode=prospects&preset=ops_7x7&rank_by=bogus",
            "/?mode=prospects&preset=ops_7x7",  # rank_by missing
        ):
            with self.subTest(query=query):
                response = self.client.get(query)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("Your League #", response.get_data(as_text=True))

    def test_rankings_route_forwards_preset_and_rank_by(self):
        if not self._board_ready():
            self.skipTest("prospect board / universal model not available")
        response = self.client.get(
            "/rankings?mode=prospects&preset=ops_7x7&rank_by=league"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your League #", response.get_data(as_text=True))
        push_url = response.headers.get("HX-Replace-Url", "")
        self.assertIn("preset=ops_7x7", push_url)
        self.assertIn("rank_by=league", push_url)

    def test_custom_cats_reorder_and_render_rerank_column(self):
        if not self._board_ready():
            self.skipTest("prospect board / universal model not available")
        default = self.client.get("/?mode=prospects")
        custom = self.client.get(
            "/?mode=prospects&rank_by=league"
            "&cats=HR,SB,OPS&pcats=K,ERA,WHIP"
        )
        self.assertEqual(default.status_code, 200)
        self.assertEqual(custom.status_code, 200)
        default_html = default.get_data(as_text=True)
        custom_html = custom.get_data(as_text=True)
        # An arbitrary supported category set (no preset) re-ranks and renders the
        # labeled column + the independence caption.
        self.assertIn("Your League #", custom_html)
        self.assertIn("Not a dollar value", custom_html)
        self.assertNotEqual(
            _player_names(default_html), _player_names(custom_html)
        )

    def test_custom_cats_with_unsupported_cat_falls_back_with_notice(self):
        if not self._board_ready():
            self.skipTest("prospect board / universal model not available")
        default = self.client.get("/?mode=prospects")
        # W is a recognized league category the prospect model cannot project, so a
        # custom set containing it must refuse to re-rank: coverage notice, no
        # re-rank column, default order preserved.
        custom = self.client.get(
            "/?mode=prospects&rank_by=league&cats=HR,SB&pcats=W,K"
        )
        self.assertEqual(custom.status_code, 200)
        custom_html = custom.get_data(as_text=True)
        self.assertIn("coverage-notice", custom_html)
        self.assertNotIn("Your League #", custom_html)
        self.assertEqual(
            _player_names(default.get_data(as_text=True)),
            _player_names(custom_html),
        )

    def test_ui_exposes_only_supported_prospect_categories(self):
        if not self._board_ready():
            self.skipTest("prospect board / universal model not available")
        html = self.client.get("/?mode=prospects").get_data(as_text=True)
        # Supported categories appear as selectable chips...
        for cat in ("HR", "SB", "OPS", "SO"):
            self.assertIn(f'name="cats" value="{cat}"', html)
        for pcat in ("K", "ERA", "WHIP", "SV", "HLD", "SV_HLD", "K_BB"):
            self.assertIn(f'name="pcats" value="{pcat}"', html)
        # ...while the categories the model can't project are NOT selectable, only
        # surfaced as an inline "not yet projected" hint. (SV and HLD graduated to
        # supported on 7/1 via the split trained targets; W has no label data.)
        self.assertNotIn('name="pcats" value="W"', html)
        self.assertIn("Not yet projected", html)


class TestProspectCategoryStateAndRescorer(unittest.TestCase):
    def test_state_canonicalizes_preset_into_board_vocabulary(self):
        args = {"preset": "ops_7x7", "rank_by": "league"}
        cats, pcats, active, label = app._prospect_category_state(
            type("A", (), {"get": lambda self, k, d=None: args.get(k, d)})()
        )
        self.assertTrue(active)
        self.assertEqual(label, "7x7 OPS")
        pcat_keys = dict(pcats)
        # Board vocabulary in the URL/state contract: K_BB not K/BB; the 7/1 split
        # preset carries separate SV and HLD (no combined SV_HLD, no IP, no L).
        self.assertIn("SV", pcat_keys)
        self.assertIn("HLD", pcat_keys)
        self.assertIn("K_BB", pcat_keys)
        self.assertNotIn("SV_HLD", pcat_keys)
        self.assertNotIn("SV+HLD", pcat_keys)
        # Negative-direction categories keep their sign from the adapter PRESETS.
        self.assertEqual(dict(cats)["SO"], -1)
        self.assertEqual(pcat_keys["ERA"], -1)

    def test_canonical_signs_match_the_shipped_presets(self):
        # Signs are derived from the adapter PRESETS, never invented: lower-is-better
        # cats are negative, counting/rate-positive cats are positive.
        signs = app._PROSPECT_CANONICAL_SIGNS
        for cat in ("ERA", "WHIP", "SO", "L"):
            self.assertEqual(signs[cat], -1, cat)
        for cat in ("HR", "SB", "OPS", "R", "RBI", "K", "QS", "SV_HLD", "K_BB"):
            self.assertEqual(signs[cat], 1, cat)

    def test_state_builds_custom_cats_with_canonical_signs(self):
        args = {"rank_by": "league", "cats": "HR,SB,OPS", "pcats": "K,ERA,WHIP"}
        stub = type("A", (), {
            "get": lambda self, k, d=None: args.get(k, d),
            "getlist": lambda self, k: (
                [args[k]] if isinstance(args.get(k), str) else (args.get(k) or [])
            ),
        })()
        cats, pcats, active, label = app._prospect_category_state(stub)
        self.assertTrue(active)
        self.assertEqual(label, "Custom")
        # Arbitrary picks get magnitude-1.0 weights with the canonical sign.
        self.assertEqual(dict(cats)["HR"], 1.0)
        self.assertEqual(dict(cats)["OPS"], 1.0)
        self.assertEqual(dict(pcats)["ERA"], -1.0)
        self.assertEqual(dict(pcats)["WHIP"], -1.0)

    def test_state_drops_unrecognized_cats_and_falls_back(self):
        # Pure garbage is dropped; an all-garbage set degrades to the default board.
        args = {"rank_by": "league", "cats": "ZZZ", "pcats": "QQQ"}
        stub = type("A", (), {
            "get": lambda self, k, d=None: args.get(k, d),
            "getlist": lambda self, k: (
                [args[k]] if isinstance(args.get(k), str) else (args.get(k) or [])
            ),
        })()
        cats, pcats, active, label = app._prospect_category_state(stub)
        self.assertEqual((cats, pcats, active, label), ((), (), False, ""))

    def test_rescorer_canonicalizes_board_keys_back_to_adapter_keys(self):
        # SV_HLD/K_BB (board) must canonicalize to SV+HLD/K/BB (adapter) so the
        # adapter recognizes them — otherwise it would report them as missing.
        cats = (("R", 1), ("HR", 1), ("RBI", 1), ("SB", 1),
                ("AVG", 1), ("OPS", 1), ("SO", -1))
        pcats = (("K", 1), ("QS", 1), ("SV_HLD", 1), ("ERA", -1),
                 ("WHIP", -1), ("K_BB", 1), ("L", -1))
        if not app._UNIVERSAL_PROSPECT_AVAILABLE:
            self.skipTest("universal model not available")
        scored = app._custom_prospect_ranks(cats, pcats)
        self.assertEqual(
            scored["role_status"]["hitter"]["status"], "research_ranked"
        )
        self.assertEqual(
            scored["role_status"]["pitcher"]["status"], "research_ranked"
        )
        self.assertEqual(
            scored["role_status"]["pitcher"]["missing_categories"], []
        )
        # Ranks are keyed (int(mlbam_id), role) and start at 1 within each role.
        self.assertTrue(scored["ranks"])
        for (mlbam_id, role), payload in scored["ranks"].items():
            self.assertIsInstance(mlbam_id, int)
            self.assertIn(role, {"hitter", "pitcher"})
            self.assertGreaterEqual(payload["adapter_rank"], 1)

    def test_prospect_adapter_key_join(self):
        row = type("Row", (), {"mlbam_id": "660271", "role": "hitter"})()
        self.assertEqual(app._prospect_adapter_key(row), (660271, "hitter"))
        # Unusable rows yield None (sort LAST, keep default context).
        self.assertIsNone(
            app._prospect_adapter_key(
                type("Row", (), {"mlbam_id": None, "role": "hitter"})()
            )
        )
        self.assertIsNone(
            app._prospect_adapter_key(
                type("Row", (), {"mlbam_id": "abc", "role": "hitter"})()
            )
        )
        self.assertIsNone(
            app._prospect_adapter_key(
                type("Row", (), {"mlbam_id": "1", "role": "two_way"})()
            )
        )


if __name__ == "__main__":
    unittest.main()
