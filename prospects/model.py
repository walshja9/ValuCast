"""ValuCast Prospect Model, trained only from the factual ValuCast input contract.

This model is observe-only. It cannot alter the live prospect board until its
coverage, target, and out-of-sample gates earn a separate promotion decision.
"""
from __future__ import annotations

import copy
import json
import math
import os
from bisect import bisect_right
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev
from zoneinfo import ZoneInfo

from prospects.gate import decide_gate
from prospects.input_contract import VALUCAST_INPUT_PATH, validate_factual_contract

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = VALUCAST_INPUT_PATH
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_model.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_prospect_model"

MODEL_NAME = "ValuCast Prospect Model"
MODEL_VERSION = "0.6.1"  # 0.6.1: stale-current comparator adjusts served scores
MODEL_STATUS = "shadow_only"
POOLED_SHADOW_ENABLED = os.environ.get("VALUCAST_POOLED_SHADOW", "1") != "0"
POOLED_SHADOW_VERSION = "0.1.0"
POOLED_SHADOW_USAGE = "pooled_line_shadow_observe_only_not_live_score_or_value"
MATURE_THROUGH = 2019
MAX_AGE = 25
MIN_CURRENT_SAMPLE = {"hitter": 50.0, "pitcher": 15.0}
SAMPLE_REGRESSION = {"hitter": 200.0, "pitcher": 50.0}
# Level vocabulary for stat-based scoring. A/A+ were added so the model scores
# lower-minors prospects on their current line instead of falling back to
# pedigree (which mechanically forced low confidence). Codes preserve the
# existing AA/AAA feature values and keep strict level ordering A < A+ < AA <
# AAA (the historical de-dupe keeps each player's highest level). EXPECTED_AGE
# encodes the on-track prospect age per level (~2y below the population median),
# matching the existing AA/AAA convention.
LEVEL_CODE = {"A": -2.0, "A+": -1.0, "AA": 0.0, "AAA": 1.0}
EXPECTED_AGE = {"A": 20.0, "A+": 21.0, "AA": 22.5, "AAA": 24.0}
OUTCOME_TARGET = {"bust": 0.0, "role": 0.5, "star": 1.0}
MIN_GATE_SAMPLE = 250
MIN_GATE_IMPROVEMENT_PCT = 2.0
RIDGE_LAMBDA = 10.0
HITTER_IMPACT_RIDGE_LAMBDA = 3.0
PRIOR_K = 40.0
NEIGHBOR_K = 25

