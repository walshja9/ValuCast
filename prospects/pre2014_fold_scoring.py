"""Leak-safe fold scoring seams for the pre-2014 cross-role adjudicator.

This module performs no file I/O.  The single-use gate owns artifact reservation
and outcome-file access; callers inject an already loaded extended factual
contract and a Rank-v1 scorer.  The default raw-head scorer is the production
prospect model path, while tests can inject a deterministic scorer without
touching sealed outcomes.
"""
from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from prospects.common_target_calibration import (
    apply_common_target_calibrators,
    build_role_calibrator,
)
from prospects.direct_7x7 import (
    DirectValueError,
    build_fold_references,
    direct_7x7_target as _strict_direct_7x7_target,
    join_quality_starts as _strict_join_quality_starts,
)
from prospects.extended_history import outcome_label
from prospects.model import (
    OUTCOME_HORIZON_YEARS,
    OUTCOME_TARGET,
)


CANDIDATE_MODEL_FLAGS = {
    "PITCHER_INVESTMENT_FEATURE_MODE": "drop_raw_pick_value"
}
INCUMBENT_MODEL_FLAGS = {"PITCHER_INVESTMENT_FEATURE_MODE": "incumbent"}
ROLES = ("hitter", "pitcher")


class FoldScoringError(ValueError):
    """Raised when a fold would violate the fixed factual scoring contract."""


RawScorer = Callable[..., tuple[list[dict], dict]]
RankScorer = Callable[..., tuple[Mapping[tuple[str, str], float], dict]]


def _identity(row: Mapping[str, Any]) -> tuple[str, str]:
    role = str(row.get("role") or "")
    mlbam_id = row.get("mlbam_id")
    if role not in ROLES or mlbam_id in (None, ""):
        raise FoldScoringError("every row requires mlbam_id and hitter/pitcher role")
    return str(mlbam_id), role


def _season_key(row: Mapping[str, Any]) -> str:
    mlbam_id, role = _identity(row)
    return f"{mlbam_id}_{role}"


