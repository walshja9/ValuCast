import hashlib

import numpy as np
import pytest

from prospects.ordinal_calibration_power import (
    _calibrate_intercept_effect,
    _calibrate_slope_effect,
    _expected_tier_gap,
    _ordered_probabilities,
    build_power_artifact,
    build_oof_score_artifact,
    likelihood_ratio_test,
    validate_power_artifact,
    validate_oof_score_artifact,
)


def _folds():
    folds = []
    for cohort in (2018, 2019, 2021):
        data = {
            "scores": {
                (f"{cohort}01", "hitter"): 51.0,
                (f"{cohort}02", "pitcher"): 49.0,
            },
            "tiers": {
                (f"{cohort}01", "hitter"): 1.0,
                (f"{cohort}02", "pitcher"): 0.0,
            },
        }
        diagnostics = {
            "test_cohort": cohort,
            "train_cohort_max": cohort - 4,
            "pseudo_universe": 2,
            "board_rows": 2,
            "scored_and_labeled": 2,
            "hitters": 1,
            "pitchers": 1,
            "score_source_counts": {"prospect_model_v0_6": 2},
            "rank_status": "shadow_only",
        }
        folds.append((cohort, data, diagnostics))
    return folds


def test_oof_artifact_records_fold_role_counts_and_identity_hashes():
    payload = build_oof_score_artifact(
        _folds(),
        input_sha256="a" * 64,
        generated_at="2026-07-15T16:00:00+00:00",
    )

    assert payload["status"] == "research_only"
    assert payload["prediction_policy"] == {
        "fold_trained_out_of_fold": True,
        "in_sample_predictions_used": False,
        "todays_model_used": False,
        "current_board_rows_used": False,
        "historical_role_terms_fitted": False,
    }
    assert len(payload["rows"]) == 6
    for fold in payload["folds"]:
        assert fold["row_count"] == 2
        assert fold["roles"]["hitter"]["row_count"] == 1
        assert fold["roles"]["pitcher"]["row_count"] == 1
        for role in ("hitter", "pitcher"):
            row = next(
                item
                for item in payload["rows"]
                if item["test_cohort"] == fold["test_cohort"]
                and item["role"] == role
            )
            expected = hashlib.sha256(
                f"{row['mlbam_id']}|{role}".encode("utf-8")
            ).hexdigest()
            assert fold["roles"][role]["identity_sha256"] == expected
    assert validate_oof_score_artifact(payload) == []


def test_oof_validator_rejects_tampering_and_historical_role_output():
    payload = build_oof_score_artifact(_folds(), input_sha256="b" * 64)
    payload["rows"][0]["mlbam_id"] = "tampered"
    payload["historical_role_fit"] = {"pitcher_intercept": 0.1}

    problems = validate_oof_score_artifact(payload)

    assert "unexpected top-level fields: historical_role_fit" in problems
    assert any("identity_sha256" in problem for problem in problems)


def test_registered_effect_calibration_hits_frozen_targets():
    score = np.linspace(-1.5, 1.5, 301)
    blind_x = np.column_stack((score, np.zeros_like(score), np.zeros_like(score)))
    nuisance = np.array([-0.6, 0.1, 0.8, 0.0, 0.0])

    intercept = _calibrate_intercept_effect(nuisance, blind_x)
    slope = _calibrate_slope_effect(nuisance, blind_x)
    intercept_gap = _expected_tier_gap(nuisance, blind_x, intercept, 0.0)
    slope_gap = _expected_tier_gap(nuisance, blind_x, 0.0, slope)

    assert intercept < 0
    assert slope < 0
    assert float(intercept_gap.mean()) == pytest.approx(-0.10, abs=1e-6)
    assert float(np.sqrt(np.mean(np.square(slope_gap)))) == pytest.approx(
        0.10, abs=1e-6
    )


def test_two_df_lrt_detects_strong_simulated_role_effect():
    rng = np.random.default_rng(41)
    n = 900
    score = rng.normal(0.0, 0.8, n)
    folds = np.arange(n) % 3
    blind_x = np.column_stack((score, folds == 1, folds == 2)).astype(float)
    pitcher = (np.arange(n) % 2).astype(float)
    nuisance = np.array([-0.7, 0.2, 0.9, 0.1, -0.1])
    full_x = np.column_stack((blind_x, pitcher, pitcher * score))
    full_params = np.concatenate((nuisance, [-1.0, 0.0]))
    probabilities = _ordered_probabilities(full_params, full_x)
    draws = rng.random(n)
    outcomes = (draws > probabilities[:, 0]).astype(int)
    outcomes += (draws > probabilities[:, :2].sum(axis=1)).astype(int)

    result = likelihood_ratio_test(blind_x, pitcher, outcomes)

    assert result["degrees_of_freedom"] == 2
    assert result["p_value"] < 0.05


def test_power_validator_locks_protocol_and_forbids_historical_role_fit():
    payload = build_power_artifact(
        oof_sha256="c" * 64,
        row_count=2218,
        common_support_count=2000,
        scenario_results={
            "intercept_penalty": {
                "target": -0.1,
                "achieved": -0.1,
                "injected_effect": -0.8,
                "rejections": 750,
            },
            "slope_interaction": {
                "target": 0.1,
                "achieved": 0.1,
                "injected_effect": -0.7,
                "rejections": 690,
            },
        },
        generated_at="2026-07-15T17:00:00+00:00",
    )

    assert payload["status"] == "underpowered"
    assert payload["historical_fit"]["pitcher_intercept_fitted"] is False
    assert payload["promotion"]["historical_look_authorized"] is False
    assert validate_power_artifact(payload) == []

    payload["protocol"]["seed"] = 1
    payload["historical_fit"]["pitcher_score_slope_fitted"] = True
    problems = validate_power_artifact(payload)
    assert "protocol does not match the registered simulation" in problems
    assert "historical pitcher terms must remain unfit and unreported" in problems
