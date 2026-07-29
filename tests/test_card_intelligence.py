import json
import tempfile
import unittest
from pathlib import Path

import app as app_module
from web import prospect_percentiles
from web.dynasty_models import DynastyRankingRow


def _row_from_record(record):
    team = DynastyRankingRow.TEAM_CODE_MAP.get(
        record.get("mlb_team", ""), record.get("mlb_team", "")
    )
    return DynastyRankingRow(
        id=record["id"],
        name=record["name"],
        player_type=record["player_type"],
        positions=DynastyRankingRow._normalize_positions(record.get("positions") or []),
        team=team,
        age=DynastyRankingRow._coerce_int(record.get("age")),
        dynasty_rank=record["dynasty_rank"],
        dynasty_value=record["dynasty_value"],
        status=record.get("status"),
        mlbam_id=record.get("mlbam_id"),
        prospect_rank=record.get("prospect_rank"),
        level=record.get("level"),
        eta=DynastyRankingRow._coerce_int(record.get("eta")),
        source_ranks=record.get("source_ranks"),
        source_divergence=record.get("source_divergence"),
        stat_line=DynastyRankingRow._coerce_dict(record.get("stat_line")),
        value_history=DynastyRankingRow._coerce_value_history(record.get("value_history")),
        mlb_stat_line=DynastyRankingRow._coerce_dict(record.get("mlb_stat_line")),
        stat_line_translated=DynastyRankingRow._coerce_dict(
            record.get("stat_line_translated")
        ),
        combined_season_stat_line=DynastyRankingRow._coerce_dict(
            record.get("combined_season_stat_line")
        ),
        metadata=record,
    )


