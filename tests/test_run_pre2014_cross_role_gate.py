import base64
from contextlib import contextmanager
import hashlib
import http.client
import json
import zlib
from pathlib import Path

import pytest

from prospects.pre2014_cross_role_gate import DIRECT_METRIC
from prospects.pre2014_readiness import (
    REGISTERED_IMPLEMENTATION_PATHS,
    REGISTERED_PREPARED_SOURCE_PATHS,
    REGISTERED_SOURCE_PATHS,
)
import scripts.run_pre2014_cross_role_gate as runner_module
from scripts.run_pre2014_cross_role_gate import (
    _run_sealed_adjudication,
    parse_strict_statsapi_seasons,
    run_registered_adjudication,
)


OUTER_FOLDS = (2017, 2018, 2019, 2021)
CANDIDATE_FLAGS = {
    "PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"
}
INCUMBENT_FLAGS = {"PITCHER_INVESTMENT_FEATURE_MODE": "incumbent"}


def _compressed_fields(raw):
    compressed = zlib.compress(raw, level=9)
    return {
        "raw_encoding": "zlib+base64",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_byte_count": len(raw),
        "compressed_sha256": hashlib.sha256(compressed).hexdigest(),
        "compressed_byte_count": len(compressed),
        "compressed_body_base64": base64.b64encode(compressed).decode("ascii"),
    }


def test_evidence_file_record_uses_canonical_repo_relative_posix_path(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(runner_module, "ROOT", tmp_path)
    path = tmp_path / "data" / "validation" / "terminal-evidence.json"

    record = runner_module._write_evidence(path, {"fixture": True})

    assert record["path"] == "data/validation/terminal-evidence.json"
    assert "\\" not in record["path"]
    assert ":" not in record["path"]


@pytest.mark.parametrize(
    ("fetch", "args"),
    [
        (runner_module._fetch_strict_statsapi_with_receipt, (101, "hitter")),
        (runner_module._fetch_strict_qs_game_log_with_receipt, (202, 2024)),
    ],
)
def test_incomplete_http_response_is_retryable_transport_receipt(fetch, args):
    class PartialResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            raise http.client.IncompleteRead(b"partial", 100)

    resolved, receipt = fetch(*args, opener=lambda *_args, **_kwargs: PartialResponse())

    assert resolved is None
    assert receipt["status"] == "unresolved_transport"
    assert receipt["error_type"] == "IncompleteRead"


def _write_json(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(runner_module.ROOT.resolve()).as_posix()


def _fixture_source_replay(prepared, manifest, draft_facts, *, load_bytes):
    inputs = [
        {
            "path": path,
            "sha256": hashlib.sha256(load_bytes(path)).hexdigest(),
        }
        for path in REGISTERED_PREPARED_SOURCE_PATHS
    ]
    return {
        "artifact": "valucast_pre2014_source_replay",
        "schema_version": 1,
        "inputs": inputs,
        "replay_counts": {
            "milb_cohorts": 13,
            "draft_sources": 23,
            "prepared_sources": 50,
        },
        "prepared_output": {
            "path": manifest["output"]["path"],
            "sha256": manifest["output"]["sha256"],
            "candidate_count": len(prepared["rows"]),
        },
        "draft_facts_output": {
            "path": manifest["draft_facts_output"]["path"],
            "sha256": manifest["draft_facts_output"]["sha256"],
            "candidate_id_count": len(draft_facts),
        },
    }


def _outcome_attempt(mlbam_id, role, seasons):
    splits = []
    for season in seasons:
        stat = (
            {
                "plateAppearances": season["pa"],
                "ops": season["ops"],
            }
            if role == "hitter"
            else {
                "inningsPitched": str(season["ip"]),
                "era": season["era"],
            }
        )
        splits.append({
            "season": str(season["year"]),
            "sport": {"id": 1},
            "player": {"id": int(mlbam_id)},
            "gameType": "R",
            "stat": stat,
        })
    payload = (
        {"copyright": "fixture", "stats": []}
        if not splits
        else {
            "stats": [{
                "type": {"displayName": "yearByYear"},
                "group": {
                    "displayName": "hitting" if role == "hitter" else "pitching"
                },
                "splits": splits,
            }]
        }
    )
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return {
        "mlbam_id": int(mlbam_id),
        "role": role,
        "provider": "MLB StatsAPI",
        "endpoint": "yearByYear",
        "http_status": 200,
        **_compressed_fields(raw),
        "status": "resolved",
        "season_count": len(seasons),
    }


def _qs_attempt(mlbam_id, season, games):
    payload = {
        "stats": [{
            "type": {"displayName": "gameLog"},
            "group": {"displayName": "pitching"},
            "splits": games,
        }]
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return {
        "mlbam_id": int(mlbam_id),
        "season": int(season),
        "provider": "MLB StatsAPI",
        "stat": "gameLog",
        "group": "pitching",
        "game_type": "R",
        "http_status": 200,
        **_compressed_fields(raw),
        "status": "resolved",
        "game_count": len(games),
    }


def _prepared_rows():
    rows = []
    for year in range(2009, 2017):
        for role_index, role in enumerate(("hitter", "pitcher")):
            mlbam_id = year * 1000 + 800 + role_index
            rows.append(
                {
                    "mlbam_id": mlbam_id,
                    "name": f"Calibration {mlbam_id}",
                    "role": role,
                    "cohort_year": year,
                }
            )
    for year in OUTER_FOLDS:
        for role_index, role in enumerate(("hitter", "pitcher")):
            for index in range(63):
                mlbam_id = year * 1000 + role_index * 100 + index
                rows.append(
                    {
                        "mlbam_id": mlbam_id,
                        "name": f"Player {mlbam_id}",
                        "role": role,
                        "cohort_year": year,
                    }
                )
    for role_index, role in enumerate(("hitter", "pitcher")):
        mlbam_id = 2022 * 1000 + role_index * 100
        rows.append(
            {
                "mlbam_id": mlbam_id,
                "name": f"Immature {mlbam_id}",
                "role": role,
                "cohort_year": 2022,
            }
        )
    return rows


def _sealed_inputs(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    runner_module.ROOT = tmp_path
    result_path = tmp_path / "sealed-result.json"
    prepared_path = tmp_path / REGISTERED_SOURCE_PATHS["prepared_artifact"]
    manifest_path = tmp_path / REGISTERED_SOURCE_PATHS["prepared_manifest"]
    draft_path = tmp_path / REGISTERED_SOURCE_PATHS["draft_facts"]
    readiness_path = tmp_path / "readiness.json"

    rows = _prepared_rows()
    prepared = {
        "artifact": "valucast_extended_prospect_history_prepared",
        "mode": "prepare_only",
        "source_policy": {"outcomes_read": False, "labels_scored": False},
        "cohort_years": [*range(2009, 2020), 2021, 2022],
        "identity_parity": {
            "status": "ready",
            "cohort_year": 2014,
            "candidate_count": 1559,
            "committed_count": 1559,
            "extra": [],
            "missing": [],
        },
        "rows": rows,
    }
    prepared_sha = _write_json(prepared_path, prepared)
    draft_sha = _write_json(
        draft_path,
        {str(row["mlbam_id"]): {} for row in rows},
    )
    _write_json(
        manifest_path,
        {
            "artifact": "valucast_extended_prospect_history_source_manifest",
            "mode": "prepare_only",
            "output": {"path": _repo_relative(prepared_path), "sha256": prepared_sha},
            "draft_facts_output": {
                "path": _repo_relative(draft_path),
                "sha256": draft_sha,
            },
        },
    )
    source_payloads = {
        "prepared_artifact": prepared,
        "prepared_manifest": json.loads(manifest_path.read_text(encoding="utf-8")),
        "draft_facts": json.loads(draft_path.read_text(encoding="utf-8")),
    }
    source_records = {}
    for key, relative_path in REGISTERED_SOURCE_PATHS.items():
        path = tmp_path / relative_path
        sha256 = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if key in source_payloads
            else _write_json(path, {"fixture": key})
        )
        source_records[key] = (
            {
                "path": relative_path,
                "git_blob": "1" * 40,
                "binding": "git_blob_only_pre_reservation",
            }
            if key == "current_prospect_contract"
            else {
                "path": relative_path,
                "sha256": sha256,
                "git_blob": "1" * 40,
            }
        )
    implementation_records = []
    for relative_path in REGISTERED_IMPLEMENTATION_PATHS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# frozen fixture: {relative_path}\n", encoding="utf-8")
        implementation_records.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "git_blob": "2" * 40,
            }
        )
    implementation_path = tmp_path / REGISTERED_IMPLEMENTATION_PATHS[0]
    prepared_source_records = []
    for relative_path in REGISTERED_PREPARED_SOURCE_PATHS:
        path = tmp_path / relative_path
        sha256 = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.exists()
            else _write_json(path, {"prepared_source_fixture": relative_path})
        )
        prepared_source_records.append(
            {
                "path": relative_path,
                "sha256": sha256,
                "git_blob": "4" * 40,
            }
        )
    source_replay = _fixture_source_replay(
        prepared,
        source_payloads["prepared_manifest"],
        source_payloads["draft_facts"],
        load_bytes=lambda relative_path: (tmp_path / relative_path).read_bytes(),
    )
    readiness = {
        "artifact": "valucast_pre2014_cross_role_readiness",
        "schema_version": 1,
        "status": "ready",
        "blockers": [],
        "look_spent": False,
        "execution_authorized": True,
        "claim_authorized": False,
        "production_review_authorized": False,
        "implementation_base_commit": "3" * 40,
        "source_replay": source_replay,
        "source_policy": {
            "phase": "pre_look",
            "reads_outcomes": False,
            "reads_mlb_seasons": False,
            "research_only": True,
        },
        "candidate_audit": {
            "cohorts": [*range(2009, 2020), 2021, 2022],
            "identity_parity": prepared["identity_parity"],
        },
        "outer_fold_audit": {"registered_folds": list(OUTER_FOLDS)},
        "result": {
            "path": _repo_relative(result_path),
            "exists": False,
            "unspent": True,
        },
        "hashes": {
            "source_files": source_records,
            "prepared_manifest_sources": [
                {
                    "kind": "registered_prepared_source",
                    "path": relative_path,
                    "sha256": record["sha256"],
                }
                for record, relative_path in zip(
                    prepared_source_records,
                    REGISTERED_PREPARED_SOURCE_PATHS,
                    strict=True,
                )
            ],
            "prepared_source_files": prepared_source_records,
            "implementation_files": implementation_records,
        },
    }
    readiness_sha = _write_json(readiness_path, readiness)
    outcomes = {
        f"{row['mlbam_id']}_{row['role']}": []
        for row in rows
    }
    return {
        "readiness_path": readiness_path,
        "readiness_sha": readiness_sha,
        "result_path": result_path,
        "rows": rows,
        "outcomes": outcomes,
        "implementation_path": implementation_path,
    }


