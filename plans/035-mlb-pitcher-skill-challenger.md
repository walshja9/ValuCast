# Plan 035 — MLB Pitcher Skill Challenger

**Status:** REGISTERED — UNSPENT; RESEARCH ONLY

## Purpose

This registration permits one retrospective, research-only look at whether a
single combined public Statcast feature set improves next-season pitcher skill
forecasts beyond the frozen ValuCast Control. It does not authorize Statcast
acquisition, result inspection, a second retrospective variant, or any change
to the model freeze, failed-decay flag, pitcher publication veto, pitcher cap,
Role Watch, ranks, values, projections, workflows, or served artifacts.

<!-- mlb-pitcher-skill-registration:start -->
```json
{
  "study_id": "mlb_pitcher_skill_challenger_v1",
  "registered_at": "2026-08-02",
  "status": "registered_unspent",
  "research_only": true,
  "retrospective_target_seasons": [2020, 2021, 2022, 2023, 2024, 2025],
  "statcast_feature_seasons": [2015, 2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024],
  "minimum_input_pitches": 500,
  "ridge_lambda": 10.0,
  "bootstrap_seed": 35021,
  "forbidden_bootstrap_seeds": [28013, 28014, 28015, 28017, 29001, 29016, 31013, 31017, 32019, 33021, 34021, 34027, 34031, 72127],
  "outer_looks": 1,
  "model_and_evaluation": {
    "target_residuals": {
      "k_bf": "actual_next_season_k_bf_minus_control_k_bf",
      "bb_bf": "actual_next_season_bb_bf_minus_control_bb_bf"
    },
    "feature_set": "one_combined_shape_location_execution_arsenal_set",
    "descriptive_ablations": ["shape", "location_execution", "arsenal"],
    "ablation_policy": "in_look_descriptive_only",
    "fold_rule": "target_T_trains_only_outcome_seasons_before_T",
    "control": {
      "params": "PitcherMarcelParams()",
      "builder": "build_pitcher_projections",
      "version": "registration_commit"
    },
    "context_comparators": [
      "same_season_persistence",
      "archived_steamer"
    ],
    "context_comparator_common_support": "exact_same_player_outcome_and_forecast_window_only",
    "context_comparator_policy": "context_only_never_trains_challenger_or_rescues_gate",
    "scored_folds": [2020, 2021, 2022, 2023, 2024, 2025],
    "scorecard": "canonical_methodology_scorecard",
    "input_eligibility": {
      "feature_season": "T-1",
      "minimum_tracked_pitches": 500,
      "requires_control_projection_for_T": true
    },
    "meaningful_pitch_type": {
      "minimum_pitches": 50,
      "minimum_usage": 0.05
    },
    "location_geometry": {
      "horizontal_zone_half_width_ft": 0.83,
      "vertical_bounds": "per_pitch_sz_bot_to_sz_top",
      "valid_location_requires": ["plate_x", "plate_z", "sz_top", "sz_bot"],
      "rate_denominator": "pitches_with_all_valid_location_fields",
      "zone": "inside_closed_strike_zone_rectangle",
      "heart": "central_50_percent_of_rectangle_width_and_height",
      "edge": "euclidean_distance_to_clamped_rectangle_boundary_lte_3_inches_inside_or_outside",
      "waste": "outside_euclidean_distance_to_closest_rectangle_point_gte_12_inches"
    },
    "ridge": {
      "lambda": 10.0,
      "grid_search": false
    },
    "correction_clip": {
      "lower_training_residual_percentile": 5,
      "upper_training_residual_percentile": 95,
      "fit_independently_inside_each_fold_and_target": true
    },
    "primary_gate": {
      "endpoints": ["k_per_9", "bb_per_9", "era", "whip"],
      "minimum_pooled_out_of_sample_mae_reduction_pct": 2.0,
      "maximum_endpoint_or_projected_role_cohort_regression_pct": 1.0,
      "minimum_improved_folds": 4,
      "total_scored_folds": 6,
      "minimum_scored_pitcher_seasons": 250
    },
    "paired_hierarchical_bootstrap": {
      "resamples": 10000,
      "sampling_order": "completed_target_season_then_pitcher",
      "seed": 35021,
      "interval": "two_sided_95_percentile",
      "use": "descriptive_only_for_retrospective_gate"
    },
    "post_look_policy": "no_second_retrospective_variant_after_outer_result_known",
    "prospective_confirmation": {
      "season": 2026,
      "evaluate_only_after_season_complete": true
    }
  },
  "feeds_live_projection": false,
  "feeds_rank_or_value": false,
  "feeds_pitcher_publication": false,
  "claim_eligible": false
}
```
<!-- mlb-pitcher-skill-registration:end -->

## Acquisition status (clarified 2026-08-03, review)

The integration branch added the acquisition *code* (immutable chunked
fetch, sealing, and manifest machinery) but **no historical Statcast data
was acquired or committed** — the commit titled "acquire immutable MLB
pitcher Statcast history" ships machinery only. Running the fetch is a
separately authorized owner step; until sealed season artifacts and the
registration seals exist, readiness fails loudly and the look cannot be
spent.

## Frozen boundaries

- Control is `PitcherMarcelParams()` plus `build_pitcher_projections` at the
  registration commit; the incumbent opportunity, role, and rate identities
  remain authoritative outside the research evaluator.
- Same-season persistence and exact-window archived Steamer are context only.
  Neither can train the challenger or rescue a failed gate.
- Shape, Location/Execution, and Arsenal ablations are descriptive outputs
  inside the single registered look, never additional candidate-selection looks.
- The location geometry and rate denominator were frozen before synthetic
  aggregation tests or acquisition, with no result seen.
- A retrospective pass authorizes only prospective confirmation on the completed
  2026 season. Promotion or a public superiority claim requires separate review
  and explicit authorization.
