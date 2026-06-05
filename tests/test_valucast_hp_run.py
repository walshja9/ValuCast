import json
import tempfile
import unittest
from pathlib import Path

from projections.export.valucast_hp_run import write_valucast_hp_run


def _h(pid):
    return {"id": f"mlbam_{pid}_H", "name": pid, "pool": "hitter", "positions": [],
            "stats": {"PA": 600, "HR": 25, "AVG": 0.280}, "metadata": {"mlbam_id": pid}}


def _p(pid):
    return {"id": f"mlbam_{pid}_P", "name": pid, "pool": "starter", "positions": ["SP"],
            "stats": {"IP": 180, "K": 200, "ERA": 3.50}, "metadata": {"mlbam_id": pid}}


class TestValucastHpRun(unittest.TestCase):
    def test_writes_combined_run_with_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "runs"
            run_id = write_valucast_hp_run(
                [_h("1"), _h("2")], [_p("3")], runs, version=1,
                hitter_meta={"model": "valucast_marcel_statcast", "alpha_contact": 0.75},
                pitcher_meta={"model": "valucast_pitching_marcel"},
            )
            self.assertEqual(run_id, "valucast_hp_2026_v1")
            rows = json.loads((runs / run_id / "projections.json").read_text())
            self.assertEqual(len(rows), 3)                       # 2 hitters + 1 pitcher
            man = json.loads((runs / run_id / "run_manifest.json").read_text())
            self.assertEqual(man["source_name"], "valucast")
            self.assertEqual(man["hitter_count"], 2)
            self.assertEqual(man["pitcher_count"], 1)
            self.assertEqual(man["components"]["hitters"]["alpha_contact"], 0.75)

    def test_rejects_single_pool(self):
        with tempfile.TemporaryDirectory() as d:
            runs = Path(d) / "runs"
            with self.assertRaises(ValueError):     # no pitchers -> reject
                write_valucast_hp_run([_h("1")], [], runs, version=1,
                                      hitter_meta={}, pitcher_meta={})
            with self.assertRaises(ValueError):     # no hitters -> reject
                write_valucast_hp_run([], [_p("3")], runs, version=1,
                                      hitter_meta={}, pitcher_meta={})
