import json
import re
import subprocess
from pathlib import Path

from prospects import challenger_eval
from prospects.dynasty_backtest import OUTCOME_COMPLETE_THROUGH, OUTCOME_HORIZON_YEARS
from prospects.realized_value_readiness import IDENTITY_POLICY


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_REGISTRATION = {
    "protocol": "prospect-normalized-production-v1",
    "registered_at": "2026-07-20",
    "registration_status": "registered_unspent",
    "registration_amendment": {
        "reviewed_at": "2026-07-20",
        "kind": "pre_look_registration_review",
        "outcome_look_executed_before_amendment": False,
    },
    "base_commit": "16df0aeeb4ac11a41c9ff279240b60a055aee3bf",
    "prospect_input_git_blob": "4ce139871ae456b5289c68dad1e15d8191ff7ef5",
    "aaa_statcast_git_blob": "37533ad816d86bcf392ccce75bb15f0b745f0f74",
    "incumbent_model_git_blob": "7a9b9d12ae0866ae3b460f3f02395a0e30949844",
    "live_rank_git_blob": "4ed3f2603b93e5ecf319f501519303f6ff7c18fa",
    "competition_benchmark_git_blob": "85a1c2ff43ee7c050da75f43ae1f3382058d1ed3",
    "historical_cutoff": "cohort_season_completion",
    "reference_fold_years": [2016, 2017, 2018, 2019, 2021, 2022],
    "scored_fold_years": [2018, 2019, 2021],
    "fold_eligibility": {
        "outcome_complete_through": 2025,
        "outcome_horizon_years": 4,
        "earliest_historical_cohort": 2014,
        "maturity_rule": "cohort_year <= outcome_complete_through - outcome_horizon_years",
        "training_history_rule": "cohort_year - outcome_horizon_years >= earliest_historical_cohort",
        "omitted_cohorts": [2020],
        "selection": "all_and_only_pinned_historical_cohorts_satisfying_maturity_training_and_omission_rules",
    },
    "realized_value_readiness": {
        "artifact": "data/validation/valucast_prospect_realized_value_readiness.json",
        "required_status": "blocked",
        "required_ready": False,
        "required_blockers": [
            "missing_pitcher_category:qs",
            "impact_target_not_direct_7x7",
            "exact_prospective_replay_not_reconstructable",
        ],
    },
    "identity_policy": {
        "identity_key": "integer_mlbam_id",
        "cohort_key": "cohort_year:mlbam_id",
        "one_row_per_cohort_identity": True,
        "historical_role": "frozen_from_cohort_cutoff_row",
        "later_role_changes": "disclosed_never_relabels_prior_cohort",
        "same_cohort_role_conflict": "block_affected_cohort",
        "common_pool": "unique_mlbam_identities",
        "role_results": "frozen_cohort_role",
    },
    "variants": ["control", "normalized_production"],
    "rate_fields": {
        "hitter": ["iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip"],
        "pitcher": ["k_per_9", "bb_per_9", "k_bb_pct", "era", "whip"],
    },
    "same_level_min_other_peers": 25,
    "role_season_min_other_peers": 250,
    "minimum_exercised_coverage": 0.9,
    "normalization_exercised_coverage_scope": "each_role_each_reference_fold",
    "normalization_coverage_failure": "stop_before_outcome_scoring_leave_look_unspent",
    "research_primary": "ordinal_percentile_rank_mae",
    "future_public_primary": "realized_value_regret",
    "secondary_endpoints": [
        "partial_category_best_season_impact",
        "pairwise_concordance",
        "top_25_regret",
        "calibration",
        "coverage",
        "fold_stability",
    ],
    "within_single_look_reports": [
        "under_19_full_season_minors",
        "hitter_position_if_audit_passes",
        "aaa_statcast_component_disagreement",
    ],
    "hitter_position_audit": {
        "minimum_non_null_coverage_each_fold": 0.9,
        "allowed_raw_labels": ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "DH"],
        "reject_delimiters": ["/", ",", ";"],
    },
    "hitters_and_pitchers_separate": True,
    "minimum_completed_cohorts": 3,
    "minimum_unique_players": 250,
    "minimum_relative_improvement_pct": 5.0,
    "maximum_single_cohort_regression_pct": 5.0,
    "maximum_role_regression_pct": 5.0,
    "bootstrap": "paired_hierarchical_cohort_then_player",
    "bootstrap_resamples": 10000,
    "bootstrap_interval": "two_sided_95_percentile",
    "adjudication": {
        "implementation_path": "prospects/competition_benchmark.py",
        "function": "build_track",
        "independent_track_per_role": True,
        "roles": ["hitter", "pitcher"],
        "cohort_construction": "one_cohort_per_scored_fold_and_role",
        "build_track_criteria": {
            "minimum_cohorts": 3,
            "minimum_unique_players": 250,
            "minimum_outcome_coverage": 0.9,
            "minimum_relative_improvement_pct": 5.0,
            "maximum_single_cohort_regression_pct": 5.0,
            "maximum_segment_regression_pct": 5.0,
            "top_k": 25,
            "bootstrap_seed": 33021,
            "bootstrap_resamples": 10000,
        },
    },
    "adjudication_math": {
        "fold_role_metric": "equal_player_percentile_rank_mae",
        "role_track_primary": "unweighted_mean_of_completed_fold_role_maes",
        "error_delta": "control_mae_minus_candidate_mae",
        "relative_improvement_formula": "(control_mae-candidate_mae)/control_mae*100",
        "regression_formula": "(candidate_mae-control_mae)/control_mae*100",
        "hierarchical_bootstrap_sampling": "completed_cohorts_then_players",
        "bootstrap_interval": "two_sided_95_percentile",
        "research_success_requires": [
            "evidence_ready",
            "error_delta_ci_low_gt_0",
            "relative_improvement_pct_gte_5",
            "every_cohort_regression_pct_lte_5",
            "every_role_segment_regression_pct_lte_5",
            "candidate_top_25_regret_lte_control",
        ],
        "research_underperformance": "error_delta_ci_high_lt_0",
        "otherwise": "no_significant_difference",
        "claim_authorized": False,
    },
    "final_artifact_status_contract": {
        "top_level_status_mapping": {
            "research_only": "research_only",
            "validated_underperformance": "validated_underperformance",
            "no_significant_difference": "no_significant_difference",
            "collecting": "collecting",
        },
        "statistical_status_mapping": {
            "validated_superiority": "research_success",
            "validated_underperformance": "validated_underperformance",
            "no_significant_difference": "no_significant_difference",
            "collecting": "collecting",
        },
        "raw_only_status_values": ["validated_superiority"],
        "allowed_final_status_values": [
            "research_only",
            "research_success",
            "validated_underperformance",
            "no_significant_difference",
            "collecting",
        ],
        "forbidden_final_status_values": ["validated_superiority"],
        "claim_authorized": False,
        "public_claim_eligible": False,
    },
    "seed": 33021,
    "forbidden_seeds": [28013, 28017, 29001, 31013, 31017],
    "v0_7_baseline": "excluded_unstable_prediction_contract",
    "combined_promotion_variant": "unavailable_until_prospective_archive_matures",
    "public_claim_eligible": False,
    "production_importer": False,
}


