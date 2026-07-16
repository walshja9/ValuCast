"""Display-only raw MiLB Strike% on pitcher cards.

Strike% = strikes / total pitches from the season stat feed, rendered at
request time on the prospect card. DISPLAY-ONLY: never a value/rank/buy
input. None-safe omission is the contract — missing, zero, or corrupt
(strikes > pitches) counts render NOTHING, and hitters never show it.
"""
import unittest
from types import SimpleNamespace

import app as app_module
from web import prospect_percentiles
from web.dynasty_models import DynastyRankingRow


def _fake_row(*, positions=("SP",), mlbam_id="999900001"):
    return SimpleNamespace(positions=list(positions), mlbam_id=mlbam_id)


class TestPitcherStrikePctHelper(unittest.TestCase):
    def setUp(self):
        self._original_index = app_module.MILB_SEASON_STATS_BY_MLBAM

    def tearDown(self):
        app_module.MILB_SEASON_STATS_BY_MLBAM = self._original_index

    def _set_index(self, rows, mlbam_id="999900001"):
        app_module.MILB_SEASON_STATS_BY_MLBAM = {mlbam_id: rows}

    def test_counts_present_one_decimal(self):
        self._set_index([{"role": "pitcher", "pitches": 1000, "strikes": 658}])
        self.assertEqual(app_module._pitcher_strike_pct(_fake_row()), "65.8")

    def test_multi_level_rows_aggregate(self):
        self._set_index([
            {"role": "pitcher", "level": "AA", "pitches": 620, "strikes": 400},
            {"role": "pitcher", "level": "AAA", "pitches": 380, "strikes": 250},
        ])
        # (400 + 250) / (620 + 380) = 65.0
        self.assertEqual(app_module._pitcher_strike_pct(_fake_row()), "65.0")

    def test_counts_absent_returns_none(self):
        # Today's committed feed shape: pitcher rows without pitches/strikes.
        self._set_index([{"role": "pitcher", "level": "AA", "era": 3.10}])
        self.assertIsNone(app_module._pitcher_strike_pct(_fake_row()))

    def test_none_counts_returns_none(self):
        self._set_index([{"role": "pitcher", "pitches": None, "strikes": None}])
        self.assertIsNone(app_module._pitcher_strike_pct(_fake_row()))

    def test_zero_counts_returns_none(self):
        self._set_index([{"role": "pitcher", "pitches": 0, "strikes": 0}])
        self.assertIsNone(app_module._pitcher_strike_pct(_fake_row()))

    def test_corrupt_counts_suppress_entirely(self):
        # One corrupt row (strikes > pitches) poisons the stat even when a
        # second valid row exists — omit rather than publish a suspect number.
        self._set_index([
            {"role": "pitcher", "pitches": 100, "strikes": 120},
            {"role": "pitcher", "pitches": 500, "strikes": 300},
        ])
        self.assertIsNone(app_module._pitcher_strike_pct(_fake_row()))

    def test_non_numeric_counts_skipped(self):
        self._set_index([{"role": "pitcher", "pitches": "bad", "strikes": "worse"}])
        self.assertIsNone(app_module._pitcher_strike_pct(_fake_row()))

    def test_hitter_never_shows_it(self):
        # Even with valid pitcher feed rows under the same mlbam id (two-way /
        # feed quirk), a hitter card renders nothing.
        self._set_index([{"role": "pitcher", "pitches": 1000, "strikes": 658}])
        self.assertIsNone(
            app_module._pitcher_strike_pct(_fake_row(positions=("SS",)))
        )

    def test_two_way_positions_treated_as_hitter(self):
        self._set_index([{"role": "pitcher", "pitches": 1000, "strikes": 658}])
        self.assertIsNone(
            app_module._pitcher_strike_pct(_fake_row(positions=("SP", "1B")))
        )

    def test_hitter_feed_rows_ignored(self):
        self._set_index([{"role": "hitter", "pitches": 1000, "strikes": 658}])
        self.assertIsNone(app_module._pitcher_strike_pct(_fake_row()))

    def test_missing_mlbam_returns_none(self):
        self._set_index([{"role": "pitcher", "pitches": 1000, "strikes": 658}])
        self.assertIsNone(app_module._pitcher_strike_pct(_fake_row(mlbam_id=None)))

    def test_committed_feed_today_is_omission_safe(self):
        """Against the real committed index: the helper must never raise, and
        every value it does produce must be a well-formed one-decimal percent."""
        for mlbam_id in list(self._original_index)[:200]:
            value = app_module._pitcher_strike_pct(
                _fake_row(mlbam_id=mlbam_id, positions=("SP",))
            )
            if value is not None:
                self.assertRegex(value, r"^\d{1,3}\.\d$")