def _execution_registration(inputs, tmp_path):
    readiness = json.loads(inputs["readiness_path"].read_text(encoding="utf-8"))
    hashes = readiness["hashes"]
    source = hashes["source_files"]
    return {
        "protocol": runner_module.PROTOCOL,
        "registered_at": "2026-08-11T00:00:00Z",
        "status": "registered",
        "look_spent": False,
        "execution_authorized": True,
        "research_only": True,
        "automatic_promotion": False,
        "claim_authorized": False,
        "implementation_base_commit": readiness["implementation_base_commit"],
        "readiness": {
            "path": _repo_relative(inputs["readiness_path"]),
            "sha256": inputs["readiness_sha"],
        },
        "result_path": _repo_relative(inputs["result_path"]),
        "source_contract": {
            "prepared_path": source["prepared_artifact"]["path"],
            "prepared_sha256": source["prepared_artifact"]["sha256"],
            "prepared_manifest_path": source["prepared_manifest"]["path"],
            "prepared_manifest_sha256": source["prepared_manifest"]["sha256"],
            "draft_facts_path": source["draft_facts"]["path"],
            "draft_facts_sha256": source["draft_facts"]["sha256"],
            "cohorts": [*range(2009, 2020), 2021, 2022],
            "declared_omissions": [2020],
            "outcome_complete_through": 2025,
            "outcome_horizon_years": 4,
            "identity_key": "mlbam_id+role",
            "parity": {
                "status": "ready",
                "cohort_year": 2014,
                "candidate_count": 1559,
                "committed_count": 1559,
                "extra": [],
                "missing": [],
            },
        },
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
        "outer_folds": list(OUTER_FOLDS),
        "bootstrap": json.loads(json.dumps(runner_module.EXPECTED_BOOTSTRAP)),
        "primary_endpoint": DIRECT_METRIC,
        "thresholds": json.loads(json.dumps(runner_module.EXPECTED_THRESHOLDS)),
        "governor": dict(runner_module.EXPECTED_GOVERNOR),
        "hashes": hashes,
        "result_contract": {
            "single_use": True,
            "claim_authorized": False,
            "automatic_promotion": False,
            "terminal_evidence_path": _repo_relative(tmp_path / "evidence.json"),
            "acquisition_checkpoint_path": _repo_relative(
                tmp_path / "checkpoint.json"
            ),
            "outcome_cutoff_date": "2025-12-31",
        },
        "limitations": ["cohort-season-completion pseudo-replay"],
    }


@pytest.mark.parametrize(
    "mutation",
    [
        lambda registration: registration.update(unregistered_field=True),
        lambda registration: registration["candidate"]["head_blend"].update(
            outcome=0.57
        ),
        lambda registration: registration["bootstrap"].update(resamples=9999),
        lambda registration: registration["thresholds"].update(
            minimum_outer_folds=3
        ),
        lambda registration: registration["governor"].update(
            max_top25_pitcher_count=999
        ),
        lambda registration: registration["source_contract"].update(
            cohorts=[*range(2009, 2020), 2021]
        ),
        lambda registration: registration.update(limitations=[]),
    ],
)
def test_execution_registration_rejects_exact_contract_drift_before_spend(
    tmp_path, monkeypatch, mutation
):
    inputs = _sealed_inputs(tmp_path)
    evidence_path = tmp_path / "evidence.json"
    checkpoint_path = tmp_path / "checkpoint.json"
    monkeypatch.setattr(
        runner_module, "REGISTERED_READINESS_PATH", inputs["readiness_path"]
    )
    monkeypatch.setattr(
        runner_module, "REGISTERED_RESULT_PATH", inputs["result_path"]
    )
    monkeypatch.setattr(runner_module, "REGISTERED_EVIDENCE_PATH", evidence_path)
    monkeypatch.setattr(
        runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint_path
    )
    readiness = json.loads(
        inputs["readiness_path"].read_text(encoding="utf-8")
    )
    registration = _execution_registration(inputs, tmp_path)

    assert runner_module._validate_execution_registration(
        registration, readiness
    ) == (inputs["readiness_sha"], "3" * 40)
    mutation(registration)
    with pytest.raises(ValueError, match="registration"):
        runner_module._validate_execution_registration(registration, readiness)
    assert not inputs["result_path"].exists()
    assert not evidence_path.exists()
    assert not checkpoint_path.exists()


@pytest.fixture(autouse=True)
def _registered_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_module, "ROOT", tmp_path)
    monkeypatch.setattr(
        runner_module,
        "replay_pre2014_source_contract",
        _fixture_source_replay,
    )


