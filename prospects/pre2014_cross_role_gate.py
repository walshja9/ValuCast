"""Pure, fail-closed adjudication core for the sealed cross-role research gate.

The module performs no network or model work.  Callers inject already-scored
outer-fold observations after reserving the single-use result path.
"""
from __future__ import annotations

import json
import math
import os
import random
import tempfile
import uuid
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from statistics import mean
from typing import Any


BOOTSTRAP_SEED = 35011
DEFAULT_BOOTSTRAP_RESAMPLES = 10_000
OUTCOME_HORIZON_YEARS = 4
OUTCOME_COMPLETE_THROUGH = 2025
CALIBRATION_WARMUP_FOLDS = 4
MIN_OUTER_FOLDS = 4
MIN_UNIQUE_PLAYERS_PER_ROLE = 250
MIN_FOLD_ROLE_COVERAGE = 0.90

DIRECT_METRIC = "direct_7x7_target_percentile_rank_mae"
MIN_PRIMARY_RELATIVE_IMPROVEMENT = 0.02
MIN_CROSS_ROLE_RELATIVE_IMPROVEMENT = 0.02
MAX_FOLD_RELATIVE_REGRESSION = 0.05
MAX_ROLE_RELATIVE_REGRESSION = 0.01


def derive_outer_folds(
    cohort_years: Iterable[int],
    *,
    declared_omissions: Iterable[int] = (),
    outcome_complete_through: int = OUTCOME_COMPLETE_THROUGH,
    outcome_horizon_years: int = OUTCOME_HORIZON_YEARS,
    calibration_warmup_folds: int = CALIBRATION_WARMUP_FOLDS,
) -> tuple[int, ...]:
    """Return outer cohorts after outcome and inner-OOF calibration warmups."""
    years = sorted({_year(value, "cohort year") for value in cohort_years})
    if not years:
        return ()
    if (
        isinstance(calibration_warmup_folds, bool)
        or not isinstance(calibration_warmup_folds, int)
        or calibration_warmup_folds < 0
    ):
        raise ValueError("calibration_warmup_folds must be a non-negative integer")
    omissions = {_year(value, "declared omission") for value in declared_omissions}
    first_outer = years[0] + outcome_horizon_years + calibration_warmup_folds
    last_complete = _year(outcome_complete_through, "outcome cutoff") - outcome_horizon_years
    return tuple(
        year
        for year in years
        if first_outer <= year <= last_complete and year not in omissions
    )


def hierarchical_bootstrap_improvement(
    paired_errors_by_cohort: Mapping[int, Sequence[tuple[float, float]]],
    *,
    seed: int = BOOTSTRAP_SEED,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    """Bootstrap paired relative-MAE improvement by cohort and player."""
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, int) or n_resamples < 1:
        raise ValueError("n_resamples must be a positive integer")
    cohorts = []
    for cohort_year in sorted(paired_errors_by_cohort):
        pairs = []
        for value in paired_errors_by_cohort[cohort_year]:
            if (
                not isinstance(value, Sequence)
                or isinstance(value, (str, bytes))
                or len(value) != 2
            ):
                raise ValueError("each player must have paired incumbent/candidate errors")
            incumbent, candidate = (float(value[0]), float(value[1]))
            if (
                not math.isfinite(incumbent)
                or not math.isfinite(candidate)
                or incumbent < 0.0
                or candidate < 0.0
            ):
                raise ValueError("paired player errors must be finite and non-negative")
            pairs.append((incumbent, candidate))
        if not pairs:
            raise ValueError("each cohort must have paired player errors")
        cohorts.append(tuple(pairs))
    if not cohorts:
        raise ValueError("at least one cohort is required")

    incumbent_point = mean(pair[0] for cohort in cohorts for pair in cohort)
    candidate_point = mean(pair[1] for cohort in cohorts for pair in cohort)
    point = _relative_improvement(incumbent_point, candidate_point)
    if point is None:
        return {
            "point": None,
            "ci_lower": None,
            "ci_upper": None,
            "seed": seed,
            "n_resamples": n_resamples,
            "resample_unit": "player_within_cohort_hierarchical",
            "point_statistic": "relative_mae_improvement",
            "draws": (),
        }
    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        for _draw_attempt in range(100):
            incumbent_sum = 0.0
            candidate_sum = 0.0
            sampled_count = 0
            for _ in cohorts:
                cohort = cohorts[rng.randrange(len(cohorts))]
                for _ in cohort:
                    incumbent, candidate = cohort[rng.randrange(len(cohort))]
                    incumbent_sum += incumbent
                    candidate_sum += candidate
                    sampled_count += 1
            incumbent_mae = incumbent_sum / sampled_count
            candidate_mae = candidate_sum / sampled_count
            relative = _relative_improvement(incumbent_mae, candidate_mae)
            if relative is not None:
                draws.append(relative)
                break
        else:
            raise ValueError("bootstrap incumbent MAE remained zero")
    ordered = sorted(draws)
    return {
        "point": point,
        "ci_lower": _percentile(ordered, 0.025),
        "ci_upper": _percentile(ordered, 0.975),
        "seed": seed,
        "n_resamples": n_resamples,
        "resample_unit": "player_within_cohort_hierarchical",
        "point_statistic": "relative_mae_improvement",
        "draws": tuple(draws),
    }


