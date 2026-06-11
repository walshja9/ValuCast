import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import _compute_dynasty_dollars, _compute_dynasty_tiers
from web.dynasty_models import DynastyRankingRow
from web.league_settings import LeagueSettings


def _row(i, value):
    return DynastyRankingRow(
        id=f"p{i}", name=f"Player {i}", player_type="mlb", positions=("OF",),
        team="NYY", age=27, dynasty_rank=i, dynasty_value=value,
        status="mlb", mlbam_id=None,
    )


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


from app import app as flask_app


class TestDynastyRoutes(unittest.TestCase):
    def setUp(self):
        self.client = flask_app.test_client()
        flask_app.config["TESTING"] = True

    def test_dynasty_config_summary_reflects_params(self):
        r = self.client.get("/?mode=dd_dynasty&teams=10&budget=300&roster=20&pslots=4")
        self.assertEqual(r.status_code, 200)
        self.assertIn("10 teams · $300 · 20 roster · 4 prospect slots",
                      r.data.decode("utf-8"))

    def test_dynasty_default_summary(self):
        r = self.client.get("/?mode=dd_dynasty")
        self.assertIn("12 teams · $200 · 26 roster · 5 prospect slots",
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

    def test_prospects_has_no_customize_panel(self):
        r = self.client.get("/?mode=prospects")
        self.assertNotIn(b'class="customize-toggle"', r.data)
        r2 = self.client.get("/rankings?mode=prospects")
        self.assertNotIn(b'hx-swap-oob="innerHTML:#setup-panel"', r2.data)


if __name__ == "__main__":
    unittest.main()
