"""Feature-liveness guard.

Catches the silent dead-feature class that left HR/600, SB/600 (hitter) and
hr_per_9/h_per_9/walks_per_9/start_rate (pitcher) wired to the wrong record keys
and zeroed across every training row for the model's life. Every feature the
model DECLARES in its rich vector must actually VARY across the real training
rows; a constant column means it's reading a key that isn't there (or is
otherwise degenerate). This fails CI instead of going unnoticed for months.
"""
import unittest

from prospects import model as m

# Indicators that CAN be legitimately constant in a given training sample and are
# therefore not evidence of a wiring bug. Keep this list tight + justified.
#   bats_switch         - switch-hitting pitchers are rare/absent in the cohorts
#   draft_record_known  - every cohort player has a known draft record (all True);
#                         zero-signal but correct, not a key mismatch
_MAY_BE_CONSTANT = {"bats_switch", "draft_record_known"}


class TestFeatureLiveness(unittest.TestCase):
    def test_no_constant_features_in_training_vectors(self):
        try:
            contract = m.load_input_contract()
        except FileNotFoundError:
            self.skipTest("prospect input contract not present")
        rows = contract["historical"].get("rows", [])
        self.assertTrue(rows, "no historical rows in contract")
        for role in ("hitter", "pitcher"):
            hist = m._historical_rows(rows, role)
            self.assertGreater(len(hist), 50, f"too few {role} rows to judge liveness")
            names = m.OUTCOME_FEATURE_NAMES[role]
            columns = list(zip(*(row["features"] for row in hist)))
            self.assertEqual(len(columns), len(names))
            dead = [
                name
                for name, col in zip(names, columns)
                if name not in _MAY_BE_CONSTANT and len({round(v, 9) for v in col}) <= 1
            ]
            self.assertEqual(
                dead,
                [],
                f"{role}: declared feature(s) constant across all {len(hist)} training "
                f"rows -- likely a wrong record key / dead feature: {dead}",
            )


if __name__ == "__main__":
    unittest.main()
