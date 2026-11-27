"""Tests for the serialized per-player outcome-score OOF artifact (R6)."""
import copy
import hashlib
import json
from statistics import mean

import pytest

from prospects.model import outcome_oof_rows
from prospects.outcome_oof import (
    ARTIFACT_PATH,
    run_outcome_oof_artifact,
    validate_outcome_oof_artifact,
)
from prospects.universal import INPUT_PATH, load_input_contract


def _committed_payload():
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_committed_outcome_oof_artifact_validates():
    assert validate_outcome_oof_artifact(_committed_payload()) == []


def test_committed_outcome_oof_stores_no_consensus_or_serving_leakage():
    payload = _committed_payload()
    policy = payload["prediction_policy"]
    assert policy["consensus_or_third_party_ranks_used"] is False
    assert policy["feeds_model_score"] is False
    assert policy["fold_trained_out_of_fold"] is True
    text = json.dumps(payload)
    # No third-party / consensus rank leakage in the artifact body.
    for banned in ("source_rank", "consensus_rank", "eephus", "board_count"):
        assert banned not in text


def test_pooled_mae_delta_reproduces_the_served_board_gate():
    # The whole point of R6: the committed artifact must reproduce the served
    # combined outcome-score MAE gate improvement_pct exactly.
    rows = _committed_payload()["rows"]
    mae_model = mean(abs(r["model_prediction"] - r["target"]) for r in rows)
    mae_prior = mean(abs(r["prior_prediction"] - r["target"]) for r in rows)
    mae_neighbor = mean(abs(r["neighbor_prediction"] - r["target"]) for r in rows)
    baseline = min(mae_prior, mae_neighbor)  # gate picks the lower (better) MAE
    delta_pct = (baseline - mae_model) / abs(baseline) * 100.0
    assert round(delta_pct, 4) == pytest.approx(6.3566, abs=1e-4)


def test_outcome_oof_rows_realign_flat_predictions_to_players():
    contract = load_input_contract(INPUT_PATH)
    rows = outcome_oof_rows("hitter", contract["historical"]["rows"])
    assert rows
    # every fold trains strictly before its test cohort
    assert all(r["train_cohort_max"] < r["test_cohort"] for r in rows)
    # identities unique within a fold
    seen = set()
    for r in rows:
        key = (r["mlbam_id"], r["test_cohort"])
        assert key not in seen
        seen.add(key)


def test_validator_rejects_duplicate_identity():
    payload = _committed_payload()
    broken = copy.deepcopy(payload)
    broken["rows"].append(copy.deepcopy(broken["rows"][0]))
    problems = validate_outcome_oof_artifact(broken)
    assert any("duplicates an OOF identity" in p for p in problems)


def test_validator_rejects_non_ordinal_target():
    payload = _committed_payload()
    broken = copy.deepcopy(payload)
    broken["rows"][0]["target"] = 0.7
    problems = validate_outcome_oof_artifact(broken)
    assert any("ordinal outcome tier" in p for p in problems)


def test_validator_rejects_leaky_prediction_policy():
    payload = _committed_payload()
    broken = copy.deepcopy(payload)
    broken["prediction_policy"]["feeds_model_score"] = True
    problems = validate_outcome_oof_artifact(broken)
    assert any("research-only OOF contract" in p for p in problems)


def test_run_writes_and_validates_a_fresh_artifact(tmp_path):
    artifact_path = tmp_path / "outcome_oof.json"
    result = run_outcome_oof_artifact(artifact_path=artifact_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert validate_outcome_oof_artifact(payload) == []
    assert result["row_count"] == len(payload["rows"])
    # input sha256 matches the committed contract bytes
    expected = hashlib.sha256(INPUT_PATH.read_bytes()).hexdigest()
    assert payload["input"]["sha256"] == expected
