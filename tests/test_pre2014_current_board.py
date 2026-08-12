"""Current-board certification tests for the registered cross-role candidate."""
from __future__ import annotations

from copy import deepcopy
import inspect
from pathlib import Path

import pytest

import prospects.model as prospect_model

from prospects.pre2014_current_board import (
    build_registered_current_calibration_rows,
    evaluate_current_candidate_board,
    make_current_board_governor_evaluator,
)


def _readiness(*, ready: bool = True) -> dict:
    current_context_keys = (
        "current_prospect_contract",
        "prospect_universe",
        "dynasty_layer",
        "prospect_availability",
        "mlb_roster_status",
        "investment_evidence",
        "milb_season_stats",
        "milb_card_history",
        "manual_graduation",
        "sts_snapshot",
        "fangraphs_snapshot",
        "prospectslive_snapshot",
        "pipeline_snapshot",
        "hkb_snapshot",
    )
    source_files = {
        "prepared_artifact": {
            "path": "prepared.json",
            "sha256": "a" * 64,
            "git_blob": "1" * 40,
        },
        "prepared_manifest": {
            "path": "manifest.json",
            "sha256": "b" * 64,
            "git_blob": "2" * 40,
        },
        "draft_facts": {
            "path": "draft.json",
            "sha256": "c" * 64,
            "git_blob": "3" * 40,
        },
    }
    source_files.update(
        {
            key: {
                "path": f"{key}.json",
                "sha256": "e" * 64,
                "git_blob": "4" * 40,
            }
            for key in current_context_keys
        }
    )
    source_files["current_prospect_contract"] = {
        "path": "current_prospect_contract.json",
        "git_blob": "5" * 40,
        "binding": "git_blob_only_pre_reservation",
    }
    return {
        "artifact": "valucast_pre2014_cross_role_readiness",
        "status": "ready" if ready else "blocked",
        "execution_authorized": ready,
        "blockers": [] if ready else ["not_ready"],
        "source_policy": {
            "phase": "pre_look",
            "reads_outcomes": False,
            "reads_mlb_seasons": False,
            "research_only": True,
        },
        "hashes": {
            "source_files": source_files,
            "implementation_files": [
                {
                    "path": "prospects/model.py",
                    "sha256": "d" * 64,
                    "git_blob": "6" * 40,
                }
            ],
        },
    }


def _bundle(*, crowded: bool = False):
    historical = []
    calibration_rows = []
    mlbam_id = 100_000
    for role in ("hitter", "pitcher"):
        for index in range(250):
            cohort = (2014, 2015, 2016, 2017)[index % 4]
            historical.append(
                {
                    "mlbam_id": mlbam_id,
                    "role": role,
                    "cohort_year": cohort,
                    "outcome": "role",
                }
            )
            calibration_rows.append(
                {
                    "mlbam_id": mlbam_id,
                    "role": role,
                    "cohort_year": cohort,
                    "source_fold": cohort,
                    "is_out_of_fold": True,
                    "expected_outcome_score": (index + 1) / 251,
                    "outcome_tier": 0.5,
                    "expected_category_impact_score": (index + 1) / 251,
                    "direct_7x7_target": (index + 1) / 251,
                }
            )
            mlbam_id += 1

    current_rows = []
    universe_rows = []
    for rank in range(1, 61):
        if crowded:
            role = "pitcher" if rank <= 20 else "hitter"
        else:
            role = "pitcher" if rank <= 7 or 26 <= rank <= 33 else "hitter"
        identity = 200_000 + rank
        current_rows.append(
            {
                "mlbam_id": identity,
                "name": f"Player {rank}",
                "role": role,
                "expected_outcome_score": 1 - rank / 100,
                "expected_category_impact_score": 1 - rank / 120,
            }
        )
        universe_rows.append(
            {
                "mlbam_id": identity,
                "name": f"Player {rank}",
                "role": role,
                "positions": ["SP" if role == "pitcher" else "SS"],
            }
        )

    contract = {
        "schema_version": "1.2",
        "generated_at": "2026-08-11T12:00:00+00:00",
        "source_policy": {},
        "historical": {"rows": historical},
        "historical_mlb_seasons": {},
        "current": {"hitters": [], "pitchers": []},
        "mlb_service": [],
        "rookie_limits": {"at_bats": 131, "innings_pitched": 51},
    }
    universe = {
        "schema_version": "1.0",
        "artifact": "valucast_prospect_universe",
        "candidate_count": len(universe_rows),
        "players": universe_rows,
    }
    rank_context = {
        "manual_graduated_ids": [],
        "external_snapshots": {
            "sts": {},
            "fangraphs": {},
            "prospectslive": {},
            "pipeline": {},
            "hkb": {},
        },
    }
    return contract, universe, current_rows, calibration_rows, rank_context


