"""No-outcome tests for the pre-2014 cross-role readiness artifact."""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest

import prospects.pre2014_readiness as readiness
from prospects.pre2014_readiness import (
    DRAFT_FACT_FIELDS,
    EXPECTED_COHORTS,
    MIN_CANDIDATES_PER_ROLE_FOLD,
    REGISTERED_IMPLEMENTATION_PATHS,
    REGISTERED_OUTER_FOLDS,
    REGISTERED_PREPARED_SOURCE_PATHS,
    REGISTERED_SOURCE_PATHS,
    build_pre2014_readiness,
)
from scripts import build_pre2014_cross_role_readiness as cli


def _json_bytes(payload) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


@pytest.fixture(scope="module")
def registered_replay_bundle():
    prepared = json.loads(
        (cli.DEFAULT_PREPARED).read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (cli.DEFAULT_PREPARED_MANIFEST).read_text(encoding="utf-8")
    )
    draft_facts = json.loads(
        (cli.DEFAULT_DRAFT_FACTS).read_text(encoding="utf-8")
    )
    source_bytes = {
        path: cli._git_bytes("cat-file", "blob", f"HEAD:{path}")
        for path in REGISTERED_PREPARED_SOURCE_PATHS
    }
    return prepared, manifest, draft_facts, source_bytes


def _replay(prepared, manifest, draft_facts, source_bytes):
    replay = getattr(readiness, "replay_pre2014_source_contract", None)
    assert callable(replay), "readiness is missing deterministic source replay"
    return replay(
        prepared,
        manifest,
        draft_facts,
        load_bytes=source_bytes.__getitem__,
    )


def test_registered_sources_replay_exact_prepared_and_draft_outputs(
    registered_replay_bundle,
):
    receipt = _replay(*registered_replay_bundle)

    assert set(receipt) == {
        "artifact",
        "schema_version",
        "inputs",
        "replay_counts",
        "prepared_output",
        "draft_facts_output",
    }
    assert receipt["artifact"] == "valucast_pre2014_source_replay"
    assert receipt["schema_version"] == 1
    assert [record["path"] for record in receipt["inputs"]] == list(
        REGISTERED_PREPARED_SOURCE_PATHS
    )
    assert receipt["replay_counts"] == {
        "milb_cohorts": 13,
        "draft_sources": 23,
        "prepared_sources": 50,
    }
    assert receipt["prepared_output"] == {
        "path": REGISTERED_SOURCE_PATHS["prepared_artifact"],
        "sha256": "8c681c09f95d471300f2d84f0bc933afc93ea0b5f7d7f5eb89f132cdd1baa66e",
        "candidate_count": 10_405,
    }
    assert receipt["draft_facts_output"] == {
        "path": REGISTERED_SOURCE_PATHS["draft_facts"],
        "sha256": "f87acb8b262968d1c1045128eb4a0d0425d414def50c3d2b224c28a41247ba2f",
        "candidate_id_count": 10_397,
    }


def test_replay_rejects_self_consistently_rehashed_raw_milb_divergence(
    registered_replay_bundle,
):
    prepared, manifest, draft_facts, source_bytes = registered_replay_bundle
    manifest = deepcopy(manifest)
    source_bytes = dict(source_bytes)
    path = (
        "data/research/extended_prospect_history/"
        "milb-source-responses/milb-2009.json"
    )
    payload = json.loads(source_bytes[path].decode("utf-8"))
    payload["stats"][0]["splits"][0]["stat"]["hits"] += 1
    source_bytes[path] = _json_bytes(payload)
    next(source for source in manifest["sources"] if source["path"] == path)[
        "sha256"
    ] = _sha256_bytes(source_bytes[path])

    with pytest.raises(ValueError, match="raw response hash mismatch"):
        _replay(prepared, manifest, draft_facts, source_bytes)


def test_replay_rejects_self_consistently_rehashed_checkpoint_divergence(
    registered_replay_bundle,
):
    prepared, manifest, draft_facts, source_bytes = registered_replay_bundle
    manifest = deepcopy(manifest)
    source_bytes = dict(source_bytes)
    path = (
        "data/research/extended_prospect_history/checkpoints/milb-2009.json"
    )
    payload = json.loads(source_bytes[path].decode("utf-8"))
    payload["rows"][0]["hits"] += 1
    payload["rows_sha256"] = _sha256_bytes(_json_bytes(payload["rows"]))
    source_bytes[path] = _json_bytes(payload)
    next(source for source in manifest["sources"] if source["path"] == path)[
        "sha256"
    ] = _sha256_bytes(source_bytes[path])

    with pytest.raises(ValueError, match="checkpoint parser output mismatch"):
        _replay(prepared, manifest, draft_facts, source_bytes)