FEATURE_NAMES = {
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
OUTCOME_FEATURE_NAMES = {
    "hitter": FEATURE_NAMES["hitter"]
    + (
        "avg",
        "obp",
        "slg",
        "babip",
        "hr_per_600_pa",
        "sb_per_600_pa",
        "bb_minus_k_pct",
        "bb_to_k_ratio",
        "log_pa",
        "iso_x_youth",
        "ops_x_youth",
        "discipline_x_youth",
        "iso_x_ops",
        "iso_x_discipline",
        "ops_x_discipline",
        "iso_x_level",
        "ops_x_level",
        "k_pct_x_level",
        "bb_pct_x_level",
    ),
    "pitcher": FEATURE_NAMES["pitcher"]
    + (
        "k_to_bb_per_9",
        "hr_per_9",
        "h_per_9",
        "walks_per_9_raw",
        "start_rate",
        "log_ip",
        "batters_faced_per_ip",
        "k_bb_pct_x_youth",
        "era_x_youth",
        "whip_x_youth",
        "starter_x_youth",
        "era_x_whip",
        "k_per_9_x_level",
        "bb_per_9_x_level",
        "k_bb_pct_x_level",
        "era_x_level",
        "whip_x_level",
        "rule4_drafted",
        "draft_record_known",
        "pick_value",
        "inverse_draft_pick",
        "inverse_draft_round",
        "log_signing_bonus",
        "college_drafted",
        "prep_drafted",
        "bats_left",
        "bats_switch",
        "throws_left",
    ),
}
OUTCOME_MODEL_KIND = {"hitter": "hurdle_ridge", "pitcher": "hurdle_ridge"}
# The fantasy-impact axis shares the rich factual feature vector with the
# outcome axis (OUTCOME_FEATURE_NAMES). Both axes are best predicted from the
# same minor-league line + pedigree signal; only the regression target differs.
# The simple fixed-interaction vector below is retained solely as the canonical
# kNN baseline the impact gate must beat.
IMPACT_DRIVER_GROUPS = {
    "hitter": {
        "aaa_translation": (
            "level",
            "iso_x_level",
            "ops_x_level",
            "k_pct_x_level",
            "bb_pct_x_level",
        ),
    },
    "pitcher": {},
}
IMPACT_CATEGORIES = {
    "hitter": ("r", "hr", "rbi", "sb", "avg", "ops", "so"),
    "pitcher": ("so", "qs", "sv_hld", "era", "whip", "k_bb", "l"),
}
IMPACT_CATEGORY_GROUPS = {
    "hitter": {
        "hitter": IMPACT_CATEGORIES["hitter"],
    },
    "pitcher": {
        "starter": ("so", "qs", "era", "whip", "k_bb", "l"),
        "reliever": ("so", "sv_hld", "era", "whip", "k_bb", "l"),
    },
}
IMPACT_INVERSE_CATEGORIES = {
    "hitter": {"so"},
    "pitcher": {"era", "whip", "l"},
}
IMPACT_CATEGORY_COVERAGE = 0.80
IMPACT_REFERENCE_MIN = {"hitter": 150.0, "pitcher": 20.0}
IMPACT_TARGET_MIN = {"hitter": 50.0, "pitcher": 10.0}
SHRINK_FEATURES = {
    "hitter": {"iso", "k_pct", "bb_pct", "ops"},
    "pitcher": {"k_per_9", "bb_per_9", "k_bb_pct", "era", "whip"},
}
# Structural, sample-independent facts: age, level, sample-size proxies, role,
# and draft pedigree. Every OTHER feature in the (rich) scoring vector is
# performance-derived and MUST be shrunk toward the model mean by current-sample
# reliability — otherwise a small-sample rate/discipline outlier (e.g. an extreme
# BB/K in 50 PA at A-ball) sails into the model unregressed and saturates the
# score. Shrink-by-default; only these names are held fixed.
NON_SHRINK_FEATURES = {
    "youth",
    "level",
    "log_pa",
    "log_ip",
    "is_starter",
    "start_rate",
    "starter_x_youth",
    "rule4_drafted",
    "draft_record_known",
    "pick_value",
    "inverse_draft_pick",
    "inverse_draft_round",
    "log_signing_bonus",
    "college_drafted",
    "prep_drafted",
    "bats_left",
    "bats_switch",
    "throws_left",
}


def validate_input_contract(contract: dict) -> None:
    problems = validate_factual_contract(contract)
    if problems:
        raise ValueError("Invalid prospect input contract: " + "; ".join(problems))
    for key in ("historical_mlb_seasons",):
        if key not in contract:
            raise ValueError(f"Prospect input contract missing {key}")


def load_input_contract(path: Path = INPUT_PATH) -> dict:
    contract = json.loads(path.read_text(encoding="utf-8"))
    validate_input_contract(contract)
    return contract


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _zero_num(value) -> float:
    return float(_num(value) or 0.0)


def _safe_ratio(numerator, denominator, default: float = 0.0) -> float:
    denominator = _num(denominator)
    if not denominator:
        return default
    return float(_num(numerator) or 0.0) / denominator


def _safe_log1p(value) -> float:
    value = _num(value) or 0.0
    if value <= 0:
        return 0.0
    return float(math.log1p(value))


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _sample(record: dict, role: str) -> float:
    key = "plate_appearances" if role == "hitter" else "innings_pitched"
    return _num(record.get(key)) or 0.0


def _age_bucket(age) -> str:
    age = int(age or 0)
    if age <= 20:
        return "<=20"
    if age <= 22:
        return str(age)
    return "23+"


def _feature_vector(record: dict, role: str) -> list[float] | None:
    level = str(record.get("level") or "").upper()
    age = _num(record.get("age"))
    if role not in FEATURE_NAMES or level not in LEVEL_CODE or age is None:
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
    return None if any(value is None for value in values) else [float(v) for v in values]


def _outcome_feature_vector(record: dict, role: str) -> list[float] | None:
    base = _feature_vector(record, role)
    if base is None:
        return None
    if role == "hitter":
        iso, strikeout_pct, walk_pct, ops, youth, level = base
        plate_appearances = _sample(record, role)
        discipline = walk_pct - strikeout_pct
        extra = [
            _zero_num(record.get("avg")),
            _zero_num(record.get("obp")),
            _zero_num(record.get("slg")),
            _zero_num(record.get("babip")),
            _safe_ratio(record.get("home_runs", record.get("hr")), plate_appearances, 0.0) * 600.0,
            _safe_ratio(record.get("stolen_bases", record.get("sb")), plate_appearances, 0.0) * 600.0,
            discipline,
            walk_pct / (strikeout_pct + 1.0),
            _safe_log1p(plate_appearances),
            iso * youth,
            ops * youth,
            discipline * youth,
            iso * ops,
            iso * discipline,
            ops * discipline,
            iso * level,
            ops * level,
            strikeout_pct * level,
            walk_pct * level,
        ]
    else:
        k_per_9, bb_per_9, k_bb_pct, era, whip, youth, level, is_starter = base
        innings = _sample(record, role)
        draft_pick = _zero_num(record.get("draft_pick_number"))
        draft_round = _zero_num(record.get("draft_round"))
        bonus = _zero_num(record.get("signing_bonus"))
        school_type = str(record.get("school_type") or "").strip().lower()
        bats = str(record.get("bats") or record.get("bat_side") or "").strip().upper()
        throws = (
            str(record.get("throws") or record.get("throwing_hand") or "")
            .strip()
            .upper()
        )
        extra = [
            k_per_9 / (bb_per_9 + 1.0),
            _safe_ratio(record.get("home_runs"), innings, 0.0) * 9.0,
            _safe_ratio(record.get("hits"), innings, 0.0) * 9.0,
            _safe_ratio(record.get("walks"), innings, 0.0) * 9.0,
            _safe_ratio(record.get("games_started"), record.get("games", record.get("games_played")), is_starter),
            _safe_log1p(innings),
            _safe_ratio(record.get("batters_faced"), innings, 0.0),
            k_bb_pct * youth,
            era * youth,
            whip * youth,
            is_starter * youth,
            era * whip,
            k_per_9 * level,
            bb_per_9 * level,
            k_bb_pct * level,
            era * level,
            whip * level,
            1.0 if _truthy(record.get("rule4_drafted")) else 0.0,
            1.0 if _truthy(record.get("draft_record_known")) else 0.0,
            _zero_num(record.get("pick_value")),
            1.0 / (draft_pick or 999.0),
            1.0 / (draft_round or 99.0),
            _safe_log1p(bonus),
            1.0 if school_type == "college" else 0.0,
            1.0 if school_type in ("prep", "high_school", "highschool", "hs") else 0.0,
            1.0 if bats == "L" else 0.0,
            1.0 if bats == "S" else 0.0,
            1.0 if throws == "L" else 0.0,
        ]
    return [float(value) for value in base + extra]


def _canonical_impact_feature_vector(base: list[float], role: str) -> list[float]:
    """Original fixed interaction layer retained as the canonical neighbor baseline."""
    if role == "hitter":
        iso, strikeout_pct, walk_pct, ops, youth, _level = base
        extra = [
            iso * youth,
            ops * youth,
            (walk_pct - strikeout_pct) * youth,
            iso * ops,
        ]
    else:
        k_per_9, bb_per_9, k_bb_pct, era, whip, youth, _level, is_starter = base
        extra = [
            k_per_9 / (bb_per_9 + 1.0),
            k_bb_pct * youth,
            era * youth,
            whip * youth,
            is_starter * youth,
            era * whip,
        ]
    return base + extra


def _category_value(season: dict, category: str) -> float | None:
    """Return a canonical league-category value from factual season fields."""
    if category == "sv_hld":
        saves = _num(season.get("sv"))
        holds = _num(season.get("hld"))
        return None if saves is None or holds is None else saves + holds
    return _num(season.get(category))


def _impact_references(seasons_by_player: dict) -> dict:
    references = {
        role: {category: [] for category in IMPACT_CATEGORIES[role]}
        for role in ("hitter", "pitcher")
    }
    for key, seasons in seasons_by_player.items():
        if key.endswith("_hitter"):
            role, sample_key = "hitter", "pa"
        elif key.endswith("_pitcher"):
            role, sample_key = "pitcher", "ip"
        else:
            continue
        for season in seasons:
            if (_num(season.get(sample_key)) or 0.0) < IMPACT_REFERENCE_MIN[role]:
                continue
            for category in IMPACT_CATEGORIES[role]:
                value = _category_value(season, category)
                if value is not None:
                    references[role][category].append(value)
    for role in references:
        for category in references[role]:
            references[role][category].sort()
    return references


def _active_impact_categories(references: dict, role: str) -> tuple[str, ...]:
    """Use only canonical categories with coverage comparable to the best field."""
    counts = {
        category: len(references[role][category])
        for category in IMPACT_CATEGORIES[role]
    }
    max_count = max(counts.values(), default=0)
    if not max_count:
        return ()
    return tuple(
        category
        for category in IMPACT_CATEGORIES[role]
        if counts[category] >= max_count * IMPACT_CATEGORY_COVERAGE
    )


def _percentile(values: list[float], value: float, inverse: bool = False) -> float:
    if not values:
        return 0.0
    percentile = bisect_right(values, value) / len(values)
    return 1.0 - percentile if inverse else percentile


def _impact_target(
    record: dict,
    role: str,
    seasons_by_player: dict,
    references: dict,
) -> float:
    """Best post-cohort season across the factual categories currently available."""
    key = f"{record['mlbam_id']}_{role}"
    sample_key = "pa" if role == "hitter" else "ip"
    active_categories = _active_impact_categories(references, role)
    if not active_categories:
        return 0.0
    scores = []
    for season in seasons_by_player.get(key, []):
        if int(season.get("year") or 0) <= int(record["cohort_year"]):
            continue
        if (_num(season.get(sample_key)) or 0.0) < IMPACT_TARGET_MIN[role]:
            continue
        group_scores = []
        for group_categories in IMPACT_CATEGORY_GROUPS[role].values():
            categories = [
                category
                for category in group_categories
                if category in active_categories
            ]
            category_scores = []
            for category in categories:
                value = _category_value(season, category)
                if value is None:
                    continue
                category_scores.append(
                    _percentile(
                        references[role][category],
                        value,
                        inverse=category in IMPACT_INVERSE_CATEGORIES[role],
                    )
                )
            if categories and len(category_scores) == len(categories):
                group_scores.append(mean(category_scores))
        if group_scores:
            scores.append(max(group_scores))
    return max(scores, default=0.0)


def _historical_rows(
    rows: list[dict], role: str, mature_through: int = MATURE_THROUGH
) -> list[dict]:
    eligible = []
    for record in rows:
        if record.get("role") != role:
            continue
        if int(record.get("cohort_year") or 9999) > mature_through:
            continue
        if record.get("outcome") not in OUTCOME_TARGET:
            continue
        if not record.get("mlbam_id") or (_num(record.get("age")) or 99) > MAX_AGE:
            continue
        baseline_features = _feature_vector(record, role)
        features = _outcome_feature_vector(record, role)
        if baseline_features is None or features is None:
            continue
        eligible.append(
            {
                "mlbam_id": int(record["mlbam_id"]),
                "cohort_year": int(record["cohort_year"]),
                "level": str(record.get("level") or "").upper(),
                "age": int(record.get("age") or 0),
                "features": features,
                "baseline_features": baseline_features,
                "target": OUTCOME_TARGET[record["outcome"]],
            }
        )
    eligible.sort(
        key=lambda row: (row["cohort_year"], -LEVEL_CODE[row["level"]], row["mlbam_id"])
    )
    by_player = {}
    for row in eligible:
        by_player.setdefault(row["mlbam_id"], row)
    return sorted(by_player.values(), key=lambda row: (row["cohort_year"], row["mlbam_id"]))


def _historical_impact_rows(
    rows: list[dict],
    role: str,
    seasons_by_player: dict,
    references: dict,
    mature_through: int = MATURE_THROUGH,
) -> list[dict]:
    eligible = []
    for record in rows:
        if record.get("role") != role:
            continue
        if int(record.get("cohort_year") or 9999) > mature_through:
            continue
        if not record.get("mlbam_id") or (_num(record.get("age")) or 99) > MAX_AGE:
            continue
        base = _feature_vector(record, role)
        outcome_features = _outcome_feature_vector(record, role)
        if base is None or outcome_features is None:
            continue
        eligible.append(
            {
                "mlbam_id": int(record["mlbam_id"]),
                "cohort_year": int(record["cohort_year"]),
                "level": str(record.get("level") or "").upper(),
                "age": int(record.get("age") or 0),
                "features": outcome_features,
                "baseline_features": _canonical_impact_feature_vector(base, role),
                "target": _impact_target(record, role, seasons_by_player, references),
            }
        )
    eligible.sort(
        key=lambda row: (row["cohort_year"], -LEVEL_CODE[row["level"]], row["mlbam_id"])
    )
    by_player = {}
    for row in eligible:
        by_player.setdefault(row["mlbam_id"], row)
    return sorted(by_player.values(), key=lambda row: (row["cohort_year"], row["mlbam_id"]))


def _solve(matrix: list[list[float]], vector: list[float]) -> list[float]:
    """Solve Ax=b with partial-pivot Gaussian elimination."""
    n = len(vector)
    augmented = [list(matrix[i]) + [vector[i]] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(augmented[row][col]))
        if abs(augmented[pivot][col]) < 1e-12:
            raise ValueError("Singular ridge system")
        augmented[col], augmented[pivot] = augmented[pivot], augmented[col]
        divisor = augmented[col][col]
        augmented[col] = [value / divisor for value in augmented[col]]
        for row in range(n):
            if row == col:
                continue
            factor = augmented[row][col]
            if factor:
                augmented[row] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(augmented[row], augmented[col])
                ]
    return [augmented[row][-1] for row in range(n)]


