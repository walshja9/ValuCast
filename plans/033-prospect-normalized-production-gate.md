# Plan 033 — Normalized-Production Prospect Research Gate

**Status:** SPENT — INVALID FOR ADJUDICATION / DESCRIPTIVE ONLY (executed 2026-07-20; no public claim authorized)

## Scope

This immutable registration permits one research-only look comparing the Control and normalized-production variants, with hitters and pitchers kept separate. The registered historical cutoff is cohort-season completion. The current primary endpoint is ordinal percentile-rank MAE and may decide only whether the challenger merits further study; it cannot prove format-specific superiority or authorize a public claim.

This is a pre-look registration-review amendment to the initial registration commit. No outcome scorer, seed, or comparative result was executed before this amendment, so the look remains unspent. The amendment distinguishes six input-normalization reference/coverage folds from the three mature outcome-scoring folds and freezes the exact adjudication implementation, criteria, weighting, and decision math before any result look.

The future public primary endpoint is realized-value regret. It remains blocked by every blocker in the Task-2 readiness audit: missing pitcher QS, an impact target that is not direct 7x7, and exact prospective replay that cannot be reconstructed. This registration does not create a production importer.

<!-- normalized-production-registration:start -->
```json
{
  "protocol": "prospect-normalized-production-v1",
  "registered_at": "2026-07-20",
  "registration_status": "registered_unspent",
  "registration_amendment": {
    "reviewed_at": "2026-07-20",
    "kind": "pre_look_registration_review",
    "outcome_look_executed_before_amendment": false
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
    "selection": "all_and_only_pinned_historical_cohorts_satisfying_maturity_training_and_omission_rules"
  },
  "realized_value_readiness": {
    "artifact": "data/validation/valucast_prospect_realized_value_readiness.json",
    "required_status": "blocked",
    "required_ready": false,
    "required_blockers": [
      "missing_pitcher_category:qs",
      "impact_target_not_direct_7x7",
      "exact_prospective_replay_not_reconstructable"
    ]
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
  "normalization_exercised_coverage_scope": "each_role_each_reference_fold",
  "normalization_coverage_failure": "stop_before_outcome_scoring_leave_look_unspent",
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
  "adjudication": {
    "implementation_path": "prospects/competition_benchmark.py",
    "function": "build_track",
    "independent_track_per_role": true,
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
      "bootstrap_resamples": 10000
    }
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
      "candidate_top_25_regret_lte_control"
    ],
    "research_underperformance": "error_delta_ci_high_lt_0",
    "otherwise": "no_significant_difference",
    "claim_authorized": false
  },
  "final_artifact_status_contract": {
    "top_level_status_mapping": {
      "research_only": "research_only",
      "validated_underperformance": "validated_underperformance",
      "no_significant_difference": "no_significant_difference",
      "collecting": "collecting"
    },
    "statistical_status_mapping": {
      "validated_superiority": "research_success",
      "validated_underperformance": "validated_underperformance",
      "no_significant_difference": "no_significant_difference",
      "collecting": "collecting"
    },
    "raw_only_status_values": ["validated_superiority"],
    "allowed_final_status_values": ["research_only", "research_success", "validated_underperformance", "no_significant_difference", "collecting"],
    "forbidden_final_status_values": ["validated_superiority"],
    "claim_authorized": false,
    "public_claim_eligible": false
  },
  "seed": 33021,
  "forbidden_seeds": [28013, 28017, 29001, 31013, 31017],
  "v0_7_baseline": "excluded_unstable_prediction_contract",
  "combined_promotion_variant": "unavailable_until_prospective_archive_matures",
  "public_claim_eligible": false,
  "production_importer": false
}
```
<!-- normalized-production-registration:end -->

## Fold and coverage contract

The six reference folds are `2016`, `2017`, `2018`, `2019`, `2021`, and `2022`. They exist to construct and audit the cutoff-available normalization references. Normalized production must reach at least 90% exercised coverage separately for hitters and pitchers in every one of these six reference folds before any outcome scoring begins; failure leaves the look unspent.

The outcome-scored folds are all and only `2018`, `2019`, and `2021`. Starting from the pinned historical cohorts, a scored fold must satisfy both deterministic rules: `cohort_year <= 2025 - 4` for a complete four-year outcome horizon, and `cohort_year - 4 >= 2014` for prior training history. The 2020 cohort is absent by the input contract. The 2022 fold is reference-only because its four-year horizon ends in 2026, beyond the 2025 outcome-completeness pin.

## Adjudication contract

Adjudication is pinned to Git blob `85a1c2ff43ee7c050da75f43ae1f3382058d1ed3` of `prospects/competition_benchmark.py`, function `build_track`. Hitters and pitchers form independent tracks, with one cohort per scored fold and role. Each role track requires three completed cohorts, 250 unique players, at least 90% outcome coverage in every fold/role, at least 5% relative improvement, no cohort or role segment more than 5% worse, candidate top-25 regret no worse than Control, seed `33021`, and 10,000 bootstrap resamples.

Within each fold and role, percentile-rank MAE weights every resolved player equally. Each role-track primary is the unweighted mean of its completed fold-role MAEs. Relative improvement is `(Control - candidate) / Control * 100`; regression is `(candidate - Control) / Control * 100`. The paired hierarchical bootstrap samples completed cohorts and then players and reports a two-sided 95% percentile interval for Control-minus-candidate error.

Research success requires evidence readiness, an interval lower bound above zero, at least 5% relative improvement, every cohort and role-segment regression at or below 5%, and candidate top-25 regret no worse than Control. An interval upper bound below zero is research underperformance; every other evidence-ready result is no significant difference. `claim_authorized` remains false regardless of statistical status.