def _cross_cohort(fold: Mapping[str, Any]) -> dict[str, Any]:
    by_role = {"hitter": [], "pitcher": []}
    for player in fold.get("players") or []:
        if not isinstance(player, Mapping):
            raise ValueError("cross-role concordance player must be a mapping")
        role = str(player.get("role") or "")
        if role not in by_role:
            raise ValueError("cross-role concordance role is invalid")
        row = {
            "target": _finite_or_none(player.get("outcome_tier")),
            "incumbent": _finite_or_none(player.get("incumbent_score")),
            "candidate": _finite_or_none(player.get("candidate_score")),
        }
        if (
            any(value is None for value in row.values())
            or not 0.0 <= row["target"] <= 1.0
        ):
            raise ValueError("cross-role concordance inputs are invalid")
        by_role[role].append(row)
    if not by_role["hitter"] or not by_role["pitcher"]:
        raise ValueError("cross-role concordance requires both roles")

    sorted_pitchers = {}
    for field in ("incumbent", "candidate"):
        groups = {}
        for index, row in enumerate(by_role["pitcher"]):
            groups.setdefault(row["target"], []).append((row[field], index))
        sorted_pitchers[field] = {
            target: {
                "scores": [score for score, _index in sorted(items)],
                "indices": [index for _score, index in sorted(items)],
            }
            for target, items in groups.items()
        }
    return {**by_role, "sorted_pitchers": sorted_pitchers}


def _bootstrap_counts(size: int, rng: random.Random) -> list[int]:
    counts = [0] * size
    for _ in range(size):
        counts[rng.randrange(size)] += 1
    return counts


def _weighted_cross_concordance(
    cohort: Mapping[str, Any],
    field: str,
    hitter_counts: Sequence[int],
    pitcher_counts: Sequence[int],
) -> float:
    prefixes = {}
    for target, group in cohort["sorted_pitchers"][field].items():
        prefix = [0]
        for index in group["indices"]:
            prefix.append(prefix[-1] + int(pitcher_counts[index]))
        prefixes[target] = (group["scores"], prefix)

    numerator = 0.0
    denominator = 0
    for hitter_index, hitter_count in enumerate(hitter_counts):
        if not hitter_count:
            continue
        hitter = cohort["hitter"][hitter_index]
        for target, (scores, prefix) in prefixes.items():
            if target == hitter["target"]:
                continue
            total = prefix[-1]
            if not total:
                continue
            left = bisect_left(scores, hitter[field])
            right = bisect_right(scores, hitter[field])
            tied = prefix[right] - prefix[left]
            if hitter["target"] > target:
                credited = prefix[left] + 0.5 * tied
            else:
                credited = (total - prefix[right]) + 0.5 * tied
            numerator += hitter_count * credited
            denominator += hitter_count * total
    if denominator == 0:
        raise ValueError("cross-role concordance has no comparable resampled pairs")
    return numerator / denominator


def _observed_cross_concordance(cohort: Mapping[str, Any], field: str) -> float:
    return _weighted_cross_concordance(
        cohort,
        field,
        [1] * len(cohort["hitter"]),
        [1] * len(cohort["pitcher"]),
    )


def hierarchical_bootstrap_cross_role_concordance(
    fold_outputs: Sequence[Mapping[str, Any]],
    *,
    seed: int = BOOTSTRAP_SEED,
    n_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    """Recompute paired cross-role concordance inside every bootstrap draw."""
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, int) or n_resamples < 1:
        raise ValueError("n_resamples must be a positive integer")
    cohorts = []
    declared_incumbents = []
    declared_candidates = []
    observed_incumbents = []
    observed_candidates = []
    for fold in fold_outputs:
        cohort = _cross_cohort(fold)
        declared = _mapping(fold.get("cross_role_concordance"))
        declared_incumbent = _finite_or_none(declared.get("incumbent"))
        declared_candidate = _finite_or_none(declared.get("candidate"))
        if declared_incumbent is None or declared_candidate is None:
            raise ValueError("declared cross-role concordance is invalid")
        observed_incumbent = _observed_cross_concordance(cohort, "incumbent")
        observed_candidate = _observed_cross_concordance(cohort, "candidate")
        if not (
            math.isclose(
                declared_incumbent, observed_incumbent, rel_tol=0.0, abs_tol=1e-12
            )
            and math.isclose(
                declared_candidate, observed_candidate, rel_tol=0.0, abs_tol=1e-12
            )
        ):
            raise ValueError("declared cross-role concordance does not recompute")
        cohorts.append(cohort)
        declared_incumbents.append(declared_incumbent)
        declared_candidates.append(declared_candidate)
        observed_incumbents.append(observed_incumbent)
        observed_candidates.append(observed_candidate)
    if not cohorts:
        raise ValueError("at least one cross-role cohort is required")

    point = _relative_discordance_reduction(
        mean(observed_incumbents), mean(observed_candidates)
    )
    declared_point = _relative_discordance_reduction(
        mean(declared_incumbents), mean(declared_candidates)
    )
    if point is None or declared_point is None:
        raise ValueError("incumbent cross-role discordance must be positive")

    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        for _draw_attempt in range(100):
            sampled_incumbents = []
            sampled_candidates = []
            for _ in cohorts:
                cohort = cohorts[rng.randrange(len(cohorts))]
                for _cohort_attempt in range(100):
                    hitter_counts = _bootstrap_counts(len(cohort["hitter"]), rng)
                    pitcher_counts = _bootstrap_counts(len(cohort["pitcher"]), rng)
                    try:
                        incumbent = _weighted_cross_concordance(
                            cohort, "incumbent", hitter_counts, pitcher_counts
                        )
                        candidate = _weighted_cross_concordance(
                            cohort, "candidate", hitter_counts, pitcher_counts
                        )
                        break
                    except ValueError:
                        continue
                else:
                    raise ValueError(
                        "cross-role bootstrap could not form comparable pairs"
                    )
                sampled_incumbents.append(incumbent)
                sampled_candidates.append(candidate)
            relative = _relative_discordance_reduction(
                mean(sampled_incumbents), mean(sampled_candidates)
            )
            if relative is not None:
                draws.append(relative)
                break
        else:
            raise ValueError("cross-role bootstrap incumbent discordance is zero")
    ordered = sorted(draws)
    return {
        "point": point,
        "declared_point": declared_point,
        "ci_lower": _percentile(ordered, 0.025),
        "ci_upper": _percentile(ordered, 0.975),
        "seed": seed,
        "n_resamples": n_resamples,
        "resample_unit": "cohort_then_identity_within_role",
        "point_statistic": "incumbent_discordance_reduction",
        "draws": tuple(draws),
    }


