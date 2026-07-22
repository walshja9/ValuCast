from copy import deepcopy

import pytest

from prospects.stage1_contract import build_stage1_contract


def _model():
    return {
        "model_version": "0.6.1",
        "input_contract": {"generated_at": "2026-07-22T00:00:00+00:00"},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "ranked": [{"mlbam_id": 1, "role": "hitter", "expected_outcome_score": 0.6}],
    }


def _layer():
    return {
        "generated_at": "2026-07-22T00:00:00+00:00",
        "layer_version": "0.1.0",
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "profiles": [{"mlbam_id": 1, "role": "hitter", "outcome_distribution": {}}],
    }


def test_contract_binds_served_profiles_without_mutating_inputs():
    model, layer = _model(), _layer()
    before = deepcopy((model, layer))
    result = build_stage1_contract(model, layer, "2026-07-22T00:00:00+00:00")
    assert result["contract_version"] == "1.0.0"
    assert result["state"] == "incumbent"
    assert result["generated_date"] == "2026-07-22"
    assert result["profiles_by_key"][("1", "hitter")]["model_profile"]["expected_outcome_score"] == 0.6
    assert result["profiles_by_key"][("1", "hitter")]["outcome_profile"]["mlbam_id"] == 1
    assert (model, layer) == before


@pytest.mark.parametrize("state", ["research", "shadow", "candidate"])
def test_contract_rejects_non_served_states(state):
    with pytest.raises(ValueError, match="Stage 1 state"):
        build_stage1_contract(_model(), _layer(), "2026-07-22", state=state)


def test_contract_rejects_stale_or_non_serving_artifacts():
    layer = _layer()
    layer["generated_at"] = "2026-07-21T00:00:00+00:00"
    with pytest.raises(ValueError, match="generated date"):
        build_stage1_contract(_model(), layer, "2026-07-22")

    layer = _layer()
    layer["release_contract"]["feeds_live_valucast_rank"] = False
    with pytest.raises(ValueError, match="not authorized"):
        build_stage1_contract(_model(), layer, "2026-07-22")


@pytest.mark.parametrize("bucket", ["ranked", "profiles"])
def test_contract_rejects_duplicate_or_invalid_identity(bucket):
    model, layer = _model(), _layer()
    source = model if bucket == "ranked" else layer
    source[bucket].append(deepcopy(source[bucket][0]))
    with pytest.raises(ValueError, match="duplicate"):
        build_stage1_contract(model, layer, "2026-07-22")

    model, layer = _model(), _layer()
    source = model if bucket == "ranked" else layer
    source[bucket][0]["role"] = "two_way"
    with pytest.raises(ValueError, match="role"):
        build_stage1_contract(model, layer, "2026-07-22")
