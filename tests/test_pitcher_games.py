import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from projections.export.valucast_hp_run import write_valucast_hp_run
from projections.models.marcel_pitcher import project_pitcher
from projections.models.pitcher_params import PitcherMarcelParams


class TestPitcherGames(unittest.TestCase):
    def _project(self, games):
        prior = [{
            "mlbam_id": "600", "BF": 750, "IP": 180.0, "ER": 70,
            "H_ALLOWED": 150, "BB": 45, "HBP": 5, "K": 200,
            "HR": 22, "GS": 30, "G": games, "QS": 18,
            "SV": 0, "HLD": 0, "W": 14,
        } for _ in range(3)]
        rates = {c: 0.0 for c in ("K", "BB", "H_ALLOWED", "HR", "ER", "HBP")}
        factors = {c: 1.0 for c in rates}
        return project_pitcher(prior, rates, factors, PitcherMarcelParams())

    def test_pure_starter_games_include_all_starts(self):
        stats = self._project(30)["stats"]
        self.assertEqual(stats["GS"], 30.0)
        self.assertEqual(stats["G"], stats["GS"])

    def test_mixed_role_games_include_starts(self):
        row = self._project(40)
        self.assertTrue(row["metadata"]["mixed_role"])
        self.assertEqual(row["stats"]["GS"], 22.5)
        self.assertGreaterEqual(row["stats"]["G"], row["stats"]["GS"])
        self.assertEqual(row["stats"]["G"], 32.5)

    def test_export_retains_games_and_starts(self):
        pitcher = self._project(30)
        with TemporaryDirectory() as tmp:
            runs_dir = Path(tmp)
            run_id = write_valucast_hp_run(
                [{"id": "invented_H", "pool": "hitter"}], [pitcher],
                runs_dir, 1, {}, {},
            )
            rows = json.loads((runs_dir / run_id / "projections.json").read_text(encoding="utf-8"))
        stats = rows[1]["stats"]
        self.assertEqual(stats["G"], 30.0)
        self.assertEqual(stats["GS"], 30.0)
