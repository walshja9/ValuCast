"""No-outcome readiness checks for registered prospect challengers."""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from datetime import date
from typing import Any

from prospects.input_contract import validate_factual_contract
from prospects.model import EXPECTED_AGE, LEVEL_CODE

RAW_GUARD_FIELDS = frozenset(
    {
        "age",
        "level",
        "plate_appearances",
        "innings_pitched",
        "games_played",
        "games_started",
        "sample_season",
    }
)
MODEL_FEATURE_NAMESPACE = "fold_local_transformed_features"
NOT_BEFORE = "2027-01-01"
POSITION_VALUE = {
    "C": 1.0,
    "SS": 0.95,
    "CF": 0.80,
    "2B": 0.65,
    "3B": 0.55,
    "RF": 0.40,
    "LF": 0.30,
    "1B": 0.15,
    "DH": 0.0,
}


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def development_density_features(row: dict, role: str) -> tuple[float, ...]:
    games = _number(row.get("games_played")) or 0.0
    if role == "hitter":
        pa = _number(row.get("plate_appearances")) or 0.0
        return (pa / games if games > 0 else 0.0, min(1.0, games / 132.0))
    if role == "pitcher":
        innings = _number(row.get("innings_pitched")) or 0.0
        return (innings / games if games > 0 else 0.0,)
    raise ValueError("role must be hitter or pitcher")


def position_value_features(row: dict) -> tuple[float, float, float]:
    position = str(row.get("position") or "").upper()
    level = str(row.get("level") or "").upper()
    age = _number(row.get("age")) or 0.0
    position_value = POSITION_VALUE.get(position, 0.5)
    level_value = LEVEL_CODE.get(level, 0.0)
    youth = EXPECTED_AGE.get(level, age) - age
    return (
        position_value,
        position_value * youth,
        position_value * level_value,
    )


