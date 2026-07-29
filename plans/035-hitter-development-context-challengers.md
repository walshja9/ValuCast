# Plan 035 — Hitter Development-Context Challengers

**Status:** PROTOCOL REGISTERED — WAITING FOR 2026 VINTAGE; NO LOOK AUTHORIZED

## Purpose

Register two data-informed Stage 1 hitter hypotheses without changing the live
model or spending another look on the historical folds used to identify them:

1. injury-adjusted development density; and
2. position-by-youth context.

The exploratory Sirota review selected these families after inspecting existing
2018, 2019, and 2021 walk-forward results. Those cohorts are therefore
selection-contaminated and cannot confirm either idea. The first confirmatory
outcome is the untouched 2022 cohort after its complete four-year horizon is
frozen following the 2026 MLB season.

No part of this plan authorizes a Sirota adjustment, a public superiority claim,
or automatic promotion.

<!-- hitter-development-context-registration:start -->
```json
{
  "protocol": "hitter-development-context-challengers-v1",
  "registered_at": "2026-07-29",
  "registration_status": "protocol_registered_waiting_for_2026_vintage",
  "look_spent": false,
  "execution_authorized": false,
  "selection_disclosure": {
    "data_informed_hypotheses": true,
    "exploratory_cohorts": [2018, 2019, 2021],
    "exploratory_results_confirmatory_eligible": false,
    "confirmatory_cohort": 2022
  },
  "execution_trigger": {
    "not_before": "2027-01-01",
    "requires_2026_mlb_season_complete": true,
    "requires_2022_cohort_four_year_horizon_complete": true,
    "requires_reviewed_pre_look_implementation_amendment": true
  },
  "scope": {
    "stage": "stage_1_real_baseball_outcomes",
    "role": "hitter",
    "live_model": "frozen_incumbent_at_amendment_commit",
    "identity_key": "cohort_year:mlbam_id:hitter",
    "primary_outcome": "fold_local_partial_category_impact_absolute_error",
    "direct_fantasy_promotion_authorized": false
  },
  "hypothesis_families": [
    {
      "id": "injury_adjusted_development_density",
      "claim": "Verified pre-cutoff missed-development context improves future hitter outcome forecasts beyond the incumbent age-level treatment.",
      "allowed_sources": [
        "committed_pre_cutoff_exposure_history",
        "historically_reconstructable_pre_cutoff_mlb_statsapi_transactions"
      ],
      "forbidden": [
        "post_cutoff_injury_knowledge",
        "current_player_manual_flags",
        "missing_injury_record_means_healthy",
        "single_player_override"
      ]
    },
    {
      "id": "position_by_youth",
      "claim": "Training-fold position context changes the meaning of age relative to level and improves future hitter outcome forecasts.",
      "allowed_sources": [
        "committed_pre_cutoff_primary_positions",
        "training_fold_only_level_age_references"
      ],
      "forbidden": [
        "future_position",
        "public_tool_grade",
        "manual_defensive_value",
        "single_player_override"
      ]
    }
  ],
  "pre_look_amendment": {
    "required_fields": [
      "base_commit",
      "source_git_blobs",
      "source_file_sha256",
      "exact_feature_definitions",
      "finite_candidate_grids",
      "missingness_policy",
      "minimum_source_coverage",
      "implementation_paths",
      "confirmatory_cohort_row_count",
      "control_hash",
      "readiness_artifact_sha256"
    ],
    "may_narrow_or_remove_family": true,
    "may_add_family": false,
    "may_inspect_2022_outcomes": false,
    "may_relax_gate": false
  },
  "multiplicity": {
    "confirmatory_family_count": 2,
    "familywise_alpha": 0.05,
    "method": "bonferroni",
    "per_family_two_sided_interval": 0.975,
    "one_confirmatory_look": true,
    "no_free_follow_up": true,
    "at_most_one_candidate_may_advance": true,
    "winner_rule": "largest_relative_improvement_then_fewest_features_then_lexical_id"
  },
  "gates": {
    "minimum_unique_2022_hitters": 250,
    "minimum_2022_outcome_coverage": 0.9,
    "minimum_relative_improvement_vs_incumbent_pct": 2.0,
    "paired_interval_high_must_be_below_zero": true,
    "candidate_mae_must_beat_rich_historical_neighbors_25": true,
    "top_25_regret_must_not_worsen": true,
    "identity_and_cutoff_audit_must_pass": true
  },
  "bootstrap": {
    "method": "paired_player",
    "interval": "two_sided_97_5_percentile_per_family",
    "resamples": 10000,
    "seed": 35021
  },
  "forbidden_seeds": [
    28013,
    28014,
    28017,
    29001,
    31013,
    31017,
    33021,
    34021,
    34027,
    34031,
    72127
  ],
  "result_contract": {
    "allowed_statuses": [
      "waiting_for_vintage",
      "blocked_readiness",
      "research_success",
      "validated_underperformance",
      "no_significant_difference",
      "invalid",
      "spent_error"
    ],
    "claim_authorized": false,
    "public_claim_eligible": false,
    "production_importer": false,
    "automatic_promotion": false
  },
  "explicit_non_actions": [
    "no_sirota_adjustment",
    "no_pitcher_challenger",
    "no_cross_role_normalization_change",
    "no_contact_quality_challenger",
    "no_athleticism_challenger",
    "no_investment_challenger",
    "no_rank_or_value_change"
  ],
  "frozen_live_boundaries": {
    "prospect_scores": "unchanged",
    "prospect_ranks": "unchanged",
    "dynasty_values": "unchanged",
    "pitcher_caps": "unchanged",
    "role_watch": "unchanged",
    "pitcher_publication": "unchanged",
    "failed_pedigree_decay_flag": "false_unchanged"
  }
}
```
<!-- hitter-development-context-registration:end -->

## Readiness and stop conditions

Stop before reading any 2022 outcome if:

1. the 2026 season or four-year outcome window is incomplete;
2. fewer than 250 unique 2022 hitters or 90% outcome coverage remain;
3. injury-source coverage cannot distinguish unknown from verified zero;
4. any post-cutoff transaction or position enters a feature;
5. the exact finite definitions and hashes are not frozen in the reviewed
   amendment;
6. the control cannot be reproduced exactly;
7. the runner can be invoked twice or overwrite a spent result; or
8. any production importer exists.

A readiness stop leaves the look unspent. Reading any confirmatory 2022 outcome
spends the look even if the job later fails.

## Relationship to Plan 034

Plan 034 was already registered before these two hypotheses were selected and
explicitly forbids adding a new family after registration. Plan 035 is therefore
an independent hitter-only confirmatory protocol. Its result cannot rescue or
condemn Plan 034, and Plan 034 cannot supply a free second look.

## Current operating rule

Until the trigger and amendment are complete, these hypotheses remain research
ideas only. Preserve dated inputs and transaction provenance; do not expose a
new player field, score component, rank change, or public claim.
