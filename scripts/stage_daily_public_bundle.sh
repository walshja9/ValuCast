#!/usr/bin/env bash
set -e

git add \
  data/actuals/current.json \
  data/prospects/prospect_model_inputs.json \
  data/prospects/raw \
  data/mlb/mlb_track_record_cache.json \
  data/mlb/mlb_availability_transactions_cache.json \
  data/mlb/mlb_roster_status_cache.json \
  data/models/valucast_mlb_availability.json \
  data/models/valucast_hp_promotion_sanity_report.json \
  data/models/valucast_playing_time_role_tracker.json \
  data/models/valucast_mlb_roster_status.json \
  data/models/valucast_mlb_dynasty_layer.json \
  data/models/valucast_mlb_dynasty_layer_marcel_shadow.json \
  data/models/valucast_mlb_projection_source_comparison.json \
  data/models/valucast_mlb_track_record.json \
  data/models/valucast_quality_governor.json \
  data/models/valucast_prospect_movers.json \
  data/models/valucast_prospect_comps.json \
  data/models/valucast_pooled_shadow.json \
  data/models/valucast_call_up_receipts.json \
  data/models/valucast_gaps_claim_ledger.json \
  data/models/valucast_prospect_buys.json \
  data/models/valucast_prospect_buys_monitor.json \
  data/models/valucast_prospect_buys_review.json \
  data/models/valucast_prospect_availability.json \
  data/models/valucast_prospect_model.json \
  data/prediction_archive/valucast_prospect_model \
  data/models/valucast_prospect_coverage_audit.json \
  data/models/valucast_prospect_calibration_report.json \
  data/models/valucast_prospect_peak_projection_v1.json \
  data/models/valucast_prospect_rank_history.json \
  data/models/valucast_prospect_peak_projection_calibration.json \
  data/models/valucast_prospect_forward_validation.json \
  data/models/valucast_prospect_model_v0_7.json \
  data/models/valucast_prospect_outcome_backtest.json \
  data/models/valucast_prospect_cross_role_shadow.json \
  data/models/valucast_prospect_shadow_promotion.json \
  data/models/valucast_front_office_failures.json \
  data/models/valucast_raw_data_independence_audit.json \
  data/models/valucast_milb_stat_freshness_audit.json \
  data/models/valucast_prospect_card_data_audit.json \
  data/models/valucast_recent_signal_report.json \
  data/models/valucast_recent_form_signal.json \
  data/models/valucast_call_up_pulse.json \
  data/fangraphs/fg_fv_snapshot.json \
  data/sts/sts_consensus_snapshot.json \
  data/prospectslive/prospectslive_consensus_snapshot.json \
  data/hkb/hkb_source.csv \
  data/hkb/hkb_consensus_snapshot.json \
  data/models/valucast_ahead_of_consensus.json \
  data/models/valucast_ahead_of_consensus_scorecard.json \
  data/models/valucast_consensus_gap.json \
  data/models/valucast_pipeline_observability.json \
  data/models/valucast_front_office_report.json \
  data/models/valucast_scouting_reports.json \
  data/models/valucast_prospect_dynasty_backtest.json \
  data/models/valucast_prospect_dynasty_layer.json \
  data/models/valucast_prospect_forward_shadow.json \
  data/models/valucast_prospect_universe.json \
  data/models/valucast_prospect_rank_v1.json \
  data/models/valucast_universal_prospect_index.json \
  data/models/valucast_universal_prospect_index_backtest.json \
  data/models/valucast_universal_prospect_model.json \
  data/models/valucast_prospect_league_adapters.json \
  data/prediction_archive/valucast_prospect_league_adapters \
  data/prediction_archive/valucast_mlb_dynasty_layer \
  data/prediction_archive/valucast_mlb_dynasty_layer_marcel_shadow \
  data/prediction_archive/valucast_mlb_projection_source_freeze \
  data/prediction_archive/valucast_mlb_projection_source_comparison \
  data/prediction_archive/valucast_actuals_snapshot \
  data/prediction_archive/valucast_mlb_availability \
  data/prediction_archive/valucast_mlb_roster_status \
  data/prediction_archive/valucast_mlb_track_record \
  data/prediction_archive/valucast_playing_time_role_tracker \
  data/prediction_archive/valucast_prospect_movers \
  data/prediction_archive/valucast_call_up_receipts \
  data/prediction_archive/valucast_gaps_claim_ledger \
  data/prediction_archive/valucast_prospect_buys \
  data/prediction_archive/valucast_prospect_dynasty_layer \
  data/prediction_archive/valucast_prospect_peak_projection_v1 \
  data/prediction_archive/valucast_prospect_shadow_promotion \
  data/prediction_archive/valucast_prospect_forward_shadow \
  data/prediction_archive/valucast_prospect_rank_v1 \
  data/prediction_archive/valucast_projection_scorecard/ \
  data/prediction_archive/valucast_universal_prospect_index \
  data/prediction_archive/valucast_universal_prospect_model \
  data/projections/current.json \
  data/projections/metadata.json \
  data/projections/ros.json \
  data/public/public_dynasty_snapshot.json \
  data/statcast/percentiles.json \
  data/validation/methodology_scorecard.json \
  projections/runs/valucast_hp_2026_v2/projections.json \
  projections/runs/valucast_hp_2026_v2/run_manifest.json \
  projections/runs/valucast_hp_2026_v2/metadata.json \
  projections/data/identity.json
if [ -f data/models/valucast_scouting_llm_cache.json ]; then
  git add data/models/valucast_scouting_llm_cache.json
fi
# Forward-ledger scoreboard (plan 030 S3): guarded add — the artifact is
# not yet tracked and a failed build aborts the job before this step, so an
# unconditional pathspec would fail the whole publish on any run where the
# scoreboard build produced nothing. Guard it like the other new artifacts.
if [ -f data/models/valucast_forward_scoreboard.json ]; then
  git add data/models/valucast_forward_scoreboard.json
fi
# Plate-discipline artifact: guarded add — absent until the first full
# backfill lands (and on any cold-cache/no-op morning at HEAD without
# it), and an unconditional pathspec would fail the whole publish step.
if [ -f data/models/valucast_pitch_discipline.json ]; then
  git add data/models/valucast_pitch_discipline.json
fi
# AAA-Statcast feature artifact: same guarded add — absent until the first
# backfill lands (the pitch cache is uncommitted, so a cold-cache CI morning
# produces no artifact) and an unconditional pathspec would fail the publish.
if [ -f data/models/valucast_aaa_statcast_features.json ]; then
  git add data/models/valucast_aaa_statcast_features.json
fi
# Season-stamped AAA-Statcast vintage archive: append-only, hash-skipped, so
# most nights add nothing. Guarded add — the directory does not exist until the
# first vintage lands (cold-cache CI mornings never build the features artifact
# to archive), and an unconditional pathspec would fail the whole publish step.
if [ -d data/aaa_statcast_archive ]; then
  git add data/aaa_statcast_archive/
fi
if [ -d data/milb_observation_archive ]; then
  git add data/milb_observation_archive/*.json
fi
