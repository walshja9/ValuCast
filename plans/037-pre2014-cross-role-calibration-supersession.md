# Plan 037 — Pre-2014 Cross-Role Calibration Supersession

## Decision

Complete the spent Plan 036 adjudication from its exact committed acquisition
receipts after correcting two deterministic representation defects: MLB StatsAPI's
bare dash is a missing numeric sentinel, and a positive-strikeout/zero-walk target
is an ordered K/BB state above every finite reference. No row, identity, category,
candidate, threshold, governor limit, bootstrap setting, or fold is changed.

This is a corrective completion in the same look lineage, not a fresh independent
look. The runner must reserve the unique Plan 037 result before opening any Plan 036
outcome blob. It may read only the registered Git blobs and must not use the network.
The registration authorizes one research adjudication and never authorizes a public
claim or automatic promotion.

<!-- plan037-registration:start -->
```json
{
  "protocol": "plan_037_pre2014_cross_role_calibration_supersession",
  "registered_at": "2026-08-12T02:42:34Z",
  "status": "registered",
  "look_spent": false,
  "execution_authorized": true,
  "research_only": true,
  "automatic_promotion": false,
  "claim_authorized": false,
  "implementation_base_commit": "b4a5b2bfd4bb324e7b8d6e7d249fb91fea9f0708",
  "readiness": {
    "path": "data/validation/valucast_pre2014_cross_role_supersession_readiness.json",
    "sha256": "0bd86c7d15a460d415de00be5c9e05906d63459e7f8f2d3b079c0f3971032fa2"
  },
  "result_path": "data/validation/valucast_pre2014_cross_role_supersession_gate.json",
  "supersedes": {
    "network_refetch_forbidden": true,
    "outcome_blob_records": [
      {
        "binding": "git_blob_only_pre_reservation",
        "git_blob": "b65f34f0c302e98269c25216fc7c325d79769e0c",
        "path": "data/validation/valucast_pre2014_cross_role_gate.json"
      },
      {
        "binding": "git_blob_only_pre_reservation",
        "git_blob": "41153259894183f9cbf311e6855c22e9c8f05a61",
        "path": "data/validation/valucast_pre2014_cross_role_evidence.json"
      },
      {
        "binding": "git_blob_only_pre_reservation",
        "git_blob": "1ed2ff8476333c8ebd193659084e68eb5133f345",
        "path": "data/research/extended_prospect_history/sealed-acquisition-checkpoint.json"
      }
    ],
    "plan036_artifact_commit": "f06f14599659863bbacf459a1e2fa654529b6c01",
    "plan036_execution_commit": "568aea2e91bf473ba4491dec394e16afdffd5478",
    "plan036_readiness": {
      "git_blob": "d9061c337bf1f9fc78d8e997a94071554599afd0",
      "path": "data/validation/valucast_pre2014_cross_role_readiness.json",
      "sha256": "12a1023bd1000e54520c2ac445aebbe603c27c69f2bcc0badf3cbbf1fae7e610"
    },
    "plan036_registration": {
      "git_blob": "69a51320771c2a147191d005ff1665156700002c",
      "path": "plans/036-pre2014-cross-role-calibration-gate.md",
      "sha256": "70cfe7948a5bb82bcaaa16308c60eabafcf0d7f72e3d618978232d15155fd862"
    },
    "prior_error_type": "FoldScoringError",
    "prior_status": "spent_error",
    "same_look_lineage": true
  },
  "candidate": {
    "calibration": "fold_trained_role_head_isotonic",
    "candidate_count": 1,
    "forbidden_substitutions": [
      "raw_pick_value",
      "live_role_quantile",
      "governor_relaxation"
    ],
    "governor_thresholds_changed": false,
    "head_blend": {
      "impact": 0.42,
      "outcome": 0.58
    },
    "pitcher_investment_feature_mode": "drop_raw_pick_value",
    "rank_model_score_mode": "common_target"
  },
  "outer_folds": [
    2017,
    2018,
    2019,
    2021
  ],
  "bootstrap": {
    "cross_role_concordance": {
      "point_statistic": "incumbent_discordance_reduction",
      "unit": "cohort_then_identity_within_role"
    },
    "direct_mae": {
      "point_statistic": "relative_mae_improvement",
      "unit": "player_within_cohort_hierarchical"
    },
    "interval": "two_sided_95_percentile",
    "resamples": 10000,
    "seed": 35011
  },
  "primary_endpoint": "direct_7x7_target_percentile_rank_mae",
  "thresholds": {
    "cross_role_bootstrap_lower_strictly_gt": 0.0,
    "current_governor_required": true,
    "direct_mae_bootstrap_lower_strictly_gt": 0.0,
    "maximum_fold_relative_regression": 0.05,
    "maximum_role_concordance_relative_regression": 0.01,
    "minimum_cross_role_concordance_relative_improvement": 0.02,
    "minimum_direct_mae_relative_improvement": 0.02,
    "minimum_fold_role_coverage": 0.9,
    "minimum_outer_folds": 4,
    "minimum_unique_players_per_role": 250,
    "top25_direct_regret_no_worse": true,
    "top25_ordinal_regret_no_worse": true
  },
  "governor": {
    "check_id": "prospect_top_board_role_shape",
    "max_top25_pitcher_count": 7,
    "max_top50_pitcher_rate": 0.3
  },
  "result_contract": {
    "single_use": true,
    "claim_authorized": false,
    "automatic_promotion": false,
    "terminal_evidence_path": "data/validation/valucast_pre2014_cross_role_supersession_evidence.json",
    "network_refetch_forbidden": true
  },
  "limitations": [
    "cohort-season-completion pseudo-replay"
  ]
}
```
<!-- plan037-registration:end -->

## Interpretation

A pass authorizes production review only. Production remains prohibited until a
separate integration commit derives and validates the exact frozen training and
calibration bundle, rebuilds the public artifacts, and passes the unchanged full
quality governor. A failed or spent-error result authorizes no production change.

The terminal result and evidence are permanent. A hard interruption may resume
only the exact existing reservation; every deterministic failure consumes it.