def test_replay_rejects_self_consistently_rehashed_prepared_divergence(
    registered_replay_bundle,
):
    prepared, manifest, draft_facts, source_bytes = registered_replay_bundle
    prepared = deepcopy(prepared)
    manifest = deepcopy(manifest)
    prepared["rows"][0]["age"] += 1
    manifest["output"]["sha256"] = _sha256_bytes(_json_bytes(prepared))

    with pytest.raises(ValueError, match="prepared rows do not match source replay"):
        _replay(prepared, manifest, draft_facts, source_bytes)


def test_replay_rejects_self_consistently_rehashed_draft_facts_divergence(
    registered_replay_bundle,
):
    prepared, manifest, draft_facts, source_bytes = registered_replay_bundle
    manifest = deepcopy(manifest)
    draft_facts = deepcopy(draft_facts)
    first = next(iter(draft_facts.values()))
    first["bats"] = "L" if first["bats"] != "L" else "R"
    manifest["draft_facts_output"]["sha256"] = _sha256_bytes(
        _json_bytes(draft_facts)
    )

    with pytest.raises(ValueError, match="draft facts do not match source replay"):
        _replay(prepared, manifest, draft_facts, source_bytes)


def test_replay_rejects_self_consistently_rehashed_draft_receipt_divergence(
    registered_replay_bundle,
):
    prepared, manifest, draft_facts, source_bytes = registered_replay_bundle
    manifest = deepcopy(manifest)
    source_bytes = dict(source_bytes)
    response_path = (
        "data/research/extended_prospect_history/"
        "draft-source-responses/people-10.json"
    )
    response = json.loads(source_bytes[response_path].decode("utf-8"))
    person = response["people"][0]
    person["batSide"]["code"] = (
        "L" if person["batSide"]["code"] != "L" else "R"
    )
    source_bytes[response_path] = _json_bytes(response)
    next(
        source
        for source in manifest["sources"]
        if source["path"] == response_path
    )["sha256"] = _sha256_bytes(source_bytes[response_path])

    supplement_path = (
        "data/research/extended_prospect_history/draft-facts-supplement.json"
    )
    supplement = json.loads(source_bytes[supplement_path].decode("utf-8"))
    next(
        receipt
        for receipt in supplement["receipts"]
        if receipt["response_path"] == response_path
    )["response_sha256"] = _sha256_bytes(source_bytes[response_path])
    source_bytes[supplement_path] = _json_bytes(supplement)
    next(
        source
        for source in manifest["sources"]
        if source["path"] == supplement_path
    )["sha256"] = _sha256_bytes(source_bytes[supplement_path])

    with pytest.raises(
        ValueError, match="draft supplement facts differ from raw replay"
    ):
        _replay(prepared, manifest, draft_facts, source_bytes)


