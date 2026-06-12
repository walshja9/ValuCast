import json
import tempfile
import unittest
from pathlib import Path

import app as app_module
from web import prospect_percentiles
from web.dd_feed_store import DDFeedStore
from web.dynasty_models import DynastyRankingRow


def _row(
    row_id,
    *,
    player_type="prospect",
    name=None,
    prospect_rank=1,
    change=0,
    age=19,
    positions=None,
    source_ranks=None,
    stat_line=None,
):
    return DynastyRankingRow.from_feed({
        "id": row_id,
        "player_type": player_type,
        "name": name or row_id.replace("_", " ").title(),
        "positions": positions or ["SS"],
        "mlb_team": "TEX",
        "age": age,
        "dynasty_rank": prospect_rank or 1,
        "dynasty_value": 70.0,
        "status": "minors" if player_type == "prospect" else "mlb",
        "prospect_rank": prospect_rank,
        "source_ranks": source_ranks,
        "breakout_label": "rising" if change > 0 else "falling" if change < 0 else "steady",
        "breakout_rank_change": change,
        "stat_line": stat_line,
    })


class TestProspectPercentiles(unittest.TestCase):
    def test_percentile_midrank_and_ties(self):
        self.assertEqual(
            prospect_percentiles.percentile_for({"ops": list(range(1, 11))}, "ops", 5),
            45,
        )
        self.assertEqual(
            prospect_percentiles.percentile_for({"ops": [1, 2, 2, 4]}, "ops", 2),
            50,
        )

    def test_k_pct_inversion_and_caption(self):
        low = prospect_percentiles.percentile_for({"k_pct": [10, 20, 30, 40]}, "k_pct", 10)
        high = prospect_percentiles.percentile_for({"k_pct": [10, 20, 30, 40]}, "k_pct", 40)
        self.assertGreater(low, high)
        self.assertEqual(
            prospect_percentiles.caption_for("k_pct", 92),
            "Elite bat-to-ball — rarely strikes out",
        )

    def test_percentile_clamps_best_and_worst(self):
        pool = {"ops": list(range(1, 101))}
        self.assertEqual(prospect_percentiles.percentile_for(pool, "ops", 100), 99)
        self.assertEqual(prospect_percentiles.percentile_for(pool, "ops", 1), 1)

    def test_percentile_none_safety(self):
        self.assertIsNone(prospect_percentiles.percentile_for({}, "ops", 1))
        self.assertIsNone(prospect_percentiles.percentile_for({"ops": [1]}, "ops", None))
        self.assertIsNone(prospect_percentiles.percentile_for({"avg": [1]}, "ops", 1))

    def test_card_percentiles_requires_eligible_prospect(self):
        pool = {"ops": [0.700, 0.900]}
        small = _row("small", stat_line={"pa": 80, "ops": 0.900})
        mlb = _row("mlb", player_type="mlb", prospect_rank=None, stat_line={"pa": 200, "ops": 0.900})
        self.assertEqual(prospect_percentiles.card_percentiles(pool, small), {})
        self.assertEqual(prospect_percentiles.card_percentiles(pool, mlb), {})

    def test_caption_neutral_and_non_headline_metric(self):
        self.assertIsNone(prospect_percentiles.caption_for("ops", 50))
        self.assertIsNone(prospect_percentiles.caption_for("avg", 95))

    def test_top_movers_filters_sorts_and_caps(self):
        rows = [
            _row("m20", prospect_rank=20, change=20),
            _row("m15", prospect_rank=15, change=-15),
            _row("m12", prospect_rank=12, change=12),
            _row("m10", prospect_rank=10, change=10),
            _row("m8", prospect_rank=8, change=-8),
            _row("m7", prospect_rank=7, change=7),
            _row("quiet", prospect_rank=2, change=4),
            _row("deep", prospect_rank=201, change=99),
        ]
        movers = prospect_percentiles.top_movers(rows)
        self.assertEqual([m["change"] for m in movers], [20, -15, 12, 10, -8])
        self.assertEqual(len(movers), 5)
        self.assertEqual(prospect_percentiles.top_movers([rows[-2], rows[-1]]), [])

    def test_identity_line_agree_higher_elite_and_non_prospect(self):
        agree = _row(
            "agree",
            prospect_rank=10,
            source_ranks={"pipeline": 12, "cfr": 14, "hkb": 16},
        )
        higher = _row(
            "higher",
            prospect_rank=10,
            source_ranks={"pipeline": 30, "cfr": 32, "hkb": 34},
        )
        mlb = _row("mlb", player_type="mlb", prospect_rank=None)
        self.assertIn("see it the same way", prospect_percentiles.identity_line(agree, {}))
        self.assertIn("we're higher", prospect_percentiles.identity_line(higher, {}))
        self.assertIn(
            "carried by elite power",
            prospect_percentiles.identity_line(agree, {"iso": 95}),
        )
        self.assertIsNone(prospect_percentiles.identity_line(mlb, {}))


