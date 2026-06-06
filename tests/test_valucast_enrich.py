import unittest
from projections.export.valucast_enrich import build_eligibility, enrich_rows


STEAMER = [
    {"name": "Real Hitter", "pool": "hitter", "positions": ["SS", "2B"], "team": "NYY",
     "metadata": {"mlbam_id": "100"}},
    {"name": "Real Pitcher", "pool": "starter", "positions": ["SP"], "team": "LAD",
     "metadata": {"mlbam_id": "200"}},
    # 300 is a PITCHER in current.json (so his hitter-history ghost must be dropped).
    {"name": "Pitcher Who Batted", "pool": "reliever", "positions": ["RP"], "team": "BOS",
     "metadata": {"mlbam_id": "300"}},
]


class TestEligibilityEnrich(unittest.TestCase):
    def setUp(self):
        self.elig = build_eligibility(STEAMER)

    def test_eligibility_split_by_pool(self):
        self.assertIn("100", self.elig["hitters"])
        self.assertIn("200", self.elig["pitchers"])
        self.assertIn("300", self.elig["pitchers"])
        self.assertNotIn("300", self.elig["hitters"])   # not a position player

    def test_enrich_sets_name_team_positions(self):
        rows = [{"id": "mlbam_100_H", "name": "100", "pool": "hitter", "positions": [],
                 "stats": {"HR": 25}, "metadata": {"mlbam_id": "100"}}]
        out = enrich_rows(rows, self.elig["hitters"])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "Real Hitter")
        self.assertEqual(out[0]["positions"], ["SS", "2B"])
        self.assertEqual(out[0]["metadata"]["team"], "NYY")
        self.assertEqual(out[0]["stats"]["HR"], 25)   # stats untouched

    def test_drops_ghost_pitcher_hitter_row(self):
        # 300 has a hitter-history projection row but is a PITCHER in current.json.
        rows = [
            {"id": "mlbam_100_H", "pool": "hitter", "metadata": {"mlbam_id": "100"}},
            {"id": "mlbam_300_H", "pool": "hitter", "metadata": {"mlbam_id": "300"}},  # ghost
        ]
        out = enrich_rows(rows, self.elig["hitters"])
        ids = {r["id"] for r in out}
        self.assertIn("mlbam_100_H", ids)
        self.assertNotIn("mlbam_300_H", ids)   # ghost dropped

    def test_drops_retired_not_in_universe(self):
        rows = [{"id": "mlbam_999_H", "pool": "hitter", "metadata": {"mlbam_id": "999"}}]
        self.assertEqual(enrich_rows(rows, self.elig["hitters"]), [])