def _model_builder(current_rows, calls):
    def build(contract, now=None, *, mature_through=None):
        calls.append(
            {
                "flag": prospect_model.PITCHER_INVESTMENT_FEATURE_MODE,
                "historical_count": len(contract["historical"]["rows"]),
                "generated_at": now,
                "mature_through": mature_through,
            }
        )
        return {
            "status": "shadow_only",
            "model_version": "registered_candidate_test",
            "input_contract": {"generated_at": contract["generated_at"]},
            "release_contract": {
                "consumer": "prospect_rank_v1",
                "feeds_live_valucast_rank": True,
            },
            "ranked": deepcopy(current_rows),
        }

    return build


def _rank_builder(calls, *, drop_last: bool = False):
    def build(
        universe,
        dynasty_layer,
        prospect_model_payload,
        input_contract,
        **kwargs,
    ):
        assert kwargs["model_score_mode"] == "common_target"
        assert kwargs["stage1_state"] == "incumbent"
        assert all(
            "expected_outcome_score_common_target" in row
            and "expected_category_impact_score_common_target" in row
            and (row.get("common_target_calibration") or {}).get("sha256")
            for row in prospect_model_payload["ranked"]
        )
        calls.append(kwargs["model_score_mode"])
        rows = prospect_model_payload["ranked"][:-1] if drop_last else prospect_model_payload["ranked"]
        board = [
            {
                "rank": rank,
                "mlbam_id": row["mlbam_id"],
                "name": row["name"],
                "role": row["role"],
                "positions": ["SP" if row["role"] == "pitcher" else "SS"],
                "score": 100 - rank,
            }
            for rank, row in enumerate(rows, 1)
        ]
        return {
            "status": "candidate_ready",
            "rank_version": "1",
            "ranked_count": len(board),
            "validation": {"blockers": [], "ranks_contiguous": True},
            "promotion": {"feeds_live_valucast_rank": True},
            "board": board,
        }

    return build


def _evaluate(
    *,
    crowded=False,
    readiness=None,
    mutate=None,
    drop_last=False,
    calibration_before_cohort=2022,
    quality_starts_override=None,
):
    contract, universe, current_rows, calibration_rows, rank_context = _bundle(
        crowded=crowded
    )
    qs = {
        "schema": "valucast_stage2_quality_starts",
        "status": "ready",
        "content_sha256": "a" * 64,
        "rows": [],
    }
    if quality_starts_override is not None:
        qs = quality_starts_override
    if mutate:
        mutate(contract, universe, calibration_rows, qs)
    model_calls = []
    rank_calls = []
    result = evaluate_current_candidate_board(
        contract,
        universe,
        {"generated_at": contract["generated_at"]},
        calibration_rows,
        qs,
        readiness or _readiness(),
        calibration_before_cohort=calibration_before_cohort,
        rank_context=rank_context,
        model_builder=_model_builder(current_rows, model_calls),
        rank_builder=_rank_builder(rank_calls, drop_last=drop_last),
    )
    return result, model_calls, rank_calls


