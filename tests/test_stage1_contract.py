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


def _contract(model, layer, state="incumbent"):
    expected = {
        "incumbent": {
            "expected_model_version": "0.6.1",
            "expected_model_consumer": "prospect_rank_v1",
            "expected_layer_consumer": "prospect_rank_v1",
            "expected_score_source": "prospect_model_v0_6",
            "expected_model_feed": True,
            "expected_layer_feed": True,
        },
        "candidate": {
            "expected_model_version": "0.8.0",
            "expected_model_consumer": "prospect_rank_v2",
            "expected_layer_consumer": "prospect_rank_v2",
            "expected_score_source": "prospect_model_v0_8",
            "expected_model_feed": False,
            "expected_layer_feed": False,
        },
        "promoted": {
            "expected_model_version": "0.8.0",
            "expected_model_consumer": "prospect_rank_v2",
            "expected_layer_consumer": "prospect_rank_v2",
            "expected_score_source": "prospect_model_v0_8",
            "expected_model_feed": False,
            "expected_layer_feed": True,
        },
    }[state]
    return build_stage1_contract(
        model,
        layer,
        "2026-07-22T00:00:00+00:00",
        state=state,
        **expected,
    )


def test_contract_binds_served_profiles_without_mutating_inputs():
    model, layer = _model(), _layer()
    before = deepcopy((model, layer))
    result = _contract(model, layer)
    assert result["contract_version"] == "1.0.0"
    assert result["state"] == "incumbent"
    assert result["generated_date"] == "2026-07-22"
    assert result["model_consumer"] == "prospect_rank_v1"
    assert result["layer_consumer"] == "prospect_rank_v1"
    assert result["score_source"] == "prospect_model_v0_6"
    assert result["profiles_by_key"][("1", "hitter")]["model_profile"]["expected_outcome_score"] == 0.6
    assert result["profiles_by_key"][("1", "hitter")]["outcome_profile"]["mlbam_id"] == 1
    assert (model, layer) == before


@pytest.mark.parametrize("state", ["research", "shadow"])
def test_contract_rejects_non_served_states(state):
    with pytest.raises(ValueError, match="Stage 1 state"):
        build_stage1_contract(
            _model(),
            _layer(),
            "2026-07-22",
            state=state,
            expected_model_version="0.6.1",
            expected_model_consumer="prospect_rank_v1",
            expected_layer_consumer="prospect_rank_v1",
            expected_score_source="prospect_model_v0_6",
            expected_model_feed=True,
            expected_layer_feed=True,
        )


@pytest.mark.parametrize("state,layer_feed", [("candidate", False), ("promoted", True)])
def test_v2_contract_requires_exact_model_source_and_state_specific_layer_feed(
    state, layer_feed
):
    model = _model()
    model["model_version"] = "0.8.0"
    model["release_contract"] = {
        "consumer": "prospect_rank_v2",
        "score_source": "prospect_model_v0_8",
        "feeds_live_valucast_rank": False,
    }
    model["ranked"][0]["score_source"] = "prospect_model_v0_8"
    layer = _layer()
    layer["release_contract"] = {
        "consumer": "prospect_rank_v2",
        "feeds_live_valucast_rank": layer_feed,
    }

    result = _contract(model, layer, state)

    assert result["state"] == state
    assert result["score_source"] == "prospect_model_v0_8"


def test_contract_rejects_stale_or_non_serving_artifacts():
    layer = _layer()
    layer["generated_at"] = "2026-07-21T00:00:00+00:00"
    with pytest.raises(ValueError, match="generated date"):
        _contract(_model(), layer)

    layer = _layer()
    layer["release_contract"]["feeds_live_valucast_rank"] = False
    with pytest.raises(ValueError, match="not authorized"):
        _contract(_model(), layer)


@pytest.mark.parametrize("target", ["expected", "model", "layer"])
def test_contract_rejects_malformed_generated_timestamps(target):
    model, layer = _model(), _layer()
    expected = "2026-07-22T00:00:00+00:00"
    if target == "expected":
        expected = "2026-07-22-invalid"
    elif target == "model":
        model["input_contract"]["generated_at"] = "2026-07-22-invalid"
    else:
        layer["generated_at"] = "2026-07-22-invalid"

    with pytest.raises(ValueError, match="generated date"):
        build_stage1_contract(
            model,
            layer,
            expected,
            state="incumbent",
            expected_model_version="0.6.1",
            expected_model_consumer="prospect_rank_v1",
            expected_layer_consumer="prospect_rank_v1",
            expected_score_source="prospect_model_v0_6",
            expected_model_feed=True,
            expected_layer_feed=True,
        )


@pytest.mark.parametrize("bucket", ["ranked", "profiles"])
def test_contract_rejects_duplicate_or_invalid_identity(bucket):
    model, layer = _model(), _layer()
    source = model if bucket == "ranked" else layer
    source[bucket].append(deepcopy(source[bucket][0]))
    with pytest.raises(ValueError, match="duplicate"):
        _contract(model, layer)

    model, layer = _model(), _layer()
    source = model if bucket == "ranked" else layer
    source[bucket][0]["role"] = "two_way"
    with pytest.raises(ValueError, match="role"):
        _contract(model, layer)


@pytest.mark.parametrize(
    "mutation",
    ["version", "model_consumer", "model_feed", "layer_consumer", "layer_feed"],
)
def test_v2_contract_rejects_wrong_lineage_metadata(mutation):
    model = _model()
    model["model_version"] = "0.8.0"
    model["release_contract"] = {
        "consumer": "prospect_rank_v2",
        "score_source": "prospect_model_v0_8",
        "feeds_live_valucast_rank": False,
    }
    model["ranked"][0]["score_source"] = "prospect_model_v0_8"
    layer = _layer()
    layer["release_contract"] = {
        "consumer": "prospect_rank_v2",
        "feeds_live_valucast_rank": False,
    }
    if mutation == "version":
        model["model_version"] = "0.7.0"
    elif mutation == "model_consumer":
        model["release_contract"]["consumer"] = "prospect_rank_v1"
    elif mutation == "model_feed":
        model["release_contract"]["feeds_live_valucast_rank"] = True
    elif mutation == "layer_consumer":
        layer["release_contract"]["consumer"] = "prospect_rank_v1"
    else:
        layer["release_contract"]["feeds_live_valucast_rank"] = True

    with pytest.raises(ValueError):
        _contract(model, layer, "candidate")


@pytest.mark.parametrize("source", [None, "prospect_model_v0_7"])
def test_v2_contract_rejects_missing_or_mixed_row_source(source):
    model = _model()
    model["model_version"] = "0.8.0"
    model["release_contract"] = {
        "consumer": "prospect_rank_v2",
        "score_source": "prospect_model_v0_8",
        "feeds_live_valucast_rank": False,
    }
    model["ranked"][0]["score_source"] = source
    layer = _layer()
    layer["release_contract"] = {
        "consumer": "prospect_rank_v2",
        "feeds_live_valucast_rank": False,
    }
    with pytest.raises(ValueError, match="source"):
        _contract(model, layer, "candidate")


def test_v1_contract_rejects_an_explicit_wrong_source():
    model = _model()
    model["release_contract"]["score_source"] = "prospect_model_v0_7"
    with pytest.raises(ValueError, match="source"):
        _contract(model, _layer())