def _fold_scorer(contract, year):
    rows = [row for row in contract["rows"] if row["cohort_year"] == year]
    identities = [(str(row["mlbam_id"]), row["role"]) for row in rows]
    targets = {}
    incumbent = {}
    candidate = {}
    for index, identity in enumerate(identities):
        direct_target = index / (len(identities) - 1)
        targets[identity] = {
            "outcome": ("bust", "role", "star")[min(index // 42, 2)],
            "outcome_tier": min(index // 42, 2) / 2,
            "direct_7x7_target": direct_target,
        }
        incumbent[identity] = (
            direct_target if index % 5 == 0 else 1.0 - direct_target
        )
        candidate[identity] = direct_target
    inner_years = list(range(2009, year - 3))
    return {
        "scores": {"incumbent": incumbent, "candidate": candidate},
        "targets": targets,
        "calibrator_hashes": {
            "hitter.outcome": "a" * 64,
            "hitter.impact": "b" * 64,
            "pitcher.outcome": "c" * 64,
            "pitcher.impact": "d" * 64,
        },
        "metadata": {
            "outer_year": year,
            "train_through": year - 4,
            "inner_fold_years": inner_years,
            "calibration_mature_through": year - 4,
            "calibration_strategy": (
                "leave_one_cohort_out_within_outer_mature_pool"
            ),
            "identity_count": len(identities),
            "outer_reference_sha256": "e" * 64,
            "candidate_model_flags": CANDIDATE_FLAGS,
            "incumbent_model_flags": INCUMBENT_FLAGS,
            "quality_starts_sha256": contract["quality_starts"]["content_sha256"],
        },
        "diagnostics": {
            "identity_sets_equal": True,
            "inner_folds": [
                {
                    "test_year": inner_year,
                    "target_complete_by": inner_year + 4,
                    "train_through": max(
                        candidate_year
                        for candidate_year in inner_years
                        if candidate_year != inner_year
                    ),
                    "training_strategy": "leave_one_cohort_out",
                    "reference_sha256": "f" * 64,
                    "raw_scorer": {"fixture": True},
                }
                for inner_year in inner_years
            ],
            "outer": {
                "incumbent_rank": {
                    "model_score_mode": "incumbent_role_quantile"
                },
                "candidate_rank": {"model_score_mode": "common_target"},
            },
        },
    }


def _ready_qs(contract, reservation_id):
    assert contract["artifact"] == "valucast_extended_prospect_history_labeled"
    assert contract["source_policy"]["horizon_years"] == 4
    assert reservation_id
    rows = []
    for identity, seasons in contract["historical_mlb_seasons"].items():
        if not identity.endswith("_pitcher"):
            continue
        mlbam_id = int(identity.removesuffix("_pitcher"))
        for season in seasons:
            rows.append(
                {
                    "mlbam_id": mlbam_id,
                    "season": int(season["year"]),
                    "games_started": int(season.get("gs") or 0),
                    "quality_starts": int(season.get("qs") or 0),
                    "provenance": "synthetic_fixture",
                }
            )
    quality_input = runner_module._quality_starts_input_payload(contract)
    sidecar = {
        "schema": "valucast_stage2_quality_starts",
        "version": "1.0.0",
        "status": "ready",
        "source": dict(runner_module.QUALITY_STARTS_SOURCE),
        "input": {
            "kind": "embedded_json",
            "document_path": "sealed-result-evidence.json",
            "json_pointer": "/quality_starts/input_contract",
            "sha256": runner_module._canonical_payload_sha256(quality_input),
            "cutoff_date": "2025-12-31",
        },
        "coverage": {
            "source_rows": len(rows),
            "unique_player_seasons": len(rows),
            "resolved_player_seasons": len(rows),
            "post_join_rows_with_qs": len(rows),
        },
        "validation": {
            "existing_values_checked": 0,
            "existing_value_mismatches": [],
            "current_season_values_superseded": [],
            "games_started_mismatches": [],
            "duplicate_value_conflicts": [],
        },
        "rows": rows,
        "blockers": [],
        "reservation_id": reservation_id,
    }
    encoded = json.dumps(sidecar, sort_keys=True, separators=(",", ":")).encode()
    sidecar["content_sha256"] = hashlib.sha256(encoded).hexdigest()
    return sidecar


def _passing_governor(**kwargs):
    assert "candidate_model_flags" not in kwargs
    assert "model_score_mode" not in kwargs
    assert kwargs["reservation_id"]
    assert kwargs["research_contract"]["quality_starts"]["status"] == "ready"
    assert kwargs["quality_starts"] is kwargs["research_contract"]["quality_starts"]
    assert kwargs["readiness"]["execution_authorized"] is True
    receipt = {
        "passed": True,
        "unchanged_thresholds": True,
        "candidate_model_flags": CANDIDATE_FLAGS,
        "model_score_mode": "common_target",
        "reservation_id": kwargs["reservation_id"],
        "governor_scope": "prospect_top_board_role_shape",
        "full_governor_required_at": "post_look_pre_publication",
        "role_shape_governor_check": {
            "id": "prospect_top_board_role_shape",
            "status": "passed",
            "metrics": {
                "max_top25_pitcher_count": 7,
                "max_top50_pitcher_rate": 0.3,
            },
        },
    }
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    return {**receipt, "receipt_sha256": hashlib.sha256(encoded).hexdigest()}


def _run(inputs, *, outcome_acquirer=None, qs_builder=_ready_qs,
         fold_scorer=_fold_scorer, governor_evaluator=_passing_governor):
    if outcome_acquirer is None:
        def outcome_acquirer(**kwargs):
            marker = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
            assert marker["status"] == "reserved_before_outer_outcomes"
            assert kwargs["reservation_id"] == marker["reservation_id"]
            assert max(row["cohort_year"] for row in kwargs["prepared"]["rows"]) == 2021
            mature_keys = {
                f"{row['mlbam_id']}_{row['role']}"
                for row in kwargs["prepared"]["rows"]
            }
            return {
                key: value
                for key, value in inputs["outcomes"].items()
                if key in mature_keys
            }

    return _run_sealed_adjudication(
        readiness_path=inputs["readiness_path"],
        registered_readiness_sha256=inputs["readiness_sha"],
        result_path=inputs["result_path"],
        outcome_acquirer=outcome_acquirer,
        quality_starts_builder=qs_builder,
        governor_evaluator=governor_evaluator,
        fold_scorer=fold_scorer,
        reservation_id="fixed-reservation",
    )


def test_official_executor_has_no_caller_selected_paths_or_callbacks():
    import inspect

    assert list(inspect.signature(run_registered_adjudication).parameters) == []


def test_runner_reserves_then_builds_scores_and_finalizes_one_permanent_result(tmp_path):
    inputs = _sealed_inputs(tmp_path)

    result = _run(inputs)

    committed = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
    assert result == committed
    assert result["artifact"] == "valucast_pre2014_cross_role_gate"
    assert result["protocol"] == "plan_036_pre2014_cross_role_calibration"
    assert result["candidate"] == {
        "model_flags": CANDIDATE_FLAGS,
        "model_score_mode": "common_target",
    }
    assert result["outer_folds"] == list(OUTER_FOLDS)
    assert result["evaluation"]["readiness"]["outer_folds"] == list(OUTER_FOLDS)
    assert result["evaluation"]["production_review_authorized"] is True
    assert result["claim_authorized"] is False
    assert result["current_role_shape_governor"]["passed"] is True
    assert set(result["evidence_bundle"]) == {"terminal_evidence"}
    for record in result["evidence_bundle"].values():
        evidence_path = runner_module.ROOT / record["path"]
        assert evidence_path.exists()
        assert hashlib.sha256(evidence_path.read_bytes()).hexdigest() == record["sha256"]
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        assert evidence["reservation_id"] == result["reservation_id"]
        assert evidence["status"] == result["status"]
        assert evidence["fold_outputs"] == result["fold_outputs"]
    assert all(
        fold["metric"] == DIRECT_METRIC and len(fold["players"]) == 126
        for fold in result["fold_outputs"]
    )
    first_fold = result["fold_outputs"][0]
    assert first_fold["coverage_by_role"] == {
        "hitter": {
            "eligible_identity_count": 63,
            "scored_outcome_count": 63,
            "rate": 1.0,
        },
        "pitcher": {
            "eligible_identity_count": 63,
            "scored_outcome_count": 63,
            "rate": 1.0,
        },
    }
    assert set(first_fold["top25_ordinal_regret"]) == {"incumbent", "candidate"}
    assert set(first_fold["role_concordance"]) == {"hitter", "pitcher"}
    assert {
        "outcome_tier",
        "incumbent_score",
        "candidate_score",
        "direct_7x7_target",
    }.issubset(first_fold["players"][0])
    assert (
        "cross_role_concordance_improvement_contribution"
        not in first_fold["players"][0]
    )

    committed_bytes = inputs["result_path"].read_bytes()
    with pytest.raises(FileExistsError):
        _run(inputs)
    assert inputs["result_path"].read_bytes() == committed_bytes


def test_runner_holds_run_lease_through_acquisition_and_finalization(
    tmp_path, monkeypatch
):
    inputs = _sealed_inputs(tmp_path)
    active = False

    @contextmanager
    def lease(path, reservation_id):
        nonlocal active
        assert path == inputs["result_path"]
        assert reservation_id == "fixed-reservation"
        active = True
        try:
            yield
        finally:
            active = False

    def acquired(**_kwargs):
        assert active is True
        return {
            key: value
            for key, value in inputs["outcomes"].items()
            if not key.startswith("2022")
        }

    monkeypatch.setattr(
        runner_module, "sealed_result_run_lease", lease, raising=False
    )
    result = _run(inputs, outcome_acquirer=acquired)

    assert result["status"] == "passed"
    assert active is False


@pytest.mark.parametrize("mutation", ["readiness_sha", "implementation"])
def test_runner_stops_before_reservation_or_outcomes_on_any_hash_mismatch(
    tmp_path, mutation
):
    inputs = _sealed_inputs(tmp_path)
    called = False

    def forbidden(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("outcomes must not be accessed")

    if mutation == "readiness_sha":
        inputs["readiness_sha"] = "0" * 64
    else:
        inputs["implementation_path"].write_text("FROZEN = False\n", encoding="utf-8")

    with pytest.raises(ValueError, match="hash"):
        _run(inputs, outcome_acquirer=forbidden)
    assert called is False
    assert inputs["result_path"].exists() is False


def test_runner_stops_before_reservation_when_readiness_is_not_authorized(tmp_path):
    inputs = _sealed_inputs(tmp_path)
    readiness = json.loads(inputs["readiness_path"].read_text(encoding="utf-8"))
    readiness["status"] = "blocked"
    readiness["execution_authorized"] = False
    readiness["blockers"] = ["synthetic_blocker"]
    inputs["readiness_sha"] = _write_json(inputs["readiness_path"], readiness)

    with pytest.raises(ValueError, match="readiness is not authorized"):
        _run(inputs)
    assert inputs["result_path"].exists() is False


def test_any_post_reservation_failure_is_permanently_spent(tmp_path):
    inputs = _sealed_inputs(tmp_path)

    def broken_acquirer(**_kwargs):
        raise RuntimeError("synthetic outcome failure")

    with pytest.raises(RuntimeError, match="synthetic outcome failure"):
        _run(inputs, outcome_acquirer=broken_acquirer)

    spent = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
    assert spent["status"] == "spent_error"
    assert spent["claim_authorized"] is False
    assert set(spent["evidence_bundle"]) == {"terminal_evidence"}
    evidence_record = spent["evidence_bundle"]["terminal_evidence"]
    evidence = json.loads(
        (runner_module.ROOT / evidence_record["path"]).read_text(encoding="utf-8")
    )
    assert evidence["status"] == "spent_error"
    assert evidence["reservation_id"] == spent["reservation_id"]
    with pytest.raises(FileExistsError):
        _run(inputs)


def test_post_reservation_pre_evidence_failure_is_permanently_spent(
    tmp_path, monkeypatch
):
    inputs = _sealed_inputs(tmp_path)
    original = runner_module.validate_registered_readiness
    calls = 0

    def fail_second_validation(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError("synthetic post-reservation validation failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(
        runner_module,
        "validate_registered_readiness",
        fail_second_validation,
    )

    with pytest.raises(
        ValueError, match="synthetic post-reservation validation failure"
    ):
        _run(inputs)

    spent = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
    assert calls == 2
    assert spent["status"] == "spent_error"
    evidence_record = spent["evidence_bundle"]["terminal_evidence"]
    evidence = json.loads(
        (runner_module.ROOT / evidence_record["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert evidence["status"] == "spent_error"
    assert evidence["error_type"] == "ValueError"


def test_post_reservation_temp_cleanup_failure_is_permanently_spent(
    tmp_path, monkeypatch
):
    inputs = _sealed_inputs(tmp_path)

    def broken_cleanup(*_args, **_kwargs):
        raise PermissionError("synthetic cleanup failure")

    monkeypatch.setattr(
        runner_module, "_cleanup_bound_runtime_json_temps", broken_cleanup
    )

    with pytest.raises(PermissionError, match="synthetic cleanup failure"):
        _run(inputs)

    spent = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
    assert spent["status"] == "spent_error"
    assert spent["error_type"] == "PermissionError"


def test_spent_evidence_write_fallback_preserves_execution_context(
    tmp_path, monkeypatch
):
    inputs = _sealed_inputs(tmp_path)
    original = runner_module._write_evidence
    writes = 0

    def fail_first_spent_write(path, payload):
        nonlocal writes
        writes += 1
        if writes == 2:
            raise OSError("synthetic evidence persistence failure")
        return original(path, payload)

    def broken_acquirer(**_kwargs):
        raise RuntimeError("synthetic outcome failure")

    context = {
        "registration_sha256": "a" * 64,
        "execution_commit": "b" * 40,
        "registration_path": "plans/036-pre2014-cross-role-calibration-gate.md",
        "acquisition_checkpoint_path": (
            "data/research/extended_prospect_history/"
            "sealed-acquisition-checkpoint.json"
        ),
        "outcome_cutoff_date": "2025-12-31",
    }
    monkeypatch.setattr(runner_module, "_write_evidence", fail_first_spent_write)

    with pytest.raises(RuntimeError, match="synthetic outcome failure"):
        runner_module._run_sealed_adjudication(
            readiness_path=inputs["readiness_path"],
            registered_readiness_sha256=inputs["readiness_sha"],
            result_path=inputs["result_path"],
            outcome_acquirer=broken_acquirer,
            quality_starts_builder=_ready_qs,
            governor_evaluator=_passing_governor,
            fold_scorer=_fold_scorer,
            reservation_id="fixed-reservation",
            evidence_context=context,
        )

    spent = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
    evidence_record = spent["evidence_bundle"]["terminal_evidence"]
    evidence = json.loads(
        (runner_module.ROOT / evidence_record["path"]).read_text(
            encoding="utf-8"
        )
    )
    assert writes == 3
    assert evidence["status"] == "spent_error"
    assert evidence["evidence_write_error_type"] == "OSError"
    assert {key: evidence[key] for key in context} == context


def test_successful_publish_does_not_reopen_or_corrupt_committed_result(
    tmp_path, monkeypatch
):
    inputs = _sealed_inputs(tmp_path)
    original = runner_module._load_mapping
    result_reads = 0

    def forbid_post_publish_read(path):
        nonlocal result_reads
        if Path(path) == inputs["result_path"]:
            result_reads += 1
            if result_reads > 1:
                raise OSError("synthetic post-publish read failure")
        return original(path)

    monkeypatch.setattr(runner_module, "_load_mapping", forbid_post_publish_read)

    returned = _run(inputs)
    committed = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
    evidence_record = committed["evidence_bundle"]["terminal_evidence"]
    evidence = json.loads(
        (runner_module.ROOT / evidence_record["path"]).read_text(
            encoding="utf-8"
        )
    )

    assert result_reads == 1
    assert returned == committed
    assert evidence["status"] == committed["status"] == "passed"


def test_runner_requires_exact_outcome_identity_set_and_strict_qs_sidecar(tmp_path):
    inputs = _sealed_inputs(tmp_path)
    inputs["outcomes"].pop(next(iter(inputs["outcomes"])))

    with pytest.raises(ValueError, match="outcome identity set mismatch"):
        _run(inputs)
    assert json.loads(inputs["result_path"].read_text(encoding="utf-8"))[
        "status"
    ] == "spent_error"

    second = _sealed_inputs(tmp_path / "second")

    def blocked_qs(_contract, _reservation_id):
        return {
            "schema": "valucast_stage2_quality_starts",
            "status": "blocked",
            "rows": [],
            "blockers": ["missing_qs"],
        }

    with pytest.raises(ValueError, match="quality-start sidecar"):
        _run(second, qs_builder=blocked_qs)
    assert json.loads(second["result_path"].read_text(encoding="utf-8"))[
        "status"
    ] == "spent_error"


def test_runner_canonicalizes_team_splits_to_one_proven_season_before_qs(tmp_path):
    inputs = _sealed_inputs(tmp_path)
    hitter = next(row for row in inputs["rows"] if row["role"] == "hitter")
    key = f"{hitter['mlbam_id']}_hitter"
    inputs["outcomes"][key] = [
        {"year": hitter["cohort_year"] + 1, "pa": 100, "ops": 0.700},
        {"year": hitter["cohort_year"] + 1, "pa": 200, "ops": 0.800},
        {"year": hitter["cohort_year"] + 1, "pa": 300, "ops": 0.767},
        {"year": 2026, "pa": 100},
        {"year": 2026, "pa": 200},
    ]
    observed = []

    def assert_canonical(contract, reservation_id):
        observed.extend(contract["historical_mlb_seasons"][key])
        return _ready_qs(contract, reservation_id)

    _run(inputs, qs_builder=assert_canonical)

    assert len(observed) == 1
    assert observed[0]["pa"] == 300


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"stats": None},
        {"stats": [{}]},
        {"stats": [{"splits": "not-a-list"}]},
        {"stats": [{"splits": []}]},
    ],
)
def test_strict_statsapi_parser_never_turns_missing_or_empty_payloads_into_busts(
    payload,
):
    with pytest.raises(ValueError, match="StatsAPI"):
        parse_strict_statsapi_seasons(payload, "hitter", mlbam_id=123)


@pytest.mark.parametrize(
    "payload",
    [
        {"stats": []},
        {"copyright": "Copyright MLB Advanced Media, L.P.", "stats": []},
        {
            "stats": [
                {
                    "type": {"displayName": "yearByYear"},
                    "group": {"displayName": "hitting"},
                    "splits": [],
                }
            ]
        },
    ],
)
def test_strict_statsapi_parser_accepts_typed_factual_never_mlb_responses(payload):
    assert parse_strict_statsapi_seasons(
        payload, "hitter", mlbam_id=123
    ) == []


def test_strict_statsapi_parser_preserves_missing_direct_categories_as_missing():
    parsed = parse_strict_statsapi_seasons(
        {
            "stats": [
                {
                    "type": {"displayName": "yearByYear"},
                    "group": {"displayName": "hitting"},
                    "splits": [
                        {
                            "season": "2018",
                            "sport": {"id": 1},
                            "player": {"id": 123},
                            "gameType": "R",
                            "stat": {"plateAppearances": 500, "ops": ".800"},
                        }
                    ]
                }
            ]
        },
        "hitter",
        mlbam_id=123,
    )

    assert parsed == [{"year": 2018, "pa": 500.0, "ops": 0.8}]
    assert "r" not in parsed[0]
    assert "so" not in parsed[0]


def test_strict_statsapi_parser_treats_bare_dash_as_missing_numeric_value():
    parsed = parse_strict_statsapi_seasons(
        {
            "stats": [
                {
                    "type": {"displayName": "yearByYear"},
                    "group": {"displayName": "pitching"},
                    "splits": [
                        {
                            "season": "2025",
                            "sport": {"id": 1},
                            "player": {"id": 123},
                            "gameType": "R",
                            "stat": {
                                "inningsPitched": "0.0",
                                "era": "-.--",
                                "whip": "-",
                                "strikeoutWalkRatio": "-.--",
                            },
                        }
                    ],
                }
            ]
        },
        "pitcher",
        mlbam_id=123,
    )

    assert parsed == [
        {"year": 2025, "ip": 0.0, "era": None, "whip": None, "k_bb": None}
    ]


@pytest.mark.parametrize(
    ("role", "stat"),
    [
        ("hitter", {"plateAppearances": 500}),
        ("hitter", {"ops": ".800"}),
        ("pitcher", {"inningsPitched": "100.0"}),
        ("pitcher", {"era": "3.00"}),
    ],
)
def test_strict_statsapi_parser_rejects_missing_label_critical_fields(role, stat):
    with pytest.raises(ValueError, match="label-critical"):
        parse_strict_statsapi_seasons(
            {
                "stats": [{
                    "type": {"displayName": "yearByYear"},
                    "group": {
                        "displayName": (
                            "hitting" if role == "hitter" else "pitching"
                        )
                    },
                    "splits": [{
                        "season": "2018",
                        "sport": {"id": 1},
                        "player": {"id": 123},
                        "gameType": "R",
                        "stat": stat,
                    }]
                }]
            },
            role,
            mlbam_id=123,
        )


@pytest.mark.parametrize(
    ("type_name", "group_name"),
    [("season", "hitting"), ("yearByYear", "pitching")],
)
def test_strict_statsapi_parser_rejects_wrong_type_or_role_group(
    type_name, group_name
):
    with pytest.raises(ValueError, match="type/group"):
        parse_strict_statsapi_seasons(
            {
                "stats": [{
                    "type": {"displayName": type_name},
                    "group": {"displayName": group_name},
                    "splits": [{
                        "season": "2018",
                        "sport": {"id": 1},
                        "player": {"id": 123},
                        "gameType": "R",
                        "stat": {"plateAppearances": 500, "ops": ".800"},
                    }],
                }]
            },
            "hitter",
            mlbam_id=123,
        )


@pytest.mark.parametrize(
    ("role", "stat", "expected"),
    [
        (
            "hitter",
            {
                "plateAppearances": 9,
                "atBats": 7,
                "avg": "-.--",
                "ops": ".---",
                "strikeOuts": 3,
                "baseOnBalls": 2,
            },
            {"year": 2018, "pa": 9.0, "ab": 7.0, "avg": None,
             "ops": None, "so": 3.0, "bb": 2.0},
        ),
        (
            "pitcher",
            {
                "inningsPitched": "2.0",
                "era": "-.--",
                "whip": ".---",
                "strikeOuts": 2,
                "baseOnBalls": 1,
                "strikeoutWalkRatio": "-.--",
            },
            {"year": 2018, "ip": 2.0, "era": None, "whip": None,
             "so": 2.0, "bb": 1.0, "k_bb": None},
        ),
    ],
)
def test_strict_statsapi_parser_preserves_tiny_sample_sentinels_and_counts(
    role, stat, expected
):
    payload = {
        "stats": [
            {
                "type": {"displayName": "yearByYear"},
                "group": {
                    "displayName": "hitting" if role == "hitter" else "pitching"
                },
                "splits": [
                    {
                        "season": "2018",
                        "sport": {"id": 1},
                        "player": {"id": 123},
                        "gameType": "R",
                        "stat": stat,
                    }
                ]
            }
        ]
    }

    assert parse_strict_statsapi_seasons(payload, role, mlbam_id=123) == [expected]


def test_runner_spends_the_look_on_ambiguous_duplicate_year_outcomes(tmp_path):
    inputs = _sealed_inputs(tmp_path)
    hitter = next(row for row in inputs["rows"] if row["role"] == "hitter")
    key = f"{hitter['mlbam_id']}_hitter"
    inputs["outcomes"][key] = [
        {"year": hitter["cohort_year"] + 1, "pa": 100},
        {"year": hitter["cohort_year"] + 1, "pa": 200},
    ]

    with pytest.raises(ValueError, match="full-season aggregate"):
        _run(inputs)
    assert json.loads(inputs["result_path"].read_text(encoding="utf-8"))[
        "status"
    ] == "spent_error"


def test_runner_rejects_any_candidate_or_fold_substitution(tmp_path):
    inputs = _sealed_inputs(tmp_path)

    def substituted(contract, year):
        result = _fold_scorer(contract, year)
        result["metadata"]["candidate_model_flags"] = {
            "PITCHER_INVESTMENT_FEATURE_MODE": "incumbent"
        }
        return result

    with pytest.raises(ValueError, match="candidate model flags"):
        _run(inputs, fold_scorer=substituted)
    assert json.loads(inputs["result_path"].read_text(encoding="utf-8"))[
        "status"
    ] == "spent_error"


def test_runner_rejects_unregistered_qs_rows_and_invalid_calibrator_hashes(tmp_path):
    inputs = _sealed_inputs(tmp_path)

    def extra_qs(contract, reservation_id):
        sidecar = _ready_qs(contract, reservation_id)
        sidecar["rows"] = [
            {
                "mlbam_id": 999999,
                "season": 2018,
                "games_started": 1,
                "quality_starts": 1,
            }
        ]
        body = {key: value for key, value in sidecar.items() if key != "content_sha256"}
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        sidecar["content_sha256"] = hashlib.sha256(encoded).hexdigest()
        return sidecar

    with pytest.raises(ValueError, match="quality-start sidecar coverage"):
        _run(inputs, qs_builder=extra_qs)

    second = _sealed_inputs(tmp_path / "second")

    def invalid_calibrator(contract, year):
        result = _fold_scorer(contract, year)
        result["calibrator_hashes"]["pitcher.impact"] = "not-a-hash"
        return result

    with pytest.raises(ValueError, match="calibrator hashes"):
        _run(second, fold_scorer=invalid_calibrator)


def test_failed_current_board_governor_finalizes_a_negative_gate_not_an_exception(
    tmp_path,
):
    inputs = _sealed_inputs(tmp_path)

    def blocked_governor(**kwargs):
        receipt = {
            "passed": False,
            "unchanged_thresholds": True,
            "candidate_model_flags": CANDIDATE_FLAGS,
            "model_score_mode": "common_target",
            "reservation_id": kwargs["reservation_id"],
            "governor_scope": "prospect_top_board_role_shape",
            "full_governor_required_at": "post_look_pre_publication",
            "role_shape_governor_check": {
                "id": "prospect_top_board_role_shape",
                "status": "failed",
                "metrics": {
                    "max_top25_pitcher_count": 7,
                    "max_top50_pitcher_rate": 0.3,
                },
            },
            "blockers": ["prospect_top25_pitcher_count"],
        }
        encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
        return {**receipt, "receipt_sha256": hashlib.sha256(encoded).hexdigest()}

    result = _run(inputs, governor_evaluator=blocked_governor)

    assert result["status"] == "failed"
    assert result["evaluation"]["production_review_authorized"] is False
    assert (
        result["evaluation"]["gates"]["current_role_shape_governor"]["passed"]
        is False
    )
    assert json.loads(inputs["result_path"].read_text(encoding="utf-8")) == result


def test_governor_receipt_must_bind_the_active_reservation(tmp_path):
    inputs = _sealed_inputs(tmp_path)

    def stale_governor(**_kwargs):
        return {
            "passed": True,
            "unchanged_thresholds": True,
            "candidate_model_flags": CANDIDATE_FLAGS,
            "model_score_mode": "common_target",
            "reservation_id": "some-other-look",
            "governor_scope": "prospect_top_board_role_shape",
            "full_governor_required_at": "post_look_pre_publication",
            "role_shape_governor_check": {
                "id": "prospect_top_board_role_shape",
                "status": "passed",
                "metrics": {
                    "max_top25_pitcher_count": 7,
                    "max_top50_pitcher_rate": 0.3,
                },
            },
        }

    with pytest.raises(ValueError, match="not bound to the candidate"):
        _run(inputs, governor_evaluator=stale_governor)
    assert json.loads(inputs["result_path"].read_text(encoding="utf-8"))[
        "status"
    ] == "spent_error"


def test_governor_receipt_hash_must_match_its_contents(tmp_path):
    inputs = _sealed_inputs(tmp_path)

    def tampered_governor(**kwargs):
        receipt = _passing_governor(**kwargs)
        receipt["passed"] = False
        return receipt

    with pytest.raises(ValueError, match="not bound to the candidate"):
        _run(inputs, governor_evaluator=tampered_governor)


def test_registered_outcomes_strict_fetch_every_mature_identity_and_ignore_legacy(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "outcome-checkpoint.json"
    monkeypatch.setattr(runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint)
    calls = []
    rows = [
        {"mlbam_id": 101, "role": "hitter", "cohort_year": 2019},
        {"mlbam_id": 202, "role": "pitcher", "cohort_year": 2021},
        {"mlbam_id": 303, "role": "hitter", "cohort_year": 2022},
    ]
    fetched = {
        "101_hitter": [{"year": 2020, "pa": 500.0, "ops": 0.8}],
        "202_pitcher": [],
    }

    def strict_fetch(mlbam_id, role):
        calls.append(f"{mlbam_id}_{role}")
        seasons = fetched[f"{mlbam_id}_{role}"]
        return seasons, _outcome_attempt(mlbam_id, role, seasons)

    monkeypatch.setattr(
        runner_module, "_fetch_strict_statsapi_with_receipt", strict_fetch
    )
    acquirer = runner_module._make_registered_outcome_acquirer(
        lambda: (_ for _ in ()).throw(
            AssertionError("legacy production season cache must not be read")
        ),
        registration_sha256="a" * 64,
        readiness_sha256="b" * 64,
        current_contract_record={
            "path": "legacy.json",
            "sha256": "c" * 64,
            "git_blob": "d" * 40,
        },
    )
    acquired = acquirer(
        reservation_id="sealed-token",
        prepared={"rows": rows},
        readiness={},
    )

    assert sorted(calls) == ["101_hitter", "202_pitcher"]
    assert acquired["cache"] == fetched
    assert acquired["provider_receipt"]["legacy_contract_cache_used"] is False
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["status"] == "outcomes_ready"
    assert saved["target_identities"] == ["101_hitter", "202_pitcher"]
    assert "cache" not in saved
    assert set(saved["raw_response_receipts"]) == set(fetched)
    assert acquired["provider_receipt"]["checkpoint"]["path"] == (
        "outcome-checkpoint.json"
    )


def test_outcome_receipt_reparse_rejects_a_swapped_player_body():
    attempt = _outcome_attempt(
        999, "hitter", [{"year": 2020, "pa": 500.0, "ops": 0.8}]
    )
    attempt["mlbam_id"] = 101
    receipt = {
        "identity": "101_hitter",
        "mlbam_id": 101,
        "role": "hitter",
        "status": "resolved",
        "attempt_count": 1,
        "attempts": [attempt],
        "season_count": 1,
    }
    with pytest.raises(ValueError, match="cannot be reparsed"):
        runner_module._resolved_seasons_from_provider_receipt(
            receipt, identity="101_hitter"
        )


def test_provider_raw_receipt_compression_round_trips_compactly_and_detects_tamper():
    raw = (b'{"stats":[{"splits":[]}]}' * 1600) + b"\n"
    fields = runner_module._compressed_raw_receipt_fields(raw)

    assert runner_module._raw_bytes_from_compressed_receipt(
        fields, label="fixture receipt"
    ) == raw
    assert len(fields["compressed_body_base64"]) < len(
        base64.b64encode(raw)
    )

    tampered = dict(fields)
    tampered["compressed_body_base64"] = (
        "A" + tampered["compressed_body_base64"][1:]
    )
    with pytest.raises(ValueError, match="compressed body"):
        runner_module._raw_bytes_from_compressed_receipt(
            tampered, label="fixture receipt"
        )


def test_registered_outcome_transport_gap_preserves_receipts_and_resumes_missing_only(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "outcome-checkpoint.json"
    monkeypatch.setattr(runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)
    rows = [
        {"mlbam_id": 101, "role": "hitter", "cohort_year": 2019},
        {"mlbam_id": 202, "role": "pitcher", "cohort_year": 2021},
    ]
    first_calls = []

    def first_fetch(mlbam_id, role):
        first_calls.append(f"{mlbam_id}_{role}")
        if mlbam_id == 101:
            return None, {
                "mlbam_id": mlbam_id,
                "role": role,
                "provider": "MLB StatsAPI",
                "endpoint": "yearByYear",
                "status": "unresolved_transport",
                "error_type": "TimeoutError",
            }
        return [], _outcome_attempt(mlbam_id, role, [])

    monkeypatch.setattr(
        runner_module, "_fetch_strict_statsapi_with_receipt", first_fetch
    )
    acquirer = runner_module._make_registered_outcome_acquirer(
        lambda: {},
        registration_sha256="a" * 64,
        readiness_sha256="b" * 64,
        current_contract_record={
            "path": "legacy.json",
            "sha256": "c" * 64,
            "git_blob": "d" * 40,
        },
    )
    with pytest.raises(
        runner_module.ResumableAcquisitionIncomplete, match="resumable"
    ):
        acquirer(
            reservation_id="sealed-token",
            prepared={"rows": rows},
            readiness={},
        )
    assert first_calls.count("101_hitter") == runner_module.ACQUISITION_MAX_ATTEMPTS
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["status"] == "acquisition_incomplete"
    assert saved["coverage"]["resolved_identity_count"] == 1

    resumed_calls = []

    def resumed_fetch(mlbam_id, role):
        resumed_calls.append(f"{mlbam_id}_{role}")
        return [], _outcome_attempt(mlbam_id, role, [])

    monkeypatch.setattr(
        runner_module, "_fetch_strict_statsapi_with_receipt", resumed_fetch
    )
    acquired = acquirer(
        reservation_id="sealed-token",
        prepared={"rows": rows},
        readiness={},
    )
    assert resumed_calls == ["101_hitter"]
    assert set(acquired["cache"]) == {"101_hitter", "202_pitcher"}


def test_http_200_invalid_outcome_body_retries_then_remains_resumable(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "outcome-checkpoint.json"
    monkeypatch.setattr(runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)
    calls = []
    raw = b"<html>temporary upstream error</html>"

    def invalid_fetch(mlbam_id, role):
        calls.append((mlbam_id, role))
        return None, {
            "mlbam_id": mlbam_id,
            "role": role,
            "provider": "MLB StatsAPI",
            "endpoint": "yearByYear",
            "http_status": 200,
            **_compressed_fields(raw),
            "status": "invalid_response",
            "error_type": "JSONDecodeError",
        }

    monkeypatch.setattr(
        runner_module, "_fetch_strict_statsapi_with_receipt", invalid_fetch
    )
    acquirer = runner_module._make_registered_outcome_acquirer(
        lambda: {},
        registration_sha256="a" * 64,
        readiness_sha256="b" * 64,
        current_contract_record={
            "path": "legacy.json",
            "sha256": "c" * 64,
            "git_blob": "d" * 40,
        },
    )
    with pytest.raises(runner_module.ResumableAcquisitionIncomplete):
        acquirer(
            reservation_id="sealed-token",
            prepared={
                "rows": [
                    {"mlbam_id": 101, "role": "hitter", "cohort_year": 2019}
                ]
            },
            readiness={},
        )
    assert len(calls) == runner_module.ACQUISITION_MAX_ATTEMPTS
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    receipt = saved["raw_response_receipts"]["101_hitter"]
    assert receipt["status"] == "unresolved"
    assert len(receipt["attempts"]) == runner_module.ACQUISITION_MAX_ATTEMPTS


def test_resumable_acquisition_does_not_spend_the_reserved_result(tmp_path):
    inputs = _sealed_inputs(tmp_path)

    def incomplete(**_kwargs):
        raise runner_module.ResumableAcquisitionIncomplete(
            "provider incomplete",
            checkpoint={"path": "checkpoint.json", "sha256": "a" * 64},
            remaining_count=2,
        )

    with pytest.raises(runner_module.ResumableAcquisitionIncomplete):
        _run(inputs, outcome_acquirer=incomplete)
    marker = json.loads(inputs["result_path"].read_text(encoding="utf-8"))
    assert marker == {
        "reservation_id": "fixed-reservation",
        "status": "reserved_before_outer_outcomes",
    }
    evidence_path = inputs["result_path"].with_name("sealed-result-evidence.json")
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["status"] == "acquisition_incomplete"
    assert evidence["remaining_identity_count"] == 2


def test_qs_input_pointer_is_persisted_and_hash_valid_before_acquisition(
    tmp_path
):
    inputs = _sealed_inputs(tmp_path)

    def incomplete_qs(contract, _reservation_id):
        evidence_path = inputs["result_path"].with_name(
            "sealed-result-evidence.json"
        )
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        quality = evidence["quality_starts"]
        descriptor = quality["input_descriptor"]
        assert descriptor["json_pointer"] == "/quality_starts/input_contract"
        assert descriptor["document_path"] == "sealed-result-evidence.json"
        assert descriptor["sha256"] == runner_module._canonical_payload_sha256(
            quality["input_contract"]
        )
        assert quality["input_contract"] == (
            runner_module._quality_starts_input_payload(contract)
        )
        raise runner_module.ResumableAcquisitionIncomplete(
            "QS provider incomplete",
            checkpoint={"path": "checkpoint.json", "sha256": "a" * 64},
            remaining_count=1,
        )

    with pytest.raises(runner_module.ResumableAcquisitionIncomplete):
        _run(inputs, qs_builder=incomplete_qs)

    persisted = json.loads(
        inputs["result_path"]
        .with_name("sealed-result-evidence.json")
        .read_text(encoding="utf-8")
    )
    assert persisted["status"] == "acquisition_incomplete"
    assert persisted["quality_starts"]["input_descriptor"]["kind"] == (
        "embedded_json"
    )


@pytest.mark.parametrize("interruption", [KeyboardInterrupt, SystemExit])
def test_operator_interruption_preserves_reservation_checkpoint_and_evidence(
    tmp_path, monkeypatch, interruption
):
    inputs = _sealed_inputs(tmp_path)
    checkpoint = tmp_path / "data" / "research" / "checkpoint.json"
    monkeypatch.setattr(runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint)

    def interrupted(**_kwargs):
        _write_json(
            checkpoint,
            {"reservation_id": "fixed-reservation", "status": "acquiring"},
        )
        raise interruption()

    with pytest.raises(interruption):
        _run(inputs, outcome_acquirer=interrupted)

    assert json.loads(inputs["result_path"].read_text(encoding="utf-8")) == {
        "reservation_id": "fixed-reservation",
        "status": "reserved_before_outer_outcomes",
    }
    assert json.loads(checkpoint.read_text(encoding="utf-8")) == {
        "reservation_id": "fixed-reservation",
        "status": "acquiring",
    }
    evidence_path = inputs["result_path"].with_name("sealed-result-evidence.json")
    assert json.loads(evidence_path.read_text(encoding="utf-8"))["status"] == (
        "in_progress"
    )


def test_registered_quality_starts_checkpoint_raw_logs_and_resume(
    tmp_path, monkeypatch
):
    checkpoint = tmp_path / "acquisition-checkpoint.json"
    evidence = tmp_path / "terminal-evidence.json"
    monkeypatch.setattr(runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint)
    monkeypatch.setattr(runner_module, "REGISTERED_EVIDENCE_PATH", evidence)
    monkeypatch.setattr(runner_module.time, "sleep", lambda _seconds: None)
    _write_json(
        checkpoint,
        {
            "artifact": "valucast_plan036_sealed_acquisition_checkpoint",
            "schema_version": 1,
            "reservation_id": "sealed-token",
            "status": "outcomes_ready",
        },
    )
    contract = {
        "artifact": "valucast_extended_prospect_history_labeled",
        "historical_mlb_seasons": {
            "401_pitcher": [
                {"year": 2024, "ip": 120.0, "gs": 1.0, "era": 3.0}
            ]
        },
        "rows": [],
    }
    games = [{
        "date": "2024-04-01",
        "season": "2024",
        "gameType": "R",
        "sport": {"id": 1},
        "player": {"id": 401},
        "stat": {
            "gamesStarted": 1,
            "inningsPitched": "6.0",
            "earnedRuns": 2,
        },
    }]
    calls = []

    def transient(mlbam_id, season):
        calls.append((mlbam_id, season))
        return None, {
            "mlbam_id": mlbam_id,
            "season": season,
            "provider": "MLB StatsAPI",
            "stat": "gameLog",
            "group": "pitching",
            "game_type": "R",
            "status": "unresolved_transport",
            "error_type": "TimeoutError",
        }

    monkeypatch.setattr(
        runner_module, "_fetch_strict_qs_game_log_with_receipt", transient
    )
    with pytest.raises(runner_module.ResumableAcquisitionIncomplete):
        runner_module._registered_quality_starts_builder(contract, "sealed-token")
    assert len(calls) == runner_module.ACQUISITION_MAX_ATTEMPTS
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["status"] == "quality_starts_incomplete"
    assert saved["quality_starts_acquisition"]["remaining"] == ["401:2024"]

    def success(mlbam_id, season):
        return games, _qs_attempt(mlbam_id, season, games)

    monkeypatch.setattr(
        runner_module, "_fetch_strict_qs_game_log_with_receipt", success
    )
    sidecar = runner_module._registered_quality_starts_builder(
        contract, "sealed-token"
    )
    assert sidecar["status"] == "ready"
    assert sidecar["rows"][0]["quality_starts"] == 1
    saved = json.loads(checkpoint.read_text(encoding="utf-8"))
    assert saved["status"] == "ready"
    qs_state = saved["quality_starts_acquisition"]
    expected_input = {
        "kind": "embedded_json",
        "document_path": "terminal-evidence.json",
        "json_pointer": "/quality_starts/input_contract",
        "sha256": runner_module._canonical_payload_sha256(
            runner_module._quality_starts_input_payload(contract)
        ),
        "cutoff_date": "2025-12-31",
    }
    assert sidecar["input"] == expected_input
    assert qs_state["input"] == expected_input
    assert "input_path" not in qs_state
    assert qs_state["coverage"] == {
        "target_player_season_count": 1,
        "receipt_player_season_count": 1,
        "resolved_player_season_count": 1,
        "remaining_player_season_count": 0,
    }
    assert runner_module._resolved_games_from_qs_receipt(
        qs_state["raw_response_receipts"]["401:2024"], key="401:2024"
    ) == games


def test_quality_start_receipt_reparse_rejects_swapped_player_or_season_body():
    games = [{
        "date": "2024-04-01",
        "season": "2024",
        "gameType": "R",
        "sport": {"id": 1},
        "player": {"id": 999},
        "stat": {
            "gamesStarted": 1,
            "inningsPitched": "6.0",
            "earnedRuns": 2,
        },
    }]
    attempt = _qs_attempt(999, 2024, games)
    attempt["mlbam_id"] = 401
    receipt = {
        "key": "401:2024",
        "mlbam_id": 401,
        "season": 2024,
        "status": "resolved",
        "attempt_count": 1,
        "attempts": [attempt],
        "game_count": 1,
    }
    with pytest.raises(ValueError, match="cannot reparse"):
        runner_module._resolved_games_from_qs_receipt(
            receipt, key="401:2024"
        )


def test_official_entry_routes_qs_input_path_to_sealed_core_not_readiness(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "result.json"
    evidence_path = tmp_path / "evidence.json"
    readiness_path = tmp_path / "readiness.json"
    readiness_path.write_text("{}\n", encoding="utf-8")
    plan_path = tmp_path / "plans" / "036-pre2014-cross-role-calibration-gate.md"
    checkpoint_path = (
        tmp_path
        / "data"
        / "research"
        / "extended_prospect_history"
        / "sealed-acquisition-checkpoint.json"
    )
    monkeypatch.setattr(runner_module, "REGISTERED_RESULT_PATH", result_path)
    monkeypatch.setattr(runner_module, "REGISTERED_EVIDENCE_PATH", evidence_path)
    monkeypatch.setattr(
        runner_module, "REGISTERED_READINESS_PATH", readiness_path
    )
    monkeypatch.setattr(runner_module, "PLAN_REGISTRATION_PATH", plan_path)
    monkeypatch.setattr(
        runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint_path
    )
    monkeypatch.setattr(
        runner_module,
        "_load_registered_plan",
        lambda: ({"fixture": True}, "a" * 64),
    )
    readiness = {
        "hashes": {
            "source_files": {"current_prospect_contract": {"fixture": True}}
        }
    }
    monkeypatch.setattr(runner_module, "_load_mapping", lambda _path: readiness)
    monkeypatch.setattr(
        runner_module,
        "_validate_execution_registration",
        lambda _registration, _readiness: ("b" * 64, "c" * 40),
    )
    monkeypatch.setattr(
        runner_module, "_validate_execution_git_topology", lambda **_kwargs: "d" * 40
    )
    monkeypatch.setattr(
        runner_module,
        "_git_text",
        lambda *args: "d" * 40
        if args == ("rev-parse", "HEAD")
        else (_ for _ in ()).throw(AssertionError(args)),
    )
    monkeypatch.setattr(
        runner_module, "_validate_execution_registration_files", lambda _commit: None
    )

    def validate_without_qs_kwarg(
        readiness_path,
        readiness_sha256,
        result_path,
        *,
        git_base_commit=None,
    ):
        return readiness, {}

    monkeypatch.setattr(
        runner_module, "validate_registered_readiness", validate_without_qs_kwarg
    )
    source_bytes = {
        key: b"{}" for key in runner_module.REGISTERED_SOURCE_PATHS
    }
    monkeypatch.setattr(
        runner_module, "_registered_source_blobs", lambda *_args, **_kwargs: source_bytes
    )
    monkeypatch.setattr(
        runner_module,
        "_make_registered_outcome_acquirer",
        lambda *_args, **_kwargs: object(),
    )

    def sealed_core(**kwargs):
        assert kwargs["quality_starts_input_path"] == evidence_path
        assert kwargs["evidence_context"]["registration_path"] == (
            "plans/036-pre2014-cross-role-calibration-gate.md"
        )
        assert kwargs["evidence_context"]["acquisition_checkpoint_path"] == (
            "data/research/extended_prospect_history/"
            "sealed-acquisition-checkpoint.json"
        )
        return {"status": "passed"}

    monkeypatch.setattr(runner_module, "_run_sealed_adjudication", sealed_core)
    assert runner_module.run_registered_adjudication() == {"status": "passed"}


def test_official_entry_defers_outcome_bearing_source_bytes_until_reservation(
    tmp_path, monkeypatch
):
    result_path = tmp_path / "data" / "validation" / "result.json"
    evidence_path = tmp_path / "data" / "validation" / "evidence.json"
    checkpoint_path = tmp_path / "data" / "research" / "checkpoint.json"
    plan_path = tmp_path / "plans" / "036.md"
    readiness_path = tmp_path / "data" / "validation" / "readiness.json"
    monkeypatch.setattr(runner_module, "REGISTERED_RESULT_PATH", result_path)
    monkeypatch.setattr(runner_module, "REGISTERED_EVIDENCE_PATH", evidence_path)
    monkeypatch.setattr(
        runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint_path
    )
    monkeypatch.setattr(runner_module, "PLAN_REGISTRATION_PATH", plan_path)
    readiness_path.parent.mkdir(parents=True, exist_ok=True)
    readiness_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        runner_module, "REGISTERED_READINESS_PATH", readiness_path
    )
    monkeypatch.setattr(
        runner_module,
        "_load_registered_plan",
        lambda: ({"fixture": True}, "a" * 64),
    )
    source_records = {
        key: {"path": path, "sha256": "b" * 64, "git_blob": "c" * 40}
        for key, path in runner_module.REGISTERED_SOURCE_PATHS.items()
    }
    source_records["current_prospect_contract"] = {
        "path": runner_module.REGISTERED_SOURCE_PATHS[
            "current_prospect_contract"
        ],
        "git_blob": "c" * 40,
        "binding": "git_blob_only_pre_reservation",
    }
    readiness = {"hashes": {"source_files": source_records}}
    monkeypatch.setattr(runner_module, "_load_mapping", lambda _path: readiness)
    monkeypatch.setattr(
        runner_module,
        "_validate_execution_registration",
        lambda *_args: ("d" * 64, "e" * 40),
    )
    monkeypatch.setattr(
        runner_module, "_validate_execution_git_topology", lambda **_kwargs: "f" * 40
    )
    monkeypatch.setattr(
        runner_module,
        "_git_text",
        lambda *args: "f" * 40
        if args == ("rev-parse", "HEAD")
        else (_ for _ in ()).throw(AssertionError(args)),
    )
    monkeypatch.setattr(
        runner_module, "_validate_execution_registration_files", lambda _commit: None
    )

    def readiness_check(*_args, **kwargs):
        assert set(kwargs) == {"git_base_commit"}
        return readiness, {}

    monkeypatch.setattr(
        runner_module, "validate_registered_readiness", readiness_check
    )
    reserved = False
    reads = []

    def source_blobs(_readiness, *, base_commit, source_keys):
        nonlocal reserved
        keys = set(source_keys)
        reads.append((reserved, keys))
        if "current_prospect_contract" in keys:
            assert reserved is True
        return {key: b"{}" for key in keys}

    monkeypatch.setattr(runner_module, "_registered_source_blobs", source_blobs)
    monkeypatch.setattr(
        runner_module,
        "_make_registered_outcome_acquirer",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        runner_module,
        "_current_board_evaluator",
        lambda _sources: (lambda **_kwargs: {"fixture": True}),
    )

    def sealed_core(**kwargs):
        nonlocal reserved
        assert all(
            "current_prospect_contract" not in keys
            for was_reserved, keys in reads
            if not was_reserved
        )
        reserved = True
        kwargs["governor_evaluator"]()
        return {"status": "passed"}

    monkeypatch.setattr(runner_module, "_run_sealed_adjudication", sealed_core)
    assert runner_module.run_registered_adjudication() == {"status": "passed"}
    assert any(
        was_reserved and "current_prospect_contract" in keys
        for was_reserved, keys in reads
    )


@pytest.mark.parametrize(
    "lines",
    [
        [
            "A\tplans/036-pre2014-cross-role-calibration-gate.md",
            "M\tdata/validation/valucast_pre2014_cross_role_readiness.json",
            "A\ttests/test_pre2014_cross_role_registration.py",
        ],
        [
            "A\tplans/036-pre2014-cross-role-calibration-gate.md",
            "M\tplans/README.md",
            "M\tdata/validation/valucast_pre2014_cross_role_readiness.json",
            "A\ttests/test_pre2014_cross_role_registration.py",
            "M\tunrelated.py",
        ],
        [
            "A\tplans/036-pre2014-cross-role-calibration-gate.md",
            "M\tplans/README.md",
            "M\tdata/validation/valucast_pre2014_cross_role_readiness.json",
            "D\ttests/test_pre2014_cross_role_registration.py",
        ],
    ],
)
def test_execution_topology_rejects_missing_extra_or_deleted_registration_files(
    tmp_path, monkeypatch, lines
):
    monkeypatch.setattr(
        runner_module,
        "PLAN_REGISTRATION_PATH",
        tmp_path / "plans/036-pre2014-cross-role-calibration-gate.md",
    )
    monkeypatch.setattr(
        runner_module,
        "REGISTERED_READINESS_PATH",
        tmp_path / "data/validation/valucast_pre2014_cross_role_readiness.json",
    )
    monkeypatch.setattr(
        runner_module,
        "REGISTERED_RESULT_PATH",
        tmp_path / "data/validation/valucast_pre2014_cross_role_gate.json",
    )
    monkeypatch.setattr(
        runner_module,
        "REGISTERED_EVIDENCE_PATH",
        tmp_path / "data/validation/valucast_pre2014_cross_role_evidence.json",
    )
    monkeypatch.setattr(
        runner_module,
        "ACQUISITION_CHECKPOINT_PATH",
        tmp_path / "data/research/extended_prospect_history/checkpoint.json",
    )
    base = "a" * 40

    def git_text(*args):
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[0] == "rev-list":
            return f"{'b' * 40} {base}"
        if args[:2] == ("diff", "--name-status"):
            return "\n".join(lines)
        raise AssertionError(args)

    monkeypatch.setattr(runner_module, "_git_text", git_text)
    with pytest.raises(ValueError, match="non-registration"):
        runner_module._validate_execution_git_topology(
            base_commit=base, allow_runtime_paths=False
        )


def test_execution_topology_accepts_only_the_exact_four_file_registration_diff(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        runner_module,
        "PLAN_REGISTRATION_PATH",
        tmp_path / "plans/036-pre2014-cross-role-calibration-gate.md",
    )
    monkeypatch.setattr(
        runner_module,
        "REGISTERED_READINESS_PATH",
        tmp_path / "data/validation/valucast_pre2014_cross_role_readiness.json",
    )
    monkeypatch.setattr(
        runner_module,
        "REGISTERED_RESULT_PATH",
        tmp_path / "data/validation/valucast_pre2014_cross_role_gate.json",
    )
    monkeypatch.setattr(
        runner_module,
        "REGISTERED_EVIDENCE_PATH",
        tmp_path / "data/validation/valucast_pre2014_cross_role_evidence.json",
    )
    monkeypatch.setattr(
        runner_module,
        "ACQUISITION_CHECKPOINT_PATH",
        tmp_path / "data/research/extended_prospect_history/checkpoint.json",
    )
    base = "a" * 40
    exact = [
        f"A\t{path}" for path in sorted(runner_module.REGISTRATION_COMMIT_PATHS)
    ]

    def git_text(*args):
        if args[:2] == ("status", "--porcelain=v1"):
            return ""
        if args[0] == "rev-list":
            return f"{'b' * 40} {base}"
        if args[:2] == ("diff", "--name-status"):
            return "\n".join(exact)
        raise AssertionError(args)

    monkeypatch.setattr(runner_module, "_git_text", git_text)
    monkeypatch.setattr(
        runner_module, "_validate_execution_registration_files", lambda _commit: None
    )
    assert runner_module._validate_execution_git_topology(
        base_commit=base, allow_runtime_paths=False
    ) == "b" * 40


def test_execution_status_excludes_sealed_current_contract_path(monkeypatch):
    observed = None

    def git_text(*args):
        nonlocal observed
        observed = args
        return ""

    monkeypatch.setattr(runner_module, "_git_text", git_text)

    assert runner_module._status_paths() == set()
    assert observed == (
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
        ":(exclude)"
        + runner_module.REGISTERED_SOURCE_PATHS[
            "current_prospect_contract"
        ],
    )


@pytest.mark.parametrize(
    ("temp_name", "allowed"),
    [
        (
            ".valucast_pre2014_cross_role_evidence.json."
            "fixed-reservation.random.tmp",
            True,
        ),
        (
            ".valucast_pre2014_cross_role_evidence.json."
            "other-reservation.random.tmp",
            False,
        ),
        (".unrelated.json.fixed-reservation.random.tmp", False),
    ],
)
def test_resume_topology_allows_only_active_reservation_atomic_json_residue(
    tmp_path, monkeypatch, temp_name, allowed
):
    evidence = tmp_path / "data/validation/valucast_pre2014_cross_role_evidence.json"
    monkeypatch.setattr(runner_module, "REGISTERED_EVIDENCE_PATH", evidence)
    monkeypatch.setattr(
        runner_module,
        "REGISTERED_RESULT_PATH",
        evidence.with_name("valucast_pre2014_cross_role_gate.json"),
    )
    monkeypatch.setattr(
        runner_module,
        "ACQUISITION_CHECKPOINT_PATH",
        tmp_path / "data/research/extended_prospect_history/checkpoint.json",
    )
    dirty_path = (evidence.parent / temp_name).relative_to(tmp_path).as_posix()
    monkeypatch.setattr(runner_module, "_status_paths", lambda: {dirty_path})
    base = "a" * 40

    def git_text(*args):
        if args[0] == "rev-list":
            return f"{'b' * 40} {base}"
        if args[:2] == ("diff", "--name-status"):
            return "\n".join(
                f"M\t{path}"
                for path in sorted(runner_module.REGISTRATION_COMMIT_PATHS)
            )
        raise AssertionError(args)

    monkeypatch.setattr(runner_module, "_git_text", git_text)
    monkeypatch.setattr(
        runner_module, "_validate_execution_registration_files", lambda _commit: None
    )
    if allowed:
        assert runner_module._validate_execution_git_topology(
            base_commit=base,
            allow_runtime_paths=True,
            reservation_id="fixed-reservation",
        ) == "b" * 40
    else:
        with pytest.raises(ValueError, match="clean"):
            runner_module._validate_execution_git_topology(
                base_commit=base,
                allow_runtime_paths=True,
                reservation_id="fixed-reservation",
            )


def test_runtime_temp_cleanup_removes_only_active_reservation_owned_files(
    tmp_path, monkeypatch
):
    evidence = tmp_path / "data/validation/evidence.json"
    checkpoint = tmp_path / "data/research/checkpoint.json"
    result = tmp_path / "data/validation/result.json"
    for path in (evidence, checkpoint, result):
        path.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(runner_module, "REGISTERED_EVIDENCE_PATH", evidence)
    monkeypatch.setattr(
        runner_module, "ACQUISITION_CHECKPOINT_PATH", checkpoint
    )
    monkeypatch.setattr(runner_module, "REGISTERED_RESULT_PATH", result)
    owned = evidence.with_name(
        ".evidence.json.fixed-reservation.random.tmp"
    )
    wrong_token = evidence.with_name(
        ".evidence.json.other-reservation.random.tmp"
    )
    wrong_target = evidence.with_name(
        ".neighbor.json.fixed-reservation.random.tmp"
    )
    for path in (owned, wrong_token, wrong_target):
        path.write_text("residue", encoding="utf-8")

    runner_module._cleanup_bound_runtime_json_temps("fixed-reservation")

    assert not owned.exists()
    assert wrong_token.exists()
    assert wrong_target.exists()


@pytest.mark.parametrize(
    ("case", "repo_path", "message"),
    [
        (
            "symlink",
            sorted(runner_module.REGISTRATION_COMMIT_PATHS)[0],
            "symbolic link",
        ),
        (
            "nonblob",
            sorted(runner_module.REGISTRATION_COMMIT_PATHS)[0],
            "regular Git blob",
        ),
        (
            "oid_mismatch",
            sorted(runner_module.REGISTRATION_COMMIT_PATHS)[0],
            "differs from sealed commit",
        ),
        (
            "symlink",
            runner_module.REGISTERED_IMPLEMENTATION_PATHS[0],
            "symbolic link",
        ),
        (
            "nonblob",
            runner_module.REGISTERED_IMPLEMENTATION_PATHS[0],
            "regular Git blob",
        ),
    ],
)
def test_runner_git_bound_registration_and_implementation_file_guards(
    tmp_path, monkeypatch, case, repo_path, message
):
    monkeypatch.setattr(runner_module, "ROOT", tmp_path)
    path = tmp_path / repo_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n", encoding="utf-8")
    if case == "symlink":
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == path or original_is_symlink(self),
        )

    committed_blob = "a" * 40

    def git_text(*args):
        if args[0] == "ls-tree":
            if case == "nonblob":
                return f"120000 blob {committed_blob}\t{repo_path}"
            return f"100644 blob {committed_blob}\t{repo_path}"
        if args[0] == "hash-object":
            return "b" * 40 if case == "oid_mismatch" else committed_blob
        raise AssertionError(args)

    monkeypatch.setattr(runner_module, "_git_text", git_text)
    with pytest.raises(ValueError, match=message):
        runner_module._validate_git_bound_worktree_file(
            commit="c" * 40,
            repo_path=repo_path,
            expected_blob=(
                committed_blob
                if repo_path in runner_module.REGISTERED_IMPLEMENTATION_PATHS
                else None
            ),
            label="sealed file",
        )


def test_official_runner_rejects_head_change_during_registration_validation(
    tmp_path, monkeypatch
):
    plan = tmp_path / "plans/036.md"
    readiness_path = tmp_path / "data/validation/readiness.json"
    result = tmp_path / "data/validation/result.json"
    plan.parent.mkdir(parents=True)
    readiness_path.parent.mkdir(parents=True)
    plan.write_text("fixture\n", encoding="utf-8")
    readiness_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(runner_module, "PLAN_REGISTRATION_PATH", plan)
    monkeypatch.setattr(runner_module, "REGISTERED_READINESS_PATH", readiness_path)
    monkeypatch.setattr(runner_module, "REGISTERED_RESULT_PATH", result)
    monkeypatch.setattr(
        runner_module,
        "_git_text",
        lambda *args: "a" * 40
        if args == ("rev-parse", "HEAD")
        else (_ for _ in ()).throw(AssertionError(args)),
    )
    monkeypatch.setattr(
        runner_module, "_validate_execution_registration_files", lambda _commit: None
    )
    monkeypatch.setattr(
        runner_module,
        "_load_registered_plan",
        lambda: ({"fixture": True}, "b" * 64),
    )
    readiness = {"fixture": True}
    monkeypatch.setattr(runner_module, "_load_mapping", lambda _path: readiness)
    monkeypatch.setattr(
        runner_module,
        "_validate_execution_registration",
        lambda *_args: ("c" * 64, "d" * 40),
    )
    monkeypatch.setattr(
        runner_module,
        "_validate_execution_git_topology",
        lambda **_kwargs: "e" * 40,
    )

    with pytest.raises(ValueError, match="HEAD changed"):
        runner_module.run_registered_adjudication()
