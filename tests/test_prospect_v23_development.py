import copy
import importlib
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


RUNNER = "scripts.build_prospect_v23_candidate"
HAS_RUNNER = (Path(__file__).resolve().parents[1] / "scripts" / "build_prospect_v23_candidate.py").exists()
requires_runner = pytest.mark.skipif(not HAS_RUNNER, reason="runner import is the RED gate")


def _runner():
    return importlib.import_module(RUNNER)


def _exact_registration(candidate, runtime, monkeypatch=None):
    implementation, empty_hash = "e" * 40, candidate.canonical_sha256([])
    object_hash = candidate.canonical_sha256(["a" * 40])
    history = {
        "scope_tip": implementation, "standalone_pattern": "",
        "inventory_schema": "git_blob_path_offset_v1", "object_count": 1,
        "sorted_object_ids_sha256": object_hash, "inventory_entry_count": 0,
        "inventory_sha256": empty_hash,
        "classification_schema": "git_blob_path_offset_line_sha256_classification_v1",
        "classifications": [], "classification_sha256": empty_hash,
        "result_artifact_entries": [], "runner_invocation_entries": [],
    }

    def predecessor(name, seed):
        evidence = {**history, "standalone_pattern": rf"(^|[^0-9]){seed}([^0-9]|$)"}
        return {
            "plan_path": f"plans/{name}.md", "track": "model",
            "transition": "superseded_by_plan_038", "held_seed": seed,
            "seed_status": "retired_unspent_never_execute",
            "pre_transition_blob": "1" * 40, "post_transition_blob": "2" * 40,
            "append_only_prefix_bytes": 1, "history_evidence": evidence,
        }

    hygiene = {
        "token": 39017, "pre_design_tip": "d" * 40,
        "pre_design": {"object_count": 1, "sorted_object_ids_sha256": object_hash, "match_count": 0},
        "post_design": {"scope_tip": implementation, "entry_count": 0, "inventory_sha256": empty_hash, "unexpected_path_count": 0, "allowed_paths": ["runner.py"]},
        "structured_seed_fields": {"inventory_sha256": empty_hash, "pre_design_match_count": 0, "forbidden_held_spent_reserved_membership": False},
        "post_registration_policy": {"allowed_paths": []},
    }
    identities = {
        str(year): {
            role: {"count": 1, "sha256": str(index) * 64}
            for index, role in enumerate(("hitter", "pitcher"), 1)
        }
        for year in (2018, 2019, 2021)
    }
    registration = {
        "schema": "synthetic",
        "candidate": {"implementation_commit": implementation, "map": {"parameter_order": ["a", "b"]}},
        "predecessors": {
            "plan_031": predecessor("031", 31013),
            "plan_034": predecessor("034", 34021),
            "plan_index": {
                "plan_path": "plans/README.md",
                "transition": "update_plan_031_plan_034_model_track_status_and_add_plan_038",
                "pre_transition_blob": "1" * 40, "post_transition_blob": "2" * 40,
            },
        },
        "inputs": {candidate.CANONICAL_READ_PATHS[1]: {"git_blob": "3" * 40, "canonical_sha256": "4" * 64, "internal_field": "input_sha256", "internal_sha256": "5" * 64}},
        "sources": {"prospects/rank_v2.py": {"git_blob": "1" * 40, "normalized_sha256": "2" * 64}},
        "folds": {"order": [2018, 2019, 2021], "identity_receipts": identities},
        "comparators": {"product": {"sort": ["score"]}},
        "metrics": {"per_fold_gates": [{"operator": "<"}]},
        "bootstrap": {"replicates": 10_000, "seed_hygiene": hygiene},
        "state_machine": {"cli": [""]}, "outputs": {"receipt": "receipt.json"},
        "forbidden_inputs": ["market_rank"], "forbidden_paths": ["app.py"],
        "feeds_live_rank": False, "feeds_value": False, "runtime": runtime,
        "execution": {"sha_semantics": {"recovery": "bound"}},
    }
    registration["artifact_sha256"] = candidate.canonical_sha256(registration)
    if monkeypatch is not None:
        static, _dynamic = candidate._registration_static_view(registration)
        monkeypatch.setattr(candidate, "_REGISTRATION_CONTRACT", {
            **candidate._REGISTRATION_CONTRACT,
            "static_sha256": candidate.canonical_sha256(static),
        })
    return registration
def _terminal_result(candidate, *, qualified: bool, map_sha: str | None = None):
    metrics = {
        "candidate_mae": 0.125, "control_mae": 0.25, "candidate_control_mae_delta": -0.125,
        "candidate_concordance": 0.75, "control_concordance": 0.5, "product_concordance": 0.25,
        "candidate_control_concordance_delta": 0.25, "candidate_product_concordance_delta": 0.5,
        "candidate_top25_target_sum": 10.0, "control_top25_target_sum": 9.0, "product_top25_target_sum": 8.0,
    }
    if qualified:
        fold = {
            "status": "completed", "failure_stage": None,
            "identity_count_by_role": {"hitter": 1, "pitcher": 1},
            "identity_sha256_by_role": {"hitter": "a" * 64, "pitcher": "b" * 64}, "target_sha256": "c" * 64,
            "metrics": metrics, "gates": {name: True for name in candidate.FOLD_GATE_ORDER},
            "structural_checks": {"identity_sets_equal": True, "targets_equal": True, "candidate_map_valid": True, "control_map_valid": True, "product_rank_reproduced": True, "top25_complete": True},
            "failed_gates": [], "failed_structural": [],
        }
        bootstrap_metrics = {
            "candidate_control_mae_delta": {"point": -0.125, "lower": -0.2, "upper": -0.05, "valid_replicates": 10_000, "gate_passed": True},
            "candidate_control_concordance_delta": {"point": 0.25, "lower": 0.05, "upper": 0.3, "valid_replicates": 10_000, "gate_passed": True},
            "candidate_product_concordance_delta": {"point": 0.5, "lower": 0.05, "upper": 0.4, "valid_replicates": 10_000, "gate_passed": True},
        }
        bootstrap = {"status": "completed", "seed": 39017, "replicates": 10_000, "minimum_valid_replicates": candidate.BOOTSTRAP_MINIMUM, "interval": {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"}, "sample_plan_sha256": "d" * 64, "metrics": bootstrap_metrics}
        pooled = {"attempted": True, "status": "validated", "row_count": 2, "training_rows_sha256": "e" * 64, "map_artifact_sha256": map_sha}
        failed = ([], [], [])
    else:
        fold = {
            "status": "structural_failure", "failure_stage": "identity_alignment",
            "identity_count_by_role": None, "identity_sha256_by_role": None, "target_sha256": None,
            "metrics": {name: None for name in metrics}, "gates": {name: None for name in candidate.FOLD_GATE_ORDER},
            "structural_checks": {"identity_sets_equal": False, "targets_equal": None, "candidate_map_valid": None, "control_map_valid": None, "product_rank_reproduced": None, "top25_complete": None},
            "failed_gates": [], "failed_structural": ["identity_alignment"],
        }
        bootstrap = candidate._not_attempted_bootstrap()
        pooled = {"attempted": False, "status": "not_attempted_qualification_failure", "row_count": 0, "training_rows_sha256": None, "map_artifact_sha256": None}
        failed = (list(candidate.DEVELOPMENT_FOLDS), [], [f"{year}:identity_alignment" for year in candidate.DEVELOPMENT_FOLDS])
    return {"fold_order": list(candidate.DEVELOPMENT_FOLDS), "folds": {str(year): copy.deepcopy(fold) for year in candidate.DEVELOPMENT_FOLDS}, "bootstrap": bootstrap, "failed_folds": failed[0], "failed_bootstrap": failed[1], "failed_structural": failed[2], "pooled_fit": pooled}


def _failed_gate_fold(completed):
    failed = copy.deepcopy(completed)
    failed["metrics"].update(candidate_mae=2.0, control_mae=1.0, candidate_control_mae_delta=1.0)
    failed["gates"]["candidate_control_mae"] = False
    failed["failed_gates"] = ["candidate_control_mae"]
    return failed


def test_fold_runner_import_is_the_registered_red_gate():
    _runner()


@requires_runner
def test_protocol_refuses_missing_registration_before_reservation(monkeypatch, tmp_path):
    """The canonical wrapper never reserves or opens outcome data without registration."""
    candidate = _runner()
    receipt = tmp_path / "data" / "validation" / "receipt.json"
    opened = []
    monkeypatch.setattr(candidate, "RECEIPT_PATH", receipt)
    monkeypatch.setattr(candidate, "CALIBRATOR_PATH", tmp_path / "data" / "models" / "map.json")
    monkeypatch.setattr(candidate, "REGISTRATION_PATH", tmp_path / "missing-registration.json")
    monkeypatch.setattr(candidate, "SPEND_TOKEN_PATH", tmp_path / "common" / "spent.json")
    monkeypatch.setattr(candidate, "_common_lock_path", lambda: tmp_path / "common" / "lock")
    monkeypatch.setattr(candidate, "_load_json", lambda path, **_kwargs: opened.append(path) or {})
    monkeypatch.setattr(candidate, "_head", lambda: "a" * 40)
    monkeypatch.setenv("VALUCAST_V23_APPROVED_EXECUTION_SHA", "a" * 40)

    assert candidate.run([]) == 2
    assert not receipt.exists()
    assert opened == []


@requires_runner
def test_committed_static_registration_preimage_matches_production_hash():
    candidate = _runner()
    path = Path(__file__).parent / "fixtures" / "prospect_v23_registration_static_preimage.json"
    preimage = json.loads(path.read_text(encoding="utf-8"))

    assert candidate.canonical_sha256(preimage) == candidate._REGISTRATION_CONTRACT["static_sha256"]
    assert path.relative_to(Path(__file__).parents[1]).as_posix() in preimage[
        "bootstrap"
    ]["seed_hygiene"]["post_design"]["allowed_paths"]
    assert Path(__file__).relative_to(Path(__file__).parents[1]).as_posix() in preimage[
        "bootstrap"
    ]["seed_hygiene"]["post_registration_policy"]["allowed_paths"]


@requires_runner
def test_committed_registration_matches_plan_038_and_predecessor_transitions(
    monkeypatch,
):
    candidate = _runner()
    root = Path(__file__).parents[1]
    registration_path = (
        root / "data/validation/valucast_prospect_rank_v2_3_registration.json"
    )
    plan_path = root / "plans/038-prospect-vnext-phase-a.md"
    registration = json.loads(registration_path.read_text(encoding="utf-8"))
    plan = plan_path.read_text(encoding="utf-8")
    fenced = plan.split(
        "<!-- prospect-vnext-phase-a-registration:start -->\n```json\n", 1
    )[1].split("\n```\n<!-- prospect-vnext-phase-a-registration:end -->", 1)[0]

    assert fenced + "\n" == registration_path.read_text(encoding="utf-8")
    assert json.loads(fenced) == registration
    foreign_runtime = candidate._runtime_tuple()
    if foreign_runtime == registration["runtime"]:
        foreign_runtime = {**foreign_runtime, "serial": foreign_runtime["serial"] + 1}
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: foreign_runtime)
    with pytest.raises(candidate.ProtocolError, match="runtime does not match"):
        candidate._registration(registration)
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: registration["runtime"])
    assert candidate._registration(registration) == registration
    static, _dynamic = candidate._registration_static_view(registration)
    static_path = (
        Path(__file__).parent
        / "fixtures/prospect_v23_registration_static_preimage.json"
    )
    assert static == json.loads(static_path.read_text(encoding="utf-8"))

    for name in ("plan_031", "plan_034"):
        predecessor = registration["predecessors"][name]
        before = candidate._git_blob_bytes(predecessor["pre_transition_blob"])
        current = (root / predecessor["plan_path"]).read_bytes()
        assert len(before) == predecessor["append_only_prefix_bytes"]
        assert current.startswith(before)
        assert candidate._git_blob(predecessor["plan_path"], root / predecessor["plan_path"]) == predecessor["post_transition_blob"]

    historical_034 = candidate._git_blob_bytes(
        registration["predecessors"]["plan_034"]["pre_transition_blob"]
    ).decode("utf-8")
    historical_registration = json.loads(
        historical_034.split(
            "<!-- post-2026-challenger-registration:start -->\n```json\n", 1
        )[1].split("\n```\n<!-- post-2026-challenger-registration:end -->", 1)[0]
    )
    for name, registered in registration["predecessors"]["plan_034"][
        "active_tracks"
    ].items():
        value = historical_registration["decision_tracks"][name]
        assert registered == {
            "value": value,
            "canonical_sha256": candidate.canonical_sha256(value),
        }


