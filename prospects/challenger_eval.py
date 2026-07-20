"""Leak-free preparation for the registered normalized-production challenger."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from copy import deepcopy
from math import isfinite

from prospects.dynasty_backtest import OUTCOME_HORIZON_YEARS
from prospects.universal import _horizon_clipped_seasons

HITTER_RATE_FIELDS = ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip")
PITCHER_RATE_FIELDS = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
SAME_LEVEL_MIN_PEERS = 25
ROLE_SEASON_MIN_PEERS = 250
MIN_EXERCISED_COVERAGE = 0.90
REGISTERED_SEED = 33021
FORBIDDEN_SEEDS = {28013, 28017, 29001, 31013, 31017}
REGISTERED_FOLD_YEARS = (2016, 2017, 2018, 2019, 2021, 2022)

_RATE_FIELDS = {
    "hitter": HITTER_RATE_FIELDS,
    "pitcher": PITCHER_RATE_FIELDS,
}


def _loo_quantile(value: float, peers: list[float]) -> float:
    ordered = sorted(peers)
    left = bisect_left(ordered, value)
    right = bisect_right(ordered, value)
    return (left + right) / (2.0 * len(ordered))


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None


def _reference_season(row: dict) -> int | None:
    value = row.get("cohort_year")
    if value is None:
        value = row.get("sample_season")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _reference_level(row: dict) -> str:
    return str(row.get("level") or "").strip()


def _empty_diagnostics() -> dict:
    return {
        "rows": 0,
        "same_level_rows": 0,
        "backoff_rows": 0,
        "unavailable": 0,
        "available": 0,
        "exercised_coverage": 0.0,
        "_reference_counts": {
            name: {"cell_size": [], "other_peers": []}
            for name in ("same_level", "role_season")
        },
    }


def _finalize_diagnostics(diagnostics: dict) -> dict:
    finalized = dict(diagnostics)
    finalized["exercised_coverage"] = (
        finalized["available"] / finalized["rows"] if finalized["rows"] else 0.0
    )
    finalized["reference_counts"] = {}
    for name in ("same_level", "role_season"):
        counts = finalized["_reference_counts"][name]
        finalized["reference_counts"][name] = {
            kind: {
                "minimum": min(values) if values else None,
                "maximum": max(values) if values else None,
            }
            for kind, values in counts.items()
        }
    finalized.pop("_reference_counts")
    return finalized


def _record_reference_counts(
    diagnostics: dict, name: str, cell_size: int, peers: int
) -> None:
    diagnostics["_reference_counts"][name]["cell_size"].append(cell_size)
    diagnostics["_reference_counts"][name]["other_peers"].append(peers)


def normalize_rows(
    rows: list[dict],
    *,
    same_level_min: int = SAME_LEVEL_MIN_PEERS,
    role_season_min: int = ROLE_SEASON_MIN_PEERS,
) -> tuple[list[dict], dict]:
    """Replace factual rate fields with leave-one-out, season-local quantiles."""
    same_level: dict[tuple, list[tuple[tuple, float]]] = {}
    role_season: dict[tuple, list[tuple[tuple, float]]] = {}
    row_facts = []
    for row in rows:
        role = row.get("role")
        season = _reference_season(row)
        level = _reference_level(row)
        mlbam_id = row.get("mlbam_id")
        identity = (season, mlbam_id, role)
        fields = _RATE_FIELDS.get(role, ())
        usable_identity = season is not None and mlbam_id not in (None, "")
        values = {field: _number(row.get(field)) for field in fields}
        row_facts.append((row, role, season, identity, fields, usable_identity, values))
        if not usable_identity:
            continue
        for field, value in values.items():
            if value is None:
                continue
            if level:
                same_level.setdefault((role, season, level, field), []).append(
                    (identity, value)
                )
            role_season.setdefault((role, season, field), []).append((identity, value))

    fold_diagnostics: dict[str, dict[str, dict]] = {}
    overall = _empty_diagnostics()
    normalized = []
    for row, role, season, identity, fields, usable_identity, values in row_facts:
        fold = fold_diagnostics.setdefault(
            str(season) if season is not None else "unknown", {}
        )
        diagnostics = fold.setdefault(str(role or "unknown"), _empty_diagnostics())
        diagnostics["rows"] += 1
        overall["rows"] += 1
        transformed = dict(row)
        backed_off = False
        available = bool(fields) and usable_identity and all(
            value is not None for value in values.values()
        )
        for field in fields:
            level_entries = same_level.get(
                (role, season, _reference_level(row), field), []
            )
            level_peers = [
                value
                for peer_identity, value in level_entries
                if peer_identity != identity
            ]
            role_entries = role_season.get((role, season, field), [])
            role_peers = [
                value
                for peer_identity, value in role_entries
                if peer_identity != identity
            ]
            _record_reference_counts(
                diagnostics, "same_level", len(level_entries), len(level_peers)
            )
            _record_reference_counts(
                diagnostics, "role_season", len(role_entries), len(role_peers)
            )
            _record_reference_counts(
                overall, "same_level", len(level_entries), len(level_peers)
            )
            _record_reference_counts(
                overall, "role_season", len(role_entries), len(role_peers)
            )
            if not available:
                continue
            if len(level_peers) >= same_level_min:
                peers = level_peers
            elif len(role_peers) >= role_season_min:
                peers = role_peers
                backed_off = True
            else:
                available = False
                continue
            transformed[field] = _loo_quantile(values[field], peers)

        if available:
            key = "backoff_rows" if backed_off else "same_level_rows"
            diagnostics[key] += 1
            diagnostics["available"] += 1
            overall[key] += 1
            overall["available"] += 1
            normalized.append(transformed)
        else:
            diagnostics["unavailable"] += 1
            overall["unavailable"] += 1

    years = set(fold_diagnostics)
    for year in years:
        for role in _RATE_FIELDS:
            fold_diagnostics[year].setdefault(role, _empty_diagnostics())
    reference_years = {
        year: {role: _finalize_diagnostics(values) for role, values in roles.items()}
        for year, roles in fold_diagnostics.items()
    }
    folds = {}
    for year in REGISTERED_FOLD_YEARS:
        key = str(year)
        folds[key] = reference_years.get(key) or {
            role: _finalize_diagnostics(_empty_diagnostics())
            for role in _RATE_FIELDS
        }
    overall = _finalize_diagnostics(overall)
    return normalized, {
        **overall,
        "overall": overall,
        "folds": folds,
        "reference_years": reference_years,
    }


def fold_local_contract(contract: dict, test_year: int) -> dict:
    train_through = test_year - OUTCOME_HORIZON_YEARS
    training_rows = [
        row
        for row in contract["historical"]["rows"]
        if int(row.get("cohort_year") or 9999) <= train_through
    ]
    cohort_by_key = {}
    for row in training_rows:
        key = f"{row['mlbam_id']}_{row['role']}"
        year = int(row["cohort_year"])
        cohort_by_key[key] = min(year, cohort_by_key.get(key, year))
    clipped = _horizon_clipped_seasons(
        training_rows,
        contract.get("historical_mlb_seasons") or {},
    )

    def within_horizon(key: str, season: dict) -> bool:
        try:
            return int(season.get("year")) <= cohort_by_key[key] + OUTCOME_HORIZON_YEARS
        except (TypeError, ValueError):
            return False

    fold = deepcopy(contract)
    fold["historical_mlb_seasons"] = {
        key: [season for season in clipped[key] if within_horizon(key, season)]
        for key in clipped
        if key in cohort_by_key
    }
    return fold


def _identity(row: dict) -> tuple[int, object, str] | None:
    role = row.get("role")
    mlbam_id = row.get("mlbam_id")
    try:
        cohort_year = int(row["cohort_year"])
    except (KeyError, TypeError, ValueError):
        return None
    if role not in _RATE_FIELDS or mlbam_id in (None, ""):
        return None
    return cohort_year, mlbam_id, role


def prepare_fold(contract: dict, test_year: int) -> dict:
    """Prepare identity-matched fold contracts without training or scoring."""
    candidate_rows, diagnostics = normalize_rows(contract["historical"]["rows"])
    candidate_identities = {_identity(row) for row in candidate_rows}
    candidate_identities.discard(None)
    control_rows = [
        row
        for row in contract["historical"]["rows"]
        if _identity(row) in candidate_identities
    ]
    control_contract = deepcopy(contract)
    control_contract["historical"]["rows"] = control_rows
    candidate_contract = deepcopy(contract)
    candidate_contract["historical"]["rows"] = candidate_rows
    control_contract = fold_local_contract(control_contract, test_year)
    candidate_contract = fold_local_contract(candidate_contract, test_year)

    common_identities = {}
    for role in _RATE_FIELDS:
        control = {
            _identity(row)
            for row in control_contract["historical"]["rows"]
            if int(row.get("cohort_year") or -1) == test_year
            and row.get("role") == role
        }
        candidate = {
            _identity(row)
            for row in candidate_contract["historical"]["rows"]
            if int(row.get("cohort_year") or -1) == test_year
            and row.get("role") == role
        }
        if control != candidate:
            raise ValueError(
                f"fold {test_year} {role}: Control/candidate identity sets differ"
            )
        common_identities[role] = [list(identity) for identity in sorted(candidate)]

    coverage = diagnostics["reference_years"].get(str(test_year), {})
    return {
        "control_contract": control_contract,
        "candidate_contract": candidate_contract,
        "common_identities": common_identities,
        "coverage": {
            role: coverage.get(role, _finalize_diagnostics(_empty_diagnostics()))
            for role in _RATE_FIELDS
        },
    }