def _fit_ridge(rows: list[dict], ridge_lambda: float = RIDGE_LAMBDA) -> dict | None:
    if not rows:
        return None
    columns = list(zip(*(row["features"] for row in rows)))
    means = [mean(column) for column in columns]
    stds = [pstdev(column) or 1.0 for column in columns]
    design = [
        [1.0]
        + [(value - center) / spread for value, center, spread in zip(row["features"], means, stds)]
        for row in rows
    ]
    width = len(design[0])
    matrix = [[0.0] * width for _ in range(width)]
    vector = [0.0] * width
    for x, row in zip(design, rows):
        for i in range(width):
            vector[i] += x[i] * row["target"]
            for j in range(width):
                matrix[i][j] += x[i] * x[j]
    for i in range(1, width):
        matrix[i][i] += ridge_lambda
    return {"weights": _solve(matrix, vector), "means": means, "stds": stds}


def _predict(model: dict, features: list[float]) -> float:
    standardized = [
        (value - center) / spread
        for value, center, spread in zip(features, model["means"], model["stds"])
    ]
    prediction = model["weights"][0] + sum(
        weight * value for weight, value in zip(model["weights"][1:], standardized)
    )
    return max(0.0, min(1.0, prediction))


def _fit_prediction_model(
    rows: list[dict], model_kind: str, ridge_lambda: float
) -> dict | None:
    if model_kind == "ridge":
        model = _fit_ridge(rows, ridge_lambda)
        return {"model_kind": "ridge", **model} if model else None
    if model_kind != "hurdle_ridge":
        raise ValueError(f"Unknown model kind {model_kind}")
    arrival_rows = [
        {**row, "target": 1.0 if row["target"] > 0 else 0.0}
        for row in rows
    ]
    conditional_rows = [row for row in rows if row["target"] > 0]
    arrival = _fit_ridge(arrival_rows, ridge_lambda)
    conditional = _fit_ridge(conditional_rows, ridge_lambda)
    if not arrival or not conditional:
        return None
    return {
        "model_kind": "hurdle_ridge",
        "arrival_model": arrival,
        "conditional_model": conditional,
    }


