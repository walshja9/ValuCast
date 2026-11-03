"""Synthetic-only checks of the research Stage A harness."""
from __future__ import annotations

from collections import defaultdict
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

import numpy as np
import pytest

from projections.backtest import prospect_stage_a as stage_a
from prospects import impact_oof, model
from prospects.raw_input_builder import _service_totals
from scripts import run_prospect_stage_a as runner

SYNTHETIC_TEMP = (Path("D:/UserData/Alex/Temp/codex-stage-a-synthetic") if os.name == "nt"
                  else Path("/tmp/codex-stage-a-synthetic"))


@pytest.fixture(autouse=True)
def isolated_synthetic_environment(monkeypatch):
    for variable in ("CI", "GITHUB_ACTIONS", "RUNNER_OS"):
        monkeypatch.delenv(variable, raising=False)


@pytest.fixture
def outside_repo():
    path = SYNTHETIC_TEMP / f"test-output-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    assert not path.is_relative_to(Path(__file__).resolve().parents[1])
    return path


@pytest.fixture
def tmp_path():
    path = SYNTHETIC_TEMP / f"test-input-{uuid.uuid4().hex}"
    path.mkdir(parents=True)
    return path


@pytest.mark.parametrize("error_type,status", [(RuntimeError, "error"), (stage_a.FreezeError, "abort_hash"), (stage_a.EquivalenceError, "abort_equiv")])
def test_t18_status_line_and_exception_redaction(outside_repo, monkeypatch, capsys, error_type, status):
    def fail(*args, **kwargs):
        print("hidden stdout")
        print("hidden stderr", file=sys.stderr)
        raise error_type("private sentinel exception")

    monkeypatch.setattr(stage_a, "run_synthetic", fail)
    runner.main(["--synthetic", "--out", str(outside_repo)])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert re.fullmatch(rf"STAGE_A status={status} results_sha256=[0-9a-f]{{64}}\n", captured.out)
    assert "private" not in captured.out
    assert not (outside_repo / "results.json").exists()


