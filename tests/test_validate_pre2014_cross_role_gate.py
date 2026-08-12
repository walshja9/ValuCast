import base64
import hashlib
import json
import shutil
import zlib
from pathlib import Path

import pytest

from prospects.extended_history import build_labeled_rows
from prospects.pre2014_cross_role_gate import (
    DIRECT_METRIC,
    evaluate_pre2014_cross_role_gate,
)
from prospects.pre2014_readiness import (
    REGISTERED_IMPLEMENTATION_PATHS,
    REGISTERED_PREPARED_SOURCE_PATHS,
    REGISTERED_SOURCE_PATHS,
)
from scripts.run_pre2014_cross_role_gate import convert_fold_output
import scripts.run_pre2014_cross_role_gate as runner_module
from scripts.validate_pre2014_cross_role_gate import (
    ResultValidationError,
    validate_result_files,
)
import scripts.validate_pre2014_cross_role_gate as validator_module


FOLDS = (2017, 2018, 2019, 2021)
CANDIDATE_FLAGS = {
    "PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"
}


@pytest.mark.parametrize(
    "value",
    [
        r"D:\\clone\\data\\evidence.json",
        "/tmp/data/evidence.json",
        r"data\\evidence.json",
        "../data/evidence.json",
        "data//evidence.json",
        "data/./evidence.json",
    ],
)
def test_contract_paths_reject_noncanonical_or_clone_bound_spellings(
    tmp_path, monkeypatch, value
):
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    with pytest.raises(ResultValidationError, match="canonical repo-relative"):
        validator_module._registration_path(value, label="fixture")


def test_file_receipt_resolves_after_repository_relocation(tmp_path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    relative = Path("data/validation/evidence.json")
    first_path = first / relative
    second_path = second / relative
    first_path.parent.mkdir(parents=True)
    second_path.parent.mkdir(parents=True)
    first_path.write_bytes(b"portable receipt\n")
    second_path.write_bytes(first_path.read_bytes())
    record = {
        "path": relative.as_posix(),
        "sha256": hashlib.sha256(first_path.read_bytes()).hexdigest(),
    }

    monkeypatch.setattr(validator_module, "ROOT", first)
    assert validator_module._validate_file_record(
        record, label="portable fixture"
    )[0] == first_path
    monkeypatch.setattr(validator_module, "ROOT", second)
    assert validator_module._validate_file_record(
        record, label="portable fixture"
    )[0] == second_path


def test_runtime_file_receipt_rejects_symlink_to_mutable_external_json(
    tmp_path, monkeypatch
):
    root = tmp_path / "repo"
    external = tmp_path / "external-result.json"
    external.write_text('{"status":"passed"}\n', encoding="utf-8")
    link = root / "data/validation/evidence.json"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(external)
    except OSError:
        link.write_bytes(external.read_bytes())
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == link or original_is_symlink(self),
        )
    monkeypatch.setattr(validator_module, "ROOT", root)
    record = {
        "path": "data/validation/evidence.json",
        "sha256": hashlib.sha256(external.read_bytes()).hexdigest(),
    }

    with pytest.raises(ResultValidationError, match="symbolic link"):
        validator_module._validate_file_record(
            record,
            label="terminal evidence",
            expected_path=link,
        )


def test_result_path_rejects_symlink_before_following_external_json(
    tmp_path, monkeypatch
):
    external = tmp_path / "external-result.json"
    external.write_text('{"status":"passed"}\n', encoding="utf-8")
    result = tmp_path / "repo/data/validation/result.json"
    result.parent.mkdir(parents=True)
    try:
        result.symlink_to(external)
    except OSError:
        result.write_bytes(external.read_bytes())
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == result or original_is_symlink(self),
        )
    monkeypatch.setattr(validator_module, "ROOT", tmp_path / "repo")

    with pytest.raises(ResultValidationError, match="result.*symbolic link"):
        validate_result_files(
            result_path=result,
            readiness_path=tmp_path / "repo/readiness.json",
            registration_path=tmp_path / "repo/plan.md",
        )


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


def _fast_evaluation(folds, *, governor_passed):
    result = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=[*range(2009, 2020), 2021, 2022],
        declared_omissions={2020},
        current_role_shape_governor_passed=governor_passed,
        bootstrap_seed=35011,
        bootstrap_resamples=10,
    )
    if result.get("metrics"):
        result["metrics"]["direct_mae"]["bootstrap_resamples"] = 10000
        result["metrics"]["cross_role_concordance"]["bootstrap_resamples"] = 10000
    return result


@pytest.fixture(autouse=True)
def _fast_validator_replay(monkeypatch):
    def replay(
        folds,
        *,
        cohort_years,
        declared_omissions,
        current_role_shape_governor_passed,
        bootstrap_seed,
        bootstrap_resamples,
        **_kwargs,
    ):
        assert list(cohort_years) == [*range(2009, 2020), 2021, 2022]
        assert set(declared_omissions) == {2020}
        assert bootstrap_seed == 35011
        assert bootstrap_resamples == 10000
        return _fast_evaluation(
            folds, governor_passed=current_role_shape_governor_passed
        )

    monkeypatch.setattr(validator_module, "evaluate_pre2014_cross_role_gate", replay)
    monkeypatch.setattr(
        runner_module, "replay_pre2014_source_contract", _fixture_source_replay
    )

    def current_board_evaluator(sources):
        assert set(sources) == set(REGISTERED_SOURCE_PATHS)
        passed = sources["current_prospect_contract"]["governor_passed"]

        def evaluate(*, reservation_id, **_kwargs):
            return _governor_receipt(reservation_id, passed=passed)

        return evaluate

    monkeypatch.setattr(
        validator_module,
        "_current_board_evaluator",
        current_board_evaluator,
        raising=False,
    )
    monkeypatch.setattr(
        validator_module, "score_outer_fold", _fixture_fold_scorer, raising=False
    )


def _json_bytes(payload):
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()