def test_actual_replay_receipt_passes_official_registered_readiness_validation(
    tmp_path,
    registered_replay_bundle,
):
    import scripts.run_pre2014_cross_role_gate as runner

    prepared, manifest, draft_facts, source_bytes = registered_replay_bundle

    implementation_commit = cli._git("rev-parse", "HEAD")

    def committed_record(path: str) -> dict[str, str]:
        git_blob = cli._git("rev-parse", f"{implementation_commit}:{path}")
        content = cli._git_bytes(
            "cat-file", "blob", f"{implementation_commit}:{path}"
        )
        return {
            "path": path,
            "sha256": _sha256_bytes(content),
            "git_blob": git_blob,
        }

    source_files = {
        key: committed_record(path)
        for key, path in REGISTERED_SOURCE_PATHS.items()
        if key != "current_prospect_contract"
    }
    source_files["current_prospect_contract"] = {
        "path": REGISTERED_SOURCE_PATHS["current_prospect_contract"],
        "git_blob": cli._git(
            "rev-parse",
            f"{implementation_commit}:"
            + REGISTERED_SOURCE_PATHS["current_prospect_contract"],
        ),
        "binding": "git_blob_only_pre_reservation",
    }
    prepared_source_files = [
        committed_record(path) for path in REGISTERED_PREPARED_SOURCE_PATHS
    ]
    implementation_files = [
        committed_record(path) for path in REGISTERED_IMPLEMENTATION_PATHS
    ]
    source_replay = _replay(prepared, manifest, draft_facts, source_bytes)
    result_path = cli.ROOT / readiness.REGISTERED_RESULT_PATH
    assert not result_path.exists()
    report = build_pre2014_readiness(
        prepared,
        manifest,
        draft_facts,
        source_files=source_files,
        implementation_files=implementation_files,
        prepared_source_files=prepared_source_files,
        source_replay=source_replay,
        implementation_base_commit=implementation_commit,
        result_path=readiness.REGISTERED_RESULT_PATH,
        result_path_exists=False,
    )
    assert report["status"] == "ready"

    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_bytes(_json_bytes(report))
    validated, _paths = runner.validate_registered_readiness(
        readiness_path,
        _sha256_bytes(readiness_path.read_bytes()),
        result_path,
        git_base_commit=implementation_commit,
    )

    assert validated["source_replay"] == source_replay


def _ready_bundle():
    rows = []
    next_id = 100_000

    def add(year: int, role: str, count: int) -> None:
        nonlocal next_id
        for _ in range(count):
            row = {
                "cohort_year": year,
                "mlbam_id": next_id,
                "role": role,
                "level": "AA",
                "age": 21,
            }
            if role == "hitter":
                row.update(
                    {
                        "iso": 0.18,
                        "k_pct": 20.0,
                        "bb_pct": 10.0,
                        "ops": 0.800,
                        "plate_appearances": 300,
                    }
                )
            else:
                row.update(
                    {
                        "k_per_9": 10.0,
                        "bb_per_9": 3.0,
                        "k_bb_pct": 20.0,
                        "era": 3.40,
                        "whip": 1.15,
                        "innings_pitched": 75.0,
                        "is_starter": True,
                    }
                )
            rows.append(row)
            next_id += 1

    for year in EXPECTED_COHORTS:
        if year == 2014:
            add(year, "hitter", 780)
            add(year, "pitcher", 779)
        elif year in REGISTERED_OUTER_FOLDS:
            add(year, "hitter", MIN_CANDIDATES_PER_ROLE_FOLD)
            add(year, "pitcher", MIN_CANDIDATES_PER_ROLE_FOLD)
        else:
            add(year, "hitter", 1)

    parity = {
        "status": "ready",
        "cohort_year": 2014,
        "candidate_count": 1559,
        "committed_count": 1559,
        "extra": [],
        "missing": [],
    }
    prepared = {
        "artifact": "valucast_extended_prospect_history_prepared",
        "mode": "prepare_only",
        "source_policy": {"outcomes_read": False, "labels_scored": False},
        "cohort_years": list(EXPECTED_COHORTS),
        "candidate_count": len(rows),
        "identity_parity": deepcopy(parity),
        "rows": rows,
    }
    manifest = {
        "artifact": "valucast_extended_prospect_history_source_manifest",
        "mode": "prepare_only",
        "output": {
            "path": REGISTERED_SOURCE_PATHS["prepared_artifact"],
            "sha256": "a" * 64,
        },
        "draft_facts_output": {
            "path": REGISTERED_SOURCE_PATHS["draft_facts"],
            "sha256": "c" * 64,
        },
        "identity_parity": deepcopy(parity),
        "sources": [
            {
                "kind": "milb_checkpoint",
                "path": "milb-2009.json",
                "sha256": "1" * 64,
            },
            {
                "kind": "committed_contract",
                "path": "prospect_model_inputs.json",
                "sha256": "2" * 64,
            },
        ],
    }
    draft_facts = {
        str(row["mlbam_id"]): {
            "draft_record_known": True,
            "rule4_drafted": False,
            "draft_year": None,
            "draft_pick_number": None,
            "draft_round": None,
            "signing_bonus": None,
            "pick_value": None,
            "school_type": None,
            "bats": "R",
            "throws": "R",
        }
        for row in rows
    }
    prepared_sha256 = _sha256_bytes(_json_bytes(prepared))
    draft_sha256 = _sha256_bytes(_json_bytes(draft_facts))
    manifest["output"]["sha256"] = prepared_sha256
    manifest["draft_facts_output"]["sha256"] = draft_sha256
    source_files = {
        key: {
            "path": path,
            "sha256": (format(index + 10, "x")[-1] * 64),
            "git_blob": (format(index + 1, "x")[-1] * 40),
        }
        for index, (key, path) in enumerate(REGISTERED_SOURCE_PATHS.items())
    }
    source_files["prepared_artifact"]["sha256"] = prepared_sha256
    source_files["prepared_manifest"]["sha256"] = "b" * 64
    source_files["draft_facts"]["sha256"] = draft_sha256
    source_files["current_prospect_contract"] = {
        "path": REGISTERED_SOURCE_PATHS["current_prospect_contract"],
        "git_blob": "d" * 40,
        "binding": "git_blob_only_pre_reservation",
    }
    implementation_files = [
        {
            "path": path,
            "sha256": (format(index + 1, "x")[-1] * 64),
            "git_blob": (format(index + 2, "x")[-1] * 40),
        }
        for index, path in enumerate(REGISTERED_IMPLEMENTATION_PATHS)
    ]
    prepared_source_files = [
        {
            "path": path,
            "sha256": (format(index + 3, "x")[-1] * 64),
            "git_blob": (format(index + 4, "x")[-1] * 40),
        }
        for index, path in enumerate(REGISTERED_PREPARED_SOURCE_PATHS)
    ]
    for record in prepared_source_files:
        if record["path"] == REGISTERED_SOURCE_PATHS["current_prospect_contract"]:
            record.update(source_files["current_prospect_contract"])
    manifest["sources"] = [
        {
            "kind": "registered_prepared_source",
            "path": record["path"],
            "sha256": record["sha256"],
        }
        for record in prepared_source_files
    ]
    source_replay = {
        "artifact": "valucast_pre2014_source_replay",
        "schema_version": 1,
        "inputs": [
            {"path": record["path"], "sha256": record["sha256"]}
            for record in prepared_source_files
        ],
        "replay_counts": {
            "milb_cohorts": 13,
            "draft_sources": 23,
            "prepared_sources": 50,
        },
        "prepared_output": {
            "path": REGISTERED_SOURCE_PATHS["prepared_artifact"],
            "sha256": source_files["prepared_artifact"]["sha256"],
            "candidate_count": len(rows),
        },
        "draft_facts_output": {
            "path": REGISTERED_SOURCE_PATHS["draft_facts"],
            "sha256": source_files["draft_facts"]["sha256"],
            "candidate_id_count": len(draft_facts),
        },
    }
    return (
        prepared,
        manifest,
        draft_facts,
        source_files,
        implementation_files,
        prepared_source_files,
        source_replay,
    )


