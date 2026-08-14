"""Machinery tests for the registered Stage 1 maturation re-run.

Registration: docs/registration-2026-08-14-stage1-maturation-rerun.md.
Synthetic fixtures only — CI must never compute real 2021 predictions
before the registered look.
"""
import json
from pathlib import Path

import prospects.model as prospect_model
from prospects.model import MATURE_THROUGH, outcome_oof_rows
from prospects.outcome_oof import (
    build_outcome_oof_artifact,
    validate_outcome_oof_artifact,
)
from prospects.probability_reliability import (
    DEFAULT_SOURCE_PATH,
    build_probability_reliability,
)
from prospects.stage1_outcome_proof import build_evidence_bands
from scripts import run_stage1_maturation_rerun as rerun

ROOT = Path(__file__).resolve().parents[1]
GENERATED_AT = "2026-08-14T00:00:00+00:00"


def test_live_mature_through_constant_is_untouched():
    # The live constant gates served training labels; editing it is a model
    # change under the freeze. The registered study passes 2021 as a
    # parameter instead.
    assert MATURE_THROUGH == 2019


def test_outcome_oof_rows_default_preserves_served_maturity(monkeypatch):
    captured = {}

    def capture(rows, role, mature_through=MATURE_THROUGH):
        captured[role] = mature_through
        return []

    monkeypatch.setattr(prospect_model, "_historical_rows", capture)
    assert outcome_oof_rows("hitter", []) == []
    assert captured["hitter"] == 2019
    assert outcome_oof_rows("pitcher", [], mature_through=2021) == []
    assert captured["pitcher"] == 2021


def test_runner_constants_match_registration_document():
    text = rerun.REGISTRATION_PATH.read_text(encoding="utf-8")
    assert rerun.STUDY_ID in text
    assert rerun.SEED == 36061 and "36061" in text
    assert rerun.RULE4_RESERVED_SEED == 37083 and "37083" in text
    assert rerun.SEED not in rerun.FORBIDDEN_SEEDS
    assert rerun.RULE4_RESERVED_SEED not in rerun.FORBIDDEN_SEEDS
    assert {34041, 35021} <= set(rerun.FORBIDDEN_SEEDS)
    for seed in rerun.FORBIDDEN_SEEDS:
        assert str(seed) in text
    assert rerun.MATURE_THROUGH_RESEARCH == 2021
    assert rerun.EXPECTED_ELIGIBLE_2021 == {"hitter": 386, "pitcher": 365}
    assert rerun.EXPECTED_POOLED == {"hitter": 1765, "pitcher": 1887}
    assert rerun.EXPECTED_COHORTS == [2016, 2017, 2018, 2019, 2021]
    for path in (
        rerun.OOF_OUT,
        rerun.RELIABILITY_OUT,
        rerun.BACKTEST_SNAPSHOT,
        rerun.SCORECARD_SNAPSHOT,
    ):
        assert str(path.relative_to(ROOT)).replace("\\", "/") in text


