"""Tests for the fixed-horizon prospect dynasty-layer gate."""
import json

from prospects.dynasty_backtest import (
    _multiclass_brier,
    _temporal_stability_guard,
    _weighted_fold_metric,
    build_backtest,
    run_backtest,
)


def _row(role, cohort, mlbam_id):
    row = {
        "cohort_year": cohort,
        "mlbam_id": mlbam_id,
        "role": role,
        "level": "AA" if mlbam_id % 2 else "AAA",
        "age": 21 + mlbam_id % 3,
    }
    if role == "hitter":
        row.update({"iso": 0.150, "k_pct": 22.0, "bb_pct": 9.0, "ops": 0.760})
    else:
        row.update(
            {
                "k_per_9": 9.0,
                "bb_per_9": 3.0,
                "k_bb_pct": 15.0,
                "era": 3.80,
                "whip": 1.20,
                "is_starter": mlbam_id % 3 != 0,
            }
        )
    return row


def _contract():
    rows, seasons = [], {}
    for role in ("hitter", "pitcher"):
        offset = 0 if role == "hitter" else 10000
        for cohort in (2012, 2016, 2020):
            for index in range(1, 9):
                mlbam_id = offset + cohort * 100 + index
                rows.append(_row(role, cohort, mlbam_id))
                if index % 3 == 0:
                    seasons[f"{mlbam_id}_{role}"] = []
                elif role == "hitter":
                    seasons[f"{mlbam_id}_{role}"] = [
                        {
                            "year": cohort + 2,
                            "pa": 500,
                            "ops": 0.810 if index % 2 else 0.750,
                        }
                    ]
                else:
                    seasons[f"{mlbam_id}_{role}"] = [
                        {
                            "year": cohort + 2,
                            "ip": 130,
                            "era": 3.70 if index % 2 else 4.20,
                        }
                    ]
    return {
        "schema_version": "1.0",
        "generated_at": "2026-06-13T00:00:00+00:00",
        "source_policy": {
            "kind": "factual_only",
            "sources": [
                "prospect_outcome_dataset",
                "milb_season_stats",
                "fantrax_mlb_actuals",
                "mlb_prospect_seasons_cache",
            ],
            "external_rankings_used": False,
            "external_projections_used": False,
            "market_values_used": False,
            "dynasty_values_used": False,
        },
        "historical": {"rows": rows},
        "historical_mlb_seasons": seasons,
        "current": {"hitters": [], "pitchers": []},
        "mlb_service": [],
    }


def test_multiclass_brier_rewards_coherent_correct_distribution():
    actual = [
        {
            "bust_probability": 0.0,
            "role_probability": 0.0,
            "star_probability": 1.0,
        }
    ]
    assert _multiclass_brier(actual, actual) == 0.0


def test_backtest_uses_longest_supported_closed_horizon_and_blocks_live_use():
    payload = build_backtest(_contract(), now="2026-06-13T00:00:00+00:00")

    assert payload["validation_contract"]["outcome_horizon_years"] == 4
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["feeds_live_dd_value"] is False
    assert payload["promotion"]["feeds_live_valucast_rank"] is False
    for result in payload["roles"].values():
        assert result["gate"]["status"] == "insufficient_sample"
        assert result["ordering_guard"]["status"] == "insufficient_sample"
        assert result["temporal_stability_guard"]["status"] == "active"
        assert all(
            fold["train_cohort_max"] <= fold["test_cohort"] - 4
            for fold in result["folds"]
        )


def test_weighted_fold_metric_uses_only_comparable_cohort_scores():
    folds = [
        {"sample_size": 100, "score": 0.60},
        {"sample_size": 300, "score": 0.80},
    ]
    assert _weighted_fold_metric(folds, "score") == 0.75


def test_temporal_stability_guard_rejects_any_fold_regression():
    folds = [
        {
            "candidate_multiclass_brier": 0.20,
            "baseline_multiclass_brier": 0.21,
            "candidate_rank_concordance": 0.70,
            "baseline_rank_concordance": 0.69,
        },
        {
            "candidate_multiclass_brier": 0.19,
            "baseline_multiclass_brier": 0.20,
            "candidate_rank_concordance": 0.60,
            "baseline_rank_concordance": 0.61,
        },
    ]
    guard = _temporal_stability_guard(folds)
    assert guard["status"] == "hold"
    assert guard["ordering_non_regression_every_fold"] is False


def test_run_backtest_writes_separate_evidence_artifact(tmp_path):
    input_path = tmp_path / "inputs.json"
    artifact_path = tmp_path / "dynasty-backtest.json"
    input_path.write_text(json.dumps(_contract()), encoding="utf-8")

    result = run_backtest(input_path, artifact_path, now="2026-06-13T00:00:00+00:00")
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["research_gate"] == "hold"
    assert payload["promotion"]["next_allowed_step"] == (
        "improve_model_or_historical_evidence"
    )