The final private artifact exhaustively identity-maps all possible raw `build_track.status` values: `research_only`, `validated_underperformance`, `no_significant_difference`, and `collecting`. For a successful claim-ineligible gate, it separately rewrites raw `statistical_status = validated_superiority` to `research_success`; raw `validated_underperformance`, `no_significant_difference`, and `collecting` statistical statuses remain unchanged. `validated_superiority` is permitted only as the pinned evaluator's raw statistical-status mapping input and is forbidden as any final artifact status value. `research_success` means only that the registered ordinal research gate passed; it never means format-specific superiority, never authorizes a public claim, and never changes `claim_authorized` or `public_claim_eligible` from false.

## Adjudication rules

- Input-coverage failure stops before outcome scoring and leaves the look unspent.
- Once the script scores any outcome, the look is spent even if the model errors later.
- Identity mismatch raises and records no comparative result.
- Under-19, position, and AAA outputs are reports inside this look, never extra candidate-selection looks.
- Position output is omitted unless non-null, stable historical position semantics pass the pre-run audit.
- The 2020 fold is absent by contract, not as an analyst choice.
- Every top-level status remains `research_only` or a failure state; final statistical status follows the frozen private-artifact mapping, and `claim_authorized` remains false.

## Result — 2026-07-20

The registered command was invoked exactly once. Its original Python process completed without a rerun and wrote the sealed private artifact `data/validation/valucast_prospect_normalized_production_gate.json` with content SHA-256 `49116e4e7bb5773fa981fa0096a6a15fad72fd5c1c02aa2236a6dce9ad2be19a`. The run completed, the look is spent, Control/candidate score identities were exactly equal, and both `claim_authorized` and `public_claim_eligible` remain `false`.

All six reference folds exercised normalized production for 100% of hitter and pitcher rows before scoring. The outcome tracks scored all and only 2018, 2019, and 2021, each with 100% outcome coverage.

### Post-run implementation audit — adjudication invalid

The sealed statistical outputs below are descriptive only and are **not evidence for or against normalized production**. Independent post-run review found that `normalize_rows` replaced factual rate fields with `[0,1]` quantiles, then the unchanged production scorer applied raw-unit heuristics and guards to those quantiles. For example, the pitcher bad-line guard compares `k_bb_pct <= 5.0`, which classifies every `[0,1]` normalized K-BB% as bad when its sample gate is met and can activate pedigree correction. Rank v1 likewise compares normalized K-BB%, OPS, and ISO against thresholds registered in their original raw units. The sealed MAEs therefore measure normalized inputs plus a changed heuristic/correction regime, not the isolated normalized-production representation.

The look remains spent and receives no free rerun. Any future test requires a separate registration and implementation that keeps factual raw-unit guard/heuristic fields distinct from normalized model features, or explicitly preregisters percentile-aware guards before a fresh look.

### Sealed raw ordinal outputs — descriptive only

- **Raw hitter evaluator output — `no_significant_difference`:** normalized production MAE `0.213090` versus Control `0.214023`; Control-minus-candidate delta `+0.000933`; relative improvement `+0.435821%`; paired hierarchical 95% interval `[-0.001614, +0.003513]`; 1,091 unique players across three complete folds. Normalized production had lower error in all three folds and lower top-25 regret (`0.233333` versus `0.280000`), but the interval crossed zero and improvement was below the registered 5% floor.
- **Raw pitcher evaluator output — `no_significant_difference`:** normalized production MAE `0.237796` versus Control `0.237255`; Control-minus-candidate delta `-0.000541`; relative improvement `-0.228228%`; paired hierarchical 95% interval `[-0.003306, +0.002068]`; 1,127 unique players across three complete folds. Normalized production had lower error only in 2019, lost 2018 and 2021, and had higher top-25 regret (`0.420000` versus `0.386667`).

### Registered in-look reports

- Under-19 full-season affiliated sample: 17 hitters and 9 pitchers, report-only with no independent verdict. Hitter error improved only in the nine-player 2018 fold and tied in 2019/2021; pitcher error tied in every fold.
- Raw hitter-position semantics passed: non-null coverage was 100% in every scored fold, with no invalid labels or within-player conflicts. Raw labels were reported without coercing `DH`, `OF`, or multi-position strings and without an independent verdict.
- Partial-category best-season impact remained secondary and not direct 7x7. Hitters favored normalized production by `+0.000813` Control-minus-candidate error; pitchers favored Control by `-0.001120`. Realized-value regret was not calculated because the registered readiness artifact remains blocked.
- Current model-component context retained exact Control/candidate identity equality for 2,765 research ranks. Historical normalization covered 6,756/6,756 rows. Current normalization covered 6,445/6,618 rows (`97.385917%`), excluding 173 unavailable rows (72 unique MLBAM identities) from both variants.
- AAA measured-component report: 462 current ranked AAA identities, 341 with the pinned measured artifact, and 121 missing Statcast identities excluded without zero-filling. Measured rows split into 170 hitters, 123 pitcher starters, and 48 pitcher relievers; no pitcher lacked the factual starter/reliever field. The report contains separate raw components and reliability counts only—no composite index, opportunity, health, availability, transaction-direction, or future-innings inference.

This spent result is invalid for adjudication and descriptive only. It does not change the live model, Rank v1, any served artifact, or any production workflow, and it authorizes no public superiority claim.

The one-shot runner received a post-run durability hardening after this audit: after all pre-score pin, readiness, coverage, and identity checks, it now atomically reserves the single output path and durably marks the look spent before invoking the scorer. A later validation, write, crash, or concurrent invocation can no longer reopen the look. This patch is post-run, did not execute the scorer, did not alter the sealed artifact, and changed no scoring math.
