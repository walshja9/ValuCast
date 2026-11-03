"""Synthetic-only checks for the offline board rehearsal."""
import csv
import json
import math
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

from scripts import compare_2027_boards as boards
from web.config_builder import build_config
from web.projection_store import ProjectionStore


def row(player_id, rank, value, role="hitter", age=25):
    return dict(mlbam_id=str(player_id), name="Synthetic %s" % player_id,
                role=role, team="TEST", age=age, rank=rank, value=value)


def projections():
    rows = []
    for i in range(1, 5):
        rows.append(dict(id=str(i), name="Synthetic %s" % i, pool="hitter",
                         positions=["OF"], team="TEST",
                         metadata={"mlbam_id": i, "base_id": str(i)},
                         stats={"PA": 600, "AB": 500, "H": 120 + i * 10,
                                "R": 50 + i * 10, "HR": i * 10,
                                "RBI": 40 + i * 10, "SB": i * 5}))
    rows.append(dict(id="1", name="Synthetic 1", pool="starter", team="TEST",
                     positions=["SP"], metadata={"mlbam_id": 1, "base_id": "1"},
                     stats={"IP": 180, "W": 15, "SV": 0, "K": 200,
                            "ER": 60, "BB": 40, "H_ALLOWED": 150}))
    rows.append(dict(id="5", name="Synthetic 5", pool="reliever", team="TEST",
                     positions=["RP"], metadata={"mlbam_id": 5},
                     stats={"IP": 65, "W": 3, "SV": 30, "K": 80,
                            "ER": 20, "BB": 20, "H_ALLOWED": 45}))
    rows.append(dict(id="6", name="Below floor", pool="hitter", team="TEST",
                     positions=["OF"], metadata={"mlbam_id": 6},
                     stats={"PA": 99, "AB": 80, "H": 20}))
    return rows


class ComparisonTests(unittest.TestCase):
    def test_identity_is_role_sensitive_and_shifts_are_new_minus_old(self):
        old = [row(1, 1, 90), row(1, 2, 80, "pitcher")]
        new = [row(1, 2, 88), row(1, 1, 95, "pitcher")]
        result = boards.compare_rows(old, new)
        self.assertEqual(result["matched_count"], 2)
        shifts = {r["role"]: r for r in result["matched"]}
        self.assertEqual((shifts["hitter"]["rank_shift"],
                          shifts["pitcher"]["value_shift"]), (1, 15))
        self.assertAlmostEqual(result["spearman"], -1)

    def test_spearman_uses_matched_rank_order_and_average_ties(self):
        old = [row(1, 1, 1), row(2, 2, 2), row(3, 3, 3)]
        new = [row(1, 1, 1), row(2, 3, 2), row(3, 2, 3)]
        self.assertAlmostEqual(boards.compare_rows(old, new)["spearman"], .5)
        old[1]["rank"] = 1
        new[1]["rank"], new[2]["rank"] = 2, 3
        self.assertAlmostEqual(boards.compare_rows(old, new)["spearman"],
                               math.sqrt(3) / 2)

    def test_cutoff_membership_is_based_on_rank_not_input_order(self):
        old = [row(1, 301, 10), row(2, 300, 20), row(3, 100, 30)]
        new = [row(2, 301, 19), row(1, 300, 21), row(3, 100, 30)]
        result = boards.compare_rows(old, new)
        self.assertEqual(result["overlap"][100]["count"], 1)
        self.assertEqual(result["overlap"][300]["count"], 1)
        self.assertEqual(result["overlap"][300]["percent"], 50)
        self.assertEqual(len(result["matched"]), 3)
        self.assertEqual([r["mlbam_id"] for r in result["entered_top300"]], ["1"])
        self.assertEqual([r["mlbam_id"] for r in result["dropped_top300"]], ["2"])
        self.assertEqual([r["mlbam_id"] for r in result["risers"]], ["1"])
        self.assertEqual([r["mlbam_id"] for r in result["fallers"]], ["2"])

    def test_groups_use_new_age_including_unknown(self):
        old = [row(i, i, i, age=21) for i in range(1, 7)]
        new = [row(i, i, i + 2, age=age)
               for i, age in enumerate([22, 25, 28, 31, 32, None], 1)]
        result = boards.compare_rows(old, new)
        groups = {r["group"]: r for r in result["by_age_band"]}
        self.assertEqual(set(groups), {"<=22", "23-25", "26-28", "29-31", "32+", "Unknown"})
        self.assertTrue(all(r["count"] == 1 for r in groups.values()))
        self.assertTrue(all(r["mean_value_shift"] == 2 for r in groups.values()))
        self.assertEqual(result["by_role"][0]["mean_rank_shift"], 0)

    def test_invalid_comparison_rows_fail_instead_of_silently_disappearing(self):
        for bad in [dict(row(1, 1, 1), mlbam_id=None),
                    dict(row(1, 1, 1), rank=0),
                    dict(row(1, 1, 1), value=float("nan"))]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    boards.compare_rows([bad], [row(1, 1, 1)])
        with self.assertRaises(ValueError):
            boards.compare_rows([row(1, 1, 1), row(1, 2, 2)], [])

    def test_empty_and_singleton_spearman_are_explicitly_undefined(self):
        for rows in [[], [row(1, 1, 1)]]:
            result = boards.compare_rows(rows, rows)
            self.assertIsNone(result["spearman"])
            self.assertEqual(result["overlap"][300]["percent"], 100)


