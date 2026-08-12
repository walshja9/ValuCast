import hashlib
import json
from pathlib import Path

import pytest

import scripts.run_pre2014_cross_role_supersession_gate as runner


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_plan036_blob_loader_cannot_run_before_plan037_reservation(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    calls = []

    def blob_loader(_commit, path):
        calls.append(path)
        return b"{}"

    monkeypatch.setattr(runner, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="before inherited outcomes"):
        runner._load_plan036_artifacts(
            result_path=result_path,
            reservation_id="reservation-037",
            supersedes=runner._expected_supersedes(),
            blob_loader=blob_loader,
        )

    assert calls == []


def test_plan036_blob_loader_reads_only_registered_blobs_after_reservation(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    reservation_id = "reservation-037"
    _write_json(
        result_path,
        {
            "reservation_id": reservation_id,
            "status": "reserved_before_outer_outcomes",
        },
    )
    expected = runner._expected_supersedes()
    payloads = {
        record["path"]: json.dumps({"path": record["path"]}).encode()
        for record in expected["outcome_blob_records"]
    }
    payloads[expected["plan036_registration"]["path"]] = b"registration"
    payloads[expected["plan036_readiness"]["path"]] = b"readiness"
    calls = []

    def blob_loader(commit, path):
        assert commit in {
            runner.PLAN036_ARTIFACT_COMMIT,
            runner.PLAN036_EXECUTION_COMMIT,
        }
        calls.append(path)
        return payloads[path]

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    inherited = runner._load_plan036_artifacts(
        result_path=result_path,
        reservation_id=reservation_id,
        supersedes=expected,
        blob_loader=blob_loader,
        validate_metadata_hashes=False,
    )

    assert set(calls) == set(payloads)
    assert set(inherited) == {
        "result",
        "evidence",
        "checkpoint",
        "registration_bytes",
        "readiness_bytes",
        "blob_receipt",
    }
    assert all(
        receipt["sha256"] == hashlib.sha256(payloads[path]).hexdigest()
        for path, receipt in inherited["blob_receipt"].items()
    )


def test_reserved_runner_consumes_failure_and_never_calls_network(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    evidence_path = tmp_path / "evidence.json"
    events = []

    def inherited_loader(*, result_path, reservation_id):
        marker = json.loads(Path(result_path).read_text(encoding="utf-8"))
        assert marker == {
            "reservation_id": reservation_id,
            "status": "reserved_before_outer_outcomes",
        }
        events.append("loaded_after_reservation")
        return {"fixture": True}

    def replay_builder(**_kwargs):
        events.append("replay")
        raise RuntimeError("synthetic scorer failure")

    monkeypatch.setattr(runner, "ROOT", tmp_path)

    with pytest.raises(RuntimeError, match="synthetic scorer failure"):
        runner._run_reserved_supersession(
            result_path=result_path,
            evidence_path=evidence_path,
            registered_readiness_sha256="a" * 64,
            registration_sha256="b" * 64,
            implementation_base_commit="c" * 40,
            execution_commit="e" * 40,
            supersedes=runner._expected_supersedes(),
            inherited_loader=inherited_loader,
            replay_builder=replay_builder,
            reservation_id="reservation-037",
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert events == ["loaded_after_reservation", "replay"]
    assert result["status"] == "spent_error"
    assert result["error_type"] == "RuntimeError"
    assert evidence["status"] == "spent_error"
    assert evidence["error_type"] == "RuntimeError"


def test_reserved_runner_finalizes_deterministic_pass_payload(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    evidence_path = tmp_path / "evidence.json"
    evaluation = {
        "production_review_authorized": True,
        "decision": "production_review_authorized",
    }
    replay = {
        "inherited_validation": {"status": "validated"},
        "canonical_outcomes": {"identity_count": 2},
        "labeled_contract": {"rows": []},
        "quality_starts": {"sidecar": {"content_sha256": "d" * 64}},
        "fold_outputs": [{"cohort_year": 2017}],
        "current_role_shape_governor": {"passed": True},
        "evaluation": evaluation,
    }

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    result = runner._run_reserved_supersession(
        result_path=result_path,
        evidence_path=evidence_path,
        registered_readiness_sha256="a" * 64,
        registration_sha256="b" * 64,
        implementation_base_commit="c" * 40,
        execution_commit="e" * 40,
        supersedes=runner._expected_supersedes(),
        inherited_loader=lambda **_kwargs: {"fixture": True},
        replay_builder=lambda **_kwargs: replay,
        reservation_id="reservation-037",
    )

    persisted = json.loads(result_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert result == persisted
    assert persisted["status"] == "passed"
    assert persisted["protocol"] == runner.PROTOCOL
    assert persisted["claim_authorized"] is False
    assert persisted["candidate"] == {
        "model_flags": dict(runner.CANDIDATE_MODEL_FLAGS),
        "model_score_mode": runner.CANDIDATE_SCORE_MODE,
    }
    assert evidence["status"] == "passed"
    assert evidence["evaluation"] == evaluation
    assert evidence["quality_starts_sha256"] == "d" * 64
    assert "canonical_outcomes" not in evidence
    assert "labeled_contract" not in evidence
    assert "quality_starts" not in evidence


def test_late_success_finalization_failure_writes_exact_spent_evidence(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    evidence_path = tmp_path / "evidence.json"
    replay = {
        "inherited_validation": {"status": "validated"},
        "canonical_outcomes": {"identity_count": 2},
        "labeled_contract": {"rows": []},
        "quality_starts": {"sidecar": {"content_sha256": "d" * 64}},
        "fold_outputs": [{"cohort_year": 2017}],
        "current_role_shape_governor": {"passed": True},
        "evaluation": {
            "production_review_authorized": True,
            "decision": "production_review_authorized",
        },
    }
    original_finalize = runner.finalize_reserved_result
    calls = []

    def fail_success_finalize(path, reservation_id, payload):
        calls.append(payload["status"])
        if payload["status"] == "passed":
            raise RuntimeError("synthetic late finalization failure")
        return original_finalize(path, reservation_id, payload)

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(runner, "finalize_reserved_result", fail_success_finalize)

    with pytest.raises(RuntimeError, match="synthetic late finalization failure"):
        runner._run_reserved_supersession(
            result_path=result_path,
            evidence_path=evidence_path,
            registered_readiness_sha256="a" * 64,
            registration_sha256="b" * 64,
            implementation_base_commit="c" * 40,
            execution_commit="e" * 40,
            supersedes=runner._expected_supersedes(),
            inherited_loader=lambda **_kwargs: {"fixture": True},
            replay_builder=lambda **_kwargs: replay,
            reservation_id="reservation-037",
        )

    result = json.loads(result_path.read_text(encoding="utf-8"))
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert calls == ["passed", "spent_error"]
    assert result["status"] == "spent_error"
    assert result["error_type"] == "RuntimeError"
    assert set(evidence) == {
        "artifact",
        "schema_version",
        "status",
        "reservation_id",
        "registered_readiness_sha256",
        "registration_sha256",
        "implementation_base_commit",
        "execution_commit",
        "supersedes",
        "network_refetch_used",
        "error_type",
    }
    assert evidence["status"] == "spent_error"
    assert evidence["error_type"] == "RuntimeError"


def test_reserved_runner_resumes_exact_existing_reservation(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    evidence_path = tmp_path / "evidence.json"
    reservation_id = "existing-reservation-037"
    _write_json(
        result_path,
        {
            "reservation_id": reservation_id,
            "status": "reserved_before_outer_outcomes",
        },
    )
    replay = {
        "inherited_validation": {"status": "validated"},
        "canonical_outcomes": {"identity_count": 2},
        "labeled_contract": {"rows": []},
        "quality_starts": {"sidecar": {"content_sha256": "d" * 64}},
        "fold_outputs": [{"cohort_year": 2017}],
        "current_role_shape_governor": {"passed": True},
        "evaluation": {
            "production_review_authorized": False,
            "decision": "production_review_not_authorized",
        },
    }

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner,
        "reserve_result_path",
        lambda *_args, **_kwargs: pytest.fail("resume must not reserve again"),
    )
    result = runner._run_reserved_supersession(
        result_path=result_path,
        evidence_path=evidence_path,
        registered_readiness_sha256="a" * 64,
        registration_sha256="b" * 64,
        implementation_base_commit="c" * 40,
        execution_commit="e" * 40,
        supersedes=runner._expected_supersedes(),
        inherited_loader=lambda **_kwargs: {"fixture": True},
        replay_builder=lambda **_kwargs: replay,
        reservation_id=reservation_id,
        existing_reservation=True,
    )

    assert result["reservation_id"] == reservation_id
    assert result["status"] == "failed"


def test_runner_has_no_network_acquisition_path():
    source = Path(runner.__file__).read_text(encoding="utf-8")

    assert "urllib" not in source
    assert "ThreadPoolExecutor" not in source
    assert "fetch_strict" not in source
    assert "bootstrap_seed=BOOTSTRAP_SEED" in source
    assert "bootstrap_resamples=DEFAULT_BOOTSTRAP_RESAMPLES" in source
    assert runner.REGISTERED_RESULT_PATH != runner.PLAN036_RESULT_PATH
    assert runner.REGISTERED_EVIDENCE_PATH != runner.PLAN036_EVIDENCE_PATH


def test_implementation_contract_binds_exact_sorted_60_file_set():
    expected = sorted(
        set(runner.plan036.REGISTERED_IMPLEMENTATION_PATHS)
        | set(runner.EXPECTED_IMPLEMENTATION_CHANGE_PATHS)
    )

    assert len(expected) == 60
    assert expected == sorted(expected)
    assert set(runner.EXPECTED_IMPLEMENTATION_CHANGE_PATHS).issubset(expected)
    assert set(runner.EXPECTED_IMPLEMENTATION_CHANGE_STATUSES) == set(
        runner.EXPECTED_IMPLEMENTATION_CHANGE_PATHS
    )
    assert set(runner.EXPECTED_IMPLEMENTATION_CHANGE_STATUSES.values()) == {
        "A",
        "M",
    }


def test_governor_receives_exact_inherited_plan036_readiness(monkeypatch):
    expected_readiness = {
        "artifact": "valucast_pre2014_cross_role_readiness",
        "status": "ready",
    }
    calls = []

    def evaluator(**kwargs):
        calls.append(kwargs)
        return {"fixture": True}

    monkeypatch.setattr(
        runner.plan036,
        "_validate_governor_receipt",
        lambda receipt, **_kwargs: receipt,
    )
    result = runner._evaluate_current_governor(
        governor_evaluator=evaluator,
        reservation_id="reservation-037",
        research_contract={"contract": True},
        quality_starts={"sidecar": True},
        plan036_readiness=expected_readiness,
    )

    assert result == {"fixture": True}
    assert calls[0]["readiness"] is expected_readiness


def test_resume_cleans_only_exact_reservation_json_temps(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    evidence_path = tmp_path / "evidence.json"
    reservation_id = "existing-reservation-037"
    _write_json(
        result_path,
        {
            "reservation_id": reservation_id,
            "status": "reserved_before_outer_outcomes",
        },
    )
    owned = tmp_path / f".{evidence_path.name}.{reservation_id}.random.tmp"
    other = tmp_path / f".{evidence_path.name}.other-reservation.random.tmp"
    owned.write_text("partial", encoding="utf-8")
    other.write_text("keep", encoding="utf-8")
    replay = {
        "inherited_validation": {"status": "validated"},
        "canonical_outcomes": {},
        "labeled_contract": {},
        "quality_starts": {"sidecar": {"content_sha256": "d" * 64}},
        "fold_outputs": [],
        "current_role_shape_governor": {"passed": False},
        "evaluation": {
            "production_review_authorized": False,
            "decision": "production_review_not_authorized",
        },
    }

    monkeypatch.setattr(runner, "ROOT", tmp_path)
    runner._run_reserved_supersession(
        result_path=result_path,
        evidence_path=evidence_path,
        registered_readiness_sha256="a" * 64,
        registration_sha256="b" * 64,
        implementation_base_commit="c" * 40,
        execution_commit="e" * 40,
        supersedes=runner._expected_supersedes(),
        inherited_loader=lambda **_kwargs: {"fixture": True},
        replay_builder=lambda **_kwargs: replay,
        reservation_id=reservation_id,
        existing_reservation=True,
    )

    assert not owned.exists()
    assert other.read_text(encoding="utf-8") == "keep"