def _audit(
    prepared,
    manifest,
    draft_facts,
    source_files,
    implementation_files,
    prepared_source_files,
    source_replay,
    *,
    result_exists=False,
):
    return build_pre2014_readiness(
        prepared,
        manifest,
        draft_facts,
        source_files=source_files,
        implementation_files=implementation_files,
        prepared_source_files=prepared_source_files,
        source_replay=source_replay,
        implementation_base_commit="f" * 40,
        result_path="data/validation/valucast_pre2014_cross_role_gate.json",
        result_path_exists=result_exists,
    )


def test_ready_artifact_authorizes_execution_but_no_claim_or_production_review():
    bundle = _ready_bundle()

    report = _audit(*bundle)

    assert report["artifact"] == "valucast_pre2014_cross_role_readiness"
    assert report["status"] == "ready"
    assert report["blockers"] == []
    assert report["look_spent"] is False
    assert report["execution_authorized"] is True
    assert report["claim_authorized"] is False
    assert report["production_review_authorized"] is False
    assert report["source_policy"] == {
        "phase": "pre_look",
        "reads_outcomes": False,
        "reads_mlb_seasons": False,
        "research_only": True,
    }
    assert report["candidate_audit"]["cohorts"] == list(EXPECTED_COHORTS)
    assert report["candidate_audit"]["cohort_2014_identity_count"] == 1559
    assert report["candidate_audit"]["duplicate_mlbam_role_keys"] == []
    assert report["candidate_audit"]["outcome_label_count"] == 0
    assert report["outer_fold_audit"]["registered_folds"] == list(
        REGISTERED_OUTER_FOLDS
    )
    for counts in report["outer_fold_audit"]["role_counts"].values():
        assert counts == {
            "hitter": MIN_CANDIDATES_PER_ROLE_FOLD,
            "pitcher": MIN_CANDIDATES_PER_ROLE_FOLD,
        }
    assert report["hashes"]["source_files"] == bundle[3]
    assert report["hashes"]["implementation_files"] == bundle[4]
    assert report["hashes"]["prepared_manifest_sources"] == [
        {
            "kind": "registered_prepared_source",
            "path": record["path"],
            "sha256": record["sha256"],
        }
        for record in bundle[5]
    ]
    assert report["hashes"]["prepared_source_files"] == bundle[5]
    assert report["source_replay"] == bundle[6]
    assert report["implementation_base_commit"] == "f" * 40
    assert report["draft_fact_audit"]["exact_candidate_id_set"] is True
    assert report["draft_fact_audit"]["invalid_record_count"] == 0


