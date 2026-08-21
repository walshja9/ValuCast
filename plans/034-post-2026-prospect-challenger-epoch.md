# Plan 034 — Post-2026 Prospect Challenger Epoch

**Status:** PROTOCOL REGISTERED — WAITING FOR 2026 VINTAGE; NO LOOK AUTHORIZED

## Purpose

This plan registers the next prospect-model research epoch without reopening the
spent Plan 033 look or changing the live model. It converts the remaining
analytics findings into a controlled challenger program whose selection occurs
inside training folds and whose final evidence is evaluated once on untouched
outer cohorts.

The protocol is registered now. Execution remains blocked until the 2026 MLB
season is complete, the 2022 prospect cohort has a complete four-year outcome
window, all readiness gates pass, and one pre-look implementation amendment
freezes exact code/data hashes and the finite candidate grids. That amendment
may narrow or remove a hypothesis family; it may not add one, change an endpoint,
relax a threshold, reuse a seed, or inspect outer-fold results.

No part of this plan authorizes a public superiority claim, a production
importer, or an automatic model promotion.

<!-- post-2026-challenger-registration:start -->
```json
{
  "protocol": "prospect-model-challenger-epoch-v1",
  "registered_at": "2026-07-21",
  "registration_status": "protocol_registered_waiting_for_2026_vintage",
  "look_spent": false,
  "execution_authorized": false,
  "pre_look_implementation_amendment_required": true,
  "permitted_amendment_fields": [
    "base_commit",
    "source_git_blobs",
    "source_file_sha256",
    "exact_candidate_grids",
    "implementation_paths",
    "outcome_complete_through",
    "derived_outer_folds",
    "readiness_artifact_sha256"
  ],
  "forbidden_amendment_actions": [
    "add_hypothesis_family",
    "change_primary_endpoint",
    "relax_gate",
    "change_seed",
    "inspect_outer_fold_result",
    "reuse_plan_033_result",
    "relabel_2020_as_analyst_exclusion"
  ],
  "execution_trigger": {
    "not_before": "2027-01-01",
    "requires_2026_mlb_season_complete": true,
    "requires_2022_cohort_four_year_horizon_complete": true,
    "requires_reviewed_implementation_amendment": true
  },
  "historical_cutoff": "cohort_season_completion",
  "cohort_contract": {
    "earliest_historical_cohort": 2014,
    "outcome_horizon_years": 4,
    "omitted_cohorts": {
      "2020": "no_affiliated_minor_league_season"
    },
    "expected_outer_folds_after_2026": [2018, 2019, 2021, 2022],
    "outer_fold_derivation": "all_and_only_pinned_cohorts_with_complete_four_year_outcomes_and_at_least_four_years_of_prior_training_history",
    "training_rule": "cohort_year_strictly_less_than_test_cohort",
    "role_results": "separate_hitter_and_pitcher",
    "combined_result": "descriptive_only_never_overrides_role_result"
  },
  "identity_policy": {
    "identity_key": "mlbam_id:role",
    "cohort_key": "cohort_year:mlbam_id:role",
    "one_row_per_cohort_role_identity": true,
    "historical_role": "frozen_from_cohort_cutoff_row",
    "later_role_changes": "disclosed_never_relabels_prior_cohort",
    "same_cohort_role_conflict": "block_affected_identity",
    "two_way_players": "preserve_each_role_without_last_row_wins"
  },
  "reference_policy": {
    "impact_percentile_references": "training_identities_only_within_each_outer_fold",
    "reference_seasons": "strictly_post_cohort_through_cohort_plus_four",
    "reference_minimums": {
      "hitter_pa": 150,
      "pitcher_ip": 20
    },
    "test_identity_in_reference_pool": "fatal",
    "future_identity_in_reference_pool": "fatal",
    "source_and_reference_hashes_required": true
  },
  "model_track": {
    "purpose": "select_one_locked_role_specific_composite_challenger",
    "control": "frozen_incumbent_role_model_at_amendment_commit",
    "hypothesis_families": [
      "training_fold_only_ridge_regularization",
      "stronger_distance_weighted_neighbor_comparator",
      "inner_oof_residualized_or_nonnegative_stacked_rank_components",
      "corroborating_investment_blend_instead_of_max_draft_bonus",
      "training_fold_quantile_or_link_target_scaling",
      "train_serve_shrinkage_alignment",
      "multiplicative_confidence_haircut"
    ],
    "selection": {
      "method": "nested_walk_forward",
      "outer_test_cohorts_never_used_for_selection": true,
      "inner_primary": "fold_local_partial_category_impact_mae",
      "tie_breaker": "fewest_changed_components_then_lowest_parameter_count_then_lexical_variant_id",
      "one_candidate_per_role_reaches_outer_test": true,
      "component_ablation_reports": "inside_same_outer_look_descriptive_only"
    },
    "research_primary": "fold_local_partial_category_impact_absolute_error",
    "paired_delta": "candidate_absolute_error_minus_baseline_absolute_error_lower_is_better",
    "promotion_primary": "direct_format_specific_realized_value_regret",
    "promotion_readiness_required": true,
    "promotion_readiness_blockers": [
      "missing_pitcher_category_qs",
      "impact_target_not_direct_7x7",
      "exact_prospective_replay_not_reconstructable"
    ],
    "baselines": [
      "frozen_incumbent",
      "level_age_prior",
      "rich_historical_neighbors_25",
      "canonical_historical_neighbors_25"
    ],
    "minimum_completed_outer_cohorts": 4,
    "minimum_unique_players_per_role": 250,
    "minimum_outcome_coverage_each_fold_role": 0.9,
    "minimum_relative_improvement_vs_incumbent_pct": 2.0,
    "maximum_single_fold_regression_pct": 5.0,
    "top_25_regret_must_not_worsen": true,
    "research_success_requires": [
      "fold_local_reference_audit_passes",
      "candidate_minus_incumbent_paired_interval_high_lt_zero",
      "relative_improvement_vs_incumbent_gte_2_pct",
      "candidate_mae_lt_rich_neighbor_mae",
      "every_outer_fold_regression_lte_5_pct",
      "candidate_top_25_regret_lte_incumbent"
    ],
    "promotion_requires": [
      "research_success",
      "direct_realized_value_readiness_passes",
      "direct_realized_value_regret_gate_passes",
      "separate_human_review",
      "new_explicit_production_authorization"
    ]
  },
  "decision_tracks": {
    "buy_momentum": {
      "status": "registered_family_not_executable",
      "hypothesis": "audit_asymmetric_buy_momentum_prior",
      "primary": "forward_registered_buy_decision_regret",
      "must_use_preexisting_forward_cohorts": true,
      "cannot_change_rank_or_value_in_this_protocol": true,
      "seed": 34027
    },
    "cross_universe_mapping": {
      "status": "registered_family_not_executable",
      "hypothesis": "genuine_empirical_mlb_to_prospect_value_mapping",
      "control": "compatibility_only_no_unit_mapping",
      "primary": "forward_format_specific_trade_decision_regret",
      "minimum_completed_cohorts": 4,
      "cannot_change_display_or_value_in_this_protocol": true,
      "seed": 34031
    }
  },
  "multiplicity": {
    "outer_model_looks_per_role": 1,
    "outer_candidate_count_per_role": 1,
    "roles_are_independent_scoped_verdicts": true,
    "decision_tracks_are_independent_registrations_before_execution": true,
    "no_best_of_outer_fold_selection": true,
    "no_free_follow_up_look": true
  },
  "bootstrap": {
    "method": "paired_hierarchical_cohort_then_player",
    "interval": "two_sided_95_percentile",
    "resamples": 10000,
    "model_seed": 34021
  },
  "forbidden_seeds": [
    28013,
    28017,
    29001,
    31013,
    31017,
    33021,
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
<!-- post-2026-challenger-registration:end -->

## Why This Is One Model Look

The seven model hypothesis families do not receive seven outer-fold verdicts.
They are a finite search space selected entirely inside each outer training
fold. The deterministic nested procedure emits one locked composite challenger
per role. Only that challenger reaches the untouched outer cohort.

A component may look promising in inner folds and still be excluded by the
deterministic tie-breaker. Component and ablation tables are descriptive
diagnostics inside the same look; they cannot select a second challenger after
the outer result is known.

## Readiness and STOP Conditions

Stop before any outer scoring if any of these is true:

1. the 2026 season is incomplete or the 2022 outcome horizon is not frozen;
2. exact `mlbam_id:role` identity preservation fails;
3. a test/future identity enters an impact reference pool;
4. any fold-role outcome coverage is below 90%;
5. fewer than four complete outer cohorts or 250 players in either role remain;
6. the exact candidate grids, implementation paths, blobs, and source hashes
   have not been committed in the allowed pre-look amendment;
7. raw-unit guards would receive normalized or linked inputs;
8. the runner can be invoked twice or can overwrite a spent result; or
9. a serving, rank, value, publication, or public-claim importer exists.

A readiness stop leaves the look unspent. Once any outer-fold outcome is scored,
the role look is spent even if validation or writing later fails.

## Interpretation Rules

A model-track research success is role-specific. A pitcher success cannot mask a
hitter failure, and a combined result cannot create a broader verdict. Beating
the level-age prior is insufficient. The locked challenger must improve on the
incumbent and finish below the rich 25-neighbor comparator while meeting the
fold and top-25 guards.

Even research success cannot promote a model while direct realized-value
readiness remains blocked. It earns only a separate promotion review.

The buy-momentum and cross-universe families have different decisions, outcomes,
and maturities. They are reserved here to keep the roadmap coherent, but each
requires its own exact pre-look registration before execution. Their results
cannot rescue or condemn the prospect-model track.

## Current Operating Recommendation

Until the registered challenger epoch becomes executable:

1. Make no live model change from the fold-local impact audit.
2. Treat the public ahead-of-consensus Ledger as a consensus-movement
   accountability record, not proof of fantasy-ranking or valuation accuracy.
3. Preserve dated ranks, values, projections, roles, availability, and model
   versions so direct outcome and decision-regret tests are reconstructable.
4. Keep the pitcher model as the incumbent and prioritize role, workload, and
   availability evidence.
5. Require the hitter challenger to beat the rich-neighbor baseline and the
   frozen incumbent before it can earn more influence.
6. Evaluate final Prospect Rank v1 and ValuCast Value against direct,
   format-specific outcomes before any market-superiority claim.

## Implementation Order After the Trigger

1. Build the no-outcome readiness and identity validator.
2. Implement each hypothesis family behind a training-fold-only interface.
3. Freeze finite grids, code/data hashes, and derived folds in the permitted
   amendment.
4. Obtain independent review of the amendment and runner.
5. Reserve the output atomically before outer scoring.
6. Run once.
7. Validate and seal the artifact.
8. Review the role-specific result before any promotion proposal.

Until then, Plan 034 is a protocol and seed reservation only. It changes no
model, rank, value, public surface, or workflow.

## Append-only model-selection transition (2026-08-21)

Plan 038 supersedes only Plan 034's model-selection track. Held seed `34021`
was never executed and is retired forever as
`retired_unspent_never_execute`. This transition records no scientific result
and authorizes no execution.

The reviewed Git-history receipt is bound in the sealed Plan 038 registration:
scope tip `e1229bacc1c64d651609a5e621de0ec528a79a78`, 25,964 reachable objects
with sorted-object digest
`338ecf8463398b9702b9963475a99cb18d160f6a730d64d8a66fcc621484a35c`, and
25 raw standalone-token occurrences with inventory digest
`6fffbff002d1d2582317a12820d5e65beec9c5416e2754139a948f121127e0f2`.
The one-to-one reviewed classification list has digest
`bbf86755a4e072587c2dc804120b394d183627f11c2b333ec9a000d2b8937b23`;
its `result_artifact_entries` and `runner_invocation_entries` are both empty.

The separately registered decision tracks remain active and byte-for-byte
unchanged: buy momentum (seed `34027`, canonical subobject SHA-256
`ecca3d3964da2daac195d2825d6f5850ff1956f8800e4cbd4f37a540aa6053b7`)
and cross-universe mapping (seed `34031`, canonical subobject SHA-256
`0076afb20765bfc44d5f1f58f726b68cafa872397ba3f0efedbe1a8bef783412`).