def test_exact_candidate_path_passes_unchanged_role_shape_governor_check():
    result, model_calls, rank_calls = _evaluate()

    assert result["status"] == "passed"
    assert result["current_role_shape_governor_passed"] is True
    assert "current_governor_passed" not in result
    assert result["candidate_path"]["pitcher_investment_feature_mode"] == "drop_raw_pick_value"
    assert result["candidate_path"]["rank_model_score_mode"] == "common_target"
    assert model_calls == [
        {
            "flag": "drop_raw_pick_value",
            "historical_count": 500,
            "generated_at": "2026-08-11T12:00:00+00:00",
            "mature_through": 2021,
        }
    ]
    assert rank_calls == ["common_target"]
    assert result["calibration"]["row_count"] == 500
    assert len(result["calibration"]["rows_sha256"]) == 64
    assert len(result["calibration"]["identity_set_sha256"]) == 64
    assert set(result["calibration"]["calibrator_hashes"]) == {
        "hitter.outcome",
        "hitter.impact",
        "pitcher.outcome",
        "pitcher.impact",
    }
    metrics = result["role_shape_governor_check"]["metrics"]
    assert metrics["top25_pitcher_count"] == 7
    assert metrics["max_top25_pitcher_count"] == 7
    assert metrics["top50_pitcher_rate"] == 0.3
    assert metrics["max_top50_pitcher_rate"] == 0.3


def test_blocked_readiness_prevents_any_model_or_rank_execution():
    result, model_calls, rank_calls = _evaluate(readiness=_readiness(ready=False))

    assert result["status"] == "blocked"
    assert result["current_role_shape_governor_passed"] is False
    assert result["blockers"] == ["registered_readiness_not_ready"]
    assert model_calls == []
    assert rank_calls == []


def test_official_deferred_current_contract_record_is_readiness_valid():
    readiness = _readiness()

    result, model_calls, rank_calls = _evaluate(readiness=readiness)

    assert readiness["hashes"]["source_files"][
        "current_prospect_contract"
    ] == {
        "path": "current_prospect_contract.json",
        "git_blob": "5" * 40,
        "binding": "git_blob_only_pre_reservation",
    }
    assert result["status"] == "passed"
    assert len(model_calls) == 1
    assert rank_calls == ["common_target"]


@pytest.mark.parametrize(
    "record",
    [
        {
            "path": "current_prospect_contract.json",
            "sha256": "a" * 64,
            "git_blob": "5" * 40,
        },
        {
            "path": "current_prospect_contract.json",
            "git_blob": "5" * 40,
            "binding": "wrong_binding",
        },
    ],
)
def test_current_contract_readiness_record_rejects_nonsealed_schema(record):
    readiness = _readiness()
    readiness["hashes"]["source_files"]["current_prospect_contract"] = record

    result, model_calls, rank_calls = _evaluate(readiness=readiness)

    assert result["status"] == "blocked"
    assert result["blockers"] == ["registered_readiness_not_ready"]
    assert model_calls == []
    assert rank_calls == []


def test_readiness_without_preregistered_current_context_hashes_fails_closed():
    readiness = _readiness()
    readiness["hashes"]["source_files"].pop("mlb_roster_status")

    result, model_calls, rank_calls = _evaluate(readiness=readiness)

    assert result["status"] == "blocked"
    assert result["blockers"] == ["registered_readiness_not_ready"]
    assert model_calls == []
    assert rank_calls == []


def test_missing_quality_start_evidence_fails_closed_before_model_execution():
    def missing_qs(contract, _universe, _calibration, _qs):
        contract["historical_mlb_seasons"]["100250_pitcher"] = [
            {"year": 2015, "ip": 60, "gs": 10}
        ]

    result, model_calls, rank_calls = _evaluate(mutate=missing_qs)

    assert result["status"] == "blocked"
    assert result["blockers"] == ["quality_starts_invalid: missing QS row: (100250, 2015)"]
    assert model_calls == []
    assert rank_calls == []