@pytest.mark.parametrize(
    ("case", "blocker"),
    [
        ("wrong_prepared_mode", "prepared_mode_not_prepare_only"),
        ("wrong_manifest_mode", "manifest_mode_not_prepare_only"),
        ("outcomes_read", "prepared_outcomes_read_not_false"),
        ("labels_scored", "prepared_labels_scored_not_false"),
        ("parity", "identity_parity_not_exact"),
        ("cohorts", "cohort_set_mismatch"),
        ("candidate_count", "candidate_count_mismatch"),
        ("duplicate", "duplicate_mlbam_role_identity"),
        ("outcome_label", "outcome_labels_present"),
        ("draft_coverage", "draft_fact_coverage_incomplete"),
        ("fold_role_count", "outer_fold_role_minimum_not_met"),
        ("result_exists", "result_path_already_exists"),
        ("wrong_result_path", "result_path_not_registered"),
        ("manifest_binding", "prepared_manifest_output_sha256_mismatch"),
        (
            "manifest_draft_binding",
            "prepared_manifest_draft_facts_sha256_mismatch",
        ),
        ("manifest_source_hash", "prepared_source_hashes_invalid"),
        ("source_replay", "source_replay_invalid"),
        (
            "manifest_source_binding",
            "prepared_manifest_source_binding_mismatch",
        ),
        ("missing_prepared_source", "prepared_source_path_set_mismatch"),
        (
            "missing_manifest_source",
            "prepared_manifest_source_path_set_mismatch",
        ),
        ("missing_implementation", "implementation_hashes_missing"),
        ("bad_implementation_hash", "implementation_hashes_invalid"),
        ("missing_implementation_path", "implementation_path_set_mismatch"),
        ("extra_implementation_path", "implementation_path_set_mismatch"),
        ("bad_base_commit", "implementation_base_commit_invalid"),
        ("missing_current_source", "source_file_path_set_mismatch"),
        ("sealed_source_sha256", "source_file_hashes_invalid"),
        ("sealed_source_bad_binding", "source_file_hashes_invalid"),
        ("noncanonical_source_path", "source_file_path_set_mismatch"),
        ("windows_source_path", "source_file_path_set_mismatch"),
        ("empty_draft_fact", "draft_fact_schema_invalid"),
        ("extra_draft_fact", "draft_fact_identity_set_mismatch"),
        ("bad_draft_consistency", "draft_fact_schema_invalid"),
        ("unscorable_candidate", "candidate_feature_eligibility_failed"),
    ],
)
def test_every_readiness_prerequisite_fails_closed(case, blocker):
    (
        prepared,
        manifest,
        draft,
        sources,
        implementations,
        prepared_sources,
        source_replay,
    ) = _ready_bundle()
    result_exists = False
    if case == "wrong_prepared_mode":
        prepared["mode"] = "execute_sealed_look"
    elif case == "wrong_manifest_mode":
        manifest["mode"] = "execute_sealed_look"
    elif case == "outcomes_read":
        prepared["source_policy"]["outcomes_read"] = True
    elif case == "labels_scored":
        prepared["source_policy"]["labels_scored"] = True
    elif case == "parity":
        manifest["identity_parity"]["committed_count"] = 1558
    elif case == "cohorts":
        prepared["cohort_years"] = [*EXPECTED_COHORTS, 2020]
    elif case == "candidate_count":
        prepared["candidate_count"] += 1
    elif case == "duplicate":
        prepared["rows"].append(deepcopy(prepared["rows"][0]))
        prepared["candidate_count"] += 1
    elif case == "outcome_label":
        prepared["rows"][0]["outcome"] = "star"
    elif case == "draft_coverage":
        draft.pop(str(prepared["rows"][0]["mlbam_id"]))
    elif case == "fold_role_count":
        index = next(
            i
            for i, row in enumerate(prepared["rows"])
            if row["cohort_year"] == 2017 and row["role"] == "pitcher"
        )
        prepared["rows"].pop(index)
        prepared["candidate_count"] -= 1
    elif case == "result_exists":
        result_exists = True
    elif case == "manifest_binding":
        manifest["output"]["sha256"] = "f" * 64
    elif case == "manifest_draft_binding":
        manifest["draft_facts_output"]["sha256"] = "f" * 64
    elif case == "manifest_source_hash":
        manifest["sources"][0]["sha256"] = "not-a-sha"
    elif case == "source_replay":
        source_replay["prepared_output"]["sha256"] = "0" * 64
    elif case == "manifest_source_binding":
        manifest["sources"][0]["sha256"] = "f" * 64
    elif case == "missing_prepared_source":
        prepared_sources.pop()
    elif case == "missing_manifest_source":
        manifest["sources"].pop()
    elif case == "missing_implementation":
        implementations.clear()
    elif case == "bad_implementation_hash":
        implementations[0]["sha256"] = "not-a-sha"
    elif case == "missing_implementation_path":
        implementations.pop()
    elif case == "extra_implementation_path":
        implementations.append(
            {
                "path": "prospects/not-registered.py",
                "sha256": "1" * 64,
                "git_blob": "2" * 40,
            }
        )
    elif case == "bad_base_commit":
        pass
    elif case == "missing_current_source":
        sources.pop("current_prospect_contract")
    elif case == "sealed_source_sha256":
        sources["current_prospect_contract"]["sha256"] = "1" * 64
    elif case == "sealed_source_bad_binding":
        sources["current_prospect_contract"]["binding"] = "sha256_pre_reservation"
    elif case == "noncanonical_source_path":
        sources["current_prospect_contract"]["path"] = str(
            (
                cli.ROOT
                / REGISTERED_SOURCE_PATHS["current_prospect_contract"]
            ).resolve()
        )
    elif case == "windows_source_path":
        sources["current_prospect_contract"]["path"] = (
            REGISTERED_SOURCE_PATHS["current_prospect_contract"].replace("/", "\\")
        )
    elif case == "empty_draft_fact":
        draft[str(prepared["rows"][0]["mlbam_id"])] = {}
    elif case == "extra_draft_fact":
        draft["999999999"] = deepcopy(next(iter(draft.values())))
    elif case == "bad_draft_consistency":
        fact = draft[str(prepared["rows"][0]["mlbam_id"])]
        fact["rule4_drafted"] = True
    elif case == "unscorable_candidate":
        pitcher = next(row for row in prepared["rows"] if row["role"] == "pitcher")
        pitcher.pop("k_per_9")

    base_commit = "bad" if case == "bad_base_commit" else "f" * 40
    result_path = (
        "data/validation/not-the-registered-result.json"
        if case == "wrong_result_path"
        else "data/validation/valucast_pre2014_cross_role_gate.json"
    )

    report = build_pre2014_readiness(
        prepared,
        manifest,
        draft,
        source_files=sources,
        implementation_files=implementations,
        prepared_source_files=prepared_sources,
        source_replay=source_replay,
        implementation_base_commit=base_commit,
        result_path=result_path,
        result_path_exists=result_exists,
    )

    assert blocker in report["blockers"]
    assert report["status"] == "blocked"
    assert report["execution_authorized"] is False
    assert report["claim_authorized"] is False
    assert report["production_review_authorized"] is False