@requires_runner
def test_committed_registration_passes_dynamic_verification():
    candidate = _runner()
    path = (
        Path(__file__).parents[1]
        / "data/validation/valucast_prospect_rank_v2_3_registration.json"
    )
    candidate._verify_dynamic_registration(json.loads(path.read_text(encoding="utf-8")))


@requires_runner
def test_registration_rejects_every_resealed_nested_contract_mutation(monkeypatch):
    candidate = _runner()
    runtime = {"runtime": "synthetic"}
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: runtime)
    valid = _exact_registration(candidate, runtime, monkeypatch)
    assert candidate._registration(valid) == valid

    mutations = {
        "candidate": lambda row: row["candidate"]["map"]["parameter_order"].reverse(),
        "predecessors": lambda row: row["predecessors"]["plan_031"].__setitem__("track", "changed"),
        "plan_index": lambda row: row["predecessors"]["plan_index"].__setitem__("transition", "changed"),
        "folds": lambda row: row["folds"]["order"].reverse(),
        "comparators": lambda row: row["comparators"]["product"]["sort"].pop(),
        "metrics": lambda row: row["metrics"]["per_fold_gates"][0].__setitem__("operator", "<="),
        "bootstrap": lambda row: row["bootstrap"].__setitem__("replicates", 9_999),
        "inputs": lambda row: row["inputs"][candidate.CANONICAL_READ_PATHS[1]].__setitem__("canonical_sha256", "f" * 64),
        "sources": lambda row: row["sources"].update({"extra.py": copy.deepcopy(next(iter(row["sources"].values())))}),
        "state_machine": lambda row: row["state_machine"]["cli"].pop(),
        "outputs": lambda row: row["outputs"].__setitem__("receipt", "wrong.json"),
        "runtime": lambda row: row["runtime"].__setitem__("runtime", "changed"),
        "execution": lambda row: row["execution"]["sha_semantics"].pop("recovery"),
        "forbidden_inputs": lambda row: row["forbidden_inputs"].pop(),
        "forbidden_paths": lambda row: row["forbidden_paths"].pop(),
    }
    for label, mutate in mutations.items():
        changed = copy.deepcopy(valid)
        mutate(changed)
        changed["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in changed.items() if key != "artifact_sha256"})
        with pytest.raises(candidate.ProtocolError, match="registration"):
            candidate._registration(changed)


@requires_runner
def test_dynamic_source_binding_rejects_altered_hash_or_implementation(monkeypatch):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})

    def git_run(args, **_kwargs):
        return subprocess.CompletedProcess(args, int("merge-base" in args and "f" * 40 in args), stdout="")

    monkeypatch.setattr(candidate.subprocess, "run", git_run)
    monkeypatch.setattr(candidate, "_git_blob_at", lambda *_args: "1" * 40)
    monkeypatch.setattr(candidate, "_git_blob", lambda *_args: "1" * 40)
    monkeypatch.setattr(candidate, "_normalized_source_sha256", lambda *_args: "2" * 64)
    assert candidate._verify_source_bindings(registration) == "e" * 40
    changed = copy.deepcopy(registration)
    changed["sources"]["prospects/rank_v2.py"]["git_blob"] = "f" * 40
    with pytest.raises(candidate.ProtocolError, match="source binding"):
        candidate._verify_source_bindings(changed)
    changed = copy.deepcopy(registration)
    changed["candidate"]["implementation_commit"] = "f" * 40
    with pytest.raises(candidate.ProtocolError, match="implementation commit"):
        candidate._verify_source_bindings(changed)


@requires_runner
def test_dynamic_source_binding_allows_unrelated_merge_parent_changes(monkeypatch):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})

    def git_run(args, **_kwargs):
        if args[:3] == ["git", "merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args, 0, stdout="")
        if args[:3] == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(
                args, 0, stdout="data/actuals/current.json\n"
            )
        raise AssertionError(args)

    monkeypatch.setattr(candidate.subprocess, "run", git_run)
    monkeypatch.setattr(candidate, "_git_blob_at", lambda *_args: "1" * 40)
    monkeypatch.setattr(candidate, "_git_blob", lambda *_args: "1" * 40)
    monkeypatch.setattr(candidate, "_normalized_source_sha256", lambda *_args: "2" * 64)

    assert candidate._verify_source_bindings(registration) == "e" * 40


@requires_runner
def test_dynamic_source_binding_rejects_unregistered_python_drift(monkeypatch):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})

    def git_run(args, **_kwargs):
        if args[:3] == ["git", "merge-base", "--is-ancestor"]:
            return subprocess.CompletedProcess(args, 0, stdout="")
        if args[:3] == ["git", "diff", "--name-only"]:
            return subprocess.CompletedProcess(args, 0, stdout="scripts/json.py\n")
        raise AssertionError(args)

    monkeypatch.setattr(candidate.subprocess, "run", git_run)
    monkeypatch.setattr(candidate, "_git_blob_at", lambda *_args: "1" * 40)
    monkeypatch.setattr(candidate, "_git_blob", lambda *_args: "1" * 40)
    monkeypatch.setattr(candidate, "_normalized_source_sha256", lambda *_args: "2" * 64)

    with pytest.raises(candidate.ProtocolError, match="post-implementation code"):
        candidate._verify_source_bindings(registration)


@requires_runner
def test_dynamic_predecessor_evidence_rejects_altered_inventory(monkeypatch, tmp_path):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})
    monkeypatch.setattr(candidate, "ROOT", tmp_path)
    for name in ("plan_031", "plan_034"):
        path = tmp_path / registration["predecessors"][name]["plan_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    index_path = tmp_path / registration["predecessors"]["plan_index"]["plan_path"]
    index_path.write_bytes(b"index")
    monkeypatch.setattr(candidate, "_git_object_ids", lambda _tip: ["a" * 40])
    monkeypatch.setattr(candidate, "_git_blob_inventory", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(candidate, "_git_blob_bytes", lambda _blob: b"x")
    monkeypatch.setattr(candidate, "_git_blob_at", lambda revision, _path: "1" * 40 if revision == "e" * 40 else "2" * 40)
    monkeypatch.setattr(candidate, "_git_blob", lambda *_args: "2" * 40)
    candidate._verify_predecessor_bindings(registration, "e" * 40)
    registration["predecessors"]["plan_031"]["history_evidence"]["inventory_sha256"] = "f" * 64
    with pytest.raises(candidate.ProtocolError, match="history evidence"):
        candidate._verify_predecessor_bindings(registration, "e" * 40)
    registration["predecessors"]["plan_031"]["history_evidence"]["classification_sha256"] = "f" * 64
    _static, dynamic = candidate._registration_static_view(registration)
    with pytest.raises(candidate.ProtocolError, match="classifications"):
        candidate._validate_dynamic_fields(dynamic)


@requires_runner
def test_plan_index_blobs_are_dynamic_and_mechanically_verified(monkeypatch, tmp_path):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})
    static, dynamic = candidate._registration_static_view(registration)
    index = static["predecessors"]["plan_index"]
    assert index["pre_transition_blob"] is None
    assert index["post_transition_blob"] is None
    candidate._validate_dynamic_fields(dynamic)

    monkeypatch.setattr(candidate, "ROOT", tmp_path)
    for name in ("plan_031", "plan_034"):
        predecessor = tmp_path / registration["predecessors"][name]["plan_path"]
        predecessor.parent.mkdir(parents=True, exist_ok=True)
        predecessor.write_bytes(b"x")
    path = tmp_path / registration["predecessors"]["plan_index"]["plan_path"]
    path.write_bytes(b"index")
    monkeypatch.setattr(candidate, "_git_object_ids", lambda _tip: ["a" * 40])
    monkeypatch.setattr(candidate, "_git_blob_inventory", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(candidate, "_git_blob_bytes", lambda _blob: b"x")
    monkeypatch.setattr(candidate, "_git_blob_at", lambda revision, _path: "1" * 40 if revision == "e" * 40 else "2" * 40)
    monkeypatch.setattr(candidate, "_git_blob", lambda *_args: "2" * 40)
    candidate._verify_predecessor_bindings(registration, "e" * 40)

    registration["predecessors"]["plan_index"]["post_transition_blob"] = "f" * 40
    with pytest.raises(candidate.ProtocolError, match="plan index"):
        candidate._verify_predecessor_bindings(registration, "e" * 40)


@requires_runner
def test_dynamic_seed_evidence_rejects_altered_inventory(monkeypatch):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})
    monkeypatch.setattr(candidate, "_git_object_ids", lambda _tip: ["a" * 40])
    monkeypatch.setattr(candidate, "_git_blob_inventory", lambda *_args, **_kwargs: ([], []))
    candidate._verify_seed_hygiene(registration, "e" * 40)
    registration["bootstrap"]["seed_hygiene"]["post_design"]["inventory_sha256"] = "f" * 64
    with pytest.raises(candidate.ProtocolError, match="seed-hygiene"):
        candidate._verify_seed_hygiene(registration, "e" * 40)


@requires_runner
def test_seed_hygiene_uses_the_reviewed_structured_inventory(monkeypatch):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})
    hygiene = registration["bootstrap"]["seed_hygiene"]
    row = ["b" * 40, "runner.py", 7, "c" * 64]
    hygiene["post_design"].update(
        entry_count=1,
        inventory_sha256=candidate.canonical_sha256([row]),
    )
    hygiene["structured_seed_fields"]["inventory_sha256"] = candidate.canonical_sha256([row])

    monkeypatch.setattr(candidate, "_git_object_ids", lambda _tip: ["a" * 40])
    monkeypatch.setattr(
        candidate,
        "_git_blob_inventory",
        lambda tip, *_args, **_kwargs: ([row], [row]) if tip == "e" * 40 else ([], []),
    )
    candidate._verify_seed_hygiene(registration, "e" * 40)

    changed = [*row[:2], row[2] + 1, row[3]]
    monkeypatch.setattr(
        candidate,
        "_git_blob_inventory",
        lambda tip, *_args, **_kwargs: ([row], [changed]) if tip == "e" * 40 else ([], []),
    )
    with pytest.raises(candidate.ProtocolError, match="seed-hygiene"):
        candidate._verify_seed_hygiene(registration, "e" * 40)


