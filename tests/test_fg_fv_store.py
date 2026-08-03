"""FanGraphs FV store: mlbam join + fail-soft, and the committed snapshot shape.

The store is display-only scouting reference (FV + tool grades). It must never
be wired into scoring; this test only covers the card-side lookup contract.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from web.fg_fv_store import FgFvStore, _DEFAULT_PATH


ROOT = Path(__file__).resolve().parents[1]


class TestFgFvStore(unittest.TestCase):
    def test_lookup_and_failsoft(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "snap.json"
            path.write_text(json.dumps({"players_by_mlbam": {
                "800543": {"fv": "55", "fv_num": 55.0, "hit_grades": {"Hit": "40 / 60"}},
            }}), encoding="utf-8")
            store = FgFvStore(path)
            # int or str mlbam both resolve; missing / blank / None -> None.
            self.assertEqual(store.get(800543)["fv"], "55")
            self.assertEqual(store.get("800543")["fv_num"], 55.0)
            self.assertIsNone(store.get("999999"))
            self.assertIsNone(store.get(None))
            self.assertIsNone(store.get(""))

    def test_missing_artifact_is_empty_not_error(self):
        store = FgFvStore(Path(tempfile.gettempdir()) / "does_not_exist_fg.json")
        self.assertIsNone(store.get("800543"))  # no raise

    def test_committed_snapshot_is_joinable(self):
        if not _DEFAULT_PATH.exists():
            self.skipTest("fg_fv_snapshot.json not built")
        raw = json.loads(_DEFAULT_PATH.read_text(encoding="utf-8"))
        by = raw.get("players_by_mlbam") or {}
        self.assertGreaterEqual(len(by), 700)
        store = FgFvStore()
        sample_mid = next(iter(by))
        rec = store.get(sample_mid)
        self.assertIsNotNone(rec)
        self.assertIn("fv", rec)

    def test_current_export_passes_builder_self_check(self):
        result = subprocess.run(
            [sys.executable, "scripts/build_fangraphs_fv_snapshot.py"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