def _predict_model(model: dict, features: list[float]) -> float:
    if model.get("model_kind") == "hurdle_ridge":
        return _predict(model["arrival_model"], features) * _predict(
            model["conditional_model"], features
        )
    return _predict(model, features)


def _rounded_prediction_model(model: dict) -> dict:
    def rounded_ridge(ridge):
        return {
            "weights": [round(value, 8) for value in ridge["weights"]],
            "means": [round(value, 8) for value in ridge["means"]],
            "stds": [round(value, 8) for value in ridge["stds"]],
        }

    if model["model_kind"] == "hurdle_ridge":
        return {
            "model_kind": "hurdle_ridge",
            "arrival_model": rounded_ridge(model["arrival_model"]),
            "conditional_model": rounded_ridge(model["conditional_model"]),
        }
    return {"model_kind": "ridge", **rounded_ridge(model)}


def _fit_prior(rows: list[dict]) -> dict:
    overall = mean(row["target"] for row in rows) if rows else 0.0
    cells = {}
    for row in rows:
        key = f"{row['level']}|{_age_bucket(row['age'])}"
        cells.setdefault(key, []).append(row["target"])
    return {
        "overall": overall,
        "cells": {
            key: (sum(values) + overall * PRIOR_K) / (len(values) + PRIOR_K)
            for key, values in cells.items()
        },
    }


def _prior_predict(prior: dict, row: dict) -> float:
    key = f"{row['level']}|{_age_bucket(row['age'])}"
    return float(prior["cells"].get(key, prior["overall"]))


def _fit_neighbors(rows: list[dict], feature_key: str = "features") -> dict | None:
    if not rows:
        return None
    columns = list(zip(*(row[feature_key] for row in rows)))
    means = [mean(column) for column in columns]
    stds = [pstdev(column) or 1.0 for column in columns]
    return {
        "features": [
            [
                (value - center) / spread
                for value, center, spread in zip(row[feature_key], means, stds)
            ]
            for row in rows
        ],
        "targets": [row["target"] for row in rows],
        "means": means,
        "stds": stds,
    }


def _neighbor_predict(neighbors: dict, features: list[float], k: int = NEIGHBOR_K) -> float:
    x = [
        (value - center) / spread
        for value, center, spread in zip(features, neighbors["means"], neighbors["stds"])
    ]
    distances = [
        (sum((left - right) ** 2 for left, right in zip(row, x)), index)
        for index, row in enumerate(neighbors["features"])
    ]
    indices = [index for _, index in sorted(distances)[:k]]
    return mean(neighbors["targets"][index] for index in indices)


def _rank_concordance(predictions: list[float], targets: list[float]) -> float | None:
    correct = ties = total = 0
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            if targets[i] == targets[j]:
                continue
            total += 1
            delta_prediction = predictions[i] - predictions[j]
            delta_target = targets[i] - targets[j]
            if delta_prediction == 0:
                ties += 1
            elif delta_prediction * delta_target > 0:
                correct += 1
    return (correct + 0.5 * ties) / total if total else None


def _walk_forward(
    role_rows: list[dict],
    model_kind: str = "ridge",
    ridge_lambda: float = RIDGE_LAMBDA,
    neighbor_feature_key: str = "features",
) -> dict:
    model_predictions, prior_predictions = [], []
    neighbor_predictions, canonical_neighbor_predictions, targets = [], [], []
    folds = []
    cohorts = sorted({row["cohort_year"] for row in role_rows})
    for test_year in cohorts[2:]:
        train = [row for row in role_rows if row["cohort_year"] < test_year]
        test = [row for row in role_rows if row["cohort_year"] == test_year]
        model = _fit_prediction_model(train, model_kind, ridge_lambda)
        neighbors = _fit_neighbors(train, neighbor_feature_key)
        canonical_train = [
            {**row, "features": row.get("baseline_features", row["features"])}
            for row in train
        ]
        canonical_neighbors = _fit_neighbors(canonical_train)
        if not model or not neighbors or not canonical_neighbors or not test:
            continue
        prior = _fit_prior(train)
        folds.append(
            {
                "test_year": test_year,
                "train_year_max": max(row["cohort_year"] for row in train),
                "train_ids": [row["mlbam_id"] for row in train],
                "test_ids": [row["mlbam_id"] for row in test],
            }
        )
        for row in test:
            model_predictions.append(_predict_model(model, row["features"]))
            prior_predictions.append(_prior_predict(prior, row))
            neighbor_predictions.append(
                _neighbor_predict(neighbors, row.get(neighbor_feature_key, row["features"]))
            )
            canonical_neighbor_predictions.append(
                _neighbor_predict(
                    canonical_neighbors,
                    row.get("baseline_features", row["features"]),
                )
            )
            targets.append(row["target"])

    def mae(predictions):
        return mean(abs(prediction - target) for prediction, target in zip(predictions, targets)) if targets else None

    return {
        "model_predictions": model_predictions,
        "prior_predictions": prior_predictions,
        "neighbor_predictions": neighbor_predictions,
        "canonical_neighbor_predictions": canonical_neighbor_predictions,
        "targets": targets,
        "model_mae": mae(model_predictions),
        "prior_mae": mae(prior_predictions),
        "neighbor_mae": mae(neighbor_predictions),
        "canonical_neighbor_mae": mae(canonical_neighbor_predictions),
        "rank_concordance": _rank_concordance(model_predictions, targets),
        "folds": folds,
    }


