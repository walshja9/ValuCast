"""Quality guards on the committed public ValuCast H+P run (the artifact users see)."""
import json
import unittest
from pathlib import Path

RUN = Path(__file__).parent.parent / "projections" / "runs" / "valucast_hp_2026_v2" / "projections.json"


class TestValucastRunQuality(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads(RUN.read_text(encoding="utf-8"))
        cls.hitters = [r for r in cls.rows if r["pool"] == "hitter"]
        cls.pitchers = [r for r in cls.rows if r["pool"] in ("starter", "reliever", "pitcher")]

    def test_both_pools_present(self):
        self.assertGreater(len(self.hitters), 100)
        self.assertGreater(len(self.pitchers), 100)

    def test_no_numeric_pitcher_names(self):
        numeric = [r["id"] for r in self.pitchers if str(r["name"]).strip().isdigit()]
        self.assertEqual(numeric, [], f"{len(numeric)} pitchers still have numeric names")

    def test_no_numeric_hitter_names(self):
        numeric = [r["id"] for r in self.hitters if str(r["name"]).strip().isdigit()]
        self.assertEqual(numeric, [])

    def test_hitter_position_coverage(self):
        with_pos = sum(1 for r in self.hitters if r.get("positions"))
        self.assertGreater(with_pos / len(self.hitters), 0.9)   # >90% have positions

    def test_shortstop_eligible_players_exist(self):
        ss = [r for r in self.hitters if "SS" in (r.get("positions") or [])]
        self.assertGreater(len(ss), 10)   # position filters return meaningful results

    def test_team_coverage_through_projection_store(self):
        # Load the way the app does (ProjectionStore overwrites metadata.team from
        # top-level row.team) and assert teams are not blank.
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from web.projection_store import ProjectionStore
        players = ProjectionStore(str(RUN)).get_all()
        with_team = sum(1 for p in players if (p.metadata.get("team") or "").strip())
        source_with_team = sum(1 for row in self.rows if (row.get("team") or "").strip())
        # Free agents make upstream coverage drift. This guard owns only the join:
        # ProjectionStore must preserve every team the committed run supplies.
        self.assertEqual(with_team, source_with_team)

    def test_manifest_documents_eligibility_source(self):
        man = json.loads((RUN.parent / "run_manifest.json").read_text(encoding="utf-8"))
        self.assertIn("eligibility_source", man)
        self.assertIn("no projection stats", man["eligibility_source"].lower())
