"""ValuCast-owned universal prospect outcome profiles.

The universal model predicts factual future MLB outcomes. It deliberately does
not rank players or encode a fantasy league's category weights; downstream
league adapters may translate these profiles into league-specific values later.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

from prospects.gate import decide_gate
from prospects.model import (
    INPUT_PATH,
    MAX_AGE,
    MIN_GATE_IMPROVEMENT_PCT,
    MIN_GATE_SAMPLE,
    MATURE_THROUGH,
    RIDGE_LAMBDA,
    _fit_neighbors,
    _fit_prior,
    _fit_ridge,
    _neighbor_predict,
    _num,
    _predict,
    _prior_predict,
    _rank_concordance,
    _service_index,
    _walk_forward,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_universal_prospect_model.json"
ARCHIVE_DIR = (
    ROOT / "data" / "prediction_archive" / "valucast_universal_prospect_model"
)

MODEL_NAME = "ValuCast Universal Prospect Model"
MODEL_VERSION = "0.4.0"
MODEL_STATUS = "shadow_only"
INPUT_SCHEMA_SOURCES = {
    "1.0": {
        "prospect_outcome_dataset",
        "milb_season_stats",
        "fantrax_mlb_actuals",
        "mlb_prospect_seasons_cache",
    },
    "1.1": {
        "valucast_universal_prospect_dataset",
        "milb_season_stats",
        "fantrax_mlb_actuals",
        "mlb_prospect_seasons_cache",
        "mlb_statsapi_draft",
    },
}
LEVEL_CODE = {"A": 0.0, "A+": 1.0, "AA": 2.0, "AAA": 3.0}
EXPECTED_AGE = {"A": 20.5, "A+": 21.5, "AA": 22.5, "AAA": 24.0}
MIN_CURRENT_SAMPLE = {"hitter": 50.0, "pitcher": 15.0}
SAMPLE_REGRESSION = {"hitter": 200.0, "pitcher": 50.0}
CANONICAL_FEATURE_NAMES = {
    "hitter": ("iso", "k_pct", "bb_pct", "ops", "youth", "level"),
    "pitcher": (
        "k_per_9",
        "bb_per_9",
        "k_bb_pct",
        "era",
        "whip",
        "youth",
        "level",
        "is_starter",
    ),
}
FEATURE_NAMES = {
    "hitter": CANONICAL_FEATURE_NAMES["hitter"]
    + (
        "avg",
        "obp",
        "slg",
        "babip",
        "hr_per_600",
        "sb_per_600",
        "sample_log",
        "draft_record_known",
        "rule4_drafted",
        "draft_pick_score",
        "signing_bonus_log",
        "signing_bonus_known",
        "college_draftee",
        "high_school_draftee",
    ),
    "pitcher": CANONICAL_FEATURE_NAMES["pitcher"]
    + (
        "starts_share",
        "h_per_9",
        "hr_per_9",
        "sample_log",
        "draft_record_known",
        "rule4_drafted",
        "draft_pick_score",
        "signing_bonus_log",
        "signing_bonus_known",
        "college_draftee",
        "high_school_draftee",
    ),
}
SHRINK_FEATURES = {
    "hitter": {
        "iso",
        "k_pct",
        "bb_pct",
        "ops",
        "avg",
        "obp",
        "slg",
        "babip",
        "hr_per_600",
        "sb_per_600",
    },
    "pitcher": {
        "k_per_9",
        "bb_per_9",
        "k_bb_pct",
        "era",
        "whip",
        "starts_share",
        "h_per_9",
        "hr_per_9",
    },
}

ROLE_THRESHOLDS = {
    "hitter": {"established": 300.0, "regular": 450.0},
    "pitcher": {"established": 50.0, "rotation": 120.0},
}
STAR_THRESHOLDS = {
    "hitter": {"pa": 450.0, "ops": 0.800},
    "pitcher": {"ip": 120.0, "era": 3.75},
}


def validate_input_contract(contract: dict) -> None:
    schema_version = contract.get("schema_version")
    if schema_version not in INPUT_SCHEMA_SOURCES:
        raise ValueError(f"Unsupported prospect input schema {schema_version!r}")
    policy = contract.get("source_policy") or {}
    if policy.get("kind") != "factual_only":
        raise ValueError("Prospect input contract must be factual_only")
    if set(policy.get("sources") or []) != INPUT_SCHEMA_SOURCES[schema_version]:
        raise ValueError("Prospect input contract contains an unexpected source")
    prohibited_flags = (
        "external_rankings_used",
        "external_projections_used",
        "market_values_used",
        "dynasty_values_used",
    )
    if any(policy.get(flag) is not False for flag in prohibited_flags):
        raise ValueError("Prospect input contract contains prohibited model inputs")
    for key in ("historical", "historical_mlb_seasons", "current", "mlb_service"):
        if key not in contract:
            raise ValueError(f"Prospect input contract missing {key}")


def load_input_contract(path: Path = INPUT_PATH) -> dict:
    contract = json.loads(path.read_text(encoding="utf-8"))
    validate_input_contract(contract)
    return contract


def _sample(record: dict, role: str) -> float:
    key = "plate_appearances" if role == "hitter" else "innings_pitched"
    return _num(record.get(key)) or 0.0


def _rate_per(record: dict, numerator: str, sample: float, scale: float) -> float:
    value = _num(record.get(numerator))
    return value / sample * scale if value is not None and sample else 0.0


def _draft_features(record: dict) -> list[float]:
    import math

    known = 1.0 if record.get("draft_record_known") else 0.0
    drafted = 1.0 if record.get("rule4_drafted") else 0.0
    pick = _num(record.get("draft_pick_number"))
    bonus = _num(record.get("signing_bonus"))
    school_type = record.get("school_type")
    return [
        known,
        drafted,
        max(0.0, min(1.0, (621.0 - pick) / 620.0)) if pick else 0.0,
        math.log1p(max(0.0, bonus)) / math.log1p(10_000_000.0) if bonus else 0.0,
        1.0 if bonus is not None else 0.0,
        1.0 if school_type == "college" else 0.0,
        1.0 if school_type == "high_school" else 0.0,
    ]


def _canonical_feature_vector(record: dict, role: str) -> list[float] | None:
    level = str(record.get("level") or "").upper()
    age = _num(record.get("age"))
    if role not in CANONICAL_FEATURE_NAMES or level not in LEVEL_CODE or age is None:
        return None
    youth = EXPECTED_AGE[level] - age
    if role == "hitter":
        values = [
            _num(record.get("iso")),
            _num(record.get("k_pct")),
            _num(record.get("bb_pct")),
            _num(record.get("ops")),
            youth,
            LEVEL_CODE[level],
        ]
    else:
        values = [
            _num(record.get("k_per_9")),
            _num(record.get("bb_per_9")),
            _num(record.get("k_bb_pct")),
            _num(record.get("era")),
            _num(record.get("whip")),
            youth,
            LEVEL_CODE[level],
            1.0 if record.get("is_starter") else 0.0,
        ]
    return None if any(value is None for value in values) else [float(value) for value in values]


def _feature_vector(record: dict, role: str) -> list[float] | None:
    canonical = _canonical_feature_vector(record, role)
    if canonical is None:
        return None
    sample = _sample(record, role)
    import math

    if role == "hitter":
        extras = [
            _num(record.get("avg")) or 0.250,
            _num(record.get("obp")) or 0.320,
            _num(record.get("slg")) or max(0.0, (_num(record.get("ops")) or 0.720) - 0.320),
            _num(record.get("babip")) or 0.300,
            _rate_per(record, "home_runs", sample, 600.0),
            _rate_per(record, "stolen_bases", sample, 600.0),
            math.log1p(sample),
        ]
    else:
        games = _num(record.get("games_played")) or 0.0
        starts = _num(record.get("games_started")) or 0.0
        extras = [
            starts / games if games else (1.0 if record.get("is_starter") else 0.0),
            _rate_per(record, "hits", sample, 9.0),
            _rate_per(record, "home_runs", sample, 9.0),
            math.log1p(sample),
        ]
    return canonical + extras + _draft_features(record)


def _eligible_current(record: dict, role: str) -> bool:
    level = str(record.get("level") or "").upper()
    age = _num(record.get("age"))
    if level not in LEVEL_CODE or age is None or age > MAX_AGE:
        return False
    if role == "hitter" and str(record.get("position") or "").upper() == "P":
        return False
    return _sample(record, role) >= MIN_CURRENT_SAMPLE[role]


def _select_current_records(current: dict, role: str) -> list[dict]:
    group = "hitters" if role == "hitter" else "pitchers"
    by_player = {}
    for record in current.get(group, []):
        if not record.get("mlbam_id") or not _eligible_current(record, role):
            continue
        key = int(record["mlbam_id"])
        incumbent = by_player.get(key)
        if incumbent is None or _sample(record, role) > _sample(incumbent, role):
            by_player[key] = record
    return list(by_player.values())


def _regress_current_features(
    features: list[float], role_model: dict, role: str, sample: float
) -> tuple[list[float], float]:
    reliability = sample / (sample + SAMPLE_REGRESSION[role])
    out = list(features)
    for index, name in enumerate(FEATURE_NAMES[role]):
        if name in SHRINK_FEATURES[role]:
            center = float(role_model["means"][index])
            out[index] = center + reliability * (out[index] - center)
    return out, reliability


def _regress_canonical_features(
    features: list[float], target_model: dict, role: str, reliability: float
) -> list[float]:
    out = list(features)
    centers = target_model["_runtime"]["canonical_neighbors"]["means"]
    for index, name in enumerate(CANONICAL_FEATURE_NAMES[role]):
        if name in SHRINK_FEATURES[role]:
            out[index] = centers[index] + reliability * (out[index] - centers[index])
    return out

# Fixed transforms put unlike outcomes onto a stable [0, 1] training scale.
# They are units, not fantasy-category weights, and are not tuned per league.
TARGET_SPECS = {
    "hitter": {
        "established_probability": {
            "kind": "probability",
            "description": "Probability of any post-cohort MLB season with at least 300 PA",
            "unit": "probability",
        },
        "star_probability": {
            "kind": "probability",
            "description": (
                "Probability of any post-cohort MLB season with at least 450 PA "
                "and .800 OPS"
            ),
            "unit": "probability",
        },
        "regular_probability": {
            "kind": "probability",
            "description": "Probability of any post-cohort MLB season with at least 450 PA",
            "unit": "probability",
        },
        "representative_pa": {
            "kind": "conditional",
            "field": "pa",
            "offset": 0.0,
            "scale": 650.0,
            "unit": "PA",
        },
        "representative_avg": {
            "kind": "conditional",
            "field": "avg",
            "offset": 0.180,
            "scale": 0.180,
            "unit": "AVG",
        },
        "representative_ops": {
            "kind": "conditional",
            "field": "ops",
            "offset": 0.500,
            "scale": 0.500,
            "unit": "OPS",
        },
        "representative_hr_per_600": {
            "kind": "conditional",
            "derived": "hr_per_600",
            "offset": 0.0,
            "scale": 50.0,
            "unit": "HR/600 PA",
        },
        "representative_r_per_600": {
            "kind": "conditional",
            "derived": "r_per_600",
            "offset": 0.0,
            "scale": 150.0,
            "unit": "R/600 PA",
        },
        "representative_rbi_per_600": {
            "kind": "conditional",
            "derived": "rbi_per_600",
            "offset": 0.0,
            "scale": 160.0,
            "unit": "RBI/600 PA",
        },
        "representative_sb_per_600": {
            "kind": "conditional",
            "derived": "sb_per_600",
            "offset": 0.0,
            "scale": 50.0,
            "unit": "SB/600 PA",
        },
        "representative_k_pct": {
            "kind": "conditional",
            "derived": "k_pct",
            "offset": 0.0,
            "scale": 50.0,
            "unit": "K%",
        },
    },
    "pitcher": {
        "established_probability": {
            "kind": "probability",
            "description": "Probability of any post-cohort MLB season with at least 50 IP",
            "unit": "probability",
        },
        "star_probability": {
            "kind": "probability",
            "description": (
                "Probability of any post-cohort MLB season with at least 120 IP "
                "and a 3.75 ERA or better"
            ),
            "unit": "probability",
        },
        "rotation_probability": {
            "kind": "probability",
            "description": "Probability of any post-cohort MLB season with at least 120 IP",
            "unit": "probability",
        },
        "representative_ip": {
            "kind": "conditional",
            "field": "ip",
            "offset": 0.0,
            "scale": 200.0,
            "unit": "IP",
        },
        "representative_era": {
            "kind": "conditional",
            "field": "era",
            "offset": 0.0,
            "scale": 8.0,
            "unit": "ERA",
        },
        "representative_whip": {
            "kind": "conditional",
            "field": "whip",
            "offset": 0.0,
            "scale": 2.0,
            "unit": "WHIP",
        },
        "representative_k_per_9": {
            "kind": "conditional",
            "derived": "k_per_9",
            "offset": 0.0,
            "scale": 15.0,
            "unit": "K/9",
        },
        "representative_k_bb": {
            "kind": "conditional",
            "field": "k_bb",
            "offset": 0.0,
            "scale": 8.0,
            "unit": "K:BB",
        },
        "representative_qs_per_180": {
            "kind": "conditional",
            "derived": "qs_per_180",
            "offset": 0.0,
            "scale": 40.0,
            "unit": "QS/180 IP",
        },
        "representative_sv_hld_per_60": {
            "kind": "conditional",
            "derived": "sv_hld_per_60",
            "offset": 0.0,
            "scale": 80.0,
            "unit": "SV+HLD/60 IP",
        },
        "representative_l_per_180": {
            "kind": "conditional",
            "derived": "l_per_180",
            "offset": 0.0,
            "scale": 30.0,
            "unit": "L/180 IP",
        },
    },
}


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _transform(value: float, spec: dict) -> float:
    if spec["kind"] == "probability":
        return _clamp(value)
    return _clamp((value - spec["offset"]) / spec["scale"])


def _inverse_transform(value: float, spec: dict) -> float:
    if spec["kind"] == "probability":
        return _clamp(value)
    return spec["offset"] + _clamp(value) * spec["scale"]


def _base_historical_rows(
    rows: list[dict], role: str, mature_through: int = MATURE_THROUGH
) -> list[dict]:
    eligible = []
    for record in rows:
        if record.get("role") != role:
            continue
        if int(record.get("cohort_year") or 9999) > mature_through:
            continue
        if not record.get("mlbam_id") or (_num(record.get("age")) or 99) > MAX_AGE:
            continue
        features = _feature_vector(record, role)
        baseline_features = _canonical_feature_vector(record, role)
        if features is None or baseline_features is None:
            continue
        eligible.append(
            {
                "mlbam_id": int(record["mlbam_id"]),
                "cohort_year": int(record["cohort_year"]),
                "level": str(record.get("level") or "").upper(),
                "age": int(record.get("age") or 0),
                "features": features,
                "baseline_features": baseline_features,
            }
        )
    eligible.sort(
        key=lambda row: (row["cohort_year"], -LEVEL_CODE[row["level"]], row["mlbam_id"])
    )
    by_player = {}
    for row in eligible:
        by_player.setdefault(row["mlbam_id"], row)
    return sorted(by_player.values(), key=lambda row: (row["cohort_year"], row["mlbam_id"]))


def _future_seasons(row: dict, role: str, seasons_by_player: dict) -> list[dict]:
    key = f"{row['mlbam_id']}_{role}"
    return [
        season
        for season in seasons_by_player.get(key, [])
        if int(season.get("year") or 0) > row["cohort_year"]
    ]


def _representative_season(
    row: dict, role: str, seasons_by_player: dict
) -> dict | None:
    """Choose the highest-volume future season without optimizing any category."""
    sample_key = "pa" if role == "hitter" else "ip"
    seasons = _future_seasons(row, role, seasons_by_player)
    return max(
        seasons,
        key=lambda season: (_num(season.get(sample_key)) or 0.0, -int(season.get("year") or 0)),
        default=None,
    )


def _raw_target(row: dict, role: str, target_name: str, seasons_by_player: dict):
    seasons = _future_seasons(row, role, seasons_by_player)
    sample_key = "pa" if role == "hitter" else "ip"
    if target_name == "established_probability":
        threshold = ROLE_THRESHOLDS[role]["established"]
        return float(any((_num(season.get(sample_key)) or 0.0) >= threshold for season in seasons))
    if target_name == "star_probability":
        if role == "hitter":
            return float(
                any(
                    (_num(season.get("pa")) or 0.0) >= STAR_THRESHOLDS[role]["pa"]
                    and (_num(season.get("ops")) or 0.0)
                    >= STAR_THRESHOLDS[role]["ops"]
                    for season in seasons
                )
            )
        return float(
            any(
                (_num(season.get("ip")) or 0.0) >= STAR_THRESHOLDS[role]["ip"]
                and _num(season.get("era")) is not None
                and _num(season.get("era")) <= STAR_THRESHOLDS[role]["era"]
                for season in seasons
            )
        )
    if target_name == "regular_probability":
        threshold = ROLE_THRESHOLDS["hitter"]["regular"]
        return float(any((_num(season.get("pa")) or 0.0) >= threshold for season in seasons))
    if target_name == "rotation_probability":
        threshold = ROLE_THRESHOLDS["pitcher"]["rotation"]
        return float(any((_num(season.get("ip")) or 0.0) >= threshold for season in seasons))

    season = _representative_season(row, role, seasons_by_player)
    if season is None:
        return None
    sample = _num(season.get(sample_key)) or 0.0
    if sample < ROLE_THRESHOLDS[role]["established"]:
        return None
    spec = TARGET_SPECS[role][target_name]
    if spec.get("field"):
        return _num(season.get(spec["field"]))
    if spec.get("derived") == "hr_per_600":
        value = _num(season.get("hr"))
        return None if value is None or not sample else value / sample * 600.0
    if spec.get("derived") == "r_per_600":
        value = _num(season.get("r"))
        return None if value is None or not sample else value / sample * 600.0
    if spec.get("derived") == "rbi_per_600":
        value = _num(season.get("rbi"))
        return None if value is None or not sample else value / sample * 600.0
    if spec.get("derived") == "sb_per_600":
        value = _num(season.get("sb"))
        return None if value is None or not sample else value / sample * 600.0
    if spec.get("derived") == "k_pct":
        value = _num(season.get("so"))
        return None if value is None or not sample else value / sample * 100.0
    if spec.get("derived") == "k_per_9":
        value = _num(season.get("so"))
        return None if value is None or not sample else value / sample * 9.0
    if spec.get("derived") == "qs_per_180":
        value = _num(season.get("qs"))
        return None if value is None or not sample else value / sample * 180.0
    if spec.get("derived") == "sv_hld_per_60":
        saves = _num(season.get("sv"))
        holds = _num(season.get("hld"))
        if saves is None and holds is None:
            return None
        return None if not sample else ((saves or 0.0) + (holds or 0.0)) / sample * 60.0
    if spec.get("derived") == "l_per_180":
        value = _num(season.get("l"))
        return None if value is None or not sample else value / sample * 180.0
    raise ValueError(f"Unsupported universal target {target_name}")


def _target_rows(
    dataset_rows: list[dict],
    seasons_by_player: dict,
    role: str,
    target_name: str,
    mature_through: int = MATURE_THROUGH,
) -> list[dict]:
    spec = TARGET_SPECS[role][target_name]
    out = []
    for row in _base_historical_rows(dataset_rows, role, mature_through):
        raw_target = _raw_target(row, role, target_name, seasons_by_player)
        if raw_target is None:
            continue
        out.append({**row, "target": _transform(raw_target, spec)})
    return out


def _rounded_ridge(model: dict) -> dict:
    return {
        "weights": [round(value, 8) for value in model["weights"]],
        "means": [round(value, 8) for value in model["means"]],
        "stds": [round(value, 8) for value in model["stds"]],
    }


def _validation_score(predictions: list[float], targets: list[float], kind: str):
    if not targets:
        return None
    if kind == "probability":
        return mean((prediction - target) ** 2 for prediction, target in zip(predictions, targets))
    return mean(abs(prediction - target) for prediction, target in zip(predictions, targets))


def train_target(
    role: str,
    target_name: str,
    dataset_rows: list[dict],
    seasons_by_player: dict,
    now: str | None = None,
) -> dict:
    rows = _target_rows(dataset_rows, seasons_by_player, role, target_name)
    validation = _walk_forward(rows, ridge_lambda=RIDGE_LAMBDA)
    spec = TARGET_SPECS[role][target_name]
    metric_name = "brier_score" if spec["kind"] == "probability" else "mae"
    scores = {
        "model": _validation_score(
            validation["model_predictions"], validation["targets"], spec["kind"]
        ),
        "level_age_prior": _validation_score(
            validation["prior_predictions"], validation["targets"], spec["kind"]
        ),
        "historical_neighbors_25": _validation_score(
            validation["neighbor_predictions"], validation["targets"], spec["kind"]
        ),
        "canonical_historical_neighbors_25": _validation_score(
            validation["canonical_neighbor_predictions"],
            validation["targets"],
            spec["kind"],
        ),
    }
    rank_concordance_by_source = {
        "ridge": _rank_concordance(
            validation["model_predictions"], validation["targets"]
        ),
        "level_age_prior": _rank_concordance(
            validation["prior_predictions"], validation["targets"]
        ),
        "historical_neighbors_25": _rank_concordance(
            validation["neighbor_predictions"], validation["targets"]
        ),
        "canonical_historical_neighbors_25": _rank_concordance(
            validation["canonical_neighbor_predictions"], validation["targets"]
        ),
    }
    now = now or datetime.now(timezone.utc).isoformat()
    gate = decide_gate(
        metric=f"{target_name}_{metric_name}",
        model_score=scores["model"],
        baselines={
            "level_age_prior": scores["level_age_prior"],
            "historical_neighbors_25": scores["historical_neighbors_25"],
            "canonical_historical_neighbors_25": scores[
                "canonical_historical_neighbors_25"
            ],
        },
        sample_size=len(validation["targets"]),
        cv_method="walk_forward",
        validated_through=str(MATURE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=True,
        now=now,
    )
    model = _fit_ridge(rows, RIDGE_LAMBDA)
    neighbors = _fit_neighbors(rows)
    canonical_neighbors = _fit_neighbors(
        [{**row, "features": row["baseline_features"]} for row in rows]
    )
    if model is None or neighbors is None or canonical_neighbors is None:
        raise ValueError(f"Could not fit {role} {target_name} from {len(rows)} rows")
    prior = _fit_prior(rows)
    source = "ridge" if gate["status"] == "active" else gate["baseline"]
    return {
        "target": target_name,
        "kind": spec["kind"],
        "unit": spec["unit"],
        "transform": (
            {"kind": "identity_clamped_0_1"}
            if spec["kind"] == "probability"
            else {
                "kind": "fixed_linear_clamped_0_1",
                "offset": spec["offset"],
                "scale": spec["scale"],
            }
        ),
        "conditional_on": (
            f"representative season has at least {int(ROLE_THRESHOLDS[role]['established'])} "
            f"{'PA' if role == 'hitter' else 'IP'}"
            if spec["kind"] == "conditional"
            else None
        ),
        "ridge_lambda": RIDGE_LAMBDA,
        "feature_names": list(FEATURE_NAMES[role]),
        "model": _rounded_ridge(model),
        "training_sample": len(rows),
        "validation_sample": len(validation["targets"]),
        "validation_metric": metric_name,
        "model_validation_score": round(scores["model"], 6) if scores["model"] is not None else None,
        "prior_validation_score": (
            round(scores["level_age_prior"], 6)
            if scores["level_age_prior"] is not None
            else None
        ),
        "neighbor_validation_score": (
            round(scores["historical_neighbors_25"], 6)
            if scores["historical_neighbors_25"] is not None
            else None
        ),
        "canonical_neighbor_validation_score": (
            round(scores["canonical_historical_neighbors_25"], 6)
            if scores["canonical_historical_neighbors_25"] is not None
            else None
        ),
        "model_mae": round(validation["model_mae"], 6) if validation["model_mae"] is not None else None,
        "prior_mae": round(validation["prior_mae"], 6) if validation["prior_mae"] is not None else None,
        "neighbor_mae": round(validation["neighbor_mae"], 6) if validation["neighbor_mae"] is not None else None,
        "canonical_neighbor_mae": (
            round(validation["canonical_neighbor_mae"], 6)
            if validation["canonical_neighbor_mae"] is not None
            else None
        ),
        "rank_concordance": (
            round(validation["rank_concordance"], 6)
            if validation["rank_concordance"] is not None
            else None
        ),
        "rank_concordance_by_source": {
            name: round(value, 6) if value is not None else None
            for name, value in rank_concordance_by_source.items()
        },
        "gate": gate,
        "prediction_source": source,
        "_runtime": {
            "model": model,
            "prior": prior,
            "neighbors": neighbors,
            "canonical_neighbors": canonical_neighbors,
        },
    }


def _selected_prediction(
    target_model: dict,
    row: dict,
    features: list[float],
    baseline_features: list[float],
) -> tuple[float, str]:
    runtime = target_model["_runtime"]
    predictions = {
        "ridge": _predict(runtime["model"], features),
        "level_age_prior": _prior_predict(runtime["prior"], row),
        "historical_neighbors_25": _neighbor_predict(runtime["neighbors"], features),
        "canonical_historical_neighbors_25": _neighbor_predict(
            runtime["canonical_neighbors"], baseline_features
        ),
    }
    source = target_model["prediction_source"]
    if source not in predictions:
        source = "level_age_prior"
    return predictions[source], source


def _coherent_outcome_distribution(outcomes: dict) -> dict:
    established = _clamp(
        float(outcomes["established_probability"]["prediction"])
    )
    star = min(
        established,
        _clamp(float(outcomes["star_probability"]["prediction"])),
    )
    outcomes["star_probability"]["prediction"] = round(star, 4)
    return {
        "bust_probability": round(1.0 - established, 4),
        "role_probability": round(established - star, 4),
        "star_probability": round(star, 4),
    }


def score_current(contract: dict, role_targets: dict) -> list[dict]:
    service = _service_index(contract)
    profiles = []
    for role in ("hitter", "pitcher"):
        targets = role_targets[role]
        for record in _select_current_records(contract["current"], role):
            service_fact = service.get((int(record["mlbam_id"]), role))
            if service_fact is None or service_fact.get("graduated"):
                continue
            raw = _feature_vector(record, role)
            canonical = _canonical_feature_vector(record, role)
            if raw is None or canonical is None:
                continue
            sample_key = "plate_appearances" if role == "hitter" else "innings_pitched"
            sample = _num(record.get(sample_key)) or 0.0
            outcomes = {}
            reliability = None
            for target_name, target_model in targets.items():
                regressed, target_reliability = _regress_current_features(
                    raw, target_model["model"], role, sample
                )
                regressed_canonical = _regress_canonical_features(
                    canonical, target_model, role, target_reliability
                )
                reliability = target_reliability if reliability is None else reliability
                normalized, source = _selected_prediction(
                    target_model,
                    {
                        "level": str(record.get("level") or "").upper(),
                        "age": int(record.get("age") or 0),
                    },
                    regressed,
                    regressed_canonical,
                )
                spec = TARGET_SPECS[role][target_name]
                raw_prediction = _inverse_transform(normalized, spec)
                digits = 4 if spec["unit"] in {"probability", "AVG", "OPS", "ERA", "WHIP", "K:BB"} else 2
                outcomes[target_name] = {
                    "prediction": round(raw_prediction, digits),
                    "unit": spec["unit"],
                    "conditional_on": target_model["conditional_on"],
                    "prediction_source": source,
                    "gate_status": target_model["gate"]["status"],
                }
            outcome_distribution = _coherent_outcome_distribution(outcomes)
            profiles.append(
                {
                    "mlbam_id": int(record["mlbam_id"]),
                    "name": record.get("name"),
                    "normalized_name": record.get("normalized_name"),
                    "role": role,
                    "position": record.get("position"),
                    "team": record.get("team"),
                    "age": record.get("age"),
                    "level": record.get("level"),
                    "sample": round(sample, 1),
                    "sample_unit": "PA" if role == "hitter" else "IP",
                    "sample_reliability": round(reliability, 3),
                    "outcomes": outcomes,
                    "outcome_distribution": outcome_distribution,
                }
            )
    return sorted(profiles, key=lambda row: (row["role"], row["mlbam_id"]))


def _target_contract() -> dict:
    return {
        "kind": "factual_future_mlb_outcome_profile",
        "rank_free": True,
        "league_scoring_independent": True,
        "representative_season": (
            "highest-volume post-cohort MLB season; never selected by fantasy category"
        ),
        "conditional_targets": (
            "trained only when the representative season reaches the role's "
            "established threshold"
        ),
        "outcome_distribution": (
            "bust = 1 - established; star is a factual volume/production "
            "probability capped at established; role is the remainder"
        ),
        "validation": "player-grouped expanding-window",
        "mature_through": MATURE_THROUGH,
        "role_thresholds": ROLE_THRESHOLDS,
        "feature_spaces": {
            role: {
                "expanded": list(FEATURE_NAMES[role]),
                "canonical_baseline": list(CANONICAL_FEATURE_NAMES[role]),
            }
            for role in ("hitter", "pitcher")
        },
        "targets": {
            role: {
                name: {
                    key: value
                    for key, value in spec.items()
                    if key
                    in {
                        "kind",
                        "description",
                        "unit",
                        "field",
                        "derived",
                        "offset",
                        "scale",
                    }
                }
                for name, spec in targets.items()
            }
            for role, targets in TARGET_SPECS.items()
        },
    }


def build_shadow_model(contract: dict, now: str | None = None) -> dict:
    validate_input_contract(contract)
    now = now or datetime.now(timezone.utc).isoformat()
    dataset_rows = contract["historical"].get("rows", [])
    seasons_by_player = contract["historical_mlb_seasons"]
    role_targets = {
        role: {
            target_name: train_target(
                role, target_name, dataset_rows, seasons_by_player, now
            )
            for target_name in TARGET_SPECS[role]
        }
        for role in ("hitter", "pitcher")
    }
    profiles = score_current(contract, role_targets)
    target_status_counts = {
        "active": 0,
        "fallback": 0,
        "failed": 0,
        "insufficient_sample": 0,
    }
    for targets in role_targets.values():
        for model in targets.values():
            status = model["gate"]["status"]
            target_status_counts[status] = target_status_counts.get(status, 0) + 1
            model.pop("_runtime", None)
    return {
        "status": MODEL_STATUS,
        "research_status": "mixed_evidence",
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "input_contract": {
            "schema_version": contract["schema_version"],
            "generated_at": contract.get("generated_at"),
            "source_policy": contract["source_policy"],
        },
        "target_contract": _target_contract(),
        "scope": "A/A+/AA/AAA statistical prospects only",
        "target_status_counts": target_status_counts,
        "roles": role_targets,
        "candidate_count": len(profiles),
        "profiles": profiles,
        "limitations": [
            "Shadow-only; never consumed by the live prospect board.",
            "Produces factual outcome profiles, not a universal rank or fantasy value.",
            "Complex-league and rookie-ball prospects remain outside the statistical scope.",
            "Draft/signing facts are Rule 4 only; international amateur investment is absent.",
            "No defensive, physical, or scouting-report inputs.",
            "Conditional production targets currently have limited mature held-out samples.",
            "A later league adapter must map these outcomes into league-specific values.",
        ],
    }


def _stable_gate(gate: dict) -> dict:
    return {key: value for key, value in gate.items() if key != "activated_at"}


def archive_predictions(
    payload: dict, date_str: str | None = None, archive_dir: Path = ARCHIVE_DIR
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_str = date_str or datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "model_version": payload["model_version"],
        "research_status": payload["research_status"],
        "target_status_counts": payload["target_status_counts"],
        "roles": {
            role: {
                name: {
                    "gate": _stable_gate(target["gate"]),
                    "prediction_source": target["prediction_source"],
                    "training_sample": target["training_sample"],
                    "validation_sample": target["validation_sample"],
                    "validation_metric": target["validation_metric"],
                    "model_validation_score": target["model_validation_score"],
                    "prior_validation_score": target["prior_validation_score"],
                    "neighbor_validation_score": target["neighbor_validation_score"],
                    "canonical_neighbor_validation_score": target[
                        "canonical_neighbor_validation_score"
                    ],
                    "rank_concordance_by_source": target[
                        "rank_concordance_by_source"
                    ],
                    "model_mae": target["model_mae"],
                    "prior_mae": target["prior_mae"],
                    "neighbor_mae": target["neighbor_mae"],
                    "canonical_neighbor_mae": target["canonical_neighbor_mae"],
                }
                for name, target in targets.items()
            }
            for role, targets in payload["roles"].items()
        },
        "candidate_count": payload["candidate_count"],
        "profiles": payload["profiles"],
    }
    text = json.dumps(archive, sort_keys=True, separators=(",", ":"))
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return path, False
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path, True


def write_artifact(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def run_model(
    input_path: Path = INPUT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    now: str | None = None,
) -> dict:
    effective_now = now or datetime.now(timezone.utc).isoformat()
    payload = build_shadow_model(load_input_contract(input_path), now=effective_now)
    path = write_artifact(payload, artifact_path)
    parsed_now = datetime.fromisoformat(effective_now.replace("Z", "+00:00"))
    if parsed_now.tzinfo is None:
        parsed_now = parsed_now.replace(tzinfo=timezone.utc)
    archive_date = parsed_now.date().isoformat()
    archive_path, archive_changed = archive_predictions(
        payload, date_str=archive_date, archive_dir=archive_dir
    )
    return {
        "artifact_path": str(path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "research_status": payload["research_status"],
        "target_status_counts": payload["target_status_counts"],
        "candidates": payload["candidate_count"],
    }