@requires_runner
def test_seed_hygiene_allows_only_exact_reviewed_superseded_rows(monkeypatch):
    candidate = _runner()
    registration = _exact_registration(candidate, {"runtime": "synthetic"})
    reviewed = [
        "660d69986baa81a259f0794df28d712da9be1952",
        "tests/fixtures/prospect_v23_registration_static_preimage.json",
        15868,
        "ce1bd7ec0b6feed55d327eefa8d7d80fcf304fe4f64c6918d042513d4c6ae127",
    ]
    monkeypatch.setattr(candidate, "_git_object_ids", lambda _tip: ["a" * 40])
    monkeypatch.setattr(
        candidate,
        "_git_blob_inventory",
        lambda tip, *_args, **_kwargs: ([], [])
        if tip == "e" * 40
        else ([reviewed], []),
    )

    candidate._verify_seed_hygiene(registration, "e" * 40)

    changed = [*reviewed[:2], reviewed[2] + 1, reviewed[3]]
    monkeypatch.setattr(
        candidate,
        "_git_blob_inventory",
        lambda tip, *_args, **_kwargs: ([], [])
        if tip == "e" * 40
        else ([changed], []),
    )
    with pytest.raises(candidate.ProtocolError, match="seed occurrence"):
        candidate._verify_seed_hygiene(registration, "e" * 40)


@requires_runner
def test_identity_receipt_hashes_exact_sorted_mlbam_role_pairs():
    candidate = _runner()
    rows = [{"mlbam_id": 2, "role": "hitter"}, {"mlbam_id": 1, "role": "hitter"}, {"mlbam_id": 3, "role": "pitcher"}]
    counts, hashes = candidate._identity_provenance(rows)
    assert counts == {"hitter": 2, "pitcher": 1}
    assert hashes == {"hitter": candidate.canonical_sha256([[1, "hitter"], [2, "hitter"]]), "pitcher": candidate.canonical_sha256([[3, "pitcher"]])}


@requires_runner
@pytest.mark.parametrize("year", ["2018", "2019", "2021"])
@pytest.mark.parametrize("role", ["hitter", "pitcher"])
@pytest.mark.parametrize("field", ["count", "sha256"])
def test_registration_rejects_each_identity_cell_literal(monkeypatch, year, role, field):
    candidate = _runner()
    runtime = {"runtime": "synthetic"}
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: runtime)
    registration = _exact_registration(candidate, runtime, monkeypatch)
    receipt = registration["folds"]["identity_receipts"][year][role]
    receipt[field] = receipt[field] + 1 if field == "count" else "f" * 64
    registration["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in registration.items() if key != "artifact_sha256"})
    with pytest.raises(candidate.ProtocolError, match="registration"):
        candidate._registration(registration)


def _bypass_registered_identities(monkeypatch, candidate):
    monkeypatch.setattr(candidate, "_validate_registered_identities", lambda *_args: None)


@requires_runner
def test_registered_identity_receipts_fail_before_any_map_or_metric(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()
    receipts = {}
    for year in candidate.DEVELOPMENT_FOLDS:
        receipts[str(year)] = {
            role: {"count": len(pairs), "sha256": candidate.canonical_sha256(pairs)}
            for role in candidate.ROLES
            for pairs in [sorted([[int(row["mlbam_id"]), str(row["role"])] for row in ladders[year][f"candidate_{role}s"]])]
        }
    registration = {"folds": {"identity_receipts": receipts}}
    registration["folds"]["identity_receipts"]["2019"]["pitcher"]["sha256"] = "f" * 64
    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: ladders)
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda *_args: pytest.fail("map or metric stage reached"))

    with pytest.raises(ValueError, match="registered identity"):
        candidate.build_development_artifacts({}, {}, registration)


