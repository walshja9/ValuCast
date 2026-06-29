import unittest
from web.dynasty_models import DynastyRankingRow


SAMPLE_MLB = {
    "id": "dd_mlb_paul_skenes",
    "player_type": "mlb",
    "name": "Paul Skenes",
    "mlbam_id": None,
    "positions": ["SP"],
    "mlb_team": "PIT",
    "age": 23,
    "dynasty_rank": 1,
    "dynasty_value": 148.0,
    "status": "mlb",
    "tier": 1,
    "market_value": 142.0,
    "proj_ip": 180.0,
    "dna": "Front-line ace.",
    "z_scores": {"ERA": -2.0, "K": 2.4},
    "confidence": {"score": 90, "level": "high", "range": {"low": 135, "mid": 148, "high": 150}},
}

SAMPLE_PROSPECT = {
    "id": "dd_prospect_sebastian_walcott",
    "player_type": "prospect",
    "name": "Sebastian Walcott",
    "mlbam_id": None,
    "positions": ["SS", "3B"],
    "mlb_team": "TEX",
    "age": 19,
    "dynasty_rank": 58,
    "dynasty_value": 73.8,
    "status": "minors",
    "level": "AA",
    "eta": 2027,
    "prospect_rank": 3,
    "source_ranks": {"pipeline": 6, "cfr": 9.0, "hkb": 7},
    "source_divergence": 55,
    "breakout_label": "steady",
    "breakout_rank_change": -1,
    "stat_line": {"pa": 200, "hr": 10, "ops": 0.900},
}


class TestDynastyRankingRow(unittest.TestCase):
    def _row(self, record):
        return DynastyRankingRow(
            id=record["id"],
            name=record["name"],
            player_type=record["player_type"],
            positions=DynastyRankingRow._normalize_positions(record.get("positions") or []),
            team=DynastyRankingRow.TEAM_CODE_MAP.get(
                record.get("mlb_team", ""), record.get("mlb_team", "")
            ),
            age=DynastyRankingRow._coerce_int(record.get("age")),
            dynasty_rank=record["dynasty_rank"],
            dynasty_value=record["dynasty_value"],
            status=record.get("status"),
            mlbam_id=record.get("mlbam_id"),
            tier=record.get("tier"),
            market_value=record.get("market_value"),
            proj_ip=record.get("proj_ip"),
            dna=record.get("dna"),
            z_scores=record.get("z_scores"),
            confidence=record.get("confidence"),
            prospect_rank=record.get("prospect_rank"),
            level=record.get("level"),
            eta=DynastyRankingRow._coerce_int(record.get("eta")),
            source_ranks=record.get("source_ranks"),
            source_divergence=record.get("source_divergence"),
            stat_line=DynastyRankingRow._coerce_dict(record.get("stat_line")),
            value_history=DynastyRankingRow._coerce_value_history(
                record.get("value_history")
            ),
            mlb_stat_line=DynastyRankingRow._coerce_dict(record.get("mlb_stat_line")),
            stat_line_translated=DynastyRankingRow._coerce_dict(
                record.get("stat_line_translated")
            ),
            combined_season_stat_line=DynastyRankingRow._coerce_dict(
                record.get("combined_season_stat_line")
            ),
            metadata=record,
        )

    def test_mlb_row_fields(self):
        row = self._row(SAMPLE_MLB)
        self.assertEqual(row.id, "dd_mlb_paul_skenes")
        self.assertEqual(row.name, "Paul Skenes")
        self.assertEqual(row.player_type, "mlb")
        self.assertEqual(row.dynasty_rank, 1)
        self.assertEqual(row.dynasty_value, 148.0)
        self.assertIsNone(row.prospect_rank)
        self.assertIsNone(row.stat_line)
        self.assertEqual(row.market_value, 142.0)
        self.assertEqual(row.z_scores["K"], 2.4)
        self.assertEqual(row.confidence["range"]["low"], 135)

    def test_prospect_row_fields(self):
        row = self._row(SAMPLE_PROSPECT)
        self.assertEqual(row.id, "dd_prospect_sebastian_walcott")
        self.assertEqual(row.player_type, "prospect")
        self.assertEqual(row.prospect_rank, 3)
        self.assertEqual(row.level, "AA")
        self.assertEqual(row.eta, 2027)
        self.assertFalse(hasattr(row, "breakout_label"))
        self.assertIsNotNone(row.stat_line)
        self.assertEqual(row.source_divergence, 55)
        # cfr is excluded from the public consensus (deep stat-formula scale).
        self.assertEqual(row.public_source_ranks, {"pipeline": 6, "hkb": 7})
        self.assertEqual(row.public_source_consensus, 6)
        self.assertIsNone(row.milb_performance_rank)

    def test_prospect_sample_context_properties(self):
        record = dict(
            SAMPLE_PROSPECT,
            components={
                "availability_adjusted": True,
                "availability_risk_discount": 0.04,
                "availability": {
                    "status": "thin_current_sample",
                    "sample": 72,
                    "sample_unit": "PA",
                    "note": "Limited current sample.",
                },
                "bucket_calibration": {
                    "bucket": "lower_minors_pedigree_score_source",
                    "adjustment": -1.0,
                },
            },
        )
        row = self._row(record)

        self.assertTrue(row.availability_adjusted)
        self.assertEqual(row.availability_risk_discount, 0.04)
        self.assertEqual(row.availability_status_label, "Thin Current Sample")
        self.assertEqual(row.availability_sample_label, "72 PA")
        self.assertEqual(row.availability_note, "Limited current sample.")
        self.assertTrue(row.bucket_calibration_adjusted)
        self.assertEqual(row.bucket_calibration_label, "Lower-minors context")

    def test_is_prospect(self):
        mlb_row = self._row(SAMPLE_MLB)
        prospect_row = self._row(SAMPLE_PROSPECT)
        self.assertFalse(mlb_row.is_prospect)
        self.assertTrue(prospect_row.is_prospect)

    def test_positions_as_tuple(self):
        row = self._row(SAMPLE_MLB)
        self.assertIsInstance(row.positions, tuple)

    def test_missing_optional_fields(self):
        minimal = {"id": "dd_mlb_1", "player_type": "mlb", "name": "Test",
                   "dynasty_rank": 1, "dynasty_value": 50.0}
        row = self._row(minimal)
        self.assertIsNone(row.mlbam_id)
        self.assertIsNone(row.age)
        self.assertEqual(row.positions, ("DH",))
