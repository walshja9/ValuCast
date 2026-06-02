import json
import tempfile
import unittest
from pathlib import Path

from projections.data.historical import store_season
from projections.export.marcel_run import build_marcel_projections, write_run
from projections.models.marcel_params import MarcelParams


class TestMarcelRun(unittest.TestCase):
    def _seed(self, data_dir):
        for yr in (2021, 2022, 2023):
            store_season(yr, [{
                "mlbam_id": "5", "season": yr, "PA": 500, "AB": 450, "H": 125,
                "1B": 100, "2B": 0, "3B": 0, "HR": 25, "R": 80, "RBI": 70,
                "SB": 0, "CS": 0, "BB": 50, "SO": 100, "HBP": 0, "SF": 0,
            }], data_dir)

    def test_build_emits_engine_shaped_rows(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed(data_dir)
            rows = build_marcel_projections(
                2024, data_dir, MarcelParams(),
                identities={"5": {"name": "Test Bat", "birth_date": "1995-06-01"}},
            )
            self.assertEqual(len(rows), 1)
            r = rows[0]
            self.assertEqual(r["id"], "mlbam_5_H")
            self.assertEqual(r["name"], "Test Bat")        # identity wired through
            self.assertEqual(r["pool"], "hitter")
            self.assertEqual(r["metadata"]["source"], "marcel")
            self.assertEqual(r["metadata"]["model"], "valucast_marcel")
            self.assertEqual(r["metadata"]["as_of_season"], 2024)
            self.assertFalse(r["metadata"]["age_unknown"])
            self.assertIn("HR", r["stats"])
            self.assertIn("OPS", r["stats"])

    def test_write_run_is_self_describing(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            runs_dir = data_dir / "runs"
            self._seed(data_dir)
            rows = build_marcel_projections(
                2024, data_dir, MarcelParams(),
                identities={"5": {"name": "Test Bat", "birth_date": "1995-06-01"}},
            )
            run_id = write_run(rows, runs_dir, model="marcel", as_of_season=2024, version=1)
            self.assertEqual(run_id, "marcel_2024_v1")
            run_path = runs_dir / run_id
            self.assertTrue((run_path / "projections.json").exists())
            manifest = json.loads((run_path / "run_manifest.json").read_text())
            self.assertEqual(manifest["as_of_season"], 2024)
            self.assertEqual(manifest["row_count"], 1)

    def test_write_run_is_immutable(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            runs_dir = data_dir / "runs"
            self._seed(data_dir)
            rows = build_marcel_projections(
                2024, data_dir, MarcelParams(),
                identities={"5": {"name": "Test Bat", "birth_date": "1995-06-01"}},
            )
            run_id = write_run(rows, runs_dir, model="marcel", as_of_season=2024, version=1)
            # Identical re-write of the same run_id is a no-op.
            self.assertEqual(
                write_run(rows, runs_dir, model="marcel", as_of_season=2024, version=1),
                run_id,
            )
            # Different contents under the same run_id must raise (bump version instead).
            changed = [dict(rows[0], name="Changed")]
            with self.assertRaises(ValueError):
                write_run(changed, runs_dir, model="marcel", as_of_season=2024, version=1)

    def _seed_many(self, data_dir):
        # 5 consecutive seasons, two players with differing HR trajectories so
        # reliability is computable.
        traj = {"5": [25, 27, 24, 26, 25], "7": [10, 18, 12, 20, 9]}
        for i, yr in enumerate((2019, 2020, 2021, 2022, 2023)):
            rows = []
            for pid, hrs in traj.items():
                rows.append({"mlbam_id": pid, "season": yr, "PA": 500, "AB": 450,
                             "H": 125, "1B": 100 - hrs[i] + 25, "2B": 0, "3B": 0,
                             "HR": hrs[i], "R": 80, "RBI": 70, "SB": 0, "CS": 0,
                             "BB": 50, "SO": 100, "HBP": 0, "SF": 0})
            store_season(yr, rows, data_dir)

    def test_gamma_positive_changes_projection_vs_classic(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"},
                      "7": {"birth_date": "1994-01-01"}}
            classic = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            tuned = build_marcel_projections(2024, data_dir, MarcelParams(gamma=1.0), idents)
            c = {r["id"]: r["stats"]["HR"] for r in classic}
            t = {r["id"]: r["stats"]["HR"] for r in tuned}
            # At least one player's HR projection moves once reliability differentiates.
            self.assertTrue(any(abs(c[k] - t[k]) > 1e-9 for k in c))

    def test_gamma_zero_matches_prior_behavior(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"}, "7": {"birth_date": "1994-01-01"}}
            a = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            b = build_marcel_projections(2024, data_dir, MarcelParams(gamma=0.0), idents)
            self.assertEqual([r["stats"] for r in a], [r["stats"] for r in b])

    def _seed_statcast(self, data_dir):
        from projections.data.statcast import store_statcast_season
        # High xslg for player 7 so de-noising visibly moves their line.
        for yr in (2019, 2020, 2021, 2022, 2023):
            store_statcast_season(yr, [
                {"mlbam_id": "5", "xba": 0.270, "xslg": 0.470, "xwoba": 0.340},
                {"mlbam_id": "7", "xba": 0.250, "xslg": 0.520, "xwoba": 0.350},
            ], data_dir)

    def test_alpha_zero_matches_classic_build(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            self._seed_statcast(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"}, "7": {"birth_date": "1994-01-01"}}
            classic = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            a0 = build_marcel_projections(
                2024, data_dir, MarcelParams(alpha_contact=0.0, alpha_power=0.0), idents)
            self.assertEqual([r["stats"] for r in classic], [r["stats"] for r in a0])

    def test_alpha_positive_changes_projection(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            self._seed_many(data_dir)
            self._seed_statcast(data_dir)
            idents = {"5": {"birth_date": "1994-01-01"}, "7": {"birth_date": "1994-01-01"}}
            classic = build_marcel_projections(2024, data_dir, MarcelParams(), idents)
            tuned = build_marcel_projections(
                2024, data_dir, MarcelParams(alpha_contact=0.5, alpha_power=0.5), idents)
            c = {r["id"]: r["stats"]["SLG"] for r in classic}
            t = {r["id"]: r["stats"]["SLG"] for r in tuned}
            self.assertTrue(any(abs(c[k] - t[k]) > 1e-9 for k in c))
