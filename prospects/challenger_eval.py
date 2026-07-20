"""Leak-free preparation for the registered normalized-production challenger."""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from copy import deepcopy
from math import isfinite
from statistics import mean

from prospects.competition_benchmark import (
    _percentile_ranks,
    build_cohort,
    build_track,
)
from prospects.dynasty_backtest import OUTCOME_COMPLETE_THROUGH, OUTCOME_HORIZON_YEARS
from prospects.model import (
    _active_impact_categories,
    _impact_references,
    _impact_target,
    build_shadow_model,
)
from prospects.rank_backtest import _fold_board_scores
from prospects.universal import _horizon_clipped_seasons

HITTER_RATE_FIELDS = ("iso", "k_pct", "bb_pct", "ops", "avg", "obp", "slg", "babip")
PITCHER_RATE_FIELDS = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
SAME_LEVEL_MIN_PEERS = 25
ROLE_SEASON_MIN_PEERS = 250
MIN_EXERCISED_COVERAGE = 0.90
REGISTERED_SEED = 33021
FORBIDDEN_SEEDS = {28013, 28017, 29001, 31013, 31017}
REGISTERED_FOLD_YEARS = (2016, 2017, 2018, 2019, 2021, 2022)
FULL_SEASON_AFFILIATED_LEVELS = {"A", "A+", "AA", "AAA"}

_RATE_FIELDS = {
    "hitter": HITTER_RATE_FIELDS,
    "pitcher": PITCHER_RATE_FIELDS,
}


