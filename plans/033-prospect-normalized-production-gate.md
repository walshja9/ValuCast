# Plan 033 — Normalized-Production Prospect Research Gate

**Status:** REGISTERED + UNSPENT (2026-07-20)

## Scope

This immutable registration permits one research-only look comparing the Control and normalized-production variants, with hitters and pitchers kept separate. The registered historical cutoff is cohort-season completion. The current primary endpoint is ordinal percentile-rank MAE and may decide only whether the challenger merits further study; it cannot prove format-specific superiority or authorize a public claim.

The future public primary endpoint is realized-value regret. It remains blocked by the Task-2 readiness audit because pitcher QS is missing, and this registration does not create a production importer.

<!-- normalized-production-registration:start -->
```json
{
  "protocol": "prospect-normalized-production-v1",
  "registered_at": "2026-07-20",
  "base_commit": "16df0aeeb4ac11a41c9ff279240b60a055aee3bf",
  "prospect_input_git_blob": "4ce139871ae456b5289c68dad1e15d8191ff7ef5",
  "aaa_statcast_git_blob": "37533ad816d86bcf392ccce75bb15f0b745f0f74",
  "incumbent_model_git_blob": "7a9b9d12ae0866ae3b460f3f02395a0e30949844",
  "live_rank_git_blob": "4ed3f2603b93e5ecf319f501519303f6ff7c18fa",
  "historical_cutoff": "cohort_season_completion",
  "realized_value_readiness": {
    "artifact": "data/validation/valucast_prospect_realized_value_readiness.json",
    "required_status": "blocked",
    "required_ready": false,
    "blocking_category": "qs"
  },
  "identity_policy": {
    "identity_key": "integer_mlbam_id",
    "cohort_key": "cohort_year:mlbam_id",
    "one_row_per_cohort_identity": true,
    "historical_role": "frozen_from_cohort_cutoff_row",
    "later_role_changes": "disclosed_never_relabels_prior_cohort",
    "same_cohort_role_conflict": "block_affected_cohort",
    "common_pool": "unique_mlbam_identities",
    "role_results": "frozen_cohort_role"
  },
  "variants": ["control", "normalized_production"],
  "rate_fields": {
    "hitter": ["iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip"],
    "pitcher": ["k_per_9", "bb_per_9", "k_bb_pct", "era", "whip"]
  },
  "same_level_min_other_peers": 25,
  "role_season_min_other_peers": 250,
  "minimum_exercised_coverage": 0.9,
  "research_primary": "ordinal_percentile_rank_mae",
  "future_public_primary": "realized_value_regret",
  "secondary_endpoints": ["partial_category_best_season_impact", "pairwise_concordance", "top_25_regret", "calibration", "coverage", "fold_stability"],
  "within_single_look_reports": ["under_19_full_season_minors", "hitter_position_if_audit_passes", "aaa_statcast_component_disagreement"],
  "hitter_position_audit": {
    "minimum_non_null_coverage_each_fold": 0.9,
    "allowed_raw_labels": ["C", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "OF", "DH"],
    "reject_delimiters": ["/", ",", ";"]
  },
  "hitters_and_pitchers_separate": true,
  "minimum_completed_cohorts": 3,
  "minimum_unique_players": 250,
  "minimum_relative_improvement_pct": 5.0,
  "maximum_single_cohort_regression_pct": 5.0,
  "maximum_role_regression_pct": 5.0,
  "bootstrap": "paired_hierarchical_cohort_then_player",
  "bootstrap_resamples": 10000,
  "bootstrap_interval": "two_sided_95_percentile",
  "seed": 33021,
  "forbidden_seeds": [28013, 28017, 29001, 31013, 31017],
  "v0_7_baseline": "excluded_unstable_prediction_contract",
  "combined_promotion_variant": "unavailable_until_prospective_archive_matures",
  "public_claim_eligible": false,
  "production_importer": false
}
```
<!-- normalized-production-registration:end -->

## Adjudication rules

- Input-coverage failure stops before outcome scoring and leaves the look unspent.
- Once the script scores any outcome, the look is spent even if the model errors later.
- Identity mismatch raises and records no comparative result.
- Under-19, position, and AAA outputs are reports inside this look, never extra candidate-selection looks.
- Position output is omitted unless non-null, stable historical position semantics pass the pre-run audit.
- The 2020 fold is absent by contract, not as an analyst choice.
- Every status remains `research_only` or a failure state, and `claim_authorized` remains false.
