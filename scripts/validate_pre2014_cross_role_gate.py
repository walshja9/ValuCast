#!/usr/bin/env python3
"""Read-only validator for the permanent Plan 036 adjudication receipt.

Run only from the sealed execution checkout: HEAD must be the registered
execution commit R with the three terminal artifacts untracked, or its direct
artifact-only child S.  Later production validation must use a detached S
checkout; this validator intentionally rejects later production-code HEADs.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.pre2014_cross_role_gate import (  # noqa: E402
    BOOTSTRAP_SEED,
    DEFAULT_BOOTSTRAP_RESAMPLES,
    DIRECT_METRIC,
    MAX_FOLD_RELATIVE_REGRESSION,
    MAX_ROLE_RELATIVE_REGRESSION,
    MIN_CROSS_ROLE_RELATIVE_IMPROVEMENT,
    MIN_FOLD_ROLE_COVERAGE,
    MIN_OUTER_FOLDS,
    MIN_PRIMARY_RELATIVE_IMPROVEMENT,
    MIN_UNIQUE_PLAYERS_PER_ROLE,
    OUTCOME_COMPLETE_THROUGH,
    OUTCOME_HORIZON_YEARS,
    evaluate_pre2014_cross_role_gate,
)
from prospects.direct_7x7 import join_quality_starts  # noqa: E402
from prospects.pre2014_fold_scoring import (  # noqa: E402
    CANDIDATE_MODEL_FLAGS,
    score_outer_fold,
)
from prospects.extended_history import build_labeled_rows, outcome_label  # noqa: E402
from prospects.pre2014_readiness import (  # noqa: E402
    EXPECTED_COHORTS,
    PARITY_COHORT,
    PARITY_IDENTITY_COUNT,
    REGISTERED_IMPLEMENTATION_PATHS,
    REGISTERED_OUTER_FOLDS,
    REGISTERED_PREPARED_SOURCE_PATHS,
    REGISTERED_SOURCE_PATHS,
)
from quality.valucast_governor import (  # noqa: E402
    MAX_TOP25_PROSPECT_PITCHER_COUNT,
    MAX_TOP50_PROSPECT_PITCHER_RATE,
)
from scripts.run_pre2014_cross_role_gate import (  # noqa: E402
    ACQUISITION_CHECKPOINT_BATCH_SIZE,
    ACQUISITION_MAX_ATTEMPTS,
    CANDIDATE_SCORE_MODE,
    MATURE_COHORT_THROUGH,
    PROTOCOL,
    QUALITY_STARTS_SOURCE,
    REGISTERED_CUTOFF_DATE,
    REGISTRATION_COMMIT_PATHS,
    STRICT_OUTCOME_FETCH_MODE,
    _concordance,
    _current_board_evaluator,
    _draft_facts,
    _outcomes,
    _percentile_ranks,
    _prepared_rows,
    _quality_start_fetch_targets,
    _quality_starts_content_sha256,
    _regret,
    _resolved_games_from_qs_receipt,
    _resolved_seasons_from_provider_receipt,
    convert_fold_output,
    validate_registered_readiness,
)
from scripts.build_stage2_quality_starts import build_quality_starts  # noqa: E402


REGISTRATION_START = "<!-- plan036-registration:start -->"
REGISTRATION_END = "<!-- plan036-registration:end -->"
GOVERNOR_CHECK_ID = "prospect_top_board_role_shape"
REGISTERED_PLAN_REPO_PATH = "plans/036-pre2014-cross-role-calibration-gate.md"
REGISTERED_READINESS_REPO_PATH = (
    "data/validation/valucast_pre2014_cross_role_readiness.json"
)
REGISTERED_RESULT_REPO_PATH = (
    "data/validation/valucast_pre2014_cross_role_gate.json"
)
REGISTERED_EVIDENCE_REPO_PATH = (
    "data/validation/valucast_pre2014_cross_role_evidence.json"
)
REGISTERED_CHECKPOINT_REPO_PATH = (
    "data/research/extended_prospect_history/sealed-acquisition-checkpoint.json"
)
_TEST_ONLY_ALLOW_NO_GIT = False
EXPECTED_BOOTSTRAP = {
    "seed": BOOTSTRAP_SEED,
    "resamples": DEFAULT_BOOTSTRAP_RESAMPLES,
    "interval": "two_sided_95_percentile",
    "direct_mae": {
        "unit": "player_within_cohort_hierarchical",
        "point_statistic": "relative_mae_improvement",
    },
    "cross_role_concordance": {
        "unit": "cohort_then_identity_within_role",
        "point_statistic": "incumbent_discordance_reduction",
    },
}
EXPECTED_THRESHOLDS = {
    "minimum_outer_folds": MIN_OUTER_FOLDS,
    "minimum_unique_players_per_role": MIN_UNIQUE_PLAYERS_PER_ROLE,
    "minimum_fold_role_coverage": MIN_FOLD_ROLE_COVERAGE,
    "minimum_direct_mae_relative_improvement": MIN_PRIMARY_RELATIVE_IMPROVEMENT,
    "direct_mae_bootstrap_lower_strictly_gt": 0.0,
    "maximum_fold_relative_regression": MAX_FOLD_RELATIVE_REGRESSION,
    "maximum_role_concordance_relative_regression": MAX_ROLE_RELATIVE_REGRESSION,
    "top25_direct_regret_no_worse": True,
    "top25_ordinal_regret_no_worse": True,
    "minimum_cross_role_concordance_relative_improvement": (
        MIN_CROSS_ROLE_RELATIVE_IMPROVEMENT
    ),
    "cross_role_bootstrap_lower_strictly_gt": 0.0,
    "current_governor_required": True,
}
EXPECTED_GOVERNOR = {
    "check_id": GOVERNOR_CHECK_ID,
    "max_top25_pitcher_count": MAX_TOP25_PROSPECT_PITCHER_COUNT,
    "max_top50_pitcher_rate": MAX_TOP50_PROSPECT_PITCHER_RATE,
}
EXPECTED_RESULT_KEYS = {
    "artifact",
    "schema_version",
    "protocol",
    "status",
    "decision",
    "production_review_authorized",
    "claim_authorized",
    "registered_readiness_sha256",
    "candidate",
    "outer_folds",
    "quality_starts_sha256",
    "current_role_shape_governor",
    "fold_outputs",
    "evaluation",
    "evidence_bundle",
    "reservation_id",
}
EXPECTED_SPENT_KEYS = {
    "artifact",
    "protocol",
    "status",
    "decision",
    "production_review_authorized",
    "claim_authorized",
    "error_type",
    "evidence_bundle",
    "reservation_id",
}
EXPECTED_FOLD_KEYS = {
    "cohort_year",
    "metric",
    "players",
    "coverage_by_role",
    "top25_direct_regret",
    "top25_ordinal_regret",
    "cross_role_concordance",
    "role_concordance",
    "receipt",
}
EXPECTED_PLAYER_KEYS = {
    "player_id",
    "role",
    "target_percentile_rank",
    "incumbent_percentile_rank",
    "candidate_percentile_rank",
    "outcome_tier",
    "incumbent_score",
    "candidate_score",
    "direct_7x7_target",
}
EXPECTED_CALIBRATOR_KEYS = {
    "hitter.outcome",
    "hitter.impact",
    "pitcher.outcome",
    "pitcher.impact",
}
EXPECTED_REGISTRATION_KEYS = {
    "protocol",
    "registered_at",
    "status",
    "look_spent",
    "execution_authorized",
    "research_only",
    "automatic_promotion",
    "claim_authorized",
    "implementation_base_commit",
    "readiness",
    "result_path",
    "source_contract",
    "candidate",
    "outer_folds",
    "bootstrap",
    "primary_endpoint",
    "thresholds",
    "governor",
    "hashes",
    "result_contract",
    "limitations",
}


class ResultValidationError(ValueError):
    """Raised when a sealed result or one of its registered controls drifts."""


def _reject_constant(value: str) -> None:
    raise ResultValidationError(f"non-finite JSON constant is forbidden: {value}")


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_constant
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultValidationError(f"invalid JSON object: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ResultValidationError(f"JSON object required: {path}")
    return dict(payload)


def _load_registration(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ResultValidationError(f"registration is unreadable: {path}") from exc
    if text.count(REGISTRATION_START) != 1 or text.count(REGISTRATION_END) != 1:
        raise ResultValidationError("exactly one marked Plan 036 registration block is required")
    start = text.index(REGISTRATION_START) + len(REGISTRATION_START)
    end = text.index(REGISTRATION_END, start)
    block = text[start:end].strip()
    match = re.fullmatch(r"```json\s*(\{.*\})\s*```", block, flags=re.DOTALL)
    if match is None:
        raise ResultValidationError("marked Plan 036 registration block is invalid")
    try:
        payload = json.loads(match.group(1), parse_constant=_reject_constant)
    except json.JSONDecodeError as exc:
        raise ResultValidationError("marked Plan 036 registration JSON is invalid") from exc
    if not isinstance(payload, Mapping):
        raise ResultValidationError("Plan 036 registration must be a JSON object")
    return dict(payload)


def _same_path(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def _registration_path(value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ResultValidationError(
            f"{label} is not a canonical repo-relative POSIX path"
        )
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in value
        or "\\" in value
    ):
        raise ResultValidationError(
            f"{label} is not a canonical repo-relative POSIX path"
        )
    return ROOT.joinpath(*path.parts)


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            default=str,
        )
    except (TypeError, ValueError) as exc:
        raise ResultValidationError("result contains non-canonical values") from exc


def _require_exact_keys(value: Any, expected: set[str], *, label: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ResultValidationError(f"{label} schema drift")
    return value


def _record_signature(
    record: Any, *, label: str, git_blob_only: bool = False
) -> tuple[str, str, str]:
    expected_keys = (
        {"path", "git_blob", "binding"}
        if git_blob_only
        else {"path", "sha256", "git_blob"}
    )
    if not isinstance(record, Mapping) or set(record) != expected_keys:
        raise ResultValidationError(f"registration hash record drift: {label}")
    path = _registration_path(record.get("path"), label=label)
    binding = record.get("binding") if git_blob_only else record.get("sha256")
    if git_blob_only and binding != "git_blob_only_pre_reservation":
        raise ResultValidationError(f"registration binding is invalid: {label}")
    if not git_blob_only and not _is_sha256(binding):
        raise ResultValidationError(f"registration hash is invalid: {label}")
    git_blob = record.get("git_blob")
    if not isinstance(git_blob, str) or re.fullmatch(r"[0-9a-f]{40}", git_blob) is None:
        raise ResultValidationError(f"registration git blob is invalid: {label}")
    return os.path.normcase(os.path.abspath(path)), str(binding), git_blob


def _git_text(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ResultValidationError("registered Git topology is unreadable") from exc


def _git_bytes(*args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ResultValidationError("registered Git object is unreadable") from exc


def _name_status(base: str, head: str) -> dict[str, str]:
    changed: dict[str, str] = {}
    for line in _git_text("diff", "--name-status", base, head).splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            raise ResultValidationError("registered Git diff is malformed")
        status, raw_path = parts
        path = raw_path.replace("\\", "/")
        if path in changed:
            raise ResultValidationError("registered Git diff repeats a path")
        changed[path] = status
    return changed


def _worktree_status() -> dict[str, str]:
    paths: dict[str, str] = {}
    for line in _git_text(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
        f":(exclude){REGISTERED_SOURCE_PATHS['current_prospect_contract']}",
    ).splitlines():
        if len(line) < 4:
            raise ResultValidationError("registered Git status is malformed")
        status = line[:2]
        path = line[3:].strip('"').replace("\\", "/")
        if " -> " in path:
            raise ResultValidationError("registered Git status contains a rename")
        if path in paths:
            raise ResultValidationError("registered Git status repeats a path")
        paths[path] = status
    return paths


def _validate_git_bound_worktree_file(
    *,
    commit: str,
    repo_path: str,
    expected_blob: str | None = None,
    label: str,
) -> str:
    path = ROOT / repo_path
    if path.is_symlink():
        raise ResultValidationError(f"{label} must not be a symbolic link")
    if not path.is_file():
        raise ResultValidationError(f"{label} must be a regular file")
    entry = _git_text("ls-tree", commit, "--", repo_path)
    match = re.fullmatch(
        rf"(100644|100755) blob ([0-9a-f]{{40}})\t{re.escape(repo_path)}",
        entry,
    )
    if match is None:
        raise ResultValidationError(f"{label} is not a regular Git blob")
    committed_blob = match.group(2)
    if expected_blob is not None and committed_blob != expected_blob:
        raise ResultValidationError(f"{label} registered Git blob drift")
    working_blob = _git_text(
        "hash-object",
        f"--path={repo_path}",
        str(path.resolve()),
    )
    if working_blob != committed_blob:
        raise ResultValidationError(f"{label} worktree differs from sealed commit")
    return committed_blob


def _validate_execution_registration_files(execution_commit: str) -> None:
    for repo_path in sorted(REGISTRATION_COMMIT_PATHS):
        _validate_git_bound_worktree_file(
            commit=execution_commit,
            repo_path=repo_path,
            label=f"execution registration file:{repo_path}",
        )


def _validate_live_registered_implementations(
    registration: Mapping[str, Any], *, git_base_commit: str | None
) -> None:
    records = (registration.get("hashes") or {}).get("implementation_files")
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
        or len(records) != len(REGISTERED_IMPLEMENTATION_PATHS)
    ):
        raise ResultValidationError("registered implementation hashes are invalid")
    for index, (record, expected_path) in enumerate(
        zip(records, REGISTERED_IMPLEMENTATION_PATHS, strict=True)
    ):
        signature = _record_signature(
            record, label=f"live-implementation:{index}"
        )
        live_path = ROOT / expected_path
        if not _same_path(signature[0], live_path):
            raise ResultValidationError("registered implementation path drift")
        if live_path.is_symlink():
            raise ResultValidationError(
                "live registered implementation must not be a symbolic link"
            )
        if not live_path.is_file():
            raise ResultValidationError(
                "live registered implementation must be a regular file"
            )
        live_bytes = live_path.read_bytes()
        if git_base_commit is not None:
            _validate_git_bound_worktree_file(
                commit=git_base_commit,
                repo_path=expected_path,
                expected_blob=signature[2],
                label=f"live registered implementation:{expected_path}",
            )
            frozen_bytes = _git_bytes(
                "cat-file", "blob", f"{git_base_commit}:{expected_path}"
            )
            if hashlib.sha256(frozen_bytes).hexdigest() != signature[1]:
                raise ResultValidationError(
                    "frozen registered implementation hash drift"
                )
        elif hashlib.sha256(live_bytes).hexdigest() != signature[1]:
            raise ResultValidationError("live registered implementation hash drift")


def _validate_execution_result_git_topology(
    evidence: Mapping[str, Any], registration: Mapping[str, Any]
) -> None:
    implementation_commit = str(registration["implementation_base_commit"])
    execution_commit = str(evidence.get("execution_commit") or "")
    execution_topology = _git_text(
        "rev-list", "--parents", "-n", "1", execution_commit
    ).split()
    if execution_topology != [execution_commit, implementation_commit]:
        raise ResultValidationError(
            "execution commit is not the direct registration child"
        )
    registration_diff = _name_status(implementation_commit, execution_commit)
    if set(registration_diff) != REGISTRATION_COMMIT_PATHS or any(
        status not in {"A", "M"} for status in registration_diff.values()
    ):
        raise ResultValidationError("execution commit registration diff drift")
    _validate_execution_registration_files(execution_commit)

    possible_runtime_paths = {
        REGISTERED_RESULT_REPO_PATH,
        REGISTERED_EVIDENCE_REPO_PATH,
        REGISTERED_CHECKPOINT_REPO_PATH,
    }
    for runtime_path in possible_runtime_paths:
        if _git_text("ls-tree", execution_commit, "--", runtime_path):
            raise ResultValidationError(
                "terminal artifact already exists in execution commit"
            )
    runtime_paths = {
        REGISTERED_RESULT_REPO_PATH,
        REGISTERED_EVIDENCE_REPO_PATH,
    }
    checkpoint_path = ROOT / REGISTERED_CHECKPOINT_REPO_PATH
    if checkpoint_path.is_symlink():
        raise ResultValidationError("runtime checkpoint must not be a symbolic link")
    checkpoint_exists = checkpoint_path.is_file()
    if checkpoint_path.exists() and not checkpoint_exists:
        raise ResultValidationError("runtime checkpoint must be a regular file")
    if evidence.get("status") != "spent_error" or checkpoint_exists:
        runtime_paths.add(REGISTERED_CHECKPOINT_REPO_PATH)
    head = _git_text("rev-parse", "HEAD")
    dirty = _worktree_status()
    if head == execution_commit:
        if set(dirty) != runtime_paths or any(
            status != "??" for status in dirty.values()
        ):
            raise ResultValidationError("runtime result worktree topology drift")
        return

    terminal_topology = _git_text(
        "rev-list", "--parents", "-n", "1", head
    ).split()
    if terminal_topology != [head, execution_commit]:
        raise ResultValidationError(
            "terminal commit is not the direct execution child"
        )
    terminal_diff = _name_status(execution_commit, head)
    if set(terminal_diff) != runtime_paths or any(
        status != "A" for status in terminal_diff.values()
    ):
        raise ResultValidationError("terminal commit runtime diff drift")
    for runtime_path in runtime_paths:
        entry = _git_text("ls-tree", head, "--", runtime_path)
        match = re.fullmatch(
            rf"(100644|100755) blob [0-9a-f]{{40}}\t{re.escape(runtime_path)}",
            entry,
        )
        if match is None:
            raise ResultValidationError(
                "terminal commit artifact is not a regular Git blob"
            )
    if dirty:
        raise ResultValidationError("terminal result worktree is not clean")


def _load_registered_source(
    registration: Mapping[str, Any],
    key: str,
    *,
    git_base_commit: str | None,
) -> dict[str, Any]:
    records = (registration.get("hashes") or {}).get("source_files") or {}
    record = records.get(key) if isinstance(records, Mapping) else None
    git_blob_only = key == "current_prospect_contract"
    _record_signature(
        record,
        label=f"registered-source:{key}",
        git_blob_only=git_blob_only,
    )
    expected_path = REGISTERED_SOURCE_PATHS[key]
    try:
        if git_base_commit is None:
            path = _registration_path(record.get("path"), label=f"source:{key}")
            content = path.read_bytes()
        else:
            object_id = subprocess.run(
                ["git", "rev-parse", f"{git_base_commit}:{expected_path}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            if object_id != record.get("git_blob"):
                raise ResultValidationError(
                    f"registered source git blob drift: {key}"
                )
            content = subprocess.run(
                ["git", "cat-file", "blob", f"{git_base_commit}:{expected_path}"],
                cwd=ROOT,
                check=True,
                capture_output=True,
            ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ResultValidationError(
            f"registered source is unreadable: {key}"
        ) from exc
    if not git_blob_only and hashlib.sha256(content).hexdigest() != record.get(
        "sha256"
    ):
        raise ResultValidationError(f"registered source content hash drift: {key}")
    try:
        payload = json.loads(content.decode("utf-8"), parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultValidationError(f"registered source is invalid JSON: {key}") from exc
    if not isinstance(payload, Mapping):
        raise ResultValidationError(f"registered source must be an object: {key}")
    return dict(payload)


def _registered_label_inputs(
    registration: Mapping[str, Any], *, git_base_commit: str | None
) -> tuple[
    Mapping[str, Any],
    list[dict[str, Any]],
    Mapping[str, Any],
    dict[str, int],
]:
    prepared = _load_registered_source(
        registration, "prepared_artifact", git_base_commit=git_base_commit
    )
    draft_payload = _load_registered_source(
        registration, "draft_facts", git_base_commit=git_base_commit
    )
    try:
        mature_rows = [
            row
            for row in _prepared_rows(prepared)
            if int(row["cohort_year"]) <= MATURE_COHORT_THROUGH
        ]
        draft_facts = _draft_facts(draft_payload)
        cohort_by_identity = {
            f"{int(row['mlbam_id'])}_{row['role']}": int(row["cohort_year"])
            for row in mature_rows
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultValidationError("registered prepared/draft source is invalid") from exc
    if (
        not mature_rows
        or len(cohort_by_identity) != len(mature_rows)
        or any(cohort > MATURE_COHORT_THROUGH for cohort in cohort_by_identity.values())
    ):
        raise ResultValidationError("registered prepared mature identity set is invalid")
    return prepared, mature_rows, draft_facts, cohort_by_identity


def _compare_registered_hashes(
    registration_hashes: Any, readiness_hashes: Any
) -> None:
    if not isinstance(registration_hashes, Mapping) or not isinstance(
        readiness_hashes, Mapping
    ):
        raise ResultValidationError("registration/readiness hashes are missing")
    if set(registration_hashes) != {
        "source_files",
        "prepared_manifest_sources",
        "prepared_source_files",
        "implementation_files",
    } or set(readiness_hashes) != set(registration_hashes):
        raise ResultValidationError("registration hash schema drift")
    registered_sources = registration_hashes.get("source_files")
    readiness_sources = readiness_hashes.get("source_files")
    if not isinstance(registered_sources, Mapping) or not isinstance(
        readiness_sources, Mapping
    ) or set(registered_sources) != set(REGISTERED_SOURCE_PATHS) or set(
        readiness_sources
    ) != set(REGISTERED_SOURCE_PATHS):
        raise ResultValidationError("registration source hashes do not match readiness")
    for key in registered_sources:
        registered_signature = _record_signature(
            registered_sources[key],
            label=f"source:{key}",
            git_blob_only=key == "current_prospect_contract",
        )
        if registered_signature != _record_signature(
            readiness_sources[key],
            label=f"readiness-source:{key}",
            git_blob_only=key == "current_prospect_contract",
        ) or not _same_path(
            registered_signature[0], ROOT / REGISTERED_SOURCE_PATHS[key]
        ):
            raise ResultValidationError("registration source hashes do not match readiness")

    registered_prepared = registration_hashes.get("prepared_source_files")
    readiness_prepared = readiness_hashes.get("prepared_source_files")
    if (
        not isinstance(registered_prepared, Sequence)
        or isinstance(registered_prepared, (str, bytes))
        or not isinstance(readiness_prepared, Sequence)
        or isinstance(readiness_prepared, (str, bytes))
        or len(registered_prepared) != len(REGISTERED_PREPARED_SOURCE_PATHS)
        or len(readiness_prepared) != len(REGISTERED_PREPARED_SOURCE_PATHS)
    ):
        raise ResultValidationError("registration prepared-source hashes are invalid")
    for index, expected_path in enumerate(REGISTERED_PREPARED_SOURCE_PATHS):
        registered = _record_signature(
            registered_prepared[index], label=f"prepared-source:{index}"
        )
        readiness_record = _record_signature(
            readiness_prepared[index], label=f"readiness-prepared-source:{index}"
        )
        if registered != readiness_record or Path(registered[0]).as_posix().lower().endswith(
            expected_path.lower()
        ) is False:
            raise ResultValidationError(
                "registration prepared-source hashes do not match readiness"
            )

    registered_manifest = registration_hashes.get("prepared_manifest_sources")
    readiness_manifest = readiness_hashes.get("prepared_manifest_sources")
    if (
        not isinstance(registered_manifest, Sequence)
        or isinstance(registered_manifest, (str, bytes))
        or not isinstance(readiness_manifest, Sequence)
        or isinstance(readiness_manifest, (str, bytes))
        or len(registered_manifest) != len(REGISTERED_PREPARED_SOURCE_PATHS)
        or list(registered_manifest) != list(readiness_manifest)
    ):
        raise ResultValidationError("registration prepared-manifest hashes are invalid")
    for index, (source, record, expected_path) in enumerate(
        zip(
            registered_manifest,
            registered_prepared,
            REGISTERED_PREPARED_SOURCE_PATHS,
            strict=True,
        )
    ):
        if (
            not isinstance(source, Mapping)
            or set(source) != {"kind", "path", "sha256"}
            or source.get("kind") != "registered_prepared_source"
            or not Path(str(source.get("path"))).as_posix().lower().endswith(
                expected_path.lower()
            )
            or source.get("sha256") != record.get("sha256")
        ):
            raise ResultValidationError(
                f"registration prepared-manifest source drift: {index}"
            )

    registered_impl = registration_hashes.get("implementation_files")
    readiness_impl = readiness_hashes.get("implementation_files")
    if (
        not isinstance(registered_impl, Sequence)
        or isinstance(registered_impl, (str, bytes))
        or not isinstance(readiness_impl, Sequence)
        or isinstance(readiness_impl, (str, bytes))
    ):
        raise ResultValidationError("registration implementation hashes are invalid")
    registered_signatures = [
        _record_signature(record, label=f"implementation:{index}")
        for index, record in enumerate(registered_impl)
    ]
    readiness_signatures = [
        _record_signature(record, label=f"readiness-implementation:{index}")
        for index, record in enumerate(readiness_impl)
    ]
    if (
        registered_signatures != readiness_signatures
        or len(registered_signatures) != len(REGISTERED_IMPLEMENTATION_PATHS)
        or any(
            not Path(signature[0]).as_posix().lower().endswith(expected.lower())
            for signature, expected in zip(
                registered_signatures, REGISTERED_IMPLEMENTATION_PATHS, strict=True
            )
        )
    ):
        raise ResultValidationError(
            "registration implementation hashes do not match readiness"
        )


def _validate_registration(
    registration: Mapping[str, Any],
    *,
    registration_path: Path,
    readiness_path: Path,
    result_path: Path,
    readiness: Mapping[str, Any],
) -> str:
    if (
        not _same_path(registration_path, ROOT / REGISTERED_PLAN_REPO_PATH)
        or not _same_path(readiness_path, ROOT / REGISTERED_READINESS_REPO_PATH)
        or not _same_path(result_path, ROOT / REGISTERED_RESULT_REPO_PATH)
    ):
        raise ResultValidationError("registration fixed path drift")
    _require_exact_keys(registration, EXPECTED_REGISTRATION_KEYS, label="registration")
    readiness_ref = _require_exact_keys(
        registration.get("readiness"), {"path", "sha256"}, label="registration readiness"
    )
    readiness_sha = readiness_ref.get("sha256")
    if not _is_sha256(readiness_sha):
        raise ResultValidationError("registration readiness hash is invalid")
    if not _same_path(
        _registration_path(readiness_ref.get("path"), label="readiness"),
        readiness_path,
    ):
        raise ResultValidationError("registration readiness path drift")
    if not _same_path(
        _registration_path(registration.get("result_path"), label="result"),
        result_path,
    ):
        raise ResultValidationError("registration result path drift")
    if (
        registration.get("protocol") != PROTOCOL
        or registration.get("status") != "registered"
        or registration.get("look_spent") is not False
        or registration.get("execution_authorized") is not True
        or registration.get("research_only") is not True
        or registration.get("automatic_promotion") is not False
        or registration.get("claim_authorized") is not False
        or not isinstance(registration.get("registered_at"), str)
        or not registration.get("registered_at")
        or re.fullmatch(
            r"[0-9a-f]{40}", str(registration.get("implementation_base_commit") or "")
        )
        is None
    ):
        raise ResultValidationError("registration fixed controls drift")
    if registration.get("implementation_base_commit") != readiness.get(
        "implementation_base_commit"
    ):
        raise ResultValidationError("registration implementation commit drift")
    if registration.get("outer_folds") != list(REGISTERED_OUTER_FOLDS):
        raise ResultValidationError("registration outer folds drift")
    if registration.get("bootstrap") != EXPECTED_BOOTSTRAP:
        raise ResultValidationError("registration bootstrap drift")
    if registration.get("primary_endpoint") != DIRECT_METRIC:
        raise ResultValidationError("registration primary endpoint drift")
    if registration.get("thresholds") != EXPECTED_THRESHOLDS:
        raise ResultValidationError("registration thresholds drift")
    if registration.get("governor") != EXPECTED_GOVERNOR:
        raise ResultValidationError("registration governor thresholds drift")

    candidate = _require_exact_keys(
        registration.get("candidate"),
        {
            "candidate_count",
            "pitcher_investment_feature_mode",
            "rank_model_score_mode",
            "calibration",
            "head_blend",
            "governor_thresholds_changed",
            "forbidden_substitutions",
        },
        label="registration candidate",
    )
    forbidden = candidate.get("forbidden_substitutions")
    if (
        candidate.get("candidate_count") != 1
        or candidate.get("pitcher_investment_feature_mode")
        != CANDIDATE_MODEL_FLAGS["PITCHER_INVESTMENT_FEATURE_MODE"]
        or candidate.get("rank_model_score_mode") != CANDIDATE_SCORE_MODE
        or candidate.get("head_blend") != {"outcome": 0.58, "impact": 0.42}
        or candidate.get("governor_thresholds_changed") is not False
        or candidate.get("calibration") != "fold_trained_role_head_isotonic"
        or forbidden
        != [
            "raw_pick_value",
            "live_role_quantile",
            "governor_relaxation",
        ]
    ):
        raise ResultValidationError("registration candidate drift")

    source = _require_exact_keys(
        registration.get("source_contract"),
        {
            "prepared_path",
            "prepared_sha256",
            "prepared_manifest_path",
            "prepared_manifest_sha256",
            "draft_facts_path",
            "draft_facts_sha256",
            "cohorts",
            "declared_omissions",
            "outcome_complete_through",
            "outcome_horizon_years",
            "identity_key",
            "parity",
        },
        label="registration source contract",
    )
    if (
        source.get("cohorts") != list(EXPECTED_COHORTS)
        or source.get("declared_omissions") != [2020]
        or source.get("outcome_complete_through") != OUTCOME_COMPLETE_THROUGH
        or source.get("outcome_horizon_years") != OUTCOME_HORIZON_YEARS
        or source.get("identity_key") != "mlbam_id+role"
        or source.get("parity")
        != {
            "status": "ready",
            "cohort_year": PARITY_COHORT,
            "candidate_count": PARITY_IDENTITY_COUNT,
            "committed_count": PARITY_IDENTITY_COUNT,
            "extra": [],
            "missing": [],
        }
    ):
        raise ResultValidationError("registration source contract drift")
    registered_sources = (registration.get("hashes") or {}).get("source_files") or {}
    source_bindings = {
        "prepared_artifact": ("prepared_path", "prepared_sha256"),
        "prepared_manifest": ("prepared_manifest_path", "prepared_manifest_sha256"),
        "draft_facts": ("draft_facts_path", "draft_facts_sha256"),
    }
    for key, (path_key, hash_key) in source_bindings.items():
        registered_signature = _record_signature(
            registered_sources.get(key), label=f"hashes:{key}"
        )
        source_path = _registration_path(
            source.get(path_key), label=f"source-contract:{key}"
        )
        if (
            os.path.normcase(os.path.abspath(source_path))
            != registered_signature[0]
            or source.get(hash_key) != registered_signature[1]
        ):
            raise ResultValidationError("registration source contract hash drift")

    result_contract = registration.get("result_contract")
    limitations = registration.get("limitations")
    if (
        not isinstance(result_contract, Mapping)
        or set(result_contract)
        != {
            "single_use",
            "claim_authorized",
            "automatic_promotion",
            "terminal_evidence_path",
            "acquisition_checkpoint_path",
            "outcome_cutoff_date",
        }
        or result_contract.get("single_use") is not True
        or result_contract.get("claim_authorized") is not False
        or result_contract.get("automatic_promotion") is not False
        or limitations != ["cohort-season-completion pseudo-replay"]
    ):
        raise ResultValidationError("registration result contract drift")
    if result_contract.get("outcome_cutoff_date") != "2025-12-31":
        raise ResultValidationError("registration outcome cutoff drift")
    if (
        result_contract.get("terminal_evidence_path")
        != REGISTERED_EVIDENCE_REPO_PATH
        or result_contract.get("acquisition_checkpoint_path")
        != REGISTERED_CHECKPOINT_REPO_PATH
    ):
        raise ResultValidationError("registration result contract path drift")
    _compare_registered_hashes(registration.get("hashes"), readiness.get("hashes"))
    return str(readiness_sha)


def _validate_fold_schema(folds: Any, *, quality_starts_sha256: str) -> None:
    if not isinstance(folds, list) or [fold.get("cohort_year") for fold in folds] != list(
        REGISTERED_OUTER_FOLDS
    ):
        raise ResultValidationError("canonical fold order/schema drift")
    for fold in folds:
        fold = _require_exact_keys(fold, EXPECTED_FOLD_KEYS, label="fold")
        if fold.get("metric") != DIRECT_METRIC:
            raise ResultValidationError("canonical fold metric drift")
        players = fold.get("players")
        if not isinstance(players, list) or not players:
            raise ResultValidationError("canonical fold players are missing")
        identities = set()
        analysis_rows = []
        for player in players:
            _require_exact_keys(player, EXPECTED_PLAYER_KEYS, label="fold player")
            player_id = player.get("player_id")
            role = player.get("role")
            identity = (str(player_id), str(role))
            if (
                not str(player_id or "").isdigit()
                or role not in {"hitter", "pitcher"}
                or identity in identities
            ):
                raise ResultValidationError("fold player identity drift")
            identities.add(identity)
            numeric = {}
            for field in (
                "target_percentile_rank",
                "incumbent_percentile_rank",
                "candidate_percentile_rank",
                "outcome_tier",
                "direct_7x7_target",
                "incumbent_score",
                "candidate_score",
            ):
                try:
                    value = float(player[field])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ResultValidationError(
                        f"fold player {field} is not finite"
                    ) from exc
                if not math.isfinite(value) or (
                    field
                    in {
                        "target_percentile_rank",
                        "incumbent_percentile_rank",
                        "candidate_percentile_rank",
                        "outcome_tier",
                        "direct_7x7_target",
                    }
                    and not 0.0 <= value <= 1.0
                ):
                    raise ResultValidationError(
                        f"fold player {field} is not finite and bounded"
                    )
                numeric[field] = value
            analysis_rows.append(
                {
                    "mlbam_id": int(str(player_id)),
                    "role": role,
                    "outcome_tier": numeric["outcome_tier"],
                    "direct_7x7_target": numeric["direct_7x7_target"],
                    "incumbent_score": numeric["incumbent_score"],
                    "candidate_score": numeric["candidate_score"],
                }
            )
        target_ranks = _percentile_ranks(
            [row["direct_7x7_target"] for row in analysis_rows]
        )
        incumbent_ranks = _percentile_ranks(
            [row["incumbent_score"] for row in analysis_rows]
        )
        candidate_ranks = _percentile_ranks(
            [row["candidate_score"] for row in analysis_rows]
        )
        for index, player in enumerate(players):
            expected = {
                "target_percentile_rank": target_ranks[index],
                "incumbent_percentile_rank": incumbent_ranks[index],
                "candidate_percentile_rank": candidate_ranks[index],
            }
            if any(
                not math.isclose(
                    float(player[field]), value, rel_tol=0.0, abs_tol=1e-12
                )
                for field, value in expected.items()
            ):
                raise ResultValidationError("fold percentile ranks do not recompute")
        expected_coverage = {}
        expected_role_concordance = {}
        for role in ("hitter", "pitcher"):
            role_rows = [row for row in analysis_rows if row["role"] == role]
            expected_coverage[role] = {
                "eligible_identity_count": len(role_rows),
                "scored_outcome_count": len(role_rows),
                "rate": 1.0,
            }
            try:
                expected_role_concordance[role] = {
                    mode: _concordance(
                        role_rows,
                        f"{mode}_score",
                        target_field="outcome_tier",
                        cross_role=False,
                    )
                    for mode in ("incumbent", "candidate")
                }
            except ValueError as exc:
                raise ResultValidationError(str(exc)) from exc
        try:
            expected_direct_regret = {
                mode: _regret(
                    analysis_rows, f"{mode}_score", "direct_7x7_target"
                )
                for mode in ("incumbent", "candidate")
            }
            expected_ordinal_regret = {
                mode: _regret(analysis_rows, f"{mode}_score", "outcome_tier")
                for mode in ("incumbent", "candidate")
            }
            expected_cross = {
                mode: _concordance(
                    analysis_rows,
                    f"{mode}_score",
                    target_field="outcome_tier",
                    cross_role=True,
                )
                for mode in ("incumbent", "candidate")
            }
        except ValueError as exc:
            raise ResultValidationError(str(exc)) from exc
        derived = {
            "coverage_by_role": expected_coverage,
            "top25_direct_regret": expected_direct_regret,
            "top25_ordinal_regret": expected_ordinal_regret,
            "cross_role_concordance": expected_cross,
            "role_concordance": expected_role_concordance,
        }
        if any(
            _canonical(fold.get(key)) != _canonical(expected)
            for key, expected in derived.items()
        ):
            raise ResultValidationError("fold derived summaries do not recompute")
        receipt = _require_exact_keys(
            fold.get("receipt"),
            {
                "calibrator_hashes",
                "quality_starts_sha256",
                "identity_count",
                "scoring_provenance",
            },
            label="fold receipt",
        )
        calibrators = receipt.get("calibrator_hashes")
        provenance = _require_exact_keys(
            receipt.get("scoring_provenance"),
            {
                "calibration_strategy",
                "calibration_mature_through",
                "outer_train_through",
                "inner_fold_years",
                "outer_reference_sha256",
                "inner_folds",
            },
            label="fold scoring provenance",
        )
        cohort_year = int(fold["cohort_year"])
        inner_years = provenance.get("inner_fold_years")
        inner_folds = provenance.get("inner_folds")
        if (
            not isinstance(calibrators, Mapping)
            or set(calibrators) != EXPECTED_CALIBRATOR_KEYS
            or any(not _is_sha256(value) for value in calibrators.values())
            or receipt.get("quality_starts_sha256") != quality_starts_sha256
            or receipt.get("identity_count") != len(players)
            or provenance.get("calibration_strategy")
            != "leave_one_cohort_out_within_outer_mature_pool"
            or provenance.get("calibration_mature_through") != cohort_year - 4
            or provenance.get("outer_train_through") != cohort_year - 4
            or not _is_sha256(provenance.get("outer_reference_sha256"))
            or not isinstance(inner_years, list)
            or inner_years != sorted(set(inner_years))
            or not isinstance(inner_folds, list)
            or len(inner_folds) != len(inner_years)
        ):
            raise ResultValidationError("fold receipt hash/schema drift")
        for inner_year, inner in zip(inner_years, inner_folds, strict=True):
            remaining = [year for year in inner_years if year != inner_year]
            inner = _require_exact_keys(
                inner,
                {
                    "test_year",
                    "target_complete_by",
                    "train_through",
                    "training_strategy",
                    "reference_sha256",
                },
                label="inner-fold scoring provenance",
            )
            if (
                not remaining
                or inner.get("test_year") != inner_year
                or inner.get("target_complete_by") != inner_year + 4
                or inner.get("target_complete_by") > cohort_year
                or inner.get("train_through") != max(remaining)
                or inner.get("training_strategy") != "leave_one_cohort_out"
                or not _is_sha256(inner.get("reference_sha256"))
            ):
                raise ResultValidationError("fold receipt hash/schema drift")


def _validate_governor_receipt(
    receipt: Any, *, reservation_id: str, registration_governor: Mapping[str, Any]
) -> bool:
    if not isinstance(receipt, Mapping):
        raise ResultValidationError("current-board governor receipt is missing")
    declared_hash = receipt.get("receipt_sha256")
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    actual_hash = hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()
    governor = receipt.get("role_shape_governor_check")
    metrics = governor.get("metrics") if isinstance(governor, Mapping) else None
    passed = receipt.get("passed")
    if (
        not isinstance(passed, bool)
        or receipt.get("unchanged_thresholds") is not True
        or receipt.get("candidate_model_flags") != CANDIDATE_MODEL_FLAGS
        or receipt.get("model_score_mode") != CANDIDATE_SCORE_MODE
        or receipt.get("reservation_id") != reservation_id
        or receipt.get("governor_scope") != "prospect_top_board_role_shape"
        or receipt.get("full_governor_required_at")
        != "post_look_pre_publication"
        or declared_hash != actual_hash
        or not isinstance(governor, Mapping)
        or governor.get("id") != registration_governor.get("check_id")
        or governor.get("status") != ("passed" if passed else "failed")
        or not isinstance(metrics, Mapping)
        or metrics.get("max_top25_pitcher_count")
        != registration_governor.get("max_top25_pitcher_count")
        or metrics.get("max_top50_pitcher_rate")
        != registration_governor.get("max_top50_pitcher_rate")
    ):
        raise ResultValidationError("current-board governor receipt drift")
    return passed


def _validate_file_record(
    record: Any, *, label: str, expected_path: Path | None = None
) -> tuple[Path, str]:
    if not isinstance(record, Mapping) or set(record) != {"path", "sha256"}:
        raise ResultValidationError(f"{label} file record drift")
    path = _registration_path(record.get("path"), label=label)
    sha256 = record.get("sha256")
    if not _is_sha256(sha256):
        raise ResultValidationError(f"{label} hash is invalid")
    if expected_path is not None and not _same_path(path, expected_path):
        raise ResultValidationError(f"{label} path drift")
    if path.is_symlink():
        raise ResultValidationError(f"{label} must not be a symbolic link")
    if not path.is_file():
        raise ResultValidationError(f"{label} must be a regular file")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ResultValidationError(f"{label} file is unreadable") from exc
    if actual != sha256:
        raise ResultValidationError(f"{label} content hash drift")
    return path, str(sha256)


def _result_contract_path(
    registration: Mapping[str, Any], key: str
) -> Path | None:
    contract = registration.get("result_contract")
    if not isinstance(contract, Mapping) or key not in contract:
        return None
    return _registration_path(contract[key], label=f"result_contract.{key}")


def _validate_terminal_evidence(
    result: Mapping[str, Any],
    registration: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any],
    readiness_sha256: str,
    registration_sha256: str,
    git_base_commit: str | None,
) -> dict[str, Any]:
    bundle = result.get("evidence_bundle")
    if not isinstance(bundle, Mapping) or set(bundle) != {"terminal_evidence"}:
        raise ResultValidationError("terminal evidence bundle schema drift")
    expected_path = _result_contract_path(registration, "terminal_evidence_path")
    evidence_path, _evidence_sha = _validate_file_record(
        bundle["terminal_evidence"],
        label="terminal evidence",
        expected_path=expected_path,
    )
    evidence = _load_json_object(evidence_path)
    reservation_id = result.get("reservation_id")
    if (
        evidence.get("artifact") != "valucast_plan036_terminal_evidence"
        or evidence.get("schema_version") != 1
        or evidence.get("reservation_id") != reservation_id
        or evidence.get("registered_readiness_sha256") != readiness_sha256
        or evidence.get("implementation_base_commit")
        != registration.get("implementation_base_commit")
        or evidence.get("status") != result.get("status")
    ):
        raise ResultValidationError("terminal evidence reservation binding drift")
    if evidence.get("registration_sha256") != registration_sha256:
        raise ResultValidationError("terminal registration hash drift")
    if (
        re.fullmatch(r"[0-9a-f]{40}", str(evidence.get("execution_commit") or ""))
        is None
        or evidence.get("registration_path") != REGISTERED_PLAN_REPO_PATH
        or evidence.get("acquisition_checkpoint_path")
        != REGISTERED_CHECKPOINT_REPO_PATH
        or evidence.get("outcome_cutoff_date") != REGISTERED_CUTOFF_DATE
    ):
        raise ResultValidationError("terminal execution context drift")
    if result.get("status") == "spent_error":
        if evidence.get("error_type") != result.get("error_type"):
            raise ResultValidationError("spent evidence error binding drift")
        return evidence

    required = {
        "canonical_outcomes",
        "labeled_contract",
        "quality_starts",
        "fold_outputs",
        "current_role_shape_governor",
        "evaluation",
        "quality_starts_sha256",
        "registration_sha256",
        "execution_commit",
        "registration_path",
        "acquisition_checkpoint_path",
        "outcome_cutoff_date",
    }
    if not required.issubset(evidence):
        raise ResultValidationError("terminal evidence is incomplete")
    if (
        _canonical(evidence["fold_outputs"])
        != _canonical(result.get("fold_outputs"))
        or _canonical(evidence["current_role_shape_governor"])
        != _canonical(result.get("current_role_shape_governor"))
        or _canonical(evidence["evaluation"])
        != _canonical(result.get("evaluation"))
        or evidence["quality_starts_sha256"]
        != result.get("quality_starts_sha256")
    ):
        raise ResultValidationError("terminal evidence/result cross-link drift")

    outcomes = evidence.get("canonical_outcomes")
    contract = evidence.get("labeled_contract")
    quality_starts_evidence = evidence.get("quality_starts")
    if not isinstance(outcomes, Mapping) or not isinstance(contract, Mapping):
        raise ResultValidationError("terminal outcome evidence is malformed")
    if (
        not isinstance(quality_starts_evidence, Mapping)
        or set(quality_starts_evidence)
        != {"input_contract", "input_descriptor", "sidecar", "provider"}
    ):
        raise ResultValidationError("terminal quality-start evidence is malformed")
    sidecar = quality_starts_evidence.get("sidecar")
    seasons = outcomes.get("historical_mlb_seasons")
    rows = contract.get("rows")
    if not isinstance(seasons, Mapping) or not isinstance(rows, list):
        raise ResultValidationError("terminal labeled evidence is malformed")
    prepared, mature_rows, draft_facts, registered_cohort_by_identity = (
        _registered_label_inputs(
            registration,
            git_base_commit=git_base_commit,
        )
    )
    if set(seasons) != set(registered_cohort_by_identity):
        raise ResultValidationError("terminal identity set does not match registered prepared rows")
    sidecar_input = sidecar.get("input") if isinstance(sidecar, Mapping) else None
    if (
        not isinstance(sidecar, Mapping)
        or set(sidecar)
        != {
            "schema",
            "version",
            "status",
            "source",
            "input",
            "coverage",
            "validation",
            "rows",
            "blockers",
            "reservation_id",
            "content_sha256",
        }
        or sidecar.get("schema") != "valucast_stage2_quality_starts"
        or sidecar.get("version") != "1.0.0"
        or sidecar.get("status") != "ready"
        or sidecar.get("blockers") != []
        or sidecar.get("reservation_id") != reservation_id
        or sidecar.get("source") != QUALITY_STARTS_SOURCE
        or quality_starts_evidence.get("provider") != QUALITY_STARTS_SOURCE
        or quality_starts_evidence.get("input_descriptor") != sidecar_input
        or not isinstance(sidecar_input, Mapping)
        or set(sidecar_input)
        != {
            "kind",
            "document_path",
            "json_pointer",
            "sha256",
            "cutoff_date",
        }
        or sidecar_input.get("kind") != "embedded_json"
        or sidecar_input.get("json_pointer")
        != "/quality_starts/input_contract"
        or sidecar_input.get("cutoff_date") != "2025-12-31"
        or not _same_path(
            _registration_path(
                sidecar_input.get("document_path"), label="QS input document"
            ),
            _result_contract_path(registration, "terminal_evidence_path"),
        )
        or sidecar.get("content_sha256")
        != _quality_starts_content_sha256(sidecar)
        or sidecar.get("content_sha256") != result.get("quality_starts_sha256")
    ):
        raise ResultValidationError("terminal quality-start evidence drift")
    quality_input = copy.deepcopy(quality_starts_evidence["input_contract"])
    if not isinstance(quality_input, Mapping):
        raise ResultValidationError("terminal quality-start input is malformed")
    encoded_input = json.dumps(
        quality_input, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    if hashlib.sha256(encoded_input).hexdigest() != sidecar_input.get("sha256"):
        raise ResultValidationError("terminal quality-start input hash drift")
    expected_qs_keys = {
        (int(str(identity).removesuffix("_pitcher")), int(season["year"]))
        for identity, season_rows in seasons.items()
        if str(identity).endswith("_pitcher")
        for season in season_rows
    }
    expected_pitcher_rows = sum(
        len(season_rows)
        for identity, season_rows in seasons.items()
        if str(identity).endswith("_pitcher")
    )
    try:
        actual_qs_keys = [
            (int(row["mlbam_id"]), int(row["season"]))
            for row in sidecar.get("rows") or []
        ]
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultValidationError("terminal quality-start rows are malformed") from exc
    if (
        len(actual_qs_keys) != len(set(actual_qs_keys))
        or set(actual_qs_keys) != expected_qs_keys
        or sidecar.get("coverage")
        != {
            "source_rows": expected_pitcher_rows,
            "unique_player_seasons": len(expected_qs_keys),
            "resolved_player_seasons": len(expected_qs_keys),
            "post_join_rows_with_qs": expected_pitcher_rows,
        }
    ):
        raise ResultValidationError("terminal quality-start coverage binding drift")

    cohort_by_identity = {}
    labels = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise ResultValidationError("terminal labeled row is malformed")
        identity = f"{int(row['mlbam_id'])}_{row['role']}"
        if identity in cohort_by_identity:
            raise ResultValidationError("terminal labeled identity is duplicated")
        cohort = int(row["cohort_year"])
        cohort_by_identity[identity] = cohort
        if identity not in seasons:
            raise ResultValidationError("terminal labeled outcome is missing")
        expected_label = outcome_label(
            seasons[identity],
            str(row["role"]),
            cohort,
            horizon_years=OUTCOME_HORIZON_YEARS,
        )
        if row.get("outcome") != expected_label:
            raise ResultValidationError("terminal outcome label does not recompute")
        labels[(cohort, str(row["mlbam_id"]), str(row["role"]))] = {
            "bust": 0.0,
            "role": 0.5,
            "star": 1.0,
        }[expected_label]
    if set(seasons) != set(cohort_by_identity):
        raise ResultValidationError("terminal outcome identity set drift")
    for fold in result.get("fold_outputs") or []:
        cohort = int(fold["cohort_year"])
        expected_identities = {
            (player_id, role)
            for year, player_id, role in labels
            if year == cohort
        }
        observed = {
            (str(player["player_id"]), str(player["role"]))
            for player in fold.get("players") or []
        }
        if observed != expected_identities or any(
            not math.isclose(
                float(player["outcome_tier"]),
                labels[(cohort, str(player["player_id"]), str(player["role"]))],
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            for player in fold.get("players") or []
        ):
            raise ResultValidationError("terminal fold/label identity drift")

    provider = outcomes.get("provider_receipt")
    expected_provider_keys = {
        "mode",
        "reservation_id",
        "outcome_cutoff_date",
        "checkpoint",
        "target_identity_count",
        "receipt_identity_count",
        "resolved_identity_count",
        "legacy_contract_cache_used",
    }
    if not isinstance(provider, Mapping) or set(provider) != expected_provider_keys:
        raise ResultValidationError("strict acquisition provider receipt is malformed")
    expected_identities = sorted(registered_cohort_by_identity)
    if (
        provider.get("mode") != STRICT_OUTCOME_FETCH_MODE
        or provider.get("reservation_id") != reservation_id
        or provider.get("outcome_cutoff_date") != REGISTERED_CUTOFF_DATE
        or provider.get("target_identity_count") != len(expected_identities)
        or provider.get("receipt_identity_count") != len(expected_identities)
        or provider.get("resolved_identity_count") != len(expected_identities)
        or provider.get("legacy_contract_cache_used") is not False
    ):
        raise ResultValidationError("strict acquisition provider binding drift")
    checkpoint_record = provider.get("checkpoint")
    if checkpoint_record is None:
        raise ResultValidationError("acquisition checkpoint receipt is missing")
    checkpoint_path = _result_contract_path(
        registration, "acquisition_checkpoint_path"
    )
    checkpoint_file, _checkpoint_sha = _validate_file_record(
        checkpoint_record,
        label="acquisition checkpoint",
        expected_path=checkpoint_path,
    )
    checkpoint = _load_json_object(checkpoint_file)
    expected_checkpoint_keys = {
        "artifact",
        "schema_version",
        "reservation_id",
        "registration_sha256",
        "registered_readiness_sha256",
        "outcome_cutoff_date",
        "status",
        "comparison_context",
        "fetch_policy",
        "target_identities",
        "raw_response_receipts",
        "coverage",
        "remaining",
        "quality_starts_acquisition",
    }
    fetch_policy = {
        "mode": STRICT_OUTCOME_FETCH_MODE,
        "legacy_contract_cache_used": False,
        "max_attempts_per_identity": ACQUISITION_MAX_ATTEMPTS,
        "checkpoint_batch_size": ACQUISITION_CHECKPOINT_BATCH_SIZE,
    }
    comparison_context = checkpoint.get("comparison_context")
    expected_contract_record = (
        ((registration.get("hashes") or {}).get("source_files") or {}).get(
            "current_prospect_contract"
        )
    )
    receipts = checkpoint.get("raw_response_receipts")
    coverage = checkpoint.get("coverage")
    if (
        set(checkpoint) != expected_checkpoint_keys
        or checkpoint.get("artifact")
        != "valucast_plan036_sealed_acquisition_checkpoint"
        or checkpoint.get("schema_version") != 1
        or checkpoint.get("reservation_id") != reservation_id
        or checkpoint.get("registered_readiness_sha256") != readiness_sha256
        or checkpoint.get("registration_sha256") != registration_sha256
        or checkpoint.get("outcome_cutoff_date") != REGISTERED_CUTOFF_DATE
        or checkpoint.get("status") != "ready"
        or checkpoint.get("fetch_policy") != fetch_policy
        or checkpoint.get("target_identities") != expected_identities
        or checkpoint.get("remaining") != []
        or not isinstance(comparison_context, Mapping)
        or set(comparison_context) != {
            "source",
            "record",
            "used_as_outcome_truth",
        }
        or comparison_context.get("source")
        != "registered_current_prospect_contract"
        or comparison_context.get("record") != expected_contract_record
        or comparison_context.get("used_as_outcome_truth") is not False
        or not isinstance(receipts, Mapping)
        or set(receipts) != set(expected_identities)
        or coverage
        != {
            "target_identity_count": len(expected_identities),
            "receipt_identity_count": len(expected_identities),
            "resolved_identity_count": len(expected_identities),
            "remaining_identity_count": 0,
        }
    ):
        raise ResultValidationError("acquisition checkpoint binding drift")
    try:
        receipt_seasons = {
            identity: _resolved_seasons_from_provider_receipt(
                receipts[identity], identity=identity
            )
            for identity in expected_identities
        }
        canonical_checkpoint = _outcomes(
            receipt_seasons, registered_cohort_by_identity
        )
        rebuilt_rows = build_labeled_rows(
            mature_rows,
            canonical_checkpoint,
            draft_facts,
            horizon_years=OUTCOME_HORIZON_YEARS,
        )
    except ValueError as exc:
        raise ResultValidationError(str(exc)) from exc
    if _canonical(canonical_checkpoint) != _canonical(seasons):
        raise ResultValidationError("acquisition receipt outcome drift")
    if _canonical(rebuilt_rows) != _canonical(rows):
        raise ResultValidationError(
            "terminal labeled contract does not match registered prepared rows"
        )

    qs_state = checkpoint.get("quality_starts_acquisition")
    expected_qs_targets = _quality_start_fetch_targets(quality_input)
    qs_receipts = (
        qs_state.get("raw_response_receipts")
        if isinstance(qs_state, Mapping)
        else None
    )
    expected_qs_policy = {
        "max_attempts_per_player_season": ACQUISITION_MAX_ATTEMPTS,
        "checkpoint_batch_size": ACQUISITION_CHECKPOINT_BATCH_SIZE,
    }
    if (
        not isinstance(qs_state, Mapping)
        or set(qs_state)
        != {
            "reservation_id",
            "status",
            "input",
            "source",
            "fetch_policy",
            "target_player_seasons",
            "raw_response_receipts",
            "coverage",
            "remaining",
        }
        or qs_state.get("reservation_id") != reservation_id
        or qs_state.get("status") != "ready"
        or qs_state.get("input") != sidecar_input
        or qs_state.get("source") != QUALITY_STARTS_SOURCE
        or qs_state.get("fetch_policy") != expected_qs_policy
        or qs_state.get("target_player_seasons") != expected_qs_targets
        or qs_state.get("remaining") != []
        or not isinstance(qs_receipts, Mapping)
        or set(qs_receipts) != set(expected_qs_targets)
        or qs_state.get("coverage")
        != {
            "target_player_season_count": len(expected_qs_targets),
            "receipt_player_season_count": len(expected_qs_targets),
            "resolved_player_season_count": len(expected_qs_targets),
            "remaining_player_season_count": 0,
        }
    ):
        raise ResultValidationError("quality-start acquisition receipt drift")
    try:
        games_by_key = {
            key: _resolved_games_from_qs_receipt(qs_receipts[key], key=key)
            for key in expected_qs_targets
        }
        history_rows = [
            {
                "id": int(str(identity).removesuffix("_pitcher")),
                "season": int(season["year"]),
                "gs": season["gs"],
            }
            for identity, season_rows in canonical_checkpoint.items()
            if str(identity).endswith("_pitcher")
            for season in season_rows
            if "gs" in season
        ]
        rebuilt_sidecar = build_quality_starts(
            copy.deepcopy(dict(quality_input)),
            {"rows": history_rows},
            input_path=str(sidecar_input["document_path"]),
            input_sha256=str(sidecar_input["sha256"]),
            fetcher=lambda mlbam_id, _group, season: games_by_key[
                f"{int(mlbam_id)}:{int(season)}"
            ],
            checkpoint_path=None,
            delay=0.0,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultValidationError(
            "quality-start acquisition receipt cannot rederive sidecar"
        ) from exc
    rebuilt_sidecar["reservation_id"] = reservation_id
    rebuilt_sidecar["input"] = copy.deepcopy(dict(sidecar_input))
    rebuilt_sidecar["content_sha256"] = _quality_starts_content_sha256(
        rebuilt_sidecar
    )
    if _canonical(rebuilt_sidecar) != _canonical(sidecar):
        raise ResultValidationError("quality-start sidecar does not rederive")

    try:
        registered_contract = {
            "artifact": "valucast_extended_prospect_history_labeled",
            "schema_version": 1,
            "mode": "execute_sealed_look",
            "source_policy": {
                "separate_research_contract": True,
                "production_contract_overwritten": False,
                "caller_supplied_outcome_cache": True,
                "caller_supplied_draft_cache": True,
                "horizon_years": OUTCOME_HORIZON_YEARS,
            },
            "candidate_count": len(mature_rows),
            "labeled_row_count": len(rebuilt_rows),
            "identity_parity": prepared.get("identity_parity"),
            "rows": copy.deepcopy(rebuilt_rows),
            "historical_mlb_seasons": join_quality_starts(
                canonical_checkpoint, rebuilt_sidecar
            ),
            "quality_starts": copy.deepcopy(rebuilt_sidecar),
        }
        recomputed_folds = []
        for cohort_year in REGISTERED_OUTER_FOLDS:
            eligible = {
                (str(row["mlbam_id"]), str(row["role"]))
                for row in rebuilt_rows
                if int(row["cohort_year"]) == cohort_year
            }
            mature_cohort_years = sorted(
                {
                    int(row["cohort_year"])
                    for row in rebuilt_rows
                    if int(row["cohort_year"])
                    <= cohort_year - OUTCOME_HORIZON_YEARS
                }
            )
            scored = score_outer_fold(registered_contract, cohort_year)
            recomputed_folds.append(
                convert_fold_output(
                    scored,
                    cohort_year=cohort_year,
                    eligible_identities=eligible,
                    quality_starts_sha256=str(rebuilt_sidecar["content_sha256"]),
                    mature_cohort_years=mature_cohort_years,
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultValidationError("registered fold recomputation failed") from exc
    if _canonical(recomputed_folds) != _canonical(result.get("fold_outputs")):
        raise ResultValidationError(
            "registered fold recomputation drift: exact folds do not recompute"
        )

    try:
        registered_sources = {
            key: _load_registered_source(
                registration,
                key,
                git_base_commit=git_base_commit,
            )
            for key in REGISTERED_SOURCE_PATHS
        }
        recomputed_governor = _current_board_evaluator(registered_sources)(
            reservation_id=str(reservation_id),
            research_contract=registered_contract,
            quality_starts=rebuilt_sidecar,
            readiness=readiness,
        )
        _validate_governor_receipt(
            recomputed_governor,
            reservation_id=str(reservation_id),
            registration_governor=registration["governor"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ResultValidationError("registered governor recomputation failed") from exc
    if _canonical(recomputed_governor) != _canonical(
        result.get("current_role_shape_governor")
    ):
        raise ResultValidationError("registered governor recomputation drift")
    return evidence


def _validate_spent_result(
    result: Mapping[str, Any],
    registration: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any],
    readiness_sha256: str,
    registration_sha256: str,
    git_base_commit: str | None,
) -> dict[str, Any]:
    _require_exact_keys(result, EXPECTED_SPENT_KEYS, label="spent result")
    if (
        result.get("artifact") != "valucast_pre2014_cross_role_gate"
        or result.get("protocol") != PROTOCOL
        or result.get("status") != "spent_error"
        or result.get("decision") != "production_review_not_authorized"
        or result.get("production_review_authorized") is not False
        or result.get("claim_authorized") is not False
        or not isinstance(result.get("error_type"), str)
        or not result.get("error_type")
        or not isinstance(result.get("reservation_id"), str)
        or not result.get("reservation_id")
    ):
        raise ResultValidationError("spent result is not a permanent fail-closed receipt")
    evidence = _validate_terminal_evidence(
        result,
        registration,
        readiness=readiness,
        readiness_sha256=readiness_sha256,
        registration_sha256=registration_sha256,
        git_base_commit=git_base_commit,
    )
    if git_base_commit is not None:
        _validate_execution_result_git_topology(evidence, registration)
    return {
        "valid": True,
        "status": "spent_error",
        "production_review_authorized": False,
        "claim_authorized": False,
    }


def validate_result_files(
    *,
    result_path: Path | str,
    readiness_path: Path | str,
    registration_path: Path | str,
) -> dict[str, Any]:
    """Validate all Plan 036 seals and deterministically replay adjudication."""
    result_path = Path(result_path)
    readiness_path = Path(readiness_path)
    registration_path = Path(registration_path)
    if result_path.is_symlink():
        raise ResultValidationError("result must not be a symbolic link")
    if not result_path.is_file():
        raise ResultValidationError("result must be a regular file")
    if readiness_path.is_symlink() or registration_path.is_symlink():
        raise ResultValidationError(
            "readiness and registration must not be symbolic links"
        )
    if not readiness_path.is_file() or not registration_path.is_file():
        raise ResultValidationError(
            "readiness and registration must be regular files"
        )
    result = _load_json_object(result_path)
    registration = _load_registration(registration_path)
    registration_sha = hashlib.sha256(_canonical(registration).encode("utf-8")).hexdigest()
    try:
        readiness = _load_json_object(readiness_path)
        readiness_sha = _validate_registration(
            registration,
            registration_path=registration_path,
            readiness_path=readiness_path,
            result_path=result_path,
            readiness=readiness,
        )
        try:
            readiness_path.resolve().relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ResultValidationError(
                "registered readiness must be inside the repository"
            ) from exc
        if not (ROOT / ".git").exists():
            if not _TEST_ONLY_ALLOW_NO_GIT:
                raise ResultValidationError(
                    "sealed-checkout Git metadata is required"
                )
            git_base_commit = None
        else:
            git_base_commit = str(registration["implementation_base_commit"])
        validate_registered_readiness(
            readiness_path,
            readiness_sha,
            result_path,
            git_base_commit=git_base_commit,
        )
        _validate_live_registered_implementations(
            registration, git_base_commit=git_base_commit
        )
    except (OSError, ValueError) as exc:
        if isinstance(exc, ResultValidationError):
            raise
        raise ResultValidationError(str(exc)) from exc

    status = result.get("status")
    if status == "spent_error":
        return _validate_spent_result(
            result,
            registration,
            readiness=readiness,
            readiness_sha256=readiness_sha,
            registration_sha256=registration_sha,
            git_base_commit=git_base_commit,
        )
    if status not in {"passed", "failed"}:
        raise ResultValidationError("result is not a permanent terminal status")

    _require_exact_keys(result, EXPECTED_RESULT_KEYS, label="result")
    reservation_id = result.get("reservation_id")
    if (
        result.get("artifact") != "valucast_pre2014_cross_role_gate"
        or result.get("schema_version") != 1
        or result.get("protocol") != PROTOCOL
        or result.get("claim_authorized") is not False
        or not isinstance(reservation_id, str)
        or not reservation_id
        or result.get("registered_readiness_sha256") != readiness_sha
        or result.get("candidate")
        != {
            "model_flags": CANDIDATE_MODEL_FLAGS,
            "model_score_mode": CANDIDATE_SCORE_MODE,
        }
        or result.get("outer_folds") != list(REGISTERED_OUTER_FOLDS)
        or not _is_sha256(result.get("quality_starts_sha256"))
    ):
        raise ResultValidationError("result fixed contract drift")

    folds = result.get("fold_outputs")
    evidence = _validate_terminal_evidence(
        result,
        registration,
        readiness=readiness,
        readiness_sha256=readiness_sha,
        registration_sha256=registration_sha,
        git_base_commit=git_base_commit,
    )
    if git_base_commit is not None:
        _validate_execution_result_git_topology(evidence, registration)
    _validate_fold_schema(
        folds, quality_starts_sha256=str(result["quality_starts_sha256"])
    )
    governor_passed = _validate_governor_receipt(
        result.get("current_role_shape_governor"),
        reservation_id=str(reservation_id),
        registration_governor=registration["governor"],
    )
    recomputed = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=EXPECTED_COHORTS,
        declared_omissions={2020},
        current_role_shape_governor_passed=governor_passed,
        bootstrap_seed=BOOTSTRAP_SEED,
        bootstrap_resamples=DEFAULT_BOOTSTRAP_RESAMPLES,
    )
    if _canonical(result.get("evaluation")) != _canonical(recomputed):
        raise ResultValidationError("stored evaluation does not match deterministic replay")
    authorized = recomputed.get("production_review_authorized") is True
    expected_status = "passed" if authorized else "failed"
    if (
        status != expected_status
        or result.get("production_review_authorized") is not authorized
        or result.get("decision") != recomputed.get("decision")
    ):
        raise ResultValidationError("result status/decision does not match evaluation")
    return {
        "valid": True,
        "status": status,
        "production_review_authorized": authorized,
        "claim_authorized": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--registration", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = validate_result_files(
            result_path=args.result,
            readiness_path=args.readiness,
            registration_path=args.registration,
        )
    except ResultValidationError as exc:
        print(f"Plan 036 result invalid: {exc}", file=sys.stderr, flush=True)
        return 1
    print(
        "Plan 036 result valid: "
        f"status={report['status']} "
        f"production_review_authorized={report['production_review_authorized']} "
        "claim_authorized=false",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
