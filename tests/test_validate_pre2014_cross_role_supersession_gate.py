import hashlib
import json
from copy import deepcopy
import pytest

from scripts.validate_pre2014_cross_role_supersession_gate import (
    PLAN036_ARTIFACT_COMMIT,
    ResultValidationError,
    _canonical,
    _validate_fixed_gate,
    _validate_runtime_record,
    _validate_readiness_contract,
    _validate_git_topology,
    _validate_registration_contract,
    _validate_terminal_documents,
    _validate_supersession,
    replay_terminal_decision,
)


def _gate_registration():
    return {
        "candidate": {
            "candidate_count": 1,
            "pitcher_investment_feature_mode": "drop_raw_pick_value",
            "rank_model_score_mode": "common_target",
            "calibration": "fold_trained_role_head_isotonic",
            "head_blend": {"outcome": 0.58, "impact": 0.42},
            "governor_thresholds_changed": False,
            "forbidden_substitutions": [
                "raw_pick_value",
                "live_role_quantile",
                "governor_relaxation",
            ],
        },
        "outer_folds": [2017, 2018, 2019, 2021],
        "bootstrap": {
            "seed": 35011,
            "resamples": 10000,
            "interval": "two_sided_95_percentile",
            "direct_mae": {
                "unit": "player_within_cohort_hierarchical",
                "point_statistic": "relative_mae_improvement",
            },
            "cross_role_concordance": {
                "unit": "cohort_then_identity_within_role",
                "point_statistic": "incumbent_discordance_reduction",
            },
        },
        "primary_endpoint": "direct_7x7_target_percentile_rank_mae",
        "thresholds": {
            "minimum_outer_folds": 4,
            "minimum_unique_players_per_role": 250,
            "minimum_fold_role_coverage": 0.9,
            "minimum_direct_mae_relative_improvement": 0.02,
            "direct_mae_bootstrap_lower_strictly_gt": 0.0,
            "maximum_fold_relative_regression": 0.05,
            "maximum_role_concordance_relative_regression": 0.01,
            "top25_direct_regret_no_worse": True,
            "top25_ordinal_regret_no_worse": True,
            "minimum_cross_role_concordance_relative_improvement": 0.02,
            "cross_role_bootstrap_lower_strictly_gt": 0.0,
            "current_governor_required": True,
        },
        "governor": {
            "check_id": "prospect_top_board_role_shape",
            "max_top25_pitcher_count": 7,
            "max_top50_pitcher_rate": 0.3,
        },
    }


def _supersession():
    import scripts.run_pre2014_cross_role_supersession_gate as runner

    return deepcopy(runner._expected_supersedes())


def _readiness():
    gate = _gate_registration()
    return {
        "artifact": "valucast_pre2014_cross_role_supersession_readiness",
        "schema_version": 1,
        "status": "ready",
        "blockers": [],
        "execution_authorized": True,
        "look_spent": False,
        "research_only": True,
        "claim_authorized": False,
        "automatic_promotion": False,
        "implementation_base_commit": "8" * 40,
        "supersedes": _supersession(),
        **gate,
        "corrections": {
            "allowed": [
                "zero_walk_positive_strikeout_k_bb_ordinal_target",
                "statsapi_bare_dash_missing_numeric_sentinel",
            ],
            "row_or_identity_drops": 0,
            "category_drops": 0,
            "threshold_changes": 0,
            "candidate_changes": 0,
        },
        "hashes": {
            "implementation_files": [
                {
                    "path": "prospects/direct_7x7.py",
                    "git_blob": "9" * 40,
                    "sha256": "a" * 64,
                }
            ],
            "implementation_change_paths": ["prospects/direct_7x7.py"],
            "current_prospect_contract": {
                "path": "data/prospects/prospect_model_inputs.json",
                "git_blob": "b" * 40,
                "binding": "git_blob_only_pre_reservation",
            },
        },
        "result": {
            "path": (
                "data/validation/valucast_pre2014_cross_role_"
                "supersession_gate.json"
            ),
            "exists": False,
            "unspent": True,
        },
    }


