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

    def test_from_feed_prospect(self):
        row = DynastyRankingRow.from_feed(SAMPLE_PROSPECT)
        self.assertEqual(row.id, "dd_prospect_sebastian_walcott")
        self.assertEqual(row.player_type, "prospect")
        self.assertEqual(row.prospect_rank, 3)
        self.assertEqual(row.level, "AA")
        self.assertEqual(row.eta, 2027)
        self.assertEqual(row.breakout_label, "steady")
        self.assertIsNotNone(row.stat_line)

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
        self.assertEqual(row.positions, ())
