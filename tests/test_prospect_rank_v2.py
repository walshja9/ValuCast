from __future__ import annotations

from copy import deepcopy

import pytest

import prospects.rank_v1 as rank_v1
import prospects.rank_v2 as rank_v2
from prospects.rank_v2 import (
    _v2_dynasty_layer,
    _v2_investment_evidence,
    build_fold_contract,
    build_prospect_rank_v2,
    reconstruct_fold_scores,
)
from test_prospect_rank_v1 import (
    _dynasty_layer,
    _input_contract,
    _investment_evidence,
    _prospect_model,
    _universe,
)


def _v08_model() -> dict:
    return {
        "model_version": "0.8.0",
        "score_source": "prospect_model_v0_8",
        "release_contract": {
            "consumer": "prospect_rank_v2",
            "score_source": "prospect_model_v0_8",
            "feeds_live_valucast_rank": False,
        },
    }


def _calibrator() -> dict:
    return {"version": "2.0.0", "artifact_sha256": "calibrator-hash"}


def _scoring_fixture(monkeypatch):
    def raw(rows, model):
        assert len(rows) == 1
        return [
            {
                "mlbam_id": 1,
                "role": "hitter",
                "expected_outcome_score": 0.7,
                "expected_category_impact_score": 0.6,
                "raw_composite": 0.658,
                "score_source": "prospect_model_v0_8",
            }
        ]

    def calibrated(rows, calibrator):
        return [
            {
                **row,
                "calibrated_expected_tier": 0.75,
                "calibrator_sha256": calibrator["artifact_sha256"],
            }
            for row in rows
        ]

    monkeypatch.setattr(rank_v2, "score_v08_profiles", raw)
    monkeypatch.setattr(rank_v2, "score_profiles", calibrated)


def _wrapper_inputs():
    contract = _input_contract()
    contract["current"]["hitters"] = contract["current"]["hitters"][:1]
    contract["current"]["hitters"][0].update(
        {
            "role": "hitter",
            "level": "AA",
            "age": 20,
            "iso": 0.18,
            "k_pct": 20.0,
            "bb_pct": 10.0,
            "ops": 0.8,
        }
    )
    return _universe(), _dynasty_layer(), _v08_model(), contract, _calibrator()


def test_v2_uses_calibrated_tier_without_role_quantiles(monkeypatch):
    _scoring_fixture(monkeypatch)
    monkeypatch.setattr(
        rank_v1,
        "_apply_role_quantile_model_score_normalization",
        lambda _rows: (_ for _ in ()).throw(
            AssertionError("v2 called role-quantile normalization")
        ),
    )
    payload = build_prospect_rank_v2(*_wrapper_inputs(), state="candidate")
    row = next(row for row in payload["board"] if row["mlbam_id"] == 1)
    assert row["score_source"] == "prospect_model_v0_8"
    assert row["components"]["model_score"] == 75.0
    assert "model_score_normalization" not in row["components"]
    assert payload["rank_name"] == "ValuCast Prospect Rank v2"
    assert payload["rank_version"] == "2.0.0"


def test_v2_rewraps_dynasty_metadata_without_changing_profiles():
    layer = _dynasty_layer()
    original = deepcopy(layer)
    candidate = _v2_dynasty_layer(layer, state="candidate")
    promoted = _v2_dynasty_layer(layer, state="promoted")

    assert candidate["profiles"] == original["profiles"]
    assert promoted["profiles"] == original["profiles"]
    assert layer == original
    assert candidate["release_contract"]["consumer"] == "prospect_rank_v2"
    assert candidate["release_contract"]["feeds_live_valucast_rank"] is False
    assert promoted["release_contract"]["feeds_live_valucast_rank"] is True


