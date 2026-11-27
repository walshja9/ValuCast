import tempfile
import unittest
from pathlib import Path

from league_values.engine import ValuationEngine
from league_values.post_processors import VolumeMultiplier
from league_values.presets import standard_5x5
from projections.data.historical import store_season
from projections.export.marcel_run import build_marcel_projections, write_run
from projections.models.marcel_params import MarcelParams
from web.projection_catalog import ProjectionCatalog


class TestProjectionsIntegration(unittest.TestCase):
    def test_engine_values_marcel_source_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            data_dir = Path(d)
            for yr in (2021, 2022, 2023):
                store_season(yr, [
                    {"mlbam_id": "5", "season": yr, "PA": 600, "AB": 540,
                     "H": 170, "1B": 110, "2B": 30, "3B": 2, "HR": 28,
                     "R": 95, "RBI": 92, "SB": 8, "CS": 2, "BB": 55,
                     "SO": 120, "HBP": 4, "SF": 5},
                    {"mlbam_id": "7", "season": yr, "PA": 580, "AB": 520,
                     "H": 140, "1B": 95, "2B": 25, "3B": 1, "HR": 19,
                     "R": 70, "RBI": 65, "SB": 15, "CS": 4, "BB": 50,
                     "SO": 110, "HBP": 3, "SF": 4},
                ], data_dir)
            rows = build_marcel_projections(
                2024, data_dir, MarcelParams(),
                identities={"5": {"name": "Bat Five", "birth_date": "1996-01-01"},
                            "7": {"name": "Bat Seven", "birth_date": "1993-01-01"}},
            )
            runs_dir = data_dir / "runs"
            run_id = write_run(rows, runs_dir, model="marcel", as_of_season=2024, version=1)

            cat = ProjectionCatalog(
                sources={"marcel": str(runs_dir / run_id / "projections.json")},
                default="marcel",
            )
            store = cat.store_for("marcel")
            engine = ValuationEngine(post_processors=[VolumeMultiplier()])
            results = engine.value_players(store.get_all(), standard_5x5())

            self.assertEqual(len(results), 2)
            # Engine produced a ranking with distinct total values.
            values = sorted((r.total_value for r in results), reverse=True)
            self.assertGreater(values[0], values[1])