@requires_runner
def test_terminal_receipt_schema_and_seal_rejects_undeclared_fields(monkeypatch):
    candidate = _runner()
    runtime = {"test": "runtime"}
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: runtime)
    receipt = candidate._receipt(registration, "a" * 40, "failed", "completed", spend_token_sha256="c" * 64, result=_terminal_result(candidate, qualified=False), map_artifact_sha256=None)

    assert candidate._validate_receipt(receipt) == receipt
    malformed = {**receipt, "unexpected": True}
    malformed["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in malformed.items() if key != "artifact_sha256"})
    with pytest.raises(candidate.ProtocolError, match="fields"):
        candidate._validate_receipt(malformed)


@requires_runner
def test_completed_receipt_rejects_empty_result(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    receipt = candidate._receipt(registration, "a" * 40, "failed", "completed", spend_token_sha256="c" * 64, result={}, map_artifact_sha256=None)

    with pytest.raises(candidate.ProtocolError, match="result"):
        candidate._validate_receipt(receipt)


@requires_runner
def test_completed_receipt_rejects_nested_result_schema_and_structural_state(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    base = candidate._receipt(registration, "a" * 40, "failed", "completed", spend_token_sha256="c" * 64, result=_terminal_result(candidate, qualified=False), map_artifact_sha256=None)
    variants = []
    missing = copy.deepcopy(base)
    missing["result"].pop("bootstrap")
    variants.append(missing)
    extra = copy.deepcopy(base)
    extra["result"]["unexpected"] = None
    variants.append(extra)
    fold_missing = copy.deepcopy(base)
    fold_missing["result"]["folds"]["2018"].pop("metrics")
    variants.append(fold_missing)
    bootstrap_extra = copy.deepcopy(base)
    bootstrap_extra["result"]["bootstrap"]["unexpected"] = True
    variants.append(bootstrap_extra)
    bootstrap_metric_extra = copy.deepcopy(base)
    bootstrap_metric_extra["result"]["bootstrap"]["metrics"][candidate.BOOTSTRAP_METRICS[0]]["unexpected"] = True
    variants.append(bootstrap_metric_extra)
    invalid_null_order = copy.deepcopy(base)
    invalid_null_order["result"]["folds"]["2018"]["status"] = "completed"
    invalid_null_order["result"]["folds"]["2018"]["failure_stage"] = None
    invalid_null_order["result"]["folds"]["2018"]["failed_structural"] = []
    variants.append(invalid_null_order)
    invalid_pooled = copy.deepcopy(base)
    invalid_pooled["result"]["pooled_fit"]["status"] = "validated"
    variants.append(invalid_pooled)
    for receipt in variants:
        receipt["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in receipt.items() if key != "artifact_sha256"})
        with pytest.raises(candidate.ProtocolError):
            candidate._validate_receipt(receipt)


@requires_runner
def test_completed_receipt_rejects_semantic_result_contradictions(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    valid = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    variants = []
    wrong_delta = copy.deepcopy(valid)
    wrong_delta["folds"]["2018"]["metrics"]["candidate_control_mae_delta"] = 0.0
    variants.append(("qualified", wrong_delta, "f" * 64))
    structural_in_qualified = copy.deepcopy(valid)
    structural_in_qualified["folds"]["2018"] = _terminal_result(candidate, qualified=False)["folds"]["2018"]
    variants.append(("qualified", structural_in_qualified, "f" * 64))
    too_few_bootstraps = copy.deepcopy(valid)
    too_few_bootstraps["bootstrap"]["metrics"]["candidate_control_mae_delta"]["valid_replicates"] = 1
    variants.append(("qualified", too_few_bootstraps, "f" * 64))
    impossible_pooled = copy.deepcopy(valid)
    impossible_pooled["pooled_fit"].update(attempted=False, row_count=0, training_rows_sha256=None)
    variants.append(("qualified", impossible_pooled, "f" * 64))
    missing_provenance = copy.deepcopy(valid)
    missing_provenance["folds"]["2018"].update(identity_count_by_role=None, identity_sha256_by_role=None, target_sha256=None)
    variants.append(("qualified", missing_provenance, "f" * 64))
    unrun_bootstrap = _terminal_result(candidate, qualified=False)
    unrun_bootstrap["folds"] = copy.deepcopy(valid["folds"])
    variants.append(("failed", unrun_bootstrap, None))
    contradictory_failure_lists = _terminal_result(candidate, qualified=False)
    contradictory_failure_lists.update(failed_folds=[], failed_bootstrap=[], failed_structural=[])
    variants.append(("failed", contradictory_failure_lists, None))
    for status, result, map_sha in variants:
        receipt = candidate._receipt(registration, "a" * 40, status, "completed", spend_token_sha256="c" * 64, result=result, map_artifact_sha256=map_sha)
        with pytest.raises(candidate.ProtocolError):
            candidate._validate_receipt(receipt)


@requires_runner
def test_structural_top25_receipt_preserves_only_valid_upstream_arithmetic(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    result = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    fold = result["folds"]["2018"]
    fold.update(status="structural_failure", failure_stage="top25_contract", failed_structural=["top25_contract"])
    for name in ("candidate_top25_target_sum", "control_top25_target_sum", "product_top25_target_sum"):
        fold["metrics"][name] = None
    for name in candidate.FOLD_GATE_ORDER[4:]:
        fold["gates"][name] = None
    fold["structural_checks"]["top25_complete"] = False
    result["folds"] = {str(year): copy.deepcopy(fold) for year in candidate.DEVELOPMENT_FOLDS}
    result.update(
        bootstrap=candidate._not_attempted_bootstrap(),
        failed_folds=list(candidate.DEVELOPMENT_FOLDS),
        failed_bootstrap=[],
        failed_structural=[f"{year}:top25_contract" for year in candidate.DEVELOPMENT_FOLDS],
        pooled_fit={"attempted": False, "status": "not_attempted_qualification_failure", "row_count": 0, "training_rows_sha256": None, "map_artifact_sha256": None},
    )
    result["folds"]["2018"]["metrics"]["candidate_control_mae_delta"] = -0.1
    receipt = candidate._receipt(registration, "a" * 40, "failed", "completed", spend_token_sha256="c" * 64, result=result, map_artifact_sha256=None)

    with pytest.raises(candidate.ProtocolError):
        candidate._validate_receipt(receipt)


@requires_runner
def test_receipt_rejects_structural_provenance_and_bootstrap_point_contradictions(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    candidate_map = candidate._failed_fold_receipt("candidate_map")
    structural = _terminal_result(candidate, qualified=False)
    structural["folds"] = {str(year): copy.deepcopy(candidate_map) for year in candidate.DEVELOPMENT_FOLDS}
    structural.update(
        failed_folds=list(candidate.DEVELOPMENT_FOLDS),
        failed_structural=[f"{year}:candidate_map" for year in candidate.DEVELOPMENT_FOLDS],
    )
    impossible_identity = _terminal_result(candidate, qualified=False)
    impossible_identity["folds"]["2018"]["target_sha256"] = "1" * 64
    wrong_point = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    wrong_point["bootstrap"]["metrics"]["candidate_control_mae_delta"]["point"] = 999.0
    for status, result, map_sha in (
        ("failed", structural, None),
        ("failed", impossible_identity, None),
        ("qualified", wrong_point, "f" * 64),
    ):
        receipt = candidate._receipt(registration, "a" * 40, status, "completed", spend_token_sha256="c" * 64, result=result, map_artifact_sha256=map_sha)
        with pytest.raises(candidate.ProtocolError):
            candidate._validate_receipt(receipt)


@requires_runner
def test_receipt_rejects_non_string_nested_hashes(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    variants = []
    identity = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    identity["folds"]["2018"]["identity_sha256_by_role"]["hitter"] = int("1" * 64)
    variants.append((identity, "f" * 64))
    target = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    target["folds"]["2018"]["target_sha256"] = int("2" * 64)
    variants.append((target, "f" * 64))
    bootstrap = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    bootstrap["bootstrap"]["sample_plan_sha256"] = int("3" * 64)
    variants.append((bootstrap, "f" * 64))
    training = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    training["pooled_fit"]["training_rows_sha256"] = int("4" * 64)
    variants.append((training, "f" * 64))
    artifact = _terminal_result(candidate, qualified=True, map_sha=int("5" * 64))
    artifact["pooled_fit"]["map_artifact_sha256"] = int("5" * 64)
    variants.append((artifact, int("5" * 64)))
    for result, map_sha in variants:
        receipt = candidate._receipt(registration, "a" * 40, "qualified", "completed", spend_token_sha256="c" * 64, result=result, map_artifact_sha256=map_sha)
        with pytest.raises(candidate.ProtocolError):
            candidate._validate_receipt(receipt)


@requires_runner
def test_receipt_preserves_earliest_structural_provenance_variants(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    for stage, rows in (("identity_alignment", None), ("target_alignment", _bootstrap_fold(2018)["candidate"])):
        fold = candidate._failed_fold_receipt(stage, rows)
        result = _terminal_result(candidate, qualified=False)
        result["folds"] = {str(year): copy.deepcopy(fold) for year in candidate.DEVELOPMENT_FOLDS}
        result.update(
            failed_folds=list(candidate.DEVELOPMENT_FOLDS),
            failed_structural=[f"{year}:{stage}" for year in candidate.DEVELOPMENT_FOLDS],
        )
        receipt = candidate._receipt(registration, "a" * 40, "failed", "completed", spend_token_sha256="c" * 64, result=result, map_artifact_sha256=None)
        assert candidate._validate_receipt(receipt) == receipt


@requires_runner
def test_receipt_accepts_emitted_post_map_identity_failure(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"test": "runtime"})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    result = _terminal_result(candidate, qualified=True, map_sha="f" * 64)
    fold, _values = candidate._record_structural_failure(result["folds"]["2018"], "identity_alignment")
    fold["structural_checks"]["identity_sets_equal"] = False
    result.update(
        folds={str(year): copy.deepcopy(fold) for year in candidate.DEVELOPMENT_FOLDS},
        bootstrap=candidate._not_attempted_bootstrap(),
        failed_folds=list(candidate.DEVELOPMENT_FOLDS),
        failed_bootstrap=[],
        failed_structural=[f"{year}:identity_alignment" for year in candidate.DEVELOPMENT_FOLDS],
        pooled_fit={"attempted": False, "status": "not_attempted_qualification_failure", "row_count": 0, "training_rows_sha256": None, "map_artifact_sha256": None},
    )
    receipt = candidate._receipt(registration, "a" * 40, "failed", "completed", spend_token_sha256="c" * 64, result=result, map_artifact_sha256=None)

    assert candidate._validate_receipt(receipt) == receipt


def _protocol_sandbox(monkeypatch, tmp_path):
    """Synthetic D: files only; never call the canonical wrapper paths."""
    candidate = _runner()
    root = tmp_path / "repo"
    runtime = {"runtime": "synthetic"}
    monkeypatch.setattr(candidate, "ROOT", root)
    monkeypatch.setattr(candidate, "REGISTRATION_PATH", root / candidate.CANONICAL_READ_PATHS[0])
    monkeypatch.setattr(candidate, "RECEIPT_PATH", root / "data" / "validation" / "receipt.json")
    monkeypatch.setattr(candidate, "CALIBRATOR_PATH", root / "data" / "models" / "map.json")
    monkeypatch.setattr(candidate, "SPEND_TOKEN_PATH", tmp_path / "common" / "spent.json")
    monkeypatch.setattr(candidate, "_common_lock_path", lambda: tmp_path / "common" / "lock")
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: runtime)
    monkeypatch.setattr(candidate, "_head", lambda: "a" * 40)
    monkeypatch.setattr(candidate, "validate_development_contract", lambda _contract: [])
    monkeypatch.setenv("VALUCAST_V23_APPROVED_EXECUTION_SHA", "a" * 40)
    inputs = {}
    for relative in candidate.CANONICAL_READ_PATHS[1:]:
        payload = {"seal": "d" * 64}
        if relative.endswith(("v2_1_development.json", "v2_2_development.json")):
            payload.update(status="failed", feeds_live_rank=False, feeds_value=False)
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        inputs[relative] = {
            "git_blob": "1" * 40,
            "canonical_sha256": candidate.canonical_sha256(payload),
            "internal_field": "seal", "internal_sha256": "d" * 64,
        }
    source = root / "prospects" / "registered.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("registered = True\n", encoding="utf-8")
    registration = {
        "schema": "valucast_prospect_rank_v2_3_registration_v1",
        "registration_id": "plan_038_prospect_vnext_phase_a",
        "registration_status_at_seal": "registered_unspent",
        "candidate": {}, "predecessors": {}, "inputs": inputs,
        "sources": {"prospects/registered.py": {"git_blob": "2" * 40, "normalized_sha256": candidate._normalized_source_sha256(source)}},
        "folds": {}, "comparators": {}, "metrics": {}, "bootstrap": {},
        "state_machine": {
            "lock_file": "valucast-prospect-v23.lock", "spent_token": "valucast-prospect-v23-spent.json",
            "states": ["reserved", "outcome_access_spent", "qualified", "failed", "spent_error"],
            "cli": ["", "--resume-reserved", "--seal-interrupted-spend", "--reproduce"],
            "exit_codes": {"qualified": 0, "failed": 1, "spent_error": 2},
        },
        "outputs": {"receipt": "data/validation/valucast_prospect_rank_v2_3_development.json", "calibrator": "data/models/valucast_prospect_joint_ladder_calibrator_v5.json"},
        "forbidden_inputs": [], "forbidden_paths": [], "feeds_live_rank": False, "feeds_value": False,
        "runtime": runtime, "execution": {"approved_env": "VALUCAST_V23_APPROVED_EXECUTION_SHA"},
    }
    registration["artifact_sha256"] = candidate.canonical_sha256(registration)
    candidate.REGISTRATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.REGISTRATION_PATH.write_text(json.dumps(registration), encoding="utf-8")
    monkeypatch.setattr(candidate, "_git_blob", lambda relative, _path: inputs.get(relative, {"git_blob": "2" * 40})["git_blob"])
    monkeypatch.setattr(candidate, "_read_registration", lambda: registration)
    monkeypatch.setattr(candidate, "_verify_dynamic_registration", lambda _registration: None)
    return candidate, registration


@requires_runner
def test_first_outcome_open_observes_spent_marker_and_failed_run_writes_no_map(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    seen = []
    original = candidate._load_json
    contract_path = candidate.ROOT / candidate.CANONICAL_READ_PATHS[1]

    def observe(path, **kwargs):
        if path == contract_path:
            seen.append(json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))["status"])
        return original(path, **kwargs)

    monkeypatch.setattr(candidate, "_load_json", observe)
    result = {"failed_folds": [2018], "failed_bootstrap": [], "failed_structural": []}
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: (result, None))

    assert candidate.run([]) == 1
    assert seen == ["outcome_access_spent"]
    assert not candidate.CALIBRATOR_PATH.exists()
    receipt = json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["status"] == "failed" and receipt["development_qualified"] is False
    assert receipt["spend_token_sha256"] == __import__("hashlib").sha256(candidate.SPEND_TOKEN_PATH.read_bytes()).hexdigest()


@requires_runner
def test_bad_approval_refuses_before_any_outcome_open(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    monkeypatch.setenv("VALUCAST_V23_APPROVED_EXECUTION_SHA", "b" * 40)
    original = candidate._load_json
    monkeypatch.setattr(candidate, "_load_json", lambda path, **kwargs: original(path, **kwargs) if path == candidate.REGISTRATION_PATH else pytest.fail("outcome data opened"))

    assert candidate.run([]) == 2
    assert not candidate.RECEIPT_PATH.exists()
    assert not candidate.SPEND_TOKEN_PATH.exists()


@requires_runner
def test_post_marker_exception_is_terminal_spent_error(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: (_ for _ in ()).throw(OSError("disk fault")))

    assert candidate.run([]) == 2
    receipt = json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["status"] == "spent_error"
    assert receipt["error"] == {"stage": "post_marker", "type": "OSError", "message": "disk fault"}


@requires_runner
def test_escaped_evaluator_value_error_is_spent_error_not_scientific_failure(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: (_ for _ in ()).throw(ValueError("escaped")))

    assert candidate.run([]) == 2
    receipt = json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))
    assert receipt["status"] == "spent_error"
    assert receipt["error"]["type"] == "ValueError"


@requires_runner
def test_interrupted_spend_seals_without_reopening_outcomes(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    token = candidate._token(registration, "a" * 40)
    candidate.SPEND_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.SPEND_TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.RECEIPT_PATH.write_text(json.dumps(candidate._receipt(registration, "a" * 40, "outcome_access_spent", "outcome_access_spent", spend_token_sha256=__import__("hashlib").sha256(candidate.SPEND_TOKEN_PATH.read_bytes()).hexdigest())), encoding="utf-8")
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: pytest.fail("no recomputation"))
    monkeypatch.setattr(candidate, "_outcomes", lambda *_args: pytest.fail("no outcome reopen"))

    assert candidate.run(["--seal-interrupted-spend"]) == 2
    assert json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))["status"] == "spent_error"


@requires_runner
def test_qualified_run_writes_map_before_terminal_receipt_and_reproduces_without_writing(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    pooled = {"map": "synthetic"}
    pooled["artifact_sha256"] = candidate.canonical_sha256(pooled)
    result = _terminal_result(candidate, qualified=True, map_sha=pooled["artifact_sha256"])
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: (result, pooled))
    original = candidate._atomic_json
    writes = []
    monkeypatch.setattr(candidate, "_atomic_json", lambda path, payload, **kwargs: writes.append((path, payload["status"] if "status" in payload else "map")) or original(path, payload, **kwargs))

    assert candidate.run([]) == 0
    assert writes[-2:] == [(candidate.CALIBRATOR_PATH, "map"), (candidate.RECEIPT_PATH, "qualified")]
    receipt_before = candidate.RECEIPT_PATH.read_bytes()
    map_before = candidate.CALIBRATOR_PATH.read_bytes()
    monkeypatch.setattr(candidate, "_atomic_json", lambda *_args, **_kwargs: pytest.fail("reproduction writes nothing"))

    assert candidate.run(["--reproduce"]) == 0
    assert candidate.RECEIPT_PATH.read_bytes() == receipt_before
    assert candidate.CALIBRATOR_PATH.read_bytes() == map_before


@requires_runner
def test_failed_reproduction_returns_zero_without_rewriting_receipt(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    result = _terminal_result(candidate, qualified=False)
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: (result, None))
    assert candidate.run([]) == 1
    before = candidate.RECEIPT_PATH.read_bytes()
    monkeypatch.setattr(candidate, "_atomic_json", lambda *_args, **_kwargs: pytest.fail("reproduction writes"))

    assert candidate.run(["--reproduce"]) == 0
    assert candidate.RECEIPT_PATH.read_bytes() == before


@requires_runner
def test_qualified_reproduction_refuses_receipt_map_hash_mismatch(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    pooled = {"map": "synthetic"}
    pooled["artifact_sha256"] = candidate.canonical_sha256(pooled)
    result = _terminal_result(candidate, qualified=True, map_sha=pooled["artifact_sha256"])
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: (result, pooled))
    assert candidate.run([]) == 0
    receipt = json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))
    receipt["map_artifact_sha256"] = "f" * 64
    receipt["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in receipt.items() if key != "artifact_sha256"})
    candidate.RECEIPT_PATH.write_text(json.dumps(receipt), encoding="utf-8")

    assert candidate.run(["--reproduce"]) == 2


@requires_runner
def test_late_atomic_cas_race_preserves_newer_prior_receipt(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    reserved = candidate._receipt(registration, "a" * 40, "reserved", "reserved")
    candidate.RECEIPT_PATH.write_text(json.dumps(reserved), encoding="utf-8")
    newer = candidate._receipt(registration, "a" * 40, "spent_error", "post_marker", spend_token_sha256="e" * 64, result=None, error={"stage": "post_marker", "type": "Race", "message": "newer"})
    original_fsync = candidate.os.fsync
    raced = False

    def race(descriptor):
        nonlocal raced
        original_fsync(descriptor)
        if not raced:
            raced = True
            candidate.RECEIPT_PATH.write_text(json.dumps(newer), encoding="utf-8")

    monkeypatch.setattr(candidate.os, "fsync", race)
    with pytest.raises(candidate.ProtocolError, match="prior durable"):
        candidate._atomic_json(candidate.RECEIPT_PATH, candidate._receipt(registration, "a" * 40, "outcome_access_spent", "outcome_access_spent", spend_token_sha256="e" * 64), expected_state="reserved")
    assert json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))["error"]["message"] == "newer"


