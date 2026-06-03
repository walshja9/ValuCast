import unittest
from projections.models.expected_stats_grid import cell_key, outcome_bases, EV_BIN, LA_BIN


class TestGridKeysAndOutcomes(unittest.TestCase):
    def test_cell_key_bins(self):
        # EV 2mph bins, LA 5deg bins -> floor to bin edge.
        self.assertEqual(cell_key(98.7, 12.0), (98, 10))   # 98.7->98 (2mph), 12->10 (5deg)
        self.assertEqual(cell_key(81.0, -41.0), (80, -45))

    def test_outcome_bases_and_hit(self):
        self.assertEqual(outcome_bases("single"), (1, 1))
        self.assertEqual(outcome_bases("double"), (1, 2))
        self.assertEqual(outcome_bases("triple"), (1, 3))
        self.assertEqual(outcome_bases("home_run"), (1, 4))
        self.assertEqual(outcome_bases("field_out"), (0, 0))
        self.assertEqual(outcome_bases("field_error"), (0, 0))   # reached on error: not a hit
        self.assertEqual(outcome_bases("sac_fly"), (0, 0))