def train_role(role: str, dataset_rows: list[dict], now: str | None = None) -> dict:
    rows = _historical_rows(dataset_rows, role)
    model_kind = OUTCOME_MODEL_KIND[role]
    validation = _walk_forward(
        rows,
        model_kind,
        RIDGE_LAMBDA,
        neighbor_feature_key="baseline_features",
    )
    now = now or datetime.now(timezone.utc).isoformat()
    gate = decide_gate(
        metric="outcome_score_mae",
        model_score=validation["model_mae"],
        baselines={
            "level_age_prior": validation["prior_mae"],
            "historical_neighbors_25": validation["neighbor_mae"],
        },
        sample_size=len(validation["targets"]),
        cv_method="walk_forward",
        validated_through=str(MATURE_THROUGH),
        min_sample=MIN_GATE_SAMPLE,
        min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
        lower_is_better=True,
        now=now,
    )
    prediction_model = _fit_prediction_model(rows, model_kind, RIDGE_LAMBDA)
    driver_model = _fit_ridge(rows)
    if prediction_model is None or driver_model is None:
        raise ValueError(f"Could not fit {role} model from {len(rows)} rows")
    return {
        "role": role,
        "model_kind": model_kind,
        "ridge_lambda": RIDGE_LAMBDA,
        "feature_names": list(OUTCOME_FEATURE_NAMES[role]),
        "prediction_model": _rounded_prediction_model(prediction_model),
        "weights": [round(value, 8) for value in driver_model["weights"]],
        "means": [round(value, 8) for value in driver_model["means"]],
        "stds": [round(value, 8) for value in driver_model["stds"]],
        "training_sample": len(rows),
        "validation_sample": len(validation["targets"]),
        "model_mae": round(validation["model_mae"], 6),
        "prior_mae": round(validation["prior_mae"], 6),
        "neighbor_mae": round(validation["neighbor_mae"], 6),
        "rank_concordance": round(validation["rank_concordance"], 6),
        "gate": gate,
        "_validation": validation,
    }


