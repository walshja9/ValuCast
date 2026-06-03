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


from projections.models.expected_stats_grid import fit_grid, lookup


class TestGridFit(unittest.TestCase):
    def _balls(self):
        balls = []
        for _ in range(80):
            balls.append({"ev": 100.0, "la": 12.0, "events": "home_run"})
        for _ in range(20):
            balls.append({"ev": 100.0, "la": 12.0, "events": "field_out"})
        for _ in range(90):
            balls.append({"ev": 66.0, "la": -30.0, "events": "field_out"})
        for _ in range(10):
            balls.append({"ev": 66.0, "la": -30.0, "events": "single"})
        return balls

    def test_dense_cells_reflect_outcomes(self):
        grid = fit_grid(self._balls())
        hot = lookup(grid, 100.0, 12.0)
        cold = lookup(grid, 66.0, -30.0)
        self.assertAlmostEqual(hot["p_hit"], 0.80, places=2)      # 80/100
        self.assertAlmostEqual(hot["e_bases"], 3.20, places=2)    # 80*4 /100
        self.assertAlmostEqual(cold["p_hit"], 0.10, places=2)     # 10/100
        self.assertLess(cold["p_hit"], hot["p_hit"])

    def test_sparse_cell_falls_back_to_global(self):
        grid = fit_grid(self._balls())
        out = lookup(grid, 120.0, 60.0)   # never observed -> global
        self.assertAlmostEqual(out["p_hit"], 90 / 200, places=3)

    def test_missing_ev_uses_global(self):
        grid = fit_grid(self._balls())
        out = lookup(grid, None, None)   # missing-EV ball -> global fallback
        self.assertAlmostEqual(out["p_hit"], 90 / 200, places=3)

    def test_store_grid_immutable(self):
        import tempfile
        from pathlib import Path
        from projections.models.expected_stats_grid import store_grid, load_grid
        grid = fit_grid(self._balls())
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "grid.json"
            store_grid(grid, p)
            store_grid(grid, p)                       # identical -> no-op
            self.assertEqual(load_grid(p)["global"], grid["global"])
            changed = fit_grid(self._balls() + [{"ev": 105.0, "la": 20.0, "events": "home_run"}])
            with self.assertRaises(ValueError):
                store_grid(changed, p)                # changed content -> raise
