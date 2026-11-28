"""Prospective canonical history only: synthetic inputs, no files or models."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import unittest
from unittest.mock import patch

from web.recorded_public_history import apply_recorded_public_history


def _row(value=45.0, identity=1, role="hitter", domain="mlb", history=None):
    points = history if history is not None else []
    return {"mlbam_id": identity, "role": role, "player_type": domain,
            "rank": 1, "value": value, "value_scale": "score-v1",
            "context": {"value_history": deepcopy(points), "chart_value_history": deepcopy(points)}}


def _snapshot(day="2026-12-03", method="a", rows=None, source="prospect_model_v0_6"):
    return {"schema_version": "1.1", "artifact": "valucast_public_dynasty_snapshot",
            "generated_at": day + "T12:00:00+00:00",
            "input_artifacts": {"mlb_dynasty_method_id": method,
                                "prospect_rank_v1_version": "0.2.9",
                                "prospect_score_source": source},
            "quality_governor": {"ready_for_public_snapshot": False},
            "players": [_row()] if rows is None else rows}


def _bytes(payload):
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _apply(payload, prior=None, cutoff=None):
    return apply_recorded_public_history(
        payload, None if prior is None else _bytes(prior),
        legacy_mlb_policy={"latest_incompatible_date": cutoff, "dates": []},
    )


class TestRecordedPublicHistory(unittest.TestCase):
    def test_three_days_keep_final_public_floor_and_exact_prior_digest(self):
        first = _apply(_snapshot("2026-12-01"))
        second = _apply(_snapshot("2026-12-02", rows=[_row(history=[("2026-12-01", 3)])]), first)
        third = _apply(_snapshot(rows=[_row(history=[("2026-12-01", 3), ("2026-12-02", 3)])]), second)
        expected = [("2026-12-01", 45.0), ("2026-12-02", 45.0), ("2026-12-03", 45.0)]
        self.assertEqual(third["players"][0]["context"]["value_history"], expected)
        self.assertEqual(third["players"][0]["context"]["chart_value_history"], expected)
        self.assertEqual(third["recorded_public_history"]["previous_snapshot_sha256"], hashlib.sha256(_bytes(second)).hexdigest())

    def test_legacy_thirty_points_are_retained_and_not_relabelled(self):
        start = date(2026, 11, 1)
        points = [((start + timedelta(days=index)).isoformat(), float(index)) for index in range(30)]
        payload = _snapshot("2026-11-30", rows=[_row(29, history=points)])
        before = deepcopy(payload)
        result = _apply(payload)
        self.assertEqual(result["players"][0]["context"]["value_history"], points)
        self.assertEqual(payload, before)
        self.assertEqual(result["players"][0]["context"]["value_history_basis"]["legacy_points"], 29)

    def test_public_only_bridge_and_absent_player_return(self):
        first = _apply(_snapshot("2026-12-01"))
        absent = _apply(_snapshot("2026-12-02", rows=[]), first)
        returned = _apply(_snapshot(), absent)
        self.assertEqual(returned["players"][0]["context"]["value_history"], [("2026-12-01", 45.0), ("2026-12-03", 45.0)])
        self.assertEqual(returned["players"][0]["context"]["chart_value_history"], [("2026-12-01", 45.0), ("2026-12-03", 45.0)])

    def test_method_a_b_a_even_without_player_and_on_same_date(self):
        first = _apply(_snapshot("2026-12-01", "a"))
        other = _apply(_snapshot("2026-12-02", "b", rows=[]), first)
        returned = _apply(_snapshot(method="a", rows=[_row(history=[("2026-12-01", 3)])]), other)
        self.assertEqual(returned["players"][0]["context"]["value_history"], [("2026-12-01", 45.0), ("2026-12-03", 45.0)])
        self.assertEqual(returned["players"][0]["context"]["chart_value_history"], [("2026-12-03", 45.0)])
        self.assertEqual(returned["recorded_public_history"]["domains"]["mlb"]["comparison_epoch"], 3)
        same_b = _apply(_snapshot("2026-12-03", "b"), returned)
        same_a = _apply(_snapshot("2026-12-03", "a"), same_b)
        self.assertEqual(same_a["players"][0]["context"]["chart_value_history"], [("2026-12-03", 45.0)])
        self.assertEqual(same_a["recorded_public_history"]["domains"]["mlb"]["epoch"], 5)
        self.assertEqual(same_a["recorded_public_history"]["domains"]["mlb"]["comparison_epoch"], 5)

    def test_raw_incompatible_empty_date_and_november_boundary_are_respected(self):
        prior = _apply(_snapshot("2026-11-17"))
        current = _snapshot("2026-11-19", rows=[_row(history=[("2026-11-17", 3)])])
        for cutoff in ("2026-11-17", "2026-11-18"):
            result = _apply(current, prior, cutoff)
            self.assertEqual(result["players"][0]["context"]["value_history"], [("2026-11-17", 45.0), ("2026-11-19", 45.0)])
            self.assertEqual(result["players"][0]["context"]["chart_value_history"], [("2026-11-19", 45.0)])

    def test_same_day_current_wins_and_retries_are_pure(self):
        prior = _apply(_snapshot(rows=[_row(40)]))
        current = _snapshot(rows=[_row(45)])
        result = _apply(current, prior)
        self.assertEqual(result["players"][0]["context"]["value_history"], [("2026-12-03", 45.0)])
        self.assertEqual(_apply(current, prior), result)
        candidate = _apply(_snapshot(rows=[_row(90)]), prior)
        self.assertNotEqual(candidate["players"][0]["value"], result["players"][0]["value"])
        self.assertEqual(_apply(current, prior), result)

    def test_role_returns_and_two_way_rows_never_reuse_other_roles(self):
        hitter = _apply(_snapshot("2026-12-01"))
        both = _apply(_snapshot("2026-12-02", rows=[_row(70, role="two_way")]), hitter)
        returned = _apply(_snapshot(rows=[_row(45, history=[("2026-12-01", 3), ("2026-12-02", 63)])]), both)
        self.assertEqual(returned["players"][0]["context"]["chart_value_history"], [("2026-12-03", 45.0)])
        self.assertEqual(returned["players"][0]["context"]["value_history"], [("2026-12-01", 45.0), ("2026-12-02", 63), ("2026-12-03", 45.0)])
        self.assertEqual(returned["players"][0]["context"]["value_history_basis"]["legacy_points"], 1)

    def test_real_scale_change_fails_closed_before_unlike_unit_arithmetic(self):
        first = _apply(_snapshot("2026-12-01"))
        changed = _snapshot("2026-12-02", rows=[_row(450)])
        changed["players"][0]["value_scale"] = "score-v2"
        with self.assertRaisesRegex(ValueError, "scale|unit"):
            _apply(changed, first)

    def test_cosmetic_common_scale_certification_preserves_underlying_units(self):
        first = _apply(_snapshot("2026-12-01"))
        renamed = _snapshot("2026-12-02")
        renamed["players"][0]["value_scale"] = "0_100_valucast_dynasty_score"
        renamed["players"][0]["context"]["cross_universe_calibration"] = {
            "unit_mapping_applied": False, "value_mutation": "none", "raw_value_scale": "score-v1"}
        result = _apply(renamed, first)
        self.assertEqual(result["players"][0]["context"]["chart_value_history"], [("2026-12-01", 45.0), ("2026-12-02", 45.0)])
        raw_again = _apply(_snapshot(), result)
        self.assertEqual(len(raw_again["players"][0]["context"]["chart_value_history"]), 3)

    def test_explicit_prospect_unit_bridge_can_coexist_with_mlb_unit_rows(self):
        mlb = _row(identity=1)
        bridge = _row(identity=2)
        bridge["active_mlb_callup_bridge"] = True
        for row, raw_scale in ((mlb, "0_100_valucast_mlb_shadow_dynasty_score"),
                               (bridge, "0_100_valucast_prospect_score")):
            row["value_scale"] = "0_100_valucast_dynasty_score"
            row["context"]["cross_universe_calibration"] = {
                "unit_mapping_applied": False, "value_mutation": "none", "raw_value_scale": raw_scale}
        first = _apply(_snapshot("2026-12-01", rows=[mlb, bridge]))
        second = _apply(_snapshot("2026-12-02", rows=[mlb, bridge]), first)
        self.assertEqual([len(row["context"]["chart_value_history"]) for row in second["players"]], [2, 2])
        observations = second["recorded_public_history"]["observations"]
        domains = second["recorded_public_history"]["domains"]
        self.assertEqual({domains[group["domain"]]["epochs"][str(point[2])]["scale"]
                          for group in observations for point in group["points"]}, {
            "0_100_valucast_mlb_shadow_dynasty_score", "0_100_valucast_prospect_score"})
        self.assertTrue(all(set(group) == {"mlbam_id", "domain", "role", "points"} for group in observations))
        self.assertTrue(all(len(point) == 4 for group in observations for point in group["points"]))

    def test_known_bridge_to_mlb_domain_keeps_legacy_records_without_movement_arithmetic(self):
        bridge = _row()
        bridge.update(active_mlb_callup_bridge=True, value_scale="0_100_valucast_prospect_score")
        prior = _apply(_snapshot("2026-12-01", rows=[bridge]))
        mlb = _row(history=[("2026-12-01", 45.0)])
        mlb["value_scale"] = "0_100_valucast_mlb_shadow_dynasty_score"
        current = _apply(_snapshot("2026-12-02", rows=[mlb]), prior)
        context = current["players"][0]["context"]
        self.assertEqual(context["value_history"], [("2026-12-01", 45.0), ("2026-12-02", 45.0)])
        self.assertEqual(context["chart_value_history"], [("2026-12-02", 45.0)])
        self.assertIs(context["value_history_basis"]["movement_comparable"], False)

    def test_existing_prospect_epoch_bounds_display_but_preserves_genuine_carrier_records(self):
        cutoff = "2026-07-30"
        def apply_at(day, prior=None):
            return apply_recorded_public_history(
                _snapshot(day, rows=[_row(domain="prospect")]),
                None if prior is None else _bytes(prior), prospect_history_epoch_date=cutoff,
            )
        before = apply_at("2026-07-29")
        self.assertNotIn("value_history", before["players"][0]["context"])
        self.assertNotIn("chart_value_history", before["players"][0]["context"])
        at = apply_at(cutoff, before)
        after = apply_at("2026-07-31", at)
        self.assertEqual(at["players"][0]["context"]["value_history"], [(cutoff, 45.0)])
        expected = [(cutoff, 45.0), ("2026-07-31", 45.0)]
        self.assertEqual(after["players"][0]["context"]["value_history"], expected)
        self.assertEqual(after["players"][0]["context"]["chart_value_history"], expected)
        points = after["recorded_public_history"]["observations"][0]["points"]
        self.assertEqual([point[0] for point in points], ["2026-07-29", cutoff])

    def test_same_day_role_or_domain_replacement_is_comparable_when_exact_key_wins(self):
        for domain_change in (False, True):
            previous = _row(40)
            current = _row(70, role="hitter" if domain_change else "two_way", history=[("2026-12-01", 63)])
            if domain_change:
                previous.update(active_mlb_callup_bridge=True, value_scale="0_100_valucast_prospect_score")
                current["value_scale"] = "0_100_valucast_mlb_shadow_dynasty_score"
            first = _apply(_snapshot("2026-12-01", rows=[previous]))
            replaced = _apply(_snapshot("2026-12-01", rows=[current]), first)
            next_row = deepcopy(current)
            next_row["value"] = 71
            result = _apply(_snapshot("2026-12-02", rows=[next_row]), replaced)
            with self.subTest(domain_change=domain_change):
                self.assertEqual(result["players"][0]["context"]["value_history"], [("2026-12-01", 70), ("2026-12-02", 71)])
                self.assertIs(result["players"][0]["context"]["value_history_basis"]["movement_comparable"], True)

    def test_incompatible_evidence_on_trimmed_away_date_does_not_suppress_movement(self):
        first = _apply(_snapshot("2026-12-01"))
        history = [(f"2026-12-{day:02}", float(day)) for day in range(1, 31)]
        result = _apply(_snapshot("2026-12-31", rows=[_row(70, role="two_way", history=history)]), first)
        context = result["players"][0]["context"]
        self.assertEqual(len(context["value_history"]), 30)
        self.assertEqual(context["value_history"][0][0], "2026-12-02")
        self.assertIs(context["value_history_basis"]["movement_comparable"], True)

    def test_bridge_uses_own_method_and_never_draws_raw_mlb_legacy_values(self):
        bridge = _row()
        bridge.update(active_mlb_callup_bridge=True, value_scale="0_100_valucast_prospect_score")
        first = _apply(_snapshot("2026-12-01", rows=[bridge]))
        next_row = deepcopy(bridge)
        next_row["value"] = 46
        next_row["context"]["value_history"] = [("2026-11-30", 3), ("2026-12-01", 3)]
        next_row["context"]["chart_value_history"] = list(next_row["context"]["value_history"])
        for cutoff in (None, "2026-12-01"):
            result = _apply(_snapshot("2026-12-02", "different-mlb-method", rows=[next_row]), first, cutoff)
            context = result["players"][0]["context"]
            with self.subTest(cutoff=cutoff):
                self.assertEqual(context["chart_value_history"], [("2026-12-01", 45.0), ("2026-12-02", 46)])
                self.assertEqual(context["value_history"], [("2026-11-30", 3), ("2026-12-01", 45.0), ("2026-12-02", 46)])
                self.assertIs(context["value_history_basis"]["movement_comparable"], False)

    def test_prospect_contract_changes_but_narrow_universal_and_labels_do_not(self):
        first = _apply(_snapshot("2026-12-01", rows=[_row(domain="prospect")]))
        current = _snapshot("2026-12-02", rows=[_row(domain="prospect")])
        current["input_artifacts"].update(prospect_universal_model_version="0.4.1", unrelated_label="new")
        second = _apply(current, first)
        self.assertEqual(len(second["players"][0]["context"]["chart_value_history"]), 2)
        changed = _snapshot(rows=[_row(domain="prospect")], source="different_scoring_source")
        third = _apply(changed, second)
        self.assertEqual(third["players"][0]["context"]["chart_value_history"], [("2026-12-03", 45.0)])

    def test_unknown_method_does_not_create_a_compatible_recorded_tail(self):
        first = _apply(_snapshot("2026-12-01", method=None))
        second = _apply(_snapshot("2026-12-02", method=None), first)
        self.assertEqual(second["players"][0]["context"]["value_history"], [("2026-12-01", 45.0), ("2026-12-02", 45.0)])
        self.assertEqual(second["players"][0]["context"]["chart_value_history"], [("2026-12-02", 45.0)])

    def test_unknown_current_method_preserves_all_thirty_legacy_selected_points(self):
        start = date(2026, 11, 1)
        points = [((start + timedelta(days=index)).isoformat(), float(index)) for index in range(30)]
        result = _apply(_snapshot("2026-11-30", method=None, rows=[_row(29, history=points)]))
        self.assertEqual(result["players"][0]["context"]["value_history"], points)
        self.assertEqual(result["players"][0]["context"]["chart_value_history"], points)

    def test_known_missing_same_known_preserves_selection_without_adding_unknown_dates(self):
        first = _apply(_snapshot("2026-12-01", "a"))
        missing = _apply(_snapshot("2026-12-02", None, rows=[_row(history=[("2026-12-01", 3)])]), first)
        self.assertEqual(missing["players"][0]["context"]["chart_value_history"], [("2026-12-01", 45.0), ("2026-12-02", 45.0)])
        restored = _apply(_snapshot(rows=[_row(history=[("2026-12-01", 3), ("2026-12-02", 3)])]), missing)
        self.assertEqual(restored["players"][0]["context"]["chart_value_history"], [("2026-12-01", 45.0), ("2026-12-02", 45.0), ("2026-12-03", 45.0)])
        excluded = _apply(_snapshot(rows=[_row(history=[("2026-12-01", 3)])]), missing)
        self.assertEqual(excluded["players"][0]["context"]["chart_value_history"], [("2026-12-01", 45.0), ("2026-12-03", 45.0)])
        state = restored["recorded_public_history"]["domains"]["mlb"]
        self.assertEqual(state["comparison_epoch"], 1)
        unknown = next(metadata for metadata in state["epochs"].values() if metadata["method"]["method_id"] is None)
        self.assertEqual(unknown["comparison_epoch"], 1)

    def test_invalid_carrier_provenance_is_rejected_before_overlay(self):
        first = _apply(_snapshot("2026-12-01"))
        prior = _apply(_snapshot("2026-12-02"), first)
        for change in ("digest", "role_epoch", "unknown_identity", "method_shape", "date_shape", "boolean_schema",
                       "comparison_counter", "comparison_method", "registry_comparison"):
            corrupt = deepcopy(prior)
            carrier = corrupt["recorded_public_history"]
            if change == "digest":
                carrier["previous_snapshot_sha256"] = "not-a-digest"
            elif change == "role_epoch":
                point = list(carrier["observations"][0]["points"][0])
                point[3] = 999
                carrier["observations"][0]["points"][0] = point
            elif change == "unknown_identity":
                carrier["observations"][0]["mlbam_id"] = "999"
            elif change == "method_shape":
                carrier["domains"]["mlb"]["method"] = {"method_id": {"invalid": True}}
            elif change == "date_shape":
                point = list(carrier["observations"][0]["points"][0])
                point[0] += "T00:00:00Z"
                carrier["observations"][0]["points"][0] = point
            elif change == "comparison_counter":
                carrier["domains"]["mlb"]["comparison_epoch"] = True
            elif change == "comparison_method":
                carrier["domains"]["mlb"]["comparison_method"]["method_id"] = True
            elif change == "registry_comparison":
                carrier["domains"]["mlb"]["epochs"]["1"]["comparison_epoch"] = 999
            else:
                carrier["schema_version"] = True
            with self.subTest(change=change), self.assertRaises(ValueError):
                _apply(_snapshot(), corrupt)

    def test_grouped_schema_rejects_duplicate_groups_dates_and_invalid_fixed_tuples(self):
        prior = _apply(_snapshot("2026-12-02"), _apply(_snapshot("2026-12-01")))
        for change in ("duplicate_group", "duplicate_date", "wrong_width", "boolean_epoch", "nonnumeric_value", "empty_group"):
            corrupt = deepcopy(prior)
            groups = corrupt["recorded_public_history"]["observations"]
            if change == "duplicate_group":
                groups.append(deepcopy(groups[0]))
            elif change == "duplicate_date":
                groups[0]["points"].append(groups[0]["points"][0])
            elif change == "empty_group":
                groups[0]["points"] = []
            else:
                point = list(groups[0]["points"][0])
                if change == "wrong_width":
                    point.append("extra")
                elif change == "boolean_epoch":
                    point[2] = True
                else:
                    point[1] = "NaN"
                groups[0]["points"][0] = point
            with self.subTest(change=change), self.assertRaises(ValueError):
                _apply(_snapshot(), corrupt)

    def test_stale_malformed_unknown_and_duplicate_carriers_fail_closed(self):
        prior = _apply(_snapshot("2026-12-02"), _apply(_snapshot("2026-12-01")))
        with self.assertRaises(ValueError):
            _apply(_snapshot("2026-12-01"), prior)
        for corrupt in (b"{", b"[]"):
            with self.subTest(corrupt=corrupt), self.assertRaises(ValueError):
                apply_recorded_public_history(_snapshot(), corrupt)
        for change in ("schema", "duplicate", "future", "value", "null"):
            corrupt = deepcopy(prior)
            carrier = corrupt["recorded_public_history"]
            if change == "schema":
                carrier["schema_version"] = 999
            elif change == "duplicate":
                carrier["identities"] += deepcopy(carrier["identities"])
            elif change == "null":
                corrupt["recorded_public_history"] = None
            else:
                point = list(carrier["observations"][0]["points"][0])
                if change == "future":
                    point[0] = "2027-01-01"
                else:
                    point[1] = float("nan")
                carrier["observations"][0]["points"][0] = point
            with self.subTest(change=change), self.assertRaises(ValueError):
                _apply(_snapshot("2026-12-04"), corrupt)

    def test_preliminary_canonical_prior_is_accepted_and_inherited_history_is_not_seeded(self):
        prior = _snapshot("2026-12-01", rows=[_row(history=[("2026-11-01", 999)])])
        result = _apply(_snapshot("2026-12-02"), prior)
        self.assertEqual(result["players"][0]["context"]["value_history"], [("2026-12-01", 45.0), ("2026-12-02", 45.0)])
        observations = result["recorded_public_history"]["observations"]
        self.assertEqual([point[0] for group in observations for point in group["points"]], ["2026-12-01"])

    def test_initial_source_metadata_transport_preserves_legacy_chart_membership(self):
        prior = _snapshot("2026-12-01", rows=[_row(domain="prospect")])
        prior["input_artifacts"].pop("prospect_score_source")
        current = _snapshot("2026-12-02", rows=[_row(domain="prospect", history=[("2026-12-01", 3)])])
        result = _apply(current, prior)
        self.assertEqual(result["players"][0]["context"]["chart_value_history"], [("2026-12-01", 45.0), ("2026-12-02", 45.0)])
        no_legacy_date = _apply(_snapshot("2026-12-02", rows=[_row(domain="prospect")]), prior)
        self.assertEqual(no_legacy_date["players"][0]["context"]["chart_value_history"], [("2026-12-02", 45.0)])

    def test_unqualified_and_ambiguous_rows_remain_diagnostic_and_unrecorded(self):
        bad = [_row(identity=None), _row(identity=2, role=None), _row(float("nan"), identity=3),
               _row(identity=4), _row(identity=5), _row(identity=5, role="pitcher")]
        bad[3]["value_scale"] = None
        prior = _snapshot("2026-12-01", rows=bad)
        current = _snapshot("2026-12-02", rows=deepcopy(bad))
        current["validation"] = {"ready_for_live_consumers": False, "blockers": ["synthetic missing identity"]}
        result = _apply(current, prior)
        self.assertEqual(result["validation"], current["validation"])
        self.assertEqual(result["players"][0]["context"], current["players"][0]["context"])
        self.assertEqual(result["recorded_public_history"]["observations"], [])
        for label in ("current", "prior"):
            skips = result["recorded_public_history"]["skipped_rows"][label]
            self.assertEqual(skips["unqualified_identity_or_role"], 2)
            self.assertEqual(skips["unqualified_value_or_unit"], 2)
            self.assertEqual(skips["ambiguous_identity_rows"], 2)

    def test_retention_is_thirty_observations_and_no_absent_day_is_filled(self):
        current = None
        start = date(2026, 12, 1)
        for offset in range(33):
            current = _apply(_snapshot((start + timedelta(days=offset)).isoformat()), current)
        self.assertLessEqual(sum(len(group["points"]) for group in current["recorded_public_history"]["observations"]), 30)
        self.assertEqual(len(current["players"][0]["context"]["value_history"]), 30)

    def test_absent_return_inside_and_outside_global_publication_window(self):
        start = date(2026, 12, 1)
        for absent_count, has_old_point in ((28, True), (31, False)):
            current = _apply(_snapshot(start.isoformat()))
            for offset in range(1, absent_count + 1):
                current = _apply(_snapshot((start + timedelta(days=offset)).isoformat(), rows=[]), current)
            returned = _apply(_snapshot((start + timedelta(days=absent_count + 1)).isoformat()), current)
            history = returned["players"][0]["context"]["value_history"]
            self.assertEqual(any(day == start.isoformat() for day, _ in history), has_old_point)
            self.assertLessEqual(len(returned["recorded_public_history"]["accepted_dates"]), 30)
            if not has_old_point:
                self.assertEqual(returned["recorded_public_history"]["observations"], [])


class TestRecordedPublicHistoryWiring(unittest.TestCase):
    def test_prior_carrier_own_row_consistency_stops_runner_before_any_child(self):
        from scripts import run_daily_public_build as daily
        prior = _apply(_snapshot("2026-12-02"), _apply(_snapshot("2026-12-01")))
        for change in ("method", "role", "domain", "unit"):
            corrupt = deepcopy(prior)
            if change == "method":
                corrupt["input_artifacts"]["mlb_dynasty_method_id"] = "different-method"
            elif change == "role":
                corrupt["players"][0]["role"] = "two_way"
            elif change == "domain":
                corrupt["players"][0]["player_type"] = "prospect"
            else:
                corrupt["players"][0]["value_scale"] = "different-units"
            with patch.object(daily.Path, "read_bytes", return_value=_bytes(corrupt)), patch.object(daily.subprocess, "run") as run, patch.object(daily, "print", create=True):
                with self.subTest(change=change):
                    with self.assertRaisesRegex(ValueError, "prior|Prior|conflict|provenance"):
                        daily.main(["--only", "build", "--previous-public-snapshot", "immutable-prior.json"])
                    self.assertEqual(run.call_count, 0)

    def test_typed_invalid_prior_methods_stop_runner_before_any_child(self):
        from scripts import run_daily_public_build as daily
        fields = ("mlb_dynasty_method_id", "prospect_rank_v1_version", "prospect_score_source")
        for field in fields:
            for value in (True, 123, [], {}):
                prior = _snapshot()
                prior["input_artifacts"][field] = value
                with patch.object(daily.Path, "read_bytes", return_value=_bytes(prior)), patch.object(daily.subprocess, "run") as run, patch.object(daily, "print", create=True):
                    with self.subTest(field=field, value_type=type(value).__name__), self.assertRaisesRegex(ValueError, "method|metadata"):
                        daily.main(["--only", "build", "--previous-public-snapshot", "immutable-prior.json"])
                    self.assertEqual(run.call_count, 0, "Invalid prior metadata started candidate steps")

    def test_workflow_captures_head_before_refresh_and_forwards_explicit_path(self):
        from pathlib import Path
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/daily-public-data.yml").read_text(encoding="utf-8")
        sync = workflow.index("git checkout -B master origin/master")
        pin = workflow.index('echo "VALUCAST_REHEARSAL_MASTER=$master" >> "$GITHUB_ENV"')
        capture = workflow.index('git show "${VALUCAST_REHEARSAL_MASTER:-HEAD}:data/public/public_dynasty_snapshot.json"')
        refresh = workflow.index("- name: Refresh MLB actuals and Steamer ROS")
        build_command = 'run_daily_public_build.py --only build --previous-public-snapshot "$VALUCAST_PREVIOUS_PUBLIC_SNAPSHOT"'
        self.assertEqual(workflow.count(build_command), 2)
        self.assertLess(sync, capture)
        self.assertLess(pin, capture)
        self.assertLess(capture, refresh)
        self.assertLess(refresh, workflow.index(build_command))
        self.assertIn('git merge-base --is-ancestor "$master" HEAD', workflow[:pin])
        self.assertIn('prior="$RUNNER_TEMP/valucast-previous-public-dynasty-snapshot.json"', workflow)
        self.assertIn('chmod a-w "$prior"', workflow)

    def test_runner_empty_or_malformed_prior_fails_before_any_child(self):
        from scripts import run_daily_public_build as daily
        for raw in (b"", b"{", b"[]"):
            with patch.object(daily.Path, "read_bytes", return_value=raw), patch.object(daily.subprocess, "run") as run:
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    daily.main(["--only", "build", "--previous-public-snapshot", "immutable-prior.json"])
                run.assert_not_called()

    def test_runner_requires_prior_before_any_child_and_forwards_only_snapshot(self):
        from scripts import run_daily_public_build as daily
        with patch.object(daily.subprocess, "run") as run, patch.object(daily, "print", create=True):
            with self.assertRaises(SystemExit):
                daily.main(["--only", "build"])
            run.assert_not_called()
        steps = {"build": [("first.py",), ("scripts/build_public_dynasty_snapshot.py",), ("last.py",)]}
        with patch.object(daily, "STAGES", steps), patch.object(daily.subprocess, "run") as run, patch.object(daily, "print", create=True):
            daily.run_stage("build", previous_public_snapshot="immutable-prior.json")
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[1][1:], ("scripts/build_public_dynasty_snapshot.py", "--previous-public-snapshot", "immutable-prior.json"))
        self.assertNotIn("--previous-public-snapshot", commands[0])
        self.assertNotIn("--previous-public-snapshot", commands[2])

    def test_snapshot_cli_reads_and_validates_prior_before_input_loads(self):
        from scripts import build_public_dynasty_snapshot as snapshot
        events = []
        class StopBeforeInputs(Exception):
            pass
        def read_prior(*args):
            events.append("prior_read")
            return _bytes(_snapshot())
        def stop(*args):
            events.append("input_load")
            raise StopBeforeInputs
        with patch.object(snapshot.Path, "read_bytes", read_prior), patch.object(snapshot, "_load_json", stop):
            with self.assertRaises(StopBeforeInputs):
                snapshot.main(["--previous-public-snapshot", "immutable-prior.json"])
        self.assertEqual(events, ["prior_read", "input_load"])

    def test_snapshot_cli_rejects_missing_empty_and_malformed_prior_before_inputs(self):
        from scripts import build_public_dynasty_snapshot as snapshot
        with patch.object(snapshot, "_load_json") as load:
            with self.assertRaises(SystemExit):
                snapshot.main([])
            load.assert_not_called()
        for raw in (b"", b"{", b"[]"):
            with patch.object(snapshot.Path, "read_bytes", return_value=raw), patch.object(snapshot, "_load_json") as load:
                with self.subTest(raw=raw), self.assertRaises(ValueError):
                    snapshot.main(["--previous-public-snapshot", "immutable-prior.json"])
                load.assert_not_called()
