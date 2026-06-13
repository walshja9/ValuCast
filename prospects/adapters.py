"""League-scoring adapters for ValuCast universal prospect profiles.

Adapters translate a baseball-outcome profile into a league opinion. They are
separate from the universal model and refuse to rank incomplete category sets.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from statistics import mean, pstdev

from prospects.universal import ARTIFACT_PATH as UNIVERSAL_ARTIFACT_PATH

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_league_adapters.json"
ADAPTER_VERSION = "0.2.0"

PRESETS = {
    "roto_5x5": {
        "name": "Standard 5x5",
        "hitter": {"R": 1, "HR": 1, "RBI": 1, "SB": 1, "AVG": 1},
        "pitcher": {"W": 1, "K": 1, "ERA": -1, "WHIP": -1, "SV": 1},
    },
    "dd_7x7": {
        "name": "Diamond Dynasties 7x7",
        "hitter": {
            "R": 1,
            "HR": 1,
            "RBI": 1,
            "SB": 1,
            "AVG": 1,
            "OPS": 1,
            "SO": -1,
        },
        "pitcher": {
            "K": 1,
            "QS": 1,
            "SV+HLD": 1,
            "ERA": -1,
            "WHIP": -1,
            "K/BB": 1,
            "L": -1,
        },
    },
}
SUPPORTED_CATEGORIES = {
    "hitter": {"PA", "R", "HR", "RBI", "SB", "AVG", "OPS", "SO"},
    "pitcher": {"IP", "K", "QS", "SV+HLD", "ERA", "WHIP", "K/BB", "L"},
}
RATIO_CATEGORIES = {
    "hitter": {"AVG", "OPS"},
    "pitcher": {"ERA", "WHIP", "K/BB"},
}
VOLUME_CATEGORY = {"hitter": "PA", "pitcher": "IP"}


def _prediction(profile: dict, name: str) -> float:
    return float(profile["outcomes"][name]["prediction"])


def _has_prediction(profile: dict, name: str) -> bool:
    value = (profile.get("outcomes") or {}).get(name, {}).get("prediction")
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def project_categories(profile: dict) -> dict[str, float]:
    role = profile["role"]
    if not _has_prediction(profile, "established_probability"):
        return {}
    established = _prediction(profile, "established_probability")
    if role == "hitter":
        if not _has_prediction(profile, "representative_pa"):
            return {}
        pa = established * _prediction(profile, "representative_pa")
        categories = {"PA": pa}
        for category, target in {
            "R": "representative_r_per_600",
            "HR": "representative_hr_per_600",
            "RBI": "representative_rbi_per_600",
            "SB": "representative_sb_per_600",
        }.items():
            if _has_prediction(profile, target):
                categories[category] = pa / 600.0 * _prediction(profile, target)
        for category, target in {
            "AVG": "representative_avg",
            "OPS": "representative_ops",
        }.items():
            if _has_prediction(profile, target):
                categories[category] = _prediction(profile, target)
        if _has_prediction(profile, "representative_k_pct"):
            categories["SO"] = pa * _prediction(profile, "representative_k_pct") / 100.0
        return categories
    if not _has_prediction(profile, "representative_ip"):
        return {}
    ip = established * _prediction(profile, "representative_ip")
    categories = {"IP": ip}
    for category, target, scale in (
        ("K", "representative_k_per_9", 9.0),
        ("L", "representative_l_per_180", 180.0),
    ):
        if _has_prediction(profile, target):
            categories[category] = ip / scale * _prediction(profile, target)
    rotation_share = None
    if _has_prediction(profile, "rotation_probability"):
        rotation_probability = _prediction(profile, "rotation_probability")
        rotation_share = (
            max(0.0, min(1.0, rotation_probability / established))
            if established
            else 0.0
        )
    if rotation_share is not None and _has_prediction(
        profile, "representative_qs_per_180"
    ):
        categories["QS"] = (
            ip
            / 180.0
            * _prediction(profile, "representative_qs_per_180")
            * rotation_share
        )
    if rotation_share is not None and _has_prediction(
        profile, "representative_sv_hld_per_60"
    ):
        categories["SV+HLD"] = (
            ip
            / 60.0
            * _prediction(profile, "representative_sv_hld_per_60")
            * (1.0 - rotation_share)
        )
    for category, target in {
        "ERA": "representative_era",
        "WHIP": "representative_whip",
        "K/BB": "representative_k_bb",
    }.items():
        if _has_prediction(profile, target):
            categories[category] = _prediction(profile, target)
    return categories


def _available_categories(profiles: list[dict], role: str) -> set[str]:
    available = None
    for profile in profiles:
        if profile.get("role") != role:
            continue
        categories = set(project_categories(profile))
        available = categories if available is None else available & categories
    return available or set()


def _category_scoring_value(
    row: dict, role: str, category: str, raw_center: float
) -> float:
    value = row["categories"][category]
    if category not in RATIO_CATEGORIES[role]:
        return value
    return (value - raw_center) * row["projected_volume"]


def _normalize_categories(categories: dict) -> dict[str, float]:
    normalized = {}
    for category, weight in categories.items():
        value = float(weight)
        if value:
            normalized[str(category).upper()] = value
    return normalized


def adapt_categories(
    profiles: list[dict],
    *,
    name: str,
    categories: dict[str, dict[str, float]],
) -> dict:
    role_configs = {
        role: _normalize_categories(categories.get(role, {}))
        for role in ("hitter", "pitcher")
    }
    role_results = {}
    for role in ("hitter", "pitcher"):
        config = role_configs[role]
        role_profiles = [profile for profile in profiles if profile.get("role") == role]
        available = _available_categories(role_profiles, role)
        missing = sorted(set(config) - available)
        coverage = (len(config) - len(missing)) / len(config) if config else 0.0
        projected = [
            _adapter_row(profile, role, config)
            for profile in role_profiles
        ]
        complete = bool(config) and bool(projected) and not missing
        if complete:
            raw_centers = {
                category: mean(row["categories"][category] for row in projected)
                for category in config
            }
            scoring_values = {
                row["mlbam_id"]: {
                    category: _category_scoring_value(
                        row, role, category, raw_centers[category]
                    )
                    for category in config
                }
                for row in projected
            }
            centers = {
                category: mean(
                    scoring_values[row["mlbam_id"]][category] for row in projected
                )
                for category in config
            }
            spreads = {
                category: pstdev(
                    scoring_values[row["mlbam_id"]][category] for row in projected
                )
                or 1.0
                for category in config
            }
            for row in projected:
                row["adapter_score"] = round(
                    sum(
                        (scoring_values[row["mlbam_id"]][category] - centers[category])
                        / spreads[category]
                        * weight
                        for category, weight in config.items()
                    ),
                    4,
                )
            projected.sort(key=lambda row: (-row["adapter_score"], row["mlbam_id"]))
            for rank, row in enumerate(projected, 1):
                row["adapter_rank"] = rank
        role_results[role] = {
            "status": "research_ranked" if complete else "insufficient_category_coverage",
            "category_coverage": round(coverage, 4),
            "configured_categories": config,
            "supported_categories": sorted(set(config) & available),
            "missing_categories": missing,
            "candidate_count": len(projected),
            "players": projected,
        }
    return {
        "name": name,
        "status": (
            "research_ranked"
            if all(result["status"] == "research_ranked" for result in role_results.values())
            else "insufficient_category_coverage"
        ),
        "roles": role_results,
    }


def _adapter_row(profile: dict, role: str, config: dict) -> dict:
    projected = project_categories(profile)
    return {
        "mlbam_id": profile["mlbam_id"],
        "name": profile.get("name"),
        "role": role,
        "level": profile.get("level"),
        "age": profile.get("age"),
        "projected_volume": round(projected.get(VOLUME_CATEGORY[role], 0.0), 4),
        "categories": {
            category: round(value, 4)
            for category, value in projected.items()
            if category in config
        },
    }


def adapt_points(
    profiles: list[dict],
    *,
    name: str,
    hitter_weights: dict[str, float],
    pitcher_weights: dict[str, float],
) -> dict:
    """Points leagues use the same guarded category adapter with scoring weights."""
    return adapt_categories(
        profiles,
        name=name,
        categories={"hitter": hitter_weights, "pitcher": pitcher_weights},
    )


def build_adapter_artifact(universal: dict) -> dict:
    profiles = universal.get("profiles") or []
    presets = {
        key: adapt_categories(
            profiles,
            name=config["name"],
            categories={"hitter": config["hitter"], "pitcher": config["pitcher"]},
        )
        for key, config in PRESETS.items()
    }
    return {
        "status": "shadow_only",
        "adapter_version": ADAPTER_VERSION,
        "universal_model_name": universal.get("model_name"),
        "universal_model_version": universal.get("model_version"),
        "candidate_count": len(profiles),
        "rule": "No adapter rank is emitted unless every configured category is supported.",
        "scoring_contract": {
            "authority": "research_only",
            "rank_scope": "within_role",
            "counting_categories": (
                "establishment-adjusted projected volume times conditional rate"
            ),
            "ratio_categories": "centered rate impact times projected volume",
            "pitcher_role_split": (
                "rotation probability allocates QS versus SV+HLD production"
            ),
            "is_dynasty_value": False,
            "feeds_live_dd_value": False,
        },
        "supported_categories": {
            role: sorted(categories) for role, categories in SUPPORTED_CATEGORIES.items()
        },
        "presets": presets,
    }


def run_adapters(
    universal_path: Path = UNIVERSAL_ARTIFACT_PATH,
    artifact_path: Path = ARTIFACT_PATH,
) -> dict:
    universal = json.loads(universal_path.read_text(encoding="utf-8"))
    payload = build_adapter_artifact(universal)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = artifact_path.with_suffix(artifact_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, artifact_path)
    return {
        "artifact_path": str(artifact_path),
        "candidate_count": payload["candidate_count"],
        "preset_statuses": {
            name: preset["status"] for name, preset in payload["presets"].items()
        },
    }
