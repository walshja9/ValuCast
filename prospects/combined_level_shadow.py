"""Observe-only per-level combined prospect value shadow."""
from __future__ import annotations

import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

from prospects.model import (
    ARTIFACT_PATH as PROSPECT_MODEL_PATH,
    INPUT_PATH as PROSPECT_INPUT_PATH,
    LEVEL_CODE,
    SAMPLE_REGRESSION,
    _outcome_feature_vector,
    _pool_current_records,
    _predict_model,
    _regress_current_features,
    _sample,
)
from prospects.rank_v1 import (
    ARTIFACT_PATH as PROSPECT_RANK_PATH,
    MODEL_COMPONENT_WEIGHTS,
    SCORE_WEIGHTS,
    _bucket_calibration_adjustment,
    _model_score_tiebreak_key,
    _pooled_quantile_value,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_NAME = "valucast_combined_level_shadow"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_combined_level_shadow.json"
ARCHIVE_DIR = ROOT / "data" / "prediction_archive" / "valucast_combined_level_shadow"
SHADOW_VERSION = "0.1.0"
USAGE = "combined_level_shadow_observe_only_not_live_score_or_value"


def _load_optional(path: Path) -> tuple[dict, list[str]]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except Exception as exc:  # noqa: BLE001
        return {}, [f"{path} unreadable: {exc}"]


def _num(value) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _round(value, digits: int = 2):
    numeric = _num(value)
    return None if numeric is None else round(numeric, digits)


def _identity(row: dict) -> tuple[int, str] | None:
    mid = row.get("mlbam_id")
    role = row.get("role")
    if mid is None or role not in {"hitter", "pitcher"}:
        return None
    return int(mid), str(role)


def _source_policy() -> dict:
    return {
        "kind": "valucast_combined_level_shadow",
        "feeds_model_score": False,
        "feeds_public_rank": False,
        "feeds_buy_score": False,
        "feeds_live_valucast_rank": False,
        "feeds_live_dd_value": False,
        "dd_values_used": False,
        "external_rankings_used": False,
        "market_values_used": False,
    }


def _sample_reliability(sample: float, role: str) -> float:
    if sample <= 0:
        return 0.0
    return round(max(0.0, min(100.0, 100.0 * sample / (sample + SAMPLE_REGRESSION[role]))), 2)


def _weighted_model_score(level_scores: list[dict]) -> tuple[float, list[dict]]:
    total = sum(_num(row.get("sample")) or 0.0 for row in level_scores)
    if total <= 0:
        return 0.0, []
    weighted = 0.0
    weights = []
    for row in level_scores:
        sample = _num(row.get("sample")) or 0.0
        score = _num(row.get("model_score")) or 0.0
        weight = sample / total
        weighted += score * weight
        weights.append(
            {
                "level": row.get("level"),
                "sample": round(sample, 1),
                "weight": round(weight, 4),
                "model_score": round(score, 2),
            }
        )
    return round(weighted, 2), weights


def _valid_current_row(row: dict, role: str) -> bool:
    level = str(row.get("level") or "").upper()
    return (
        row.get("mlbam_id") is not None
        and row.get("source_kind") == "current_season"
        and level in LEVEL_CODE
        and _sample(row, role) > 0
        and _outcome_feature_vector(row, role) is not None
    )


def _current_rows_by_key(input_payload: dict) -> dict[tuple[int, str], list[dict]]:
    grouped: dict[tuple[int, str], dict[str, dict]] = {}
    for role, group in (("hitter", "hitters"), ("pitcher", "pitchers")):
        for row in input_payload.get("current", {}).get(group, []):
            if not isinstance(row, dict) or not _valid_current_row(row, role):
                continue
            key = (int(row["mlbam_id"]), role)
            level = str(row.get("level") or "").upper()
            incumbent = grouped.setdefault(key, {}).get(level)
            if incumbent is None or _sample(row, role) > _sample(incumbent, role):
                copy_row = dict(row)
                copy_row["level"] = level
                grouped[key][level] = copy_row
    return {
        key: sorted(rows.values(), key=lambda item: LEVEL_CODE[str(item["level"])])
        for key, rows in grouped.items()
        if len(rows) >= 2
    }


def _score_record(
    record: dict,
    role: str,
    role_models: dict,
    impact_models: dict,
) -> dict | None:
    features = _outcome_feature_vector(record, role)
    if features is None:
        return None
    sample = _sample(record, role)
    role_model = role_models.get(role)
    impact_model = impact_models.get(role)
    if not role_model or not impact_model:
        return None
    regressed, reliability = _regress_current_features(features, role_model, role, sample)
    impact_features, _ = _regress_current_features(features, impact_model, role, sample)
    return {
        "expected_outcome_score": round(
            _predict_model(role_model["prediction_model"], regressed), 4
        ),
        "expected_category_impact_score": round(
            _predict_model(impact_model["prediction_model"], impact_features), 4
        ),
        "sample_reliability": round(reliability, 3),
    }


def _normalized_model_score(
    model_rows: list[dict],
    key: tuple[int, str],
    scored: dict,
) -> float | None:
    components: dict[str, float] = {}
    role = key[1]
    for field in MODEL_COMPONENT_WEIGHTS:
        replacement = _num(scored.get(field))
        if replacement is None:
            return None
        pooled_values = []
        role_entries = []
        for row in model_rows:
            row_key = _identity(row)
            value = replacement if row_key == key else _num(row.get(field))
            if row.get("role") not in {"hitter", "pitcher"} or value is None:
                continue
            pooled_values.append(value)
            if row.get("role") == role:
                role_entries.append((value, _model_score_tiebreak_key(row), row_key))
        if not pooled_values or not role_entries:
            return None
        role_entries.sort(key=lambda item: (item[0], item[1]))
        target_index = next(
            (index for index, item in enumerate(role_entries) if item[2] == key),
            None,
        )
        if target_index is None:
            return None
        percentile = (target_index + 1) / (len(role_entries) + 1)
        normalized = _pooled_quantile_value(sorted(pooled_values), percentile)
        if normalized is None:
            return None
        components[field] = normalized
    return round(
        100.0
        * sum(MODEL_COMPONENT_WEIGHTS[field] * components[field] for field in components),
        2,
    )


def _line_model_score(
    record: dict,
    role: str,
    key: tuple[int, str],
    model_rows: list[dict],
    role_models: dict,
    impact_models: dict,
) -> dict | None:
    scored = _score_record(record, role, role_models, impact_models)
    if scored is None:
        return None
    model_score = _normalized_model_score(model_rows, key, scored)
    if model_score is None:
        return None
    return {
        "level": str(record.get("level") or "").upper(),
        "sample": round(_sample(record, role), 1),
        "model_score": model_score,
        "expected_outcome_score": scored["expected_outcome_score"],
        "expected_category_impact_score": scored["expected_category_impact_score"],
    }


def _blend_score(
    model_score: float,
    universal_score: float,
    investment_score: float,
    reliability_score: float,
) -> float:
    weights = SCORE_WEIGHTS["prospect_model_v0_6"]
    return round(
        weights["model_score"] * model_score
        + weights["universal_outcome_index"] * universal_score
        + weights["factual_investment_context"] * investment_score
        + weights["sample_reliability"] * reliability_score,
        2,
    )


def _display_record(rows: list[dict], role: str) -> dict:
    return max(
        rows,
        key=lambda row: (
            LEVEL_CODE.get(str(row.get("level") or "").upper(), -99.0),
            _sample(row, role),
        ),
    )


def _served_model_line_is_current(
    model_row: dict,
    current_rows: list[dict],
    role: str,
) -> bool:
    served_level = str(model_row.get("level") or "").upper()
    served_sample = _num(model_row.get("sample"))
    if served_level not in LEVEL_CODE or served_sample is None:
        return False
    return any(
        str(row.get("level") or "").upper() == served_level
        and math.isclose(_sample(row, role), served_sample, abs_tol=0.05)
        for row in current_rows
    )


def _apply_served_rank_adjustments(
    score: float,
    components: dict,
    reliability: float,
    input_row: dict,
    role: str,
) -> tuple[float, dict]:
    availability = components.get("availability")
    availability = availability if isinstance(availability, dict) else {}
    discount = max(0.0, min(1.0, _num(availability.get("risk_discount")) or 0.0))
    after_availability = round(max(0.0, score * (1.0 - discount)), 2)
    shadow_components = dict(components)
    # The served row's own bucket application rides in via components; drop it
    # so the emitted metadata is exactly what the SHADOW recomputed (when the
    # shadow fires no adjustments, the early return would otherwise leave the
    # served board's bucket dict here, misattributed as a shadow application).
    shadow_components.pop("bucket_calibration", None)
    shadow_components.pop("score_before_bucket_calibration", None)
    shadow_components["sample_reliability"] = reliability
    shadow_components["availability"] = availability
    shadow_components["score_before_availability_adjustment"] = round(score, 2)
    shadow_components["availability_risk_discount"] = round(discount, 4)
    shadow_components["availability_adjusted"] = discount > 0
    after_bucket, adjusted_components = _bucket_calibration_adjustment(
        after_availability,
        "prospect_model_v0_6",
        None,
        input_row,
        {"role": role, "level": input_row.get("level")},
        shadow_components,
    )
    metadata = {
        "score_before_availability_adjustment": round(score, 2),
        "score_after_availability_adjustment": after_availability,
        "availability_risk_discount": round(discount, 4),
    }
    bucket = adjusted_components.get("bucket_calibration")
    if bucket:
        metadata["bucket_calibration"] = bucket
    return after_bucket, metadata


def _naive_highest_level_combined_score(
    rows: list[dict],
    role: str,
    key: tuple[int, str],
    model_rows: list[dict],
    role_models: dict,
    impact_models: dict,
    universal_score: float,
    investment_score: float,
) -> float | None:
    pooled = _pool_current_records(rows, role)
    if not pooled:
        return None
    score = _line_model_score(
        pooled["record"], role, key, model_rows, role_models, impact_models
    )
    if not score:
        return None
    reliability = _sample_reliability(pooled["pooled_sample"], role)
    return _blend_score(score["model_score"], universal_score, investment_score, reliability)


def _rank_if_live(rank_rows: list[dict], shadows: list[dict]) -> None:
    shadow_by_key = {
        (int(row["mlbam_id"]), row["role"]): row for row in shadows if row.get("mlbam_id")
    }
    simulated = []
    for row in rank_rows:
        key = _identity(row)
        if key is None:
            continue
        shadow = shadow_by_key.get(key)
        score = shadow["shadow_score"] if shadow else row.get("score")
        simulated.append((key, _num(score) or 0.0, row.get("rank") or 999999, row.get("name") or ""))
    simulated.sort(key=lambda item: (-item[1], item[2], item[3], item[0]))
    rank_by_key = {key: rank for rank, (key, *_rest) in enumerate(simulated, 1)}
    for row in shadows:
        key = (int(row["mlbam_id"]), row["role"])
        rank = rank_by_key.get(key)
        row["rank_if_live"] = rank
        row["delta_rank"] = rank - row["served_rank"] if rank is not None else None


def _p90(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * 0.90) - 1))
    return ordered[index]


