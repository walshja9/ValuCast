"""Shared league-scoring contract for ValuCast projection models.

Prospect and MLB models may estimate outcomes differently, but league adapters
should consume the same source-neutral category projection rows.
"""
from __future__ import annotations

from statistics import mean, pstdev

PROJECTION_CONTRACT_VERSION = "1.0"
ROLES = ("hitter", "pitcher")
RATIO_CATEGORIES = {
    "hitter": {"AVG", "OBP", "OPS", "SLG"},
    "pitcher": {"ERA", "WHIP", "K/BB"},
}
VOLUME_CATEGORY = {"hitter": "PA", "pitcher": "IP"}


def normalize_categories(categories: dict) -> dict[str, float]:
    normalized = {}
    for category, weight in categories.items():
        value = float(weight)
        if value:
            normalized[str(category).upper()] = value
    return normalized


def projection_row(
    *,
    player_id,
    role: str,
    projected_volume: float,
    categories: dict,
    **metadata,
) -> dict:
    """Create one source-neutral row for a category or points adapter."""
    if role not in ROLES:
        raise ValueError(f"Unsupported projection role {role!r}")
    if player_id is None or not str(player_id).strip():
        raise ValueError("Projection row missing player_id")
    volume = float(projected_volume)
    if volume < 0:
        raise ValueError("Projected volume cannot be negative")
    normalized = {
        str(category).upper(): float(value)
        for category, value in categories.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    return {
        "player_id": str(player_id),
        "role": role,
        "projected_volume": round(volume, 4),
        "categories": {key: round(value, 4) for key, value in normalized.items()},
        **metadata,
    }


def projection_contract(
    rows: list[dict],
    *,
    source_kind: str,
    source_model: str,
    source_model_version: str,
) -> dict:
    """Describe the stable boundary shared by prospect and MLB projections."""
    validate_projection_rows(rows)
    return {
        "version": PROJECTION_CONTRACT_VERSION,
        "source_kind": source_kind,
        "source_model": source_model,
        "source_model_version": source_model_version,
        "player_id": "stable source identifier; MLBAM where available",
        "role": list(ROLES),
        "volume": dict(VOLUME_CATEGORY),
        "row_count": len(rows),
        "rows": rows,
    }


def engine_projection_row(row: dict) -> dict:
    """Convert an existing ValuCast MLB projection export into the shared row."""
    role = str(row.get("pool") or "").lower()
    stats = row.get("stats") or {}
    metadata = row.get("metadata") or {}
    volume_category = VOLUME_CATEGORY.get(role)
    if volume_category is None:
        raise ValueError(f"Unsupported projection role {role!r}")
    player_id = metadata.get("mlbam_id") or row.get("id")
    return projection_row(
        player_id=player_id,
        role=role,
        projected_volume=stats.get(volume_category, 0.0),
        categories={
            category: value
            for category, value in stats.items()
            if category != volume_category
        },
        mlbam_id=metadata.get("mlbam_id"),
        name=row.get("name"),
        source=metadata.get("source"),
        source_model=metadata.get("model"),
        source_model_version=metadata.get("model_version"),
    )


def validate_projection_rows(rows: list[dict]) -> None:
    seen = set()
    for row in rows:
        role = row.get("role")
        if role not in ROLES:
            raise ValueError(f"Unsupported projection role {role!r}")
        if not row.get("player_id"):
            raise ValueError("Projection row missing player_id")
        key = (role, str(row["player_id"]))
        if key in seen:
            raise ValueError(f"Duplicate projection row {role}:{row['player_id']}")
        seen.add(key)
        volume = row.get("projected_volume")
        if (
            not isinstance(volume, (int, float))
            or isinstance(volume, bool)
            or volume < 0
        ):
            raise ValueError("Projection row has invalid projected_volume")
        categories = row.get("categories")
        if not isinstance(categories, dict):
            raise ValueError("Projection row missing categories")
        if any(
            not isinstance(value, (int, float)) or isinstance(value, bool)
            for value in categories.values()
        ):
            raise ValueError("Projection row contains a non-numeric category")


def _available_categories(rows: list[dict]) -> set[str]:
    available = None
    for row in rows:
        categories = set(row["categories"])
        available = categories if available is None else available & categories
    return available or set()


def _category_scoring_value(
    row: dict, role: str, category: str, raw_center: float
) -> float:
    value = row["categories"][category]
    if category not in RATIO_CATEGORIES[role]:
        return value
    return (value - raw_center) * row["projected_volume"]


def rank_projection_rows(rows: list[dict], role: str, categories: dict) -> dict:
    """Rank one role's rows, refusing partial category coverage."""
    validate_projection_rows(rows)
    if any(row["role"] != role for row in rows):
        raise ValueError("Projection rows must contain exactly one requested role")
    config = normalize_categories(categories)
    available = _available_categories(rows)
    missing = sorted(set(config) - available)
    coverage = (len(config) - len(missing)) / len(config) if config else 0.0
    ranked = [dict(row) for row in rows]
    complete = bool(config) and bool(ranked) and not missing
    if complete:
        raw_centers = {
            category: mean(row["categories"][category] for row in ranked)
            for category in config
        }
        scoring_values = {
            row["player_id"]: {
                category: _category_scoring_value(
                    row, role, category, raw_centers[category]
                )
                for category in config
            }
            for row in ranked
        }
        centers = {
            category: mean(
                scoring_values[row["player_id"]][category] for row in ranked
            )
            for category in config
        }
        spreads = {
            category: pstdev(
                scoring_values[row["player_id"]][category] for row in ranked
            )
            or 1.0
            for category in config
        }
        for row in ranked:
            row["adapter_score"] = round(
                sum(
                    (scoring_values[row["player_id"]][category] - centers[category])
                    / spreads[category]
                    * weight
                    for category, weight in config.items()
                ),
                4,
            )
        ranked.sort(key=lambda row: (-row["adapter_score"], row["player_id"]))
        for rank, row in enumerate(ranked, 1):
            row["adapter_rank"] = rank
    return {
        "status": "research_ranked" if complete else "insufficient_category_coverage",
        "category_coverage": round(coverage, 4),
        "configured_categories": config,
        "supported_categories": sorted(set(config) & available),
        "missing_categories": missing,
        "candidate_count": len(ranked),
        "players": ranked,
    }