def _synthetic_rows(role, count=40, tie_block=6):
    # Heavy prediction ties spanning decile boundaries, with mlbam_ids of
    # mixed digit widths (9, 10, ...) so a str-vs-int tie sort would order
    # members differently.
    return [
        {
            "mlbam_id": 9 + index,
            "role": role,
            "test_cohort": 2018 + index % 2,
            "train_cohort_max": 2017 + index % 2,
            "model_prediction": (index // tie_block) / 10.0,
            "prior_prediction": 0.2,
            "neighbor_prediction": 0.3,
            "target": [0.0, 0.5, 1.0][index % 3],
        }
        for index in range(count)
    ]


def _synthetic_oof_payload():
    payload = build_outcome_oof_artifact(
        {role: _synthetic_rows(role) for role in ("hitter", "pitcher")},
        input_sha256="a" * 64,
        generated_at=GENERATED_AT,
    )
    assert validate_outcome_oof_artifact(payload) == []
    return payload


def test_reliability_source_path_is_parameterized_with_live_default():
    payload = _synthetic_oof_payload()
    default = build_probability_reliability(
        payload, oof_sha256="b" * 64, generated_at=GENERATED_AT
    )
    assert DEFAULT_SOURCE_PATH == "data/models/valucast_outcome_oof_scores.json"
    assert default["source"]["path"] == DEFAULT_SOURCE_PATH
    maturation_path = str(rerun.OOF_OUT.relative_to(ROOT)).replace("\\", "/")
    override = build_probability_reliability(
        payload,
        oof_sha256="b" * 64,
        generated_at=GENERATED_AT,
        source_path=maturation_path,
    )
    assert override["source"]["path"] == maturation_path
    assert override["roles"] == default["roles"]


def test_evidence_bands_reconcile_reliability_ties_across_id_widths():
    # Before the tie-sort normalization, bands ordered ties by str(mlbam_id)
    # while reliability deciles ordered by numeric id; a tie block straddling
    # a decile boundary with mixed-width ids then reconciles against
    # different members and spuriously halts.
    payload = _synthetic_oof_payload()
    reliability = build_probability_reliability(
        payload, oof_sha256="b" * 64, generated_at=GENERATED_AT
    )
    for role in ("hitter", "pitcher"):
        rows = [row for row in payload["rows"] if row["role"] == role]
        bands = build_evidence_bands(rows, reliability["roles"][role])
        assert [band["decile"] for band in bands] == list(range(1, 11))
        assert sum(band["sample_size"] for band in bands) == len(rows)


def _proof_stub(pitcher_cells, hitter_low=0.05):
    def cell(point, low, high, supported):
        return {
            "point": point,
            "low": low,
            "high": high,
            "evidence_status": (
                "supported_retrospective" if supported else "descriptive"
            ),
        }

    metrics = {}
    for metric in rerun.METRICS:
        point, low, high, supported = pitcher_cells[metric]
        metrics[metric] = {
            "model_minus_baseline": {
                "historical_neighbors_25": cell(point, low, high, supported),
                "level_age_prior": cell(0.1, 0.05, 0.15, True),
            }
        }
    hitter_metrics = {
        metric: {
            "model_minus_baseline": {
                baseline: cell(0.1, hitter_low, 0.15, hitter_low > 0)
                for baseline in rerun.BASELINES
            }
        }
        for metric in rerun.METRICS
    }
    return {
        "historical": {
            "roles": {
                "pitcher": {"metrics": metrics},
                "hitter": {"metrics": hitter_metrics},
            }
        }
    }


def test_resolution_mapping_partitions_the_outcome_space():
    clears = (0.05, 0.01, 0.09, True)
    positive_straddle = (0.02, -0.01, 0.05, False)
    negative_straddle = (-0.01, -0.05, 0.03, False)
    entirely_below = (-0.06, -0.09, -0.02, False)

    def rule(spearman, kendall, roc):
        stub = _proof_stub(
            {"spearman_rho": spearman, "kendall_tau_b": kendall, "roc_auc": roc}
        )
        return rerun.apply_resolution_mapping(stub)["rule"]

    assert rule(clears, clears, clears) == "RULE_1_VALIDATED"
    assert rule(clears, clears, entirely_below) == "RULE_2_REJECTED_NOW"
    assert rule(clears, clears, negative_straddle) == "RULE_3_REJECTED_NOW"
    assert (
        rule(positive_straddle, positive_straddle, positive_straddle)
        == "RULE_4_BOUNDED_2022_INCREMENT"
    )
    # The reviewer's mixed case: some metrics clear, the rest straddle
    # positively — the residual rule, not undefined territory.
    assert rule(clears, positive_straddle, clears) == "RULE_4_BOUNDED_2022_INCREMENT"
    # An uncomputable metric voids for owner adjudication.
    assert (
        rule(clears, (None, None, None, False), clears)
        == "VOID_OWNER_ADJUDICATION"
    )


def test_hitter_monitoring_triggers_on_any_nonpositive_lower_bound():
    clears = (0.05, 0.01, 0.09, True)
    cells = {metric: clears for metric in rerun.METRICS}
    healthy = rerun.apply_resolution_mapping(_proof_stub(cells, hitter_low=0.01))
    assert healthy["hitter_monitoring"]["weakened_triggers_owner_review"] is False
    # A CI entirely below zero still "excludes zero" — the trigger is the
    # lower bound, so a catastrophic reversal cannot slip through.
    weakened = rerun.apply_resolution_mapping(_proof_stub(cells, hitter_low=-0.02))
    assert weakened["hitter_monitoring"]["weakened_triggers_owner_review"] is True
    boundary = rerun.apply_resolution_mapping(_proof_stub(cells, hitter_low=0.0))
    assert boundary["hitter_monitoring"]["weakened_triggers_owner_review"] is True
