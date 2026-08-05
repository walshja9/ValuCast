import json
from pathlib import Path

import pytest

from prospects.stage1_outcome_proof import (
    auc,
    build_disagreement_funnel,
    build_evidence_bands,
    build_role_metrics,
    build_stage1_outcome_proof,
    render_markdown,
    validate_stage1_outcome_proof,
)


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


def test_evidence_bands_cover_rows_once_and_match_reliability_counts():
    rows = [
        _row(index, 2018 + index % 2, [0.0, 0.5, 1.0][index % 3], index / 20, 0.2, 0.3)
        for index in range(20)
    ]
    reliability = {
        "bins": [
            {
                "decile": decile + 1,
                "count": 2,
                "predicted_score_min": (2 * decile) / 20,
                "predicted_score_max": (2 * decile + 1) / 20,
                "reached_role_or_better_freq": sum(
                    [0.0, 0.5, 1.0][index % 3] > 0.0
                    for index in (2 * decile, 2 * decile + 1)
                ) / 2,
            }
            for decile in range(10)
        ]
    }
    bands = build_evidence_bands(rows, reliability)
    assert len(bands) == 10
    assert sum(band["sample_size"] for band in bands) == 20
    assert all(sum(band["outcome_counts"].values()) == band["sample_size"] for band in bands)


def test_disagreement_funnel_is_role_split_and_whole_funnel():
    scorecard = {
        "calls": [
            {"identity_key": "1_hitter", "initial_gap": 30, "status": "open_toward", "bucket": "toward"},
            {"identity_key": "2_hitter", "initial_gap": 120, "status": "retired_we_backed_off", "bucket": None},
            {"identity_key": "3_pitcher", "initial_gap": 220, "status": "closed_caught_up", "bucket": "toward"},
            {"identity_key": "4_pitcher", "initial_gap": 60, "status": "left_universe", "bucket": None},
        ]
    }
    funnel = build_disagreement_funnel(scorecard)
    assert funnel["roles"]["hitter"]["total"] == 2
    assert funnel["roles"]["pitcher"]["total"] == 2
    assert funnel["roles"]["hitter"]["bins"]["100_199"]["retracted"] == 1
    assert funnel["roles"]["pitcher"]["bins"]["200_plus"]["resolved"] == 1
    assert funnel["overall"]["total"] == 4


@pytest.mark.parametrize(
    "call",
    [
        {"identity_key": "1_hitter", "initial_gap": 24, "status": "open_toward", "bucket": "toward"},
        {"identity_key": "1_hitter", "initial_gap": 30, "status": "unknown", "bucket": None},
    ],
)
def test_disagreement_funnel_fails_closed_on_non_registered_rows(call):
    with pytest.raises(ValueError):
        build_disagreement_funnel({"calls": [call]})


def test_disagreement_funnel_uses_frozen_gap_not_current_ranks():
    call = {
        "identity_key": "1_hitter",
        "initial_gap": 120,
        "status": "open_toward",
        "bucket": "toward",
        "valucast_now": 1,
        "consensus_now": 1,
    }
    baseline = build_disagreement_funnel({"calls": [call]})
    call.update(valucast_now=9999, consensus_now=-9999)
    assert build_disagreement_funnel({"calls": [call]}) == baseline


def test_payload_is_research_only_and_renders_from_one_source():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "oof": root / "data/models/valucast_outcome_oof_scores.json",
        "reliability": root / "data/models/valucast_probability_reliability.json",
        "backtest": root / "data/models/valucast_prospect_dynasty_backtest.json",
        "scorecard": root / "data/models/valucast_ahead_of_consensus_scorecard.json",
    }
    inputs = {
        key: json.loads(path.read_text(encoding="utf-8"))
        for key, path in paths.items()
    }
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": "a" * 64}
            for key, path in paths.items()
        },
        generated_at=max(str(item.get("generated_at") or "") for item in inputs.values()),
        seed=34041,
        resamples=10,
    )
    assert validate_stage1_outcome_proof(payload) == []
    assert payload["policy"]["public_superiority_authorized"] is False
    assert payload["policy"]["feeds_model_score"] is False
    report = render_markdown(payload)
    assert "Contributor discrimination" in report
    assert "Level/age prior" in report
    assert "Historical neighbors (25)" in report
    assert "Closed-cohort detail" in report
    assert "100-199" in report
    assert "Public superiority authorized: **No**" in report