@requires_runner
def test_common_dir_os_lock_refuses_a_concurrent_entry(monkeypatch, tmp_path):
    candidate = _runner()
    lock = tmp_path / "common" / "v23.lock"
    ready = tmp_path / "ready"
    code = (
        "from pathlib import Path; import time; import scripts.build_prospect_v23_candidate as c; "
        f"c._common_lock_path=lambda:Path({str(lock)!r}); "
        f"p=Path({str(ready)!r}); "
        "\nwith c._locked(): p.write_text('locked'); time.sleep(5)"
    )
    process = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "child did not acquire the common lock"
        monkeypatch.setattr(candidate, "_common_lock_path", lambda: lock)
        with pytest.raises(candidate.ProtocolError, match="already held"):
            with candidate._locked():
                pass
    finally:
        process.terminate()
        process.wait(timeout=5)


def _hold_lock(lock: Path, ready: Path):
    code = (
        "from pathlib import Path; import time; import scripts.build_prospect_v23_candidate as c; "
        f"c._common_lock_path=lambda:Path({str(lock)!r}); p=Path({str(ready)!r}); "
        "\nwith c._locked(): p.write_text('locked'); time.sleep(5)"
    )
    process = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])
    deadline = time.monotonic() + 3
    while not ready.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert ready.exists(), "child did not acquire the common lock"
    return process