def test_candidate_and_promoted_render_identical_rows(monkeypatch):
    _scoring_fixture(monkeypatch)
    inputs = _wrapper_inputs()
    candidate = build_prospect_rank_v2(*inputs, state="candidate")
    promoted = build_prospect_rank_v2(*inputs, state="promoted")

    assert candidate["board"] == promoted["board"]
    assert candidate["input_artifacts"]["stage1_state"] == "candidate"
    assert promoted["input_artifacts"]["stage1_state"] == "promoted"


def test_v2_rewraps_investment_policy_without_changing_facts():
    evidence = _investment_evidence()
    original = deepcopy(evidence)
    wrapped = _v2_investment_evidence(evidence)
    assert wrapped["rows"] == original["rows"]
    assert evidence == original
    assert wrapped["source_policy"]["permitted_use"] == (
        "prospect_rank_v2_factual_investment_context_only"
    )


def test_fold_contract_binds_one_in_memory_cohort(monkeypatch):
    row = {
        "mlbam_id": 1,
        "role": "hitter",
        "cohort_year": 2021,
        "level": "AA",
        "age": 21,
        "outcome": "role",
        "plate_appearances": 300,
        "iso": 0.15,
        "k_pct": 22.0,
        "bb_pct": 10.0,
        "ops": 0.75,
    }
    source = {
        "schema_version": "prospect_v2_development_contract_v1",
        "mature_through": 2021,
        "historical": {"rows": [row]},
        "historical_mlb_seasons": {},
    }
    context = {
        "prospect_universe": {},
        "dynasty_layer": {},
        "prospect_availability": None,
        "mlb_roster_status": None,
        "milb_history_by_key": None,
        "investment_evidence": None,
        "manual_graduated_ids": set(),
        "consensus_snapshots": {key: {} for key in ("sts", "fangraphs", "prospectslive", "pipeline", "hkb")},
        "incumbent_profiles": [],
        "input_contract": {"generated_at": "2021-09-30T00:00:00+00:00"},
    }
    monkeypatch.setattr(
        "prospects.rank_backtest.build_fold_rank_context",
        lambda *_args, **_kwargs: context,
    )

    fold = build_fold_contract(source, 2021)
    assert fold["test_cohort"] == 2021
    assert {item["cohort_year"] for item in fold["eligible_rows"]} == {2021}
    assert fold["input_contract"]["generated_at"] == "2021-09-30T00:00:00+00:00"


def test_reconstruct_fold_scores_rejects_cohort_mismatch():
    with pytest.raises(ValueError, match="cohort mismatch"):
        reconstruct_fold_scores(
            {"test_cohort": 2022}, [], _calibrator(), 2021
        )


def test_reconstruct_fold_scores_pairs_v1_and_v2_on_identical_identities():
    context = {
        "prospect_universe": _universe(),
        "dynasty_layer": _dynasty_layer(),
        "prospect_availability": None,
        "mlb_roster_status": None,
        "milb_history_by_key": None,
        "investment_evidence": None,
        "manual_graduated_ids": set(),
        "consensus_snapshots": {key: {} for key in ("sts", "fangraphs", "prospectslive", "pipeline", "hkb")},
        "incumbent_profiles": _prospect_model()["ranked"],
    }
    fold = {
        "test_cohort": 2021,
        "targets": {("1", "hitter"): 0.5, ("2", "hitter"): 0.0},
        "input_contract": _input_contract(),
        "context": context,
    }
    candidates = [
        {
            "mlbam_id": mlbam_id,
            "role": "hitter",
            "score_source": "prospect_model_v0_8",
            "calibrated_expected_tier": tier,
            "calibrator_sha256": "calibrator-hash",
        }
        for mlbam_id, tier in ((1, 0.75), (2, 0.25))
    ]

    rows = reconstruct_fold_scores(fold, candidates, _calibrator(), 2021)
    assert set(rows[0]) == {
        "mlbam_id",
        "role",
        "target",
        "candidate_final_score",
        "incumbent_final_score",
    }
    assert {(str(row["mlbam_id"]), row["role"]) for row in rows} == set(fold["targets"])