def _definition_hash(name: str) -> str:
    definitions = {
        "development_density": {
            "hitter": ["plate_appearances/games_played", "min(1,games_played/132)"],
            "pitcher": ["innings_pitched/games_played"],
            "missing": "zero_per_registration",
        },
        "position_value_x": {
            "position_value": POSITION_VALUE,
            "unknown_position": 0.5,
            "level_code": LEVEL_CODE,
            "expected_age": EXPECTED_AGE,
            "output": ["p", "p*youth", "p*level"],
        },
    }
    encoded = json.dumps(definitions[name], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _aaa_rows(payload: dict | None) -> list[dict]:
    if isinstance((payload or {}).get("rows"), list):
        return [row for row in payload["rows"] if isinstance(row, dict)]
    rows = []
    for bucket, role in (("hitters", "hitter"), ("pitchers", "pitcher")):
        for mlbam_id, metrics in ((payload or {}).get(bucket) or {}).items():
            if not isinstance(metrics, dict):
                continue
            row = {"mlbam_id": mlbam_id, "role": role}
            row.update(metrics.get("overall") or metrics)
            rows.append(row)
    return rows


def _context_challenger_readiness(rows: list[dict], look_spent: bool) -> dict:
    role_counts = Counter(
        str(row.get("role"))
        for row in rows
        if row.get("role") in {"hitter", "pitcher"}
    )
    # Exercise the exact frozen functions; no outcome field is read.
    for row in rows:
        role = row.get("role")
        if role in {"hitter", "pitcher"}:
            development_density_features(row, role)
        if role == "hitter":
            position_value_features(row)
    return {
        "development_density": {
            "definition_sha256": _definition_hash("development_density"),
            "role_rows": dict(sorted(role_counts.items())),
            "feature_width": {"hitter": 2, "pitcher": 1},
        },
        "position_value_x": {
            "definition_sha256": _definition_hash("position_value_x"),
            "role_rows": {"hitter": role_counts.get("hitter", 0)},
            "feature_width": {"hitter": 3},
        },
        "confirmatory_scoring_authorized": False,
        "registered_look_spent": bool(look_spent),
    }


def build_plan034_readiness(
    contract: dict,
    registration: dict,
    aaa_features: dict | None,
    *,
    as_of: str,
) -> dict:
    contract_problems = validate_factual_contract(contract)
    if contract_problems:
        raise ValueError("invalid factual contract: " + "; ".join(contract_problems))
    rows = list((contract.get("historical") or {}).get("rows") or [])
    keys = [
        f"{row.get('cohort_year')}:{row.get('mlbam_id')}:{row.get('role')}"
        for row in rows
    ]
    duplicates = sorted(key for key, count in Counter(keys).items() if count > 1)
    role_counts = Counter(
        str(row.get("role"))
        for row in rows
        if row.get("role") in {"hitter", "pitcher"}
    )
    aaa_rows = _aaa_rows(aaa_features)
    aaa_rows_by_role = {
        role: [row for row in aaa_rows if row.get("role") == role]
        for role in ("hitter", "pitcher")
    }
    aaa_fields_by_role = {
        role: sorted(
            set().union(*(row.keys() for row in role_rows)) - {"mlbam_id", "role"}
        )
        if role_rows
        else []
        for role, role_rows in aaa_rows_by_role.items()
    }
    missing_by_role_field = {
        role: {
            field: sum(row.get(field) is None for row in aaa_rows_by_role[role])
            for field in fields
        }
        for role, fields in aaa_fields_by_role.items()
    }
    missing_by_field = {
        field: sum(
            missing_by_role_field[role].get(field, 0)
            for role in missing_by_role_field
        )
        for field in sorted(set().union(*aaa_fields_by_role.values()))
    }
    trigger = registration.get("execution_trigger") or {}
    not_before = str(trigger.get("not_before") or NOT_BEFORE)
    before_trigger = date.fromisoformat(as_of) < date.fromisoformat(not_before)
    blockers = []
    if before_trigger:
        blockers.append(f"not_before:{not_before}")
    if duplicates:
        blockers.append("duplicate_cohort_role_identity")
    if trigger.get("requires_2026_mlb_season_complete") is True:
        blockers.append("2026_mlb_season_completion_not_attested")
    if trigger.get("requires_2022_cohort_four_year_horizon_complete") is True:
        blockers.append("2022_four_year_horizon_not_attested")
    if trigger.get("requires_reviewed_implementation_amendment") is True:
        blockers.append("reviewed_implementation_amendment_missing")
    return {
        "artifact": "valucast_prospect_challenger_readiness",
        "schema_version": "1.0.0",
        "as_of": as_of,
        "protocol": registration.get("protocol"),
        "status": "waiting_for_vintage" if before_trigger else "blocked_readiness",
        "blockers": blockers,
        "outer_scoring_authorized": False,
        "identity_audit": {
            "identity_key": "cohort_year:mlbam_id:role",
            "row_count": len(rows),
            "role_counts": dict(sorted(role_counts.items())),
            "duplicates": duplicates,
        },
        "input_contract": {"valid": True, "problems": []},
        "aaa_statcast": {
            "row_count": len(aaa_rows),
            "missing_by_field": missing_by_field,
            "missing_by_role_field": missing_by_role_field,
            "missing_value_policy": "preserve_null_never_zero_fill",
            "zero_filled_count": 0,
        },
        "raw_guard_fields": sorted(RAW_GUARD_FIELDS),
        "model_feature_namespace": MODEL_FEATURE_NAMESPACE,
        "registered_context_challengers": _context_challenger_readiness(
            rows, bool(registration.get("look_spent"))
        ),
        "source_policy": {
            "research_only": True,
            "reads_outcomes": False,
            "feeds_rank_or_value": False,
            "feeds_pitcher_cap": False,
            "feeds_role_watch": False,
            "feeds_publication": False,
            "authorizes_claim": False,
        },
    }


def assert_no_outer_scoring(report: dict) -> None:
    if report.get("outer_scoring_authorized") is True:
        raise RuntimeError("outer scoring is not authorized")