def _write(path: Path, payload) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_json_bytes(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo_relative(path: Path) -> str:
    return path.resolve().relative_to(validator_module.ROOT.resolve()).as_posix()


def _repo_file(value: str) -> Path:
    return validator_module.ROOT / value


def _fixture_source_replay(prepared, _manifest, draft_payload, *, load_bytes):
    draft_facts = draft_payload.get("draft_facts", draft_payload)
    return {
        "artifact": "valucast_pre2014_source_replay",
        "schema_version": 1,
        "inputs": [
            {"path": path, "sha256": hashlib.sha256(load_bytes(path)).hexdigest()}
            for path in REGISTERED_PREPARED_SOURCE_PATHS
        ],
        "replay_counts": {
            "milb_cohorts": 13,
            "draft_sources": 23,
            "prepared_sources": 50,
        },
        "prepared_output": {
            "path": REGISTERED_SOURCE_PATHS["prepared_artifact"],
            "sha256": hashlib.sha256(_json_bytes(prepared)).hexdigest(),
            "candidate_count": len(prepared["rows"]),
        },
        "draft_facts_output": {
            "path": REGISTERED_SOURCE_PATHS["draft_facts"],
            "sha256": hashlib.sha256(_json_bytes(draft_payload)).hexdigest(),
            "candidate_id_count": len(draft_facts),
        },
    }


def _strict_provider_receipt(identity, seasons):
    mlbam_id, role = identity.rsplit("_", 1)
    splits = []
    for season in seasons:
        if role == "hitter":
            stat = {
                "plateAppearances": season.get("pa"),
                "ops": season.get("ops"),
            }
        else:
            stat = {
                "inningsPitched": str(season.get("ip")),
                "era": season.get("era"),
            }
        splits.append({
            "season": str(season["year"]),
            "sport": {"id": 1},
            "player": {"id": int(mlbam_id)},
            "gameType": "R",
            "stat": {key: value for key, value in stat.items() if value is not None},
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
    attempt = {
        "mlbam_id": int(mlbam_id),
        "role": role,
        "provider": "MLB StatsAPI",
        "endpoint": "yearByYear",
        "status": "resolved",
        "http_status": 200,
        **_compressed_fields(raw),
        "season_count": len(seasons),
    }
    return {
        "identity": identity,
        "mlbam_id": int(mlbam_id),
        "role": role,
        "status": "resolved",
        "attempt_count": 1,
        "attempts": [attempt],
        "season_count": len(seasons),
    }


def _strict_qs_provider_receipt(mlbam_id, season):
    games = [{
        "date": f"{season}-04-01",
        "season": str(season),
        "gameType": "R",
        "sport": {"id": 1},
        "player": {"id": int(mlbam_id)},
        "stat": {
            "gamesStarted": 1,
            "inningsPitched": "5.0",
            "earnedRuns": 2,
        },
    }]
    raw = json.dumps(
        {
            "stats": [{
                "type": {"displayName": "gameLog"},
                "group": {"displayName": "pitching"},
                "splits": games,
            }]
        },
        separators=(",", ":"),
    ).encode()
    attempt = {
        "mlbam_id": int(mlbam_id),
        "season": int(season),
        "provider": "MLB StatsAPI",
        "stat": "gameLog",
        "group": "pitching",
        "game_type": "R",
        "status": "resolved",
        "http_status": 200,
        **_compressed_fields(raw),
        "game_count": 1,
    }
    key = f"{int(mlbam_id)}:{int(season)}"
    return {
        "key": key,
        "mlbam_id": int(mlbam_id),
        "season": int(season),
        "status": "resolved",
        "attempt_count": 1,
        "attempts": [attempt],
        "game_count": 1,
    }


def _fixture_history():
    prepared_rows = []
    seasons = {}
    for year in FOLDS:
        player_offset = 0
        for role in ("hitter", "pitcher"):
            for index in range(63):
                mlbam_id = year * 1000 + player_offset + index
                tier = min((player_offset + index) // 42, 2) / 2
                prepared_rows.append(
                    {
                        "mlbam_id": mlbam_id,
                        "role": role,
                        "cohort_year": year,
                    }
                )
                identity = f"{mlbam_id}_{role}"
                if tier == 0.0:
                    season_rows = []
                elif role == "hitter":
                    season_rows = [
                        {
                            "year": year + 1,
                            "pa": 200.0 if tier == 0.5 else 500.0,
                            "ops": 0.700 if tier == 0.5 else 0.900,
                        }
                    ]
                else:
                    season_rows = [
                        {
                            "year": year + 1,
                            "ip": 60.0 if tier == 0.5 else 130.0,
                            "era": 5.00 if tier == 0.5 else 2.00,
                        }
                    ]
                seasons[identity] = season_rows
            player_offset += 63
    controls = [
        *((1_609_000 + cohort_year, cohort_year) for cohort_year in range(2009, 2015)),
        (1_600_001, 2015),
        (1_600_002, 2016),
    ]
    for mlbam_id, cohort_year in controls:
        prepared_rows.append(
            {
                "mlbam_id": mlbam_id,
                "role": "hitter",
                "cohort_year": cohort_year,
            }
        )
        seasons[f"{mlbam_id}_hitter"] = []
    return prepared_rows, seasons, {}


def _fixture_fold_scorer(contract, year):
    qs_hash = contract["quality_starts"]["content_sha256"]
    inner_years = list(range(2009, year - 3))
    targets = {}
    incumbent = {}
    candidate = {}
    identities = set()
    player_offset = 0
    for role in ("hitter", "pitcher"):
        for index in range(63):
            mlbam_id = year * 1000 + player_offset + index
            identity = (str(mlbam_id), role)
            identities.add(identity)
            direct_target = (player_offset + index) / 125
            outcome_tier = min((player_offset + index) // 42, 2) / 2
            targets[identity] = {
                "outcome_tier": outcome_tier,
                "direct_7x7_target": direct_target,
            }
            incumbent[identity] = 1.0 - direct_target
            candidate[identity] = direct_target
        player_offset += 63
    return {
        "scores": {"incumbent": incumbent, "candidate": candidate},
        "targets": targets,
        "calibrator_hashes": {
            "hitter.outcome": "b" * 64,
            "hitter.impact": "c" * 64,
            "pitcher.outcome": "d" * 64,
            "pitcher.impact": "e" * 64,
        },
        "metadata": {
            "outer_year": year,
            "train_through": year - 4,
            "inner_fold_years": inner_years,
            "calibration_mature_through": year - 4,
            "calibration_strategy": "leave_one_cohort_out_within_outer_mature_pool",
            "identity_count": 126,
            "outer_reference_sha256": "f" * 64,
            "candidate_model_flags": CANDIDATE_FLAGS,
            "incumbent_model_flags": {
                "PITCHER_INVESTMENT_FEATURE_MODE": "incumbent"
            },
            "quality_starts_sha256": qs_hash,
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
                    "reference_sha256": "a" * 64,
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


def _fold_outputs(qs_hash="a" * 64):
    contract = {"quality_starts": {"content_sha256": qs_hash}}
    folds = []
    for year in FOLDS:
        scored = _fixture_fold_scorer(contract, year)
        eligible_identities = {
            (str(year * 1000 + index), "hitter") for index in range(63)
        } | {
            (str(year * 1000 + 63 + index), "pitcher") for index in range(63)
        }
        folds.append(
            convert_fold_output(
                scored,
                cohort_year=year,
                eligible_identities=eligible_identities,
                quality_starts_sha256=qs_hash,
                mature_cohort_years=list(range(2009, year - 3)),
            )
        )
    return folds


def _governor_receipt(reservation_id="sealed-token", *, passed=True):
    receipt = {
        "passed": passed,
        "unchanged_thresholds": True,
        "candidate_model_flags": CANDIDATE_FLAGS,
        "model_score_mode": "common_target",
        "reservation_id": reservation_id,
        "governor_scope": "prospect_top_board_role_shape",
        "full_governor_required_at": "post_look_pre_publication",
        "blockers": [] if passed else ["prospect_top_board_role_shape"],
        "role_shape_governor_check": {
            "id": "prospect_top_board_role_shape",
            "status": "passed" if passed else "failed",
            "metrics": {
                "max_top25_pitcher_count": 7,
                "max_top50_pitcher_rate": 0.3,
            },
        },
    }
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    return {**receipt, "receipt_sha256": hashlib.sha256(encoded).hexdigest()}


def _registration(
    readiness_path, readiness_sha, result_path, hashes, evidence_path, checkpoint_path
):
    source = hashes["source_files"]
    return {
        "protocol": "plan_036_pre2014_cross_role_calibration",
        "registered_at": "2026-08-11T00:00:00Z",
        "status": "registered",
        "look_spent": False,
        "execution_authorized": True,
        "research_only": True,
        "automatic_promotion": False,
        "claim_authorized": False,
        "implementation_base_commit": "1" * 40,
        "readiness": {
            "path": _repo_relative(readiness_path),
            "sha256": readiness_sha,
        },
        "result_path": _repo_relative(result_path),
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
        "outer_folds": list(FOLDS),
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
        "primary_endpoint": DIRECT_METRIC,
        "thresholds": {
            "minimum_outer_folds": 4,
            "minimum_unique_players_per_role": 250,
            "minimum_fold_role_coverage": 0.90,
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
        "hashes": hashes,
        "result_contract": {
            "single_use": True,
            "claim_authorized": False,
            "automatic_promotion": False,
            "terminal_evidence_path": _repo_relative(evidence_path),
            "acquisition_checkpoint_path": _repo_relative(checkpoint_path),
            "outcome_cutoff_date": "2025-12-31",
        },
        "limitations": ["cohort-season-completion pseudo-replay"],
    }


def _write_plan(path, registration):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Plan 036\n\n"
        "<!-- plan036-registration:start -->\n"
        "```json\n"
        + json.dumps(registration, indent=2, sort_keys=True)
        + "\n```\n"
        "<!-- plan036-registration:end -->\n",
        encoding="utf-8",
    )


def _bundle(tmp_path, *, governor_passed=True, spent=False):
    tmp_path.mkdir(parents=True, exist_ok=True)
    runner_module.ROOT = tmp_path
    validator_module.ROOT = tmp_path
    validator_module._TEST_ONLY_ALLOW_NO_GIT = True
    readiness_path = (
        tmp_path
        / "data/validation/valucast_pre2014_cross_role_readiness.json"
    )
    result_path = tmp_path / "data/validation/valucast_pre2014_cross_role_gate.json"
    plan_path = tmp_path / "plans/036-pre2014-cross-role-calibration-gate.md"
    evidence_path = (
        tmp_path
        / "data/validation/valucast_pre2014_cross_role_evidence.json"
    )
    checkpoint_path = (
        tmp_path
        / "data/research/extended_prospect_history/"
        "sealed-acquisition-checkpoint.json"
    )
    prepared_rows, seasons, draft_facts = _fixture_history()
    source_payloads = {
        "prepared_artifact": {
            "artifact": "valucast_extended_prospect_history_prepared",
            "mode": "prepare_only",
            "source_policy": {"outcomes_read": False, "labels_scored": False},
            "candidate_count": len(prepared_rows),
            "rows": prepared_rows,
        },
        "draft_facts": {"draft_facts": draft_facts},
        "current_prospect_contract": {
            "fixture": "current_prospect_contract",
            "governor_passed": governor_passed,
        },
    }
    source_records = {}
    for key, relative_path in REGISTERED_SOURCE_PATHS.items():
        path = tmp_path / relative_path
        sha256 = _write(path, source_payloads.get(key, {"fixture": key}))
        source_records[key] = (
            {
                "path": relative_path,
                "git_blob": "2" * 40,
                "binding": "git_blob_only_pre_reservation",
            }
            if key == "current_prospect_contract"
            else {
                "path": relative_path,
                "sha256": sha256,
                "git_blob": "2" * 40,
            }
        )
    prepared_source_records = []
    for relative_path in REGISTERED_PREPARED_SOURCE_PATHS:
        path = tmp_path / relative_path
        sha256 = (
            hashlib.sha256(path.read_bytes()).hexdigest()
            if path.exists()
            else _write(path, {"prepared_source_fixture": relative_path})
        )
        prepared_source_records.append(
            {
                "path": relative_path,
                "sha256": sha256,
                "git_blob": "3" * 40,
            }
        )
    source_replay = _fixture_source_replay(
        source_payloads["prepared_artifact"],
        source_payloads.get("prepared_manifest", {"fixture": "prepared_manifest"}),
        source_payloads["draft_facts"],
        load_bytes=lambda relative_path: (tmp_path / relative_path).read_bytes(),
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
                "git_blob": "4" * 40,
            }
        )
    implementation = tmp_path / REGISTERED_IMPLEMENTATION_PATHS[0]
    hashes = {
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
    }
    parity = {
        "status": "ready",
        "cohort_year": 2014,
        "candidate_count": 1559,
        "committed_count": 1559,
        "extra": [],
        "missing": [],
    }
    readiness = {
        "artifact": "valucast_pre2014_cross_role_readiness",
        "schema_version": 1,
        "status": "ready",
        "blockers": [],
        "look_spent": False,
        "execution_authorized": True,
        "claim_authorized": False,
        "production_review_authorized": False,
        "implementation_base_commit": "1" * 40,
        "source_replay": source_replay,
        "source_policy": {
            "phase": "pre_look",
            "reads_outcomes": False,
            "reads_mlb_seasons": False,
            "research_only": True,
        },
        "candidate_audit": {
            "cohorts": [*range(2009, 2020), 2021, 2022],
            "identity_parity": parity,
        },
        "outer_fold_audit": {"registered_folds": list(FOLDS)},
        "result": {
            "path": _repo_relative(result_path),
            "exists": False,
            "unspent": True,
        },
        "hashes": hashes,
    }
    readiness_sha = _write(readiness_path, readiness)
    registration = _registration(
        readiness_path,
        readiness_sha,
        result_path,
        hashes,
        evidence_path,
        checkpoint_path,
    )
    registration_sha = hashlib.sha256(
        json.dumps(
            registration,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    _write_plan(plan_path, registration)
    if spent:
        evidence = {
            "artifact": "valucast_plan036_terminal_evidence",
            "schema_version": 1,
            "status": "spent_error",
            "reservation_id": "sealed-token",
            "registered_readiness_sha256": readiness_sha,
            "implementation_base_commit": "1" * 40,
            "registration_sha256": registration_sha,
            "execution_commit": "5" * 40,
            "registration_path": _repo_relative(plan_path),
            "acquisition_checkpoint_path": _repo_relative(checkpoint_path),
            "outcome_cutoff_date": "2025-12-31",
            "error_type": "RuntimeError",
        }
        evidence_sha = _write(evidence_path, evidence)
        result = {
            "artifact": "valucast_pre2014_cross_role_gate",
            "protocol": "plan_036_pre2014_cross_role_calibration",
            "status": "spent_error",
            "decision": "production_review_not_authorized",
            "production_review_authorized": False,
            "claim_authorized": False,
            "error_type": "RuntimeError",
            "evidence_bundle": {
                "terminal_evidence": {
                    "path": _repo_relative(evidence_path),
                    "sha256": evidence_sha,
                }
            },
            "reservation_id": "sealed-token",
        }
    else:
        labeled_rows = build_labeled_rows(
            prepared_rows,
            seasons,
            draft_facts,
            horizon_years=4,
        )
        quality_input = {
            "artifact": "valucast_extended_prospect_history_labeled",
            "current": {"fetched_date": "2025-12-31"},
            "historical_mlb_seasons": seasons,
            "rows": labeled_rows,
        }
        qs_rows = []
        for identity, season_rows in seasons.items():
            if not identity.endswith("_pitcher"):
                continue
            mlbam_id = int(identity.removesuffix("_pitcher"))
            for season in season_rows:
                qs_rows.append({
                    "mlbam_id": mlbam_id,
                    "season": season["year"],
                    "games_started": 1,
                    "quality_starts": 0,
                    "provenance": "derived_game_log",
                })
        sidecar = {
            "schema": "valucast_stage2_quality_starts",
            "version": "1.0.0",
            "status": "ready",
            "source": dict(runner_module.QUALITY_STARTS_SOURCE),
            "input": {
                "kind": "embedded_json",
                "document_path": _repo_relative(evidence_path),
                "json_pointer": "/quality_starts/input_contract",
                "sha256": hashlib.sha256(json.dumps(
                    quality_input,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()).hexdigest(),
                "cutoff_date": "2025-12-31",
            },
            "coverage": {
                "source_rows": len(qs_rows),
                "unique_player_seasons": len(qs_rows),
                "resolved_player_seasons": len(qs_rows),
                "post_join_rows_with_qs": len(qs_rows),
            },
            "validation": {
                "existing_values_checked": 0,
                "existing_value_mismatches": [],
                "current_season_values_superseded": [],
                "games_started_mismatches": [],
                "duplicate_value_conflicts": [],
            },
            "rows": qs_rows,
            "blockers": [],
            "reservation_id": "sealed-token",
        }
        sidecar["content_sha256"] = runner_module._quality_starts_content_sha256(
            sidecar
        )
        folds = _fold_outputs(sidecar["content_sha256"])
        governor = _governor_receipt(passed=governor_passed)
        evaluation = _fast_evaluation(folds, governor_passed=governor_passed)
        authorized = evaluation["production_review_authorized"] is True
        target_identities = sorted(seasons)
        strict_receipts = {
            identity: _strict_provider_receipt(identity, seasons[identity])
            for identity in target_identities
        }
        qs_target_keys = sorted(
            f"{row['mlbam_id']}:{row['season']}" for row in qs_rows
        )
        qs_receipts = {
            key: _strict_qs_provider_receipt(*map(int, key.split(":")))
            for key in qs_target_keys
        }
        checkpoint = {
            "artifact": "valucast_plan036_sealed_acquisition_checkpoint",
            "schema_version": 1,
            "status": "ready",
            "reservation_id": "sealed-token",
            "registration_sha256": registration_sha,
            "registered_readiness_sha256": readiness_sha,
            "outcome_cutoff_date": "2025-12-31",
            "comparison_context": {
                "source": "registered_current_prospect_contract",
                "record": source_records["current_prospect_contract"],
                "used_as_outcome_truth": False,
            },
            "fetch_policy": {
                "mode": runner_module.STRICT_OUTCOME_FETCH_MODE,
                "legacy_contract_cache_used": False,
                "max_attempts_per_identity": (
                    runner_module.ACQUISITION_MAX_ATTEMPTS
                ),
                "checkpoint_batch_size": (
                    runner_module.ACQUISITION_CHECKPOINT_BATCH_SIZE
                ),
            },
            "target_identities": target_identities,
            "raw_response_receipts": strict_receipts,
            "coverage": {
                "target_identity_count": len(target_identities),
                "receipt_identity_count": len(target_identities),
                "resolved_identity_count": len(target_identities),
                "remaining_identity_count": 0,
            },
            "remaining": [],
            "quality_starts_acquisition": {
                "reservation_id": "sealed-token",
                "status": "ready",
                "input": sidecar["input"],
                "source": dict(runner_module.QUALITY_STARTS_SOURCE),
                "fetch_policy": {
                    "max_attempts_per_player_season": (
                        runner_module.ACQUISITION_MAX_ATTEMPTS
                    ),
                    "checkpoint_batch_size": (
                        runner_module.ACQUISITION_CHECKPOINT_BATCH_SIZE
                    ),
                },
                "target_player_seasons": qs_target_keys,
                "raw_response_receipts": qs_receipts,
                "coverage": {
                    "target_player_season_count": len(qs_target_keys),
                    "receipt_player_season_count": len(qs_target_keys),
                    "resolved_player_season_count": len(qs_target_keys),
                    "remaining_player_season_count": 0,
                },
                "remaining": [],
            },
        }
        checkpoint_sha = _write(checkpoint_path, checkpoint)
        canonical_outcomes = {
            "provider_receipt": {
                "mode": runner_module.STRICT_OUTCOME_FETCH_MODE,
                "reservation_id": "sealed-token",
                "outcome_cutoff_date": "2025-12-31",
                "checkpoint": {
                    "path": _repo_relative(checkpoint_path),
                    "sha256": checkpoint_sha,
                },
                "target_identity_count": len(target_identities),
                "receipt_identity_count": len(target_identities),
                "resolved_identity_count": len(target_identities),
                "legacy_contract_cache_used": False,
            },
            "historical_mlb_seasons": seasons,
            "identity_count": len(seasons),
        }
        result = {
            "artifact": "valucast_pre2014_cross_role_gate",
            "schema_version": 1,
            "protocol": "plan_036_pre2014_cross_role_calibration",
            "status": "passed" if authorized else "failed",
            "decision": evaluation["decision"],
            "production_review_authorized": authorized,
            "claim_authorized": False,
            "registered_readiness_sha256": readiness_sha,
            "candidate": {
                "model_flags": CANDIDATE_FLAGS,
                "model_score_mode": "common_target",
            },
            "outer_folds": list(FOLDS),
            "quality_starts_sha256": sidecar["content_sha256"],
            "current_role_shape_governor": governor,
            "fold_outputs": folds,
            "evaluation": evaluation,
            "reservation_id": "sealed-token",
        }
        evidence = {
            "artifact": "valucast_plan036_terminal_evidence",
            "schema_version": 1,
            "status": result["status"],
            "reservation_id": "sealed-token",
            "registered_readiness_sha256": readiness_sha,
            "implementation_base_commit": "1" * 40,
            "registration_sha256": registration_sha,
            "execution_commit": "5" * 40,
            "registration_path": _repo_relative(plan_path),
            "acquisition_checkpoint_path": _repo_relative(checkpoint_path),
            "outcome_cutoff_date": "2025-12-31",
            "canonical_outcomes": canonical_outcomes,
            "labeled_contract": {
                "artifact": "valucast_extended_prospect_history_labeled",
                "rows": labeled_rows,
                "historical_mlb_seasons": seasons,
            },
            "quality_starts": {
                "input_contract": quality_input,
                "input_descriptor": sidecar["input"],
                "sidecar": sidecar,
                "provider": dict(runner_module.QUALITY_STARTS_SOURCE),
            },
            "quality_starts_sha256": sidecar["content_sha256"],
            "fold_outputs": folds,
            "current_role_shape_governor": governor,
            "evaluation": evaluation,
        }
        evidence_sha = _write(evidence_path, evidence)
        result["evidence_bundle"] = {
            "terminal_evidence": {
                "path": _repo_relative(evidence_path),
                "sha256": evidence_sha,
            }
        }
    _write(result_path, result)
    return {
        "result": result_path,
        "readiness": readiness_path,
        "plan": plan_path,
        "implementation": implementation,
    }


@pytest.mark.parametrize(
    ("governor_passed", "expected_status"),
    [(True, "passed"), (False, "failed")],
)
def test_validator_recomputes_and_accepts_complete_permanent_results(
    tmp_path, governor_passed, expected_status
):
    bundle = _bundle(tmp_path, governor_passed=governor_passed)

    report = validate_result_files(
        result_path=bundle["result"],
        readiness_path=bundle["readiness"],
        registration_path=bundle["plan"],
    )

    assert report == {
        "valid": True,
        "status": expected_status,
        "production_review_authorized": governor_passed,
        "claim_authorized": False,
    }


def test_complete_registered_bundle_validates_after_repository_relocation(
    tmp_path,
):
    first = tmp_path / "first"
    second = tmp_path / "second"
    _bundle(first)
    shutil.copytree(first, second)
    runner_module.ROOT = second
    validator_module.ROOT = second

    report = validate_result_files(
        result_path=(
            second
            / "data/validation/valucast_pre2014_cross_role_gate.json"
        ),
        readiness_path=(
            second
            / "data/validation/valucast_pre2014_cross_role_readiness.json"
        ),
        registration_path=(
            second / "plans/036-pre2014-cross-role-calibration-gate.md"
        ),
    )

    assert report["valid"] is True
    assert report["status"] == "passed"


def test_official_validator_fails_closed_without_git_metadata(tmp_path):
    bundle = _bundle(tmp_path)
    validator_module._TEST_ONLY_ALLOW_NO_GIT = False

    with pytest.raises(ResultValidationError, match="Git metadata is required"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


def test_validator_rejects_self_consistent_registered_identity_cohort_substitution(
    tmp_path,
):
    bundle = _bundle(tmp_path)
    result = json.loads(bundle["result"].read_text(encoding="utf-8"))
    evidence_path = _repo_file(
        result["evidence_bundle"]["terminal_evidence"]["path"]
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

    def swap_registered_cohorts(rows):
        controls = {
            int(row["mlbam_id"]): row
            for row in rows
            if int(row["mlbam_id"]) in {1_600_001, 1_600_002}
        }
        assert set(controls) == {1_600_001, 1_600_002}
        first = controls[1_600_001]["cohort_year"]
        controls[1_600_001]["cohort_year"] = controls[1_600_002]["cohort_year"]
        controls[1_600_002]["cohort_year"] = first

    swap_registered_cohorts(evidence["labeled_contract"]["rows"])
    quality_input = evidence["quality_starts"]["input_contract"]
    swap_registered_cohorts(quality_input["rows"])
    evidence["quality_starts"]["sidecar"]["input"]["sha256"] = hashlib.sha256(
        json.dumps(
            quality_input,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    sidecar = evidence["quality_starts"]["sidecar"]
    evidence["quality_starts"]["input_descriptor"] = dict(sidecar["input"])
    checkpoint_record = evidence["canonical_outcomes"]["provider_receipt"][
        "checkpoint"
    ]
    checkpoint_path = _repo_file(checkpoint_record["path"])
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    checkpoint["quality_starts_acquisition"]["input"] = dict(sidecar["input"])
    checkpoint_record["sha256"] = _write(checkpoint_path, checkpoint)
    sidecar["content_sha256"] = runner_module._quality_starts_content_sha256(sidecar)
    quality_starts_sha256 = sidecar["content_sha256"]
    evidence["quality_starts_sha256"] = quality_starts_sha256
    result["quality_starts_sha256"] = quality_starts_sha256
    for folds in (evidence["fold_outputs"], result["fold_outputs"]):
        for fold in folds:
            fold["receipt"]["quality_starts_sha256"] = quality_starts_sha256

    evidence_sha = _write(evidence_path, evidence)
    result["evidence_bundle"]["terminal_evidence"]["sha256"] = evidence_sha
    _write(bundle["result"], result)

    with pytest.raises(ResultValidationError, match="registered prepared"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


def test_validator_rejects_self_consistent_fold_receipt_fabrication(tmp_path):
    bundle = _bundle(tmp_path)
    result = json.loads(bundle["result"].read_text(encoding="utf-8"))
    evidence_path = _repo_file(
        result["evidence_bundle"]["terminal_evidence"]["path"]
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    for folds in (result["fold_outputs"], evidence["fold_outputs"]):
        folds[0]["receipt"]["calibrator_hashes"]["pitcher.impact"] = "0" * 64
    evidence_sha = _write(evidence_path, evidence)
    result["evidence_bundle"]["terminal_evidence"]["sha256"] = evidence_sha
    _write(bundle["result"], result)

    with pytest.raises(ResultValidationError, match="registered fold recomputation"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


def test_validator_rejects_self_consistent_governor_receipt_fabrication(tmp_path):
    bundle = _bundle(tmp_path)
    result = json.loads(bundle["result"].read_text(encoding="utf-8"))
    evidence_path = _repo_file(
        result["evidence_bundle"]["terminal_evidence"]["path"]
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    for receipt in (
        result["current_role_shape_governor"],
        evidence["current_role_shape_governor"],
    ):
        receipt["blockers"] = ["fabricated_current_board_receipt"]
        body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        receipt["receipt_sha256"] = hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    evidence_sha = _write(evidence_path, evidence)
    result["evidence_bundle"]["terminal_evidence"]["sha256"] = evidence_sha
    _write(bundle["result"], result)

    with pytest.raises(ResultValidationError, match="registered governor recomputation"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


def test_validator_rejects_self_consistent_registration_hash_fabrication(tmp_path):
    bundle = _bundle(tmp_path)
    result = json.loads(bundle["result"].read_text(encoding="utf-8"))
    evidence_path = _repo_file(
        result["evidence_bundle"]["terminal_evidence"]["path"]
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    checkpoint_record = evidence["canonical_outcomes"]["provider_receipt"]["checkpoint"]
    checkpoint_path = _repo_file(checkpoint_record["path"])
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    fabricated = "0" * 64
    evidence["registration_sha256"] = fabricated
    checkpoint["registration_sha256"] = fabricated
    checkpoint_record["sha256"] = _write(checkpoint_path, checkpoint)
    evidence_sha = _write(evidence_path, evidence)
    result["evidence_bundle"]["terminal_evidence"]["sha256"] = evidence_sha
    _write(bundle["result"], result)

    with pytest.raises(ResultValidationError, match="registration hash"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


def test_validator_accepts_a_minimal_permanent_spent_error_receipt(tmp_path):
    bundle = _bundle(tmp_path, spent=True)

    report = validate_result_files(
        result_path=bundle["result"],
        readiness_path=bundle["readiness"],
        registration_path=bundle["plan"],
    )

    assert report["valid"] is True
    assert report["status"] == "spent_error"
    assert report["production_review_authorized"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result.update(status="reserved_before_outer_outcomes"),
        lambda result: result.update(claim_authorized=True),
        lambda result: result["candidate"].update(model_score_mode="role_quantile"),
        lambda result: result.update(outer_folds=[2017, 2018, 2019]),
        lambda result: result["fold_outputs"][0]["players"][0].update(
            candidate_percentile_rank=0.99
        ),
        lambda result: result["evaluation"]["metrics"]["direct_mae"].update(
            candidate=0.123
        ),
        lambda result: result["current_role_shape_governor"].update(
            unchanged_thresholds=False
        ),
        lambda result: result["fold_outputs"][0]["receipt"].update(
            quality_starts_sha256="f" * 64
        ),
    ],
)
def test_validator_rejects_result_drift_or_tampering(tmp_path, mutation):
    bundle = _bundle(tmp_path)
    result = json.loads(bundle["result"].read_text(encoding="utf-8"))
    mutation(result)
    _write(bundle["result"], result)

    with pytest.raises(ResultValidationError):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


@pytest.mark.parametrize(
    "mutate_fold",
    [
        lambda fold: fold["players"][0].update(candidate_percentile_rank=0.99),
        lambda fold: fold["top25_direct_regret"].update(candidate=0.123456789),
        lambda fold: fold["role_concordance"]["hitter"].update(candidate=0.99),
    ],
)
def test_validator_recomputes_fold_derivations_even_when_result_and_evidence_agree(
    tmp_path, mutate_fold
):
    bundle = _bundle(tmp_path)
    result = json.loads(bundle["result"].read_text(encoding="utf-8"))
    evidence_record = result["evidence_bundle"]["terminal_evidence"]
    evidence_path = _repo_file(evidence_record["path"])
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    mutate_fold(result["fold_outputs"][0])
    mutate_fold(evidence["fold_outputs"][0])
    evidence_sha = _write(evidence_path, evidence)
    result["evidence_bundle"]["terminal_evidence"]["sha256"] = evidence_sha
    _write(bundle["result"], result)

    with pytest.raises(ResultValidationError, match="recompute"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda checkpoint: checkpoint["quality_starts_acquisition"].update(
            source={**runner_module.QUALITY_STARTS_SOURCE, "game_type": "P"}
        ),
        lambda checkpoint: checkpoint["quality_starts_acquisition"].update(
            cutoff_date="2025-12-30"
        ),
        lambda checkpoint: checkpoint["quality_starts_acquisition"].update(
            input_sha256="0" * 64
        ),
        lambda checkpoint: checkpoint["quality_starts_acquisition"][
            "raw_response_receipts"
        ].pop(next(iter(
            checkpoint["quality_starts_acquisition"]["raw_response_receipts"]
        ))),
        lambda checkpoint: checkpoint["raw_response_receipts"].pop(
            next(iter(checkpoint["raw_response_receipts"]))
        ),
        lambda checkpoint: checkpoint["raw_response_receipts"]
        [next(iter(checkpoint["raw_response_receipts"]))]["attempts"][0].update(
            compressed_body_base64="AAAA"
        ),
    ],
)
def test_validator_rejects_resigned_provider_receipt_or_coverage_tampering(
    tmp_path, mutation
):
    bundle = _bundle(tmp_path)
    result = json.loads(bundle["result"].read_text(encoding="utf-8"))
    evidence_path = _repo_file(
        result["evidence_bundle"]["terminal_evidence"]["path"]
    )
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    provider = evidence["canonical_outcomes"]["provider_receipt"]
    checkpoint_path = _repo_file(provider["checkpoint"]["path"])
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    mutation(checkpoint)
    checkpoint_sha = _write(checkpoint_path, checkpoint)
    provider["checkpoint"]["sha256"] = checkpoint_sha
    evidence_sha = _write(evidence_path, evidence)
    result["evidence_bundle"]["terminal_evidence"]["sha256"] = evidence_sha
    _write(bundle["result"], result)

    with pytest.raises(ResultValidationError):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


def test_validator_rejects_registration_or_bound_file_hash_drift(tmp_path):
    bundle = _bundle(tmp_path)
    bundle["implementation"].write_text("FROZEN = False\n", encoding="utf-8")

    with pytest.raises(ResultValidationError, match="hash"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )

    second = _bundle(tmp_path / "second")
    text = second["plan"].read_text(encoding="utf-8")
    second["plan"].write_text(
        text.replace('"seed": 35011', '"seed": 35012'), encoding="utf-8"
    )
    with pytest.raises(ResultValidationError, match="registration"):
        validate_result_files(
            result_path=second["result"],
            readiness_path=second["readiness"],
            registration_path=second["plan"],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda registration: registration["candidate"].update(
                calibration="truthy_but_unregistered"
            ),
            "candidate",
        ),
        (
            lambda registration: registration["candidate"].update(
                forbidden_substitutions=["something_else"]
            ),
            "candidate",
        ),
        (
            lambda registration: registration["source_contract"].update(
                identity_key="(mlbam_id, role)"
            ),
            "source contract",
        ),
        (
            lambda registration: registration.update(
                limitations=["different limitation"]
            ),
            "result contract",
        ),
    ],
)
def test_validator_registration_semantics_are_exactly_the_runner_contract(
    tmp_path, mutation, message
):
    bundle = _bundle(tmp_path)
    registration = validator_module._load_registration(bundle["plan"])
    readiness = json.loads(bundle["readiness"].read_text(encoding="utf-8"))
    mutation(registration)

    with pytest.raises(ResultValidationError, match=message):
        validator_module._validate_registration(
            registration,
            registration_path=bundle["plan"],
            readiness_path=bundle["readiness"],
            result_path=bundle["result"],
            readiness=readiness,
        )


def test_validator_requires_exact_marked_registration_block(tmp_path):
    bundle = _bundle(tmp_path)
    plan = bundle["plan"].read_text(encoding="utf-8")
    bundle["plan"].write_text(
        plan.replace("<!-- plan036-registration:end -->", ""), encoding="utf-8"
    )

    with pytest.raises(ResultValidationError, match="registration block"):
        validate_result_files(
            result_path=bundle["result"],
            readiness_path=bundle["readiness"],
            registration_path=bundle["plan"],
        )


def _topology_git_text(*, scenario):
    implementation = "a" * 40
    execution = "b" * 40
    terminal = "c" * 40
    registration_lines = [
        f"A\t{path}" for path in sorted(validator_module.REGISTRATION_COMMIT_PATHS)
    ]
    runtime_lines = [
        f"A\t{path}"
        for path in sorted(
            {
                validator_module.REGISTERED_RESULT_REPO_PATH,
                validator_module.REGISTERED_EVIDENCE_REPO_PATH,
                validator_module.REGISTERED_CHECKPOINT_REPO_PATH,
            }
        )
    ]

    def git_text(*args):
        if args == ("rev-list", "--parents", "-n", "1", execution):
            parent = "d" * 40 if scenario == "wrong_execution_parent" else implementation
            return f"{execution} {parent}"
        if args == ("diff", "--name-status", implementation, execution):
            lines = list(registration_lines)
            if scenario == "extra_registration_path":
                lines.append("M\tunrelated.py")
            if scenario == "deleted_registration_path":
                lines[0] = lines[0].replace("A\t", "D\t", 1)
            return "\n".join(lines)
        if args[:3] == ("ls-tree", execution, "--"):
            return (
                f"100644 blob {'e' * 40}\t{args[3]}"
                if scenario == "artifact_already_in_execution"
                else ""
            )
        if args == ("rev-parse", "HEAD"):
            return terminal if scenario.startswith("terminal_") else execution
        if args == (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude)"
            + validator_module.REGISTERED_SOURCE_PATHS[
                "current_prospect_contract"
            ],
        ):
            if scenario.startswith("terminal_"):
                return ""
            lines = [f"?? {line.split(chr(9), 1)[1]}" for line in runtime_lines]
            if scenario == "dirty_extra_path":
                lines.append("?? unrelated.py")
            if scenario == "staged_runtime_path":
                lines[0] = lines[0].replace("?? ", "A  ", 1)
            return "\n".join(lines)
        if args == ("rev-list", "--parents", "-n", "1", terminal):
            parent = "d" * 40 if scenario == "terminal_wrong_parent" else execution
            return f"{terminal} {parent}"
        if args == ("diff", "--name-status", execution, terminal):
            lines = list(runtime_lines)
            if scenario == "terminal_extra_path":
                lines.append("M\tunrelated.py")
            if scenario == "terminal_deleted_path":
                lines[0] = lines[0].replace("A\t", "D\t", 1)
            if scenario == "terminal_modified_path":
                lines[0] = lines[0].replace("A\t", "M\t", 1)
            return "\n".join(lines)
        if args[:3] == ("ls-tree", terminal, "--"):
            mode, object_type = "100644", "blob"
            if scenario == "terminal_symlink_entry":
                mode = "120000"
            if scenario == "terminal_nonblob_entry":
                mode, object_type = "160000", "commit"
            return f"{mode} {object_type} {'e' * 40}\t{args[3]}"
        raise AssertionError(args)

    return git_text, implementation, execution


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("wrong_execution_parent", "direct registration child"),
        ("extra_registration_path", "registration diff drift"),
        ("deleted_registration_path", "registration diff drift"),
        ("artifact_already_in_execution", "already exists"),
        ("dirty_extra_path", "worktree topology drift"),
        ("staged_runtime_path", "worktree topology drift"),
        ("terminal_wrong_parent", "direct execution child"),
        ("terminal_extra_path", "runtime diff drift"),
        ("terminal_deleted_path", "runtime diff drift"),
        ("terminal_modified_path", "runtime diff drift"),
        ("terminal_symlink_entry", "regular Git blob"),
        ("terminal_nonblob_entry", "regular Git blob"),
    ],
)
def test_validator_rejects_execution_and_terminal_git_topology_tampering(
    monkeypatch, scenario, message
):
    git_text, implementation, execution = _topology_git_text(
        scenario=scenario
    )
    monkeypatch.setattr(validator_module, "_git_text", git_text)
    monkeypatch.setattr(
        validator_module, "_validate_execution_registration_files", lambda _commit: None
    )

    with pytest.raises(ResultValidationError, match=message):
        validator_module._validate_execution_result_git_topology(
            {"execution_commit": execution},
            {"implementation_base_commit": implementation},
        )


def test_spent_topology_rejects_optional_checkpoint_symlink(
    tmp_path, monkeypatch
):
    external = tmp_path / "external-checkpoint.json"
    external.write_text("{}\n", encoding="utf-8")
    checkpoint = tmp_path / validator_module.REGISTERED_CHECKPOINT_REPO_PATH
    checkpoint.parent.mkdir(parents=True)
    try:
        checkpoint.symlink_to(external)
    except OSError:
        checkpoint.write_bytes(external.read_bytes())
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(
            Path,
            "is_symlink",
            lambda self: self == checkpoint or original_is_symlink(self),
        )
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    git_text, implementation, execution = _topology_git_text(
        scenario="valid_execution"
    )
    monkeypatch.setattr(validator_module, "_git_text", git_text)
    monkeypatch.setattr(
        validator_module, "_validate_execution_registration_files", lambda _commit: None
    )

    with pytest.raises(ResultValidationError, match="checkpoint.*symbolic link"):
        validator_module._validate_execution_result_git_topology(
            {"execution_commit": execution, "status": "spent_error"},
            {"implementation_base_commit": implementation},
        )


@pytest.mark.parametrize("scenario", ["valid_execution", "terminal_valid"])
def test_validator_accepts_only_registered_or_runtime_only_terminal_topology(
    monkeypatch, scenario
):
    git_text, implementation, execution = _topology_git_text(
        scenario=scenario
    )
    monkeypatch.setattr(validator_module, "_git_text", git_text)
    monkeypatch.setattr(
        validator_module, "_validate_execution_registration_files", lambda _commit: None
    )

    validator_module._validate_execution_result_git_topology(
        {"execution_commit": execution},
        {"implementation_base_commit": implementation},
    )


def test_validator_rejects_live_implementation_byte_tampering(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    records = []
    for relative_path in validator_module.REGISTERED_IMPLEMENTATION_PATHS:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# frozen {relative_path}\n", encoding="utf-8")
        records.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "git_blob": "a" * 40,
            }
        )
    first = tmp_path / validator_module.REGISTERED_IMPLEMENTATION_PATHS[0]
    first.write_text("# post-hoc tuning\n", encoding="utf-8")

    with pytest.raises(ResultValidationError, match="implementation hash drift"):
        validator_module._validate_live_registered_implementations(
            {"hashes": {"implementation_files": records}},
            git_base_commit=None,
        )


def test_live_implementation_binding_honors_git_autocrlf_filters(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    blob = "a" * 40
    frozen_by_path = {}
    records = []
    for relative_path in validator_module.REGISTERED_IMPLEMENTATION_PATHS:
        frozen = f"# frozen {relative_path}\n".encode()
        frozen_by_path[relative_path] = frozen
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(frozen.replace(b"\n", b"\r\n"))
        records.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(frozen).hexdigest(),
                "git_blob": blob,
            }
        )

    def git_text(*args):
        if args[0] == "hash-object":
            return blob
        if args[0] == "ls-tree":
            return f"100644 blob {blob}\t{args[3]}"
        raise AssertionError(args)

    monkeypatch.setattr(validator_module, "_git_text", git_text)

    def git_bytes(*args):
        assert args[:2] == ("cat-file", "blob")
        relative_path = args[2].split(":", 1)[1]
        return frozen_by_path[relative_path]

    monkeypatch.setattr(validator_module, "_git_bytes", git_bytes)

    validator_module._validate_live_registered_implementations(
        {"hashes": {"implementation_files": records}},
        git_base_commit="b" * 40,
    )


@pytest.mark.parametrize(
    "entry",
    [
        lambda path: f"120000 blob {'a' * 40}\t{path}",
        lambda path: f"160000 commit {'a' * 40}\t{path}",
    ],
)
def test_git_bound_registration_and_implementation_paths_require_regular_blobs(
    tmp_path, monkeypatch, entry
):
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    repo_path = validator_module.REGISTERED_IMPLEMENTATION_PATHS[0]
    path = tmp_path / repo_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        validator_module,
        "_git_text",
        lambda *args: entry(repo_path)
        if args[0] == "ls-tree"
        else (_ for _ in ()).throw(AssertionError(args)),
    )

    with pytest.raises(ResultValidationError, match="regular Git blob"):
        validator_module._validate_git_bound_worktree_file(
            commit="b" * 40,
            repo_path=repo_path,
            expected_blob="a" * 40,
            label="live registered implementation",
        )


def test_git_bound_registration_path_rejects_live_symlink_before_hashing(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    repo_path = sorted(validator_module.REGISTRATION_COMMIT_PATHS)[0]
    path = tmp_path / repo_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("mutable target\n", encoding="utf-8")
    original_is_symlink = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda self: self == path or original_is_symlink(self),
    )
    monkeypatch.setattr(
        validator_module,
        "_git_text",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("Git must not hash a symlink target")
        ),
    )

    with pytest.raises(ResultValidationError, match="symbolic link"):
        validator_module._validate_git_bound_worktree_file(
            commit="b" * 40,
            repo_path=repo_path,
            label="execution registration file",
        )


@pytest.mark.parametrize("checkpoint_present", [False, True])
@pytest.mark.parametrize("terminal_commit", [False, True])
def test_spent_topology_accepts_optional_checkpoint_but_requires_two_artifacts(
    tmp_path, monkeypatch, checkpoint_present, terminal_commit
):
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    implementation = "a" * 40
    execution = "b" * 40
    terminal = "c" * 40
    runtime_paths = {
        validator_module.REGISTERED_RESULT_REPO_PATH,
        validator_module.REGISTERED_EVIDENCE_REPO_PATH,
    }
    for relative_path in runtime_paths:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture\n", encoding="utf-8")
    if checkpoint_present:
        checkpoint = tmp_path / validator_module.REGISTERED_CHECKPOINT_REPO_PATH
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        checkpoint.write_text("fixture\n", encoding="utf-8")
        runtime_paths.add(validator_module.REGISTERED_CHECKPOINT_REPO_PATH)

    def git_text(*args):
        if args == ("rev-list", "--parents", "-n", "1", execution):
            return f"{execution} {implementation}"
        if args == ("diff", "--name-status", implementation, execution):
            return "\n".join(
                f"A\t{path}"
                for path in sorted(validator_module.REGISTRATION_COMMIT_PATHS)
            )
        if args[:3] == ("ls-tree", execution, "--"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return terminal if terminal_commit else execution
        if args[:3] == (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ):
            return (
                ""
                if terminal_commit
                else "\n".join(f"?? {path}" for path in sorted(runtime_paths))
            )
        if args == ("rev-list", "--parents", "-n", "1", terminal):
            return f"{terminal} {execution}"
        if args == ("diff", "--name-status", execution, terminal):
            return "\n".join(f"A\t{path}" for path in sorted(runtime_paths))
        if args[:3] == ("ls-tree", terminal, "--"):
            return f"100644 blob {'e' * 40}\t{args[3]}"
        raise AssertionError(args)

    monkeypatch.setattr(validator_module, "_git_text", git_text)
    monkeypatch.setattr(
        validator_module, "_validate_execution_registration_files", lambda _commit: None
    )
    validator_module._validate_execution_result_git_topology(
        {"execution_commit": execution, "status": "spent_error"},
        {"implementation_base_commit": implementation},
    )


@pytest.mark.parametrize("terminal_commit", [False, True])
@pytest.mark.parametrize(
    "missing_path",
    [
        validator_module.REGISTERED_RESULT_REPO_PATH,
        validator_module.REGISTERED_EVIDENCE_REPO_PATH,
    ],
)
def test_spent_topology_rejects_missing_mandatory_artifact(
    tmp_path, monkeypatch, terminal_commit, missing_path
):
    monkeypatch.setattr(validator_module, "ROOT", tmp_path)
    implementation = "a" * 40
    execution = "b" * 40
    terminal = "c" * 40
    observed_paths = {
        validator_module.REGISTERED_RESULT_REPO_PATH,
        validator_module.REGISTERED_EVIDENCE_REPO_PATH,
    } - {missing_path}

    def git_text(*args):
        if args == ("rev-list", "--parents", "-n", "1", execution):
            return f"{execution} {implementation}"
        if args == ("diff", "--name-status", implementation, execution):
            return "\n".join(
                f"A\t{path}"
                for path in sorted(validator_module.REGISTRATION_COMMIT_PATHS)
            )
        if args[:3] == ("ls-tree", execution, "--"):
            return ""
        if args == ("rev-parse", "HEAD"):
            return terminal if terminal_commit else execution
        if args[:3] == (
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
        ):
            return (
                ""
                if terminal_commit
                else "\n".join(
                    f"?? {path}" for path in sorted(observed_paths)
                )
            )
        if args == ("rev-list", "--parents", "-n", "1", terminal):
            return f"{terminal} {execution}"
        if args == ("diff", "--name-status", execution, terminal):
            return "\n".join(f"A\t{path}" for path in sorted(observed_paths))
        if args[:3] == ("ls-tree", terminal, "--"):
            return f"100644 blob {'e' * 40}\t{args[3]}"
        raise AssertionError(args)

    monkeypatch.setattr(validator_module, "_git_text", git_text)
    monkeypatch.setattr(
        validator_module, "_validate_execution_registration_files", lambda _commit: None
    )
    with pytest.raises(ResultValidationError, match="topology drift|runtime diff"):
        validator_module._validate_execution_result_git_topology(
            {"execution_commit": execution, "status": "spent_error"},
            {"implementation_base_commit": implementation},
        )


def test_spent_result_still_requires_execution_git_topology(monkeypatch):
    result = {
        "artifact": "valucast_pre2014_cross_role_gate",
        "protocol": validator_module.PROTOCOL,
        "status": "spent_error",
        "decision": "production_review_not_authorized",
        "production_review_authorized": False,
        "claim_authorized": False,
        "error_type": "ValueError",
        "evidence_bundle": {"terminal_evidence": {}},
        "reservation_id": "sealed-token",
    }
    monkeypatch.setattr(
        validator_module,
        "_validate_terminal_evidence",
        lambda *_args, **_kwargs: {"execution_commit": "b" * 40},
    )
    monkeypatch.setattr(
        validator_module,
        "_validate_execution_result_git_topology",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ResultValidationError("synthetic spent topology drift")
        ),
    )

    with pytest.raises(ResultValidationError, match="spent topology drift"):
        validator_module._validate_spent_result(
            result,
            {"implementation_base_commit": "a" * 40},
            readiness={},
            readiness_sha256="c" * 64,
            registration_sha256="d" * 64,
            git_base_commit="a" * 40,
        )