def test_malformed_quality_start_sidecar_returns_a_structured_blocker():
    result, model_calls, rank_calls = _evaluate(quality_starts_override=[])

    assert result["status"] == "blocked"
    assert result["blockers"] == ["quality_starts_invalid: sidecar must be a mapping"]
    assert model_calls == []
    assert rank_calls == []


def test_calibration_identity_must_exist_in_registered_mature_rows():
    def unknown_identity(_contract, _universe, calibration, _qs):
        calibration[0]["mlbam_id"] = 999_999

    result, model_calls, rank_calls = _evaluate(mutate=unknown_identity)

    assert result["status"] == "blocked"
    assert result["blockers"] == [
        "calibration_invalid: calibration identity is not a registered mature row: ('999999', 'hitter')"
    ]
    assert model_calls == []
    assert rank_calls == []


def test_calibration_cutoff_is_the_frozen_registered_maturity_boundary():
    result, model_calls, rank_calls = _evaluate(calibration_before_cohort=2023)

    assert result["status"] == "blocked"
    assert result["blockers"] == ["calibration_cutoff_not_registered"]
    assert model_calls == []
    assert rank_calls == []


def test_calibration_outcome_target_must_match_registered_label():
    def wrong_target(_contract, _universe, calibration, _qs):
        calibration[0]["outcome_tier"] = 1.0

    result, model_calls, rank_calls = _evaluate(mutate=wrong_target)

    assert result["status"] == "blocked"
    assert result["blockers"] == [
        "calibration_invalid: outcome target does not match registered label: ('100000', 'hitter')"
    ]
    assert model_calls == []
    assert rank_calls == []


def test_calibrator_content_hash_is_recomputed_before_application(monkeypatch):
    import prospects.pre2014_current_board as current_board

    real_builder = current_board.build_role_calibrator

    def tampered_builder(*args, **kwargs):
        calibrator = real_builder(*args, **kwargs)
        calibrator["sha256"] = "f" * 64
        return calibrator

    monkeypatch.setattr(current_board, "build_role_calibrator", tampered_builder)

    result, model_calls, rank_calls = _evaluate()

    assert result["status"] == "blocked"
    assert result["blockers"] == [
        "calibration_invalid: calibrator content hash mismatch: hitter.outcome"
    ]
    assert model_calls == []
    assert rank_calls == []


def test_rank_board_must_preserve_every_candidate_model_identity():
    result, model_calls, rank_calls = _evaluate(drop_last=True)

    assert result["status"] == "blocked"
    assert result["blockers"] == ["rank_identity_mismatch"]
    assert len(model_calls) == 1
    assert rank_calls == ["common_target"]


def test_pitcher_crowding_is_blocked_by_production_thresholds_without_relaxation():
    result, _, _ = _evaluate(crowded=True)

    assert result["status"] == "blocked"
    assert result["current_role_shape_governor_passed"] is False
    assert result["blockers"] == ["prospect_top_board_role_shape"]
    check = result["role_shape_governor_check"]
    assert check["metrics"]["top25_pitcher_count"] == 20
    assert check["metrics"]["max_top25_pitcher_count"] == 7
    assert check["metrics"]["max_top50_pitcher_rate"] == 0.3


def test_evaluator_performs_no_file_reads(monkeypatch):
    def forbidden_read(*_args, **_kwargs):
        raise AssertionError("current-board evaluator attempted a file read")

    monkeypatch.setattr(Path, "read_text", forbidden_read)

    result, _, _ = _evaluate()

    assert result["status"] == "passed"


