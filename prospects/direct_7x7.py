"""Leak-free retrospective Diamond Dynasties 7x7 category endpoint."""
from __future__ import annotations

import copy
import math
from bisect import bisect_right
from collections.abc import Iterable, Mapping
from statistics import mean
from typing import Any

from prospects.extended_history import (
    SeasonCanonicalizationError,
    canonicalize_mlb_seasons,
)
from prospects.model import (
    IMPACT_CATEGORIES,
    IMPACT_CATEGORY_GROUPS,
    IMPACT_INVERSE_CATEGORIES,
    IMPACT_REFERENCE_MIN,
    IMPACT_TARGET_MIN,
    _category_value,
)


HORIZON_YEARS = 4


class DirectValueError(ValueError):
    """Raised when direct category evidence is incomplete or inconsistent."""


def _canonical_seasons(identity: str, seasons: Iterable[Mapping[str, Any]]) -> list[dict]:
    if identity.endswith("_hitter"):
        role = "hitter"
    elif identity.endswith("_pitcher"):
        role = "pitcher"
    else:
        raise DirectValueError(f"invalid season identity: {identity}")
    try:
        return canonicalize_mlb_seasons(seasons, role)
    except SeasonCanonicalizationError as exc:
        raise DirectValueError(f"{identity}: {exc}") from exc