def test_validator_rejects_any_public_authorization():
    payload = {
        "artifact": "valucast_stage1_outcome_proof",
        "schema_version": "1.0.0",
        "status": "research_only",
        "sources": {
            key: {"path": f"data/{key}.json", "sha256": "a" * 64}
            for key in ("oof", "reliability", "backtest", "scorecard")
        },
        "historical": {"roles": {}},
        "disagreements": {},
        "policy": {"public_superiority_authorized": True},
    }
    assert "retrospective evidence cannot authorize public superiority" in validate_stage1_outcome_proof(payload)


def test_builder_rejects_scorecard_that_feeds_a_production_surface():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "oof": root / "data/models/valucast_outcome_oof_scores.json",
        "reliability": root / "data/models/valucast_probability_reliability.json",
        "backtest": root / "data/models/valucast_prospect_dynasty_backtest.json",
        "scorecard": root / "data/models/valucast_ahead_of_consensus_scorecard.json",
    }
    inputs = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in paths.items()}
    inputs["scorecard"]["source_policy"]["feeds_model_score"] = True

    with pytest.raises(ValueError, match="research-only"):
        build_stage1_outcome_proof(
            oof_payload=inputs["oof"],
            reliability_payload=inputs["reliability"],
            backtest_payload=inputs["backtest"],
            scorecard_payload=inputs["scorecard"],
            sources={
                key: {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": "a" * 64}
                for key, path in paths.items()
            },
            generated_at=max(str(item.get("generated_at") or "") for item in inputs.values()),
            seed=34041,
            resamples=2,
        )


def test_validator_requires_hitter_and_pitcher_disagreement_scopes():
    payload = {
        "artifact": "valucast_stage1_outcome_proof",
        "schema_version": "1.0.0",
        "status": "research_only",
        "sources": {
            key: {"path": f"data/{key}.json", "sha256": "a" * 64}
            for key in ("oof", "reliability", "backtest", "scorecard")
        },
        "historical": {"roles": {}},
        "disagreements": {"roles": {"hitter": {}, "pitcher": {}}},
        "policy": {
            "public_superiority_authorized": False,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_value": False,
            "feeds_buy_score": False,
            "feeds_role_watch": False,
            "feeds_pitcher_publication": False,
        },
    }
    payload["disagreements"]["roles"].pop("pitcher")
    assert "disagreement roles must be hitter and pitcher" in validate_stage1_outcome_proof(payload)


def test_validator_requires_ten_sequential_evidence_bands_per_role():
    summary = {
        "sample_size": 0,
        "cohort_count": 0,
        "cohorts": {},
        "evidence_bands": [],
    }
    payload = {
        "artifact": "valucast_stage1_outcome_proof",
        "schema_version": "1.0.0",
        "status": "research_only",
        "sources": {
            key: {"path": f"data/{key}.json", "sha256": "a" * 64}
            for key in ("oof", "reliability", "backtest", "scorecard")
        },
        "evaluation": {"historical_rows": 0},
        "historical": {"roles": {"hitter": summary, "pitcher": summary}},
        "disagreements": {},
        "policy": {
            "public_superiority_authorized": False,
            "feeds_model_score": False,
            "feeds_public_rank": False,
            "feeds_value": False,
            "feeds_buy_score": False,
            "feeds_role_watch": False,
            "feeds_pitcher_publication": False,
        },
    }
    assert "hitter evidence bands must be ten ordered deciles" in validate_stage1_outcome_proof(payload)


def test_validator_reconciles_overall_disagreement_funnel_to_role_scopes():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "oof": root / "data/models/valucast_outcome_oof_scores.json",
        "reliability": root / "data/models/valucast_probability_reliability.json",
        "backtest": root / "data/models/valucast_prospect_dynasty_backtest.json",
        "scorecard": root / "data/models/valucast_ahead_of_consensus_scorecard.json",
    }
    inputs = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in paths.items()}
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": "a" * 64}
            for key, path in paths.items()
        },
        generated_at=max(str(item.get("generated_at") or "") for item in inputs.values()),
        seed=34041,
        resamples=2,
    )
    payload["disagreements"]["roles"]["hitter"] = {
        "total": 0,
        "open": 0,
        "resolved": 0,
        "censored": 0,
        "retracted": 0,
        "moved_toward": 0,
        "moved_away": 0,
        "bins": {},
    }
    assert "overall disagreement funnel does not reconcile to role scopes" in validate_stage1_outcome_proof(payload)