def test_runner_callback_adapter_binds_research_history_and_returns_sealed_receipt(
    monkeypatch,
):
    import prospects.pre2014_current_board as current_board

    contract, universe, current_rows, calibration_rows, rank_context = _bundle()
    research_contract = {
        "artifact": "valucast_extended_prospect_history_labeled",
        "rows": deepcopy(contract["historical"]["rows"]),
        "historical_mlb_seasons": {},
    }
    qs = {
        "schema": "valucast_stage2_quality_starts",
        "status": "ready",
        "content_sha256": "a" * 64,
        "rows": [],
    }
    model_calls = []
    rank_calls = []
    monkeypatch.setattr(
        current_board,
        "build_registered_current_calibration_rows",
        lambda received_contract, received_qs: deepcopy(calibration_rows),
    )
    monkeypatch.setattr(
        current_board, "_default_model_builder", _model_builder(current_rows, model_calls)
    )
    monkeypatch.setattr(
        current_board, "_default_rank_builder", _rank_builder(rank_calls)
    )
    callback = make_current_board_governor_evaluator(
        contract,
        universe,
        {"generated_at": contract["generated_at"]},
        rank_context=rank_context,
        milb_history_by_key={("200001", "hitter"): {"rows": []}},
    )

    receipt = callback(
        reservation_id="sealed-reservation",
        research_contract=research_contract,
        quality_starts=qs,
        readiness=_readiness(),
    )

    assert receipt["passed"] is True
    assert receipt["unchanged_thresholds"] is True
    assert receipt["candidate_model_flags"] == {
        "PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"
    }
    assert receipt["model_score_mode"] == "common_target"
    assert receipt["reservation_id"] == "sealed-reservation"
    assert receipt["blockers"] == []
    check = receipt["role_shape_governor_check"]
    assert check["metrics"]["max_top25_pitcher_count"] == 7
    assert check["metrics"]["max_top50_pitcher_rate"] == 0.3
    assert receipt["governor_scope"] == "prospect_top_board_role_shape"
    assert receipt["full_governor_required_at"] == "post_look_pre_publication"
    assert receipt["thresholds"] == {
        "max_top25_pitcher_count": 7,
        "max_top50_pitcher_rate": 0.3,
    }
    assert set(receipt["input_hashes"]) >= {
        "current_prospect_contract",
        "prospect_universe",
        "dynasty_layer",
        "rank_context",
        "research_contract",
        "quality_starts",
        "readiness",
    }
    assert all(len(value) == 64 for value in receipt["input_hashes"].values())
    assert len(receipt["receipt_sha256"]) == 64
    assert len(model_calls) == 1
    assert rank_calls == ["common_target"]


def test_runner_callback_builds_serving_calibration_only_after_sealed_contract_arrives(
    monkeypatch,
):
    import prospects.pre2014_current_board as current_board

    contract, universe, current_rows, calibration_rows, rank_context = _bundle()
    qs = {
        "schema": "valucast_stage2_quality_starts",
        "status": "ready",
        "content_sha256": "a" * 64,
        "rows": [],
    }
    research_contract = {
        "artifact": "valucast_extended_prospect_history_labeled",
        "rows": deepcopy(contract["historical"]["rows"]),
        "historical_mlb_seasons": {},
        "quality_starts": qs,
    }
    calibration_calls = []

    def calibration_builder(received_contract, received_sidecar):
        calibration_calls.append((received_contract, received_sidecar))
        return deepcopy(calibration_rows)

    monkeypatch.setattr(
        current_board,
        "build_registered_current_calibration_rows",
        calibration_builder,
    )
    monkeypatch.setattr(
        current_board, "_default_model_builder", _model_builder(current_rows, [])
    )
    monkeypatch.setattr(
        current_board, "_default_rank_builder", _rank_builder([])
    )
    callback = make_current_board_governor_evaluator(
        contract,
        universe,
        {"generated_at": contract["generated_at"]},
        rank_context=rank_context,
    )
    assert calibration_calls == []

    receipt = callback(
        reservation_id="sealed-reservation",
        research_contract=research_contract,
        quality_starts=qs,
        readiness=_readiness(),
    )

    assert receipt["passed"] is True
    assert calibration_calls == [(research_contract, qs)]