def test_fixed_gate_accepts_only_the_registered_candidate_and_parameters():
    _validate_fixed_gate(_gate_registration())

    drifted = json.loads(json.dumps(_gate_registration()))
    drifted["thresholds"]["maximum_fold_relative_regression"] = 0.051
    with pytest.raises(ResultValidationError, match="thresholds drift"):
        _validate_fixed_gate(drifted)


def test_supersession_requires_frozen_plan036_lineage_and_no_refetch():
    _validate_supersession(_supersession())

    drifted = json.loads(json.dumps(_supersession()))
    drifted["network_refetch_forbidden"] = False
    with pytest.raises(ResultValidationError, match="supersession controls drift"):
        _validate_supersession(drifted)


def test_readiness_is_exactly_outcome_blind_and_matches_registration_gate(
    monkeypatch,
):
    import scripts.validate_pre2014_cross_role_supersession_gate as validator

    readiness = _readiness()
    monkeypatch.setattr(
        validator,
        "EXPECTED_IMPLEMENTATION_CHANGE_PATHS",
        ["prospects/direct_7x7.py"],
    )
    monkeypatch.setattr(
        validator, "PLAN037_IMPLEMENTATION_PATHS", ("prospects/direct_7x7.py",)
    )
    _validate_readiness_contract(
        readiness,
        implementation_paths=("prospects/direct_7x7.py",),
    )

    drifted = json.loads(json.dumps(readiness))
    drifted["corrections"]["row_or_identity_drops"] = 1
    with pytest.raises(ResultValidationError, match="correction contract drift"):
        _validate_readiness_contract(
            drifted,
            implementation_paths=("prospects/direct_7x7.py",),
        )


def test_readiness_rejects_unbound_or_reordered_implementation_files(monkeypatch):
    import scripts.validate_pre2014_cross_role_supersession_gate as validator

    readiness = _readiness()
    monkeypatch.setattr(
        validator,
        "EXPECTED_IMPLEMENTATION_CHANGE_PATHS",
        ["prospects/direct_7x7.py"],
    )
    monkeypatch.setattr(
        validator, "PLAN037_IMPLEMENTATION_PATHS", ("prospects/direct_7x7.py",)
    )
    readiness["hashes"]["implementation_files"][0].pop("sha256")
    with pytest.raises(ResultValidationError, match="implementation hash record"):
        _validate_readiness_contract(
            readiness,
            implementation_paths=("prospects/direct_7x7.py",),
        )


def test_supersession_rejects_duplicate_or_noncanonical_inherited_paths():
    duplicate = json.loads(json.dumps(_supersession()))
    duplicate["outcome_blob_records"][1]["path"] = duplicate[
        "outcome_blob_records"
    ][0]["path"]
    with pytest.raises(ResultValidationError, match="outcome blob path drift"):
        _validate_supersession(duplicate)

    noncanonical = json.loads(json.dumps(_supersession()))
    noncanonical["outcome_blob_records"][0]["path"] = "../result.json"
    with pytest.raises(ResultValidationError, match="canonical repo-relative"):
        _validate_supersession(noncanonical)


