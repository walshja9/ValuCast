"""Tests for the Universal Prospect Index historical promotion gate."""
import json

import pytest

from prospects.index_backtest import (
    _temporal_stability_guard,
    _top_quartile_star_precision,
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


def _dynasty_backtest(gate="active"):
    return {
        "universal_model_version": "0.4.0",
        "generated_at": "2026-06-13T00:00:00+00:00",
        "promotion": {"dynasty_layer_research_gate": gate},
    }


def test_tie_aware_top_quartile_precision_does_not_arbitrarily_break_ties():
    predictions = [0.8, 0.8, 0.8, 0.8, 0.1, 0.1, 0.1, 0.1]
    actual = [100.0, 0.0, 100.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert _top_quartile_star_precision(predictions, actual) == pytest.approx(0.5)


def test_temporal_stability_guard_rejects_any_fold_regression():
    folds = [
        {
            "candidate_rank_concordance": 0.70,
            "baseline_rank_concordance": 0.69,
            "candidate_top_quartile_star_precision": 0.30,
            "baseline_top_quartile_star_precision": 0.29,
        },
        {
            "candidate_rank_concordance": 0.70,
            "baseline_rank_concordance": 0.69,
            "candidate_top_quartile_star_precision": 0.20,
            "baseline_top_quartile_star_precision": 0.21,
        },
    ]
    guard = _temporal_stability_guard(folds)
    assert guard["status"] == "hold"
    assert guard["rank_non_regression_every_fold"] is True
    assert guard["top_quartile_star_non_regression_every_fold"] is False


def test_backtest_requires_role_distribution_evidence_and_blocks_live_use():
    payload = build_backtest(
        _contract(),
        dynasty_backtest=_dynasty_backtest("hold"),
        now="2026-06-13T00:00:00+00:00",
    )
    assert payload["promotion"]["universal_index_research_gate"] == "hold"
    assert payload["promotion"]["role_distribution_prerequisite"] == "hold"
    assert payload["promotion"]["live_consumer"] == "blocked"
    assert payload["promotion"]["feeds_live_valucast_rank"] is False
    assert payload["promotion"]["feeds_live_dd_value"] is False
    assert payload["combined"]["folds"]
    assert all(
        fold["train_cohort_max"] <= fold["test_cohort"] - 4
        for fold in payload["combined"]["folds"]
    )


def test_run_backtest_writes_separate_artifact(tmp_path):
    input_path = tmp_path / "inputs.json"
    dynasty_path = tmp_path / "dynasty.json"
    artifact_path = tmp_path / "index-backtest.json"
    input_path.write_text(json.dumps(_contract()), encoding="utf-8")
    dynasty_path.write_text(json.dumps(_dynasty_backtest()), encoding="utf-8")
    result = run_backtest(
        input_path=input_path,
        dynasty_backtest_path=dynasty_path,
        artifact_path=artifact_path,
        now="2026-06-13T00:00:00+00:00",
    )
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result["research_gate"] in {"active", "hold"}
    assert payload["promotion"]["live_consumer"] == "blocked"
