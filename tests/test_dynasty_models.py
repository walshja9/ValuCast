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
    def test_from_feed_mlb(self):
        row = DynastyRankingRow.from_feed(SAMPLE_MLB)
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

    def test_from_feed_prospect(self):
        row = DynastyRankingRow.from_feed(SAMPLE_PROSPECT)
        self.assertEqual(row.id, "dd_prospect_sebastian_walcott")
        self.assertEqual(row.player_type, "prospect")
        self.assertEqual(row.prospect_rank, 3)
        self.assertEqual(row.level, "AA")
        self.assertEqual(row.eta, 2027)
        self.assertEqual(row.breakout_label, "steady")
        self.assertIsNotNone(row.stat_line)
        self.assertEqual(row.source_divergence, 55)
        self.assertEqual(row.public_source_ranks, {"pipeline": 6, "cfr": 9.0, "hkb": 7})
        self.assertEqual(row.public_source_consensus, 7)
        self.assertIsNone(row.milb_performance_rank)

    def test_from_feed_prospect_sample_context_properties(self):
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
        row = DynastyRankingRow.from_feed(record)

        self.assertTrue(row.availability_adjusted)
        self.assertEqual(row.availability_risk_discount, 0.04)
        self.assertEqual(row.availability_status_label, "Thin Current Sample")
        self.assertEqual(row.availability_sample_label, "72 PA")
        self.assertEqual(row.availability_note, "Limited current sample.")
        self.assertTrue(row.bucket_calibration_adjusted)
        self.assertEqual(
            row.bucket_calibration_label,
            "Lower Minors Pedigree Score Source (-1.0)",
        )

    def test_is_prospect(self):
        mlb_row = DynastyRankingRow.from_feed(SAMPLE_MLB)
        prospect_row = DynastyRankingRow.from_feed(SAMPLE_PROSPECT)
        self.assertFalse(mlb_row.is_prospect)
        self.assertTrue(prospect_row.is_prospect)

    def test_positions_as_tuple(self):
        row = DynastyRankingRow.from_feed(SAMPLE_MLB)
        self.assertIsInstance(row.positions, tuple)

    def test_missing_optional_fields(self):
        minimal = {"id": "dd_mlb_1", "player_type": "mlb", "name": "Test",
                   "dynasty_rank": 1, "dynasty_value": 50.0}
        row = DynastyRankingRow.from_feed(minimal)
        self.assertIsNone(row.mlbam_id)
        self.assertIsNone(row.age)
        self.assertEqual(row.positions, ("DH",))