def test_runtime_record_binds_path_and_bytes(tmp_path, monkeypatch):
    import scripts.validate_pre2014_cross_role_supersession_gate as validator

    monkeypatch.setattr(validator, "ROOT", tmp_path)
    path = tmp_path / "data/validation/evidence.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"sealed evidence\n")
    record = {
        "path": "data/validation/evidence.json",
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    assert _validate_runtime_record(record, expected_path=record["path"])[0] == path

    path.write_bytes(b"mutated evidence\n")
    with pytest.raises(ResultValidationError, match="content hash drift"):
        _validate_runtime_record(record, expected_path=record["path"])


def test_terminal_status_and_decision_are_replayed_not_trusted(monkeypatch):
    import scripts.validate_pre2014_cross_role_supersession_gate as validator

    replay = {
        "decision": "production_review_authorized",
        "production_review_authorized": True,
        "metrics": {"receipt": "deterministic"},
    }
    monkeypatch.setattr(
        validator,
        "evaluate_pre2014_cross_role_gate",
        lambda *_args, **_kwargs: replay,
    )
    result = {
        "status": "passed",
        "decision": "production_review_authorized",
        "production_review_authorized": True,
        "claim_authorized": False,
        "evaluation": replay,
    }
    assert replay_terminal_decision(
        result, folds=[{"cohort_year": 2017}], governor_passed=True
    ) == replay

    result["status"] = "failed"
    with pytest.raises(ResultValidationError, match="status/decision"):
        replay_terminal_decision(
            result, folds=[{"cohort_year": 2017}], governor_passed=True
        )


def test_canonical_serialization_rejects_nonfinite_values():
    with pytest.raises(ResultValidationError, match="non-canonical"):
        _canonical({"value": float("nan")})


def test_registration_reuses_exact_readiness_gate_and_unique_result_contract():
    readiness = _readiness()
    registration = {
        "protocol": (
            "plan_037_pre2014_cross_role_calibration_supersession"
        ),
        "registered_at": "2026-08-11T00:00:00Z",
        "status": "registered",
        "look_spent": False,
        "execution_authorized": True,
        "research_only": True,
        "automatic_promotion": False,
        "claim_authorized": False,
        "implementation_base_commit": readiness["implementation_base_commit"],
        "readiness": {
            "path": (
                "data/validation/valucast_pre2014_cross_role_"
                "supersession_readiness.json"
            ),
            "sha256": "c" * 64,
        },
        "result_path": readiness["result"]["path"],
        "supersedes": readiness["supersedes"],
        **_gate_registration(),
        "result_contract": {
            "single_use": True,
            "claim_authorized": False,
            "automatic_promotion": False,
            "terminal_evidence_path": (
                "data/validation/valucast_pre2014_cross_role_"
                "supersession_evidence.json"
            ),
            "network_refetch_forbidden": True,
        },
        "limitations": ["cohort-season-completion pseudo-replay"],
    }
    _validate_registration_contract(
        registration, readiness=readiness, readiness_sha256="c" * 64
    )

    registration["result_contract"]["network_refetch_forbidden"] = False
    with pytest.raises(ResultValidationError, match="result contract drift"):
        _validate_registration_contract(
            registration, readiness=readiness, readiness_sha256="c" * 64
        )


def test_git_topology_accepts_only_s036_i037_r037_and_artifact_only_s037(
    monkeypatch,
):
    import scripts.validate_pre2014_cross_role_supersession_gate as validator

    i037, r037, s037 = "1" * 40, "2" * 40, "3" * 40
    parents = {
        i037: [i037, PLAN036_ARTIFACT_COMMIT],
        r037: [r037, i037],
        s037: [s037, r037],
    }
    registration_paths = {
        "plans/037-pre2014-cross-role-calibration-supersession.md": "A",
        "plans/README.md": "M",
        (
            "data/validation/valucast_pre2014_cross_role_"
            "supersession_readiness.json"
        ): "A",
        "tests/test_pre2014_cross_role_supersession_registration.py": "A",
    }
    runtime_paths = {
        (
            "data/validation/valucast_pre2014_cross_role_"
            "supersession_gate.json"
        ): "A",
        (
            "data/validation/valucast_pre2014_cross_role_"
            "supersession_evidence.json"
        ): "A",
    }
    monkeypatch.setattr(
        validator,
        "_git_text",
        lambda *args: " ".join(parents[args[-1]])
        if args[:3] == ("rev-list", "--parents", "-n")
        else "",
    )
    monkeypatch.setattr(
        validator,
        "_name_status",
        lambda base, head: registration_paths if head == r037 else runtime_paths,
    )
    monkeypatch.setattr(validator, "_validate_commit_blob", lambda **_kwargs: None)
    monkeypatch.setattr(validator, "_worktree_status", lambda: {})

    assert _validate_git_topology(
        implementation_commit=i037,
        execution_commit=r037,
        head=s037,
        result_status="passed",
    ) == "artifact_commit"

    parents[i037] = [i037, "0" * 40]
    with pytest.raises(ResultValidationError, match="direct child of Plan 036"):
        _validate_git_topology(
            implementation_commit=i037,
            execution_commit=r037,
            head=s037,
            result_status="passed",
        )


def test_terminal_documents_cross_link_and_replay_exact_payload(monkeypatch, tmp_path):
    import scripts.validate_pre2014_cross_role_supersession_gate as validator

    monkeypatch.setattr(validator, "ROOT", tmp_path)
    supersedes = _supersession()
    replay = {
        "inherited_validation": {"status": "validated"},
        "canonical_outcomes": {},
        "labeled_contract": {},
        "quality_starts": {"sidecar": {"content_sha256": "d" * 64}},
        "fold_outputs": [{"cohort_year": 2017}],
        "current_role_shape_governor": {"passed": True},
        "evaluation": {
            "production_review_authorized": True,
            "decision": "production_review_authorized",
        },
    }
    evidence = {
        "artifact": "valucast_plan037_supersession_terminal_evidence",
        "schema_version": 1,
        "status": "passed",
        "reservation_id": "reservation-037",
        "registered_readiness_sha256": "a" * 64,
        "registration_sha256": "b" * 64,
        "implementation_base_commit": "c" * 40,
        "supersedes": supersedes,
        "network_refetch_used": False,
        "inherited_validation": replay["inherited_validation"],
        "fold_outputs": replay["fold_outputs"],
        "current_role_shape_governor": replay["current_role_shape_governor"],
        "evaluation": replay["evaluation"],
        "quality_starts_sha256": "d" * 64,
        "execution_commit": "e" * 40,
    }
    evidence_path = tmp_path / validator.REGISTERED_EVIDENCE_REPO_PATH
    evidence_path.parent.mkdir(parents=True)
    evidence_path.write_text(
        json.dumps(evidence, sort_keys=True) + "\n", encoding="utf-8"
    )
    result = {
        "artifact": "valucast_pre2014_cross_role_supersession_gate",
        "schema_version": 1,
        "protocol": validator.PROTOCOL,
        "status": "passed",
        "decision": "production_review_authorized",
        "production_review_authorized": True,
        "claim_authorized": False,
        "registered_readiness_sha256": "a" * 64,
        "registration_sha256": "b" * 64,
        "supersedes": supersedes,
        "candidate": {
            "model_flags": {"PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"},
            "model_score_mode": "common_target",
        },
        "outer_folds": [2017, 2018, 2019, 2021],
        "quality_starts_sha256": "d" * 64,
        "current_role_shape_governor": replay["current_role_shape_governor"],
        "fold_outputs": replay["fold_outputs"],
        "evaluation": replay["evaluation"],
        "evidence_bundle": {
            "terminal_evidence": {
                "path": validator.REGISTERED_EVIDENCE_REPO_PATH,
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
        },
        "reservation_id": "reservation-037",
    }
    monkeypatch.setattr(
        validator,
        "_recompute_from_frozen_blobs",
        lambda **_kwargs: replay,
    )
    monkeypatch.setattr(
        validator,
        "replay_terminal_decision",
        lambda *_args, **_kwargs: replay["evaluation"],
    )

    assert _validate_terminal_documents(
        result,
        readiness={
            "implementation_base_commit": "c" * 40,
            "supersedes": supersedes,
        },
        registration={},
        readiness_sha256="a" * 64,
        registration_sha256="b" * 64,
    )["execution_commit"] == "e" * 40

    result["claim_authorized"] = True
    with pytest.raises(ResultValidationError, match="fixed contract drift"):
        _validate_terminal_documents(
            result,
            readiness={
                "implementation_base_commit": "c" * 40,
                "supersedes": supersedes,
            },
            registration={},
            readiness_sha256="a" * 64,
            registration_sha256="b" * 64,
        )
