"""Pure current-board evaluator for the registered cross-role candidate.

The caller owns every read.  This module accepts already-loaded production
inputs, injects display-only Rank-v1 context, and returns a fail-closed result
that the sealed adjudicator can consume without changing governor thresholds.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from typing import Any

from prospects.common_target_calibration import (
    CalibrationError,
    apply_common_target_calibrators,
    build_role_calibrator,
)
from prospects.direct_7x7 import DirectValueError, join_quality_starts
from prospects.model import OUTCOME_HORIZON_YEARS, OUTCOME_TARGET
from prospects.pre2014_cross_role_gate import OUTCOME_COMPLETE_THROUGH
from prospects.pre2014_fold_scoring import CANDIDATE_MODEL_FLAGS
from quality.valucast_governor import (
    MAX_TOP25_PROSPECT_PITCHER_COUNT,
    MAX_TOP50_PROSPECT_PITCHER_RATE,
    _prospect_top_board_role_shape,
)


ARTIFACT = "valucast_pre2014_current_board_evaluation"
ROLES = ("hitter", "pitcher")
EXTERNAL_SNAPSHOT_NAMES = (
    "sts",
    "fangraphs",
    "prospectslive",
    "pipeline",
    "hkb",
)
REQUIRED_READINESS_SOURCE_KEYS = frozenset(
    {
        "prepared_artifact",
        "prepared_manifest",
        "draft_facts",
        "current_prospect_contract",
        "prospect_universe",
        "dynasty_layer",
        "prospect_availability",
        "mlb_roster_status",
        "investment_evidence",
        "milb_season_stats",
        "milb_card_history",
        "manual_graduation",
        "sts_snapshot",
        "fangraphs_snapshot",
        "prospectslive_snapshot",
        "pipeline_snapshot",
        "hkb_snapshot",
    }
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_BLOB_RE = re.compile(r"^[0-9a-f]{40}$")
REGISTERED_CALIBRATION_BEFORE_COHORT = (
    OUTCOME_COMPLETE_THROUGH - OUTCOME_HORIZON_YEARS + 1
)
REGISTERED_MATURE_THROUGH = REGISTERED_CALIBRATION_BEFORE_COHORT - 1


class CurrentBoardError(ValueError):
    """A current-board prerequisite failed and the candidate must not pass."""


def build_registered_current_calibration_rows(
    research_contract: Mapping[str, Any],
    quality_starts: Mapping[str, Any],
    *,
    raw_scorer: Callable[..., tuple[list[dict], dict]] | None = None,
) -> list[dict]:
    """Build serving calibrator evidence from prior-cohort OOF predictions only.

    This is deliberately run after the sealed outcome acquisition.  It uses the
    same fold construction, strict canonical season/QS join, candidate feature
    flag, and factual target builder as the registered outer-fold scorer.
    """
    from prospects.pre2014_fold_scoring import (
        FoldScoringError,
        _fold_input,
        _identity,
        _join_quality_starts,
        _rows,
        _scored_by_identity,
        _seasons,
        _target_rows,
        derive_inner_fold_years,
        fold_local_seasons,
        production_raw_head_scorer,
    )

    scorer = raw_scorer or production_raw_head_scorer
    try:
        rows = [
            row
            for row in _rows(research_contract)
            if int(row.get("cohort_year") or 9999)
            < REGISTERED_CALIBRATION_BEFORE_COHORT
        ]
        seasons = fold_local_seasons(rows, _seasons(research_contract))
        joined_seasons, _ = _join_quality_starts(seasons, quality_starts)
        fold_years = derive_inner_fold_years(
            rows, REGISTERED_CALIBRATION_BEFORE_COHORT
        )
        if len(fold_years) < 4:
            raise CurrentBoardError(
                "serving calibration has fewer than four OOF source folds"
            )

        output: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for fold_year in fold_years:
            fold = _fold_input(rows, joined_seasons, fold_year)
            expected = {_identity(row) for row in fold["pseudo_current_rows"]}
            scored, _ = scorer(fold, model_flags=dict(CANDIDATE_MODEL_FLAGS))
            by_identity = _scored_by_identity(scored, expected)
            factual = [
                row for row in rows if int(row["cohort_year"]) == fold_year
            ]
            targets = _target_rows(
                factual, joined_seasons, fold["impact_references"]
            )
            for identity in sorted(expected):
                if identity in seen:
                    raise CurrentBoardError(
                        f"duplicate serving calibration identity: {identity}"
                    )
                seen.add(identity)
                output.append(
                    {
                        **by_identity[identity],
                        "mlbam_id": int(identity[0]),
                        "role": identity[1],
                        "cohort_year": fold_year,
                        "source_fold": fold_year,
                        "is_out_of_fold": True,
                        "outcome_tier": targets[identity]["outcome_tier"],
                        "direct_7x7_target": targets[identity][
                            "direct_7x7_target"
                        ],
                    }
                )
        return output
    except CurrentBoardError:
        raise
    except (FoldScoringError, DirectValueError, KeyError, TypeError, ValueError) as exc:
        raise CurrentBoardError(f"serving_calibration_invalid: {exc}") from exc


def _sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _input_sha256(payload: Any) -> str:
    """Hash caller-loaded objects even when indexes use tuple identity keys."""

    def normalize(value: Any) -> Any:
        if isinstance(value, Mapping):
            entries = [[normalize(key), normalize(item)] for key, item in value.items()]
            entries.sort(
                key=lambda entry: json.dumps(
                    entry[0], sort_keys=True, separators=(",", ":"), default=str
                )
            )
            return {"__mapping__": entries}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        if isinstance(value, (set, frozenset)):
            items = [normalize(item) for item in value]
            return {
                "__set__": sorted(
                    items,
                    key=lambda item: json.dumps(
                        item, sort_keys=True, separators=(",", ":"), default=str
                    ),
                )
            }
        if isinstance(value, bytes):
            return {"__bytes__": value.hex()}
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return {"__type__": type(value).__name__, "value": str(value)}

    return _sha256(normalize(payload))


def _identity(row: Mapping[str, Any], *, label: str) -> tuple[str, str]:
    mlbam_id = row.get("mlbam_id")
    role = str(row.get("role") or "")
    if (
        isinstance(mlbam_id, bool)
        or not str(mlbam_id or "").isdigit()
        or role not in ROLES
    ):
        raise CurrentBoardError(f"{label}_invalid_identity")
    return str(mlbam_id), role


def _identity_index(
    rows: Iterable[Mapping[str, Any]], *, label: str
) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for source in rows:
        if not isinstance(source, Mapping):
            raise CurrentBoardError(f"{label}_invalid_row")
        key = _identity(source, label=label)
        if key in index:
            raise CurrentBoardError(f"{label}_duplicate_identity: {key}")
        index[key] = copy.deepcopy(dict(source))
    return index


def _valid_file_record(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"path", "sha256", "git_blob"}
        and isinstance(value.get("path"), str)
        and bool(value["path"])
        and isinstance(value.get("sha256"), str)
        and _SHA256_RE.fullmatch(str(value["sha256"]).lower()) is not None
        and isinstance(value.get("git_blob"), str)
        and _GIT_BLOB_RE.fullmatch(str(value["git_blob"]).lower()) is not None
    )


def _valid_deferred_file_record(value: Any) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == {"path", "git_blob", "binding"}
        and isinstance(value.get("path"), str)
        and bool(value["path"])
        and isinstance(value.get("git_blob"), str)
        and _GIT_BLOB_RE.fullmatch(str(value["git_blob"]).lower()) is not None
        and value.get("binding") == "git_blob_only_pre_reservation"
    )


def _validate_readiness(readiness: Mapping[str, Any]) -> None:
    if not isinstance(readiness, Mapping):
        raise CurrentBoardError("registered_readiness_not_ready")
    source_policy = readiness.get("source_policy") or {}
    hashes = readiness.get("hashes") or {}
    source_files = hashes.get("source_files") or {}
    implementation_files = hashes.get("implementation_files") or []
    if (
        readiness.get("artifact") != "valucast_pre2014_cross_role_readiness"
        or readiness.get("status") != "ready"
        or readiness.get("execution_authorized") is not True
        or readiness.get("blockers") != []
        or source_policy.get("phase") != "pre_look"
        or source_policy.get("reads_outcomes") is not False
        or source_policy.get("reads_mlb_seasons") is not False
        or set(source_files) != REQUIRED_READINESS_SOURCE_KEYS
        or not _valid_deferred_file_record(
            source_files.get("current_prospect_contract")
        )
        or not all(
            _valid_file_record(record)
            for key, record in source_files.items()
            if key != "current_prospect_contract"
        )
        or not isinstance(implementation_files, list)
        or not implementation_files
        or not all(_valid_file_record(record) for record in implementation_files)
    ):
        raise CurrentBoardError("registered_readiness_not_ready")


def _registered_mature_contract(
    contract: Mapping[str, Any],
    quality_starts: Mapping[str, Any],
    *,
    calibration_before_cohort: int,
) -> tuple[dict, dict[tuple[str, str], dict]]:
    if not isinstance(contract, Mapping):
        raise CurrentBoardError("current_contract_not_ready")
    if not isinstance(quality_starts, Mapping):
        raise CurrentBoardError("quality_starts_invalid: sidecar must be a mapping")
    historical = contract.get("historical") or {}
    source_rows = historical.get("rows")
    seasons = contract.get("historical_mlb_seasons")
    if not isinstance(source_rows, list) or not isinstance(seasons, Mapping):
        raise CurrentBoardError("registered_history_invalid")

    all_rows = _identity_index(source_rows, label="registered_history")
    mature: dict[tuple[str, str], dict] = {}
    clipped_seasons: dict[str, list[dict]] = {}
    for key, row in all_rows.items():
        cohort = row.get("cohort_year")
        if isinstance(cohort, bool) or not isinstance(cohort, int):
            raise CurrentBoardError("registered_history_invalid_cohort")
        if cohort >= calibration_before_cohort:
            continue
        if row.get("outcome") not in OUTCOME_TARGET:
            raise CurrentBoardError(
                f"registered_history_missing_mature_label: {key}"
            )
        mature[key] = row
        season_key = f"{key[0]}_{key[1]}"
        raw_seasons = seasons.get(season_key) or []
        if not isinstance(raw_seasons, list):
            raise CurrentBoardError(f"registered_history_invalid_seasons: {key}")
        clipped_seasons[season_key] = [
            copy.deepcopy(season)
            for season in raw_seasons
            if cohort
            < int((season or {}).get("year") or 0)
            <= cohort + OUTCOME_HORIZON_YEARS
        ]
    if not mature or {key[1] for key in mature} != set(ROLES):
        raise CurrentBoardError("registered_mature_roles_not_ready")

    try:
        joined_seasons = join_quality_starts(clipped_seasons, quality_starts)
    except (DirectValueError, KeyError, TypeError, ValueError) as exc:
        raise CurrentBoardError(f"quality_starts_invalid: {exc}") from exc

    training_contract = copy.deepcopy(dict(contract))
    training_contract["historical"] = {**copy.deepcopy(dict(historical)), "rows": list(mature.values())}
    training_contract["historical_mlb_seasons"] = joined_seasons
    return training_contract, mature


def _build_calibrators(
    calibration_rows: Iterable[Mapping[str, Any]],
    mature: Mapping[tuple[str, str], Mapping[str, Any]],
    *,
    before_cohort: int,
) -> tuple[list[dict], dict[str, dict[str, dict]]]:
    rows = [copy.deepcopy(dict(row)) for row in calibration_rows]
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = _identity(row, label="calibration")
        if key in seen:
            raise CurrentBoardError(f"calibration_invalid: duplicate identity: {key}")
        seen.add(key)
        registered = mature.get(key)
        if registered is None:
            raise CurrentBoardError(
                "calibration_invalid: calibration identity is not a registered "
                f"mature row: {key}"
            )
        cohort = row.get("cohort_year")
        source_fold = row.get("source_fold")
        if (
            isinstance(cohort, bool)
            or not isinstance(cohort, int)
            or cohort != registered.get("cohort_year")
            or source_fold != cohort
            or row.get("is_out_of_fold") is not True
            or cohort >= before_cohort
        ):
            raise CurrentBoardError(
                f"calibration_invalid: non-registered OOF provenance: {key}"
            )
        try:
            outcome_tier = float(row.get("outcome_tier"))
            direct_target = float(row.get("direct_7x7_target"))
        except (TypeError, ValueError) as exc:
            raise CurrentBoardError(
                f"calibration_invalid: non-finite target: {key}"
            ) from exc
        if not math.isfinite(outcome_tier) or not math.isfinite(direct_target):
            raise CurrentBoardError(
                f"calibration_invalid: non-finite target: {key}"
            )
        if outcome_tier != float(OUTCOME_TARGET[str(registered["outcome"])]):
            raise CurrentBoardError(
                "calibration_invalid: outcome target does not match registered "
                f"label: {key}"
            )
        if not 0.0 <= direct_target <= 1.0:
            raise CurrentBoardError(
                f"calibration_invalid: direct target outside zero-one range: {key}"
            )

    try:
        calibrators = {
            role: {
                "outcome": build_role_calibrator(
                    rows,
                    role=role,
                    prediction_field="expected_outcome_score",
                    target_field="outcome_tier",
                    before_cohort=before_cohort,
                ),
                "impact": build_role_calibrator(
                    rows,
                    role=role,
                    prediction_field="expected_category_impact_score",
                    target_field="direct_7x7_target",
                    before_cohort=before_cohort,
                ),
            }
            for role in ROLES
        }
        for role in ROLES:
            for head in ("outcome", "impact"):
                calibrator = calibrators[role][head]
                content = {
                    key: value
                    for key, value in calibrator.items()
                    if key != "sha256"
                }
                if calibrator.get("sha256") != _sha256(content):
                    raise CurrentBoardError(
                        "calibration_invalid: calibrator content hash mismatch: "
                        f"{role}.{head}"
                    )
    except CurrentBoardError:
        raise
    except (CalibrationError, KeyError, TypeError, ValueError) as exc:
        raise CurrentBoardError(f"calibration_invalid: {exc}") from exc
    return rows, calibrators


def _validate_rank_context(rank_context: Mapping[str, Any]) -> None:
    if not isinstance(rank_context, Mapping):
        raise CurrentBoardError("rank_context_not_ready")
    snapshots = rank_context.get("external_snapshots")
    graduated = rank_context.get("manual_graduated_ids")
    if (
        not isinstance(snapshots, Mapping)
        or set(snapshots) != set(EXTERNAL_SNAPSHOT_NAMES)
        or not all(isinstance(snapshots[name], Mapping) for name in EXTERNAL_SNAPSHOT_NAMES)
        or not isinstance(graduated, (list, tuple, set, frozenset))
        or any(
            isinstance(value, bool) or not str(value or "").isdigit()
            for value in graduated
        )
    ):
        raise CurrentBoardError("rank_context_not_ready")


@contextmanager
def _injected_rank_context(rank_context: Mapping[str, Any]):
    """Keep Rank-v1 deterministic and read-free using caller-loaded context."""
    import prospects.rank_v1 as rank_v1

    _validate_rank_context(rank_context)
    snapshots = rank_context["external_snapshots"]
    graduated = {str(value) for value in rank_context["manual_graduated_ids"]}
    path_names = {
        str(rank_v1.STS_CONSENSUS_PATH): "sts",
        str(rank_v1.FG_FV_SNAPSHOT_PATH): "fangraphs",
        str(rank_v1.PROSPECTSLIVE_PATH): "prospectslive",
        str(rank_v1.PIPELINE_PATH): "pipeline",
        str(rank_v1.HKB_PATH): "hkb",
    }
    original_graduated = rank_v1._manual_graduated_ids
    original_snapshot = rank_v1._snapshot_by_mlbam

    def injected_snapshot(path):
        name = path_names.get(str(path))
        if name is None:
            raise CurrentBoardError(f"unregistered_rank_snapshot_path: {path}")
        return copy.deepcopy(dict(snapshots[name]))

    try:
        rank_v1._manual_graduated_ids = lambda: set(graduated)
        rank_v1._snapshot_by_mlbam = injected_snapshot
        yield
    finally:
        rank_v1._manual_graduated_ids = original_graduated
        rank_v1._snapshot_by_mlbam = original_snapshot


def _default_model_builder(
    contract: dict, *, now: str, mature_through: int
) -> dict:
    from prospects.model import build_shadow_model

    return build_shadow_model(
        contract, now=now, mature_through=mature_through
    )


def _default_rank_builder(*args, **kwargs) -> dict:
    from prospects.rank_v1 import build_prospect_rank_v1

    return build_prospect_rank_v1(*args, **kwargs)


def _rank_identity_audit(
    rank_payload: Mapping[str, Any], candidate_identities: set[tuple[str, str]]
) -> dict[str, Any]:
    board = rank_payload.get("board")
    if not isinstance(board, list) or len(board) < 50:
        raise CurrentBoardError("rank_board_not_ready")
    board_index = _identity_index(board, label="rank_board")
    if not candidate_identities.issubset(board_index):
        raise CurrentBoardError("rank_identity_mismatch")
    ranks = [row.get("rank") for row in board]
    if ranks != list(range(1, len(board) + 1)):
        raise CurrentBoardError("rank_board_noncontiguous")
    if rank_payload.get("ranked_count") != len(board):
        raise CurrentBoardError("ranked_count_mismatch")
    for row in board:
        try:
            score = float(row.get("score"))
        except (TypeError, ValueError) as exc:
            raise CurrentBoardError("rank_board_nonfinite_score") from exc
        if not math.isfinite(score):
            raise CurrentBoardError("rank_board_nonfinite_score")
    validation = rank_payload.get("validation") or {}
    if validation.get("blockers"):
        raise CurrentBoardError("rank_validation_blocked")
    if (rank_payload.get("promotion") or {}).get("feeds_live_valucast_rank") is not True:
        raise CurrentBoardError("rank_promotion_not_ready")
    return {
        "candidate_model_identity_count": len(candidate_identities),
        "rank_board_identity_count": len(board_index),
        "candidate_identities_preserved": True,
        "ranks_contiguous": True,
    }


def _blocked(reason: str) -> dict[str, Any]:
    return {
        "artifact": ARTIFACT,
        "schema_version": 1,
        "status": "blocked",
        "current_role_shape_governor_passed": False,
        "production_review_authorized": False,
        "claim_authorized": False,
        "blockers": [reason],
    }


def evaluate_current_candidate_board(
    prospect_contract: Mapping[str, Any],
    prospect_universe: Mapping[str, Any],
    dynasty_layer: Mapping[str, Any],
    calibration_rows: Iterable[Mapping[str, Any]],
    quality_starts: Mapping[str, Any],
    readiness: Mapping[str, Any],
    *,
    calibration_before_cohort: int,
    rank_context: Mapping[str, Any],
    prospect_availability: Mapping[str, Any] | None = None,
    milb_history_by_key: Mapping[tuple[str, str], Any] | None = None,
    mlb_roster_status: Mapping[str, Any] | None = None,
    require_mlb_roster_status: bool = False,
    investment_evidence: Mapping[str, Any] | None = None,
    model_builder: Callable[..., dict] | None = None,
    rank_builder: Callable[..., dict] | None = None,
) -> dict[str, Any]:
    """Build and govern the exact registered candidate from injected inputs.

    Expected data defects return a single structured blocker.  No failed path
    can authorize a claim or production review.
    """
    try:
        if (
            isinstance(calibration_before_cohort, bool)
            or not isinstance(calibration_before_cohort, int)
        ):
            raise CurrentBoardError("calibration_cutoff_invalid")
        if calibration_before_cohort != REGISTERED_CALIBRATION_BEFORE_COHORT:
            raise CurrentBoardError("calibration_cutoff_not_registered")
        if not isinstance(prospect_universe, Mapping):
            raise CurrentBoardError("prospect_universe_not_ready")
        if not isinstance(dynasty_layer, Mapping):
            raise CurrentBoardError("dynasty_layer_not_ready")
        _validate_readiness(readiness)
        _validate_rank_context(rank_context)
        training_contract, mature = _registered_mature_contract(
            prospect_contract,
            quality_starts,
            calibration_before_cohort=calibration_before_cohort,
        )
        rows, calibrators = _build_calibrators(
            calibration_rows,
            mature,
            before_cohort=calibration_before_cohort,
        )
        universe_rows = prospect_universe.get("players")
        if not isinstance(universe_rows, list):
            raise CurrentBoardError("prospect_universe_not_ready")
        universe_index = _identity_index(universe_rows, label="prospect_universe")

        from prospects.rank_backtest import _model_flags

        build_model = model_builder or _default_model_builder
        generated_at = str(training_contract.get("generated_at") or "")
        if not generated_at:
            raise CurrentBoardError("current_contract_generated_at_missing")
        with _model_flags(dict(CANDIDATE_MODEL_FLAGS)):
            candidate_model = build_model(
                training_contract,
                now=generated_at,
                mature_through=REGISTERED_MATURE_THROUGH,
            )
        ranked = candidate_model.get("ranked")
        if not isinstance(ranked, list) or not ranked:
            raise CurrentBoardError("candidate_model_not_ready")
        model_index = _identity_index(ranked, label="candidate_model")
        if not set(model_index).issubset(universe_index):
            raise CurrentBoardError("candidate_model_universe_identity_mismatch")
        try:
            calibrated_rows = apply_common_target_calibrators(
                model_index.values(), calibrators
            )
        except (CalibrationError, KeyError, TypeError, ValueError) as exc:
            raise CurrentBoardError(f"calibration_application_invalid: {exc}") from exc
        candidate_model = copy.deepcopy(dict(candidate_model))
        candidate_model["ranked"] = calibrated_rows

        build_rank = rank_builder or _default_rank_builder
        with _injected_rank_context(rank_context):
            prospect_rank = build_rank(
                copy.deepcopy(dict(prospect_universe)),
                copy.deepcopy(dict(dynasty_layer)),
                candidate_model,
                training_contract,
                prospect_availability=copy.deepcopy(prospect_availability),
                milb_history_by_key=copy.deepcopy(milb_history_by_key),
                mlb_roster_status=copy.deepcopy(mlb_roster_status),
                require_mlb_roster_status=require_mlb_roster_status,
                investment_evidence=copy.deepcopy(investment_evidence),
                stage1_state="incumbent",
                model_score_mode="common_target",
            )
        identity_audit = _rank_identity_audit(prospect_rank, set(model_index))
        governor = _prospect_top_board_role_shape(dict(prospect_rank), [])
        governor_passed = governor.get("status") == "passed"
        blockers = [] if governor_passed else [str(governor.get("id"))]
        hashes = {
            f"{role}.{head}": calibrators[role][head]["sha256"]
            for role in ROLES
            for head in ("outcome", "impact")
        }
        return {
            "artifact": ARTIFACT,
            "schema_version": 1,
            "status": "passed" if governor_passed else "blocked",
            "current_role_shape_governor_passed": governor_passed,
            "production_review_authorized": False,
            "claim_authorized": False,
            "blockers": blockers,
            "candidate_path": {
                "pitcher_investment_feature_mode": CANDIDATE_MODEL_FLAGS[
                    "PITCHER_INVESTMENT_FEATURE_MODE"
                ],
                "rank_model_score_mode": "common_target",
                "mature_through": REGISTERED_MATURE_THROUGH,
                "governor_check_id": "prospect_top_board_role_shape",
                "governor_thresholds_changed": False,
            },
            "readiness": {
                "artifact": readiness.get("artifact"),
                "status": readiness.get("status"),
                "sha256": _sha256(readiness),
            },
            "quality_starts": {
                "status": quality_starts.get("status"),
                "content_sha256": quality_starts.get("content_sha256")
                or _sha256(quality_starts),
            },
            "calibration": {
                "before_cohort": calibration_before_cohort,
                "row_count": len(rows),
                "source_folds": sorted({int(row["source_fold"]) for row in rows}),
                "rows_sha256": _sha256(rows),
                "identity_set_sha256": _sha256(
                    sorted(
                        [str(row["mlbam_id"]), str(row["role"])] for row in rows
                    )
                ),
                "calibrator_hashes": hashes,
            },
            "identity_audit": identity_audit,
            "candidate_model": candidate_model,
            "prospect_rank": prospect_rank,
            "role_shape_governor_check": governor,
        }
    except CurrentBoardError as exc:
        return _blocked(str(exc))
    except (CalibrationError, DirectValueError, KeyError, TypeError, ValueError) as exc:
        return _blocked(f"candidate_execution_invalid: {exc}")


def make_current_board_governor_evaluator(
    current_prospect_contract: Mapping[str, Any],
    prospect_universe: Mapping[str, Any],
    dynasty_layer: Mapping[str, Any],
    *,
    rank_context: Mapping[str, Any],
    prospect_availability: Mapping[str, Any] | None = None,
    milb_history_by_key: Mapping[tuple[str, str], Any] | None = None,
    mlb_roster_status: Mapping[str, Any] | None = None,
    investment_evidence: Mapping[str, Any] | None = None,
) -> Callable[..., dict[str, Any]]:
    """Close current inputs into the sealed runner's four-keyword callback.

    The sealed runner supplies only the reserved research contract and its
    already-loaded controls.  Candidate flags, score mode, and thresholds have
    no callback input surface and therefore cannot be weakened by orchestration.
    """
    frozen_current = copy.deepcopy(dict(current_prospect_contract))
    frozen_universe = copy.deepcopy(dict(prospect_universe))
    frozen_dynasty = copy.deepcopy(dict(dynasty_layer))
    frozen_rank_context = copy.deepcopy(dict(rank_context))
    frozen_availability = copy.deepcopy(prospect_availability)
    frozen_history = copy.deepcopy(milb_history_by_key)
    frozen_roster = copy.deepcopy(mlb_roster_status)
    frozen_investment = copy.deepcopy(investment_evidence)

    def governor_evaluator(
        *,
        reservation_id: str,
        research_contract: Mapping[str, Any],
        quality_starts: Mapping[str, Any],
        readiness: Mapping[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise CurrentBoardError("current-board reservation id is required")
        if not isinstance(research_contract, Mapping):
            raise CurrentBoardError("current-board research contract is required")
        research_rows = research_contract.get("rows")
        research_seasons = research_contract.get("historical_mlb_seasons")
        if not isinstance(research_rows, list) or not isinstance(
            research_seasons, Mapping
        ):
            raise CurrentBoardError("current-board research contract is incomplete")
        attached_sidecar = research_contract.get("quality_starts")
        if attached_sidecar is not None and attached_sidecar != quality_starts:
            raise CurrentBoardError("current-board quality-start sidecar mismatch")

        try:
            serving_calibration = build_registered_current_calibration_rows(
                research_contract, quality_starts
            )
        except CurrentBoardError as exc:
            evaluation = _blocked(str(exc))
        else:
            current_contract = copy.deepcopy(frozen_current)
            historical = current_contract.get("historical") or {}
            current_contract["historical"] = {
                **copy.deepcopy(dict(historical)),
                "rows": copy.deepcopy(research_rows),
            }
            current_contract["historical_mlb_seasons"] = copy.deepcopy(
                dict(research_seasons)
            )
            evaluation = evaluate_current_candidate_board(
                current_contract,
                copy.deepcopy(frozen_universe),
                copy.deepcopy(frozen_dynasty),
                serving_calibration,
                quality_starts,
                readiness,
                calibration_before_cohort=REGISTERED_CALIBRATION_BEFORE_COHORT,
                rank_context=copy.deepcopy(frozen_rank_context),
                prospect_availability=copy.deepcopy(frozen_availability),
                milb_history_by_key=copy.deepcopy(frozen_history),
                mlb_roster_status=copy.deepcopy(frozen_roster),
                require_mlb_roster_status=True,
                investment_evidence=copy.deepcopy(frozen_investment),
            )
        governor = evaluation.get("role_shape_governor_check")
        governor_metrics = (
            governor.get("metrics")
            if isinstance(governor, Mapping)
            and isinstance(governor.get("metrics"), Mapping)
            else None
        )
        thresholds = {
            "max_top25_pitcher_count": MAX_TOP25_PROSPECT_PITCHER_COUNT,
            "max_top50_pitcher_rate": MAX_TOP50_PROSPECT_PITCHER_RATE,
        }
        unchanged_thresholds = governor_metrics is None or (
            governor_metrics.get("max_top25_pitcher_count")
            == MAX_TOP25_PROSPECT_PITCHER_COUNT
            and governor_metrics.get("max_top50_pitcher_rate")
            == MAX_TOP50_PROSPECT_PITCHER_RATE
        )
        blockers = list(evaluation.get("blockers") or [])
        if not unchanged_thresholds:
            blockers.append("production_pitcher_governor_threshold_mismatch")
        receipt = {
            "passed": (
                evaluation.get("current_role_shape_governor_passed") is True
                and unchanged_thresholds
            ),
            "unchanged_thresholds": unchanged_thresholds,
            "candidate_model_flags": dict(CANDIDATE_MODEL_FLAGS),
            "model_score_mode": "common_target",
            "reservation_id": reservation_id,
            "governor_scope": "prospect_top_board_role_shape",
            "full_governor_required_at": "post_look_pre_publication",
            "thresholds": thresholds,
            "evaluation_artifact": evaluation.get("artifact"),
            "evaluation_status": evaluation.get("status"),
            "blockers": blockers,
            "calibration": copy.deepcopy(evaluation.get("calibration")),
            "identity_audit": copy.deepcopy(evaluation.get("identity_audit")),
            "role_shape_governor_check": copy.deepcopy(governor),
            "input_hashes": {
                "current_prospect_contract": _input_sha256(frozen_current),
                "prospect_universe": _input_sha256(frozen_universe),
                "dynasty_layer": _input_sha256(frozen_dynasty),
                "rank_context": _input_sha256(frozen_rank_context),
                "prospect_availability": _input_sha256(frozen_availability),
                "milb_history_by_key": _input_sha256(frozen_history),
                "mlb_roster_status": _input_sha256(frozen_roster),
                "investment_evidence": _input_sha256(frozen_investment),
                "research_contract": _input_sha256(research_contract),
                "quality_starts": _input_sha256(quality_starts),
                "readiness": _input_sha256(readiness),
            },
        }
        return {**receipt, "receipt_sha256": _sha256(receipt)}

    return governor_evaluator