def _sha256(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _rows(contract: Mapping[str, Any]) -> list[dict]:
    source = contract.get("rows")
    if source is None:
        source = (contract.get("historical") or {}).get("rows")
    if not isinstance(source, list) or not source:
        raise FoldScoringError("extended factual contract has no historical rows")
    return copy.deepcopy(source)


def _seasons(contract: Mapping[str, Any]) -> dict[str, list[dict]]:
    source = contract.get("historical_mlb_seasons")
    if source is None:
        source = contract.get("mlb_seasons")
    if not isinstance(source, Mapping):
        raise FoldScoringError("extended factual contract has no MLB seasons")
    return {
        str(key): copy.deepcopy(list(value or []))
        for key, value in source.items()
    }


def _join_quality_starts(
    seasons: Mapping[str, list[dict]],
    sidecar: Mapping[str, Any] | None,
) -> tuple[dict[str, list[dict]], str | None]:
    if sidecar is None:
        return copy.deepcopy(dict(seasons)), None
    try:
        joined = _strict_join_quality_starts(seasons, sidecar)
    except DirectValueError as exc:
        raise FoldScoringError(str(exc)) from exc
    return joined, str(sidecar.get("content_sha256") or _sha256(sidecar))


def derive_inner_fold_years(
    rows: Iterable[Mapping[str, Any]],
    outer_year: int,
    *,
    horizon_years: int = OUTCOME_HORIZON_YEARS,
) -> list[int]:
    """Return prior cohorts that themselves have outcome-complete training data."""
    years = sorted({int(row["cohort_year"]) for row in rows})
    outer_year = int(outer_year)
    return [
        year
        for year in years
        if year < outer_year and any(prior <= year - horizon_years for prior in years)
    ]


def derive_crossfit_source_years(
    rows: Iterable[Mapping[str, Any]],
    outer_year: int,
    *,
    horizon_years: int = OUTCOME_HORIZON_YEARS,
) -> list[int]:
    """Return cohorts whose full target horizon is complete by ``outer_year``."""
    mature_through = int(outer_year) - int(horizon_years)
    return sorted(
        {
            int(row["cohort_year"])
            for row in rows
            if int(row["cohort_year"]) <= mature_through
        }
    )


def fold_local_seasons(
    training_rows: Iterable[Mapping[str, Any]],
    seasons_by_identity: Mapping[str, list[dict]],
    *,
    horizon_years: int = OUTCOME_HORIZON_YEARS,
) -> dict[str, list[dict]]:
    """Keep only training identities and each identity's fixed forward horizon."""
    local: dict[str, list[dict]] = {}
    for row in training_rows:
        key = _season_key(row)
        cohort = int(row["cohort_year"])
        clipped = [
            copy.deepcopy(season)
            for season in seasons_by_identity.get(key, [])
            if cohort < int(season.get("year") or 0) <= cohort + horizon_years
        ]
        local[key] = clipped
    return local


def direct_7x7_target(
    record: Mapping[str, Any],
    seasons_by_identity: Mapping[str, list[dict]],
    references: Mapping[str, Mapping[str, list[float]]],
) -> float:
    """Compute the strict canonical best-season target, including pitcher QS.

    A player with no qualifying horizon opportunity has factual value zero.  A
    qualifying season with a missing 7x7 field is unresolved and fails closed.
    """
    try:
        return _strict_direct_7x7_target(
            record, seasons_by_identity, dict(references)
        )
    except DirectValueError as exc:
        raise FoldScoringError(str(exc)) from exc


def _strict_fold_references(
    training_rows: Iterable[Mapping[str, Any]],
    training_seasons: Mapping[str, list[dict]],
) -> dict[str, dict[str, list[float]]]:
    try:
        return build_fold_references(training_rows, training_seasons)
    except DirectValueError as exc:
        raise FoldScoringError(str(exc)) from exc


def _fold_input(
    rows: list[dict],
    seasons: Mapping[str, list[dict]],
    test_year: int,
) -> dict:
    """Build one leave-one-cohort-out fold from a caller-provided mature pool."""
    training_rows = [
        copy.deepcopy(row)
        for row in rows
        if int(row.get("cohort_year") or -1) != int(test_year)
    ]
    test_rows = [
        row for row in rows if int(row.get("cohort_year") or -1) == int(test_year)
    ]
    if not training_rows:
        raise FoldScoringError(f"fold {test_year}: no leave-one-cohort-out training rows")
    if not test_rows:
        raise FoldScoringError(f"fold {test_year}: no pseudo-current rows")
    pseudo_current = []
    for source in test_rows:
        row = {key: copy.deepcopy(value) for key, value in source.items() if key != "outcome"}
        row["source_kind"] = "current_season"
        row["sample_season"] = int(test_year)
        pseudo_current.append(row)
    training_seasons = fold_local_seasons(training_rows, seasons)
    references = _strict_fold_references(training_rows, training_seasons)
    train_through = max(int(row["cohort_year"]) for row in training_rows)
    return {
        "test_year": int(test_year),
        "train_through": train_through,
        "training_rows": training_rows,
        "training_seasons": training_seasons,
        "impact_references": references,
        "reference_sha256": _sha256(references),
        "pseudo_current_rows": pseudo_current,
        "training_strategy": "leave_one_cohort_out",
    }


def _outer_fold_input(
    rows: list[dict],
    seasons: Mapping[str, list[dict]],
    test_year: int,
) -> dict:
    """Build the untouched outer fold from outcomes mature at its pseudo-date."""
    train_through = int(test_year) - OUTCOME_HORIZON_YEARS
    training_rows = [
        copy.deepcopy(row)
        for row in rows
        if int(row.get("cohort_year") or 9999) <= train_through
    ]
    test_rows = [
        row for row in rows if int(row.get("cohort_year") or -1) == int(test_year)
    ]
    if not training_rows:
        raise FoldScoringError(f"fold {test_year}: no rows at or before {train_through}")
    if not test_rows:
        raise FoldScoringError(f"fold {test_year}: no pseudo-current rows")
    pseudo_current = []
    for source in test_rows:
        row = {
            key: copy.deepcopy(value)
            for key, value in source.items()
            if key != "outcome"
        }
        row["source_kind"] = "current_season"
        row["sample_season"] = int(test_year)
        pseudo_current.append(row)
    training_seasons = fold_local_seasons(training_rows, seasons)
    references = _strict_fold_references(training_rows, training_seasons)
    return {
        "test_year": int(test_year),
        "train_through": train_through,
        "training_rows": training_rows,
        "training_seasons": training_seasons,
        "impact_references": references,
        "reference_sha256": _sha256(references),
        "pseudo_current_rows": pseudo_current,
        "training_strategy": "outer_walk_forward",
    }


def production_raw_head_scorer(
    fold: Mapping[str, Any],
    *,
    model_flags: Mapping[str, Any],
) -> tuple[list[dict], dict]:
    """Train and score both production model heads under one model-flag scope."""
    from prospects.model import score_current, train_impact_role, train_role
    from prospects.rank_backtest import _fold_now, _model_flags

    test_year = int(fold["test_year"])
    now = _fold_now(test_year)
    current = {"hitters": [], "pitchers": []}
    service = []
    for source in fold["pseudo_current_rows"]:
        row = copy.deepcopy(source)
        role = str(row["role"])
        current["hitters" if role == "hitter" else "pitchers"].append(row)
        service.append(
            {
                "mlbam_id": row["mlbam_id"],
                "role": role,
                "graduated": False,
                "ab": 0.0,
                "pa": 0.0,
                "ip": 0.0,
            }
        )
    scoring_contract = {
        "generated_at": now,
        "historical": {"rows": copy.deepcopy(fold["training_rows"])},
        "historical_mlb_seasons": copy.deepcopy(fold["training_seasons"]),
        "current": current,
        "mlb_service": service,
        "rookie_limits": {"at_bats": 131, "innings_pitched": 51},
    }
    mature_through = int(fold["train_through"])
    with _model_flags(dict(model_flags)):
        role_models = {
            role: train_role(
                role,
                scoring_contract["historical"]["rows"],
                now=now,
                mature_through=mature_through,
            )
            for role in ROLES
        }
        impact_models = {
            role: train_impact_role(
                role,
                scoring_contract["historical"]["rows"],
                scoring_contract["historical_mlb_seasons"],
                fold["impact_references"],
                now=now,
                mature_through=mature_through,
            )
            for role in ROLES
        }
        scored = score_current(scoring_contract, role_models, impact_models)
    return scored, {
        "test_year": test_year,
        "train_through": fold["train_through"],
        "model_flags": dict(model_flags),
        "scored_rows": len(scored),
    }


def _production_scoring_contract(fold: Mapping[str, Any]) -> dict:
    """Build the shared pseudo-current contract used by both scoring stages."""
    from prospects.rank_backtest import _fold_now

    test_year = int(fold["test_year"])
    now = _fold_now(test_year)
    current: dict[str, Any] = {
        "season": test_year,
        "fetched_date": str(now)[:10],
        "hitters": [],
        "pitchers": [],
    }
    service = []
    for source in fold["pseudo_current_rows"]:
        row = copy.deepcopy(source)
        role = str(row["role"])
        current["hitters" if role == "hitter" else "pitchers"].append(row)
        service.append(
            {
                "mlbam_id": row["mlbam_id"],
                "role": role,
                "graduated": False,
                "ab": 0.0,
                "pa": 0.0,
                "ip": 0.0,
            }
        )
    return {
        "schema_version": "1.2",
        "generated_at": now,
        "historical": {"rows": copy.deepcopy(fold["training_rows"])},
        "historical_mlb_seasons": copy.deepcopy(fold["training_seasons"]),
        "current": current,
        "mlb_service": service,
        "rookie_limits": {"at_bats": 131, "innings_pitched": 51},
    }


def _pseudo_universe(fold: Mapping[str, Any], generated_at: str) -> dict:
    """Preserve exact MLBAM+role identities, including factual two-way rows."""
    players = []
    for source in fold["pseudo_current_rows"]:
        row = copy.deepcopy(source)
        role = str(row["role"])
        position = str(row.get("position") or ("P" if role == "pitcher" else "DH"))
        players.append(
            {
                "mlbam_id": row["mlbam_id"],
                "name": row.get("name") or f"MLBAM {row['mlbam_id']}",
                "normalized_name": row.get("normalized_name") or str(row.get("name") or "").lower(),
                "role": role,
                "positions": [position],
                "mlb_team": row.get("mlb_team") or row.get("team"),
                "age": row.get("age"),
                "level": row.get("level"),
                "eta": row.get("eta") or int(fold["test_year"]),
                "universe_source": "pre2014_registered_pseudo_cohort",
            }
        )
    return {
        "schema_version": "1.0",
        "artifact": "valucast_pre2014_pseudo_universe",
        "generated_at": generated_at,
        "candidate_count": len(players),
        "players": players,
    }


def production_rank_scorer(
    fold: Mapping[str, Any],
    model_rows: list[dict],
    *,
    model_score_mode: str,
) -> tuple[dict[tuple[str, str], float], dict]:
    """Run the full Rank-v1 core with an exact role-preserving pseudo-universe."""
    from prospects.dynasty import build_layer
    from prospects.rank_backtest import _fold_now, _neutralized_module_state
    from prospects.rank_v1 import build_prospect_rank_v1
    from prospects.universal import (
        MODEL_NAME,
        MODEL_VERSION,
        TARGET_SPECS,
        score_current as universal_score_current,
        train_target,
    )

    test_year = int(fold["test_year"])
    now = _fold_now(test_year)
    scoring_contract = _production_scoring_contract(fold)
    role_targets = {
        role: {
            target: train_target(
                role,
                target,
                scoring_contract["historical"]["rows"],
                scoring_contract["historical_mlb_seasons"],
                now=now,
            )
            for target in TARGET_SPECS[role]
        }
        for role in ROLES
    }
    dynasty_layer = build_layer(
        {
            "profiles": universal_score_current(scoring_contract, role_targets),
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "input_contract": {"generated_at": now},
        },
        backtest=None,
    )
    prospect_model = {
        "status": "shadow_only",
        "model_version": f"pre2014_fold_{test_year}",
        "input_contract": {"generated_at": now},
        "release_contract": {
            "consumer": "prospect_rank_v1",
            "feeds_live_valucast_rank": True,
        },
        "ranked": copy.deepcopy(model_rows),
    }
    with _neutralized_module_state():
        payload = build_prospect_rank_v1(
            _pseudo_universe(fold, now),
            dynasty_layer,
            prospect_model,
            scoring_contract,
            prospect_availability=None,
            milb_history_by_key=None,
            mlb_roster_status=None,
            model_score_mode=model_score_mode,
        )
    scores = {
        (str(row["mlbam_id"]), str(row["role"])): float(row["score"])
        for row in payload.get("board") or []
    }
    return scores, {
        "test_year": test_year,
        "model_score_mode": model_score_mode,
        "board_rows": len(payload.get("board") or []),
        "rank_status": payload.get("status"),
        "two_way_identity_policy": "preserve_mlbam_id_plus_role",
    }


def _scored_by_identity(rows: Iterable[Mapping[str, Any]], expected: set[tuple[str, str]]) -> dict:
    by_identity: dict[tuple[str, str], dict] = {}
    for source in rows:
        row = copy.deepcopy(dict(source))
        key = _identity(row)
        if key in by_identity:
            raise FoldScoringError(f"duplicate scored identity: {key}")
        by_identity[key] = row
    if set(by_identity) != expected:
        raise FoldScoringError(
            f"raw-score identity mismatch: expected={sorted(expected)} actual={sorted(by_identity)}"
        )
    return by_identity


def _target_rows(
    factual_rows: Iterable[Mapping[str, Any]],
    seasons: Mapping[str, list[dict]],
    references: Mapping[str, Mapping[str, list[float]]],
) -> dict[tuple[str, str], dict]:
    targets = {}
    for row in factual_rows:
        key = _identity(row)
        label = str(row.get("outcome") or "")
        corrected = outcome_label(
            seasons.get(_season_key(row), []),
            key[1],
            int(row["cohort_year"]),
            horizon_years=OUTCOME_HORIZON_YEARS,
        )
        if label != corrected:
            raise FoldScoringError(
                f"incorrect fixed-horizon outcome for {key}: {label!r} != {corrected!r}"
            )
        targets[key] = {
            "outcome": label,
            "outcome_tier": OUTCOME_TARGET[label],
            "direct_7x7_target": direct_7x7_target(row, seasons, references),
        }
    return targets


def _rank_result(
    result: tuple[Mapping[tuple[str, str], float], dict],
) -> tuple[dict[tuple[str, str], float], dict]:
    scores, diagnostics = result
    normalized = {
        (str(key[0]), str(key[1])): float(value) for key, value in scores.items()
    }
    return normalized, copy.deepcopy(diagnostics)


def score_outer_fold(
    contract: Mapping[str, Any],
    outer_year: int,
    *,
    rank_scorer: RankScorer = production_rank_scorer,
    raw_scorer: RawScorer = production_raw_head_scorer,
    calibration_min_rows: int = 250,
    calibration_min_source_folds: int = 4,
) -> dict:
    """Score one untouched outer cohort through incumbent and fixed candidate.

    ``rank_scorer`` is an intentional composition seam.  It receives the same
    leakage-safe fold input and model identities for both modes and must return
    full Rank-v1 scores keyed by ``(str(mlbam_id), role)``.
    """
    rows = [
        row
        for row in _rows(contract)
        if int(row.get("cohort_year") or 9999) <= int(outer_year)
    ]
    registered_seasons = fold_local_seasons(rows, _seasons(contract))
    seasons, qs_hash = _join_quality_starts(
        registered_seasons, contract.get("quality_starts")
    )
    calibration_mature_through = int(outer_year) - OUTCOME_HORIZON_YEARS
    calibration_pool = [
        row
        for row in rows
        if int(row.get("cohort_year") or 9999) <= calibration_mature_through
    ]
    inner_years = derive_crossfit_source_years(calibration_pool, outer_year)
    if not inner_years:
        raise FoldScoringError(f"outer fold {outer_year}: no eligible inner OOF folds")

    inner_calibration_rows = []
    inner_diagnostics = []
    for inner_year in inner_years:
        if inner_year + OUTCOME_HORIZON_YEARS > int(outer_year):
            raise FoldScoringError(
                f"outer fold {outer_year}: calibration target {inner_year} is not mature"
            )
        fold = _fold_input(calibration_pool, seasons, inner_year)
        expected = {_identity(row) for row in fold["pseudo_current_rows"]}
        raw_rows, raw_diagnostics = raw_scorer(
            fold, model_flags=CANDIDATE_MODEL_FLAGS
        )
        by_identity = _scored_by_identity(raw_rows, expected)
        factual_rows = [
            row
            for row in calibration_pool
            if int(row["cohort_year"]) == inner_year
        ]
        targets = _target_rows(factual_rows, seasons, fold["impact_references"])
        for key in sorted(expected):
            prediction = by_identity[key]
            target = targets[key]
            inner_calibration_rows.append(
                {
                    **prediction,
                    "mlbam_id": int(key[0]),
                    "role": key[1],
                    "cohort_year": inner_year,
                    "source_fold": inner_year,
                    "is_out_of_fold": True,
                    "outcome_tier": target["outcome_tier"],
                    "direct_7x7_target": target["direct_7x7_target"],
                }
            )
        inner_diagnostics.append(
            {
                "test_year": inner_year,
                "target_complete_by": inner_year + OUTCOME_HORIZON_YEARS,
                "train_through": fold["train_through"],
                "training_strategy": fold["training_strategy"],
                "reference_sha256": fold["reference_sha256"],
                "raw_scorer": copy.deepcopy(raw_diagnostics),
            }
        )

    calibrators: dict[str, dict[str, dict]] = {}
    for role in ROLES:
        calibrators[role] = {
            "outcome": build_role_calibrator(
                inner_calibration_rows,
                role=role,
                prediction_field="expected_outcome_score",
                target_field="outcome_tier",
                before_cohort=int(outer_year),
                min_rows=calibration_min_rows,
                min_source_folds=calibration_min_source_folds,
            ),
            "impact": build_role_calibrator(
                inner_calibration_rows,
                role=role,
                prediction_field="expected_category_impact_score",
                target_field="direct_7x7_target",
                before_cohort=int(outer_year),
                min_rows=calibration_min_rows,
                min_source_folds=calibration_min_source_folds,
            ),
        }

    outer_fold = _outer_fold_input(rows, seasons, int(outer_year))
    expected = {_identity(row) for row in outer_fold["pseudo_current_rows"]}
    incumbent_raw, incumbent_raw_diagnostics = raw_scorer(
        outer_fold, model_flags=INCUMBENT_MODEL_FLAGS
    )
    candidate_raw, candidate_raw_diagnostics = raw_scorer(
        outer_fold, model_flags=CANDIDATE_MODEL_FLAGS
    )
    incumbent_rows = list(_scored_by_identity(incumbent_raw, expected).values())
    candidate_rows = list(_scored_by_identity(candidate_raw, expected).values())
    candidate_rows = apply_common_target_calibrators(candidate_rows, calibrators)

    incumbent_scores, incumbent_rank_diagnostics = _rank_result(
        rank_scorer(
            outer_fold,
            incumbent_rows,
            model_score_mode="incumbent_role_quantile",
        )
    )
    candidate_scores, candidate_rank_diagnostics = _rank_result(
        rank_scorer(
            outer_fold,
            candidate_rows,
            model_score_mode="common_target",
        )
    )
    if set(incumbent_scores) != expected or set(candidate_scores) != expected:
        raise FoldScoringError(
            "Rank-v1 identity mismatch before target access: "
            f"expected={sorted(expected)} incumbent={sorted(incumbent_scores)} "
            f"candidate={sorted(candidate_scores)}"
        )

    # Outer factual targets are deliberately interpreted only after both score
    # paths have proven identical identity coverage.
    outer_factual_rows = [
        row for row in rows if int(row["cohort_year"]) == int(outer_year)
    ]
    targets = _target_rows(
        outer_factual_rows, seasons, outer_fold["impact_references"]
    )
    calibrator_hashes = {
        f"{role}.{head}": calibrators[role][head]["sha256"]
        for role in ROLES
        for head in ("outcome", "impact")
    }
    return {
        "scores": {
            "incumbent": incumbent_scores,
            "candidate": candidate_scores,
        },
        "targets": targets,
        "calibrators": calibrators,
        "calibrator_hashes": calibrator_hashes,
        "metadata": {
            "outer_year": int(outer_year),
            "train_through": outer_fold["train_through"],
            "inner_fold_years": inner_years,
            "calibration_mature_through": calibration_mature_through,
            "calibration_strategy": (
                "leave_one_cohort_out_within_outer_mature_pool"
            ),
            "identity_count": len(expected),
            "outer_reference_sha256": outer_fold["reference_sha256"],
            "quality_starts_sha256": qs_hash,
            "candidate_model_flags": copy.deepcopy(CANDIDATE_MODEL_FLAGS),
            "incumbent_model_flags": copy.deepcopy(INCUMBENT_MODEL_FLAGS),
        },
        "diagnostics": {
            "identity_sets_equal": True,
            "inner_folds": inner_diagnostics,
            "outer": {
                "incumbent_raw": copy.deepcopy(incumbent_raw_diagnostics),
                "candidate_raw": copy.deepcopy(candidate_raw_diagnostics),
                "incumbent_rank": incumbent_rank_diagnostics,
                "candidate_rank": candidate_rank_diagnostics,
            },
        },
    }
