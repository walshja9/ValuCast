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
    stat_line_translated=None,
    level=None,
    context=None,
    components=None,
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
        "stat_line_translated": stat_line_translated,
        "level": level,
        "context": context,
        "components": components,
        "last_updated": "2026-06-12",
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

    def test_card_percentiles_support_pitcher_profiles(self):
        rows = [
            _row(
                "low_miss",
                positions=["SP"],
                stat_line={"ip": 40, "era": 4.50, "whip": 1.40, "k_per_9": 7.0, "bb_per_9": 4.8, "k_bb_pct": 6.0},
            ),
            _row(
                "mid_arm",
                positions=["SP"],
                stat_line={"ip": 42, "era": 3.50, "whip": 1.20, "k_per_9": 10.0, "bb_per_9": 3.2, "k_bb_pct": 16.0},
            ),
            _row(
                "top_arm",
                positions=["SP"],
                stat_line={"ip": 44, "era": 2.10, "whip": 0.90, "k_per_9": 13.0, "bb_per_9": 1.8, "k_bb_pct": 31.0},
            ),
        ]
        pool = prospect_percentiles.build_pool(rows)
        pcts = prospect_percentiles.card_percentiles(pool, rows[-1])
        bars = prospect_percentiles.profile_bars(rows[-1], pcts)
        grades = prospect_percentiles.skill_grades(rows[-1], pcts)

        self.assertGreater(pcts["k_per_9"], 75)
        self.assertGreater(pcts["bb_per_9"], 75)
        self.assertEqual(bars[0]["label"], "K/9")
        self.assertEqual(grades[0]["label"], "Miss")
        self.assertGreater(grades[0]["grade"], 60)
        self.assertIn("pitcher pool", prospect_percentiles.pool_label(rows[-1]))

    def test_skill_grades_are_current_stat_derived(self):
        row = _row(
            "tool_shape",
            stat_line={
                "pa": 220,
                "avg": 0.300,
                "obp": 0.390,
                "slg": 0.520,
                "ops": 0.910,
                "iso": 0.220,
                "k_pct": 15.0,
                "bb_pct": 12.0,
            },
        )
        grades = prospect_percentiles.skill_grades(
            row,
            {
                "avg": 70,
                "k_pct": 90,
                "iso": 80,
                "slg": 76,
                "bb_pct": 65,
                "ops": 82,
            },
        )

        self.assertEqual([g["label"] for g in grades], ["Hit", "Power", "Approach", "Production"])
        self.assertTrue(all(20 <= g["grade"] <= 80 for g in grades))
        self.assertEqual(grades[0]["metrics"], "AVG / K%")

    def test_skill_shape_compare_pairs_current_and_peak(self):
        grades = (
            {"label": "Hit", "grade": 78, "metrics": "AVG / K%"},
            {"label": "Power", "grade": 50, "metrics": "ISO / SLG"},
            {"label": "Production", "grade": 78, "metrics": "OPS"},
        )
        peak = [
            {"label": "Hit", "grade": 80},
            {"label": "Power", "grade": 60},
            {"label": "Impact", "grade": 80},  # hitter peak uses Impact for Production
        ]
        out = prospect_percentiles.skill_shape_compare(grades, peak)

        self.assertEqual([r["label"] for r in out], ["Hit", "Power", "Production"])
        self.assertEqual(out[0]["current"], 78)
        self.assertEqual(out[0]["peak"], 80)
        # Production pairs to Impact via alias
        self.assertEqual(out[2]["peak"], 80)
        # grade 50 -> (50-20)/60*100 = 50%
        self.assertAlmostEqual(out[1]["current_pct"], 50.0)
        self.assertAlmostEqual(out[0]["current_pct"], (78 - 20) / 60 * 100)

    def test_skill_shape_compare_without_peak_leaves_peak_none(self):
        grades = ({"label": "Hit", "grade": 70, "metrics": "AVG / K%"},)
        out = prospect_percentiles.skill_shape_compare(grades, [])
        self.assertIsNone(out[0]["peak"])
        self.assertIsNone(out[0]["peak_pct"])
        self.assertEqual(out[0]["current"], 70)

    def test_caption_neutral_and_non_headline_metric(self):
        self.assertIsNone(prospect_percentiles.caption_for("ops", 50))
        self.assertIsNone(prospect_percentiles.caption_for("avg", 95))
        self.assertEqual(
            prospect_percentiles.caption_for("ops", 80),
            "Strong all-around production",
        )

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

    def test_identity_line_reads_like_scouting_not_rank_narration(self):
        hitter = _row(
            "hitter",
            stat_line={"pa": 180, "ops": 0.920, "iso": 0.280, "k_pct": 30.0, "bb_pct": 12.0},
        )
        pitcher = _row(
            "pitcher",
            positions=["SP"],
            stat_line={"ip": 50, "era": 2.20, "k_per_9": 13.0, "bb_per_9": 5.0},
        )
        mlb = _row("mlb", player_type="mlb", prospect_rank=None)
        hitter_line = prospect_percentiles.identity_line(hitter, {"iso": 95})
        pitcher_line = prospect_percentiles.identity_line(pitcher, {})
        self.assertTrue(
            "power" in hitter_line.lower()
            or "thump" in hitter_line.lower()
            or "damage" in hitter_line.lower()
        )
        self.assertTrue(
            "contact" in hitter_line.lower()
            or "miss" in hitter_line.lower()
            or "empty swings" in hitter_line.lower()
        )
        self.assertTrue("walk" in pitcher_line or "control" in pitcher_line or "strike throwing" in pitcher_line)
        for line in (hitter_line, pitcher_line):
            self.assertNotIn("ValuCast", line)
            self.assertNotIn("public", line)
            self.assertNotIn("percentile", line)
            self.assertNotIn("P#", line)
            self.assertNotIn("carrying skill", line)
            self.assertNotIn("foundation", line)
            self.assertTrue(
                any(
                    outcome in line.lower()
                    for outcome in ("role", "regular", "starter", "bullpen", "bench", "floor")
                )
            )
            self.assertIn("confidence", line.lower())
        self.assertIsNone(prospect_percentiles.identity_line(mlb, {}))

    def test_identity_line_is_honest_when_no_performance_sample_exists(self):
        no_sample = prospect_percentiles.identity_line(_row("no_sample"), {})
        self.assertIn("current performance sample", no_sample)
        self.assertIn("anything stronger is projection", no_sample)
        self.assertIn("confidence: low", no_sample.lower())
        self.assertNotIn("public", no_sample)

    def test_identity_line_handles_called_up_and_old_samples_honestly(self):
        called_up = _row(
            "called_up",
            age=20,
            level="MLB",
            stat_line={"pa": 180, "ops": 0.900, "iso": 0.250, "k_pct": 20.0, "bb_pct": 12.0},
        )
        called_up_line = prospect_percentiles.identity_line(called_up, {})
        self.assertNotIn("in the majors", called_up_line)

        old_sample = _row(
            "old_sample",
            stat_line_translated={
                "season": 2025,
                "role": "hitter",
                "stats": [
                    {"key": "k_pct", "milb": 15.0},
                    {"key": "bb_pct", "milb": 10.0},
                    {"key": "iso", "milb": 0.150},
                ],
            },
        )
        old_sample_line = prospect_percentiles.identity_line(old_sample, {})
        self.assertIn("latest meaningful sample is from 2025", old_sample_line.lower())
        self.assertIn("confidence is low", old_sample_line.lower())

    def test_identity_line_calls_out_injured_stale_direct_stat_context(self):
        row = _row(
            "injured_stale",
            age=20,
            level="AA",
            stat_line={
                "pa": 552,
                "avg": 0.255,
                "obp": 0.355,
                "slg": 0.386,
                "ops": 0.741,
                "iso": 0.131,
                "k_pct": 19.6,
                "bb_pct": 12.7,
            },
            context={
                "stat_line_source_kind": "latest_milb_history",
                "stat_line_sample_season": 2025,
                "stat_line_sample": 552,
                "stat_line_sample_unit": "PA",
            },
            components={
                "availability": {
                    "status": "injured",
                    "risk_level": "high",
                    "sample": 552,
                    "sample_unit": "PA",
                },
                "availability_risk_discount": 0.12,
                "availability_adjusted": True,
            },
        )

        line = prospect_percentiles.identity_line(row, {})

        self.assertIn("currently injured", line.lower())
        self.assertIn("latest meaningful sample is from 2025", line.lower())
        self.assertIn("confidence is low", line.lower())

    def test_player_share_read_calls_out_injured_stale_sample_with_stats(self):
        row = _row(
            "walcott",
            name="Sebastian Walcott",
            age=20,
            level="AA",
            stat_line={
                "pa": 552,
                "avg": 0.255,
                "obp": 0.355,
                "slg": 0.386,
                "ops": 0.741,
                "iso": 0.131,
                "k_pct": 19.6,
                "bb_pct": 12.7,
            },
            context={
                "stat_line_source_kind": "latest_milb_history",
                "stat_line_sample_season": 2025,
                "stat_line_sample": 552,
                "stat_line_sample_unit": "PA",
            },
            components={
                "availability": {
                    "status": "injured",
                    "risk_level": "high",
                    "sample": 552,
                    "sample_unit": "PA",
                },
                "availability_risk_discount": 0.12,
                "availability_adjusted": True,
            },
        )

        line = app_module._prospect_player_card_read(
            row,
            {
                "ops": 48,
                "iso": 38,
                "k_pct": 77,
                "avg": 58,
                "obp": 58,
                "slg": 46,
                "bb_pct": 59,
            },
            row.metadata["context"],
        )

        self.assertIn("currently injured", line.lower())
        self.assertIn("2025 MiLB sample", line)
        self.assertIn(".255/.355/.386 line over 552 PA", line)

    def test_high_miss_high_walk_pitcher_read_is_not_rule_tree_copy(self):
        pitcher = _row(
            "high_miss_walk_risk",
            positions=["SP"],
            level="AAA",
            age=22,
            stat_line={
                "ip": 52,
                "era": 4.67,
                "whip": 1.40,
                "k_per_9": 13.3,
                "bb_per_9": 6.2,
                "k_bb_pct": 18.1,
            },
        )
        line = prospect_percentiles.identity_line(pitcher, {})

        self.assertIn("walk", line.lower())
        self.assertIn("starter", line.lower())
        self.assertIn("bullpen", line.lower())
        self.assertNotIn("failure point", line.lower())
        self.assertNotIn("points to the bullpen", line.lower())
        self.assertNotIn("strike throwing is", line.lower())

    def test_identity_line_contract_length_and_rotating_structure(self):
        rows = [
            _row(
                f"contract_{rank}",
                prospect_rank=rank,
                stat_line={
                    "pa": 180, "ops": 0.920, "iso": 0.280,
                    "k_pct": 30.0, "bb_pct": 12.0,
                },
            )
            for rank in range(1, 21)
        ]
        lines = [prospect_percentiles.identity_line(row, {}) for row in rows]
        sentence_counts = [line.count(".") for line in lines]
        for line in lines:
            self.assertGreaterEqual(len(line.split()), 20)
            self.assertLessEqual(len(line.split()), 80)
            self.assertGreaterEqual(line.count("."), 2)
            self.assertLessEqual(line.count("."), 4)
            self.assertNotIn("carrying skill", line)
            self.assertNotIn("sturdy foundation", line)
            self.assertNotIn("real risk", line)
            self.assertNotIn("there is still runway", line.lower())
            self.assertNotRegex(line.lower(), r"\bif\b")
            self.assertNotRegex(
                line,
                r"\b\d+(?:\.\d+)?%|\b(?:K/9|BB/9|K-BB%|ISO|ERA|WHIP)\b",
            )
        self.assertEqual(set(sentence_counts), {2, 3, 4})
        self.assertGreaterEqual(sum(count <= 3 for count in sentence_counts), len(lines) * 0.2)
        self.assertEqual(sentence_counts[0], 2)
        self.assertEqual(len({line.split(". ", 1)[0] for line in lines[:4]}), 4)

    def test_identity_line_is_stable_but_varies_by_player(self):
        rows = [
            _row(
                f"variety_{i}",
                stat_line={
                    "pa": 180, "ops": 0.920, "iso": 0.280,
                    "k_pct": 30.0, "bb_pct": 12.0,
                },
            )
            for i in range(12)
        ]
        lines = [prospect_percentiles.identity_line(row, {"iso": 95}) for row in rows]
        self.assertEqual(lines, [
            prospect_percentiles.identity_line(row, {"iso": 95}) for row in rows
        ])
        self.assertGreaterEqual(len(set(lines)), 3)


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
            "level": "MLB",
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
        {
            "id": "dd_prospect_arm",
            "player_type": "prospect",
            "name": "Pitcher Prospect",
            "positions": ["SP"],
            "mlb_team": "SEA",
            "age": 20,
            "dynasty_rank": 4,
            "dynasty_value": 58.0,
            "status": "minors",
            "level": "AA",
            "eta": 2028,
            "prospect_rank": 12,
            "source_ranks": {"milb_perf": 14},
            "breakout_label": "steady",
            "breakout_rank_change": 0,
            "stat_line": {
                "era": 2.45,
                "whip": 1.02,
                "k_per_9": 12.4,
                "bb_per_9": 2.4,
                "k_bb_pct": 26.0,
                "ip": 44.2,
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
        response = self.client.get("/player/dd_prospect_top?mode=prospects", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The ValuCast Read", response.data)
        self.assertIn(b"How His Skills Rank", response.data)
        read_pos = response.data.find(b"The ValuCast Read")
        trend_pos = response.data.find(b"Dynasty Value Trend")
        if trend_pos != -1:
            self.assertLess(read_pos, trend_pos)
        self.assertIn(b"100 = best in the ValuCast prospect pool", response.data)
        self.assertIn(b"Skill Shape", response.data)
        self.assertIn(b"not scouting grades", response.data)
        self.assertIn(b"identity-line", response.data)
        self.assertIn(b".300/.400/.550", response.data)
        self.assertIn(b"200 PA", response.data)
        self.assertIn(b"shape is more solid than explosive", response.data)
        self.assertIn(b"latest MiLB sample", response.data)
        self.assertNotIn(b"open question", response.data.lower())
        self.assertIn(b'class="prospect-profile-bar"', response.data)
        self.assertNotIn(b'class="pct-rail"', response.data)
        self.assertIn(b"vs ValuCast hitter pool", response.data)
        self.assertIn(b"all levels", response.data)
        self.assertIn(b"100+ PA", response.data)
        self.assertIn(
            b"percentile in the ValuCast prospect pool",
            response.data,
        )
        # The rich ValuCast card owns the stat display; the old stat tiles are fallback-only.
        self.assertNotIn(b"<h4>MiLB Stats", response.data)
        self.assertNotIn(b"<h5>Rate Stats</h5>", response.data)

    def test_small_sample_card_has_tag_without_percentiles(self):
        response = self.client.get("/player/dd_prospect_small?mode=prospects", headers={"HX-Request": "true"})
        self.assertIn(b"small sample", response.data)
        self.assertIn(b"<h4>MiLB Stats", response.data)
        self.assertNotIn(b'class="pct-rail"', response.data)

    def test_pitcher_prospect_card_uses_pitcher_pool_label(self):
        response = self.client.get("/player/dd_prospect_arm?mode=prospects", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"The ValuCast Read", response.data)
        self.assertIn(b"vs ValuCast pitcher pool", response.data)
        self.assertIn(b"20+ IP", response.data)
        self.assertNotIn(b"vs ValuCast hitter pool", response.data)

    def test_index_has_glass_toolbar_and_welcome_strip(self):
        response = self.client.get("/")
        self.assertIn(b'class="rank-toolbar rank-toolbar-redraft glass"', response.data)
        self.assertIn(b'class="welcome-strip glass"', response.data)


if __name__ == "__main__":
    unittest.main()