def _prospect_row(row_id, *, positions, mlbam_id, stat_line):
    return DynastyRankingRow(
        id=row_id,
        name=row_id.replace("_", " ").title(),
        player_type="prospect",
        positions=tuple(positions),
        team="TEX",
        age=20,
        dynasty_rank=1,
        dynasty_value=55.0,
        status="minors",
        mlbam_id=mlbam_id,
        prospect_rank=10,
        level="AA",
        stat_line=stat_line,
        metadata={},
    )


class _Store:
    def __init__(self, rows):
        self._by_id = {row.id: row for row in rows}
        self._rows = list(rows)
        self.generated_at = "2026-07-16T12:00:00+00:00"
        self.schema_version = "1.1"
        self.is_available = True

    def get_all(self):
        return list(self._rows)

    def get_by_id(self, row_id):
        return self._by_id.get(row_id)


PITCHER_LINE = {
    "era": 2.45, "whip": 1.02, "k_per_9": 12.4,
    "bb_per_9": 2.4, "k_bb_pct": 26.0, "ip": 44.2,
}
HITTER_LINE = {
    "avg": 0.300, "obp": 0.380, "slg": 0.500, "ops": 0.880,
    "iso": 0.200, "k_pct": 20.0, "bb_pct": 10.0, "pa": 220,
}


class TestStrikePctCardRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._orig_store = app_module.dd_store
        cls._orig_pool = app_module.prospect_pool
        cls._orig_index = app_module.MILB_SEASON_STATS_BY_MLBAM
        rows = [
            _prospect_row("sp_with_counts", positions=("SP",),
                          mlbam_id="999900001", stat_line=dict(PITCHER_LINE)),
            _prospect_row("sp_without_counts", positions=("SP",),
                          mlbam_id="999900002", stat_line=dict(PITCHER_LINE)),
            _prospect_row("sp_corrupt_counts", positions=("SP",),
                          mlbam_id="999900003", stat_line=dict(PITCHER_LINE)),
            _prospect_row("hitter_row", positions=("SS",),
                          mlbam_id="999900004", stat_line=dict(HITTER_LINE)),
        ]
        app_module.dd_store = _Store(rows)
        app_module.prospect_pool = prospect_percentiles.build_pool(rows)
        app_module.MILB_SEASON_STATS_BY_MLBAM = {
            "999900001": [
                {"role": "pitcher", "level": "AA", "pitches": 620, "strikes": 400},
                {"role": "pitcher", "level": "AAA", "pitches": 380, "strikes": 250},
            ],
            "999900002": [{"role": "pitcher", "level": "AA", "era": 3.10}],
            "999900003": [{"role": "pitcher", "level": "AA", "pitches": 100, "strikes": 120}],
            # Pitcher-bucket rows under a hitter's id must never surface on his card.
            "999900004": [{"role": "pitcher", "level": "AA", "pitches": 1000, "strikes": 658}],
        }
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.dd_store = cls._orig_store
        app_module.prospect_pool = cls._orig_pool
        app_module.MILB_SEASON_STATS_BY_MLBAM = cls._orig_index

    def _card(self, row_id):
        response = self.client.get(
            f"/player/{row_id}?mode=prospects", headers={"HX-Request": "true"}
        )
        self.assertEqual(response.status_code, 200)
        return response.data

    def test_counts_present_renders_value_and_raw_label(self):
        body = self._card("sp_with_counts")
        self.assertIn(b'class="sample-context-note strike-pct-line"', body)
        self.assertIn(b"<strong>Strike%</strong> 65.0", body)
        # Raw-observed + display-only framing must ride with the number.
        self.assertIn(b"observed, not MLB-translated", body)
        self.assertIn(b"context, not a score input", body)

    def test_counts_absent_renders_nothing(self):
        body = self._card("sp_without_counts")
        self.assertNotIn(b"strike-pct-line", body)
        self.assertNotIn(b"Strike%", body)

    def test_corrupt_counts_render_nothing(self):
        body = self._card("sp_corrupt_counts")
        self.assertNotIn(b"strike-pct-line", body)
        self.assertNotIn(b"Strike%", body)

    def test_hitter_never_renders_it(self):
        body = self._card("hitter_row")
        self.assertNotIn(b"strike-pct-line", body)
        self.assertNotIn(b"Strike%", body)


if __name__ == "__main__":
    unittest.main()