def test_validator_rejects_mutated_evidence_band_contributor_rate():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "oof": root / "data/models/valucast_outcome_oof_scores.json",
        "reliability": root / "data/models/valucast_probability_reliability.json",
        "backtest": root / "data/models/valucast_prospect_dynasty_backtest.json",
        "scorecard": root / "data/models/valucast_ahead_of_consensus_scorecard.json",
    }
    inputs = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in paths.items()}
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": "a" * 64}
            for key, path in paths.items()
        },
        generated_at=max(str(item.get("generated_at") or "") for item in inputs.values()),
        seed=34041,
        resamples=2,
    )
    payload["historical"]["roles"]["hitter"]["evidence_bands"][0]["contributor_rate"] = 1.0
    assert "hitter evidence band contributor rate does not reconcile" in validate_stage1_outcome_proof(payload)


def test_validator_requires_exact_evidence_band_outcome_keys():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "oof": root / "data/models/valucast_outcome_oof_scores.json",
        "reliability": root / "data/models/valucast_probability_reliability.json",
        "backtest": root / "data/models/valucast_prospect_dynasty_backtest.json",
        "scorecard": root / "data/models/valucast_ahead_of_consensus_scorecard.json",
    }
    inputs = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in paths.items()}
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": "a" * 64}
            for key, path in paths.items()
        },
        generated_at=max(str(item.get("generated_at") or "") for item in inputs.values()),
        seed=34041,
        resamples=2,
    )
    payload["historical"]["roles"]["hitter"]["evidence_bands"][0]["outcome_counts"].pop("star")
    assert "hitter evidence band outcome counts are invalid" in validate_stage1_outcome_proof(payload)


def test_validator_rejects_movement_counts_above_the_scope_total():
    root = Path(__file__).resolve().parents[1]
    paths = {
        "oof": root / "data/models/valucast_outcome_oof_scores.json",
        "reliability": root / "data/models/valucast_probability_reliability.json",
        "backtest": root / "data/models/valucast_prospect_dynasty_backtest.json",
        "scorecard": root / "data/models/valucast_ahead_of_consensus_scorecard.json",
    }
    inputs = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in paths.items()}
    payload = build_stage1_outcome_proof(
        oof_payload=inputs["oof"],
        reliability_payload=inputs["reliability"],
        backtest_payload=inputs["backtest"],
        scorecard_payload=inputs["scorecard"],
        sources={
            key: {"path": str(path.relative_to(root)).replace("\\", "/"), "sha256": "a" * 64}
            for key, path in paths.items()
        },
        generated_at=max(str(item.get("generated_at") or "") for item in inputs.values()),
        seed=34041,
        resamples=2,
    )
    for scope in [payload["disagreements"]["overall"], *payload["disagreements"]["roles"].values()]:
        scope["moved_toward"] = scope["total"]
        scope["moved_away"] = 1
    assert "disagreement movement counts are invalid" in validate_stage1_outcome_proof(payload)


def test_disagreement_funnel_rejects_unknown_movement_bucket():
    with pytest.raises(ValueError, match="unclassified disagreement bucket"):
        build_disagreement_funnel({
            "calls": [{
                "identity_key": "1_hitter",
                "initial_gap": 25,
                "status": "open_toward",
                "bucket": "sideways",
            }]
        })


def test_evidence_bands_reject_insufficient_rows_before_partitioning():
    with pytest.raises(ValueError, match="ten nonempty deciles"):
        build_evidence_bands([_row(1, 2018, 0.0, 0.1, 0.2, 0.3)], {"bins": []})