def _largest_movers(shadows: list[dict]) -> list[dict]:
    rows = sorted(
        shadows,
        key=lambda row: (
            -abs(_num(row.get("delta_score")) or 0.0),
            abs(_num(row.get("delta_rank")) or 0.0) * -1,
            row.get("served_rank") or 999999,
            str(row.get("name") or ""),
        ),
    )[:25]
    return [
        {
            "mlbam_id": row.get("mlbam_id"),
            "role": row.get("role"),
            "name": row.get("name"),
            "served_rank": row.get("served_rank"),
            "rank_if_live": row.get("rank_if_live"),
            "delta_rank": row.get("delta_rank"),
            "served_score": row.get("served_score"),
            "shadow_score": row.get("shadow_score"),
            "delta_score": row.get("delta_score"),
            "levels_scored": row.get("levels_scored"),
            "total_sample": row.get("total_sample"),
        }
        for row in rows
    ]


def build_combined_level_shadow(
    *,
    model_path: Path = PROSPECT_MODEL_PATH,
    rank_path: Path = PROSPECT_RANK_PATH,
    input_path: Path = PROSPECT_INPUT_PATH,
    generated_at: str | None = None,
) -> dict:
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    model_payload, model_blockers = _load_optional(model_path)
    rank_payload, rank_blockers = _load_optional(rank_path)
    input_payload, input_blockers = _load_optional(input_path)
    blockers = [*model_blockers, *rank_blockers, *input_blockers]

    model_rows = model_payload.get("ranked") if isinstance(model_payload, dict) else None
    rank_rows = rank_payload.get("board") if isinstance(rank_payload, dict) else None
    role_models = model_payload.get("roles") if isinstance(model_payload, dict) else None
    impact_models = (
        model_payload.get("impact_roles") if isinstance(model_payload, dict) else None
    )
    if model_rows is None and not model_blockers:
        blockers.append(f"{model_path} missing ranked rows")
    if rank_rows is None and not rank_blockers:
        blockers.append(f"{rank_path} missing board rows")
    if role_models is None and not model_blockers:
        blockers.append(f"{model_path} missing roles")
    if impact_models is None and not model_blockers:
        blockers.append(f"{model_path} missing impact_roles")
    if not isinstance(input_payload.get("current"), dict) and not input_blockers:
        blockers.append(f"{input_path} missing current rows")

    model_rows = model_rows if isinstance(model_rows, list) else []
    rank_rows = rank_rows if isinstance(rank_rows, list) else []
    role_models = role_models if isinstance(role_models, dict) else {}
    impact_models = impact_models if isinstance(impact_models, dict) else {}
    rank_by_key = {
        key: row
        for row in rank_rows
        if isinstance(row, dict) and (key := _identity(row)) is not None
    }
    model_by_key = {
        key: row
        for row in model_rows
        if isinstance(row, dict) and (key := _identity(row)) is not None
    }
    current_by_key = _current_rows_by_key(input_payload) if not input_blockers else {}

    shadows: list[dict] = []
    policy = _source_policy()
    for key, current_rows in current_by_key.items():
        rank_row = rank_by_key.get(key)
        model_row = model_by_key.get(key)
        if rank_row is None or model_row is None:
            continue
        if rank_row.get("score_source") != "prospect_model_v0_6":
            continue
        role = key[1]
        if not _served_model_line_is_current(model_row, current_rows, role):
            continue
        line_scores = [
            score
            for score in (
                _line_model_score(
                    row, role, key, model_rows, role_models, impact_models
                )
                for row in current_rows
            )
            if score is not None
        ]
        if len(line_scores) < 2:
            continue
        weighted_model_score, level_weights = _weighted_model_score(line_scores)
        total_sample = sum(row["sample"] for row in line_scores)
        reliability = _sample_reliability(total_sample, role)
        components = rank_row.get("components") or {}
        universal = _num(components.get("universal_outcome_index")) or 0.0
        investment = _num(components.get("factual_investment_context")) or 25.0
        raw_shadow_score = _blend_score(
            weighted_model_score, universal, investment, reliability
        )
        display_row = _display_record(current_rows, role)
        shadow_score, rank_adjustments = _apply_served_rank_adjustments(
            raw_shadow_score,
            components,
            reliability,
            display_row,
            role,
        )
        served_score = round(_num(rank_row.get("score")) or 0.0, 2)
        served_rank = int(rank_row.get("rank") or 0)
        row = {
            "mlbam_id": key[0],
            "role": role,
            "name": rank_row.get("name") or model_row.get("name"),
            "normalized_name": rank_row.get("normalized_name")
            or model_row.get("normalized_name"),
            "team": rank_row.get("mlb_team") or model_row.get("team"),
            "position": model_row.get("position"),
            "served_score": served_score,
            "served_rank": served_rank,
            "served_level": rank_row.get("level"),
            "served_sample": _round(
                ((components.get("factual_current_context") or {}).get("sample"))
                or model_row.get("sample"),
                1,
            ),
            "served_model_score": _round(components.get("model_score"), 2),
            "shadow_score": shadow_score,
            "shadow_score_before_rank_adjustments": raw_shadow_score,
            "shadow_model_score": weighted_model_score,
            "delta_score": round(shadow_score - served_score, 2),
            "rank_adjustments": rank_adjustments,
            "levels_scored": [item["level"] for item in line_scores],
            "level_weights": level_weights,
            "total_sample": round(total_sample, 1),
            "shadow_reliability": reliability,
            "universal_outcome_index": round(universal, 2),
            "factual_investment_context": round(investment, 2),
            "naive_highest_level_combined_score": _naive_highest_level_combined_score(
                current_rows,
                role,
                key,
                model_rows,
                role_models,
                impact_models,
                universal,
                investment,
            ),
            "usage": USAGE,
            "source_policy": dict(policy),
        }
        shadows.append(row)

    _rank_if_live(rank_rows, shadows)
    abs_deltas = [abs(_num(row.get("delta_score")) or 0.0) for row in shadows]
    summary = {
        "scored_count": len(rank_rows),
        "shadowed_count": len(shadows),
        "multi_level_count": len(shadows),
        "nontrivial_delta_count": sum(1 for value in abs_deltas if value >= 0.01),
        "median_abs_delta": round(median(abs_deltas), 4) if abs_deltas else 0.0,
        "p90_abs_delta": round(_p90(abs_deltas), 4),
        "largest_movers": _largest_movers(shadows),
    }
    return {
        "artifact": ARTIFACT_NAME,
        "shadow_version": SHADOW_VERSION,
        "generated_at": generated_at,
        "status": "blocked" if blockers else "candidate_ready",
        "source_policy": policy,
        "summary": summary,
        "shadows": shadows,
        "validation": {
            "ready": not blockers,
            "blockers": blockers,
        },
    }