class RegisteredLookSpentError(ValueError):
    """Failure raised after outcome scoring starts, carrying the spent record."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def _spent_failure(coverage: dict, failure: str, identity_set_equal=None) -> dict:
    return {
        "status": "collecting",
        "registered_look_spent": True,
        "identity_set_equal": identity_set_equal,
        "coverage": coverage,
        "role_results": {},
        "failure": failure,
        "claim_authorized": False,
        "public_claim_eligible": False,
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


def _omitted_years(contract: dict) -> set[int]:
    raw = contract["historical"].get("omitted_cohorts") or []
    if isinstance(raw, dict):
        raw = [raw]
    return {
        int(item["year"] if isinstance(item, dict) else item)
        for item in raw
    }


def eligible_fold_years(contract: dict) -> list[int]:
    """Derive all and only mature folds with a full prior training horizon."""
    cohorts = sorted({int(year) for year in contract["historical"]["cohorts"]})
    earliest = min(cohorts)
    omitted = _omitted_years(contract)
    return [
        year
        for year in cohorts
        if year <= OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS
        and year - OUTCOME_HORIZON_YEARS >= earliest
        and year not in omitted
    ]


def _mlbam_sort(value: object) -> tuple[int, object]:
    try:
        return 0, int(value)
    except (TypeError, ValueError):
        return 1, str(value)


def _row_index(contract: dict, year: int) -> dict[tuple[str, str], dict]:
    return {
        (str(row["mlbam_id"]), row["role"]): row
        for row in contract.get("historical", {}).get("rows", [])
        if int(row.get("cohort_year") or -1) == year
        and row.get("mlbam_id") not in (None, "")
        and row.get("role") in _RATE_FIELDS
    }


def _ranked_rows(
    scores: dict, role: str, metadata: dict[tuple[str, str], dict]
) -> list[dict]:
    keys = sorted(
        (key for key in scores if key[1] == role),
        key=lambda key: (-float(scores[key]), _mlbam_sort(key[0])),
    )
    return [
        {
            "mlbam_id": int(key[0]),
            "name": metadata.get(key, {}).get("name"),
            "role": role,
            "rank": rank,
        }
        for rank, key in enumerate(keys, 1)
    ]


def _rename_benchmark_labels(value):
    if isinstance(value, dict):
        return {
            key.replace("valucast", "normalized_production").replace(
                "competitor", "control"
            ): _rename_benchmark_labels(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_rename_benchmark_labels(item) for item in value]
    return value


def _finalize_track(track: dict, registration: dict) -> dict:
    status_contract = registration["final_artifact_status_contract"]
    final = _rename_benchmark_labels(track)
    final["status"] = status_contract["top_level_status_mapping"][track["status"]]
    final["statistical_status"] = status_contract["statistical_status_mapping"][
        track["statistical_status"]
    ]
    final["claim_authorized"] = False
    final["public_claim_eligible"] = False
    if final["status"] not in status_contract["allowed_final_status_values"]:
        raise ValueError(f"forbidden final status: {final['status']}")
    if final["statistical_status"] not in status_contract["allowed_final_status_values"]:
        raise ValueError(
            f"forbidden final statistical status: {final['statistical_status']}"
        )
    return final


def _ordinal_subset(
    control_ranks: dict[tuple[str, str], int],
    candidate_ranks: dict[tuple[str, str], int],
    tiers: dict,
    keys: list[tuple[str, str]],
) -> dict:
    if not keys:
        return {
            "players": 0,
            "control_error": None,
            "normalized_production_error": None,
            "control_minus_normalized_production_error": None,
        }
    actual = _percentile_ranks([float(tiers[key]) for key in keys], higher_is_better=True)
    control = _percentile_ranks(
        [float(control_ranks[key]) for key in keys], higher_is_better=False
    )
    candidate = _percentile_ranks(
        [float(candidate_ranks[key]) for key in keys], higher_is_better=False
    )
    control_error = mean(abs(left - right) for left, right in zip(control, actual))
    candidate_error = mean(abs(left - right) for left, right in zip(candidate, actual))
    return {
        "players": len(keys),
        "control_error": round(control_error, 6),
        "normalized_production_error": round(candidate_error, 6),
        "control_minus_normalized_production_error": round(
            control_error - candidate_error, 6
        ),
    }


def _under_19_report(scored_folds: dict[int, dict]) -> dict:
    roles = {}
    for role in _RATE_FIELDS:
        folds = []
        for year, fold in sorted(scored_folds.items()):
            metadata = fold["metadata"]
            keys = [
                key
                for key in fold["control_ranks"]
                if key[1] == role
                and _number(metadata.get(key, {}).get("age")) is not None
                and float(metadata[key]["age"]) < 19
                and str(metadata[key].get("level") or "").upper()
                in FULL_SEASON_AFFILIATED_LEVELS
            ]
            folds.append(
                {
                    "fold_year": year,
                    **_ordinal_subset(
                        fold["control_ranks"],
                        fold["candidate_ranks"],
                        fold["tiers"],
                        keys,
                    ),
                }
            )
        roles[role] = {
            "players": sum(fold["players"] for fold in folds),
            "folds": folds,
        }
    return {
        "scope": "age_under_19_full_season_affiliated_levels",
        "independent_verdict": False,
        "roles": roles,
    }


def _position_report(scored_folds: dict[int, dict], registration: dict) -> dict:
    audit_contract = registration["hitter_position_audit"]
    allowed = set(audit_contract["allowed_raw_labels"])
    delimiters = tuple(audit_contract["reject_delimiters"])
    audit_folds = []
    positions_by_player: dict[str, set[str]] = {}
    invalid = []
    for year, fold in sorted(scored_folds.items()):
        keys = [key for key in fold["control_ranks"] if key[1] == "hitter"]
        positions = []
        for key in keys:
            position = str(fold["metadata"].get(key, {}).get("position") or "").strip()
            if position:
                positions.append(position)
                positions_by_player.setdefault(key[0], set()).add(position)
            if position and (position not in allowed or any(d in position for d in delimiters)):
                invalid.append({"fold_year": year, "mlbam_id": key[0], "position": position})
        coverage = len(positions) / len(keys) if keys else 0.0
        audit_folds.append(
            {
                "fold_year": year,
                "hitters": len(keys),
                "non_null": len(positions),
                "non_null_coverage": round(coverage, 6),
            }
        )
    inconsistent = sorted(
        mlbam_id for mlbam_id, positions in positions_by_player.items() if len(positions) > 1
    )
    failed = (
        invalid
        or inconsistent
        or any(
            fold["non_null_coverage"]
            < float(audit_contract["minimum_non_null_coverage_each_fold"])
            for fold in audit_folds
        )
    )
    audit = {
        "folds": audit_folds,
        "invalid_raw_labels": invalid,
        "inconsistent_player_ids": inconsistent,
    }
    if failed:
        return {"status": "omitted_failed_position_semantics", "audit": audit}

    groups = {}
    for position in sorted(allowed):
        folds = []
        for year, fold in sorted(scored_folds.items()):
            keys = [
                key
                for key in fold["control_ranks"]
                if key[1] == "hitter"
                and str(fold["metadata"].get(key, {}).get("position") or "").strip()
                == position
            ]
            if keys:
                folds.append(
                    {
                        "fold_year": year,
                        **_ordinal_subset(
                            fold["control_ranks"],
                            fold["candidate_ranks"],
                            fold["tiers"],
                            keys,
                        ),
                    }
                )
        if folds:
            groups[position] = {
                "players": sum(fold["players"] for fold in folds),
                "folds": folds,
            }
    return {
        "included": True,
        "independent_verdict": False,
        "raw_labels_only": True,
        "audit": audit,
        "groups": groups,
    }


def _partial_impact_report(
    contract: dict, scored_folds: dict[int, dict]
) -> dict:
    seasons = contract.get("historical_mlb_seasons")
    if not seasons:
        return {"available": False, "reason": "historical_mlb_seasons_unavailable"}
    references = _impact_references(seasons)
    report = {}
    for role in _RATE_FIELDS:
        folds = []
        for year, fold in scored_folds.items():
            outcomes = {}
            for key, row in fold["metadata"].items():
                if key[1] == role and key in fold["control_ranks"]:
                    outcomes[key] = _impact_target(
                        row, role, seasons, references
                    )
            keys = sorted(outcomes, key=lambda key: _mlbam_sort(key[0]))
            folds.append(
                {
                    "fold_year": year,
                    **_ordinal_subset(
                        fold["control_ranks"],
                        fold["candidate_ranks"],
                        outcomes,
                        keys,
                    ),
                }
            )
        completed = [fold for fold in folds if fold["players"]]
        report[role] = {
            "available_categories": list(_active_impact_categories(references, role)),
            "direct_7x7": False,
            "players": sum(fold["players"] for fold in completed),
            "primary": {
                field: round(mean(fold[field] for fold in completed), 6)
                if completed
                else None
                for field in (
                    "control_error",
                    "normalized_production_error",
                    "control_minus_normalized_production_error",
                )
            },
            "folds": folds,
        }
    return {
        "available": True,
        "metric": "partial_category_best_season_impact_rank_error",
        "independent_verdict": False,
        "limitation": "Uses only the available historical fantasy categories; it is not direct 7x7 realized value.",
        "roles": report,
    }


def run_registered_replay(contract: dict, registration: dict) -> dict:
    """Run the frozen comparison after every reference-fold coverage check passes."""
    reference_years = [int(year) for year in registration["reference_fold_years"]]
    prepared = {year: prepare_fold(contract, year) for year in reference_years}
    coverage = {
        str(year): prepared[year]["coverage"]
        for year in reference_years
    }
    minimum_coverage = float(registration["minimum_exercised_coverage"])
    failures = [
        {"fold_year": year, "role": role, "exercised_coverage": values[role]["exercised_coverage"]}
        for year, values in ((year, prepared[year]["coverage"]) for year in reference_years)
        for role in _RATE_FIELDS
        if float(values[role]["exercised_coverage"]) < minimum_coverage
    ]
    if failures:
        return {
            "status": "invalid_coverage",
            "registered_look_spent": False,
            "coverage": coverage,
            "coverage_failures": failures,
            "identity_set_equal": None,
            "claim_authorized": False,
            "public_claim_eligible": False,
        }

    scored_years = eligible_fold_years(contract)
    if scored_years != [int(year) for year in registration["scored_fold_years"]]:
        raise ValueError("derived scored folds differ from frozen registration")
    if not set(scored_years) <= set(reference_years):
        raise ValueError("scored folds must be covered reference folds")

    cohorts_by_role = {role: [] for role in _RATE_FIELDS}
    outcomes_by_role = {role: {} for role in _RATE_FIELDS}
    scored_folds = {}
    scorer_diagnostics = {}
    for year in scored_years:
        fold = prepared[year]
        try:
            control, control_diagnostics = _fold_board_scores(
                fold["control_contract"], year
            )
            candidate, candidate_diagnostics = _fold_board_scores(
                fold["candidate_contract"], year
            )
        except Exception as error:
            raise RegisteredLookSpentError(
                f"fold {year}: scorer failed after the registered look began: {error}",
                _spent_failure(coverage, "scoring_error"),
            ) from error
        control_keys = set(control["scores"])
        candidate_keys = set(candidate["scores"])
        if control_keys != candidate_keys:
            raise RegisteredLookSpentError(
                f"fold {year}: identity sets differ after scoring",
                _spent_failure(
                    coverage, "post_score_identity_mismatch", False
                ),
            )
        if set(control["tiers"]) != control_keys or set(candidate["tiers"]) != candidate_keys:
            raise RegisteredLookSpentError(
                f"fold {year}: score and outcome identity sets differ",
                _spent_failure(
                    coverage, "post_score_outcome_identity_mismatch", False
                ),
            )
        if any(control["tiers"][key] != candidate["tiers"][key] for key in control_keys):
            raise RegisteredLookSpentError(
                f"fold {year}: Control/candidate outcomes differ",
                _spent_failure(coverage, "post_score_outcome_mismatch", False),
            )

        metadata = _row_index(fold["control_contract"], year)
        control_rows = {
            role: _ranked_rows(control["scores"], role, metadata)
            for role in _RATE_FIELDS
        }
        candidate_rows = {
            role: _ranked_rows(candidate["scores"], role, metadata)
            for role in _RATE_FIELDS
        }
        control_ranks = {
            (str(row["mlbam_id"]), role): row["rank"]
            for role, rows in control_rows.items()
            for row in rows
        }
        candidate_ranks = {
            (str(row["mlbam_id"]), role): row["rank"]
            for role, rows in candidate_rows.items()
            for row in rows
        }
        scored_folds[year] = {
            "metadata": metadata,
            "tiers": control["tiers"],
            "control_ranks": control_ranks,
            "candidate_ranks": candidate_ranks,
        }
        scorer_diagnostics[str(year)] = {
            "control": control_diagnostics,
            "normalized_production": candidate_diagnostics,
        }
        for role in _RATE_FIELDS:
            cohort = build_cohort(
                cohort_id=str(year),
                registered_at=registration["registered_at"],
                track=f"prospect_{role}",
                valucast_rows=candidate_rows[role],
                competitor_rows=control_rows[role],
                sources={
                    "normalized_production": f"registered_fold_{year}",
                    "control": f"registered_fold_{year}",
                },
            )
            cohorts_by_role[role].append(cohort)
            outcomes_by_role[role].update(
                {
                    f"{year}:{key[0]}": float(control["tiers"][key])
                    for key in control_keys
                    if key[1] == role
                }
            )

    try:
        criteria = registration["adjudication"]["build_track_criteria"]
        role_results = {
            role: _finalize_track(
                build_track(cohorts_by_role[role], outcomes_by_role[role], criteria),
                registration,
            )
            for role in _RATE_FIELDS
        }
        return {
            "status": registration["final_artifact_status_contract"][
                "top_level_status_mapping"
            ]["research_only"],
            "registered_look_spent": True,
            "identity_set_equal": True,
            "coverage": coverage,
            "scored_fold_years": scored_years,
            "scorer_diagnostics": scorer_diagnostics,
            "role_results": role_results,
            "under_19": _under_19_report(scored_folds),
            "hitter_position": _position_report(scored_folds, registration),
            "partial_category_best_season_impact": _partial_impact_report(
                contract, scored_folds
            ),
            "realized_value_regret": {
                "calculated": False,
                "reason": "blocked_by_registered_realized_value_readiness",
            },
            "claim_authorized": False,
            "public_claim_eligible": False,
        }
    except RegisteredLookSpentError:
        raise
    except Exception as error:
        raise RegisteredLookSpentError(
            f"registered evaluation failed after scoring: {error}",
            _spent_failure(coverage, "post_score_evaluation_error", True),
        ) from error


def _current_identity(row: dict) -> tuple[int, str, object, str] | None:
    try:
        mlbam_id = int(row["mlbam_id"])
    except (KeyError, TypeError, ValueError):
        return None
    role = row.get("role")
    if role not in _RATE_FIELDS:
        return None
    return mlbam_id, role, row.get("sample_season"), str(row.get("level") or "")


def score_current_variants(contract: dict) -> tuple[dict, dict, dict]:
    """Build current Control/candidate model-component research ranks."""
    historical_rows = contract["historical"]["rows"]
    current_rows = list(contract["current"].get("hitters") or []) + list(
        contract["current"].get("pitchers") or []
    )
    candidate_history, historical_coverage = normalize_rows(historical_rows)
    candidate_current, current_coverage = normalize_rows(current_rows)
    historical_identities = {_identity(row) for row in candidate_history}
    current_identities = {_current_identity(row) for row in candidate_current}

    control_contract = deepcopy(contract)
    control_contract["historical"]["rows"] = [
        row for row in historical_rows if _identity(row) in historical_identities
    ]
    candidate_contract = deepcopy(contract)
    candidate_contract["historical"]["rows"] = candidate_history
    for target, source in (
        (control_contract, current_rows),
        (candidate_contract, candidate_current),
    ):
        target["current"]["hitters"] = [
            row
            for row in source
            if row.get("role") == "hitter" and _current_identity(row) in current_identities
        ]
        target["current"]["pitchers"] = [
            row
            for row in source
            if row.get("role") == "pitcher" and _current_identity(row) in current_identities
        ]

    now = f"{contract['current']['fetched_date']}T23:59:59+00:00"
    control_model = build_shadow_model(control_contract, now=now)
    candidate_model = build_shadow_model(candidate_contract, now=now)

    def ranks(model: dict) -> tuple[dict[tuple[int, str], int], dict[str, int]]:
        identities = {
            (int(row["mlbam_id"]), row["role"]): int(row["valucast_prospect_rank"])
            for row in model["ranked"]
        }
        if len({mlbam_id for mlbam_id, _ in identities}) != len(identities):
            raise ValueError("current model contains a cross-role MLBAM identity collision")
        return identities, {str(mlbam_id): rank for (mlbam_id, _), rank in identities.items()}

    control_identities, control = ranks(control_model)
    candidate_identities, candidate = ranks(candidate_model)
    if set(control_identities) != set(candidate_identities):
        raise ValueError("current Control/candidate identity sets differ")
    available_ids = {str(identity[0]) for identity in current_identities if identity}
    all_ids = {
        str(identity[0])
        for row in current_rows
        if (identity := _current_identity(row)) is not None
    }
    return control, candidate, {
        "historical": historical_coverage,
        "current": current_coverage,
        "identity_set_equal": True,
        "ranked_identities": len(control),
        "unavailable_current_identities": sorted(all_ids - available_ids, key=_mlbam_sort),
    }


_HITTER_AAA_FIELDS = (
    "whiff_pct",
    "chase_pct",
    "gb_pct",
    "avg_ev",
    "max_ev",
    "hardhit_pct",
    "avg_la",
)
_PITCHER_AAA_FIELDS = ("whiff_pct", "csw_pct", "zone_pct", "chase_pct", "gb_pct")


def build_aaa_disagreement(
    control_scores: dict,
    candidate_scores: dict,
    aaa: dict,
    current_rows: list[dict],
) -> dict:
    """Join rank disagreement to measured AAA components without imputation."""
    groups = {
        name: {"rows": []}
        for name in ("hitter", "pitcher_starter", "pitcher_reliever")
    }
    missing_ids = []
    missing_role_context_ids = []
    common_ids = set(control_scores) & set(candidate_scores)
    aaa_rows = {
        str(row["mlbam_id"]): row
        for row in current_rows
        if str(row.get("level") or "").upper() == "AAA"
        and row.get("mlbam_id") not in (None, "")
        and str(row["mlbam_id"]) in common_ids
    }
    for mlbam_id in sorted(aaa_rows, key=_mlbam_sort):
        current = aaa_rows[mlbam_id]
        role = current.get("role")
        measured = (aaa.get("hitters") if role == "hitter" else aaa.get("pitchers")) or {}
        features = measured.get(mlbam_id)
        if not features:
            missing_ids.append(mlbam_id)
            continue
        if role == "hitter":
            group = "hitter"
            components = {
                field: features[field]
                for field in _HITTER_AAA_FIELDS
                if features.get(field) is not None
            }
            reliability = {
                field: features[field]
                for field in ("n_pitches", "n_bip")
                if features.get(field) is not None
            }
        elif role == "pitcher":
            if current.get("is_starter") not in (True, False):
                missing_role_context_ids.append(mlbam_id)
                continue
            group = "pitcher_starter" if current["is_starter"] else "pitcher_reliever"
            overall = features.get("overall") or {}
            components = {
                "overall": {
                    field: overall[field]
                    for field in _PITCHER_AAA_FIELDS
                    if overall.get(field) is not None
                },
                "pitch_types": {
                    pitch_type: {
                        key: value
                        for key, value in values.items()
                        if value is not None
                    }
                    for pitch_type, values in sorted(
                        (features.get("pitch_types") or {}).items()
                    )
                },
            }
            reliability = {
                "n_pitches": features["n_pitches"]
            } if features.get("n_pitches") is not None else {}
        else:
            continue
        groups[group]["rows"].append(
            {
                "mlbam_id": int(mlbam_id),
                "name": current.get("name"),
                "control_rank": control_scores[mlbam_id],
                "normalized_production_rank": candidate_scores[mlbam_id],
                "rank_delta": candidate_scores[mlbam_id] - control_scores[mlbam_id],
                "reliability": reliability,
                "components": components,
            }
        )
    for group in groups.values():
        group["rows"].sort(
            key=lambda row: (-abs(row["rank_delta"]), row["mlbam_id"])
        )
        group["count"] = len(group["rows"])
    return {
        "qualification_gates": deepcopy(aaa.get("gates") or {}),
        "eligible_current_aaa_count": len(aaa_rows),
        "measured_count": sum(group["count"] for group in groups.values()),
        "missing_statcast_count": len(missing_ids),
        "missing_ids": missing_ids,
        "missing_starter_reliever_context_count": len(missing_role_context_ids),
        "missing_starter_reliever_context_ids": missing_role_context_ids,
        "groups": groups,
        "interpretation": (
            "Raw measured components and rank disagreement only. Strong pitch traits do not imply "
            "starter volume, health, availability, future MLB innings, or opportunity. No missing "
            "component is zero-filled; every measurement remains separate."
        ),
        "snapshot_policy": (
            "Promotion and demotion are distinct dated observations; this snapshot infers no "
            "direction, transaction date, reason, or pre/post split."
        ),
    }