def test_source_replay_requires_final_rows_to_remain_source_derived():
    (
        prepared,
        manifest,
        draft,
        sources,
        implementations,
        prepared_sources,
        source_replay,
    ) = _ready_bundle()
    moved = next(row for row in prepared["rows"] if row["cohort_year"] == 2014)
    moved["cohort_year"] = 2013

    report = _audit(
        prepared,
        manifest,
        draft,
        sources,
        implementations,
        prepared_sources,
        source_replay,
    )

    assert report["status"] == "blocked"
    assert "source_replay_invalid" in report["blockers"]
    assert report["execution_authorized"] is False
    assert report["candidate_audit"]["cohort_2014_identity_count"] == 1558
    assert report["candidate_audit"]["identity_parity"]["candidate_count"] == 1559


def test_cli_rejects_caller_selected_implementation_before_reading(monkeypatch):
    read_called = False

    def forbidden_read(_path):  # pragma: no cover - argparse must stop first
        nonlocal read_called
        read_called = True
        raise AssertionError("an input was read")

    monkeypatch.setattr(cli, "_read_bytes", forbidden_read)

    with pytest.raises(SystemExit):
        cli.main(["--implementation", "prospects/fake.py"])

    assert read_called is False


def test_registered_file_sets_are_exact_and_nonempty():
    assert tuple(REGISTERED_SOURCE_PATHS)[:3] == (
        "prepared_artifact",
        "prepared_manifest",
        "draft_facts",
    )
    assert len(REGISTERED_SOURCE_PATHS) == 17
    assert len(REGISTERED_PREPARED_SOURCE_PATHS) == 50
    assert len(REGISTERED_PREPARED_SOURCE_PATHS) == len(
        set(REGISTERED_PREPARED_SOURCE_PATHS)
    )
    assert (
        REGISTERED_SOURCE_PATHS["current_prospect_contract"]
        not in REGISTERED_PREPARED_SOURCE_PATHS
    )
    assert len(REGISTERED_IMPLEMENTATION_PATHS) == 50
    assert len(REGISTERED_IMPLEMENTATION_PATHS) == len(
        set(REGISTERED_IMPLEMENTATION_PATHS)
    )
    assert set(DRAFT_FACT_FIELDS) == {
        "draft_record_known",
        "rule4_drafted",
        "draft_year",
        "draft_pick_number",
        "draft_round",
        "signing_bonus",
        "pick_value",
        "school_type",
        "bats",
        "throws",
    }