def test_runner_callback_has_no_calibration_override_surface():
    parameters = inspect.signature(make_current_board_governor_evaluator).parameters

    assert "calibration_rows" not in parameters
    assert "calibration_rows_builder" not in parameters
    assert "model_builder" not in parameters
    assert "rank_builder" not in parameters
    assert "require_mlb_roster_status" not in parameters


def _hitter_mlb_season(year, *, pa=500, ops=0.780):
    return {
        "year": year,
        "pa": pa,
        "r": 80,
        "hr": 20,
        "rbi": 75,
        "sb": 10,
        "avg": 0.260,
        "ops": ops,
        "so": 130,
    }


def _pitcher_mlb_season(year):
    return {
        "year": year,
        "ip": 150,
        "gs": 20,
        "so": 150,
        "sv": 0,
        "hld": 0,
        "era": 4.0,
        "whip": 1.3,
        "k_bb": 3.0,
        "l": 10,
    }


def test_serving_calibration_builder_uses_mature_oof_folds_and_canonical_qs_seasons():
    rows = []
    seasons = {}
    qs_rows = []
    next_id = 300_000
    for cohort in (*range(2009, 2020), 2021):
        hitter_id = next_id
        pitcher_id = next_id + 1
        next_id += 2
        rows.extend(
            [
                {
                    "mlbam_id": hitter_id,
                    "role": "hitter",
                    "cohort_year": cohort,
                    "outcome": "role",
                },
                {
                    "mlbam_id": pitcher_id,
                    "role": "pitcher",
                    "cohort_year": cohort,
                    "outcome": "role",
                },
            ]
        )
        hitter_season = _hitter_mlb_season(cohort + 1)
        if cohort == 2009:
            seasons[f"{hitter_id}_hitter"] = [
                {**hitter_season, "pa": 200},
                {**hitter_season, "pa": 300},
                hitter_season,
            ]
        else:
            seasons[f"{hitter_id}_hitter"] = [hitter_season]
        seasons[f"{pitcher_id}_pitcher"] = [_pitcher_mlb_season(cohort + 1)]
        qs_rows.append(
            {
                "mlbam_id": pitcher_id,
                "season": cohort + 1,
                "games_started": 20,
                "quality_starts": 12,
            }
        )
    contract = {
        "rows": rows,
        "historical_mlb_seasons": seasons,
    }
    sidecar = {
        "schema": "valucast_stage2_quality_starts",
        "status": "ready",
        "content_sha256": "e" * 64,
        "rows": qs_rows,
    }
    observed_folds = []

    def raw_scorer(fold, *, model_flags):
        assert model_flags == {
            "PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"
        }
        observed_folds.append(fold["test_year"])
        if fold["test_year"] == 2013:
            assert len(fold["training_seasons"]["300000_hitter"]) == 1
            assert fold["training_seasons"]["300001_pitcher"][0]["qs"] == 12
        return (
            [
                {
                    **row,
                    "expected_outcome_score": 0.5,
                    "expected_category_impact_score": 0.5,
                }
                for row in fold["pseudo_current_rows"]
            ],
            {"test_year": fold["test_year"]},
        )

    calibration = build_registered_current_calibration_rows(
        contract,
        sidecar,
        raw_scorer=raw_scorer,
    )

    assert observed_folds == [2013, 2014, 2015, 2016, 2017, 2018, 2019, 2021]
    assert len(calibration) == 16
    assert {row["role"] for row in calibration} == {"hitter", "pitcher"}
    assert all(row["is_out_of_fold"] is True for row in calibration)
    assert all(row["source_fold"] == row["cohort_year"] for row in calibration)
    assert all(0.0 <= row["direct_7x7_target"] <= 1.0 for row in calibration)
