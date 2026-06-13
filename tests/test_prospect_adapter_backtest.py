"""Tests for the fixed-horizon prospect adapter promotion gate."""
import json

from prospects.adapter_backtest import _weighted_fold_metric, build_backtest, run_backtest
from prospects.adapters import PRESETS
from prospects.universal import TARGET_SPECS


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
        for cohort in (2015, 2018, 2021):
            for index in range(1, 9):
                mlbam_id = offset + cohort * 100 + index
                rows.append(_row(role, cohort, mlbam_id))
                if index % 3 == 0:
                    seasons[f"{mlbam_id}_{role}"] = []
                elif role == "hitter":
                    seasons[f"{mlbam_id}_{role}"] = [
                        {
                            "year": cohort + 1,
                            "pa": 450,
                            "r": 60 + index,
                            "hr": 12 + index,
                            "rbi": 55 + index,
                            "sb": index,
                            "avg": 0.245 + index / 1000,
                            "ops": 0.710 + index / 100,
                            "so": 90 - index,
                        }
                    ]
                else:
                    seasons[f"{mlbam_id}_{role}"] = [
                        {
                            "year": cohort + 1,
                            "ip": 130,
                            "so": 110 + index,
                            "qs": 10 + index,
                            "sv": 0,
                            "hld": index,
                            "era": 4.20 - index / 10,
                            "whip": 1.35 - index / 100,
                            "k_bb": 2.5 + index / 10,
                            "l": 8 - index / 2,
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


def test_backtest_never_trains_on_an_unclosed_outcome_horizon():
    payload = build_backtest(_contract(), now="2026-06-13T00:00:00+00:00")

    assert payload["status"] == "shadow_only"
    assert payload["validation_contract"]["outcome_horizon_years"] == 3
    assert payload["promotion"]["live_dd_value_influence"] == "blocked"
    assert payload["promotion"]["feeds_live_dd_value"] is False
    for role, result in payload["roles"].items():
        assert result["gate"]["status"] == "insufficient_sample"
        assert result["folds"]
        assert set(result["category_diagnostics"]) == set(PRESETS["dd_7x7"][role])
        assert set(result["target_ablation_diagnostics"]) == set(TARGET_SPECS[role])
        assert all(
            fold["train_cohort_max"] <= fold["test_cohort"] - 3
            for fold in result["folds"]
        )


def test_backtest_aggregates_only_comparable_within_cohort_metrics():
    folds = [
        {"sample_size": 100, "rank_concordance": 0.60},
        {"sample_size": 300, "rank_concordance": 0.80},
    ]
    assert _weighted_fold_metric(folds, "rank_concordance") == 0.75


def test_run_backtest_writes_promotion_artifact(tmp_path):
    input_path = tmp_path / "inputs.json"
    artifact_path = tmp_path / "backtest.json"
    input_path.write_text(json.dumps(_contract()), encoding="utf-8")

    result = run_backtest(
        input_path=input_path,
        artifact_path=artifact_path,
        now="2026-06-13T00:00:00+00:00",
    )

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result["adapter_research_gate"] == "hold"
    assert payload["promotion"]["next_allowed_step"] == (
        "improve_model_or_historical_evidence"
    )