def test_readiness_builder_rejects_any_dirty_or_untracked_tree(monkeypatch):
    monkeypatch.setattr(
        cli,
        "_git",
        lambda *args: "?? untracked.py" if args[0] == "status" else "",
    )

    with pytest.raises(ValueError, match="completely clean"):
        cli._require_clean_worktree()


def test_readiness_cleanliness_check_excludes_sealed_outcome_bytes(monkeypatch):
    calls = []

    def fake_git(*args):
        calls.append(args)
        return ""

    monkeypatch.setattr(cli, "_git", fake_git)

    cli._require_clean_worktree()

    assert calls == [
        (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude)"
            + REGISTERED_SOURCE_PATHS["current_prospect_contract"],
        )
    ]


def test_readiness_record_rejects_working_file_not_equal_to_commit_blob(
    monkeypatch,
):
    path = cli.ROOT / "registered.py"

    def fake_git(*args):
        return "1" * 40 if args[0] == "rev-parse" else "2" * 40

    monkeypatch.setattr(cli, "_git", fake_git)
    monkeypatch.setattr(cli, "_git_bytes", lambda *args: b"VALUE = 1\n")

    with pytest.raises(ValueError, match="differs from base commit"):
        cli._record(path, base_commit="f" * 40)


def test_outcome_contract_metadata_record_never_reads_worktree_or_blob_bytes(
    monkeypatch,
):
    path = cli.ROOT / REGISTERED_SOURCE_PATHS["current_prospect_contract"]
    calls = []

    def fake_git(*args):
        calls.append(args)
        if args[0] == "rev-parse":
            return "a" * 40
        if args[:2] == ("cat-file", "-t"):
            return "blob"
        raise AssertionError(f"unexpected git operation: {args}")

    monkeypatch.setattr(cli, "_git", fake_git)
    monkeypatch.setattr(
        cli,
        "_git_bytes",
        lambda *_args: (_ for _ in ()).throw(AssertionError("blob bytes read")),
    )
    monkeypatch.setattr(
        cli,
        "_read_bytes",
        lambda *_args: (_ for _ in ()).throw(AssertionError("file bytes read")),
    )

    record = cli._metadata_record(path, base_commit="f" * 40)

    assert record == {
        "path": REGISTERED_SOURCE_PATHS["current_prospect_contract"],
        "git_blob": "a" * 40,
        "binding": "git_blob_only_pre_reservation",
    }
    assert calls == [
        (
            "rev-parse",
            "f" * 40
            + ":"
            + REGISTERED_SOURCE_PATHS["current_prospect_contract"],
        ),
        ("cat-file", "-t", "a" * 40),
    ]