def test_t18_success_status_contains_canonical_result_hash(outside_repo, monkeypatch, capsys):
    content = stage_a.canonical_bytes({"status": "partial", "synthetic": True})

    def complete(out, **options):
        print("hidden progress")
        print("hidden diagnostics", file=sys.stderr)
        (out / "results.json").write_bytes(content)
        return {"status": "partial"}

    monkeypatch.setattr(stage_a, "run_synthetic", complete)
    assert runner.main(["--synthetic", "--out", str(outside_repo)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == f"STAGE_A status=partial results_sha256={hashlib.sha256(content).hexdigest()}\n"


def test_t18_import_failure_has_one_redacted_status_line(outside_repo, monkeypatch, capsys):
    monkeypatch.setattr(runner, "stage_a", None)
    assert runner.main(["--synthetic", "--out", str(outside_repo)]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == f"STAGE_A status=error results_sha256={'0' * 64}\n"


@pytest.mark.parametrize("variable", ["GITHUB_ACTIONS", "CI", "RUNNER_OS"])
def test_t19_refuses_automation_environment(variable, outside_repo, monkeypatch):
    monkeypatch.setenv(variable, "1")
    with pytest.raises(RuntimeError):
        runner.validate_environment(outside_repo, synthetic=True)


def test_t19_rejects_repo_output_and_missing_real_optin(outside_repo, monkeypatch):
    for variable in ("GITHUB_ACTIONS", "CI", "RUNNER_OS", "VALUCAST_STAGE_A_REAL"):
        monkeypatch.delenv(variable, raising=False)
    with pytest.raises(RuntimeError):
        runner.validate_environment(Path(__file__).resolve().parents[1] / "synthetic-output", synthetic=True)
    with pytest.raises(RuntimeError):
        runner.validate_environment(outside_repo, synthetic=False)


@pytest.mark.parametrize("budget", ["nan", "inf", "0", "-1"])
def test_t19_invalid_budgets_rejected_before_dispatch(budget, outside_repo, monkeypatch, capsys):
    dispatched = []

    def unexpected(*arguments, **keywords):
        dispatched.append(True)
        raise AssertionError("invalid budget dispatched")

    monkeypatch.setattr(stage_a, "run_synthetic", unexpected)
    assert runner.main(["--synthetic", "--out", str(outside_repo), "--budget-minutes", budget]) == 1
    captured = capsys.readouterr()
    assert captured.err == ""
    assert re.fullmatch(r"STAGE_A status=error results_sha256=[0-9a-f]{64}\n", captured.out)
    assert dispatched == []


def test_t20_freeze_rejects_hashes_and_maturity():
    manifest = runner.build_freeze_manifest("a" * 64)
    runner.verify_freeze_manifest(manifest)
    for path in runner.HASHED_FILES:
        changed = copy.deepcopy(manifest)
        changed["sha256"][path] = "0" * 64
        with pytest.raises(stage_a.FreezeError):
            runner.verify_freeze_manifest(changed)
    changed = copy.deepcopy(manifest)
    changed["mature_through"] = 2020
    with pytest.raises(stage_a.FreezeError):
        runner.verify_freeze_manifest(changed)


def test_t20_manifest_commit_allows_only_manifest_change(monkeypatch):
    manifest = {"code_commit": "a" * 40}

    def git_ok(*arguments):
        return runner.MANIFEST_RELATIVE_PATH if arguments[0] == "diff" else ""

    monkeypatch.setattr(runner, "_git", git_ok)
    runner._verify_real_checkout(manifest)
    for bad_step in ("status", "diff", "merge-base"):
        def git_bad(*arguments):
            if arguments[0] == bad_step:
                if bad_step == "merge-base":
                    raise subprocess.CalledProcessError(1, ["git", "merge-base"])
                return "modified-file.py"
            return git_ok(*arguments)

        monkeypatch.setattr(runner, "_git", git_bad)
        with pytest.raises(stage_a.FreezeError):
            runner._verify_real_checkout(manifest)


def test_t01_loader_drops_sealed_rows_and_seasons(tmp_path):
    raw = stage_a.synthetic_contract()
    sealed = {int(row["mlbam_id"]) for row in raw["historical"]["rows"] if row["cohort_year"] == 2022}
    raw["historical_mlb_seasons"][f"{next(iter(sealed))}_pitcher"] = [{"year": 2023, "ip": 100, "sealed_sentinel": "SYNTHETIC_SEALED_SENTINEL"}]
    path = tmp_path / "synthetic.json"
    path.write_bytes(stage_a.canonical_bytes(raw))
    safe = stage_a.load_sealed_safe_contract(path)
    assert sealed
    assert not any(row["cohort_year"] == 2022 or int(row["mlbam_id"]) in sealed for row in safe.rows)
    assert not any(int(key.split("_")[0]) in sealed for key in safe.seasons_by_player)


@pytest.fixture
def safe(tmp_path):
    raw = stage_a.synthetic_contract(rows_per_cohort=6)
    path = tmp_path / "input.json"
    path.write_bytes(stage_a.canonical_bytes(raw))
    return stage_a.load_sealed_safe_contract(path)


def test_t02_dual_cohort_identity_removed_entirely(tmp_path):
    raw = stage_a.synthetic_contract()
    records = raw["historical"]["rows"]
    sealed = {row["mlbam_id"] for row in records if row["cohort_year"] == 2022}
    dual = {row["mlbam_id"] for row in records if row["cohort_year"] <= 2019} & sealed
    assert dual
    path = tmp_path / "dual.json"
    path.write_bytes(stage_a.canonical_bytes(raw))
    loaded = stage_a.load_sealed_safe_contract(path)
    assert not any(row["mlbam_id"] in dual for row in loaded.rows)
    assert not any(int(key.split("_")[0]) in dual for key in loaded.seasons_by_player)
    assert loaded.counts["dual_cohort_players_removed"] == len(dual)


def test_t03_later_cohorts_and_cohort_metadata_not_propagated(safe):
    assert safe.rows and max(row["cohort_year"] for row in safe.rows) <= 2019
    assert not hasattr(safe, "historical")
    assert not hasattr(safe, "cohorts")
    assert not hasattr(safe, "omitted_cohorts")


def test_t03_later_nonsealed_seasons_keep_reference_windows_without_outcomes(tmp_path):
    raw = stage_a.synthetic_contract(rows_per_cohort=6)
    late = [row for row in raw["historical"]["rows"] if row["cohort_year"] in (2020, 2021)]
    template = next(season for key, seasons in raw["historical_mlb_seasons"].items() if key.endswith("_hitter")
                    for season in seasons if "r" in season)
    for row in late:
        raw["historical_mlb_seasons"][f"{row['mlbam_id']}_hitter"] = [
            {**template, "year": row["cohort_year"] + 1}, {**template, "year": row["cohort_year"] + 6}]
    path = tmp_path / "late-references.json"
    path.write_bytes(stage_a.canonical_bytes(raw))
    loaded = stage_a.load_sealed_safe_contract(path)
    assert not any(row["cohort_year"] >= 2020 for row in loaded.rows)
    assert not any(int(key.split("_")[0]) in loaded.sealed_ids for key in loaded._reference_windows)
    windows = stage_a._window_seasons(loaded)
    for row in late:
        key = f"{row['mlbam_id']}_hitter"
        assert loaded._reference_windows[key] == row["cohort_year"]
        assert [season["year"] for season in windows[key]] == [row["cohort_year"] + 1]
        assert len(loaded.seasons_by_player[key]) == 2
    expected = model._impact_references(windows)["hitter"]
    actual = stage_a.reference_variants(loaded, "hitter")["R1"]["reference_summary"]["counts"]
    assert actual == {category: len(values) for category, values in expected.items()}


@pytest.mark.parametrize("rows,seasons", [
    ([{"cohort_year": 2022, "mlbam_id": 1}], {}),
    ([{"cohort_year": 2020, "mlbam_id": 1}], {}),
    ([{"cohort_year": 2016, "mlbam_id": 9000001}], {}),
    ([], {"9000001_pitcher": []}),
])
def test_t04_sealed_guard_rejects_all_paths(rows, seasons):
    with pytest.raises(stage_a.SealedDataError):
        stage_a.assert_no_sealed(rows, seasons, {9000001})


def test_t04_runner_redacts_sealed_abort(outside_repo, monkeypatch, capsys):
    def fail(*args, **kwargs):
        raise stage_a.SealedDataError("private sentinel")

    monkeypatch.setattr(stage_a, "run_synthetic", fail)
    runner.main(["--synthetic", "--out", str(outside_repo)])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert re.fullmatch(r"STAGE_A status=abort_sealed results_sha256=[0-9a-f]{64}\n", captured.out)
    assert not (outside_repo / "results.json").exists()


@pytest.mark.parametrize("contaminated", ["rows", "reference_windows", "current"])
def test_t04_every_stage_guards_entry(safe, contaminated):
    bad = copy.deepcopy(safe)
    if contaminated == "rows":
        bad.rows.append({"cohort_year": 2022, "mlbam_id": 9000001})
    elif contaminated == "reference_windows":
        bad._reference_windows["9000001_pitcher"] = 2016
        with pytest.raises(stage_a.SealedDataError):
            stage_a.assert_serialization_safe(bad, {})
    else:
        bad.current["hitters"].append({"mlbam_id": 9000001})
    for number in range(8):
        with pytest.raises(stage_a.SealedDataError):
            getattr(stage_a, f"stage_{number}")(bad)


def test_t07_null_stage_requires_fresh_stage_zero(safe, outside_repo, monkeypatch):
    def fail(*arguments, **keywords):
        raise stage_a.EquivalenceError()

    monkeypatch.setattr(stage_a, "engine_equivalence", fail)
    with pytest.raises(stage_a.EquivalenceError):
        stage_a.run_stages(safe, outside_repo, stage="1", reps=2, synthetic=True)
    assert not (outside_repo / "stage-1.json").exists()


def test_t05_serialized_stages_and_results_have_no_sentinels(safe, outside_repo):
    stage_a.run_stages(safe, outside_repo, reps=2, synthetic=True)
    files = [outside_repo / f"stage-{number}.json" for number in range(8)] + [outside_repo / "results.json"]
    for path in files:
        content = path.read_bytes()
        assert b"SYNTHETIC_SEALED_SENTINEL" not in content
        stage_a.assert_serialization_safe(safe, content)
    with pytest.raises(stage_a.SealedDataError):
        stage_a.assert_serialization_safe(safe, {"nested": [str(next(iter(safe.sealed_ids)))]})


def test_t06_calendar_2022_of_nonsealed_player_is_kept(safe):
    assert any(season.get("year") == 2022 for seasons in safe.seasons_by_player.values() for season in seasons)


@pytest.mark.parametrize("family", stage_a.FAMILIES)
@pytest.mark.parametrize("model_kind", ["ridge", "hurdle_ridge"])
def test_t07_engine_matches_served_vectors_and_gate(safe, family, model_kind):
    arguments = dict(stage_a.prepare_families(safe)[family])
    arguments["model_kind"] = model_kind
    rows = arguments.pop("rows")
    actual = stage_a.WalkForwardEngine(rows, **arguments).run()
    expected = model._walk_forward(rows, **arguments)
    for key in ("model_predictions", "prior_predictions", "neighbor_predictions", "canonical_neighbor_predictions", "targets"):
        np.testing.assert_allclose(actual[key], expected[key], rtol=0, atol=1e-8)
    axis = family.split("-")[0]
    assert stage_a.gate_for(actual, axis=axis, min_sample=1)["improvement_pct"] == stage_a.gate_for(expected, axis=axis, min_sample=1)["improvement_pct"]


def test_t08_neighbor_sets_and_duplicate_ties_match_served_builtin_sum():
    values = [1, 0, -1, 2, -1, -1] * 6
    train = [{"features": [0.0, float(value), float(value)], "target": float(value != 0)} for value in values]
    test = [{"features": [1e8, 0.0, 0.0]}]
    neighbors = model._fit_neighbors(train)
    x = [(value - center) / spread for value, center, spread in zip(test[0]["features"], neighbors["means"], neighbors["stds"])]
    expected = [index for _, index in sorted((sum((left - right) ** 2 for left, right in zip(row, x)), index) for index, row in enumerate(neighbors["features"]))[:25]]
    selected = stage_a.neighbor_indices(train, test)[0]
    assert selected == expected
    assert selected.index(0) < selected.index(4)
    assert sum(train[index]["target"] for index in selected) / 25 == model._neighbor_predict(neighbors, test[0]["features"])


@pytest.mark.parametrize("cell_stratified", [False, True])
def test_t09_permutations_preserve_strata_and_resume_order(safe, cell_stratified):
    rows = stage_a.prepare_families(safe)["outcome-hitter"]["rows"]
    original = copy.deepcopy(rows)
    strata = defaultdict(list)
    for index, row in enumerate(rows):
        key = (row["cohort_year"], row["level"], model._age_bucket(row["age"])) if cell_stratified else (row["cohort_year"],)
        strata[key].append(index)
    whole = [stage_a.permute_targets(rows, 2 if cell_stratified else 1, 0, 0, draw, cell_stratified=cell_stratified) for draw in range(7)]
    resumed = [stage_a.permute_targets(rows, 2 if cell_stratified else 1, 0, 0, draw, cell_stratified=cell_stratified) for draw in (4, 5, 6, 0, 1, 2, 3)]
    for draw, targets in enumerate(whole):
        for indices in strata.values():
            assert sorted(float(targets[index]) for index in indices) == sorted(rows[index]["target"] for index in indices)
        np.testing.assert_array_equal(targets, resumed[(4, 5, 6, 0, 1, 2, 3).index(draw)])
    stage_id = 2 if cell_stratified else 1
    children = np.random.SeedSequence([stage_a.SEED, stage_id, 0, 0]).spawn(5000)
    for draw in (0, 1, 250, 4999):
        expected = np.array([row["target"] for row in rows])
        rng = np.random.default_rng(children[draw])
        for indices in strata.values():
            expected[indices] = rng.permutation(expected[indices])
        np.testing.assert_array_equal(stage_a.permute_targets(rows, stage_id, 0, 0, draw, cell_stratified=cell_stratified), expected)
    assert rows == original


@pytest.mark.parametrize("model_kind", ["ridge", "hurdle_ridge"])
def test_t10_constant_and_conditional_zero_variance_match(model_kind):
    rows = []
    for year in range(2014, 2020):
        for slot in range(4):
            rows.append({"mlbam_id": (year - 2014) * 4 + slot + 1, "cohort_year": year, "level": "AA", "age": 22,
                         "features": [7.0, float(slot == 0)], "baseline_features": [7.0, float(slot == 0)], "target": 0.0 if slot == 0 else 0.5})
    expected = model._walk_forward(rows, model_kind=model_kind)
    actual = stage_a.WalkForwardEngine(rows, model_kind=model_kind).run()
    np.testing.assert_allclose(actual["model_predictions"], expected["model_predictions"], rtol=0, atol=1e-8)
    assert np.isfinite(actual["model_predictions"]).all()


def test_t11_planted_extreme_tails_and_200_dataset_calibration(tmp_path):
    path = tmp_path / "planted.json"
    path.write_bytes(stage_a.canonical_bytes(stage_a.synthetic_contract()))
    safe = stage_a.load_sealed_safe_contract(path)
    stage_a.stage_0(safe)
    for stage_id in (1, 2):
        result = stage_a.null_experiment(safe, "outcome-hitter", stage_id=stage_id, reps=99)
        assert result["p_value"] <= 0.01
    selected = stage_a.best_of_k(safe, "outcome-hitter", reps=99)
    assert selected["p_values"]["8"] <= 0.01
    calibration = stage_a.calibration_loop(datasets=200, reps=39)
    assert calibration["datasets"] == 200
    assert calibration["binomial_band"][0] <= calibration["extreme_count"] <= calibration["binomial_band"][1]
    assert calibration["within_band"] is True


def test_t12_best_of_identical_configs_and_monotone_maxima(safe):
    stage_a.stage_0(safe)
    config = stage_a.configuration_grid()[0]
    single = stage_a.best_of_k(safe, "outcome-hitter", reps=5, configurations=[config])
    repeated = stage_a.best_of_k(safe, "outcome-hitter", reps=5, configurations=[config] * 8)
    assert single["null_maxima"]["1"] == repeated["null_maxima"]["8"]
    assert single["observed_configuration_margins"] * 8 == repeated["observed_configuration_margins"]
    actual = stage_a.best_of_k(safe, "outcome-hitter", reps=5)
    assert actual["observed_best_margin"] >= max(actual["observed_configuration_margins"])
    for quantile in actual["null_maxima"]["8"]["quantiles"]:
        assert actual["null_maxima"]["8"]["quantiles"][quantile] >= actual["null_maxima"]["4"]["quantiles"][quantile]
        assert actual["null_maxima"]["4"]["quantiles"][quantile] >= actual["null_maxima"]["2"]["quantiles"][quantile]


def test_t13_purge_folds_and_training_windows(safe):
    validation = stage_a.purge_validation(safe, "outcome-hitter")
    by_id = {row["mlbam_id"]: row["cohort_year"] for row in safe.rows}
    first = min(by_id.values())
    assert validation["folds"]
    for fold in validation["folds"]:
        assert fold["test_year"] >= first + 4
        assert all(by_id[player_id] + 4 <= fold["test_year"] for player_id in fold["train_ids"])
    player = next(row for row in safe.rows if row["role"] == "hitter" and row["cohort_year"] == first)
    safe.seasons_by_player.setdefault(f"{player['mlbam_id']}_hitter", []).append(
        {"year": first + 4, "pa": 500, "r": 200, "hr": 100, "rbi": 200, "sb": 100,
         "avg": 0.5, "ops": 1.8, "so": 1})
    clipped = stage_a.purge_validation(safe, "impact-hitter", clip=True)
    references = model._impact_references(safe.seasons_by_player)
    changed = []
    for fold in clipped["folds"]:
        assert fold["max_training_season"] <= fold["test_year"]
        assert all(season["year"] <= fold["test_year"] for seasons in fold["training_seasons"].values() for season in seasons)
        for row in fold["training_rows"]:
            expected = model._impact_target(row, "hitter", fold["training_seasons"], references)
            assert row["target"] == expected
            full = model._impact_target(row, "hitter", safe.seasons_by_player, references)
            changed.append(row["target"] != full)
    assert any(changed)


def test_t14_training_only_references_match_served_and_seed_is_unspent(safe):
    from scripts.run_stage1_maturation_rerun import FORBIDDEN_SEEDS, RULE4_RESERVED_SEED

    assert stage_a.SEED == 20261103
    if stage_a.SEED in FORBIDDEN_SEEDS or stage_a.SEED in {20261001, 36061, 37083, RULE4_RESERVED_SEED, 72127}:
        raise AssertionError("seed is reserved")
    for role in ("hitter", "pitcher"):
        expected = impact_oof.fold_local_impact_oof(safe.rows, safe.seasons_by_player, role)
        actual = stage_a.reference_variants(safe, role)["R2"]["evidence"]
        assert actual == expected


def test_t15_dedup_rules_combined_rows_ties_and_service():
    seasons = {
        "11_hitter": [{"year": 2017, "pa": 80, "hr": 2}, {"year": 2017, "pa": 60, "hr": 1}, {"year": 2017, "pa": 140, "hr": 3}],
        "12_hitter": [{"year": 2017, "pa": 80, "hr": 2}, {"year": 2017, "pa": 60, "hr": 1}],
        "13_pitcher": [{"year": 2017, "ip": 20 + 1 / 3, "so": 12}, {"year": 2017, "ip": 10 + 2 / 3, "so": 8}, {"year": 2017, "ip": 31.0, "so": 20}],
        "14_hitter": [{"year": 2017, "pa": 90, "hr": 2}, {"year": 2017, "pa": 90, "hr": 7}],
        "15_hitter": [{"year": 2017, "pa": 80, "hr": 2}, {"year": 2017, "pa": 60, "hr": 1}, {"year": 2017, "pa": 140, "hr": 3.005}],
    }
    original = copy.deepcopy(seasons)
    d1, counts = stage_a.deduplicate_seasons(seasons, "D1")
    d2, _ = stage_a.deduplicate_seasons(seasons, "D2")
    assert d1["11_hitter"] == [seasons["11_hitter"][2]]
    assert d2["11_hitter"] == d1["11_hitter"]
    assert d2["13_pitcher"] == [seasons["13_pitcher"][2]]
    assert d2["12_hitter"] == seasons["12_hitter"]
    assert d2["15_hitter"] == seasons["15_hitter"]
    assert d1["14_hitter"] == [seasons["14_hitter"][0]]
    assert counts["no_combined_row"] >= 1
    assert _service_totals(seasons, 11, "hitter")["ab"] > _service_totals(d1, 11, "hitter")["ab"]
    assert seasons == original


def test_t16_small_team_stint_inflates_impact_label():
    def season(pa, strength):
        return {"year": 2017, "pa": pa, "r": strength, "hr": strength, "rbi": strength, "sb": strength,
                "avg": strength / 1000, "ops": strength / 100, "so": 200 - strength}

    seasons = {f"{index}_hitter": [season(500, 20 + index)] for index in range(1, 10)}
    seasons["15_hitter"] = [season(60, 150), season(500, 21)]
    d1, _ = stage_a.deduplicate_seasons(seasons, "D1")
    row = {"mlbam_id": 15, "cohort_year": 2016}
    assert model._impact_target(row, "hitter", seasons, model._impact_references(seasons)) > model._impact_target(row, "hitter", d1, model._impact_references(d1))


def test_t17_support_counts_recover_planted_rows():
    width = len(model._outcome_feature_names("hitter"))
    base = {"role": "hitter", "level": "AA", "age": 22, "draft_record_known": True, "draft_pick_number": 5, "plate_appearances": 100}
    training = [{**base, "features": [0.0] * width}, {**base, "plate_appearances": 200, "features": [1.0] * width}]
    board = [{**base, "features": [0.5] * width} for _ in range(5)]
    board[1]["level"] = "A"
    board[2].update(draft_record_known=False, draft_pick_number=None)
    board[3]["plate_appearances"] = 50
    board[4]["features"][:3] = [2.0, 2.0, 2.0]
    counts = stage_a.support_counts(training, board, "hitter")
    assert counts["absent_level"] == 1
    assert counts["undrafted"] == 1
    assert counts["below_sample"] == 1
    assert counts["outside_range"] == 1


def test_t17_regression_counterfactual_preserves_other_corrections():
    def one_feature_model(role, feature, weight):
        names = list(model._outcome_feature_names(role))
        weights = [0.0] * (len(names) + 1)
        weights[names.index(feature) + 1] = weight
        means, stds = [0.0] * len(names), [1.0] * len(names)
        return {"feature_names": names, "means": means,
                "prediction_model": {"model_kind": "ridge", "weights": weights, "means": means, "stds": stds}}

    current = stage_a.synthetic_contract()["current"]
    stale = {**current["hitters"][0], "source_kind": "latest_milb_history", "iso": 0.3}
    comparator = {**stale, "source_kind": "current_season", "plate_appearances": 40, "iso": 0.05, "ops": 0.4}
    hitter_model = one_feature_model("hitter", "iso", 2.0)
    assert stage_a._regression_off_score(stale, hitter_model, "hitter", {"hitters": [], "pitchers": []}) == 0.6
    assert stage_a._regression_off_score(stale, hitter_model, "hitter", {"hitters": [comparator], "pitchers": []}) == 0.4
    pitcher = {**current["pitchers"][0], "source_kind": "current_season", "innings_pitched": 10, "era": 8.0, "pick_value": 1.0}
    pitcher_model = one_feature_model("pitcher", "pick_value", 0.9)
    assert stage_a._regression_off_score(pitcher, pitcher_model, "pitcher", {"hitters": [], "pitchers": [pitcher]}) == 0.15
    healthy = {**pitcher, "era": 3.0, "whip": 1.1, "k_bb_pct": 15.0}
    assert stage_a._regression_off_score(healthy, pitcher_model, "pitcher", {"hitters": [], "pitchers": [healthy]}) == 0.9


def test_t17_selection_counterfactual_counts_board_departures(safe):
    record = safe.current["hitters"][0]
    first = {**record, "iso": None, "plate_appearances": 100}
    largest = {**record, "plate_appearances": 500}
    safe.current["hitters"] = [first, largest, *safe.current["hitters"][1:]]
    result = stage_a.stage_6(safe)
    for family in ("outcome-hitter", "impact-hitter"):
        selection = result["families"][family]["steps"]["selection"]
        assert selection["left"] == 1
        assert selection["before_n"] - selection["after_n"] == 1
        assert selection["entered"] == 0
        assert selection["rows_touched"] == 1


def test_t21_canonical_bytes_stable_across_fresh_and_resumed_runs(safe, outside_repo):
    direct, second, resumed = (outside_repo / name for name in ("direct", "second", "resumed"))
    for path in (direct, second, resumed):
        path.mkdir()
    stage_a.run_stages(safe, direct, reps=5, synthetic=True)
    stage_a.run_stages(safe, second, reps=5, synthetic=True)
    stage_a.run_stages(safe, resumed, reps=2, synthetic=True)
    stage_a.run_stages(safe, resumed, reps=5, resume=True, synthetic=True)
    for name in [*(f"stage-{number}.json" for number in range(8)), "results.json"]:
        expected = (direct / name).read_bytes()
        assert expected == stage_a.canonical_bytes(json.loads(expected))
        assert expected == (second / name).read_bytes()
        assert expected == (resumed / name).read_bytes()
    assert hashlib.sha256((direct / "results.json").read_bytes()).digest() == hashlib.sha256((resumed / "results.json").read_bytes()).digest()


def test_t22_synthetic_run_has_no_repo_writes(outside_repo, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    permitted = (root / "prospects", root / "projections" / "backtest", root / "scripts", root / "tests")

    def inventory():
        return sorted((str(path.relative_to(root)), path.stat().st_size, path.stat().st_mtime_ns)
                      for directory in permitted for path in directory.rglob("*") if path.is_file())

    writes = []
    enabled = [True]

    def record_write(event, arguments):
        if not enabled[0] or not arguments:
            return
        if event == "open":
            mode = arguments[1] if len(arguments) > 1 else ""
            flags = arguments[2] if len(arguments) > 2 else 0
            if not (isinstance(mode, str) and any(character in mode for character in "wax+")) and not flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
                return
        elif event not in {"os.mkdir", "os.rename", "os.remove", "os.rmdir"}:
            return
        if isinstance(arguments[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(arguments[0])).resolve()
            if path == root or path.is_relative_to(root):
                writes.append((event, str(path)))

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    before = inventory()
    sys.addaudithook(record_write)
    try:
        stage_a.run_synthetic(outside_repo, reps=2)
    finally:
        enabled[0] = False
    assert writes == []
    assert inventory() == before


def test_fix1_01_missing_service_fact_is_allowed_but_mismatch_aborts(tmp_path):
    raw = stage_a.synthetic_contract(rows_per_cohort=6)
    missing = raw["mlb_service"].pop(0)
    path = tmp_path / "service.json"
    path.write_bytes(stage_a.canonical_bytes(raw))
    loaded = stage_a.load_sealed_safe_contract(path)
    assert missing in loaded.mlb_service
    assert stage_a.stage_0(loaded, bootstrap_resamples=2)["equivalence"]
    raw["mlb_service"][0]["ab"] += 1
    path.write_bytes(stage_a.canonical_bytes(raw))
    with pytest.raises(ValueError, match="inconsistent service"):
        stage_a.load_sealed_safe_contract(path)


def test_fix1_02_structural_sealed_tokens_ignore_aggregates_and_hashes(safe):
    safe._sealed_ids = frozenset({123456})
    allowed = {"aggregate": 0.123456789, "float": 123456.0,
               "sha256": "a" * 28 + "123456" + "b" * 30,
               "strings": ["x123456", "123456x", "_123456_", ".123456", "123456.0", "123456_hitter"]}
    for payload in (allowed, stage_a.canonical_bytes(allowed)):
        stage_a.assert_serialization_safe(safe, payload)
    for payload in (123456, "id=123456,", {"nested": [123456]}, {"123456": 0}):
        for value in (payload, stage_a.canonical_bytes(payload)):
            with pytest.raises(stage_a.SealedDataError):
                stage_a.assert_serialization_safe(safe, value)


def test_fix1_03_current_debut_without_cohort_is_excluded_and_counted(safe):
    player = safe.current["hitters"][0]
    key = f"{player['mlbam_id']}_hitter"
    season = {"year": 2026, "pa": 80, "ab": 70, "r": 10, "hr": 2, "rbi": 8,
              "sb": 1, "avg": 0.25, "ops": 0.7, "so": 20}
    safe.seasons_by_player[key] = [season]
    original = copy.deepcopy(safe.seasons_by_player)
    variants = stage_a.reference_variants(safe, "hitter")
    assert key not in stage_a._window_seasons(safe)
    r1 = variants["R1"]["reference_summary"]
    assert r1["excluded_players_without_window"] == sum(
        name.endswith("_hitter") and name not in safe._reference_windows for name in original)
    assert r1["excluded_seasons_without_window"] == 1
    assert variants["R0"]["reference_summary"]["counts"] == {
        category: len(values) for category, values in model._impact_references(original)["hitter"].items()}
    assert safe.seasons_by_player == original


@pytest.mark.parametrize("experiment", ["null", "best_of_k"])
@pytest.mark.parametrize("changed_field", ["sha256", "thresholds", "versions"])
def test_fix1_04_resume_rejects_changed_frozen_identity(safe, outside_repo, monkeypatch, experiment, changed_field):
    stage_a.stage_0(safe, bootstrap_resamples=2)
    function = stage_a.null_experiment if experiment == "null" else stage_a.best_of_k
    options = {"stage_id": 1} if experiment == "null" else {}
    function(safe, "outcome-hitter", reps=1, out=outside_repo, **options)
    original = runner.build_freeze_manifest

    def changed_manifest(*args, **kwargs):
        manifest = original(*args, **kwargs)
        key = next(iter(manifest[changed_field]))
        manifest[changed_field][key] = "changed-synthetic-identity"
        return manifest

    monkeypatch.setattr(runner, "build_freeze_manifest", changed_manifest)
    with pytest.raises(stage_a.FreezeError):
        function(safe, "outcome-hitter", reps=2, out=outside_repo, resume=True, **options)


def test_fix1_05_undefined_ordering_draws_keep_denominator_and_are_counted(safe, monkeypatch):
    assert stage_a._p_value(0.5, [0.4, None, 0.6, None]) == 4 / 5
    assert stage_a._p_value(0.5, [None, None]) == 1.0
    assert stage_a._p_value(None, [0.5, None]) is None
    assert stage_a._p_value(0.5, []) is None
    stage_a.stage_0(safe, bootstrap_resamples=2)
    original = stage_a._ordering

    def ordering(validation, observed=False):
        result = original(validation, observed)
        if not observed:
            for metric in ("spearman_rho", "roc_auc"):
                for baseline in ("prior", "neighbor", "canonical_neighbor"):
                    result[metric]["delta_" + baseline] = None
        return result

    monkeypatch.setattr(stage_a, "_ordering", ordering)
    result = stage_a.null_experiment(safe, "outcome-hitter", stage_id=1, reps=2)
    for metric in ("spearman_rho", "roc_auc"):
        for baseline in ("prior", "neighbor", "canonical_neighbor"):
            summary = result["ordering_nulls"][metric][baseline]
            observed = result["observed"]["ordering"][metric]["delta_" + baseline]
            assert summary["p_value"] == (1.0 if observed is not None else None)
            assert summary["null"]["undefined"] == 2


def test_fix1_06_selection_off_retains_stale_current_comparator(safe, monkeypatch):
    record = safe.current["hitters"][2]
    first = {**record, "source_kind": "latest_milb_history", "plate_appearances": 100, "iso": 0.3}
    largest = {**first, "plate_appearances": 500}
    comparator = {**record, "source_kind": "current_season", "plate_appearances": 40,
                  "iso": 0.05, "ops": 0.4, "draft_pick_number": 1000, "pick_value": 0.0}
    others = [row for row in safe.current["hitters"] if row["mlbam_id"] != record["mlbam_id"]]
    safe.current["hitters"] = [first, largest, comparator, *others]
    original = copy.deepcopy(safe.current)
    _, role_models, impact_models = stage_a._board(safe)
    names = list(model._outcome_feature_names("hitter"))
    for fitted in (role_models["hitter"], impact_models["hitter"]):
        weights = [0.0] * (len(names) + 1)
        weights[names.index("iso") + 1] = 2.0
        fitted["prediction_model"] = {"model_kind": "ridge", "weights": weights,
                                      "means": [0.0] * len(names), "stds": [1.0] * len(names)}
    board = model.score_current({"current": safe.current, "mlb_service": safe.mlb_service}, role_models, impact_models)
    monkeypatch.setattr(stage_a, "_board", lambda contract: (board, role_models, impact_models))
    expected_current = {**safe.current, "hitters": [first, comparator, *others]}
    expected = model.score_current({"current": expected_current, "mlb_service": safe.mlb_service}, role_models, impact_models)
    assert any(row["mlbam_id"] == record["mlbam_id"] and "stale_current_correction" in row for row in expected)
    actual = stage_a.stage_6(safe)
    for axis in ("outcome", "impact"):
        comparison = stage_a._compare_boards(board, expected, axis, "hitter")
        selection = actual["families"][f"{axis}-hitter"]["steps"]["selection"]
        assert selection["score_change"] == comparison["score_change"]
        assert selection["score_changes_over_002"] == comparison["score_changes_over_002"]
    assert safe.current == original


@pytest.mark.parametrize("destination", ["stage-0.json", "results.json", "checkpoint-1-outcome-hitter.json", "synthetic-planted-input.json"])
def test_fix1_07_output_symlinks_are_refused_before_any_write(safe, outside_repo, monkeypatch, destination):
    target = outside_repo.parent / f"synthetic-link-target-{uuid.uuid4().hex}.json"
    sentinel = stage_a.canonical_bytes({"identity": {}, "draws": []})
    target.write_bytes(sentinel)
    link = outside_repo / destination
    try:
        link.symlink_to(target)
    except OSError:
        # Windows may deny symlink creation; exercise the destination check without ACL changes.
        link.write_bytes(sentinel)
        original = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda path: path == link or original(path))
    with pytest.raises(ValueError):
        if destination.startswith("checkpoint"):
            stage_a._checkpoint(safe, outside_repo, 1, "outcome-hitter", [], {})
        elif destination.startswith("synthetic"):
            stage_a.run_synthetic(outside_repo, reps=1)
        else:
            stage_a._write_results(safe, outside_repo, {0: {}}, {"status": "partial"})
    assert target.read_bytes() == sentinel
    if destination == "results.json":
        assert not (outside_repo / "stage-0.json").exists()
    if destination.startswith("checkpoint"):
        with pytest.raises(ValueError):
            stage_a._resume_draws(safe, outside_repo, 1, "outcome-hitter", {}, True)


def test_fix1_extra_support_metadata_comes_from_the_actual_training_row(safe):
    expected = stage_a.stage_6(safe)
    valid = next(row for row in safe.rows if row["role"] == "hitter")
    safe.rows.insert(0, {**valid, "iso": None, "plate_appearances": 1,
                         "draft_record_known": False, "draft_pick_number": None})
    actual = stage_a.stage_6(safe)
    for family in ("outcome-hitter", "impact-hitter"):
        assert actual["families"][family]["support"] == expected["families"][family]["support"]


def test_fix1_08_served_environment_is_frozen_and_defaults_required(monkeypatch):
    monkeypatch.delenv("VALUCAST_POOLED_SHADOW", raising=False)
    manifest = runner.build_freeze_manifest("a" * 64)
    assert manifest["environment_flags"] == {"VALUCAST_POOLED_SHADOW": True}
    runner.verify_freeze_manifest(manifest)
    monkeypatch.setenv("VALUCAST_POOLED_SHADOW", "0")
    with pytest.raises(stage_a.FreezeError):
        runner.verify_freeze_manifest(manifest)


def test_fix1_09_score_change_uses_served_precision():
    def board(score):
        return [{"mlbam_id": 800001, "role": "hitter", "expected_outcome_score": score}]

    for before, after, expected in ((0.18, 0.20, 0), (0.20, 0.18, 0), (0.18, 0.2001, 1), (0.18, 0.20004, 0)):
        comparison = stage_a._compare_boards(board(before), board(after), "outcome", "hitter")
        assert comparison["score_changes_over_002"] == expected