class RehearsalIntegrationTests(unittest.TestCase):
    def setUp(self):
        # Ordinary mkdir avoids private mode-0700 ACLs in the Windows sandbox.
        scratch = (Path.cwd() / ".tmp-tests").resolve()
        self.root = scratch / ("compare-boards-" + uuid4().hex)
        self.root.mkdir(parents=True)

        def cleanup():
            target = self.root.resolve()
            assert target.parent == scratch and target.name.startswith("compare-boards-")
            shutil.rmtree(target)

        self.addCleanup(cleanup)
        self.projection_path = self.root / "projections.json"
        self.projection_path.write_text(json.dumps(projections()), encoding="ascii")
        self.helpers = boards.app_helpers()
        self.helpers["_ineligible_mlbam_ids"] = lambda: frozenset()
        self.helpers["_mlb_availability_by_id"] = lambda: {}

    def test_redraft_calls_original_pipeline_and_preserves_two_way_merge(self):
        self.helpers["_ineligible_mlbam_ids"] = lambda: frozenset({"4"})
        self.helpers["_mlb_availability_by_id"] = lambda: {"3": {"status": "injured"}}
        original = self.helpers["_redraft_value_players"](
            self.helpers["_valuation_players"](
                active_store=ProjectionStore(self.projection_path)), build_config())
        original.sort(key=lambda r: r.total_value, reverse=True)
        scale = self.helpers["_redraft_value_scale"](original)
        actual = boards.redraft_rows(self.projection_path,
                                     ages={("1", "hitter"): 27}, helpers=self.helpers)
        self.assertEqual([r["mlbam_id"] for r in actual],
                         [str(r.player.metadata["mlbam_id"]) for r in original])
        self.assertEqual(len(actual), 3)
        for rank, (reported, valued) in enumerate(zip(actual, original), 1):
            self.assertEqual(reported["rank"], rank)
            self.assertEqual(reported["value"],
                             self.helpers["_redraft_scaled_value"](valued.total_value, scale))
            self.assertEqual(set(reported),
                             {"mlbam_id", "name", "role", "team", "age", "rank", "value"})
        self.assertEqual(next(r for r in actual if r["mlbam_id"] == "1")["age"], 27)

    def test_redraft_age_falls_back_when_dynasty_age_is_missing(self):
        source = projections()
        source[1]["metadata"]["age"] = 24
        self.projection_path.write_text(json.dumps(source), encoding="ascii")
        actual = boards.redraft_rows(self.projection_path, ages={("2", "hitter"): None},
                                     helpers=self.helpers)
        self.assertEqual(next(r for r in actual if r["mlbam_id"] == "2")["age"], 24)

    def test_zero_diff_outputs_only_allowed_fields_and_readiness(self):
        dynasty = self.root / "dynasty.json"
        source = [dict(row(i, i, 100 - i, age=22 + i),
                       stat_line={"stats": {"RAW_SECRET": 123}}) for i in range(1, 6)]
        source[0]["name"] = "Synthet\u00edc"
        dynasty.write_text(json.dumps({"players": source, "validation": {
            "ready_for_live_consumers": False, "blockers": ["Synthetic blocker"],
            "age_coverage_count": 5, "age_coverage_rate": 1.0,
            "age_coverage_threshold": .95}}), encoding="ascii")
        out = self.root / "out"
        with patch.object(boards, "app_helpers", return_value=self.helpers):
            results = boards.compare_files(dynasty, dynasty, self.projection_path,
                                           self.projection_path, out)
        for summary in results.values():
            self.assertEqual(summary["overlap"][100]["percent"], 100)
            self.assertEqual(summary["overlap"][300]["percent"], 100)
            self.assertTrue(all(r["rank_shift"] == r["value_shift"] == 0
                                for r in summary["matched"]))
        self.assertEqual({p.name for p in out.iterdir()}, {"report.md", "movers.csv"})
        report = (out / "report.md").read_text(encoding="ascii")
        self.assertIn("Synthetic blocker", report)
        self.assertIn("ready_for_live_consumers", report)
        self.assertIn("inferred", report.lower())
        self.assertIn("new board", report.lower())
        self.assertNotIn("RAW_SECRET", report)
        with (out / "movers.csv").open(encoding="ascii", newline="") as handle:
            movers = list(csv.DictReader(handle))
        self.assertEqual(len(movers), sum(r["matched_count"] for r in results.values()))
        self.assertEqual({r["board"] for r in movers}, {"dynasty", "redraft"})
        self.assertTrue(all(float(r["old_value"]) == float(r["new_value"]) for r in movers))


if __name__ == "__main__":
    unittest.main()
