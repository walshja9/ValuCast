"""Tests for the fixed-horizon prospect dynasty-layer gate."""
import json

import numpy as np

from prospects.dynasty_backtest import (
    ARTIFACT_PATH,
    OUTCOME_OOF_PATH,
    PRIOR_K,
    _cluster_bootstrap_delta_ci,
    _combined_mae_headline_from_oof,
    _eb_optimal_prior_k,
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
    assert "2015-2022" not in payload["validation_contract"]["horizon_reason"]
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

    result = run_backtest(
        input_path, artifact_path, now="2026-06-13T00:00:00+00:00", outcome_oof=None
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert result["research_gate"] == "hold"
    assert payload["promotion"]["next_allowed_step"] == (
        "improve_model_or_historical_evidence"
    )
    # reporting-only headline degrades gracefully with no committed OOF
    assert payload["combined_headline"]["source_available"] is False
    assert payload["prior_k_diagnostic"]["current"] == PRIOR_K


# --- R1/R2/R5 reporting-only statistics (senior-mathematician audit) ---


def _committed_dynasty():
    return json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))


def test_cluster_bootstrap_ci_is_deterministic_and_labels_significance():
    # candidate strictly better than baseline on every item -> CI excludes 0.
    baseline = np.full(50, 0.20)
    candidate = np.full(50, 0.10)
    clusters = np.arange(50)
    first = _cluster_bootstrap_delta_ci(candidate, baseline, clusters)
    second = _cluster_bootstrap_delta_ci(candidate, baseline, clusters)
    assert first == second  # fixed seed -> deterministic
    assert first["ci_low"] > 0
    assert first["significance"] == "significant"

    # no separation -> delta 0, CI includes 0 -> directional
    flat = _cluster_bootstrap_delta_ci(baseline, baseline, clusters)
    assert flat["point"] == 0.0
    assert flat["significance"] == "directional (CI includes 0)"


def test_committed_per_role_brier_ci_point_matches_served_gate():
    payload = _committed_dynasty()
    for role in ("hitter", "pitcher"):
        ci = payload["roles"][role]["brier_delta_ci"]
        gate = payload["roles"][role]["gate"]
        # CI point tracks the served gate improvement (rounding aside) and the
        # served number is surfaced verbatim.
        assert ci["gate_point_improvement_pct"] == gate["improvement_pct"]
        assert ci["delta_baseline_qualifier"] == "vs un-tuned K=40 prior"
        assert ci["seed"] == 28014
        assert ci["ci_low"] is not None and ci["ci_high"] is not None


def test_committed_headline_reproduces_the_board_gate_mae_delta():
    payload = _committed_dynasty()
    headline = payload["combined_headline"]
    assert headline["source_available"] is True
    assert headline["metric"] == "outcome_score_mae"
    assert headline["baseline"] == "historical_neighbors_25"
    assert headline["point"] == 6.3566
    assert headline["significance"] == "significant"
    assert headline["ci_low"] > 0
    # FIX 1: the committed headline certifies the served board_gate — same
    # baseline, same delta as data/models/valucast_prospect_model.json.
    assert headline["certifies_served_gate"] is True
    assert headline["served_gate_baseline"] == "historical_neighbors_25"
    assert headline["served_gate_improvement_pct"] == 6.3566


def _served_gate(baseline="historical_neighbors_25", improvement_pct=6.3566):
    return {"baseline": baseline, "improvement_pct": improvement_pct}


def test_headline_helper_certifies_when_served_gate_matches():
    oof = json.loads(OUTCOME_OOF_PATH.read_text(encoding="utf-8"))
    headline = _combined_mae_headline_from_oof(oof, _served_gate())
    assert headline["point"] == 6.3566
    assert headline["source_available"] is True
    assert headline["certifies_served_gate"] is True
    # neighbors baseline chosen -> prior-K qualifier does not apply to headline
    assert headline["prior_k_qualifier_applies"] is False


def test_headline_helper_degrades_when_served_gate_baseline_diverges():
    # Served gate selected canonical_historical_neighbors_25 (a baseline the OOF
    # does not store), so the 2-baseline min cannot certify it: degrade.
    oof = json.loads(OUTCOME_OOF_PATH.read_text(encoding="utf-8"))
    headline = _combined_mae_headline_from_oof(
        oof, _served_gate(baseline="canonical_historical_neighbors_25")
    )
    assert headline["certifies_served_gate"] is False
    assert headline["source_available"] is False
    assert headline["served_gate_baseline"] == "canonical_historical_neighbors_25"
    assert headline["headline_baseline"] == "historical_neighbors_25"
    assert "certification_note" in headline


def test_headline_helper_degrades_when_served_improvement_diverges():
    # Same baseline, but the served improvement_pct no longer matches the OOF
    # re-derivation -> cannot certify a divergent published number.
    oof = json.loads(OUTCOME_OOF_PATH.read_text(encoding="utf-8"))
    headline = _combined_mae_headline_from_oof(
        oof, _served_gate(improvement_pct=1.0)
    )
    assert headline["certifies_served_gate"] is False
    assert headline["source_available"] is False


def test_headline_helper_degrades_without_a_served_gate():
    # No served gate to certify against -> the headline must not publish.
    oof = json.loads(OUTCOME_OOF_PATH.read_text(encoding="utf-8"))
    headline = _combined_mae_headline_from_oof(oof, None)
    assert headline["certifies_served_gate"] is False
    assert headline["source_available"] is False


def test_prior_k_diagnostic_flags_over_shrinkage_without_changing_k():
    payload = _committed_dynasty()
    diagnostic = payload["prior_k_diagnostic"]
    assert diagnostic["current"] == PRIOR_K == 40.0
    assert 1.0 < diagnostic["eb_optimal_estimate"] < 40.0
    assert "un-tuned" in diagnostic["note"]


def test_eb_optimal_prior_k_handles_degenerate_input():
    diagnostic = _eb_optimal_prior_k([])
    assert diagnostic["current"] == PRIOR_K
    assert diagnostic["eb_optimal_estimate"] is None