@requires_runner
def test_concurrent_resume_loses_lock_before_reading_or_changing_receipt(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.RECEIPT_PATH.write_text(json.dumps(candidate._receipt(registration, "a" * 40, "reserved", "reserved")), encoding="utf-8")
    before = candidate.RECEIPT_PATH.read_bytes()
    process = _hold_lock(candidate._common_lock_path(), tmp_path / "resume-ready")
    try:
        monkeypatch.setattr(candidate, "_load_json", lambda *_args, **_kwargs: pytest.fail("resume read before lock"))
        assert candidate.run(["--resume-reserved"]) == 2
        assert candidate.RECEIPT_PATH.read_bytes() == before
    finally:
        process.terminate()
        process.wait(timeout=5)


@requires_runner
def test_common_spend_token_refuses_second_worktree_even_without_local_receipt(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: ({"failed_folds": [2018], "failed_bootstrap": [], "failed_structural": []}, None))
    assert candidate.run([]) == 1
    candidate.RECEIPT_PATH.unlink()  # a second worktree has no local canonical receipt

    assert candidate.run([]) == 2
    assert candidate.SPEND_TOKEN_PATH.exists()
    assert not candidate.RECEIPT_PATH.exists()


@requires_runner
def test_live_spent_receipt_cannot_be_reclassified_while_lock_is_held(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    token = candidate._token(registration, "a" * 40)
    candidate.SPEND_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.SPEND_TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    token_sha = __import__("hashlib").sha256(candidate.SPEND_TOKEN_PATH.read_bytes()).hexdigest()
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.RECEIPT_PATH.write_text(json.dumps(candidate._receipt(registration, "a" * 40, "outcome_access_spent", "outcome_access_spent", spend_token_sha256=token_sha)), encoding="utf-8")
    before = candidate.RECEIPT_PATH.read_bytes()
    process = _hold_lock(candidate._common_lock_path(), tmp_path / "spent-ready")
    try:
        assert candidate.run(["--seal-interrupted-spend"]) == 2
        assert candidate.RECEIPT_PATH.read_bytes() == before
    finally:
        process.terminate()
        process.wait(timeout=5)


@requires_runner
def test_atomic_replace_failure_preserves_prior_durable_receipt(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    reserved = candidate._receipt(registration, "a" * 40, "reserved", "reserved")
    candidate.RECEIPT_PATH.write_text(json.dumps(reserved), encoding="utf-8")
    before = candidate.RECEIPT_PATH.read_bytes()
    monkeypatch.setattr(candidate.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace failed")))

    with pytest.raises(OSError, match="replace failed"):
        candidate._atomic_json(candidate.RECEIPT_PATH, candidate._receipt(registration, "a" * 40, "outcome_access_spent", "outcome_access_spent", spend_token_sha256="e" * 64), expected_state="reserved")
    assert candidate.RECEIPT_PATH.read_bytes() == before


@requires_runner
def test_concurrent_reservation_loses_before_outcome_access(monkeypatch, tmp_path):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    process = _hold_lock(candidate._common_lock_path(), tmp_path / "reserve-ready")
    try:
        monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: pytest.fail("outcome access"))
        assert candidate.run([]) == 2
        assert not candidate.RECEIPT_PATH.exists()
        assert not candidate.SPEND_TOKEN_PATH.exists()
    finally:
        process.terminate()
        process.wait(timeout=5)


@requires_runner
def test_resume_requires_unchanged_runtime_binding_before_spending(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    stale = candidate._receipt(registration, "a" * 40, "reserved", "reserved")
    stale["runtime"] = {"runtime": "changed"}
    stale["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in stale.items() if key != "artifact_sha256"})
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.RECEIPT_PATH.write_text(json.dumps(stale), encoding="utf-8")
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: pytest.fail("spent despite changed runtime"))

    assert candidate.run(["--resume-reserved"]) == 2
    assert json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))["status"] == "reserved"


@requires_runner
def test_linked_worktrees_resolve_one_git_common_lock(monkeypatch, tmp_path):
    candidate = _runner()
    repository, sibling = tmp_path / "repo", tmp_path / "sibling"
    for command in (
        ["git", "init", str(repository)],
        ["git", "-C", str(repository), "config", "user.email", "tests@example.invalid"],
        ["git", "-C", str(repository), "config", "user.name", "Protocol Test"],
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "init"],
        ["git", "-C", str(repository), "worktree", "add", "-b", "sibling", str(sibling)],
    ):
        subprocess.run(command, check=True, capture_output=True, text=True)
    monkeypatch.setattr(candidate, "ROOT", repository)
    first = candidate._common_lock_path()
    monkeypatch.setattr(candidate, "ROOT", sibling)
    second = candidate._common_lock_path()

    assert first == second
    assert first.name == "valucast-prospect-v23.lock"


@requires_runner
@pytest.mark.parametrize("approved", [None, "A" * 40, "b" * 40])
def test_missing_malformed_or_wrong_head_approval_refuses_before_marker(monkeypatch, tmp_path, approved):
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    if approved is None:
        monkeypatch.delenv("VALUCAST_V23_APPROVED_EXECUTION_SHA")
    else:
        monkeypatch.setenv("VALUCAST_V23_APPROVED_EXECUTION_SHA", approved)
    monkeypatch.setattr(candidate, "_outcomes", lambda *_args: pytest.fail("outcome access"))

    assert candidate.run([]) == 2
    assert not candidate.RECEIPT_PATH.exists()
    assert not candidate.SPEND_TOKEN_PATH.exists()


@requires_runner
def test_recovery_refuses_wrong_registration_without_mutating_or_reopening(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    token = candidate._token(registration, "a" * 40)
    candidate.SPEND_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.SPEND_TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    token_sha = __import__("hashlib").sha256(candidate.SPEND_TOKEN_PATH.read_bytes()).hexdigest()
    receipt = candidate._receipt(registration, "a" * 40, "outcome_access_spent", "outcome_access_spent", spend_token_sha256=token_sha)
    receipt["registration_sha256"] = "f" * 64
    receipt["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in receipt.items() if key != "artifact_sha256"})
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.RECEIPT_PATH.write_text(json.dumps(receipt), encoding="utf-8")
    before = candidate.RECEIPT_PATH.read_bytes()
    monkeypatch.setattr(candidate, "_outcomes", lambda *_args: pytest.fail("outcome reopen"))

    assert candidate.run(["--seal-interrupted-spend"]) == 2
    assert candidate.RECEIPT_PATH.read_bytes() == before


@requires_runner
def test_orphan_map_recovery_seals_error_without_reusing_map(monkeypatch, tmp_path):
    candidate, registration = _protocol_sandbox(monkeypatch, tmp_path)
    token = candidate._token(registration, "a" * 40)
    candidate.SPEND_TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.SPEND_TOKEN_PATH.write_text(json.dumps(token), encoding="utf-8")
    token_sha = __import__("hashlib").sha256(candidate.SPEND_TOKEN_PATH.read_bytes()).hexdigest()
    candidate.RECEIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.RECEIPT_PATH.write_text(json.dumps(candidate._receipt(registration, "a" * 40, "outcome_access_spent", "outcome_access_spent", spend_token_sha256=token_sha)), encoding="utf-8")
    candidate.CALIBRATOR_PATH.parent.mkdir(parents=True, exist_ok=True)
    candidate.CALIBRATOR_PATH.write_text(json.dumps({"orphan": True}), encoding="utf-8")
    before = candidate.CALIBRATOR_PATH.read_bytes()
    monkeypatch.setattr(candidate, "_outcomes", lambda *_args: pytest.fail("outcome reopen"))

    assert candidate.run(["--seal-interrupted-spend"]) == 2
    assert json.loads(candidate.RECEIPT_PATH.read_text(encoding="utf-8"))["status"] == "spent_error"
    assert candidate.CALIBRATOR_PATH.read_bytes() == before


@requires_runner
def test_each_receipt_state_requires_exact_schema_and_seal(monkeypatch):
    candidate = _runner()
    monkeypatch.setattr(candidate, "_runtime_tuple", lambda: {"synthetic": True})
    registration = {"registration_id": "plan_038_prospect_vnext_phase_a", "artifact_sha256": "b" * 64}
    rows = [
        candidate._receipt(registration, "a" * 40, "reserved", "reserved"),
        candidate._receipt(registration, "a" * 40, "outcome_access_spent", "outcome_access_spent", spend_token_sha256="c" * 64),
        candidate._receipt(registration, "a" * 40, "qualified", "completed", spend_token_sha256="c" * 64, result=_terminal_result(candidate, qualified=True, map_sha="d" * 64), map_artifact_sha256="d" * 64),
        candidate._receipt(registration, "a" * 40, "failed", "completed", spend_token_sha256="c" * 64, result=_terminal_result(candidate, qualified=False), map_artifact_sha256=None),
        candidate._receipt(registration, "a" * 40, "spent_error", "post_marker", spend_token_sha256="c" * 64, result=None, error={"stage": "post_marker", "type": "Error", "message": "x"}),
    ]
    for receipt in rows:
        assert candidate._validate_receipt(receipt) == receipt
        malformed = dict(receipt)
        malformed.pop("stage")
        malformed["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in malformed.items() if key != "artifact_sha256"})
        with pytest.raises(candidate.ProtocolError):
            candidate._validate_receipt(malformed)

    spent = rows[-1]
    mismatched_stage = dict(spent)
    mismatched_stage["error"] = {**spent["error"], "stage": "interrupted_spend"}
    mismatched_stage["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in mismatched_stage.items() if key != "artifact_sha256"})
    with pytest.raises(candidate.ProtocolError, match="spent error"):
        candidate._validate_receipt(mismatched_stage)

    variants = [
        {**rows[0], "schema": "wrong"},
        {**rows[0], "status": "qualified", "stage": "reserved"},
        {**rows[1], "development_qualified": False},
        {**rows[2], "cli_exit_code": 1},
        {**rows[3], "result": None},
    ]
    for malformed in variants:
        malformed["artifact_sha256"] = candidate.canonical_sha256({key: value for key, value in malformed.items() if key != "artifact_sha256"})
        with pytest.raises(candidate.ProtocolError):
            candidate._validate_receipt(malformed)
    bad_seal = dict(rows[2])
    bad_seal["artifact_sha256"] = "0" * 64
    with pytest.raises(candidate.ProtocolError, match="seal"):
        candidate._validate_receipt(bad_seal)


@requires_runner
def test_lock_file_is_initialized_at_byte_zero_and_truncated_to_one_byte(monkeypatch, tmp_path):
    candidate = _runner()
    lock = tmp_path / "common" / "lock"
    lock.parent.mkdir(parents=True)
    lock.write_bytes(b"stale")
    monkeypatch.setattr(candidate, "_common_lock_path", lambda: lock)

    with candidate._locked():
        pass
    assert lock.read_bytes() == b"s"


@requires_runner
def test_actual_linked_worktree_sibling_loses_lock_before_any_read(monkeypatch, tmp_path):
    candidate = _runner()
    repository, sibling = tmp_path / "repo", tmp_path / "sibling"
    for command in (
        ["git", "init", str(repository)],
        ["git", "-C", str(repository), "config", "user.email", "tests@example.invalid"],
        ["git", "-C", str(repository), "config", "user.name", "Protocol Test"],
        ["git", "-C", str(repository), "commit", "--allow-empty", "-m", "init"],
        ["git", "-C", str(repository), "worktree", "add", "-b", "sibling", str(sibling)],
    ):
        subprocess.run(command, check=True, capture_output=True, text=True)
    ready = tmp_path / "linked-ready"
    code = (
        "from pathlib import Path; import time; import scripts.build_prospect_v23_candidate as c; "
        f"c.ROOT=Path({str(repository)!r}); p=Path({str(ready)!r}); "
        "\nwith c._locked(): p.write_text('locked'); time.sleep(5)"
    )
    process = subprocess.Popen([sys.executable, "-c", code], cwd=Path(__file__).resolve().parents[1])
    try:
        deadline = time.monotonic() + 3
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert ready.exists(), "first linked worktree did not acquire lock"
        monkeypatch.setattr(candidate, "ROOT", sibling)
        monkeypatch.setattr(candidate, "_read_registration", lambda: pytest.fail("sibling read before lock refusal"))
        assert candidate._common_lock_path() == repository / ".git" / "valucast-prospect-v23.lock"
        assert candidate.run([]) == 2
    finally:
        process.terminate()
        process.wait(timeout=5)


@requires_runner
def test_fold_contract_is_exact_and_v09_pitchers_are_sealed_oof_only(monkeypatch):
    candidate = _runner()
    calls = []
    contract = {"current_profiles": [{"mlbam_id": 999, "role": "pitcher"}]}
    v09 = {
        "oof_rows": [
            {"mlbam_id": 1, "role": "pitcher", "test_cohort": 2018, "score_source": "prospect_model_v0_9"},
            {"mlbam_id": 2, "role": "hitter", "test_cohort": 2018, "score_source": "prospect_model_v0_9"},
            {"mlbam_id": 3, "role": "pitcher", "test_cohort": 2019, "score_source": "prospect_model_v0_9"},
        ]
    }

    monkeypatch.setattr(candidate, "build_fold_contract", lambda source, year: {"year": year})
    monkeypatch.setattr(
        candidate,
        "reconstruct_fold_ladders",
        lambda fold, pitchers, year: calls.append((fold, pitchers, year)) or {"year": year},
    )

    assert candidate.DEVELOPMENT_FOLDS == (2018, 2019, 2021)
    assert candidate.TRAINING_FOLDS_BY_TEST == {2018: (2019, 2021), 2019: (2018, 2021), 2021: (2018, 2019)}
    assert candidate.reconstruct_development_ladders(contract, v09) == {2018: {"year": 2018}, 2019: {"year": 2019}, 2021: {"year": 2021}}
    assert calls[0][1] == [v09["oof_rows"][0]]
    assert calls[1][1] == [v09["oof_rows"][2]]
    assert calls[2][1] == []


@requires_runner
def test_product_board_uses_emitted_two_decimal_score_and_full_tie_order():
    candidate = _runner()
    rows = [
        {"mlbam_id": 2, "role": "hitter", "name": "Zulu", "score": 10.004, "score_source": "universal_fallback", "rank": 5},
        {"mlbam_id": 8, "role": "hitter", "name": "Bravo", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 3},
        {"mlbam_id": 9, "role": "hitter", "name": "Alpha", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 1},
        {"mlbam_id": 3, "role": "hitter", "name": "Bravo", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 2},
        {"mlbam_id": 7, "role": "pitcher", "name": "Alpha", "score": 10.004, "score_source": "prospect_model_v0_6", "rank": 4},
    ]
    board = candidate.reconstruct_product_board(
        [
            rows[0], rows[1], rows[2], rows[3],
        ],
        [rows[4]],
    )
    assert [row["mlbam_id"] for row in board] == [9, 3, 8, 7, 2]
    assert [row["rank"] for row in board] == [1, 2, 3, 4, 5]
    assert board == candidate.reconstruct_product_board(list(reversed(rows[:4])), [rows[4]])
    wrong_ranks = copy.deepcopy(rows)
    wrong_ranks[0]["rank"] = 1
    with pytest.raises(ValueError, match="emitted ranks"):
        candidate.reconstruct_product_board(wrong_ranks[:4], wrong_ranks[4:])


@requires_runner
def test_align_by_identity_reorders_and_fails_closed_on_identity_or_target_changes():
    candidate = _runner()
    reference = [
        {"mlbam_id": 1, "role": "hitter", "target": 1.0},
        {"mlbam_id": 2, "role": "pitcher", "target": 0.0},
    ]
    rows = [
        {"mlbam_id": 2, "role": "pitcher", "target": 0.0, "score": 0.1},
        {"mlbam_id": 1, "role": "hitter", "target": 1.0, "score": 0.9},
    ]
    assert [row["mlbam_id"] for row in candidate.align_by_identity(reference, rows, "candidate")] == [1, 2]
    for broken in (
        rows[:1],
        [*rows, copy.deepcopy(rows[0])],
        [{**row, "target": 0.5} if row["mlbam_id"] == 1 else row for row in rows],
    ):
        with pytest.raises(ValueError, match="candidate"):
            candidate.align_by_identity(reference, broken, "candidate")


@requires_runner
def test_metrics_hand_check_cross_role_ties_and_exact_top25_selection():
    candidate = _runner()
    rows = [
        {"role": "hitter", "target": 1.0, "expected_tier": 0.8},
        {"role": "pitcher", "target": 0.0, "expected_tier": 0.2},
        {"role": "hitter", "target": 0.5, "expected_tier": 0.4},
        {"role": "pitcher", "target": 1.0, "expected_tier": 0.4},
    ]
    assert candidate.mae(rows, "expected_tier") == pytest.approx(0.275)
    assert candidate.cross_role_concordance(rows, "expected_tier") == pytest.approx((1 + 1 + 0.5) / 3)
    assert candidate.cross_role_concordance(rows[:1], "expected_tier") is None
    top = [
        {"target": float(index), "calibrated_expected_tier": float(index)}
        for index in range(26)
    ]
    assert candidate.top25_target_sum(top) == sum(range(1, 26))
    with pytest.raises(ValueError, match="exactly 25"):
        candidate.top25_target_sum(top[:-2])
    product = [{"rank": index, "target": float(index)} for index in range(1, 27)]
    assert candidate.top25_target_sum(list(reversed(product)), product=True) == sum(range(1, 26))
    with pytest.raises(ValueError, match="exactly 25"):
        candidate.top25_target_sum(product[:-2], product=True)


@requires_runner
def test_fold_result_aligns_adversarial_input_and_cannot_mutate_fitted_maps(monkeypatch):
    candidate = _runner()

    def score(hitters, pitchers, mapping):
        return [
            {**row, "calibrated_expected_tier": row[mapping["field"]]}
            for row in [*hitters, *pitchers]
        ]

    monkeypatch.setattr(candidate, "score_role_slope_joint_ladders", score)
    base = [
        {"mlbam_id": index, "role": "hitter" if index % 2 else "pitcher", "target": float(index % 3) / 2, "candidate": float(30 - index), "control": float(index), "score": float(index), "name": str(index), "score_source": "prospect_model_v0_6", "rank": 27 - index}
        for index in range(1, 27)
    ]
    ladders = {2018: {"candidate_hitters": [row for row in base if row["role"] == "hitter"], "candidate_pitchers": [row for row in reversed(base) if row["role"] == "pitcher"], "incumbent_hitters": [row for row in base if row["role"] == "hitter"], "incumbent_pitchers": [row for row in base if row["role"] == "pitcher"]}}
    candidate_map, control_map = {"field": "candidate"}, {"field": "control"}
    monkeypatch.setattr(candidate, "fit_fold_maps", lambda *_args: (candidate_map, control_map))
    before = copy.deepcopy((candidate_map, control_map))
    result = candidate.build_fold_result(2018, ladders, candidate_map, control_map)
    assert result["candidate_mae"] is not None
    assert result["product_mae"] is None
    assert (candidate_map, control_map) == before


def _fit_ladders():
    ladders = {}
    for year in (2018, 2019, 2021):
        fold = {}
        for prefix, score in (("candidate", 3.0), ("incumbent", 2.0)):
            for role, offset in (("hitter", 10_000), ("pitcher", 20_000)):
                fold[f"{prefix}_{role}s"] = [
                    {
                        "mlbam_id": offset + year * 10 + position,
                        "role": role,
                        "source_ladder_position": position,
                        "ladder_score": score - position,
                        "outcome": outcome,
                        "target": target,
                        "test_cohort": year,
                    }
                    for position, (outcome, target) in enumerate(
                        (("star", 1.0), ("role", 0.5), ("bust", 0.0)), 1
                    )
                ]
        ladders[year] = fold
    return ladders


@requires_runner
def test_fold_complement_maps_exclude_held_out_targets_and_bind_build_result(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()
    candidate_map, control_map = candidate.fit_fold_maps(2018, ladders)
    before = (
        candidate_map["artifact_sha256"], candidate_map["params"],
        control_map["artifact_sha256"], control_map["params"],
    )
    training_rows = candidate._training_rows(2018, ladders, "candidate")
    assert {row["test_cohort"] for row in training_rows} == {2019, 2021}
    assert all(row["test_cohort"] != 2018 for row in training_rows)

    ladders[2018]["candidate_hitters"][0]["target"] = 0.0
    ladders[2018]["incumbent_pitchers"][0]["target"] = 0.0
    repeated_candidate, repeated_control = candidate.fit_fold_maps(2018, ladders)
    assert before == (
        repeated_candidate["artifact_sha256"], repeated_candidate["params"],
        repeated_control["artifact_sha256"], repeated_control["params"],
    )

    monkeypatch.setattr(candidate, "fit_fold_maps", lambda *_args: (candidate_map, control_map))
    monkeypatch.setattr(candidate, "score_role_slope_joint_ladders", lambda *_args: [])
    with pytest.raises(ValueError, match="fold-complement"):
        candidate.build_fold_result(2018, ladders, {}, control_map)


@requires_runner
def test_fold_complement_rejects_swapped_or_aliased_cohort_markers():
    candidate = _runner()
    swapped = _fit_ladders()
    swapped[2019]["candidate_hitters"][0]["test_cohort"] = 2018
    with pytest.raises(ValueError, match="cohort marker"):
        candidate.fit_fold_maps(2018, swapped)

    aliased = _fit_ladders()
    aliased[2019] = copy.deepcopy(aliased[2018])
    with pytest.raises(ValueError, match="cohort marker"):
        candidate.build_fold_result(2018, aliased, {}, {})


def _passing_fold():
    return {
        "candidate_mae": 0.1,
        "control_mae": 0.2,
        "candidate_concordance": 0.8,
        "control_concordance": 0.6,
        "product_concordance": 0.5,
        "candidate_top25_target_sum": 10.0,
        "control_top25_target_sum": 9.0,
        "product_top25_target_sum": 8.0,
    }


@requires_runner
@pytest.mark.parametrize(
    ("expected_gate", "changes"),
    [
        ("mae_improves", {"candidate_mae": 0.2}),
        ("control_concordance_improves", {"candidate_concordance": 0.6}),
        ("candidate_concordance_above_half", {"candidate_concordance": 0.5, "control_concordance": 0.4, "product_concordance": 0.3}),
        ("product_concordance_improves", {"product_concordance": 0.8}),
        ("control_top25_matches", {"candidate_top25_target_sum": 8.9}),
        ("product_top25_matches", {"candidate_top25_target_sum": 7.9, "control_top25_target_sum": 7.0}),
    ],
)
def test_each_fold_gate_fails_at_its_operator_boundary(expected_gate, changes):
    candidate = _runner()
    fold = _passing_fold()
    fold.update(changes)
    report = {"folds": {2018: fold, 2019: _passing_fold(), 2021: _passing_fold()}}
    verdict = candidate.development_qualification(report)
    assert verdict["qualified"] is False
    assert verdict["folds"][2018]["qualified"] is False
    assert [name for name, passed in verdict["folds"][2018]["gates"].items() if not passed] == [expected_gate]


@requires_runner
def test_each_fold_must_pass_without_pooled_or_majority_rescue():
    candidate = _runner()
    failed = _passing_fold()
    failed["candidate_mae"] = failed["control_mae"]
    verdict = candidate.development_qualification({"folds": {2018: failed, 2019: _passing_fold(), 2021: _passing_fold()}})
    assert verdict["qualified"] is False
    assert verdict["folds"][2018]["qualified"] is False
    assert verdict["folds"][2019]["qualified"] is True


def _bootstrap_fold(year):
    rows = []
    for role, offset in (("hitter", 0), ("pitcher", 10)):
        for index in range(1, 14):
            target = float(index % 2)
            rows.append({
                "mlbam_id": year * 100 + offset + index,
                "role": role,
                "target": target,
                "calibrated_expected_tier": target,
                "score": target,
            })
    candidate = [dict(row) for row in rows]
    control = [{**row, "calibrated_expected_tier": 1.0 - row["target"]} for row in rows]
    product = [{**row, "score": 1.0 - row["target"], "rank": index} for index, row in enumerate(rows, 1)]
    return {"year": year, "candidate": candidate, "control": control, "product": product}


@requires_runner
def test_bootstrap_uses_one_deterministic_shared_sample_plan_without_refits(monkeypatch):
    candidate = _runner()
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda *_args: pytest.fail("bootstrap must not fit maps"))

    first = candidate.build_bootstrap_summary(folds, seed=17, replicates=12)
    second = candidate.build_bootstrap_summary(copy.deepcopy(folds), seed=17, replicates=12)

    assert first == second
    assert first["sample_plan_sha256"]
    assert first["metrics"]["candidate_control_mae_delta"]["valid_replicates"] == 12
    assert first["metrics"]["candidate_control_concordance_delta"]["valid_replicates"] == 12
    assert first["metrics"]["candidate_product_concordance_delta"]["valid_replicates"] == 12


@requires_runner
def test_pooled_fit_runs_once_only_after_fold_and_bootstrap_qualification(monkeypatch):
    candidate = _runner()
    _bypass_registered_identities(monkeypatch, candidate)
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    map_calls = []

    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: {year: {} for year in candidate.DEVELOPMENT_FOLDS})
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda year, _ladders: (candidate._completed_fold_receipt(folds[year]), folds[year]))
    monkeypatch.setattr(candidate, "build_bootstrap_summary", lambda _folds: {
        "status": "completed", "seed": 39017, "replicates": 10_000,
        "minimum_valid_replicates": 9_900,
        "interval": {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"},
        "sample_plan_sha256": "0" * 64,
        "metrics": {name: {"point": -1.0 if name == "candidate_control_mae_delta" else 1.0, "lower": -0.2 if name == "candidate_control_mae_delta" else 0.1, "upper": -0.05 if name == "candidate_control_mae_delta" else 0.2, "valid_replicates": 10_000, "gate_passed": True} for name in candidate.BOOTSTRAP_METRICS},
    })
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda rows: map_calls.append(rows) or {"training_rows_sha256": "1" * 64, "artifact_sha256": "2" * 64})
    monkeypatch.setattr(candidate, "_validate_pooled_map", lambda mapping, rows: mapping)
    monkeypatch.setattr(candidate, "_pooled_candidate_rows", lambda _ladders: [
        {"mlbam_id": 1, "role": "hitter", "source_ladder_position": 1, "ladder_score": 1.0, "outcome": "star", "target": 1.0, "test_cohort": 2018},
        {"mlbam_id": 2, "role": "pitcher", "source_ladder_position": 1, "ladder_score": 1.0, "outcome": "star", "target": 1.0, "test_cohort": 2018},
    ])

    result, pooled_map = candidate.build_development_artifacts({}, {}, {})

    assert len(map_calls) == 1
    assert pooled_map["artifact_sha256"] == "2" * 64
    assert result["pooled_fit"] == {"attempted": True, "status": "validated", "row_count": 2, "training_rows_sha256": "1" * 64, "map_artifact_sha256": "2" * 64}


@requires_runner
def test_fold_receipt_records_target_alignment_before_any_map_fit(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()
    ladders[2018]["incumbent_hitters"][0]["target"] = 0.0
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda *_args: pytest.fail("maps follow target parity"))

    receipt, values = candidate._build_fold_receipt(2018, ladders)

    assert values is None
    assert receipt["failure_stage"] == "target_alignment"
    assert receipt["structural_checks"] == {
        "identity_sets_equal": True, "targets_equal": False,
        "candidate_map_valid": None, "control_map_valid": None,
        "product_rank_reproduced": None, "top25_complete": None,
    }
    assert all(value is not None for value in receipt["identity_count_by_role"].values())
    assert receipt["target_sha256"]


@requires_runner
def test_top25_structural_failure_preserves_upstream_metrics_and_gates(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()

    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda *_args: {"map": "fixed"})
    monkeypatch.setattr(candidate, "score_role_slope_joint_ladders", lambda hitters, pitchers, _map: [
        {**row, "calibrated_expected_tier": row["target"]} for row in [*hitters, *pitchers]
    ])
    monkeypatch.setattr(candidate, "reconstruct_product_board", lambda hitters, pitchers: [
        {**row, "score": row["target"], "rank": index}
        for index, row in enumerate([*hitters, *pitchers], 1)
    ])

    receipt, values = candidate._build_fold_receipt(2018, ladders)

    assert values is None
    assert receipt["failure_stage"] == "top25_contract"
    assert receipt["structural_checks"]["top25_complete"] is False
    assert all(receipt["metrics"][name] is not None for name in (
        "candidate_mae", "control_mae", "candidate_control_mae_delta",
        "candidate_concordance", "control_concordance", "product_concordance",
        "candidate_control_concordance_delta", "candidate_product_concordance_delta",
    ))
    assert all(receipt["gates"][name] is not None for name in candidate.FOLD_GATE_ORDER[:4])
    assert receipt["metrics"]["candidate_top25_target_sum"] is None
    assert receipt["gates"]["candidate_control_top25"] is None


@requires_runner
def test_bootstrap_default_stream_uses_registered_fold_role_and_sorted_id_choice_order(monkeypatch):
    candidate = _runner()
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    for fold in folds.values():
        fold["candidate"].reverse()
    calls, seeds = [], []

    class RNG:
        def choice(self, ids, *, size, replace):
            calls.append((list(ids), size, replace))
            return [ids[0]] * size

    monkeypatch.setattr(candidate.np.random, "default_rng", lambda seed: seeds.append(seed) or RNG())
    candidate.build_bootstrap_summary(folds, replicates=1)

    assert seeds == [39017]
    assert calls == [
        (sorted(row["mlbam_id"] for row in folds[year]["candidate"] if row["role"] == role), 13, True)
        for year in candidate.DEVELOPMENT_FOLDS for role in candidate.ROLES
    ]


@requires_runner
def test_bootstrap_default_rng_plan_hash_matches_the_exact_registered_draws():
    candidate = _runner()
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    expected, rng = [], candidate.np.random.default_rng(39017)
    replicate = []
    for year in candidate.DEVELOPMENT_FOLDS:
        for role in candidate.ROLES:
            ids = sorted(row["mlbam_id"] for row in folds[year]["candidate"] if row["role"] == role)
            replicate.append({"fold": year, "role": role, "mlbam_ids": [int(value) for value in rng.choice(ids, size=len(ids), replace=True)]})
    expected.append(replicate)

    summary = candidate.build_bootstrap_summary(folds, replicates=1)

    assert summary["sample_plan_sha256"] == candidate.canonical_sha256(expected)


@requires_runner
def test_bootstrap_reuses_one_multiplicity_plan_for_each_comparator_and_metric(monkeypatch):
    candidate = _runner()
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    observed = []
    original_metrics = candidate._bootstrap_metric_rows

    class RNG:
        def choice(self, ids, *, size, replace):
            return [ids[0]] * size

    def record(*boards):
        observed.append([[row["mlbam_id"] for row in board] for board in boards])
        return original_metrics(*boards)

    monkeypatch.setattr(candidate.np.random, "default_rng", lambda _seed: RNG())
    monkeypatch.setattr(candidate, "_bootstrap_metric_rows", record)
    candidate.build_bootstrap_summary(folds, replicates=1)

    for candidate_ids, control_ids, product_ids in observed[-3:]:
        assert candidate_ids == control_ids == product_ids
        assert candidate_ids.count(candidate_ids[0]) == 13


@requires_runner
@pytest.mark.parametrize("metric_index", range(3))
def test_each_bootstrap_interval_bound_is_strict_and_independent(monkeypatch, metric_index):
    candidate = _runner()
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    original_percentile = candidate.np.percentile
    calls = []

    def percentile(values, percentiles, *, method):
        calls.append(method)
        if len(calls) - 1 == metric_index:
            return [0.0, 0.0]
        return original_percentile(values, percentiles, method=method)

    monkeypatch.setattr(candidate, "BOOTSTRAP_MINIMUM", 1)
    monkeypatch.setattr(candidate.np, "percentile", percentile)
    summary = candidate.build_bootstrap_summary(folds, replicates=2)

    assert calls == ["linear"] * 3
    failed = candidate.BOOTSTRAP_METRICS[metric_index]
    assert summary["metrics"][failed]["gate_passed"] is False
    assert all(summary["metrics"][name]["gate_passed"] is True for name in candidate.BOOTSTRAP_METRICS if name != failed)


@requires_runner
def test_bootstrap_valid_count_floor_is_independent_of_interval_bounds():
    candidate = _runner()
    summary = candidate.build_bootstrap_summary(
        {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}, replicates=1
    )

    assert all(metric["valid_replicates"] == 1 for metric in summary["metrics"].values())
    assert all(metric["gate_passed"] is False for metric in summary["metrics"].values())


def _qualified_bootstrap(candidate):
    return {
        "status": "completed", "seed": 39017, "replicates": 10_000,
        "minimum_valid_replicates": 9_900,
        "interval": {"lower_percentile": 2.5, "upper_percentile": 97.5, "method": "linear"},
        "sample_plan_sha256": "0" * 64,
        "metrics": {name: {"point": -1.0 if name == "candidate_control_mae_delta" else 1.0, "lower": -0.2 if name == "candidate_control_mae_delta" else 0.1, "upper": -0.05 if name == "candidate_control_mae_delta" else 0.2, "valid_replicates": 10_000, "gate_passed": True} for name in candidate.BOOTSTRAP_METRICS},
    }


@requires_runner
def test_artifact_schema_and_bootstrap_attempt_semantics(monkeypatch):
    candidate = _runner()
    _bypass_registered_identities(monkeypatch, candidate)
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    calls = []
    completed = candidate._completed_fold_receipt(folds[2018])
    failed_gate = _failed_gate_fold(completed)

    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: {year: {} for year in candidate.DEVELOPMENT_FOLDS})
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda year, _ladders: (failed_gate if year == 2018 else completed, folds[year]))
    monkeypatch.setattr(candidate, "build_bootstrap_summary", lambda _folds: calls.append(_folds) or _qualified_bootstrap(candidate))
    result, pooled_map = candidate.build_development_artifacts({}, {}, {})

    assert pooled_map is None
    assert len(calls) == 1
    assert set(result) == {"fold_order", "folds", "bootstrap", "failed_folds", "failed_bootstrap", "failed_structural", "pooled_fit"}
    assert set(result["folds"]["2018"]) == {"status", "failure_stage", "identity_count_by_role", "identity_sha256_by_role", "target_sha256", "metrics", "gates", "structural_checks", "failed_gates", "failed_structural"}
    assert result["bootstrap"]["status"] == "completed"
    assert result["pooled_fit"]["status"] == "not_attempted_qualification_failure"


@requires_runner
def test_development_result_uses_json_stable_fold_keys(monkeypatch):
    candidate = _runner()
    _bypass_registered_identities(monkeypatch, candidate)
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    completed = candidate._completed_fold_receipt(folds[2018])
    failed = _failed_gate_fold(completed)
    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: {year: {} for year in candidate.DEVELOPMENT_FOLDS})
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda year, _ladders: (failed if year == 2018 else completed, folds[year]))
    monkeypatch.setattr(candidate, "build_bootstrap_summary", lambda _folds: _qualified_bootstrap(candidate))

    result, _map = candidate.build_development_artifacts({}, {}, {})

    assert set(result["folds"]) == {"2018", "2019", "2021"}