def _write_json(payload: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return path


def archive_combined_level_shadow(
    payload: dict, archive_dir: Path = ARCHIVE_DIR, date_str: str | None = None
) -> Path:
    archive_dir.mkdir(parents=True, exist_ok=True)
    if date_str is None:
        generated_at = datetime.fromisoformat(
            str(payload["generated_at"]).replace("Z", "+00:00")
        )
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        date_str = generated_at.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    path = archive_dir / f"{date_str}.json"
    return _write_json(payload, path)


def run_combined_level_shadow(
    *,
    model_path: Path = PROSPECT_MODEL_PATH,
    rank_path: Path = PROSPECT_RANK_PATH,
    input_path: Path = PROSPECT_INPUT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
    archive_dir: Path = ARCHIVE_DIR,
    generated_at: str | None = None,
) -> dict:
    payload = build_combined_level_shadow(
        model_path=model_path,
        rank_path=rank_path,
        input_path=input_path,
        generated_at=generated_at,
    )
    path = _write_json(payload, artifact_path)
    archive_path = archive_combined_level_shadow(payload, archive_dir)
    summary = payload["summary"]
    return {
        "artifact_path": str(path),
        "archive_path": str(archive_path),
        "status": payload["status"],
        "scored_count": summary["scored_count"],
        "shadowed_count": summary["shadowed_count"],
        "multi_level_count": summary["multi_level_count"],
        "nontrivial_delta_count": summary["nontrivial_delta_count"],
    }
