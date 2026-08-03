"""Registered, research-only walk-forward evaluator for pitcher skill evidence."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import random
import re
import tempfile
from pathlib import Path

from projections.backtest.pitching_harness import _qualified
from projections.constants import MIN_RP_IP_EVAL, MIN_SP_IP_EVAL
from projections.models.pitcher_params import PitcherMarcelParams
from projections.models.pitcher_skill_challenger import (
    FEATURE_ORDER,
    PitcherSkillChallengerParams,
    apply_rates_to_control,
    fit_fold,
    predict_rates,
)


TARGET_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025)
FEATURE_SEASONS = tuple(range(2015, 2025))
ENDPOINTS = ("k_per_9", "bb_per_9", "era", "whip")
ABLATIONS = ("shape", "location_execution", "arsenal")
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 35_021
MINIMUM_PITCHES = 500
RIDGE_LAMBDA = 10.0
MINIMUM_SAMPLE = 250
MINIMUM_REDUCTION_PCT = 2.0
MAXIMUM_REGRESSION_PCT = 1.0
MINIMUM_FOLD_WINS = 4
RESULT_PATH = Path("data/validation/mlb_pitcher_skill_challenger_result.json")
ALLOWED_VERDICTS = {
    "retrospective_pass_shadow_only",
    "validated_underperformance",
    "no_material_improvement",
    "invalid",
    "spent_error",
}
BASE_FLAGS = {
    "research_only": True,
    "feeds_live_projection": False,
    "feeds_rank_or_value": False,
    "feeds_pitcher_publication": False,
    "claim_eligible": False,
}

# Independent copy: drift in the fitted model fails before scoring.
REGISTERED_FEATURE_ORDER = (
    "control_k_bf",
    "control_bb_bf",
    "control_p_sp",
    "velocity_deviation",
    "ivb_deviation",
    "horizontal_movement_deviation",
    "spin_deviation",
    "extension_deviation",
    "whiff_rate",
    "csw_rate",
    "called_strike_rate",
    "zone_rate",
    "heart_rate",
    "edge_rate",
    "waste_rate",
    "horizontal_location_dispersion",
    "vertical_location_dispersion",
    "arsenal_count",
    "usage_hhi",
    "fastball_share",
    "max_velocity_separation",
    "max_movement_separation",
    "velocity_known",
    "ivb_known",
    "horizontal_movement_known",
    "spin_known",
    "extension_known",
)


def _canonical_bytes(payload) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(payload) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def load_registration(path: Path) -> dict:
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(
        r"<!-- mlb-pitcher-skill-registration:start -->\s*```json\s*(\{.*?\})\s*```\s*"
        r"<!-- mlb-pitcher-skill-registration:end -->",
        text,
        flags=re.S,
    )
    if not match:
        raise ValueError("Plan 035 registration marker is missing")
    return json.loads(match.group(1))


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"registration drift: {message}")


def missing_registration_seals(registration: dict) -> list[str]:
    return sorted(
        key
        for key in ("implementation_commit", "source_hashes", "readiness_hash")
        if not registration.get(key)
    )


def validate_registration(registration: dict, *, require_seals: bool) -> None:
    model = registration.get("model_and_evaluation") or {}
    gate = model.get("primary_gate") or {}
    bootstrap = model.get("paired_hierarchical_bootstrap") or {}
    pitch_type = model.get("meaningful_pitch_type") or {}
    clip = model.get("correction_clip") or {}
    _expect(registration.get("study_id") == "mlb_pitcher_skill_challenger_v1", "study id")
    _expect(registration.get("status") == "registered_unspent", "status")
    _expect(registration.get("research_only") is True, "research-only flag")
    _expect({key: registration.get(key) for key in BASE_FLAGS if key != "research_only"} == {key: value for key, value in BASE_FLAGS.items() if key != "research_only"}, "boundary flags")
    _expect(tuple(registration.get("retrospective_target_seasons") or ()) == TARGET_SEASONS, "fold seasons")
    _expect(tuple(registration.get("statcast_feature_seasons") or ()) == FEATURE_SEASONS, "source seasons")
    _expect(registration.get("minimum_input_pitches") == MINIMUM_PITCHES, "pitch floor")
    _expect(registration.get("ridge_lambda") == RIDGE_LAMBDA, "ridge lambda")
    _expect(registration.get("bootstrap_seed") == BOOTSTRAP_SEED, "bootstrap seed")
    _expect(registration.get("outer_looks") == 1, "outer look count")
    _expect(tuple(FEATURE_ORDER) == REGISTERED_FEATURE_ORDER, "feature order")
    params = PitcherSkillChallengerParams()
    _expect(
        params.ridge_lambda == RIDGE_LAMBDA
        and params.minimum_input_pitches == MINIMUM_PITCHES
        and tuple(params.residual_clip_quantiles) == (0.05, 0.95),
        "parameter defaults",
    )
    _expect(
        MIN_SP_IP_EVAL == 60 and MIN_RP_IP_EVAL == 20,
        "Control qualification floors",
    )
    control_params = PitcherMarcelParams()
    _expect(
        tuple(control_params.season_weights) == (5.0, 4.0, 3.0)
        and control_params.n_reg == 300.0
        and control_params.era_from_fip is True,
        "Control parameter defaults",
    )
    _expect(model.get("feature_set") == "one_combined_shape_location_execution_arsenal_set", "feature set")
    _expect(
        model.get("target_residuals")
        == {
            "k_bf": "actual_next_season_k_bf_minus_control_k_bf",
            "bb_bf": "actual_next_season_bb_bf_minus_control_bb_bf",
        },
        "target residuals",
    )
    _expect(tuple(model.get("descriptive_ablations") or ()) == ABLATIONS, "ablation order")
    _expect(
        model.get("ablation_policy") == "in_look_descriptive_only",
        "ablation policy",
    )
    _expect(
        model.get("fold_rule")
        == "target_T_trains_only_outcome_seasons_before_T",
        "fold rule",
    )
    _expect(
        model.get("control")
        == {
            "params": "PitcherMarcelParams()",
            "builder": "build_pitcher_projections",
            "version": "registration_commit",
        },
        "Control contract",
    )
    _expect(
        tuple(model.get("context_comparators") or ())
        == ("same_season_persistence", "archived_steamer"),
        "context comparators",
    )
    _expect(
        model.get("context_comparator_common_support")
        == "exact_same_player_outcome_and_forecast_window_only"
        and model.get("context_comparator_policy")
        == "context_only_never_trains_challenger_or_rescues_gate",
        "context comparator policy",
    )
    _expect(tuple(model.get("scored_folds") or ()) == TARGET_SEASONS, "scored folds")
    _expect(model.get("scorecard") == "canonical_methodology_scorecard", "scorecard")
    _expect(
        model.get("input_eligibility")
        == {
            "feature_season": "T-1",
            "minimum_tracked_pitches": 500,
            "requires_control_projection_for_T": True,
        },
        "input eligibility",
    )
    _expect(
        model.get("location_geometry")
        == {
            "horizontal_zone_half_width_ft": 0.83,
            "vertical_bounds": "per_pitch_sz_bot_to_sz_top",
            "valid_location_requires": ["plate_x", "plate_z", "sz_top", "sz_bot"],
            "rate_denominator": "pitches_with_all_valid_location_fields",
            "zone": "inside_closed_strike_zone_rectangle",
            "heart": "central_50_percent_of_rectangle_width_and_height",
            "edge": "euclidean_distance_to_clamped_rectangle_boundary_lte_3_inches_inside_or_outside",
            "waste": "outside_euclidean_distance_to_closest_rectangle_point_gte_12_inches",
        },
        "location geometry",
    )
    _expect(pitch_type == {"minimum_pitches": 50, "minimum_usage": 0.05}, "pitch-type gate")
    _expect(model.get("ridge") == {"lambda": 10.0, "grid_search": False}, "ridge contract")
    _expect(clip.get("lower_training_residual_percentile") == 5 and clip.get("upper_training_residual_percentile") == 95 and clip.get("fit_independently_inside_each_fold_and_target") is True, "correction clips")
    _expect(tuple(gate.get("endpoints") or ()) == ENDPOINTS, "endpoints")
    _expect(gate.get("minimum_pooled_out_of_sample_mae_reduction_pct") == MINIMUM_REDUCTION_PCT, "pooled gate")
    _expect(gate.get("maximum_endpoint_or_projected_role_cohort_regression_pct") == MAXIMUM_REGRESSION_PCT, "regression guard")
    _expect(gate.get("minimum_improved_folds") == MINIMUM_FOLD_WINS and gate.get("total_scored_folds") == len(TARGET_SEASONS), "fold gate")
    _expect(gate.get("minimum_scored_pitcher_seasons") == MINIMUM_SAMPLE, "sample gate")
    _expect(bootstrap.get("resamples") == BOOTSTRAP_RESAMPLES and bootstrap.get("seed") == BOOTSTRAP_SEED, "bootstrap configuration")
    _expect(bootstrap.get("sampling_order") == "completed_target_season_then_pitcher" and bootstrap.get("interval") == "two_sided_95_percentile", "bootstrap method")
    _expect(
        bootstrap.get("use") == "descriptive_only_for_retrospective_gate",
        "bootstrap use",
    )
    _expect(
        model.get("post_look_policy")
        == "no_second_retrospective_variant_after_outer_result_known",
        "post-look policy",
    )
    _expect(
        model.get("prospective_confirmation")
        == {"season": 2026, "evaluate_only_after_season_complete": True},
        "prospective confirmation",
    )
    _expect(BOOTSTRAP_SEED not in set(registration.get("forbidden_bootstrap_seeds") or ()), "seed is not fresh")
    missing = missing_registration_seals(registration)
    if require_seals and missing:
        raise ValueError("sealed registration is missing: " + ", ".join(missing))
    if not missing:
        _expect(isinstance(registration["implementation_commit"], str) and len(registration["implementation_commit"]) == 40, "implementation commit seal")
        _expect(set(registration["source_hashes"]) == {str(year) for year in FEATURE_SEASONS}, "source hash seasons")
        _expect(isinstance(registration["readiness_hash"], str) and len(registration["readiness_hash"]) == 64, "readiness hash seal")


def _id(value) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError("missing MLBAM identity")
    return normalized


def _index(rows: list[dict], *, label: str, season_key: str = "season") -> dict:
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"malformed {label} row")
        try:
            key = (_id(row.get("mlbam_id")), int(row[season_key]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"malformed {label} season") from error
        if key in indexed:
            raise ValueError(f"duplicate {label} row for {key[0]} {key[1]}")
        indexed[key] = row
    return indexed


def _identity_index(rows: list[dict]) -> dict[str, str]:
    indexed = {}
    for row in rows:
        pitcher_id = _id(row.get("mlbam_id"))
        if pitcher_id in indexed:
            raise ValueError(f"duplicate identity row for {pitcher_id}")
        hand = str(row.get("throws") or row.get("pitcher_hand") or "").upper()
        if hand not in {"L", "R"}:
            raise ValueError(f"missing or invalid hand for {pitcher_id}")
        indexed[pitcher_id] = hand
    return indexed


def _pair_keys(rows: list[dict]) -> list[tuple[str, int]]:
    pairs = []
    seen = set()
    for row in rows:
        try:
            key = (_id(row.get("mlbam_id")), int(row["outcome_season"]))
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("malformed evaluation pair") from error
        if key in seen:
            raise ValueError(f"duplicate evaluation pair for {key[0]} {key[1]}")
        seen.add(key)
        pairs.append(key)
    return sorted(pairs, key=lambda value: (value[1], value[0]))


def summarize_common_support(bundle: dict) -> dict:
    """Disclose the Control/outcome intersection without invalidating unmatched rows."""
    controls = _index(bundle.get("controls") or [], label="Control")
    outcomes = _index(bundle.get("outcomes") or [], label="outcome")
    declared = _pair_keys(bundle.get("pair_keys") or [])
    seasons = sorted({season for _, season in controls} | {season for _, season in outcomes})
    by_season = {}
    for season in seasons:
        control_ids = {pitcher_id for pitcher_id, value in controls if value == season}
        outcome_ids = {pitcher_id for pitcher_id, value in outcomes if value == season}
        by_season[str(season)] = {
            "control_count": len(control_ids),
            "outcome_count": len(outcome_ids),
            "pair_count": len(control_ids & outcome_ids),
            "control_only_count": len(control_ids - outcome_ids),
            "outcome_only_count": len(outcome_ids - control_ids),
        }
    fields = (
        "control_count",
        "outcome_count",
        "pair_count",
        "control_only_count",
        "outcome_only_count",
    )
    return {
        "source_seasons": seasons,
        "scored_target_seasons": sorted({season for _, season in declared}),
        "by_season": by_season,
        "totals": {
            field: sum(row[field] for row in by_season.values()) for field in fields
        },
    }


def _required_outcome_number(outcome: dict, key: str) -> float:
    value = outcome.get(key) if isinstance(outcome, dict) else None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or float(value) < 0
    ):
        raise ValueError(f"missing or invalid outcome {key}")
    return float(value)


def _validate_outcome(outcome: dict) -> None:
    for key in ("BF", "IP", "K", "BB", "ER", "H_ALLOWED"):
        _required_outcome_number(outcome, key)
    if float(outcome["BF"]) <= 0:
        raise ValueError("outcome BF must be positive")


def _required_score_number(mapping: dict, key: str, path: str) -> float:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
    ):
        raise ValueError(f"malformed score feature: {path}.{key}")
    return float(value)


def _required_score_mapping(mapping: dict, key: str, path: str) -> dict:
    value = mapping.get(key) if isinstance(mapping, dict) else None
    if not isinstance(value, dict):
        raise ValueError(f"malformed score feature: {path}.{key}")
    return value


def _validate_score_feature(feature: dict) -> None:
    """Validate present, eligible feature evidence before prediction or rebuilding lines."""
    _required_score_number(feature, "pitch_count", "feature")
    outcomes = _required_score_mapping(feature, "outcomes", "feature")
    for key in ("whiff_rate", "csw_rate", "called_strike_rate"):
        _required_score_number(outcomes, key, "feature.outcomes")
    location = _required_score_mapping(feature, "location", "feature")
    for key in ("zone_rate", "heart_rate", "edge_rate", "waste_rate"):
        _required_score_number(location, key, "feature.location")
    for axis in ("plate_x", "plate_z"):
        mapping = _required_score_mapping(location, axis, "feature.location")
        _required_score_number(mapping, "stddev", f"feature.location.{axis}")
    arsenal = _required_score_mapping(feature, "arsenal", "feature")
    for key in (
        "count",
        "usage_hhi",
        "fastball_share",
        "max_velocity_separation",
        "max_movement_separation",
    ):
        _required_score_number(arsenal, key, "feature.arsenal")
    pitch_types = _required_score_mapping(feature, "pitch_types", "feature")
    for pitch_type, type_row in pitch_types.items():
        if not isinstance(type_row, dict):
            raise ValueError(f"malformed score feature: feature.pitch_types.{pitch_type}")
        _required_score_number(type_row, "usage", f"feature.pitch_types.{pitch_type}")
        shape = _required_score_mapping(
            type_row, "shape", f"feature.pitch_types.{pitch_type}"
        )
        for field in (
            "velocity",
            "induced_vertical_movement",
            "horizontal_movement",
            "spin",
            "extension",
        ):
            observed = _required_score_mapping(
                shape, field, f"feature.pitch_types.{pitch_type}.shape"
            )
            sample_count = _required_score_number(
                observed,
                "sample_count",
                f"feature.pitch_types.{pitch_type}.shape.{field}",
            )
            if sample_count > 0:
                _required_score_number(
                    observed,
                    "mean",
                    f"feature.pitch_types.{pitch_type}.shape.{field}",
                )


def _enrich_feature(feature: dict | None, hand: str, expected_season: int) -> dict | None:
    if feature is None:
        return None
    if int(feature.get("season", -1)) != expected_season:
        raise ValueError("feature season mismatch")
    existing = str(feature.get("pitcher_hand") or "").upper()
    if existing and existing != hand:
        raise ValueError("conflicting hand between identity and feature")
    enriched = copy.deepcopy(feature)
    enriched["pitcher_hand"] = hand
    return enriched


def _projected_role(control: dict) -> str:
    p_sp = float(control.get("p_sp", -1))
    if not 0.0 <= p_sp <= 1.0:
        raise ValueError("Control p_sp must be in [0, 1]")
    return "starter" if p_sp >= 0.5 else "reliever"


def _qualified_under_control_role(outcome: dict, control: dict) -> bool:
    # Reuse the incumbent harness rule while replacing realized role with Control p_sp.
    proxy = dict(outcome)
    proxy["G"] = 1.0
    proxy["GS"] = float(control["p_sp"])
    return _qualified(proxy)


def prepare_fold(bundle: dict, target_season: int, *, minimum_pitches: int) -> dict:
    controls = _index(bundle.get("controls") or [], label="Control")
    outcomes = _index(bundle.get("outcomes") or [], label="outcome")
    features = _index(bundle.get("features") or [], label="feature")
    identities = _identity_index(bundle.get("identities") or [])
    declared_pairs = _pair_keys(bundle.get("pair_keys") or [])
    for key in declared_pairs:
        if key not in controls:
            raise ValueError(f"missing Control for {key[0]} {key[1]}")
        if key not in outcomes:
            raise ValueError(f"missing outcome for {key[0]} {key[1]}")
        if key[0] not in identities:
            raise ValueError(f"missing hand identity for {key[0]}")

    # Identity-backed rows with matching T-1 evidence are intended study joins;
    # unmatched source-only rows remain valid and are disclosed separately.
    for pitcher_id, season in outcomes:
        if (
            pitcher_id in identities
            and (pitcher_id, season - 1) in features
            and (pitcher_id, season) not in controls
        ):
            raise ValueError(f"missing Control for {pitcher_id} {season}")
    for pitcher_id, season in controls:
        if (
            pitcher_id in identities
            and (pitcher_id, season - 1) in features
            and (pitcher_id, season) not in outcomes
        ):
            raise ValueError(f"missing outcome for {pitcher_id} {season}")

    common_pairs = sorted(
        set(controls) & set(outcomes), key=lambda value: (value[1], value[0])
    )

    def joined_row(pitcher_id: str, season: int) -> dict:
        if pitcher_id not in identities:
            raise ValueError(f"missing hand identity for {pitcher_id}")
        control = copy.deepcopy(controls[(pitcher_id, season)])
        outcome = copy.deepcopy(outcomes[(pitcher_id, season)])
        if int(control.get("season", -1)) != season:
            raise ValueError("Control season mismatch")
        if int(outcome.get("season", -1)) != season:
            raise ValueError("outcome season mismatch")
        _validate_outcome(outcome)
        feature = _enrich_feature(
            features.get((pitcher_id, season - 1)), identities[pitcher_id], season - 1
        )
        fallback_reason = None
        if feature is None:
            fallback_reason = "missing_feature"
        else:
            pitch_count = _required_score_number(feature, "pitch_count", "feature")
            if pitch_count < minimum_pitches:
                fallback_reason = "below_pitch_floor"
            else:
                _validate_score_feature(feature)
        return {
            "mlbam_id": pitcher_id,
            "feature_season": season - 1,
            "outcome_season": season,
            "fold_target_season": target_season,
            "control": control,
            "feature_row": feature,
            "outcome": outcome,
            "fallback_reason": fallback_reason,
            "projected_role": _projected_role(control),
        }

    training_rows = []
    for pitcher_id, season in common_pairs:
        if season >= target_season:
            continue
        row = joined_row(pitcher_id, season)
        if row["fallback_reason"] is None:
            training_rows.append(row)

    target_pairs = [key for key in declared_pairs if key[1] == target_season]
    scoring_rows = []
    for pitcher_id, season in target_pairs:
        row = joined_row(pitcher_id, season)
        if _qualified_under_control_role(row["outcome"], row["control"]):
            scoring_rows.append(row)
    return {
        "target_season": target_season,
        "training_rows": training_rows,
        "scoring_rows": scoring_rows,
        "qualification": {
            "eligible": len(target_pairs),
            "qualified": len(scoring_rows),
            "excluded": len(target_pairs) - len(scoring_rows),
        },
    }


def _actual_endpoints(outcome: dict) -> dict[str, float]:
    _validate_outcome(outcome)
    ip = float(outcome["IP"])
    if ip <= 0:
        raise ValueError("actual IP must be positive")
    return {
        "k_per_9": 9.0 * float(outcome["K"]) / ip,
        "bb_per_9": 9.0 * float(outcome["BB"]) / ip,
        "era": 9.0 * float(outcome["ER"]) / ip,
        "whip": (float(outcome["BB"]) + float(outcome["H_ALLOWED"])) / ip,
    }


def _forecast_endpoints(row: dict) -> dict[str, float]:
    return {
        "k_per_9": float(row["K_9"]),
        "bb_per_9": float(row["BB_9"]),
        "era": float(row["ERA"]),
        "whip": float(row["WHIP"]),
    }


def _mask_feature(feature: dict | None, family: str) -> dict | None:
    if feature is None:
        return None
    masked = copy.deepcopy(feature)
    if family == "shape":
        for pitch_type in masked.get("pitch_types", {}).values():
            for stat in pitch_type.get("shape", {}).values():
                stat.update({"mean": 0.0, "sample_count": 1})
    elif family == "location_execution":
        masked["outcomes"].update(
            {"whiff_rate": 0.0, "csw_rate": 0.0, "called_strike_rate": 0.0}
        )
        masked["location"].update(
            {"zone_rate": 0.0, "heart_rate": 0.0, "edge_rate": 0.0, "waste_rate": 0.0}
        )
        masked["location"]["plate_x"]["stddev"] = 0.0
        masked["location"]["plate_z"]["stddev"] = 0.0
    elif family == "arsenal":
        masked["arsenal"] = {
            "count": 0,
            "usage_hhi": 0.0,
            "fastball_share": 0.0,
            "max_velocity_separation": 0.0,
            "max_movement_separation": 0.0,
        }
    else:
        raise ValueError(f"unknown ablation {family}")
    return masked


def _score_variant(bundle: dict, *, ablation: str | None = None) -> tuple[list[dict], dict]:
    errors = []
    fallback_counts = {"below_pitch_floor": 0, "missing_feature": 0}
    fold_samples = {}
    qualification_by_fold = {}
    # Validate every scored fold before any prediction or line reconstruction.
    prepared_folds = {
        target: prepare_fold(bundle, target, minimum_pitches=MINIMUM_PITCHES)
        for target in TARGET_SEASONS
    }
    for target, prepared in prepared_folds.items():
        training = copy.deepcopy(prepared["training_rows"])
        scoring = copy.deepcopy(prepared["scoring_rows"])
        if ablation:
            for row in training + scoring:
                row["feature_row"] = _mask_feature(row["feature_row"], ablation)
        if not training:
            raise ValueError(f"invalid fold {target}: no training history")
        model = fit_fold(training, PitcherSkillChallengerParams())
        fold_samples[str(target)] = len(scoring)
        qualification_by_fold[str(target)] = prepared["qualification"]
        for row in scoring:
            control = row["control"]
            if row["fallback_reason"]:
                fallback_counts[row["fallback_reason"]] += 1
                challenger = copy.deepcopy(control)
            else:
                _validate_score_feature(row["feature_row"])
                rates = predict_rates(model, control, row["feature_row"])
                challenger = apply_rates_to_control(
                    control, rates["k_bf"], rates["bb_bf"]
                )
            actual = _actual_endpoints(row["outcome"])
            control_endpoints = _forecast_endpoints(control)
            challenger_endpoints = _forecast_endpoints(challenger)
            control_errors = {
                endpoint: abs(control_endpoints[endpoint] - actual[endpoint])
                for endpoint in ENDPOINTS
            }
            challenger_errors = {
                endpoint: abs(challenger_endpoints[endpoint] - actual[endpoint])
                for endpoint in ENDPOINTS
            }
            errors.append(
                {
                    "season": target,
                    "mlbam_id": row["mlbam_id"],
                    "role": row["projected_role"],
                    "control_errors": control_errors,
                    "challenger_errors": challenger_errors,
                    "control_total_error": sum(control_errors.values()),
                    "challenger_total_error": sum(challenger_errors.values()),
                }
            )
    return errors, {
        "fallback_counts": fallback_counts,
        "fold_samples": fold_samples,
        "qualification_by_fold": qualification_by_fold,
        "common_support": summarize_common_support(bundle),
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_errors(rows: list[dict]) -> dict:
    summary = {
        "sample": len(rows),
        "pooled": {"control_mae": None, "challenger_mae": None},
        "endpoints": {},
        "folds": {},
        "projected_roles": {},
    }
    if not rows:
        return summary
    for row in rows:
        row.setdefault("control_total_error", sum(row["control_errors"].values()))
        row.setdefault(
            "challenger_total_error", sum(row["challenger_errors"].values())
        )
    summary["pooled"] = {
        "control_mae": sum(row["control_total_error"] for row in rows) / len(rows),
        "challenger_mae": sum(row["challenger_total_error"] for row in rows) / len(rows),
    }
    for endpoint in ENDPOINTS:
        summary["endpoints"][endpoint] = {
            "control_mae": _mean([row["control_errors"][endpoint] for row in rows]),
            "challenger_mae": _mean([row["challenger_errors"][endpoint] for row in rows]),
        }
    for season in sorted({int(row["season"]) for row in rows}):
        cohort = [row for row in rows if int(row["season"]) == season]
        summary["folds"][str(season)] = {
            "sample": len(cohort),
            "control_mae": sum(row["control_total_error"] for row in cohort) / len(cohort),
            "challenger_mae": sum(row["challenger_total_error"] for row in cohort) / len(cohort),
        }
    for role in ("starter", "reliever"):
        cohort = [row for row in rows if row["role"] == role]
        if cohort:
            summary["projected_roles"][role] = {
                "sample": len(cohort),
                "control_mae": sum(row["control_total_error"] for row in cohort) / len(cohort),
                "challenger_mae": sum(row["challenger_total_error"] for row in cohort) / len(cohort),
            }
    return summary


def _pct_change(control, challenger) -> float | None:
    if control is None or challenger is None:
        return None
    if control == 0:
        return 0.0 if challenger == 0 else math.inf
    return (challenger - control) / control * 100.0


def score_registered_gate(metrics: dict, registration: dict) -> dict:
    validate_registration(registration, require_seals=False)
    pooled = metrics.get("pooled") or {}
    pooled_regression = _pct_change(
        pooled.get("control_mae"), pooled.get("challenger_mae")
    )
    reduction = -pooled_regression if pooled_regression is not None else None
    endpoint_changes = [
        _pct_change(row.get("control_mae"), row.get("challenger_mae"))
        for row in (metrics.get("endpoints") or {}).values()
    ]
    role_changes = [
        _pct_change(row.get("control_mae"), row.get("challenger_mae"))
        for row in (metrics.get("projected_roles") or {}).values()
    ]
    folds = metrics.get("folds") or {}
    fold_wins = sum(
        row.get("challenger_mae") is not None
        and row.get("control_mae") is not None
        and row["challenger_mae"] < row["control_mae"]
        for row in folds.values()
    )
    endpoint_worst = max(endpoint_changes) if len(endpoint_changes) == len(ENDPOINTS) else math.inf
    role_worst = max(role_changes) if len(role_changes) == 2 else math.inf
    checks = {
        "pooled_reduction": {
            "value": reduction,
            "threshold": MINIMUM_REDUCTION_PCT,
            "passed": reduction is not None and math.isfinite(reduction) and reduction >= MINIMUM_REDUCTION_PCT,
        },
        "endpoint_regression": {
            "value": endpoint_worst,
            "maximum": MAXIMUM_REGRESSION_PCT,
            "passed": math.isfinite(endpoint_worst) and endpoint_worst <= MAXIMUM_REGRESSION_PCT,
        },
        "projected_role_regression": {
            "value": role_worst,
            "maximum": MAXIMUM_REGRESSION_PCT,
            "passed": math.isfinite(role_worst) and role_worst <= MAXIMUM_REGRESSION_PCT,
        },
        "fold_wins": {
            "value": fold_wins,
            "minimum": MINIMUM_FOLD_WINS,
            "folds_scored": len(folds),
            "required_folds": len(TARGET_SEASONS),
            "passed": fold_wins >= MINIMUM_FOLD_WINS and len(folds) == len(TARGET_SEASONS),
        },
        "minimum_sample": {
            "value": int(metrics.get("sample") or 0),
            "minimum": MINIMUM_SAMPLE,
            "passed": int(metrics.get("sample") or 0) >= MINIMUM_SAMPLE,
        },
    }
    return {
        "criteria": {
            "minimum_pooled_reduction_pct": MINIMUM_REDUCTION_PCT,
            "maximum_endpoint_or_role_regression_pct": MAXIMUM_REGRESSION_PCT,
            "minimum_fold_wins": MINIMUM_FOLD_WINS,
            "required_folds": len(TARGET_SEASONS),
            "minimum_sample": MINIMUM_SAMPLE,
        },
        "checks": checks,
        "passed": all(check["passed"] for check in checks.values()),
    }


def verdict_from_gate(metrics: dict, gate: dict) -> str:
    if gate.get("passed"):
        return "retrospective_pass_shadow_only"
    control = (metrics.get("pooled") or {}).get("control_mae")
    challenger = (metrics.get("pooled") or {}).get("challenger_mae")
    if control is None or challenger is None:
        return "invalid"
    if challenger > control:
        return "validated_underperformance"
    return "no_material_improvement"


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] + (ordered[high] - ordered[low]) * weight


def _bootstrap_reduction(control_total: float, challenger_total: float) -> float:
    if control_total == 0:
        raise ValueError("bootstrap reduction is undefined at zero Control error")
    return (control_total - challenger_total) / control_total * 100.0


def hierarchical_paired_bootstrap(rows: list[dict], *, resamples: int, seed: int) -> dict:
    if resamples != BOOTSTRAP_RESAMPLES or seed != BOOTSTRAP_SEED:
        raise ValueError("bootstrap configuration differs from registration")
    groups = {}
    for row in sorted(rows, key=lambda item: (int(item["season"]), str(item["mlbam_id"]))):
        groups.setdefault(int(row["season"]), []).append(row)
    seasons = sorted(groups)
    if not seasons or any(not groups[season] for season in seasons):
        raise ValueError("bootstrap requires completed target-season groups")
    rng = random.Random(seed)
    draws = []
    for _ in range(resamples):
        control_total = challenger_total = 0.0
        for season in (rng.choice(seasons) for _ in seasons):
            cohort = groups[season]
            for _ in cohort:
                row = rng.choice(cohort)
                control_total += float(row["control_total_error"])
                challenger_total += float(row["challenger_total_error"])
        draws.append(
            0.0
            if control_total == 0 and challenger_total == 0
            else _bootstrap_reduction(control_total, challenger_total)
        )
    return {
        "resamples": resamples,
        "seed": seed,
        "sampling_order": "completed_target_season_then_pitcher",
        "statistic": "paired_pooled_mae_reduction_pct",
        "percentile_interval_95": [
            _percentile(draws, 0.025),
            _percentile(draws, 0.975),
        ],
    }


def _context_metrics(bundle: dict, errors: list[dict], label: str) -> dict:
    source = _index(bundle.get(label) or [], label=label)
    outcomes = _index(bundle.get("outcomes") or [], label="outcome")
    common = []
    for row in errors:
        key = (row["mlbam_id"], int(row["season"]))
        forecast = source.get(key)
        if forecast is None or forecast.get("forecast_window") != "full_season":
            continue
        actual = _actual_endpoints(outcomes[key])
        forecast_values = _forecast_endpoints(forecast)
        common.append(
            {
                "comparator": {
                    endpoint: abs(forecast_values[endpoint] - actual[endpoint])
                    for endpoint in ENDPOINTS
                },
                "control": row["control_errors"],
                "challenger": row["challenger_errors"],
            }
        )
    return {
        "use": "context_only_never_trains_or_rescues_gate",
        "common_support_count": len(common),
        "missing_count": len(errors) - len(common),
        "mae": {
            endpoint: _mean([row["comparator"][endpoint] for row in common])
            for endpoint in ENDPOINTS
        },
        "control_mae_on_common_support": {
            endpoint: _mean([row["control"][endpoint] for row in common])
            for endpoint in ENDPOINTS
        },
        "challenger_mae_on_common_support": {
            endpoint: _mean([row["challenger"][endpoint] for row in common])
            for endpoint in ENDPOINTS
        },
    }


def evaluate_registered_look(bundle: dict, registration: dict) -> dict:
    validate_registration(registration, require_seals=True)
    errors, coverage = _score_variant(bundle)
    metrics = summarize_errors(errors)
    gate = score_registered_gate(metrics, registration)
    verdict = verdict_from_gate(metrics, gate)
    ablations = {}
    for family in ABLATIONS:
        family_errors, _ = _score_variant(bundle, ablation=family)
        ablations[family] = {
            "use": "descriptive_only_never_selects_or_rescues",
            "metrics": summarize_errors(family_errors),
        }
    payload = {
        **BASE_FLAGS,
        "study_id": registration["study_id"],
        "registration_hash": canonical_sha256(registration),
        "implementation_commit": registration["implementation_commit"],
        "source_hashes": registration["source_hashes"],
        "readiness_hash": registration["readiness_hash"],
        "sample": metrics["sample"],
        "folds": list(TARGET_SEASONS),
        "coverage": coverage,
        "qualification": {
            "starter_floor_ip": MIN_SP_IP_EVAL,
            "reliever_floor_ip": MIN_RP_IP_EVAL,
            "role_source": "Control_p_sp",
            "by_fold": coverage["qualification_by_fold"],
            "totals": {
                key: sum(
                    row[key] for row in coverage["qualification_by_fold"].values()
                )
                for key in ("eligible", "qualified", "excluded")
            },
        },
        "metrics": metrics,
        "gate": gate,
        "paired_hierarchical_bootstrap": hierarchical_paired_bootstrap(
            errors, resamples=BOOTSTRAP_RESAMPLES, seed=BOOTSTRAP_SEED
        ),
        "context_comparators": {
            "persistence": _context_metrics(bundle, errors, "persistence"),
            "steamer": _context_metrics(bundle, errors, "steamer"),
        },
        "descriptive_ablations": ablations,
        "verdict": verdict,
        "prospective_confirmation": {
            "required": True,
            "season": 2026,
            "after_season_complete": True,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, allow_nan=False).lower()
    forbidden = ("player_name", "mlbam_id", "raw_pitch", "board_rank", "competitor")
    if any(token in encoded for token in forbidden):
        raise ValueError("private or player-level field reached result payload")
    if verdict not in ALLOWED_VERDICTS:
        raise ValueError("invalid verdict")
    return payload


def _readiness_evidence(
    registration: dict,
    *,
    implementation_commit: str,
    source_hashes: dict,
    fold_training_counts: dict,
    fold_support: dict,
    scoreable_population: int,
    common_support: dict,
    serving_import_matches: list,
) -> dict:
    return {
        "study_id": registration.get("study_id"),
        "implementation_commit": implementation_commit,
        "source_hashes": source_hashes,
        "required_feature_seasons": list(FEATURE_SEASONS),
        "required_target_seasons": list(TARGET_SEASONS),
        "fold_training_counts": fold_training_counts,
        "fold_support": fold_support,
        "scoreable_population": scoreable_population,
        "common_support": common_support,
        "bootstrap_seed": registration.get("bootstrap_seed"),
        "serving_import_matches": sorted(serving_import_matches),
    }


def check_readiness(
    bundle: dict,
    registration: dict,
    *,
    implementation_commit: str,
    source_hashes: dict,
    serving_import_matches: list,
) -> dict:
    validate_registration(registration, require_seals=False)
    manifest = bundle.get("source_manifest") or {}
    if tuple(manifest.get("feature_seasons") or ()) != FEATURE_SEASONS:
        raise ValueError("source manifest does not contain exact required seasons")
    if manifest.get("source_hashes") != source_hashes:
        raise ValueError("source manifest hashes do not reconcile")
    fold_training_counts = {}
    fold_support = {}
    scoreable_population = 0
    for target in TARGET_SEASONS:
        fold = prepare_fold(bundle, target, minimum_pitches=MINIMUM_PITCHES)
        fold_training_counts[str(target)] = len(fold["training_rows"])
        fold_support[str(target)] = fold["qualification"]
        scoreable_population += len(fold["scoring_rows"])
    common_support = summarize_common_support(bundle)
    evidence = _readiness_evidence(
        registration,
        implementation_commit=implementation_commit,
        source_hashes=source_hashes,
        fold_training_counts=fold_training_counts,
        fold_support=fold_support,
        scoreable_population=scoreable_population,
        common_support=common_support,
        serving_import_matches=serving_import_matches,
    )
    evidence_hash = canonical_sha256(evidence)
    missing = missing_registration_seals(registration)
    blockers = []
    declared_target_seasons = tuple(common_support["scored_target_seasons"])
    if declared_target_seasons != TARGET_SEASONS:
        blockers.append("scored_target_seasons_mismatch")
    declared_support = bundle.get("common_support")
    if declared_support is not None and declared_support != common_support:
        blockers.append("common_support_mismatch")
    for target in TARGET_SEASONS:
        key = str(target)
        if fold_training_counts[key] <= 0:
            blockers.append(f"missing_fold_training_history:{target}")
        if fold_support[key]["eligible"] <= 0:
            blockers.append(f"missing_declared_pairs:{target}")
        if fold_support[key]["qualified"] <= 0:
            blockers.append(f"missing_qualified_support:{target}")
            blockers.append(f"missing_scoreable_support:{target}")
    if scoreable_population < MINIMUM_SAMPLE:
        blockers.append("minimum_scoreable_population")
    if serving_import_matches:
        blockers.append("serving_import_reference")
    if registration.get("implementation_commit") and registration["implementation_commit"] != implementation_commit:
        blockers.append("implementation_commit_mismatch")
    if registration.get("source_hashes") and registration["source_hashes"] != source_hashes:
        blockers.append("source_hash_mismatch")
    if registration.get("readiness_hash") and registration["readiness_hash"] != evidence_hash:
        blockers.append("readiness_hash_mismatch")
    blockers.extend(f"missing_registration_seal:{key}" for key in missing)
    return {
        **BASE_FLAGS,
        **evidence,
        "evidence_hash": evidence_hash,
        "missing_registration_seals": missing,
        "blockers": blockers,
        "ready_to_spend": not blockers,
    }


def write_spent_result(path: Path, payload: dict) -> None:
    """Atomically create an immutable spent artifact; never overwrite."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"spent result already exists: {path}")
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as error:
            raise FileExistsError(f"spent result already exists: {path}") from error
    finally:
        Path(temporary).unlink(missing_ok=True)
