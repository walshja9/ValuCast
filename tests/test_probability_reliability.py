"""Tests for the probability-reliability artifact (audit repair R4)."""
import copy
import hashlib
import json

from prospects.outcome_oof import ARTIFACT_PATH as OUTCOME_OOF_PATH
from prospects.probability_reliability import (
    ARTIFACT_PATH,
    _wilson_interval,
    build_probability_reliability,
    run_probability_reliability,
    validate_probability_reliability,
)


def _committed():
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_committed_reliability_validates():
    assert validate_probability_reliability(_committed()) == []


def test_reliability_reproduces_the_probability_nonlinear_truth():
    payload = _committed()
    for role in ("hitter", "pitcher"):
        summary = payload["roles"][role]
        resolution = summary["resolution"]
        # bottom deciles near-flat, resolution concentrated in the top deciles
        assert resolution["resolution_concentrated_in_top_deciles"] is True
        assert resolution["bottom_max_realized_mean"] < resolution["top_min_realized_mean"]
        bins = summary["bins"]
        assert len(bins) == 10
        # bottom decile realized outcome is near-zero; top decile is materially higher
        assert bins[0]["realized_mean"] < 0.10
        assert bins[-1]["realized_mean"] > bins[0]["realized_mean"]


def test_committed_reliability_stores_no_leakage():
    payload = _committed()
    policy = payload["policy"]
    assert policy["feeds_model_score"] is False
    assert policy["consensus_or_third_party_ranks_used"] is False
    text = json.dumps(payload)
    for banned in ("source_rank", "consensus_rank", "eephus", "board_count"):
        assert banned not in text


def test_ece_is_count_weighted_mean_abs_gap():
    # Recomputed from the (6dp-rounded) bin means, so allow rounding drift.
    payload = _committed()
    for role in ("hitter", "pitcher"):
        summary = payload["roles"][role]
        total = summary["sample_size"]
        expected = sum(
            (b["count"] / total) * abs(b["predicted_mean"] - b["realized_mean"])
            for b in summary["bins"]
        )
        assert abs(expected - summary["expected_calibration_error"]) < 1e-5


def test_wilson_interval_matches_known_value():
    # 5 of 20 successes, z=1.96 -> Wilson 95% CI ~ [0.112, 0.469].
    interval = _wilson_interval(5, 20)
    assert 0.10 < interval["low"] < 0.12
    assert 0.45 < interval["high"] < 0.48
    assert _wilson_interval(0, 0) == {"low": None, "high": None}


def test_validator_rejects_leaky_policy():
    payload = _committed()
    broken = copy.deepcopy(payload)
    broken["policy"]["feeds_model_score"] = True
    problems = validate_probability_reliability(broken)
    assert any("feeds_model_score must be false" in p for p in problems)


def test_validator_rejects_mismatched_sample_size():
    payload = _committed()
    broken = copy.deepcopy(payload)
    broken["roles"]["hitter"]["sample_size"] += 1
    problems = validate_probability_reliability(broken)
    assert any("sample_size does not match" in p for p in problems)


def test_run_writes_and_binds_to_the_committed_oof(tmp_path):
    artifact_path = tmp_path / "reliability.json"
    run_probability_reliability(artifact_path=artifact_path)
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert validate_probability_reliability(payload) == []
    expected = hashlib.sha256(OUTCOME_OOF_PATH.read_bytes()).hexdigest()
    assert payload["source"]["sha256"] == expected


def test_build_rejects_invalid_oof_payload():
    bad_oof = {"artifact": "not_the_oof", "rows": []}
    try:
        build_probability_reliability(bad_oof, oof_sha256="0" * 64)
    except ValueError as exc:
        assert "outcome OOF artifact invalid" in str(exc)
    else:
        raise AssertionError("expected ValueError on invalid OOF payload")