def train_impact_role(
    role: str,
    dataset_rows: list[dict],
    seasons_by_player: dict,
    references: dict,
    now: str | None = None,
) -> dict:
    rows = _historical_impact_rows(
        dataset_rows, role, seasons_by_player, references
    )
    model_kind = "hurdle_ridge"
    ridge_lambda = HITTER_IMPACT_RIDGE_LAMBDA if role == "hitter" else RIDGE_LAMBDA
    validation = _walk_forward(rows, model_kind, ridge_lambda)
    now = now or datetime.now(timezone.utc).isoformat()
    gate = decide_gate(
        metric="category_impact_mae",
        model_score=validation["model_mae"],
        baselines={
            "level_age_prior": validation["prior_mae"],
            "historical_neighbors_25": validation["neighbor_mae"],
            "canonical_historical_neighbors_25": validation[
                "canonical_neighbor_mae"
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
    prediction_model = _fit_prediction_model(rows, model_kind, ridge_lambda)
    driver_model = _fit_ridge(rows, ridge_lambda)
    if prediction_model is None or driver_model is None:
        raise ValueError(f"Could not fit {role} impact model from {len(rows)} rows")
    return {
        "role": role,
        "model_kind": model_kind,
        "ridge_lambda": ridge_lambda,
        "feature_names": list(OUTCOME_FEATURE_NAMES[role]),
        "prediction_model": _rounded_prediction_model(prediction_model),
        "weights": [round(value, 8) for value in driver_model["weights"]],
        "means": [round(value, 8) for value in driver_model["means"]],
        "stds": [round(value, 8) for value in driver_model["stds"]],
        "training_sample": len(rows),
        "validation_sample": len(validation["targets"]),
        "model_mae": round(validation["model_mae"], 6),
        "prior_mae": round(validation["prior_mae"], 6),
        "neighbor_mae": round(validation["neighbor_mae"], 6),
        "canonical_neighbor_mae": round(
            validation["canonical_neighbor_mae"], 6
        ),
        "rank_concordance": round(validation["rank_concordance"], 6),
        "gate": gate,
        "_validation": validation,
    }


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


def _current_line_is_bad(record: dict, role: str) -> bool:
    """Factual bad-line guard for the stale-current pull: only pull a prior score
    down when the current line is genuinely poor -- not merely small-sample
    regressed. The current sample must clear a floor (>=10 IP / >=40 PA) before it
    can pull at all: below the floor even an egregious-looking collapse is treated as
    noise (a 2-IP blowup, a 1-PA .000 line), symmetric across roles. Above the floor an
    EGREGIOUS collapse pulls; otherwise a single bad ratio must also clear the floor."""
    if role == "pitcher":
        era = _num(record.get("era"))
        whip = _num(record.get("whip"))
        k_bb = _num(record.get("k_bb_pct"))
        ip = _sample(record, "pitcher")
        if ip < 10.0:
            return False  # too few IP to trust even an egregious line (2-IP blowup = noise)
        if (era is not None and era >= 7.50) or (k_bb is not None and k_bb <= 0.0):
            return True  # egregious collapse / no whiffs (>= 10 IP)
        return bool(
            (era is not None and era >= 5.50)
            or (whip is not None and whip > 1.50)
            or (k_bb is not None and k_bb <= 5.0)
        )
    ops = _num(record.get("ops"))
    iso = _num(record.get("iso"))
    k_pct = _num(record.get("k_pct"))
    bb_pct = _num(record.get("bb_pct"))
    pa = _sample(record, "hitter")
    if pa < 10.0:
        return False  # too few PA to trust even an egregious line (1 PA .000 OPS = noise)
    if ops is not None and ops <= 0.550:
        return True  # egregious collapse (>= 10 PA)
    if pa < 40.0:
        return False
    return bool(
        (ops is not None and ops <= 0.650)
        or (iso is not None and iso <= 0.080)
        or (k_pct is not None and bb_pct is not None and (k_pct - bb_pct) >= 25.0)
    )


def _display_record_key(record: dict, role: str) -> tuple[float, float]:
    """Highest level, then sample -- mirrors rank_v1's display current-line selector
    so the comparator scores the SAME current line the public card shows (no
    'dropped for a line you can't see' contradiction)."""
    return (
        LEVEL_CODE.get(str(record.get("level") or "").upper(), -99.0),
        _sample(record, role),
    )


def _pool_current_records(records: list[dict], role: str) -> dict | None:
    if not records:
        return None
    qualifying = [
        record
        for record in records
        if record.get("source_kind") == "current_season"
        and _num(record.get("sample_season")) is not None
        and _eligible_current(record, role)
    ]
    if len(qualifying) < 2:
        return None
    latest_season = max(_num(record.get("sample_season")) for record in qualifying)
    qualifying = [
        record
        for record in qualifying
        if _num(record.get("sample_season")) == latest_season
    ]
    if len(qualifying) < 2:
        return None
    levels = {
        str(record.get("level") or "").upper()
        for record in qualifying
    }
    if any(level not in LEVEL_CODE for level in levels):
        return None
    levels_pooled = sorted(levels, key=lambda level: LEVEL_CODE[level], reverse=True)
    if len(levels_pooled) < 2:
        return None
    highest = max(
        qualifying,
        key=lambda record: (
            LEVEL_CODE[str(record.get("level") or "").upper()],
            _sample(record, role),
        ),
    )
    if _num(highest.get("age")) is None:
        return None
    sample_key = "plate_appearances" if role == "hitter" else "innings_pitched"
    pooled_sample = sum(_sample(record, role) for record in qualifying)
    if pooled_sample <= 0:
        return None

    pooled_record = dict(highest)
    rate_keys = (
        ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip")
        if role == "hitter"
        else ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
    )
    for key in rate_keys:
        weighted_total = 0.0
        weighted_sample = 0.0
        for record in qualifying:
            value = _num(record.get(key))
            sample = _sample(record, role)
            if value is None or sample <= 0:
                continue
            weighted_total += value * sample
            weighted_sample += sample
        pooled_record[key] = (
            weighted_total / weighted_sample if weighted_sample > 0 else None
        )

    for key in (
        "home_runs",
        "stolen_bases",
        "walks",
        "hits",
        "batters_faced",
        "games_started",
        "games",
        "games_played",
    ):
        pooled_record[key] = sum(_zero_num(record.get(key)) for record in qualifying)
    pooled_record[sample_key] = pooled_sample
    pooled_record["level"] = levels_pooled[0]
    pooled_record["age"] = highest.get("age")
    if role == "pitcher":
        games_started = pooled_record.get("games_started") or 0
        pooled_record["is_starter"] = any(
            _truthy(record.get("is_starter")) for record in qualifying
        ) or games_started >= 5

    return {
        "record": pooled_record,
        "pooled_sample": pooled_sample,
        "levels_pooled": levels_pooled,
        "n_levels": len(levels_pooled),
    }


def _regress_current_features(
    features: list[float], role_model: dict, role: str, sample: float
) -> tuple[list[float], float]:
    reliability = sample / (sample + SAMPLE_REGRESSION[role])
    # Shrink every performance-derived feature in the scoring vector toward its
    # training mean by reliability. The vector is the rich OUTCOME feature set,
    # so we walk the model's own feature_names (falling back to the base names),
    # holding only the structural facts in NON_SHRINK_FEATURES fixed.
    feature_names = role_model.get("feature_names") or FEATURE_NAMES[role]
    means = role_model["means"]
    out = list(features)
    for index, name in enumerate(feature_names):
        if index >= len(out) or index >= len(means):
            break
        if name in NON_SHRINK_FEATURES:
            continue
        center = float(means[index])
        out[index] = center + reliability * (out[index] - center)
    return out, reliability


def _drivers(
    role_model: dict, features: list[float], feature_names: tuple[str, ...]
) -> list[dict]:
    contributions = []
    for index, name in enumerate(feature_names):
        standardized = (
            features[index] - role_model["means"][index]
        ) / role_model["stds"][index]
        contributions.append((name, standardized * role_model["weights"][index + 1]))
    ranked = sorted(contributions, key=lambda item: (-abs(item[1]), item[0]))[:3]
    return [{"feature": name, "contribution": round(value, 4)} for name, value in ranked]


def _prediction_drivers(
    prediction_model: dict,
    features: list[float],
    feature_names: tuple[str, ...],
    groups: dict[str, tuple[str, ...]] | None = None,
) -> list[dict]:
    """Report local score changes from the model that produced the score."""
    groups = groups or {}
    reference_model = (
        prediction_model["arrival_model"]
        if prediction_model.get("model_kind") == "hurdle_ridge"
        else prediction_model
    )
    reference = reference_model["means"]
    index_by_name = {name: index for index, name in enumerate(feature_names)}
    grouped_names = {name for names in groups.values() for name in names}
    candidates = [
        (name, (index_by_name[name],))
        for name in feature_names
        if name not in grouped_names
    ]
    candidates.extend(
        (
            label,
            tuple(index_by_name[name] for name in names),
        )
        for label, names in groups.items()
    )

    full_score = _predict_model(prediction_model, features)
    contributions = []
    for label, indexes in candidates:
        neutral = list(features)
        for index in indexes:
            neutral[index] = reference[index]
        contributions.append(
            (label, full_score - _predict_model(prediction_model, neutral))
        )
    ranked = sorted(contributions, key=lambda item: (-abs(item[1]), item[0]))[:3]
    return [{"feature": name, "contribution": round(value, 4)} for name, value in ranked]


def _service_index(contract: dict) -> dict:
    return {
        (int(row["mlbam_id"]), row["role"]): row
        for row in contract.get("mlb_service", [])
        if row.get("mlbam_id") and row.get("role")
    }


def score_current(
    contract: dict, role_models: dict, impact_models: dict
) -> list[dict]:
    current = contract["current"]
    service = _service_index(contract)
    scored = []
    for role in ("hitter", "pitcher"):
        role_model = role_models[role]
        impact_model = impact_models[role]
        outcome_runtime = {**role_model["prediction_model"]}
        impact_runtime = {**impact_model["prediction_model"]}
        group = "hitters" if role == "hitter" else "pitchers"
        current_by_player: dict[int, list[dict]] = {}
        for current_record in current.get(group, []):
            if not current_record.get("mlbam_id") or not _eligible_current(
                current_record, role
            ):
                continue
            current_by_player.setdefault(int(current_record["mlbam_id"]), []).append(
                current_record
            )
        # W2.4 stale-current correction: every current-SEASON record by player, even
        # below the eligibility floor, so a prior-year-selected player still exposes a
        # current comparator. Picks the SAME line the public card shows (highest
        # level, then sample) so the comparator never scores a line the user can't see.
        current_season_by_player: dict[int, dict] = {}
        for current_record in current.get(group, []):
            mid = current_record.get("mlbam_id")
            if not mid or str(current_record.get("source_kind")) != "current_season":
                continue
            mid = int(mid)
            incumbent = current_season_by_player.get(mid)
            if incumbent is None or _display_record_key(
                current_record, role
            ) > _display_record_key(incumbent, role):
                current_season_by_player[mid] = current_record
        for record in _select_current_records(current, role):
            service_fact = service.get((int(record["mlbam_id"]), role))
            if service_fact is None or service_fact.get("graduated"):
                continue
            raw = _feature_vector(record, role)
            outcome_raw = _outcome_feature_vector(record, role)
            if raw is None or outcome_raw is None:
                continue
            sample = _sample(record, role)
            regressed, reliability = _regress_current_features(
                outcome_raw, role_model, role, sample
            )
            impact_features, _ = _regress_current_features(
                outcome_raw, impact_model, role, sample
            )
            if reliability >= 0.60:
                confidence = "high"
            elif reliability >= 0.35:
                confidence = "moderate"
            else:
                confidence = "low"
            row = {
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
                "confidence": confidence,
                "expected_outcome_score": round(
                    _predict_model(outcome_runtime, regressed), 4
                ),
                "expected_category_impact_score": round(
                    _predict_model(impact_runtime, impact_features), 4
                ),
                "role_gate": role_model["gate"]["status"],
                "impact_gate": impact_model["gate"]["status"],
                "drivers": _prediction_drivers(
                    outcome_runtime,
                    regressed,
                    OUTCOME_FEATURE_NAMES[role],
                ),
                "impact_drivers": _prediction_drivers(
                    impact_runtime,
                    impact_features,
                    OUTCOME_FEATURE_NAMES[role],
                    IMPACT_DRIVER_GROUPS[role],
                ),
            }
            # W2.4 stale-current correction: when the model selected a PRIOR-year line
            # but a factually WORSE current-season line exists, pull the prior score
            # DOWN toward the current comparator, weighted by current evidence
            # (min 0.35). A factual bad-line guard keeps a tiny-but-GOOD current line
            # from reading as "worse"; a player with no current line is untouched.
            # (Runs before pooled-shadow so its served_score reflects the served value.)
            if str(record.get("source_kind")) != "current_season":
                comparator = current_season_by_player.get(int(record["mlbam_id"]))
                comp_outcome_raw = (
                    _outcome_feature_vector(comparator, role) if comparator else None
                )
                if comp_outcome_raw is not None and _current_line_is_bad(
                    comparator, role
                ):
                    comp_sample = _sample(comparator, role)
                    comp_regressed, comp_rel = _regress_current_features(
                        comp_outcome_raw, role_model, role, comp_sample
                    )
                    comp_impact_features, _ = _regress_current_features(
                        comp_outcome_raw, impact_model, role, comp_sample
                    )
                    current_outcome = _predict_model(outcome_runtime, comp_regressed)
                    current_impact = _predict_model(impact_runtime, comp_impact_features)
                    pull_w = min(
                        0.35, comp_sample / (comp_sample + SAMPLE_REGRESSION[role])
                    )
                    prior_outcome = row["expected_outcome_score"]
                    prior_impact = row["expected_category_impact_score"]
                    row["expected_outcome_score"] = round(
                        prior_outcome - pull_w * max(0.0, prior_outcome - current_outcome),
                        4,
                    )
                    row["expected_category_impact_score"] = round(
                        prior_impact - pull_w * max(0.0, prior_impact - current_impact), 4
                    )
                    # Keep the raw model output (the gate validates raw, not adjusted)
                    # and expose the current comparator's reliability for honesty.
                    row["stale_current_correction"] = {
                        "raw_outcome": round(prior_outcome, 4),
                        "raw_impact": round(prior_impact, 4),
                        "current_outcome": round(current_outcome, 4),
                        "current_impact": round(current_impact, 4),
                        "current_sample": round(comp_sample, 1),
                        "current_reliability": round(comp_rel, 3),
                        "pull_weight": round(pull_w, 4),
                    }
            if POOLED_SHADOW_ENABLED:
                try:
                    pooled = _pool_current_records(
                        current_by_player.get(int(record["mlbam_id"]), []), role
                    )
                    if pooled is not None:
                        pooled_record = pooled["record"]
                        pooled_outcome_raw = _outcome_feature_vector(
                            pooled_record, role
                        )
                        if pooled_outcome_raw is not None:
                            pooled_sample = _sample(pooled_record, role)
                            pooled_regressed, _ = _regress_current_features(
                                pooled_outcome_raw,
                                role_model,
                                role,
                                pooled_sample,
                            )
                            served_score = row["expected_outcome_score"]
                            pooled_score = round(
                                _predict_model(outcome_runtime, pooled_regressed), 4
                            )
                            row["pooled_shadow"] = {
                                "version": POOLED_SHADOW_VERSION,
                                "served_score": served_score,
                                "pooled_score": pooled_score,
                                "delta": round(pooled_score - served_score, 4),
                                "served_sample": round(sample, 1),
                                "pooled_sample": round(pooled_sample, 1),
                                "levels_pooled": pooled["levels_pooled"],
                                "n_levels": pooled["n_levels"],
                                "usage": POOLED_SHADOW_USAGE,
                            }
                except Exception:  # noqa: BLE001
                    pass
            scored.append(row)
    scored.sort(key=lambda row: (-row["expected_outcome_score"], row["mlbam_id"], row["role"]))
    for rank, row in enumerate(scored, 1):
        row["valucast_prospect_rank"] = rank
    for rank, row in enumerate(
        sorted(
            scored,
            key=lambda item: (
                -item["expected_category_impact_score"],
                item["mlbam_id"],
                item["role"],
            ),
        ),
        1,
    ):
        row["valucast_impact_rank"] = rank
    return scored


def refresh_impact_drivers(payload: dict, contract: dict) -> tuple[dict, int]:
    """Refresh display-only impact drivers while preserving all model outputs."""
    refreshed_ranked = score_current(
        contract,
        payload["roles"],
        payload["impact_roles"],
    )
    old_by_identity = {
        (row["mlbam_id"], row["role"]): row for row in payload["ranked"]
    }
    new_by_identity = {
        (row["mlbam_id"], row["role"]): row for row in refreshed_ranked
    }
    if old_by_identity.keys() != new_by_identity.keys():
        raise ValueError("Driver refresh changed the candidate set")

    refreshed = copy.deepcopy(payload)
    changed = 0
    for row in refreshed["ranked"]:
        identity = (row["mlbam_id"], row["role"])
        regenerated = new_by_identity[identity]
        old_stable = {key: value for key, value in row.items() if key != "impact_drivers"}
        new_stable = {
            key: value
            for key, value in regenerated.items()
            if key != "impact_drivers"
        }
        if old_stable != new_stable:
            raise ValueError(
                f"Driver refresh changed a non-driver field for {identity}"
            )
        new_drivers = regenerated["impact_drivers"]
        if row.get("impact_drivers") != new_drivers:
            changed += 1
        row["impact_drivers"] = new_drivers
    return refreshed, changed


def build_shadow_model(contract: dict, now: str | None = None) -> dict:
    validate_input_contract(contract)
    now = now or datetime.now(timezone.utc).isoformat()
    rows = contract["historical"].get("rows", [])
    role_models = {role: train_role(role, rows, now) for role in ("hitter", "pitcher")}
    seasons_by_player = contract["historical_mlb_seasons"]
    references = _impact_references(seasons_by_player)
    active_impact_categories = {
        role: _active_impact_categories(references, role)
        for role in ("hitter", "pitcher")
    }
    missing_impact_categories = {
        role: [
            category
            for category in IMPACT_CATEGORIES[role]
            if category not in active_impact_categories[role]
        ]
        for role in ("hitter", "pitcher")
    }
    direct_7x7 = not any(missing_impact_categories.values())
    impact_models = {
        role: train_impact_role(role, rows, seasons_by_player, references, now)
        for role in ("hitter", "pitcher")
    }

    def combined_gate(models: dict, metric: str) -> dict:
        model_predictions, prior_predictions = [], []
        neighbor_predictions, canonical_neighbor_predictions, targets = [], [], []
        for role in ("hitter", "pitcher"):
            validation = models[role].pop("_validation")
            model_predictions.extend(validation["model_predictions"])
            prior_predictions.extend(validation["prior_predictions"])
            neighbor_predictions.extend(validation["neighbor_predictions"])
            canonical_neighbor_predictions.extend(
                validation["canonical_neighbor_predictions"]
            )
            targets.extend(validation["targets"])

        def mae(predictions):
            if not targets:
                return None
            return mean(
                abs(prediction - target)
                for prediction, target in zip(predictions, targets)
            )

        return decide_gate(
            metric=metric,
            model_score=mae(model_predictions),
            baselines={
                "level_age_prior": mae(prior_predictions),
                "historical_neighbors_25": mae(neighbor_predictions),
                "canonical_historical_neighbors_25": mae(
                    canonical_neighbor_predictions
                ),
            },
            sample_size=len(targets),
            cv_method="walk_forward",
            validated_through=str(MATURE_THROUGH),
            min_sample=MIN_GATE_SAMPLE * 2,
            min_improvement_pct=MIN_GATE_IMPROVEMENT_PCT,
            lower_is_better=True,
            now=now,
        )

    board_gate = combined_gate(role_models, "outcome_score_mae")
    impact_board_gate = combined_gate(
        impact_models, "category_impact_mae"
    )
    ranked = score_current(contract, role_models, impact_models)
    limitations = [
        "Shadow-only; never consumed by the live prospect board.",
        "AA/AAA only until lower-minors historical outcomes are built.",
        "No factual draft prior for players without credible statistics.",
        "The ordinal outcome score is a bridge target, not direct fantasy value.",
        "The v0.6 hitter hurdle architecture was selected during retrospective "
        "research and requires forward archived confirmation before live promotion.",
        "Served scores carry a stale-current correction (stale_current_correction): a "
        "prior-year-selected line is pulled toward a worse current line; the raw model "
        "output is preserved in that field and is what the gate validates.",
    ]
    if not direct_7x7:
        limitations.append(
            "The category-impact target remains partial until the missing "
            "historical MLB categories reach adequate coverage."
        )
    return {
        "status": MODEL_STATUS,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "input_contract": {
            "schema_version": contract["schema_version"],
            "generated_at": contract.get("generated_at"),
            "source_policy": contract["source_policy"],
        },
        "target": "ordinal forward MLB outcome score (bust=0, role=0.5, star=1)",
        "target_contract": {
            "kind": "ordinal_outcome_bridge",
            "direct_7x7": False,
            "player_grouped": True,
            "validation": "expanding_window",
            "mature_through": MATURE_THROUGH,
        },
        "impact_target": (
            "best forward MLB season percentile across the factual fantasy "
            "league categories with adequate historical coverage"
        ),
        "impact_target_contract": {
            "kind": (
                "direct_7x7_fantasy_impact"
                if direct_7x7
                else "partial_category_fantasy_impact"
            ),
            "direct_7x7": direct_7x7,
            "canonical_hitter_categories": list(IMPACT_CATEGORIES["hitter"]),
            "canonical_pitcher_categories": list(IMPACT_CATEGORIES["pitcher"]),
            "category_groups": {
                role: {
                    group: list(categories)
                    for group, categories in IMPACT_CATEGORY_GROUPS[role].items()
                }
                for role in ("hitter", "pitcher")
            },
            "hitter_categories": list(active_impact_categories["hitter"]),
            "pitcher_categories": list(active_impact_categories["pitcher"]),
            "missing_hitter_categories": missing_impact_categories["hitter"],
            "missing_pitcher_categories": missing_impact_categories["pitcher"],
            "player_grouped": True,
            "validation": "expanding_window",
            "mature_through": MATURE_THROUGH,
        },
        "scope": "AA/AAA statistical prospects only",
        "board_gate": board_gate,
        "roles": role_models,
        "impact_board_gate": impact_board_gate,
        "impact_roles": impact_models,
        "candidate_count": len(ranked),
        "ranked": ranked,
        "limitations": limitations,
    }


def _stable_gate(gate: dict | None) -> dict:
    return {key: value for key, value in (gate or {}).items() if key != "activated_at"}


def archive_predictions(
    payload: dict, date_str: str | None = None, archive_dir: Path = ARCHIVE_DIR
) -> tuple[Path, bool]:
    archive_dir.mkdir(parents=True, exist_ok=True)
    date_str = date_str or datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    path = archive_dir / f"{date_str}.json"
    archive = {
        "date": date_str,
        "model_version": payload["model_version"],
        "board_gate": _stable_gate(payload["board_gate"]),
        "impact_board_gate": _stable_gate(payload["impact_board_gate"]),
        "roles": {
            role: {
                "gate": _stable_gate(model["gate"]),
                "training_sample": model["training_sample"],
                "validation_sample": model["validation_sample"],
                "model_mae": model["model_mae"],
                "prior_mae": model["prior_mae"],
                "neighbor_mae": model["neighbor_mae"],
                "canonical_neighbor_mae": model.get(
                    "canonical_neighbor_mae", model["neighbor_mae"]
                ),
                "rank_concordance": model["rank_concordance"],
            }
            for role, model in payload["roles"].items()
        },
        "impact_roles": {
            role: {
                "gate": _stable_gate(model["gate"]),
                "training_sample": model["training_sample"],
                "validation_sample": model["validation_sample"],
                "model_mae": model["model_mae"],
                "prior_mae": model["prior_mae"],
                "neighbor_mae": model["neighbor_mae"],
                "canonical_neighbor_mae": model["canonical_neighbor_mae"],
                "model_kind": model["model_kind"],
                "rank_concordance": model["rank_concordance"],
            }
            for role, model in payload["impact_roles"].items()
        },
        "candidate_count": payload["candidate_count"],
        "ranked": payload["ranked"],
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
    archive_path, archive_changed = archive_predictions(
        payload, date_str=parsed_now.date().isoformat(), archive_dir=archive_dir
    )
    return {
        "artifact_path": str(path),
        "archive_path": str(archive_path),
        "archive_changed": archive_changed,
        "gate": payload["board_gate"]["status"],
        "impact_gate": payload["impact_board_gate"]["status"],
        "candidates": payload["candidate_count"],
    }