def _registration() -> dict:
    text = (ROOT / "plans/033-prospect-normalized-production-gate.md").read_text(encoding="utf-8")
    match = re.search(
        r"<!-- normalized-production-registration:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- normalized-production-registration:end -->",
        text,
        flags=re.S,
    )
    assert match
    return json.loads(match.group(1))


def _git_blob(path: str) -> str:
    return subprocess.run(
        ["git", "hash-object", path],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_blob_at(revision: str, path: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{revision}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_registration_matches_full_immutable_contract_and_code():
    registration = _registration()
    assert registration == EXPECTED_REGISTRATION

    assert registration["seed"] == challenger_eval.REGISTERED_SEED == 33021
    assert registration["forbidden_seeds"] == [28013, 28017, 29001, 31013, 31017]
    assert len(registration["forbidden_seeds"]) == len(set(registration["forbidden_seeds"]))
    assert set(registration["forbidden_seeds"]) == challenger_eval.FORBIDDEN_SEEDS
    assert registration["same_level_min_other_peers"] == challenger_eval.SAME_LEVEL_MIN_PEERS == 25
    assert registration["role_season_min_other_peers"] == challenger_eval.ROLE_SEASON_MIN_PEERS == 250
    assert registration["minimum_exercised_coverage"] == challenger_eval.MIN_EXERCISED_COVERAGE == 0.90
    assert registration["variants"] == ["control", "normalized_production"]
    assert registration["rate_fields"]["hitter"] == list(challenger_eval.HITTER_RATE_FIELDS)
    assert registration["rate_fields"]["pitcher"] == list(challenger_eval.PITCHER_RATE_FIELDS)
    assert registration["reference_fold_years"] == list(challenger_eval.REGISTERED_FOLD_YEARS)
    assert registration["identity_policy"] == IDENTITY_POLICY

    # Pins are anchored to the registration's base commit, not the working
    # tree: the data inputs legitimately change on every nightly refresh, and
    # the registration is an immutable historical record of what was frozen at
    # registration time.
    for key, path in {
        "prospect_input_git_blob": "data/prospects/prospect_model_inputs.json",
        "aaa_statcast_git_blob": "data/models/valucast_aaa_statcast_features.json",
        "incumbent_model_git_blob": "data/models/valucast_prospect_model.json",
        "live_rank_git_blob": "data/models/valucast_prospect_rank_v1.json",
        "competition_benchmark_git_blob": "prospects/competition_benchmark.py",
    }.items():
        assert registration[key] == _git_blob_at(registration["base_commit"], path)
    assert registration["competition_benchmark_git_blob"] == _git_blob_at(
        registration["base_commit"], registration["adjudication"]["implementation_path"]
    )

    contract = json.loads((ROOT / "data/prospects/prospect_model_inputs.json").read_text(encoding="utf-8"))
    cohorts = sorted(int(year) for year in contract["historical"]["cohorts"])
    omitted = sorted(int(row["year"]) for row in contract["historical"]["omitted_cohorts"])
    rules = registration["fold_eligibility"]
    assert rules["outcome_complete_through"] == OUTCOME_COMPLETE_THROUGH == 2025
    assert rules["outcome_horizon_years"] == OUTCOME_HORIZON_YEARS == 4
    assert rules["earliest_historical_cohort"] == min(cohorts) == 2014
    assert rules["omitted_cohorts"] == omitted == [2020]
    derived_scored_folds = [
        year
        for year in cohorts
        if year <= OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS
        and year - OUTCOME_HORIZON_YEARS >= min(cohorts)
        and year not in omitted
    ]
    assert registration["scored_fold_years"] == derived_scored_folds == [2018, 2019, 2021]

    readiness = registration["realized_value_readiness"]
    assert readiness == {
        "artifact": "data/validation/valucast_prospect_realized_value_readiness.json",
        "required_status": "blocked",
        "required_ready": False,
        "required_blockers": [
            "missing_pitcher_category:qs",
            "impact_target_not_direct_7x7",
            "exact_prospective_replay_not_reconstructable",
        ],
    }
    readiness_artifact = json.loads((ROOT / readiness["artifact"]).read_text(encoding="utf-8"))
    assert readiness_artifact["status"] == readiness["required_status"]
    assert readiness_artifact["replay"]["realized_value_regret_ready"] is readiness["required_ready"]
    assert readiness_artifact["blockers"] == readiness["required_blockers"]
    assert registration["adjudication"]["build_track_criteria"] == {
        "minimum_cohorts": 3,
        "minimum_unique_players": 250,
        "minimum_outcome_coverage": 0.90,
        "minimum_relative_improvement_pct": 5.0,
        "maximum_single_cohort_regression_pct": 5.0,
        "maximum_segment_regression_pct": 5.0,
        "top_k": 25,
        "bootstrap_seed": 33021,
        "bootstrap_resamples": 10000,
    }
    status_contract = registration["final_artifact_status_contract"]
    assert status_contract["top_level_status_mapping"] == {
        "research_only": "research_only",
        "validated_underperformance": "validated_underperformance",
        "no_significant_difference": "no_significant_difference",
        "collecting": "collecting",
    }
    assert set(status_contract["top_level_status_mapping"]) == {
        "research_only",
        "validated_underperformance",
        "no_significant_difference",
        "collecting",
    }
    assert status_contract["statistical_status_mapping"] == {
        "validated_superiority": "research_success",
        "validated_underperformance": "validated_underperformance",
        "no_significant_difference": "no_significant_difference",
        "collecting": "collecting",
    }
    final_status_values = {
        *status_contract["top_level_status_mapping"].values(),
        *status_contract["statistical_status_mapping"].values(),
    }
    assert final_status_values == set(status_contract["allowed_final_status_values"])
    assert set(status_contract["forbidden_final_status_values"]).isdisjoint(final_status_values)
    assert status_contract["raw_only_status_values"] == ["validated_superiority"]
    assert set(status_contract["raw_only_status_values"]) <= set(
        status_contract["statistical_status_mapping"]
    )
    assert status_contract["claim_authorized"] is False
    assert status_contract["public_claim_eligible"] is False
    assert registration["registration_status"] == "registered_unspent"
    assert registration["registration_amendment"]["outcome_look_executed_before_amendment"] is False
    assert registration["public_claim_eligible"] is False
    assert registration["production_importer"] is False