@requires_runner
@pytest.mark.parametrize("qualified", [False, True])
def test_persisted_actual_result_shape_reproduces_without_writes(monkeypatch, tmp_path, qualified):
    candidate = _runner()
    _bypass_registered_identities(monkeypatch, candidate)
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    completed = candidate._completed_fold_receipt(folds[2018])
    failed = _failed_gate_fold(completed)
    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: {year: {} for year in candidate.DEVELOPMENT_FOLDS})
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda year, _ladders: (completed if qualified or year != 2018 else failed, folds[year]))
    monkeypatch.setattr(candidate, "build_bootstrap_summary", lambda _folds: _qualified_bootstrap(candidate))
    pooled = None
    if qualified:
        pooled = {"training_rows_sha256": "a" * 64}
        pooled["artifact_sha256"] = candidate.canonical_sha256(pooled)
        monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda _rows: pooled)
        monkeypatch.setattr(candidate, "_validate_pooled_map", lambda mapping, _rows: mapping)
        monkeypatch.setattr(candidate, "_pooled_candidate_rows", lambda _ladders: [{"mlbam_id": 1, "role": "hitter", "source_ladder_position": 1, "ladder_score": 1.0, "outcome": "star", "target": 1.0, "test_cohort": 2018}])
    result, built_map = candidate.build_development_artifacts({}, {}, {})
    assert set(result["folds"]) == {"2018", "2019", "2021"}
    if not qualified:
        result["bootstrap"]["metrics"]["candidate_control_mae_delta"]["point"] = -1 / 3
    candidate, _registration = _protocol_sandbox(monkeypatch, tmp_path)
    monkeypatch.setattr(candidate, "build_development_artifacts", lambda *_args: (result, built_map))

    assert candidate.run([]) == (0 if qualified else 1)
    receipt_before = candidate.RECEIPT_PATH.read_bytes()
    monkeypatch.setattr(candidate, "_atomic_json", lambda *_args, **_kwargs: pytest.fail("reproduction writes"))
    assert candidate.run(["--reproduce"]) == 0
    assert candidate.RECEIPT_PATH.read_bytes() == receipt_before