class TestPublicSourceRanks(unittest.TestCase):
    def test_cfr_raw_is_not_a_public_board(self):
        row = _row(
            "sources",
            source_ranks={
                "pipeline": 10,
                "cfr": 20,
                "cfr_raw": 90,
                "hkb": 30,
                "milb_perf": 2,
            },
        )
        self.assertEqual(row.public_source_ranks, {"pipeline": 10, "cfr": 20, "hkb": 30})
        self.assertEqual(row.public_source_consensus, 20)


FEED = {
    "schema_version": "1.0",
    "generated_at": "2026-06-12T08:00:00",
    "players": [
        {
            "id": "dd_mlb_fixture",
            "player_type": "mlb",
            "name": "MLB Fixture",
            "positions": ["OF"],
            "mlb_team": "NYY",
            "age": 27,
            "dynasty_rank": 1,
            "dynasty_value": 90.0,
            "status": "mlb",
        },
        {
            "id": "dd_prospect_top",
            "player_type": "prospect",
            "name": "Top Prospect",
            "positions": ["SS"],
            "mlb_team": "TEX",
            "age": 19,
            "dynasty_rank": 2,
            "dynasty_value": 75.0,
            "status": "minors",
            "level": "AA",
            "eta": 2027,
            "prospect_rank": 1,
            "source_ranks": {
                "pipeline": 4,
                "cfr": 6,
                "cfr_raw": 40,
                "hkb": 8,
                "milb_perf": 2,
            },
            "breakout_label": "rising",
            "breakout_rank_change": 12,
            "stat_line": {
                "avg": 0.300,
                "obp": 0.400,
                "slg": 0.550,
                "ops": 0.950,
                "iso": 0.250,
                "k_pct": 18.0,
                "bb_pct": 12.0,
                "pa": 200,
            },
        },
        {
            "id": "dd_prospect_small",
            "player_type": "prospect",
            "name": "Small Sample",
            "positions": ["OF"],
            "mlb_team": "SEA",
            "age": 20,
            "dynasty_rank": 3,
            "dynasty_value": 60.0,
            "status": "minors",
            "eta": None,
            "prospect_rank": 5,
            "source_ranks": {"pipeline": 7, "cfr": 9, "hkb": 11, "milb_perf": 4},
            "breakout_label": "falling",
            "breakout_rank_change": -7,
            "stat_line": {
                "avg": 0.250,
                "obp": 0.320,
                "slg": 0.400,
                "ops": 0.720,
                "iso": 0.150,
                "k_pct": 28.0,
                "bb_pct": 8.0,
                "pa": 80,
            },
        },
    ],
}


class TestCardIntelligenceUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            dir=Path(__file__).parent,
            delete=False,
            encoding="utf-8",
        )
        json.dump(FEED, fixture)
        fixture.close()
        cls.fixture_path = Path(fixture.name)
        cls.original_store = app_module.dd_store
        cls.original_pool = app_module.prospect_pool
        app_module.dd_store = DDFeedStore(cls.fixture_path)
        app_module.prospect_pool = prospect_percentiles.build_pool(app_module.dd_store.get_all())
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.dd_store = cls.original_store
        app_module.prospect_pool = cls.original_pool
        cls.fixture_path.unlink()

    def test_prospects_board_eta_cutoff_and_movers(self):
        response = self.client.get("/?mode=prospects&teams=4&pslots=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="col-eta sortable"', response.data)
        self.assertIn(b">2027</td>", response.data)
        self.assertIn(b'colspan="7"', response.data)
        self.assertIn(b'class="movers-strip"', response.data)

        htmx = self.client.get("/rankings?mode=prospects&teams=4&pslots=1")
        self.assertIn(b'class="movers-strip"', htmx.data)

    def test_movers_hidden_when_search_is_active(self):
        response = self.client.get("/?mode=prospects&search=Top")
        self.assertNotIn(b'class="movers-strip"', response.data)

    def test_prospect_card_has_identity_percentiles_and_pool_label(self):
        response = self.client.get("/player/dd_prospect_top?mode=prospects")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="identity-line"', response.data)
        self.assertIn(b'class="pct-rail"', response.data)
        self.assertIn(b"vs ValuCast prospect pool", response.data)

    def test_small_sample_card_has_tag_without_percentiles(self):
        response = self.client.get("/player/dd_prospect_small?mode=prospects")
        self.assertIn(b"small sample", response.data)
        self.assertNotIn(b'class="pct-rail"', response.data)

    def test_index_has_glass_toolbar_and_welcome_strip(self):
        response = self.client.get("/")
        self.assertIn(b'class="rank-toolbar rank-toolbar-redraft glass"', response.data)
        self.assertIn(b'class="welcome-strip glass"', response.data)


if __name__ == "__main__":
    unittest.main()