def assess_promotion_gates(
    metrics: Mapping[str, Any], *, current_role_shape_governor_passed: bool
) -> dict[str, Any]:
    """Apply frozen review gates; the full governor remains pre-publication."""
    direct = _mapping(metrics.get("direct_mae"))
    fold_regressions = _mapping(metrics.get("fold_relative_regressions"))
    role_concordance_regressions = _mapping(
        metrics.get("role_concordance_relative_regressions")
    )
    top25 = _mapping(metrics.get("top25_direct_regret"))
    top25_ordinal = _mapping(metrics.get("top25_ordinal_regret"))
    concordance = _mapping(metrics.get("cross_role_concordance"))

    primary_relative = _finite_or_none(direct.get("relative_improvement"))
    bootstrap_lower = _finite_or_none(direct.get("bootstrap_95_lower"))
    fold_values = [_finite_or_none(value) for value in fold_regressions.values()]
    role_concordance_values = {
        role: _finite_or_none(role_concordance_regressions.get(role))
        for role in ("hitter", "pitcher")
    }
    top25_incumbent = _finite_or_none(top25.get("incumbent"))
    top25_candidate = _finite_or_none(top25.get("candidate"))
    ordinal_incumbent = _finite_or_none(top25_ordinal.get("incumbent"))
    ordinal_candidate = _finite_or_none(top25_ordinal.get("candidate"))
    cross_relative = _finite_or_none(concordance.get("relative_improvement"))
    cross_bootstrap_lower = _finite_or_none(concordance.get("bootstrap_95_lower"))

    gates = {
        "direct_mae_relative_improvement": _gate(
            primary_relative is not None
            and primary_relative >= MIN_PRIMARY_RELATIVE_IMPROVEMENT,
            primary_relative,
            {"minimum": MIN_PRIMARY_RELATIVE_IMPROVEMENT},
        ),
        "paired_bootstrap_lower_bound": _gate(
            bootstrap_lower is not None and bootstrap_lower > 0.0,
            bootstrap_lower,
            {"strictly_greater_than": 0.0, "confidence": 0.95},
        ),
        "outer_fold_regression": _gate(
            bool(fold_values)
            and all(value is not None for value in fold_values)
            and max(fold_values) <= MAX_FOLD_RELATIVE_REGRESSION,
            None if not fold_values or any(value is None for value in fold_values) else max(fold_values),
            {"maximum": MAX_FOLD_RELATIVE_REGRESSION},
        ),
        "role_concordance_regression": _gate(
            all(value is not None for value in role_concordance_values.values())
            and max(role_concordance_values.values()) <= MAX_ROLE_RELATIVE_REGRESSION,
            role_concordance_values,
            {"maximum_each_role": MAX_ROLE_RELATIVE_REGRESSION},
        ),
        "top25_direct_regret": _gate(
            top25_incumbent is not None
            and top25_candidate is not None
            and top25_candidate <= top25_incumbent,
            {"incumbent": top25_incumbent, "candidate": top25_candidate},
            {"candidate_no_worse_than_incumbent": True},
        ),
        "cross_role_concordance": _gate(
            cross_relative is not None
            and cross_relative >= MIN_CROSS_ROLE_RELATIVE_IMPROVEMENT,
            cross_relative,
            {"minimum_relative_improvement": MIN_CROSS_ROLE_RELATIVE_IMPROVEMENT},
        ),
        "cross_role_bootstrap_lower_bound": _gate(
            cross_bootstrap_lower is not None and cross_bootstrap_lower > 0.0,
            cross_bootstrap_lower,
            {"strictly_greater_than": 0.0, "confidence": 0.95},
        ),
        "top25_ordinal_regret": _gate(
            ordinal_incumbent is not None
            and ordinal_candidate is not None
            and ordinal_candidate <= ordinal_incumbent,
            {"incumbent": ordinal_incumbent, "candidate": ordinal_candidate},
            {"candidate_no_worse_than_incumbent": True},
        ),
        "current_role_shape_governor": _gate(
            current_role_shape_governor_passed is True,
            current_role_shape_governor_passed,
            {
                "required": True,
                "check_id": "prospect_top_board_role_shape",
                "full_governor_required_at": "post_look_pre_publication",
            },
        ),
    }
    blockers = [name for name, gate in gates.items() if not gate["passed"]]
    authorized = not blockers
    return {
        "decision": (
            "production_review_authorized"
            if authorized
            else "production_review_not_authorized"
        ),
        "production_review_authorized": authorized,
        "claim_authorized": False,
        "gates": gates,
        "blockers": blockers,
    }