@requires_runner
def test_structural_fold_failure_skips_bootstrap_with_exact_null_summary(monkeypatch):
    candidate = _runner()
    _bypass_registered_identities(monkeypatch, candidate)
    structural = candidate._failed_fold_receipt("candidate_map", _bootstrap_fold(2018)["candidate"])

    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: {year: {} for year in candidate.DEVELOPMENT_FOLDS})
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda year, _ladders: (structural, None))
    monkeypatch.setattr(candidate, "build_bootstrap_summary", lambda *_args: pytest.fail("structural folds skip bootstrap"))
    result, pooled_map = candidate.build_development_artifacts({}, {}, {})

    assert pooled_map is None
    assert result["bootstrap"]["status"] == "not_attempted_fold_failure"
    assert result["bootstrap"]["sample_plan_sha256"] is None
    assert all(metric == {"point": None, "lower": None, "upper": None, "valid_replicates": None, "gate_passed": None} for metric in result["bootstrap"]["metrics"].values())


@requires_runner
def test_pooled_value_error_is_scientific_failure_and_unexpected_error_propagates(monkeypatch):
    candidate = _runner()
    _bypass_registered_identities(monkeypatch, candidate)
    folds = {year: _bootstrap_fold(year) for year in candidate.DEVELOPMENT_FOLDS}
    completed = candidate._completed_fold_receipt(folds[2018])

    monkeypatch.setattr(candidate, "reconstruct_development_ladders", lambda *_args: {year: {} for year in candidate.DEVELOPMENT_FOLDS})
    monkeypatch.setattr(candidate, "_build_fold_receipt", lambda year, _ladders: (completed, folds[year]))
    monkeypatch.setattr(candidate, "build_bootstrap_summary", lambda _folds: _qualified_bootstrap(candidate))
    monkeypatch.setattr(candidate, "_pooled_candidate_rows", lambda _ladders: [{"mlbam_id": 1, "role": "hitter", "source_ladder_position": 1, "ladder_score": 1.0, "outcome": "star", "target": 1.0, "test_cohort": 2018}])
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda _rows: (_ for _ in ()).throw(ValueError("optimizer")))

    result, pooled_map = candidate.build_development_artifacts({}, {}, {})
    assert pooled_map is None
    assert result["pooled_fit"]["status"] == "failed"
    assert result["failed_structural"] == ["pooled_final_fit"]

    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda _rows: (_ for _ in ()).throw(RuntimeError("infrastructure")))
    with pytest.raises(RuntimeError, match="infrastructure"):
        candidate.build_development_artifacts({}, {}, {})


@requires_runner
def test_invalid_candidate_target_keeps_identity_provenance_and_fails_target_alignment(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()
    ladders[2018]["candidate_hitters"][0]["target"] = float("nan")
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda *_args: pytest.fail("invalid target precedes fitting"))

    receipt, values = candidate._build_fold_receipt(2018, ladders)

    assert values is None
    assert receipt["failure_stage"] == "target_alignment"
    assert receipt["identity_count_by_role"] == {"hitter": 3, "pitcher": 3}
    assert all(len(value) == 64 for value in receipt["identity_sha256_by_role"].values())
    assert receipt["target_sha256"] is None


@requires_runner
def test_post_map_identity_failure_nulls_all_downstream_checks_metrics_and_gates(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()
    calls = []

    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda *_args: {"map": "fixed"})
    def score(hitters, pitchers, _map):
        calls.append(True)
        rows = [{**row, "calibrated_expected_tier": row["target"]} for row in [*hitters, *pitchers]]
        return rows[:-1] if len(calls) == 1 else rows
    monkeypatch.setattr(candidate, "score_role_slope_joint_ladders", score)
    monkeypatch.setattr(candidate, "reconstruct_product_board", lambda hitters, pitchers: [
        {**row, "score": row["target"], "rank": index}
        for index, row in enumerate([*hitters, *pitchers], 1)
    ])

    receipt, values = candidate._build_fold_receipt(2018, ladders)

    assert values is None
    assert receipt["failure_stage"] == "identity_alignment"
    assert receipt["structural_checks"] == {
        "identity_sets_equal": False, "targets_equal": True,
        "candidate_map_valid": None, "control_map_valid": None,
        "product_rank_reproduced": None, "top25_complete": None,
    }
    assert all(value is None for value in receipt["metrics"].values())
    assert all(value is None for value in receipt["gates"].values())


@requires_runner
def test_top25_structural_failure_keeps_upstream_failed_gates_in_registered_order(monkeypatch):
    candidate = _runner()
    ladders = _fit_ladders()
    monkeypatch.setattr(candidate, "fit_role_slope_joint_map", lambda *_args: {"map": "fixed"})
    monkeypatch.setattr(candidate, "score_role_slope_joint_ladders", lambda hitters, pitchers, _map: [
        {**row, "calibrated_expected_tier": row["target"]} for row in [*hitters, *pitchers]
    ])
    monkeypatch.setattr(candidate, "reconstruct_product_board", lambda hitters, pitchers: [
        {**row, "score": row["target"], "rank": index}
        for index, row in enumerate([*hitters, *pitchers], 1)
    ])

    receipt, _ = candidate._build_fold_receipt(2018, ladders)

    assert receipt["failure_stage"] == "top25_contract"
    assert receipt["failed_gates"] == [
        "candidate_control_mae", "candidate_control_concordance",
        "candidate_product_concordance",
    ]
