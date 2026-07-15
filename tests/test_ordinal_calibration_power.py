import hashlib

from prospects.ordinal_calibration_power import (
    build_oof_score_artifact,
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
