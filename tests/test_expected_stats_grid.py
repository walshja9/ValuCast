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


from projections.models.expected_stats_grid import score_player


class TestScorePlayer(unittest.TestCase):
    def test_our_xba_xslg_full_ab_denominator(self):
        grid = {"cells": {(100, 10): {"n": 100, "hits": 80, "bases": 320}},
                "global": {"p_hit": 0.5, "e_bases": 1.0}, "ev_bin": 2, "la_bin": 5}
        balls = [
            {"ev": 100.0, "la": 12.0, "events": "home_run"},  # hot cell -> .8 / 3.2
            {"ev": 100.0, "la": 12.0, "events": "field_out"}, # hot cell -> .8 / 3.2
            {"ev": None, "la": None, "events": "field_out"},  # missing-EV -> global .5 / 1.0
        ]
        res = score_player(grid, balls, ab=4)
        # expected hits = .8 + .8 + .5 = 2.1 ; xBA = 2.1/4
        self.assertAlmostEqual(res["our_xba"], 2.1 / 4, places=4)
        # expected bases = 3.2 + 3.2 + 1.0 = 7.4 ; xSLG = 7.4/4
        self.assertAlmostEqual(res["our_xslg"], 7.4 / 4, places=4)
        self.assertEqual(res["tracked_bip"], 3)
        self.assertAlmostEqual(res["missing_ev_coverage"], 1/3, places=4)

    def test_zero_ab_safe(self):
        grid = {"cells": {}, "global": {"p_hit": 0.5, "e_bases": 1.0}, "ev_bin": 2, "la_bin": 5}
        res = score_player(grid, [], ab=0)
        self.assertEqual(res["our_xba"], 0.0)
        self.assertEqual(res["our_xslg"], 0.0)
