import json
import re

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_BOOTSTRAP_SEEDS = [
    28013,
    28014,
    28015,
    28017,
    29001,
    29016,
    31013,
    31017,
    32019,
    33021,
    34021,
    34027,
    34031,
    72127,
]


def _registration() -> dict:
    text = (ROOT / "plans/035-mlb-pitcher-skill-challenger.md").read_text(
        encoding="utf-8"
    )
    match = re.search(
        r"<!-- mlb-pitcher-skill-registration:start -->\s*```json\s*(.*?)\s*```",
        text,
        re.DOTALL,
    )
    assert match, "Plan 035 must contain the registered JSON block"
    return json.loads(match.group(1))


def test_mlb_pitcher_skill_study_is_registered_unspent_and_research_only():
    registration = _registration()

    assert registration["study_id"] == "mlb_pitcher_skill_challenger_v1"
    assert registration["status"] == "registered_unspent"
    assert registration["research_only"] is True
    assert registration["retrospective_target_seasons"] == [
        2020,
        2021,
        2022,
        2023,
        2024,
        2025,
    ]
    assert registration["statcast_feature_seasons"] == list(range(2015, 2025))
    assert registration["minimum_input_pitches"] == 500
    assert registration["ridge_lambda"] == 10.0
    assert registration["bootstrap_seed"] == 35021
    assert registration["outer_looks"] == 1
    assert registration["feeds_live_projection"] is False
    assert registration["feeds_rank_or_value"] is False
    assert registration["feeds_pitcher_publication"] is False
    assert registration["claim_eligible"] is False

    assert registration["forbidden_bootstrap_seeds"] == FORBIDDEN_BOOTSTRAP_SEEDS
    assert registration["bootstrap_seed"] not in FORBIDDEN_BOOTSTRAP_SEEDS
    assert registration["model_and_evaluation"] == {
        "target_residuals": {
            "k_bf": "actual_next_season_k_bf_minus_control_k_bf",
            "bb_bf": "actual_next_season_bb_bf_minus_control_bb_bf",
        },
        "feature_set": "one_combined_shape_location_execution_arsenal_set",
        "descriptive_ablations": ["shape", "location_execution", "arsenal"],
        "ablation_policy": "in_look_descriptive_only",
        "fold_rule": "target_T_trains_only_outcome_seasons_before_T",
        "control": {
            "params": "PitcherMarcelParams()",
            "builder": "build_pitcher_projections",
            "version": "registration_commit",
        },
        "context_comparators": [
            "same_season_persistence",
            "archived_steamer",
        ],
        "context_comparator_common_support": "exact_same_player_outcome_and_forecast_window_only",
        "context_comparator_policy": "context_only_never_trains_challenger_or_rescues_gate",
        "scored_folds": [2020, 2021, 2022, 2023, 2024, 2025],
        "scorecard": "canonical_methodology_scorecard",
        "input_eligibility": {
            "feature_season": "T-1",
            "minimum_tracked_pitches": 500,
            "requires_control_projection_for_T": True,
        },
        "meaningful_pitch_type": {
            "minimum_pitches": 50,
            "minimum_usage": 0.05,
        },
        "location_geometry": {
            "horizontal_zone_half_width_ft": 0.83,
            "vertical_bounds": "per_pitch_sz_bot_to_sz_top",
            "valid_location_requires": ["plate_x", "plate_z", "sz_top", "sz_bot"],
            "rate_denominator": "pitches_with_all_valid_location_fields",
            "zone": "inside_closed_strike_zone_rectangle",
            "heart": "central_50_percent_of_rectangle_width_and_height",
            "edge": "euclidean_distance_to_clamped_rectangle_boundary_lte_3_inches_inside_or_outside",
            "waste": "outside_euclidean_distance_to_closest_rectangle_point_gte_12_inches",
        },
        "ridge": {"lambda": 10.0, "grid_search": False},
        "correction_clip": {
            "lower_training_residual_percentile": 5,
            "upper_training_residual_percentile": 95,
            "fit_independently_inside_each_fold_and_target": True,
        },
        "primary_gate": {
            "endpoints": ["k_per_9", "bb_per_9", "era", "whip"],
            "minimum_pooled_out_of_sample_mae_reduction_pct": 2.0,
            "maximum_endpoint_or_projected_role_cohort_regression_pct": 1.0,
            "minimum_improved_folds": 4,
            "total_scored_folds": 6,
            "minimum_scored_pitcher_seasons": 250,
        },
        "paired_hierarchical_bootstrap": {
            "resamples": 10000,
            "sampling_order": "completed_target_season_then_pitcher",
            "seed": 35021,
            "interval": "two_sided_95_percentile",
            "use": "descriptive_only_for_retrospective_gate",
        },
        "post_look_policy": "no_second_retrospective_variant_after_outer_result_known",
        "prospective_confirmation": {
            "season": 2026,
            "evaluate_only_after_season_complete": True,
        },
    }

    readme = (ROOT / "plans/README.md").read_text(encoding="utf-8")
    assert (
        "| 035  | MLB Pitcher Skill Challenger"
        in readme
    )
    assert "REGISTERED — UNSPENT; RESEARCH ONLY" in readme