class _Store:
    def __init__(self, rows, generated_at="2026-06-12T12:00:00+00:00"):
        self._rows = sorted(rows, key=lambda row: row.dynasty_rank)
        self._by_id = {row.id: row for row in self._rows}
        self.generated_at = generated_at
        self.schema_version = "1.1"
        self.is_available = True

    def get_all(self):
        return list(self._rows)

    def get_by_id(self, row_id):
        return self._by_id.get(row_id)

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
            rows = [row for row in rows if search.lower() in row.name.lower()]
        return rows


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
    combined_season_stat_line=None,
    level=None,
    context=None,
    components=None,
    dynasty_value=70.0,
    peak_projection=None,
):
    if combined_season_stat_line is None and player_type == "prospect" and isinstance(stat_line, dict):
        is_pitcher = positions and set(positions) <= {"P", "SP", "RP"}
        sample_key = "ip" if is_pitcher else "pa"
        sample_unit = "IP" if is_pitcher else "PA"
        if isinstance(stat_line.get(sample_key), (int, float)):
            combined_season_stat_line = {
                **stat_line,
                "role": "pitcher" if is_pitcher else "hitter",
                "season": 2026,
                "level": level or "AA",
                "levels": [level or "AA"],
                "level_label": level or "AA",
                "sample": stat_line[sample_key],
                "sample_unit": sample_unit,
            }
    return _row_from_record({
        "id": row_id,
        "player_type": player_type,
        "name": name or row_id.replace("_", " ").title(),
        "positions": positions or ["SS"],
        "mlb_team": "TEX",
        "age": age,
        "dynasty_rank": prospect_rank or 1,
        "dynasty_value": dynasty_value,
        "status": "minors" if player_type == "prospect" else "mlb",
        "prospect_rank": prospect_rank,
        "source_ranks": source_ranks,
        "breakout_label": "rising" if change > 0 else "falling" if change < 0 else "steady",
        "breakout_rank_change": change,
        "stat_line": stat_line,
        "stat_line_translated": stat_line_translated,
        "combined_season_stat_line": combined_season_stat_line,
        "level": level,
        "context": context,
        "components": components,
        "peak_projection": peak_projection,
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

    def test_native_prospect_movers_strip_is_dd_free(self):
        import json
        import os
        import tempfile
        from pathlib import Path
        import app as app_module

        data = {
            "rising": [
                {"player_id": "vc_prospect_1_hitter", "name": "Riser A", "score_delta": 7.7},
                {"player_id": "vc_prospect_2_hitter", "name": "Riser B", "score_delta": 3.1},
            ],
            "cooling": [
                {"player_id": "vc_prospect_3_hitter", "name": "Faller C", "score_delta": -9.4},
            ],
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(data, fh)
            path = Path(fh.name)
        try:
            strip = app_module._native_prospect_movers_strip(limit=2, path=path)
        finally:
            os.unlink(path)
        # sorted by |score move| desc, capped at the limit
        self.assertEqual([m["name"] for m in strip], ["Faller C", "Riser A"])
        self.assertEqual([m["change"] for m in strip], [-9, 8])
        self.assertEqual(strip[0]["id"], "vc_prospect_3_hitter")

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
            self.assertNotIn("likely outcome", line.lower())
            self.assertNotIn("profiles as", line.lower())
            self.assertTrue(
                any(
                    outcome in line.lower()
                    for outcome in ("role", "regular", "starter", "bullpen", "bench", "floor")
                )
            )
            self.assertIn("confidence", line.lower())
        self.assertIsNone(prospect_percentiles.identity_line(mlb, {}))

    def test_contact_light_power_read_describes_shape_not_ceiling(self):
        salas = _row(
            "salas_shape",
            prospect_rank=65,
            age=20,
            level="AA",
            stat_line={
                "pa": 285,
                "ops": 0.771,
                "iso": 0.137,
                "k_pct": 15.1,
                "bb_pct": 10.2,
            },
        )

        read = prospect_percentiles.identity_line(salas, {})

        self.assertIn("contact-first table-setter shape", read.lower())
        self.assertNotIn("ceiling", read.lower())
        self.assertNotIn("floor", read.lower())

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

    def test_card_read_callout_value_matches_the_percentile_line(self):
        # Value/percentile parity: a thin 9-PA current line (.080 ISO) sits under a
        # combined 274-PA line (.424 ISO). The percentiles rank the COMBINED line, so
        # the callout VALUE must also come from the combined line — never pair the thin
        # .080 value with the combined line's 95th percentile.
        pool_rows = [
            _row(
                f"pool_{i}",
                prospect_rank=i,
                stat_line={
                    "pa": 200, "avg": 0.260, "obp": 0.330, "slg": 0.430,
                    "ops": 0.700 + 0.02 * i, "iso": 0.120 + 0.01 * i,
                    "k_pct": 20.0, "bb_pct": 9.0,
                },
                level="AA",
            )
            for i in range(1, 10)
        ]
        row = _row(
            "gillen",
            name="Theo Gillen",
            prospect_rank=40,
            positions=["OF"],
            level="A+",
            stat_line={
                "pa": 9, "avg": 0.222, "obp": 0.300, "slg": 0.444, "ops": 0.444,
                "iso": 0.080, "k_pct": 22.0, "bb_pct": 10.0,
            },
            combined_season_stat_line={
                "role": "hitter", "season": 2026, "level": "A+",
                "levels": ["A+", "A"], "level_label": "A+ & A",
                "sample": 274, "sample_unit": "PA", "pa": 274,
                "avg": 0.318, "obp": 0.430, "slg": 0.588, "ops": 1.018,
                "iso": 0.424, "k_pct": 12.0, "bb_pct": 14.0,
            },
            context={
                "stat_line_source_kind": "current_season",
                "stat_line_sample": 9, "stat_line_sample_unit": "PA",
                "stat_line_sample_season": 2026, "stat_line_level": "A+",
            },
        )
        pool = prospect_percentiles.build_pool(pool_rows + [row])
        pcts = prospect_percentiles.card_percentiles(pool, row)
        self.assertGreaterEqual(pcts["iso"], 90)

        read = app_module._prospect_player_card_read(row, pcts, row.metadata["context"])

        # The callout value is the combined .424 ISO that earned the 95th percentile,
        # and the displayed sample is the combined line's 274 PA — not the thin 9 PA.
        self.assertIn(".424 ISO", read)
        self.assertNotIn(".080", read)
        self.assertIn("274 PA", read)
        self.assertNotIn("9 PA", read)

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

    def test_value_suppressor_note_fires_on_elite_skill_low_value_gap(self):
        row = _row(
            "low_value_gap",
            positions=["SP"],
            level="A+",
            age=22,
            prospect_rank=300,
            dynasty_value=0.5,
            stat_line={
                "ip": 45,
                "era": 2.20,
                "whip": 0.92,
                "k_per_9": 12.8,
                "bb_per_9": 1.7,
                "k_bb_pct": 29.0,
            },
            components={
                "factual_current_context": {
                    "role": "pitcher",
                    "sample": 45,
                    "sample_unit": "IP",
                    "skill_band": "bat_missing",
                },
            },
            peak_projection={"peak_role": "depth_arm", "risk_band": "medium"},
        )

        line = prospect_percentiles.identity_line(
            row,
            {"k_bb_pct": 99, "bb_per_9": 95, "whip": 92},
        )

        self.assertIn("dynasty value stays low because", line)
        self.assertIn("old for High-A", line)
        self.assertIn("depth/relief arm", line)

    def test_value_suppressor_note_absent_for_high_value_player(self):
        row = _row(
            "high_value",
            positions=["SS"],
            level="AA",
            age=21,
            prospect_rank=12,
            dynasty_value=70.0,
            stat_line={
                "pa": 220,
                "avg": 0.310,
                "obp": 0.390,
                "slg": 0.530,
                "ops": 0.920,
                "iso": 0.220,
                "k_pct": 16.0,
                "bb_pct": 11.0,
            },
            peak_projection={"peak_role": "everyday_regular", "risk_band": "medium"},
        )

        self.assertIsNone(
            prospect_percentiles.value_suppressor_note(row, {"ops": 95, "iso": 80})
        )
        self.assertNotIn(
            "stays low because",
            prospect_percentiles.identity_line(row, {"ops": 95, "iso": 80}),
        )

    def test_value_suppressor_note_absent_when_skills_are_not_elite(self):
        row = _row(
            "not_elite_low_value",
            positions=["SS"],
            level="AA",
            age=23,
            prospect_rank=300,
            dynasty_value=2.0,
            stat_line={
                "pa": 220,
                "avg": 0.250,
                "obp": 0.320,
                "slg": 0.390,
                "ops": 0.710,
                "iso": 0.140,
                "k_pct": 24.0,
                "bb_pct": 8.0,
            },
            peak_projection={"peak_role": "bench_or_platoon_bat", "risk_band": "high"},
        )

        self.assertIsNone(prospect_percentiles.value_suppressor_note(row, {"ops": 55}))

    def test_value_suppressor_note_does_not_treat_uncalibrated_bust_risk_as_role(self):
        row = _row(
            "uncalibrated_bust_probability",
            positions=["SS"],
            level="AA",
            age=23,
            prospect_rank=300,
            dynasty_value=2.0,
            stat_line={
                "pa": 220,
                "avg": 0.310,
                "obp": 0.410,
                "slg": 0.530,
                "ops": 0.940,
                "iso": 0.220,
                "k_pct": 16.0,
                "bb_pct": 15.0,
            },
            peak_projection={
                "peak_role": "everyday_regular",
                "risk_band": "high",
                "peak_v2": {"role_probabilities": {"bust_risk": 0.80}},
            },
        )

        note = prospect_percentiles.value_suppressor_note(
            row,
            {"ops": 95, "obp": 95},
        )

        self.assertIsNotNone(note)
        self.assertNotIn("projection caps at a bench/depth role", note)

    def test_value_suppressor_note_uses_qualitative_bench_role_without_probability(self):
        row = _row(
            "qualitative_bench_role",
            positions=["SS"],
            level="AA",
            age=23,
            prospect_rank=300,
            dynasty_value=2.0,
            stat_line={
                "pa": 220,
                "avg": 0.310,
                "obp": 0.410,
                "slg": 0.530,
                "ops": 0.940,
                "iso": 0.220,
                "k_pct": 16.0,
                "bb_pct": 15.0,
            },
            peak_projection={
                "peak_role": "bench_or_platoon_bat",
                "risk_band": "medium",
            },
        )

        note = prospect_percentiles.value_suppressor_note(
            row,
            {"ops": 95, "obp": 95},
        )

        self.assertIsNotNone(note)
        self.assertIn("projection caps at a bench/depth role", note)

    def test_value_suppressor_reason_priority(self):
        row = _row(
            "priority_gap",
            positions=["SP"],
            level="AA",
            age=23,
            prospect_rank=280,
            dynasty_value=3.0,
            stat_line={
                "ip": 35,
                "era": 2.60,
                "whip": 0.98,
                "k_per_9": 13.4,
                "bb_per_9": 2.0,
                "k_bb_pct": 28.0,
            },
            components={
                "factual_current_context": {
                    "role": "pitcher",
                    "sample": 35,
                    "sample_unit": "IP",
                    "skill_band": "thin",
                },
            },
            peak_projection={"peak_role": "depth_arm", "risk_band": "medium"},
        )

        note = prospect_percentiles.value_suppressor_note(
            row,
            {"k_bb_pct": 99, "bb_per_9": 88, "whip": 82},
        )

        self.assertIn(
            "because he's old for Double-A (23) and the sample is still thin (35 IP).",
            note,
        )
        self.assertNotIn("depth/relief arm", note)

    def _old_for_level_hitter(self):
        return _row(
            "injury_repeat",
            positions=["CF"],
            level="AA",
            age=23,
            prospect_rank=280,
            dynasty_value=3.0,
            stat_line={"pa": 314, "ops": 1.056, "iso": 0.244, "bb_pct": 21.3},
            components={
                "factual_current_context": {
                    "role": "hitter",
                    "sample": 159,
                    "sample_unit": "PA",
                    "skill_band": "thin",
                },
            },
            peak_projection={"peak_role": "bench_or_platoon_bat", "risk_band": "high"},
        )

    def test_value_suppressor_note_adds_lost_development_time_for_short_season(self):
        row = self._old_for_level_hitter()
        exposure = {
            "draft_year": 2024,
            "seasons": [
                {"season": 2025, "games": 59, "unit": "PA", "sample": 270.0},
                {"season": 2026, "games": 68, "unit": "PA", "sample": 314.0},
            ],
        }
        note = prospect_percentiles.value_suppressor_note(
            row, {"ops": 99, "iso": 91, "bb_pct": 98}, exposure=exposure
        )
        self.assertIn("he's old for Double-A (23)", note)
        self.assertIn("his 2025 season ran just 59 games", note)
        self.assertIn("lost development time", note)

    def test_value_suppressor_note_no_mitigation_for_full_prior_season(self):
        row = self._old_for_level_hitter()
        exposure = {
            "draft_year": 2021,
            "seasons": [
                {"season": 2024, "games": 124, "unit": "PA", "sample": 520.0},
                {"season": 2025, "games": 130, "unit": "PA", "sample": 545.0},
                {"season": 2026, "games": 68, "unit": "PA", "sample": 314.0},
            ],
        }
        note = prospect_percentiles.value_suppressor_note(
            row, {"ops": 99, "iso": 91, "bb_pct": 98}, exposure=exposure
        )
        self.assertIn("he's old for Double-A (23)", note)
        self.assertNotIn("lost development time", note)

    def test_sample_context_labels_all_levels_for_combined_line(self):
        # A combined AAA+AA line's 235 PA must not read as "235 PA in Triple-A"
        # (only part of that sample was at Triple-A).
        row = _row(
            "mendez",
            positions=["LF"],
            level="AAA",
            age=22,
            prospect_rank=32,
            dynasty_value=44.8,
            stat_line={"pa": 235, "ops": 0.896, "avg": 0.314, "k_pct": 16.1},
            combined_season_stat_line={
                "pa": 235, "ops": 0.896, "avg": 0.314, "k_pct": 16.1,
                "role": "hitter", "season": 2026,
                "level": "AAA", "level_label": "AAA+AA", "levels": ["AAA", "AA"],
                "sample": 235, "sample_unit": "PA",
            },
            stat_line_translated={
                "level": "AAA", "level_label": "AAA+AA", "levels": ["AAA", "AA"],
                "sample": 235, "sample_unit": "PA", "confidence": "high", "season": 2026,
            },
        )
        read = prospect_percentiles.identity_line(row, {"ops": 89, "avg": 96, "k_pct": 90})
        self.assertIn("Triple-A and Double-A", read)
        self.assertNotIn("235 PA in Triple-A,", read)


class TestValueCardReads(unittest.TestCase):
    def test_dynasty_card_uses_clean_role_articles_and_status_prose(self):
        row = _row(
            "witt",
            name="Bobby Witt Jr.",
            player_type="mlb",
            positions=["SS"],
            prospect_rank=2,
            dynasty_value=90.0,
        )

        read = app_module._dynasty_card_read(
            row,
            {
                "role_profile": {
                    "projected_role": "everyday_regular",
                    "projected_role_label": "Everyday Regular",
                    "availability_status": "active_mlb_roster",
                    "availability_status_label": "Active Mlb Roster",
                }
            },
        )

        self.assertEqual(
            read,
            (
                "Bobby Witt Jr.: #2 on the dynasty board at 90.0. "
                "An SS projected for an everyday role. "
                "He is on an active MLB roster."
            ),
        )

    def test_dynasty_card_does_not_emit_stranded_position_sentence(self):
        row = _row(
            "skenes",
            name="Paul Skenes",
            player_type="mlb",
            positions=["SP"],
            prospect_rank=4,
            dynasty_value=90.0,
        )

        read = app_module._dynasty_card_read(row, {"role_profile": {}})

        self.assertEqual(
            read,
            "Paul Skenes: SP, #4 on the dynasty board at 90.0.",
        )
        self.assertNotIn("A SP.", read)

    def test_dynasty_card_read_uses_projection_line_when_context_is_empty(self):
        row = _row(
            "keys",
            name="Sean Keys",
            player_type="mlb",
            positions=["1B"],
            prospect_rank=830,
            dynasty_value=21.7,
            stat_line={"avg": 0.285, "obp": 0.411, "ops": 0.992, "pa": 209},
        )

        read = app_module._dynasty_card_read(row, {"role_profile": {}})

        self.assertIn("Sean Keys: 1B, #830 on the dynasty board at 21.7.", read)
        self.assertIn("the read leans on the projection", read)
        self.assertIn(".285 AVG", read)
        self.assertIn("209 PA", read)

    def test_dynasty_statcast_phrase_varies_without_label_fallbacks(self):
        phrase = app_module._statcast_profile_phrase(
            [
                {"key": "barrel", "label": "Barrel %", "percentile": 88},
                {"key": "whiff", "label": "Whiff %", "percentile": 32},
            ]
        )

        self.assertEqual(
            phrase,
            (
                "Statcast points first to elite Barrel % (88th pct), "
                "with whiff % at the 32nd pct the clearest drag."
            ),
        )


class TestPublicSourceRanks(unittest.TestCase):
    def test_cfr_and_internal_signals_excluded_from_public_boards(self):
        # cfr (deep stat-formula list) and cfr_raw/milb_perf (internal) are all
        # excluded; only the top-N scouting/market boards count in the consensus.
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
        self.assertEqual(row.public_source_ranks, {"pipeline": 10, "hkb": 30})
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
            "combined_season_stat_line": {
                "role": "hitter",
                "season": 2026,
                "level": "AA",
                "levels": ["AA"],
                "level_label": "AA",
                "sample": 200,
                "sample_unit": "PA",
                "pa": 200,
                "avg": 0.300,
                "obp": 0.400,
                "slg": 0.550,
                "ops": 0.950,
                "iso": 0.250,
                "babip": 0.330,
                "k_pct": 18.0,
                "bb_pct": 12.0,
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
            "combined_season_stat_line": {
                "role": "hitter",
                "season": 2026,
                "level": "A+",
                "levels": ["A+"],
                "level_label": "A+",
                "sample": 80,
                "sample_unit": "PA",
                "pa": 80,
                "avg": 0.250,
                "obp": 0.320,
                "slg": 0.400,
                "ops": 0.720,
                "iso": 0.150,
                "babip": 0.300,
                "k_pct": 28.0,
                "bb_pct": 8.0,
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
            "combined_season_stat_line": {
                "role": "pitcher",
                "season": 2026,
                "level": "AA",
                "levels": ["AA"],
                "level_label": "AA",
                "sample": 44.2,
                "sample_unit": "IP",
                "ip": 44.2,
                "era": 2.45,
                "whip": 1.02,
                "k_per_9": 12.4,
                "bb_per_9": 2.4,
                "k_bb_pct": 26.0,
            },
        },
    ],
}


class TestCardIntelligenceUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_store = app_module.dd_store
        cls.original_pool = app_module.prospect_pool
        app_module.dd_store = _Store(
            [_row_from_record(record) for record in FEED["players"]],
            generated_at=FEED["generated_at"],
        )
        app_module.prospect_pool = prospect_percentiles.build_pool(app_module.dd_store.get_all())
        app_module.app.config["TESTING"] = True
        cls.client = app_module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        app_module.dd_store = cls.original_store
        app_module.prospect_pool = cls.original_pool

    def test_prospects_board_eta_cutoff_and_movers(self):
        response = self.client.get("/?mode=prospects&teams=4&pslots=1")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="col-eta sortable"', response.data)
        self.assertIn(b">2027</td>", response.data)
        self.assertIn(b'colspan="9"', response.data)  # confidence + compare columns
        self.assertIn(b'class="movers-strip"', response.data)

        htmx = self.client.get("/rankings?mode=prospects&teams=4&pslots=1")
        self.assertIn(b'class="movers-strip"', htmx.data)

    def test_movers_hidden_when_search_is_active(self):
        response = self.client.get("/?mode=prospects&search=Top")
        self.assertNotIn(b'class="movers-strip"', response.data)

    def test_prospect_card_has_identity_percentiles_and_pool_label(self):
        response = self.client.get("/player/dd_prospect_top?mode=prospects", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<span class="profile-card-kicker">Skill</span>', response.data)
        self.assertIn(b"<h4>What his performance supports</h4>", response.data)
        skill_pos = response.data.find(b'<span class="profile-card-kicker">Skill</span>')
        trend_pos = response.data.find(b"ValuCast Value Trend")
        if trend_pos != -1:
            self.assertLess(skill_pos, trend_pos)
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
        self.assertIn(b"hitter pool", response.data)
        self.assertIn(b"100+ PA", response.data)
        self.assertIn(b"combined 2026 line", response.data)
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
        self.assertIn(b"MiLB Stats", response.data)
        self.assertNotIn(b'class="pct-rail"', response.data)

    def test_pitcher_prospect_card_uses_pitcher_pool_label(self):
        response = self.client.get("/player/dd_prospect_arm?mode=prospects", headers={"HX-Request": "true"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<span class="profile-card-kicker">Skill</span>', response.data)
        self.assertIn(b"<h4>What his performance supports</h4>", response.data)
        self.assertIn(b"pitcher pool", response.data)
        self.assertIn(b"20+ IP", response.data)
        self.assertNotIn(b"hitter pool", response.data)

    def test_index_has_glass_toolbar_and_welcome_strip(self):
        response = self.client.get("/")
        self.assertIn(b'class="rank-toolbar rank-toolbar-redraft glass"', response.data)
        self.assertIn(b'class="welcome-strip glass"', response.data)


if __name__ == "__main__":
    unittest.main()