def test_readiness_replays_only_allowlisted_committed_source_blobs(monkeypatch):
    source_path = REGISTERED_PREPARED_SOURCE_PATHS[0]
    calls = []

    def fake_git_bytes(*args):
        calls.append(args)
        return b"sealed-source-bytes\n"

    monkeypatch.setattr(cli, "_git_bytes", fake_git_bytes)

    assert cli._committed_prepared_source_bytes(
        source_path, base_commit="f" * 40
    ) == b"sealed-source-bytes\n"
    assert calls == [
        ("cat-file", "blob", f"{'f' * 40}:{source_path}")
    ]
    with pytest.raises(ValueError, match="unregistered prepared source"):
        cli._committed_prepared_source_bytes(
            REGISTERED_SOURCE_PATHS["current_prospect_contract"],
            base_commit="f" * 40,
        )


def test_prepared_manifest_hashes_the_committed_source_bytes():
    manifest = json.loads(cli.DEFAULT_PREPARED_MANIFEST.read_text(encoding="utf-8"))
    sources = manifest["sources"]

    assert [source["path"] for source in sources] == list(
        REGISTERED_PREPARED_SOURCE_PATHS
    )
    for source in sources:
        content = cli._git_bytes("cat-file", "blob", f"HEAD:{source['path']}")
        assert hashlib.sha256(content).hexdigest() == source["sha256"]


def test_readiness_main_does_not_open_outcome_contract(monkeypatch):
    outcome_path = (
        cli.ROOT / REGISTERED_SOURCE_PATHS["current_prospect_contract"]
    ).resolve()
    captured = {}

    monkeypatch.setattr(cli, "_require_clean_worktree", lambda: None)
    monkeypatch.setattr(cli, "_guard_output", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "_git", lambda *_args: "f" * 40)

    def fake_read(path):
        if path.resolve() == outcome_path:
            raise AssertionError("outcome-bearing contract opened before reservation")
        return b"{}"

    monkeypatch.setattr(cli, "_read_bytes", fake_read)
    monkeypatch.setattr(
        cli,
        "_record",
        lambda path, *, base_commit: {
            "path": cli._repo_path(path),
            "sha256": "1" * 64,
            "git_blob": "2" * 40,
        },
    )
    monkeypatch.setattr(
        cli,
        "_metadata_record",
        lambda path, *, base_commit: {
            "path": cli._repo_path(path),
            "git_blob": "3" * 40,
            "binding": "git_blob_only_pre_reservation",
        },
    )
    monkeypatch.setattr(cli, "replay_pre2014_source_contract", lambda *_a, **_k: {})

    def fake_build(*_args, **kwargs):
        captured.update(kwargs["source_files"])
        return {
            "status": "ready",
            "blockers": [],
            "execution_authorized": True,
        }

    monkeypatch.setattr(cli, "build_pre2014_readiness", fake_build)
    monkeypatch.setattr(cli, "_write_atomic", lambda *_args, **_kwargs: None)

    assert cli.main([]) == 0
    assert captured["current_prospect_contract"] == {
        "path": REGISTERED_SOURCE_PATHS["current_prospect_contract"],
        "git_blob": "3" * 40,
        "binding": "git_blob_only_pre_reservation",
    }


def test_cli_has_no_outcome_or_mlb_season_input_surface(tmp_path, monkeypatch):
    read_called = False

    def forbidden_read(_path):  # pragma: no cover - argparse must stop first
        nonlocal read_called
        read_called = True
        raise AssertionError("an input was read")

    monkeypatch.setattr(cli, "_read_bytes", forbidden_read)

    with pytest.raises(SystemExit):
        cli.main(["--outcome-cache", str(tmp_path / "outcomes.json")])

    assert read_called is False