def evaluate_pre2014_cross_role_gate(
    fold_outputs: Sequence[Mapping[str, Any]],
    *,
    cohort_years: Iterable[int],
    declared_omissions: Iterable[int] = (),
    outcome_complete_through: int = OUTCOME_COMPLETE_THROUGH,
    calibration_warmup_folds: int = CALIBRATION_WARMUP_FOLDS,
    current_role_shape_governor_passed: bool,
    bootstrap_seed: int = BOOTSTRAP_SEED,
    bootstrap_resamples: int = DEFAULT_BOOTSTRAP_RESAMPLES,
) -> dict[str, Any]:
    """Validate injected fold scorer outputs, compute metrics, and fail closed."""
    expected_folds = derive_outer_folds(
        cohort_years,
        declared_omissions=declared_omissions,
        outcome_complete_through=outcome_complete_through,
        calibration_warmup_folds=calibration_warmup_folds,
    )
    readiness = _readiness(fold_outputs, expected_folds)
    if not readiness["passed"]:
        return {
            "decision": "production_review_not_authorized",
            "production_review_authorized": False,
            "claim_authorized": False,
            "readiness": readiness,
            "metrics": None,
            "gates": {},
            "blockers": list(readiness["blockers"]),
        }

    metrics = _compute_metrics(
        fold_outputs,
        bootstrap_seed=bootstrap_seed,
        bootstrap_resamples=bootstrap_resamples,
    )
    decision = assess_promotion_gates(
        metrics,
        current_role_shape_governor_passed=current_role_shape_governor_passed,
    )
    return {**decision, "readiness": readiness, "metrics": metrics}


def reserve_result_path(
    result_path: Path | str, *, reservation_id: str | None = None
) -> str:
    """Atomically reserve the final path; an existing or spent path is immutable."""
    path = Path(result_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    token = _validated_reservation_id(reservation_id or uuid.uuid4().hex)
    marker = {
        "reservation_id": token,
        "status": "reserved_before_outer_outcomes",
    }
    temporary = _write_json_temporary(
        path,
        marker,
        prefix=f".{path.name}.{token}.reserve.",
    )
    try:
        # A hard-link install is atomic and, unlike os.replace, never overwrites
        # an existing reservation or permanently spent result.
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return token


@contextmanager
def sealed_result_run_lease(
    result_path: Path | str, reservation_id: str
) -> Iterable[str]:
    """Hold the reservation's crash-released lease for one complete invocation."""
    path = Path(result_path)
    token = _validated_reservation_id(reservation_id)
    lease_path = path.with_name(path.name + ".running")
    descriptor, record = _claim_run_lease(path, lease_path, token)
    try:
        yield token
    finally:
        try:
            _release_advisory_claim(path, lease_path, descriptor, record)
        except Exception:
            if not _result_is_permanently_spent(path, token):
                raise


def finalize_reserved_result(
    result_path: Path | str,
    reservation_id: str,
    payload: Mapping[str, Any],
) -> None:
    """Consume one reservation exactly once and atomically publish its result."""
    path = Path(result_path)
    token = _validated_reservation_id(reservation_id)
    lock_path = path.with_name(path.name + ".finalizing")
    lock_descriptor: int | None = None
    lock_record = ""
    temporary: Path | None = None
    published = False
    try:
        lock_descriptor, lock_record, reservation_active = _claim_finalization(
            path, lock_path, token
        )
        _cleanup_exact_reservation_residue(path, token)
        if not reservation_active:
            raise FileExistsError("result path is already spent")

        final_payload = dict(payload)
        final_payload["reservation_id"] = token
        final_payload["claim_authorized"] = False
        temporary = _write_json_temporary(
            path,
            final_payload,
            prefix=f".{path.name}.{token}.finalize.",
        )
        os.replace(temporary, path)
        published = True
        temporary = None
    finally:
        # Finalization failures must leave the same reservation recoverable so
        # the caller can permanently consume it as ``spent_error``.  The lock
        # is an in-flight mutex, not a second permanent result marker.
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if lock_descriptor is not None:
            try:
                _release_advisory_claim(
                    path,
                    lock_path,
                    lock_descriptor,
                    lock_record,
                )
            except Exception:
                if not published:
                    raise


_FINALIZATION_LOCK_ARTIFACT = "valucast_sealed_finalization_lock"
_LEGACY_FINALIZATION_LOCK_KEYS = {
    "artifact",
    "owner_nonce",
    "owner_pid",
    "reservation_id",
    "schema_version",
}
_FINALIZATION_LOCK_KEYS = _LEGACY_FINALIZATION_LOCK_KEYS | {"lock_protocol"}
_FINALIZATION_LOCK_PROTOCOL = "advisory_byte_v1"
_RUN_LEASE_ARTIFACT = "valucast_sealed_run_lease"


def _validated_reservation_id(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or any(
            not (character.isascii() and (character.isalnum() or character in "-_"))
            for character in value
        )
    ):
        raise ValueError(
            "reservation_id must contain only ASCII letters, digits, - or _"
        )
    return value


def _result_is_permanently_spent(path: Path, token: str) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        isinstance(payload, Mapping)
        and payload.get("reservation_id") == token
        and payload.get("status") != "reserved_before_outer_outcomes"
    )