def _finite(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise DirectValueError(f"{field} must be finite") from exc
    if not math.isfinite(number):
        raise DirectValueError(f"{field} must be finite")
    return number


def join_quality_starts(
    seasons_by_player: Mapping[str, list[dict]],
    sidecar: Mapping[str, Any],
) -> dict[str, list[dict]]:
    """Return copied season rows with an exact, validated QS join."""
    if (
        sidecar.get("schema") != "valucast_stage2_quality_starts"
        or sidecar.get("status") != "ready"
    ):
        raise DirectValueError("quality-start sidecar is not ready")
    by_key: dict[tuple[int, int], tuple[int, int]] = {}
    for row in sidecar.get("rows") or []:
        key = (int(row["mlbam_id"]), int(row["season"]))
        if key in by_key:
            raise DirectValueError(f"duplicate QS row: {key}")
        games_started = int(_finite(row.get("games_started"), "games_started"))
        quality_starts = int(
            _finite(row.get("quality_starts"), "quality_starts")
        )
        if games_started < 0 or quality_starts < 0:
            raise DirectValueError(f"negative QS evidence: {key}")
        if quality_starts > games_started:
            raise DirectValueError(f"quality starts exceeds games started: {key}")
        by_key[key] = (games_started, quality_starts)

    joined = {
        str(identity): _canonical_seasons(str(identity), seasons)
        for identity, seasons in seasons_by_player.items()
    }
    for identity, seasons in joined.items():
        if not identity.endswith("_pitcher"):
            continue
        try:
            mlbam_id = int(identity.removesuffix("_pitcher"))
        except ValueError as exc:
            raise DirectValueError(f"invalid pitcher identity: {identity}") from exc
        for season in seasons:
            key = (mlbam_id, int(season.get("year") or 0))
            if key not in by_key:
                raise DirectValueError(f"missing QS row: {key}")
            games_started, quality_starts = by_key[key]
            existing_games_started = season.get("gs", season.get("games_started"))
            if existing_games_started is not None and int(
                _finite(existing_games_started, "season games_started")
            ) != games_started:
                raise DirectValueError(f"games-started mismatch: {key}")
            existing_qs = season.get("qs")
            if existing_qs is not None and int(
                _finite(existing_qs, "season quality_starts")
            ) != quality_starts:
                raise DirectValueError(f"quality-start mismatch: {key}")
            season["gs"] = games_started
            season["qs"] = quality_starts
    return joined


def _identity_key(row: Mapping[str, Any]) -> str:
    return f"{int(row['mlbam_id'])}_{row['role']}"


def build_fold_references(
    training_rows: Iterable[Mapping[str, Any]],
    seasons_by_player: Mapping[str, list[dict]],
    *,
    horizon_years: int = HORIZON_YEARS,
) -> dict[str, dict[str, list[float]]]:
    """Build category distributions from training identities and horizons only."""
    if horizon_years != HORIZON_YEARS:
        raise DirectValueError("direct endpoint requires the frozen four-year horizon")
    clipped: dict[str, list[dict]] = {}
    seen: set[str] = set()
    present_roles: set[str] = set()
    for row in training_rows:
        role = str(row.get("role") or "")
        if role not in IMPACT_CATEGORIES:
            raise DirectValueError(f"invalid role: {role}")
        present_roles.add(role)
        key = _identity_key(row)
        if key in seen:
            raise DirectValueError(f"duplicate training identity: {key}")
        seen.add(key)
        cohort_year = int(row["cohort_year"])
        clipped[key] = [
            copy.deepcopy(season)
            for season in _canonical_seasons(key, seasons_by_player.get(key, []))
            if cohort_year < int(season.get("year") or 0) <= cohort_year + horizon_years
        ]
    references = {
        role: {category: [] for category in IMPACT_CATEGORIES[role]}
        for role in IMPACT_CATEGORIES
    }
    for identity, seasons in clipped.items():
        role = "pitcher" if identity.endswith("_pitcher") else "hitter"
        sample_key = "ip" if role == "pitcher" else "pa"
        for season in seasons:
            if _finite(season.get(sample_key, 0), sample_key) < IMPACT_REFERENCE_MIN[role]:
                continue
            missing = [
                category
                for category in IMPACT_CATEGORIES[role]
                if _category_value(season, category) is None
            ]
            if missing:
                raise DirectValueError(
                    "qualifying reference season missing canonical categories for "
                    f"{identity}:{season.get('year')}: {missing}"
                )
            for category in IMPACT_CATEGORIES[role]:
                references[role][category].append(
                    float(_category_value(season, category))
                )
    for role in references:
        for category in references[role]:
            references[role][category].sort()
    for role in sorted(present_roles):
        categories = IMPACT_CATEGORIES[role]
        missing = [category for category in categories if not references[role][category]]
        if missing:
            raise DirectValueError(
                f"fold references missing canonical categories for {role}: {missing}"
            )
    return references


def direct_7x7_target(
    record: Mapping[str, Any],
    seasons_by_player: Mapping[str, list[dict]],
    references: dict[str, dict[str, list[float]]],
    *,
    horizon_years: int = HORIZON_YEARS,
) -> float:
    """Return category-complete best-season impact in the four-year horizon."""
    if horizon_years != HORIZON_YEARS:
        raise DirectValueError("direct endpoint requires the frozen four-year horizon")
    role = str(record.get("role") or "")
    if role not in IMPACT_CATEGORIES:
        raise DirectValueError(f"invalid role: {role}")
    for category in IMPACT_CATEGORIES[role]:
        if not (references.get(role) or {}).get(category):
            raise DirectValueError(
                f"fold references missing canonical categories for {role}"
            )
    key = _identity_key(record)
    cohort_year = int(record["cohort_year"])
    sample_key = "pa" if role == "hitter" else "ip"
    qualifying = [
        season
        for season in _canonical_seasons(key, seasons_by_player.get(key, []))
        if cohort_year < int(season.get("year") or 0) <= cohort_year + horizon_years
        and (_finite(season.get(sample_key, 0), sample_key)) >= IMPACT_TARGET_MIN[role]
    ]
    for season in qualifying:
        missing = [
            category
            for category in IMPACT_CATEGORIES[role]
            if _category_value(season, category) is None
        ]
        if missing:
            raise DirectValueError(
                f"missing canonical categories for {key}:{season.get('year')}: {missing}"
            )
    # No qualifying opportunity is a factual zero. Missing fields within a
    # qualifying season were rejected above and are never zero-filled.
    if not qualifying:
        return 0.0
    season_scores = []
    for season in qualifying:
        group_scores = []
        for categories in IMPACT_CATEGORY_GROUPS[role].values():
            category_scores = []
            for category in categories:
                value = float(_category_value(season, category))
                distribution = references[role][category]
                percentile = bisect_right(distribution, value) / len(distribution)
                if category in IMPACT_INVERSE_CATEGORIES[role]:
                    percentile = 1.0 - percentile
                category_scores.append(percentile)
            group_scores.append(mean(category_scores))
        season_scores.append(max(group_scores))
    return float(max(season_scores))


def top_k_regret(
    rows: Iterable[Mapping[str, Any]],
    *,
    prediction_field: str,
    target_field: str,
    k: int,
) -> dict[str, float | int]:
    """Compute oracle opportunity cost for a deterministic model top-k."""
    scored = []
    for row in rows:
        scored.append(
            (
                _finite(row.get(prediction_field), prediction_field),
                _finite(row.get(target_field), target_field),
                int(row["mlbam_id"]),
                str(row.get("role") or ""),
            )
        )
    if k <= 0:
        raise DirectValueError("k must be positive")
    if len(scored) < k:
        raise DirectValueError(f"cohort has fewer than k rows: {len(scored)} < {k}")
    oracle = sorted((target for _, target, _, _ in scored), reverse=True)[:k]
    selected = sorted(scored, key=lambda row: (-row[0], row[2], row[3]))[:k]
    oracle_mean = mean(oracle)
    selected_mean = mean(target for _, target, _, _ in selected)
    return {
        "k": int(k),
        "oracle_mean": float(oracle_mean),
        "selected_mean": float(selected_mean),
        "regret": float(oracle_mean - selected_mean),
    }
