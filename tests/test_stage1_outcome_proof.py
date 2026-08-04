from prospects.stage1_outcome_proof import auc, build_role_metrics


def _row(player, cohort, target, model, prior, neighbor, role="hitter"):
    return {
        "mlbam_id": str(player),
        "role": role,
        "test_cohort": cohort,
        "train_cohort_max": cohort - 1,
        "model_prediction": model,
        "prior_prediction": prior,
        "neighbor_prediction": neighbor,
        "target": target,
    }


def test_auc_is_tie_correct_and_requires_both_classes():
    assert auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert auc([0.5, 0.5], [0, 1]) == 0.5
    assert auc([0.1, 0.2], [0, 0]) is None


def test_role_metrics_are_outcome_ordered_and_seeded():
    rows = [
        _row(1, 2018, 0.0, 0.1, 0.9, 0.8),
        _row(2, 2018, 0.5, 0.5, 0.5, 0.5),
        _row(3, 2019, 1.0, 0.9, 0.1, 0.2),
        _row(4, 2019, 0.0, 0.1, 0.9, 0.8),
    ]
    first = build_role_metrics(rows, seed=34041, resamples=100)
    second = build_role_metrics(list(reversed(rows)), seed=34041, resamples=100)
    assert first == second
    assert first["sample_size"] == 4
    assert first["cohort_count"] == 2
    assert first["contributor_base_rate"] == 0.5
    assert first["metrics"]["roc_auc"]["model"]["point"] == 1.0
    assert first["metrics"]["spearman_rho"]["model"]["point"] == 1.0
    assert first["metrics"]["kendall_tau_b"]["model"]["point"] == 1.0
    assert first["metrics"]["roc_auc"]["level_age_prior"]["point"] == 0.0
    assert set(first["cohorts"]) == {"2018", "2019"}
    assert (
        first["metrics"]["roc_auc"]["model_minus_baseline"]["level_age_prior"]
        ["historical_support"]
        is False
    )


def test_role_metrics_keep_undefined_metrics_descriptive():
    metrics = build_role_metrics(
        [
            _row(1, 2018, 0.0, 0.1, 0.2, 0.3),
            _row(2, 2018, 0.0, 0.9, 0.8, 0.7),
        ],
        seed=34041,
        resamples=2,
    )

    comparison = metrics["metrics"]["roc_auc"]["model_minus_baseline"]["level_age_prior"]
    assert comparison["point"] is None
    assert comparison["historical_support"] is False
