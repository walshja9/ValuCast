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