def _write_json_temporary(
    path: Path, payload: Mapping[str, Any], *, prefix: str
) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=prefix,
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _write_text_temporary(path: Path, content: str, *, prefix: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=prefix,
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary


def _claim_run_lease(path: Path, lease_path: Path, token: str) -> tuple[int, str]:
    try:
        result_descriptor = _acquire_path_byte_lock(path, blocking=False)
    except (FileNotFoundError, OSError) as error:
        raise FileExistsError("active sealed run already owns reservation") from error

    lease_descriptor: int | None = None
    try:
        _install_run_lease_file(lease_path, path, token)
        try:
            lease_descriptor = _acquire_path_byte_lock(lease_path, blocking=False)
        except (FileNotFoundError, OSError) as error:
            raise FileExistsError(
                "active sealed run already owns reservation"
            ) from error
        lease_content = _read_descriptor_text(lease_descriptor)
        _validate_recoverable_run_lease(lease_content, token)
        marker = _read_descriptor_json(result_descriptor)
        if (
            not isinstance(marker, Mapping)
            or marker.get("reservation_id") != token
            or marker.get("status") != "reserved_before_outer_outcomes"
        ):
            raise FileExistsError("result path is not the active reservation")
        claimed_descriptor = lease_descriptor
        lease_descriptor = None
        return claimed_descriptor, lease_content
    finally:
        if lease_descriptor is not None:
            _release_byte_lock(lease_descriptor)
            os.close(lease_descriptor)
        _release_byte_lock(result_descriptor)
        os.close(result_descriptor)


def _install_run_lease_file(lease_path: Path, path: Path, token: str) -> None:
    if lease_path.exists():
        return
    record = _run_lease_record(token)
    temporary = _write_text_temporary(
        path,
        record,
        prefix=f".{path.name}.{token}.run.",
    )
    try:
        try:
            os.link(temporary, lease_path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _run_lease_record(token: str) -> str:
    return json.dumps(
        {
            "artifact": _RUN_LEASE_ARTIFACT,
            "lock_protocol": _FINALIZATION_LOCK_PROTOCOL,
            "owner_nonce": uuid.uuid4().hex,
            "owner_pid": os.getpid(),
            "reservation_id": token,
            "schema_version": 1,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"


def _validate_recoverable_run_lease(content: str, token: str) -> None:
    if content == token:
        return
    try:
        record = json.loads(content)
    except json.JSONDecodeError as error:
        raise FileExistsError("run lease is not reservation-bound") from error
    if (
        not isinstance(record, Mapping)
        or set(record) != _FINALIZATION_LOCK_KEYS
        or record.get("artifact") != _RUN_LEASE_ARTIFACT
        or record.get("lock_protocol") != _FINALIZATION_LOCK_PROTOCOL
        or record.get("schema_version") != 1
        or record.get("reservation_id") != token
        or not isinstance(record.get("owner_nonce"), str)
        or not record["owner_nonce"]
        or isinstance(record.get("owner_pid"), bool)
        or not isinstance(record.get("owner_pid"), int)
        or record["owner_pid"] <= 0
    ):
        raise FileExistsError("run lease is not reservation-bound")


def _claim_finalization(
    path: Path, lock_path: Path, token: str
) -> tuple[int, str, bool]:
    try:
        result_descriptor = _acquire_path_byte_lock(path, blocking=False)
    except (FileNotFoundError, OSError) as error:
        raise FileExistsError("active finalization already owns reservation") from error

    lock_descriptor: int | None = None
    try:
        _install_finalization_lock_file(lock_path, path, token)
        try:
            lock_descriptor = _acquire_path_byte_lock(lock_path, blocking=False)
        except (FileNotFoundError, OSError) as error:
            raise FileExistsError(
                "active finalization already owns reservation"
            ) from error

        lock_content = _read_descriptor_text(lock_descriptor)
        _validate_recoverable_lock(lock_content, token)
        marker = _read_descriptor_json(result_descriptor)
        if not isinstance(marker, Mapping) or marker.get("reservation_id") != token:
            raise FileExistsError(
                "result path is already spent or reservation is invalid"
            )
        reservation_active = (
            marker.get("status") == "reserved_before_outer_outcomes"
        )
        claimed_descriptor = lock_descriptor
        lock_descriptor = None
        return claimed_descriptor, lock_content, reservation_active
    finally:
        if lock_descriptor is not None:
            _release_byte_lock(lock_descriptor)
            os.close(lock_descriptor)
        _release_byte_lock(result_descriptor)
        os.close(result_descriptor)


def _install_finalization_lock_file(
    lock_path: Path, path: Path, token: str
) -> None:
    if lock_path.exists():
        return
    record = _finalization_lock_record(token)
    temporary = _write_text_temporary(
        path,
        record,
        prefix=f".{path.name}.{token}.lock.",
    )
    try:
        try:
            os.link(temporary, lock_path)
        except FileExistsError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def _finalization_lock_record(token: str) -> str:
    record = json.dumps(
        {
            "artifact": _FINALIZATION_LOCK_ARTIFACT,
            "lock_protocol": _FINALIZATION_LOCK_PROTOCOL,
            "owner_nonce": uuid.uuid4().hex,
            "owner_pid": os.getpid(),
            "reservation_id": token,
            "schema_version": 1,
        },
        indent=2,
        sort_keys=True,
    ) + "\n"
    return record


def _validate_recoverable_lock(content: str, token: str) -> None:
    if content == token:
        return
    try:
        record = json.loads(content)
    except json.JSONDecodeError as error:
        raise FileExistsError("finalization lock is not reservation-bound") from error
    if (
        not isinstance(record, Mapping)
        or record.get("artifact") != _FINALIZATION_LOCK_ARTIFACT
        or record.get("schema_version") != 1
        or record.get("reservation_id") != token
        or not isinstance(record.get("owner_nonce"), str)
        or not record["owner_nonce"]
        or isinstance(record.get("owner_pid"), bool)
        or not isinstance(record.get("owner_pid"), int)
        or record["owner_pid"] <= 0
    ):
        raise FileExistsError("finalization lock is not reservation-bound")
    if (
        set(record) == _FINALIZATION_LOCK_KEYS
        and record.get("lock_protocol") == _FINALIZATION_LOCK_PROTOCOL
    ):
        return
    if set(record) != _LEGACY_FINALIZATION_LOCK_KEYS:
        raise FileExistsError("finalization lock is not reservation-bound")
    if _process_is_alive(int(record["owner_pid"])):
        raise FileExistsError("active finalization already owns reservation")


def _acquire_path_byte_lock(path: Path, *, blocking: bool) -> int:
    descriptor = os.open(path, os.O_RDWR)
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            import msvcrt

            mode = msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK
            msvcrt.locking(descriptor, mode, 1)
        else:
            import fcntl

            mode = fcntl.LOCK_EX
            if not blocking:
                mode |= fcntl.LOCK_NB
            fcntl.flock(descriptor, mode)
        opened = os.fstat(descriptor)
        current = path.stat()
        if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
            raise OSError("lock path changed during acquisition")
    except BaseException:
        try:
            _release_byte_lock(descriptor)
        except OSError:
            pass
        os.close(descriptor)
        raise
    return descriptor


def _release_byte_lock(descriptor: int) -> None:
    os.lseek(descriptor, 0, os.SEEK_SET)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


def _read_descriptor_text(descriptor: int) -> str:
    os.lseek(descriptor, 0, os.SEEK_SET)
    remaining = os.fstat(descriptor).st_size
    chunks = []
    while remaining:
        chunk = os.read(descriptor, min(remaining, 64 * 1024))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as error:
        raise FileExistsError("finalization lock is not reservation-bound") from error


def _read_descriptor_json(descriptor: int) -> Any:
    try:
        return json.loads(_read_descriptor_text(descriptor))
    except json.JSONDecodeError as error:
        raise FileExistsError("result path is not an active reservation") from error


def _process_is_alive(pid: int) -> bool:
    if pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    import ctypes
    from ctypes import wintypes

    process_query_limited_information = 0x1000
    error_invalid_parameter = 87
    still_active = 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_exit_code.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_process(process_query_limited_information, False, pid)
    if not handle:
        return ctypes.get_last_error() != error_invalid_parameter
    try:
        exit_code = wintypes.DWORD()
        if not get_exit_code(handle, ctypes.byref(exit_code)):
            return True
        return exit_code.value == still_active
    finally:
        close_handle(handle)


def _cleanup_exact_reservation_residue(path: Path, token: str) -> None:
    path.with_name(path.name + f".{token}.tmp").unlink(missing_ok=True)
    prefixes = tuple(
        f".{path.name}.{token}.{phase}."
        for phase in ("reserve", "finalize", "lock", "run")
    )
    for candidate in path.parent.iterdir():
        if not (
            candidate.name.endswith(".tmp")
            and any(candidate.name.startswith(prefix) for prefix in prefixes)
            and (candidate.is_file() or candidate.is_symlink())
        ):
            continue
        candidate.unlink(missing_ok=True)


def _release_advisory_claim(
    path: Path,
    lock_path: Path,
    lock_descriptor: int,
    record: str,
) -> None:
    result_descriptor: int | None = None
    try:
        result_descriptor = _acquire_path_byte_lock(path, blocking=True)
        opened = os.fstat(lock_descriptor)
        _release_byte_lock(lock_descriptor)
        os.close(lock_descriptor)
        lock_descriptor = -1
        try:
            current = lock_path.stat()
            if (
                (opened.st_dev, opened.st_ino) == (current.st_dev, current.st_ino)
                and lock_path.read_text(encoding="utf-8") == record
            ):
                lock_path.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
    finally:
        if lock_descriptor >= 0:
            _release_byte_lock(lock_descriptor)
            os.close(lock_descriptor)
        if result_descriptor is not None:
            _release_byte_lock(result_descriptor)
            os.close(result_descriptor)


def reserve_and_load_outer_outcomes(
    result_path: Path | str,
    load_outer_outcomes: Callable[[], Any],
    *,
    readiness_blockers: Sequence[str],
    reservation_id: str | None = None,
) -> tuple[str, Any]:
    """Stop on readiness, then reserve before invoking the injected outcome loader."""
    if readiness_blockers:
        raise ValueError("readiness failed: " + ", ".join(readiness_blockers))
    token = reserve_result_path(result_path, reservation_id=reservation_id)
    try:
        return token, load_outer_outcomes()
    except BaseException as error:
        finalize_reserved_result(
            result_path,
            token,
            {
                "status": "spent_error",
                "decision": "production_review_not_authorized",
                "error_type": type(error).__name__,
            },
        )
        raise


def _readiness(
    fold_outputs: Sequence[Mapping[str, Any]], expected_folds: tuple[int, ...]
) -> dict[str, Any]:
    blockers = []
    observed_folds = []
    unique_by_role = {"hitter": set(), "pitcher": set()}
    invalid_observation = False
    noncanonical_metric = False
    invalid_fold_summary = False
    invalid_coverage = False
    below_coverage_floor = False
    cross_concordance_mismatch = False
    coverage_audit = []

    for fold in fold_outputs:
        if not isinstance(fold, Mapping):
            invalid_fold_summary = True
            continue
        cohort_year = fold.get("cohort_year")
        if isinstance(cohort_year, int) and not isinstance(cohort_year, bool):
            observed_folds.append(cohort_year)
        else:
            invalid_fold_summary = True
        if fold.get("metric") != DIRECT_METRIC:
            noncanonical_metric = True
        if not _valid_pair(fold.get("top25_direct_regret"), bounded=False):
            invalid_fold_summary = True
        if not _valid_pair(fold.get("cross_role_concordance"), bounded=True):
            invalid_fold_summary = True
        if not _valid_pair(fold.get("top25_ordinal_regret"), bounded=False):
            invalid_fold_summary = True
        role_concordance = _mapping(fold.get("role_concordance"))
        if any(
            not _valid_pair(role_concordance.get(role), bounded=True)
            for role in ("hitter", "pitcher")
        ):
            invalid_fold_summary = True

        players = fold.get("players")
        if not isinstance(players, Sequence) or isinstance(players, (str, bytes)):
            invalid_observation = True
            continue
        seen_in_fold = set()
        observed_role_counts = {"hitter": 0, "pitcher": 0}
        for player in players:
            if not isinstance(player, Mapping):
                invalid_observation = True
                continue
            player_id = player.get("player_id")
            role = player.get("role")
            identity = (player_id, role)
            values = (
                player.get("target_percentile_rank"),
                player.get("incumbent_percentile_rank"),
                player.get("candidate_percentile_rank"),
            )
            outcome_tier = _finite_or_none(player.get("outcome_tier"))
            incumbent_score = _finite_or_none(player.get("incumbent_score"))
            candidate_score = _finite_or_none(player.get("candidate_score"))
            if (
                player_id is None
                or role not in unique_by_role
                or identity in seen_in_fold
                or not all(_is_rank(value) for value in values)
                or outcome_tier is None
                or not 0.0 <= outcome_tier <= 1.0
                or incumbent_score is None
                or candidate_score is None
            ):
                invalid_observation = True
                continue
            seen_in_fold.add(identity)
            unique_by_role[role].add(player_id)
            observed_role_counts[role] += 1

        coverage_by_role = _mapping(fold.get("coverage_by_role"))
        for role in ("hitter", "pitcher"):
            coverage = _mapping(coverage_by_role.get(role))
            eligible = coverage.get("eligible_identity_count")
            scored = coverage.get("scored_outcome_count")
            rate = _finite_or_none(coverage.get("rate"))
            valid_counts = (
                isinstance(eligible, int)
                and not isinstance(eligible, bool)
                and eligible > 0
                and isinstance(scored, int)
                and not isinstance(scored, bool)
                and 0 <= scored <= eligible
            )
            expected_rate = (scored / eligible) if valid_counts else None
            valid = (
                valid_counts
                and scored == observed_role_counts[role]
                and rate is not None
                and 0.0 <= rate <= 1.0
                and math.isclose(rate, expected_rate, rel_tol=0.0, abs_tol=1e-12)
            )
            if not valid:
                invalid_coverage = True
            elif rate < MIN_FOLD_ROLE_COVERAGE:
                below_coverage_floor = True
            coverage_audit.append(
                {
                    "cohort_year": cohort_year,
                    "role": role,
                    "eligible_identity_count": eligible,
                    "scored_outcome_count": scored,
                    "observed_player_count": observed_role_counts[role],
                    "rate": rate,
                    "valid": bool(valid),
                }
            )
        if not invalid_observation:
            try:
                cohort = _cross_cohort(fold)
                declared = _mapping(fold.get("cross_role_concordance"))
                if not (
                    math.isclose(
                        float(declared["incumbent"]),
                        _observed_cross_concordance(cohort, "incumbent"),
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                    and math.isclose(
                        float(declared["candidate"]),
                        _observed_cross_concordance(cohort, "candidate"),
                        rel_tol=0.0,
                        abs_tol=1e-12,
                    )
                ):
                    cross_concordance_mismatch = True
            except (KeyError, TypeError, ValueError):
                cross_concordance_mismatch = True

    observed = tuple(sorted(set(observed_folds)))
    if observed != expected_folds or len(observed_folds) != len(observed):
        blockers.append("outer_fold_set_mismatch")
    if len(observed) < MIN_OUTER_FOLDS:
        blockers.append("minimum_outer_folds")
    for role in ("hitter", "pitcher"):
        if len(unique_by_role[role]) < MIN_UNIQUE_PLAYERS_PER_ROLE:
            blockers.append(f"minimum_unique_{role}_players")
    if noncanonical_metric:
        blockers.append("noncanonical_direct_metric")
    if invalid_observation:
        blockers.append("invalid_player_observation")
    if invalid_fold_summary:
        blockers.append("invalid_fold_summary")
    if invalid_coverage:
        blockers.append("invalid_fold_role_coverage")
    if below_coverage_floor:
        blockers.append("minimum_fold_role_coverage")
    if cross_concordance_mismatch:
        blockers.append("cross_role_concordance_mismatch")
    return {
        "passed": not blockers,
        "blockers": blockers,
        "outer_folds": list(observed),
        "expected_outer_folds": list(expected_folds),
        "unique_players_by_role": {
            role: len(players) for role, players in unique_by_role.items()
        },
        "minimum_outer_folds": MIN_OUTER_FOLDS,
        "minimum_unique_players_per_role": MIN_UNIQUE_PLAYERS_PER_ROLE,
        "minimum_fold_role_coverage": MIN_FOLD_ROLE_COVERAGE,
        "fold_role_coverage": coverage_audit,
    }


def _compute_metrics(
    fold_outputs: Sequence[Mapping[str, Any]],
    *,
    bootstrap_seed: int,
    bootstrap_resamples: int,
) -> dict[str, Any]:
    incumbent_errors = []
    candidate_errors = []
    paired_by_cohort = {}
    errors_by_role = {
        "hitter": {"incumbent": [], "candidate": []},
        "pitcher": {"incumbent": [], "candidate": []},
    }
    fold_regressions = {}
    top25_incumbent = []
    top25_candidate = []
    top25_ordinal_incumbent = []
    top25_ordinal_candidate = []
    cross_incumbent = []
    cross_candidate = []
    role_concordance = {
        "hitter": {"incumbent": [], "candidate": []},
        "pitcher": {"incumbent": [], "candidate": []},
    }

    for fold in fold_outputs:
        cohort_year = int(fold["cohort_year"])
        fold_incumbent = []
        fold_candidate = []
        paired_errors = []
        for player in fold["players"]:
            target = float(player["target_percentile_rank"])
            incumbent = abs(float(player["incumbent_percentile_rank"]) - target)
            candidate = abs(float(player["candidate_percentile_rank"]) - target)
            fold_incumbent.append(incumbent)
            fold_candidate.append(candidate)
            paired_errors.append((incumbent, candidate))
            errors_by_role[player["role"]]["incumbent"].append(incumbent)
            errors_by_role[player["role"]]["candidate"].append(candidate)
        incumbent_errors.extend(fold_incumbent)
        candidate_errors.extend(fold_candidate)
        paired_by_cohort[cohort_year] = paired_errors
        fold_regressions[cohort_year] = _relative_regression(
            mean(fold_incumbent), mean(fold_candidate)
        )
        top25_incumbent.append(float(fold["top25_direct_regret"]["incumbent"]))
        top25_candidate.append(float(fold["top25_direct_regret"]["candidate"]))
        top25_ordinal_incumbent.append(
            float(fold["top25_ordinal_regret"]["incumbent"])
        )
        top25_ordinal_candidate.append(
            float(fold["top25_ordinal_regret"]["candidate"])
        )
        cross_incumbent.append(float(fold["cross_role_concordance"]["incumbent"]))
        cross_candidate.append(float(fold["cross_role_concordance"]["candidate"]))
        for role in ("hitter", "pitcher"):
            role_summary = fold["role_concordance"][role]
            role_concordance[role]["incumbent"].append(
                float(role_summary["incumbent"])
            )
            role_concordance[role]["candidate"].append(
                float(role_summary["candidate"])
            )

    incumbent_mae = mean(incumbent_errors)
    candidate_mae = mean(candidate_errors)
    paired_improvement = incumbent_mae - candidate_mae
    bootstrap = hierarchical_bootstrap_improvement(
        paired_by_cohort,
        seed=bootstrap_seed,
        n_resamples=bootstrap_resamples,
    )
    role_direct_mae_regressions = {
        role: _relative_regression(
            mean(values["incumbent"]), mean(values["candidate"])
        )
        for role, values in errors_by_role.items()
    }
    incumbent_cross = mean(cross_incumbent)
    candidate_cross = mean(cross_candidate)
    cross_bootstrap = hierarchical_bootstrap_cross_role_concordance(
        fold_outputs,
        seed=bootstrap_seed,
        n_resamples=bootstrap_resamples,
    )
    role_concordance_regressions = {
        role: _relative_concordance_regression(
            mean(values["incumbent"]), mean(values["candidate"])
        )
        for role, values in role_concordance.items()
    }
    return {
        "primary_metric": DIRECT_METRIC,
        "direct_mae": {
            "incumbent": incumbent_mae,
            "candidate": candidate_mae,
            "paired_improvement": paired_improvement,
            "relative_improvement": _relative_improvement(
                incumbent_mae, candidate_mae
            ),
            "bootstrap_95_lower": bootstrap["ci_lower"],
            "bootstrap_95_upper": bootstrap["ci_upper"],
            "bootstrap_seed": bootstrap_seed,
            "bootstrap_resamples": bootstrap_resamples,
        },
        "fold_relative_regressions": fold_regressions,
        "role_direct_mae_relative_regressions": role_direct_mae_regressions,
        "role_concordance_relative_regressions": role_concordance_regressions,
        "top25_direct_regret": {
            "incumbent": mean(top25_incumbent),
            "candidate": mean(top25_candidate),
        },
        "top25_ordinal_regret": {
            "incumbent": mean(top25_ordinal_incumbent),
            "candidate": mean(top25_ordinal_candidate),
        },
        "cross_role_concordance": {
            "incumbent": incumbent_cross,
            "candidate": candidate_cross,
            "relative_improvement": _relative_discordance_reduction(
                incumbent_cross, candidate_cross
            ),
            "relative_improvement_definition": "incumbent_discordance_reduction",
            "bootstrap_95_lower": cross_bootstrap["ci_lower"],
            "bootstrap_95_upper": cross_bootstrap["ci_upper"],
            "bootstrap_seed": bootstrap_seed,
            "bootstrap_resamples": bootstrap_resamples,
        },
    }


def _year(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")
    return value


def _percentile(ordered: Sequence[float], quantile: float) -> float:
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    numeric = float(value)
    return numeric if math.isfinite(numeric) else None


def _is_rank(value: Any) -> bool:
    numeric = _finite_or_none(value)
    return numeric is not None and 0.0 <= numeric <= 1.0


def _valid_pair(value: Any, *, bounded: bool) -> bool:
    pair = _mapping(value)
    numbers = [_finite_or_none(pair.get(key)) for key in ("incumbent", "candidate")]
    if any(number is None for number in numbers):
        return False
    if bounded:
        return all(0.0 <= number <= 1.0 for number in numbers)
    return all(number >= 0.0 for number in numbers)


def _gate(passed: bool, actual: Any, threshold: Any) -> dict[str, Any]:
    return {"passed": bool(passed), "actual": actual, "threshold": threshold}


def _relative_improvement(incumbent: float, candidate: float) -> float | None:
    if incumbent == 0.0:
        return 0.0 if candidate == 0.0 else None
    return (incumbent - candidate) / abs(incumbent)


def _relative_regression(incumbent: float, candidate: float) -> float | None:
    if incumbent == 0.0:
        return 0.0 if candidate == 0.0 else None
    return (candidate - incumbent) / abs(incumbent)


def _relative_discordance_reduction(
    incumbent: float, candidate: float
) -> float | None:
    incumbent_discordance = 1.0 - incumbent
    if incumbent_discordance == 0.0:
        return 0.0 if candidate == incumbent else None
    return (candidate - incumbent) / incumbent_discordance


def _relative_concordance_regression(
    incumbent: float, candidate: float
) -> float | None:
    if incumbent == 0.0:
        return 0.0 if candidate >= incumbent else None
    return (incumbent - candidate) / abs(incumbent)
