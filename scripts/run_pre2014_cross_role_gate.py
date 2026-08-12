#!/usr/bin/env python3
"""Execute the immutable Plan 036 cross-role adjudication exactly once.

The orchestration is deliberately callback-driven.  It validates every
pre-look file hash and atomically reserves the permanent result before an
outcome, quality-start, or current-board callback can run.  The default fold
scorer is the production Rank-v1 pseudo-replay path; tests may inject a scorer
without accessing the sealed data.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import copy
import hashlib
import http.client
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zlib
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path, PurePosixPath
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.direct_7x7 import (  # noqa: E402
    DirectValueError,
    join_quality_starts,
    top_k_regret,
)
from prospects.extended_history import (  # noqa: E402
    build_labeled_rows,
    canonicalize_mlb_seasons,
    parse_innings,
)
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
    evaluate_pre2014_cross_role_gate,
    finalize_reserved_result,
    reserve_result_path,
    sealed_result_run_lease,
)
from quality.valucast_governor import (  # noqa: E402
    MAX_TOP25_PROSPECT_PITCHER_COUNT,
    MAX_TOP50_PROSPECT_PITCHER_RATE,
)
from prospects.pre2014_fold_scoring import (  # noqa: E402
    CANDIDATE_MODEL_FLAGS,
    INCUMBENT_MODEL_FLAGS,
    score_outer_fold,
)
from prospects.pre2014_readiness import (  # noqa: E402
    EXPECTED_COHORTS,
    REGISTERED_IMPLEMENTATION_PATHS,
    REGISTERED_OUTER_FOLDS,
    REGISTERED_PREPARED_SOURCE_PATHS,
    REGISTERED_SOURCE_PATHS,
    replay_pre2014_source_contract,
)


PROTOCOL = "plan_036_pre2014_cross_role_calibration"
CANDIDATE_SCORE_MODE = "common_target"
INCUMBENT_SCORE_MODE = "incumbent_role_quantile"
OUTCOME_HORIZON_YEARS = 4
MATURE_COHORT_THROUGH = 2021
TOP_K = 25
REGISTRATION_START = "<!-- plan036-registration:start -->"
REGISTRATION_END = "<!-- plan036-registration:end -->"
PLAN_REGISTRATION_PATH = ROOT / "plans" / "036-pre2014-cross-role-calibration-gate.md"
REGISTERED_READINESS_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_readiness.json"
)
REGISTERED_RESULT_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_gate.json"
)
REGISTERED_EVIDENCE_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_evidence.json"
)
ACQUISITION_CHECKPOINT_PATH = (
    ROOT
    / "data"
    / "research"
    / "extended_prospect_history"
    / "sealed-acquisition-checkpoint.json"
)
REGISTERED_CUTOFF_DATE = "2025-12-31"
QUALITY_STARTS_SOURCE = {
    "provider": "MLB StatsAPI",
    "stat": "gameLog",
    "group": "pitching",
    "game_type": "R",
    "definition": "GS > 0 and IP >= 6.0 and ER <= 3",
}
QUALITY_STARTS_INPUT_KIND = "embedded_json"
QUALITY_STARTS_INPUT_POINTER = "/quality_starts/input_contract"
REGISTRATION_COMMIT_PATHS = frozenset(
    {
        "plans/036-pre2014-cross-role-calibration-gate.md",
        "plans/README.md",
        "data/validation/valucast_pre2014_cross_role_readiness.json",
        "tests/test_pre2014_cross_role_registration.py",
    }
)
ACQUISITION_CHECKPOINT_BATCH_SIZE = 200
ACQUISITION_MAX_ATTEMPTS = 3
STRICT_OUTCOME_FETCH_MODE = "strict_mlb_statsapi_every_registered_mature_identity"
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
    "check_id": "prospect_top_board_role_shape",
    "max_top25_pitcher_count": MAX_TOP25_PROSPECT_PITCHER_COUNT,
    "max_top50_pitcher_rate": MAX_TOP50_PROSPECT_PITCHER_RATE,
}
EXECUTION_SOURCE_KEYS = (
    "prepared_artifact",
    "prepared_manifest",
    "draft_facts",
)

OutcomeAcquirer = Callable[..., Mapping[str, Any]]
QualityStartsBuilder = Callable[[Mapping[str, Any], str], Mapping[str, Any]]
GovernorEvaluator = Callable[..., Mapping[str, Any]]
FoldScorer = Callable[[Mapping[str, Any], int], Mapping[str, Any]]


class ResumableAcquisitionIncomplete(RuntimeError):
    """A transport/provider gap that may resume under the same reservation."""

    def __init__(
        self,
        message: str,
        *,
        checkpoint: Mapping[str, str],
        remaining_count: int,
    ) -> None:
        super().__init__(message)
        self.checkpoint = dict(checkpoint)
        self.remaining_count = int(remaining_count)


def _git_text(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_bytes(*args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_repo_relative_path(path: Path | str, *, label: str) -> str:
    """Return the portable path spelling used inside permanent contracts."""
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        relative = candidate.resolve().relative_to(ROOT.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} must be inside the repository root") from exc
    value = relative.as_posix()
    pure = PurePosixPath(value)
    if (
        not value
        or value == "."
        or pure.is_absolute()
        or str(pure) != value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or ":" in value
        or "\\" in value
    ):
        raise ValueError(f"{label} is not a canonical repo-relative POSIX path")
    return value


def _resolve_repo_relative_path(value: Any, *, label: str) -> Path:
    """Validate a serialized contract path and resolve it below ``ROOT``."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is not a canonical repo-relative POSIX path")
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or str(pure) != value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or ":" in value
        or "\\" in value
    ):
        raise ValueError(f"{label} is not a canonical repo-relative POSIX path")
    return ROOT.joinpath(*pure.parts)


RAW_RECEIPT_ENCODING = "zlib+base64"


def _compressed_raw_receipt_fields(raw: bytes) -> dict[str, Any]:
    """Encode provider bytes compactly without weakening replayability."""
    compressed = zlib.compress(raw, level=9)
    return {
        "raw_encoding": RAW_RECEIPT_ENCODING,
        "raw_sha256": _sha256_bytes(raw),
        "raw_byte_count": len(raw),
        "compressed_sha256": _sha256_bytes(compressed),
        "compressed_byte_count": len(compressed),
        "compressed_body_base64": base64.b64encode(compressed).decode("ascii"),
    }


def _raw_bytes_from_compressed_receipt(
    attempt: Mapping[str, Any], *, label: str
) -> bytes:
    """Verify both envelopes and recover the exact provider response bytes."""
    if attempt.get("raw_encoding") != RAW_RECEIPT_ENCODING:
        raise ValueError(f"{label} encoding is malformed")
    try:
        compressed = base64.b64decode(
            str(attempt["compressed_body_base64"]), validate=True
        )
    except (binascii.Error, KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"{label} compressed body is malformed") from exc
    if (
        attempt.get("compressed_byte_count") != len(compressed)
        or attempt.get("compressed_sha256") != _sha256_bytes(compressed)
    ):
        raise ValueError(f"{label} compressed body hash drift")
    try:
        raw = zlib.decompress(compressed)
    except zlib.error as exc:
        raise ValueError(f"{label} compressed body is malformed") from exc
    if zlib.compress(raw, level=9) != compressed:
        raise ValueError(f"{label} compression is not deterministic")
    if (
        attempt.get("raw_byte_count") != len(raw)
        or attempt.get("raw_sha256") != _sha256_bytes(raw)
    ):
        raise ValueError(f"{label} raw body hash drift")
    return raw


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    reservation_id = (
        str(payload.get("reservation_id") or "")
        if isinstance(payload, Mapping)
        else ""
    )
    token = (
        reservation_id
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", reservation_id)
        else None
    )
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.{token}." if token else f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _cleanup_bound_runtime_json_temps(
    reservation_id: str,
    *,
    runtime_paths: Sequence[Path | str] | None = None,
) -> None:
    """Remove only JSON temp files owned by this exact reservation."""
    token = str(reservation_id)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", token) is None:
        raise ValueError("invalid reservation id")
    targets = (
        tuple(Path(path) for path in runtime_paths)
        if runtime_paths is not None
        else (
            REGISTERED_RESULT_PATH,
            REGISTERED_EVIDENCE_PATH,
            ACQUISITION_CHECKPOINT_PATH,
        )
    )
    for target in targets:
        prefix = f".{target.name}.{token}."
        if not target.parent.exists():
            continue
        for candidate in target.parent.glob(f"{prefix}*.tmp"):
            name = candidate.name
            middle = name[len(prefix) : -len(".tmp")]
            if (
                candidate.parent == target.parent
                and name.startswith(prefix)
                and name.endswith(".tmp")
                and middle
            ):
                candidate.unlink(missing_ok=True)


def _write_evidence(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    _atomic_json(path, payload)
    return {
        "path": _canonical_repo_relative_path(path, label="terminal evidence"),
        "sha256": _sha256_file(path),
    }


def _load_mapping_bytes(content: bytes, *, path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return dict(payload)


def _load_mapping(path: Path) -> dict[str, Any]:
    return _load_mapping_bytes(path.read_bytes(), path=path)


def _same_path(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def _declared_repo_path(value: Any) -> str | None:
    try:
        _resolve_repo_relative_path(value, label="registered path")
    except ValueError:
        return None
    return str(value)


def _validate_hash_record(
    record: Any,
    *,
    label: str,
    expected_repo_path: str,
    git_base_commit: str | None = None,
    verify_content: bool = True,
    git_blob_only: bool = False,
) -> Path:
    expected_keys = (
        {"path", "git_blob", "binding"}
        if git_blob_only
        else {"path", "sha256", "git_blob"}
    )
    if not isinstance(record, Mapping) or set(record) != expected_keys:
        raise ValueError(f"registered hash record is missing: {label}")
    raw_path = record.get("path")
    expected = record.get("sha256")
    git_blob = record.get("git_blob")
    if _declared_repo_path(raw_path) != expected_repo_path:
        raise ValueError(f"registered hash path is invalid: {label}")
    if git_blob_only and record.get("binding") != "git_blob_only_pre_reservation":
        raise ValueError(f"registered deferred binding is invalid: {label}")
    if not git_blob_only and (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise ValueError(f"registered hash is invalid: {label}")
    if (
        not isinstance(git_blob, str)
        or len(git_blob) != 40
        or any(character not in "0123456789abcdef" for character in git_blob)
    ):
        raise ValueError(f"registered git blob is invalid: {label}")
    path = Path(raw_path)
    if not path.is_absolute():
        path = ROOT / path
    try:
        if not verify_content:
            if git_base_commit is None:
                return path
            registered_blob = _git_text(
                "rev-parse", f"{git_base_commit}:{expected_repo_path}"
            )
            if registered_blob != git_blob:
                raise ValueError(f"registered git blob mismatch: {label}")
            return path
        if git_base_commit is None:
            content = path.read_bytes()
        else:
            registered_blob = _git_text(
                "rev-parse", f"{git_base_commit}:{expected_repo_path}"
            )
            if registered_blob != git_blob:
                raise ValueError(f"registered git blob mismatch: {label}")
            content = _git_bytes(
                "cat-file", "blob", f"{git_base_commit}:{expected_repo_path}"
            )
        actual = _sha256_bytes(content)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"registered hash file is unreadable: {label}") from exc
    if actual != expected:
        raise ValueError(
            f"registered hash mismatch: {label}: expected={expected} actual={actual}"
        )
    return path


def validate_registered_readiness(
    readiness_path: Path | str,
    registered_readiness_sha256: str,
    result_path: Path | str,
    *,
    git_base_commit: str | None = None,
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Validate the exact pre-look receipt and every file it hash-binds."""
    readiness_path = Path(readiness_path)
    result_path = Path(result_path)
    if readiness_path.is_symlink():
        raise ValueError("registered readiness must not be a symbolic link")
    if not readiness_path.is_file():
        raise ValueError("registered readiness must be a regular file")
    content = readiness_path.read_bytes()
    actual_readiness_sha256 = _sha256_bytes(content)
    if actual_readiness_sha256 != registered_readiness_sha256:
        raise ValueError(
            "registered readiness hash mismatch: "
            f"expected={registered_readiness_sha256} actual={actual_readiness_sha256}"
        )
    readiness = _load_mapping_bytes(content, path=readiness_path)
    if (
        readiness.get("artifact") != "valucast_pre2014_cross_role_readiness"
        or readiness.get("status") != "ready"
        or readiness.get("execution_authorized") is not True
        or readiness.get("blockers") != []
        or readiness.get("look_spent") is not False
    ):
        raise ValueError("registered readiness is not authorized")
    implementation_base_commit = readiness.get("implementation_base_commit")
    if (
        not isinstance(implementation_base_commit, str)
        or len(implementation_base_commit) != 40
        or any(
            character not in "0123456789abcdef"
            for character in implementation_base_commit
        )
    ):
        raise ValueError("registered implementation base commit is invalid")
    if (
        git_base_commit is not None
        and implementation_base_commit != git_base_commit
    ):
        raise ValueError("registered implementation base commit does not match")
    policy = readiness.get("source_policy")
    if not isinstance(policy, Mapping) or (
        policy.get("phase") != "pre_look"
        or policy.get("reads_outcomes") is not False
        or policy.get("reads_mlb_seasons") is not False
        or policy.get("research_only") is not True
    ):
        raise ValueError("registered readiness is not outcome blind")
    result = readiness.get("result")
    if not isinstance(result, Mapping) or (
        not _same_path(
            _resolve_repo_relative_path(
                result.get("path"), label="registered readiness result"
            ),
            result_path,
        )
        or result.get("exists") is not False
        or result.get("unspent") is not True
    ):
        raise ValueError("registered readiness result path does not match")
    fold_audit = readiness.get("outer_fold_audit")
    if not isinstance(fold_audit, Mapping) or fold_audit.get(
        "registered_folds"
    ) != list(REGISTERED_OUTER_FOLDS):
        raise ValueError("registered outer folds do not match Plan 036")
    candidate_audit = readiness.get("candidate_audit")
    if not isinstance(candidate_audit, Mapping) or candidate_audit.get(
        "cohorts"
    ) != list(EXPECTED_COHORTS):
        raise ValueError("registered cohort set does not match Plan 036")

    hashes = readiness.get("hashes")
    if not isinstance(hashes, Mapping) or set(hashes) != {
        "source_files",
        "prepared_manifest_sources",
        "prepared_source_files",
        "implementation_files",
    }:
        raise ValueError("registered hashes are missing")
    source_records = hashes.get("source_files")
    if not isinstance(source_records, Mapping) or set(source_records) != set(
        REGISTERED_SOURCE_PATHS
    ):
        raise ValueError("registered source hashes are incomplete or unexpected")
    deferred = {"current_prospect_contract"}
    paths = {
        key: _validate_hash_record(
            source_records[key],
            label=f"source:{key}",
            expected_repo_path=REGISTERED_SOURCE_PATHS[key],
            git_base_commit=git_base_commit,
            verify_content=key not in deferred,
            git_blob_only=key in deferred,
        )
        for key in REGISTERED_SOURCE_PATHS
    }
    prepared_source_records = hashes.get("prepared_source_files")
    if (
        not isinstance(prepared_source_records, Sequence)
        or isinstance(prepared_source_records, (str, bytes))
        or len(prepared_source_records) != len(REGISTERED_PREPARED_SOURCE_PATHS)
    ):
        raise ValueError("registered prepared-source hashes are missing")
    prepared_paths: list[Path] = []
    for index, (record, expected_repo_path) in enumerate(
        zip(
            prepared_source_records,
            REGISTERED_PREPARED_SOURCE_PATHS,
            strict=True,
        )
    ):
        prepared_paths.append(
            _validate_hash_record(
                record,
                label=f"prepared-source:{index}",
                expected_repo_path=expected_repo_path,
                git_base_commit=git_base_commit,
            )
        )
    manifest_sources = hashes.get("prepared_manifest_sources")
    if (
        not isinstance(manifest_sources, Sequence)
        or isinstance(manifest_sources, (str, bytes))
        or len(manifest_sources) != len(REGISTERED_PREPARED_SOURCE_PATHS)
    ):
        raise ValueError("registered prepared-manifest hashes are missing")
    for index, (source, record, expected_repo_path) in enumerate(
        zip(
            manifest_sources,
            prepared_source_records,
            REGISTERED_PREPARED_SOURCE_PATHS,
            strict=True,
        )
    ):
        if (
            not isinstance(source, Mapping)
            or set(source) != {"kind", "path", "sha256"}
            or source.get("kind") != "registered_prepared_source"
            or _declared_repo_path(source.get("path")) != expected_repo_path
            or source.get("sha256") != record.get("sha256")
        ):
            raise ValueError(
                f"registered prepared-manifest source drift: {index}"
            )

    def frozen_bytes(repo_path: str) -> bytes:
        if git_base_commit is not None:
            return _git_bytes("cat-file", "blob", f"{git_base_commit}:{repo_path}")
        try:
            index = list(REGISTERED_PREPARED_SOURCE_PATHS).index(repo_path)
        except ValueError as exc:
            raise ValueError(f"unregistered source replay path: {repo_path}") from exc
        return prepared_paths[index].read_bytes()

    def source_payload(key: str) -> dict[str, Any]:
        content = (
            _git_bytes(
                "cat-file", "blob", f"{git_base_commit}:{REGISTERED_SOURCE_PATHS[key]}"
            )
            if git_base_commit is not None
            else paths[key].read_bytes()
        )
        return _load_mapping_bytes(content, path=paths[key])

    recomputed_replay = replay_pre2014_source_contract(
        source_payload("prepared_artifact"),
        source_payload("prepared_manifest"),
        source_payload("draft_facts"),
        load_bytes=frozen_bytes,
    )
    source_replay = readiness.get("source_replay")
    if (
        not isinstance(source_replay, Mapping)
        or set(source_replay)
        != {
            "artifact",
            "schema_version",
            "inputs",
            "replay_counts",
            "prepared_output",
            "draft_facts_output",
        }
        or dict(source_replay) != recomputed_replay
        or list(manifest_sources)
        != [
            {
                "kind": "registered_prepared_source",
                "path": record["path"],
                "sha256": record["sha256"],
            }
            for record in recomputed_replay["inputs"]
        ]
    ):
        raise ValueError("registered source replay receipt drift")
    implementation_records = hashes.get("implementation_files")
    if (
        not isinstance(implementation_records, Sequence)
        or isinstance(implementation_records, (str, bytes))
        or len(implementation_records) != len(REGISTERED_IMPLEMENTATION_PATHS)
    ):
        raise ValueError("registered implementation hashes are missing")
    for index, (record, expected_repo_path) in enumerate(
        zip(implementation_records, REGISTERED_IMPLEMENTATION_PATHS, strict=True)
    ):
        _validate_hash_record(
            record,
            label=f"implementation:{index}",
            expected_repo_path=expected_repo_path,
            git_base_commit=git_base_commit,
        )
        if git_base_commit is not None:
            _validate_git_bound_worktree_file(
                commit=git_base_commit,
                repo_path=expected_repo_path,
                expected_blob=str(record["git_blob"]),
                label=f"implementation:{index}",
            )
    return readiness, {key: paths[key] for key in EXECUTION_SOURCE_KEYS}


def _contains_outcome_label(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            str(key).lower() in {"outcome", "outcome_label"}
            or _contains_outcome_label(nested)
            for key, nested in value.items()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_outcome_label(item) for item in value)
    return False


def _prepared_rows(prepared: Mapping[str, Any]) -> list[dict[str, Any]]:
    if (
        prepared.get("artifact")
        != "valucast_extended_prospect_history_prepared"
        or prepared.get("mode") != "prepare_only"
    ):
        raise ValueError("registered prepared artifact is invalid")
    policy = prepared.get("source_policy")
    if not isinstance(policy, Mapping) or (
        policy.get("outcomes_read") is not False
        or policy.get("labels_scored") is not False
    ):
        raise ValueError("registered prepared artifact is not outcome blind")
    rows = prepared.get("rows")
    if not isinstance(rows, list) or not rows or any(
        not isinstance(row, Mapping) for row in rows
    ):
        raise ValueError("registered prepared rows are invalid")
    if _contains_outcome_label(rows):
        raise ValueError("registered prepared rows contain outcome labels")
    normalized = [dict(row) for row in rows]
    identities: set[tuple[str, str]] = set()
    for row in normalized:
        role = str(row.get("role") or "")
        mlbam_id = row.get("mlbam_id")
        if role not in {"hitter", "pitcher"} or mlbam_id in (None, ""):
            raise ValueError("registered prepared row identity is invalid")
        identity = (str(mlbam_id), role)
        if identity in identities:
            raise ValueError(f"duplicate prepared identity: {identity}")
        identities.add(identity)
    return normalized


def _draft_facts(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("draft_facts")
    return nested if isinstance(nested, Mapping) else payload


def _strict_number(value: Any, *, field: str) -> float | None:
    if str(value).strip() in {"-.--", ".---"}:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"StatsAPI {field} is malformed") from exc
    if not math.isfinite(number):
        raise ValueError(f"StatsAPI {field} is malformed")
    return number


def parse_strict_statsapi_seasons(
    payload: Any, role: str, *, mlbam_id: int
) -> list[dict]:
    """Parse a complete StatsAPI response without zero-filling missing fields."""
    if role not in {"hitter", "pitcher"}:
        raise ValueError("StatsAPI role must be hitter or pitcher")
    if not isinstance(payload, Mapping):
        raise ValueError("StatsAPI payload is not an object")
    groups = payload.get("stats")
    if not isinstance(groups, list):
        raise ValueError("StatsAPI stats are missing or malformed")
    # StatsAPI uses this exact typed response for a real person who has never
    # appeared in MLB.  It is factual zero-season evidence, not a transport or
    # schema failure and therefore must remain distinguishable from ``None``.
    if not groups:
        allowed_keys = {"stats"}, {"copyright", "stats"}
        if set(payload) in allowed_keys and (
            "copyright" not in payload or isinstance(payload["copyright"], str)
        ):
            return []
        raise ValueError("StatsAPI empty stats response is not canonical")
    if len(groups) != 1:
        raise ValueError("StatsAPI response must contain exactly one stats group")
    raw_splits = []
    typed_empty_groups = True
    expected_group = "hitting" if role == "hitter" else "pitching"
    for group in groups:
        if not isinstance(group, Mapping) or not isinstance(group.get("splits"), list):
            raise ValueError("StatsAPI splits are missing or malformed")
        group_type = group.get("type")
        stat_group = group.get("group")
        typed_group = (
            isinstance(group_type, Mapping)
            and group_type.get("displayName") == "yearByYear"
            and isinstance(stat_group, Mapping)
            and stat_group.get("displayName") == expected_group
        )
        if not typed_group:
            raise ValueError("StatsAPI stats type/group does not match request")
        typed_empty_groups = typed_empty_groups and typed_group
        raw_splits.extend(group["splits"])
    if not raw_splits:
        if typed_empty_groups:
            return []
        raise ValueError("StatsAPI splits are empty and outcome is unresolved")

    if role == "hitter":
        fields = {
            "plateAppearances": "pa",
            "atBats": "ab",
            "runs": "r",
            "homeRuns": "hr",
            "rbi": "rbi",
            "stolenBases": "sb",
            "avg": "avg",
            "ops": "ops",
            "strikeOuts": "so",
            "baseOnBalls": "bb",
        }
    else:
        fields = {
            "era": "era",
            "whip": "whip",
            "strikeOuts": "so",
            "baseOnBalls": "bb",
            "saves": "sv",
            "holds": "hld",
            "losses": "l",
            "strikeoutWalkRatio": "k_bb",
            "gamesStarted": "gs",
        }
    seasons = []
    for split in raw_splits:
        if not isinstance(split, Mapping):
            raise ValueError("StatsAPI split is malformed")
        sport = split.get("sport")
        player = split.get("player")
        if (
            not isinstance(sport, Mapping)
            or str(sport.get("id")) != "1"
            or not isinstance(player, Mapping)
            or str(player.get("id")) != str(int(mlbam_id))
            or split.get("gameType") != "R"
        ):
            raise ValueError("StatsAPI split identity/context does not match request")
        try:
            year = int(split["season"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("StatsAPI split season is malformed") from exc
        stat = split.get("stat")
        if not isinstance(stat, Mapping):
            raise ValueError("StatsAPI split stat is missing or malformed")
        required_label_fields = (
            {"plateAppearances", "ops"}
            if role == "hitter"
            else {"inningsPitched", "era"}
        )
        if not required_label_fields.issubset(stat):
            raise ValueError("StatsAPI split is missing label-critical fields")
        row: dict[str, Any] = {"year": year}
        if role == "pitcher" and "inningsPitched" in stat:
            try:
                row["ip"] = parse_innings(stat["inningsPitched"])
            except (TypeError, ValueError) as exc:
                raise ValueError("StatsAPI inningsPitched is malformed") from exc
        for source, target in fields.items():
            if source in stat:
                row[target] = _strict_number(stat[source], field=source)
        seasons.append(row)
    if not seasons:
        raise ValueError("StatsAPI response has no MLB splits and outcome is unresolved")
    return seasons


def fetch_strict_statsapi_seasons(
    mlbam_id: int,
    role: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> list[dict] | None:
    """Fetch one identity; transport or response ambiguity stays unresolved."""
    group = "hitting" if role == "hitter" else "pitching"
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{int(mlbam_id)}/stats"
        f"?stats=yearByYear&group={group}&gameType=R"
    )
    try:
        with opener(url, timeout=20) as response:
            payload = json.load(response)
        return parse_strict_statsapi_seasons(payload, role, mlbam_id=mlbam_id)
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _fetch_strict_statsapi_with_receipt(
    mlbam_id: int,
    role: str,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[list[dict] | None, dict[str, Any]]:
    group = "hitting" if role == "hitter" else "pitching"
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{int(mlbam_id)}/stats"
        f"?stats=yearByYear&group={group}&gameType=R"
    )
    receipt: dict[str, Any] = {
        "mlbam_id": int(mlbam_id),
        "role": role,
        "provider": "MLB StatsAPI",
        "endpoint": "yearByYear",
    }
    try:
        with opener(url, timeout=20) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200))
        receipt.update(
            {
                "http_status": status,
                **_compressed_raw_receipt_fields(raw),
            }
        )
        if status != 200:
            receipt["status"] = "unresolved_http_status"
            return None, receipt
        try:
            payload = json.loads(raw.decode("utf-8"))
            seasons = parse_strict_statsapi_seasons(
                payload, role, mlbam_id=mlbam_id
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            receipt.update(
                {"status": "invalid_response", "error_type": type(exc).__name__}
            )
            return None, receipt
        receipt.update({"status": "resolved", "season_count": len(seasons)})
        return seasons, receipt
    except (OSError, http.client.HTTPException) as exc:
        receipt.update(
            {"status": "unresolved_transport", "error_type": type(exc).__name__}
        )
        return None, receipt


def _resolved_seasons_from_provider_receipt(
    receipt: Any,
    *,
    identity: str,
) -> list[dict]:
    """Reparse one resolved identity exclusively from its immutable raw bytes."""
    if not isinstance(receipt, Mapping) or set(receipt) != {
        "identity",
        "mlbam_id",
        "role",
        "status",
        "attempt_count",
        "attempts",
        "season_count",
    }:
        raise ValueError(f"provider receipt is malformed: {identity}")
    role = str(receipt.get("role") or "")
    expected_identity = f"{receipt.get('mlbam_id')}_{role}"
    attempts = receipt.get("attempts")
    if (
        receipt.get("identity") != identity
        or expected_identity != identity
        or role not in {"hitter", "pitcher"}
        or receipt.get("status") != "resolved"
        or not isinstance(attempts, list)
        or not attempts
        or receipt.get("attempt_count") != len(attempts)
    ):
        raise ValueError(f"provider receipt binding is malformed: {identity}")
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise ValueError(f"provider attempt is malformed: {identity}")
        status = attempt.get("status")
        common = {"mlbam_id", "role", "provider", "endpoint", "status"}
        if status == "unresolved_transport":
            expected_keys = common | {"error_type"}
        elif status in {"unresolved_http_status", "resolved", "invalid_response"}:
            expected_keys = common | {
                "http_status",
                "raw_encoding",
                "raw_sha256",
                "raw_byte_count",
                "compressed_sha256",
                "compressed_byte_count",
                "compressed_body_base64",
            }
            if status == "resolved":
                expected_keys.add("season_count")
            elif status == "invalid_response":
                expected_keys.add("error_type")
        else:
            raise ValueError(f"provider attempt status is malformed: {identity}")
        if set(attempt) != expected_keys or (
            attempt.get("mlbam_id") != receipt["mlbam_id"]
            or attempt.get("role") != role
            or attempt.get("provider") != "MLB StatsAPI"
            or attempt.get("endpoint") != "yearByYear"
        ):
            raise ValueError(f"provider attempt binding is malformed: {identity}")
        if status != "unresolved_transport":
            _raw_bytes_from_compressed_receipt(
                attempt, label=f"provider attempt body: {identity}"
            )
    final = attempts[-1]
    if final.get("status") != "resolved" or final.get("http_status") != 200:
        raise ValueError(f"provider receipt has no terminal success: {identity}")
    raw = _raw_bytes_from_compressed_receipt(
        final, label=f"provider terminal body: {identity}"
    )
    try:
        payload = json.loads(raw.decode("utf-8"))
        seasons = parse_strict_statsapi_seasons(
            payload, role, mlbam_id=int(receipt["mlbam_id"])
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"provider receipt cannot be reparsed: {identity}") from exc
    if (
        final.get("season_count") != len(seasons)
        or receipt.get("season_count") != len(seasons)
    ):
        raise ValueError(f"provider receipt season count drift: {identity}")
    return seasons


def _outcomes(
    payload: Any, cohort_year_by_identity: Mapping[str, int]
) -> dict[str, list[dict]]:
    if not isinstance(payload, Mapping):
        raise ValueError("outcome acquisition did not return a mapping")
    for wrapper in ("cache", "mlb_seasons", "historical_mlb_seasons", "outcomes"):
        nested = payload.get(wrapper)
        if isinstance(nested, Mapping):
            payload = nested
            break
    normalized: dict[str, list[dict]] = {}
    for key, seasons in payload.items():
        if not isinstance(seasons, list) or any(
            not isinstance(season, Mapping) for season in seasons
        ):
            raise ValueError(f"invalid acquired outcome seasons: {key}")
        identity = str(key)
        if identity.endswith("_hitter"):
            role = "hitter"
        elif identity.endswith("_pitcher"):
            role = "pitcher"
        else:
            raise ValueError(f"invalid acquired outcome identity: {identity}")
        if identity not in cohort_year_by_identity:
            raise ValueError(f"unregistered acquired outcome identity: {identity}")
        cohort_year = int(cohort_year_by_identity[identity])
        horizon_end = min(
            cohort_year + OUTCOME_HORIZON_YEARS, OUTCOME_COMPLETE_THROUGH
        )
        clipped = []
        for season in seasons:
            try:
                year = int(season["year"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid acquired outcome season: {identity}") from exc
            if cohort_year < year <= horizon_end:
                clipped.append(dict(season))
        normalized[identity] = canonicalize_mlb_seasons(clipped, role)
    return normalized


def _quality_starts_content_sha256(sidecar: Mapping[str, Any]) -> str:
    body = {key: value for key, value in sidecar.items() if key != "content_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _quality_starts_input_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(dict(contract))
    current = payload.get("current")
    payload["current"] = {
        **(dict(current) if isinstance(current, Mapping) else {}),
        "fetched_date": REGISTERED_CUTOFF_DATE,
    }
    return payload


def _canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _quality_starts_input_descriptor(
    input_sha256: str, *, document_path: Path | str
) -> dict[str, Any]:
    return {
        "kind": QUALITY_STARTS_INPUT_KIND,
        "document_path": _canonical_repo_relative_path(
            document_path, label="quality-start input document"
        ),
        "json_pointer": QUALITY_STARTS_INPUT_POINTER,
        "sha256": input_sha256,
        "cutoff_date": REGISTERED_CUTOFF_DATE,
    }


def _validate_quality_starts(
    seasons: Mapping[str, list[dict]],
    sidecar: Any,
    *,
    reservation_id: str,
    expected_input_sha256: str,
    expected_input_path: Path | None,
) -> tuple[dict[str, Any], dict[str, list[dict]]]:
    if not isinstance(sidecar, Mapping):
        raise ValueError("quality-start sidecar builder returned a non-object")
    normalized = dict(sidecar)
    expected_hash = normalized.get("content_sha256")
    actual_hash = _quality_starts_content_sha256(normalized)
    source = normalized.get("source")
    input_record = normalized.get("input")
    coverage = normalized.get("coverage")
    input_document_path = None
    if isinstance(input_record, Mapping):
        try:
            input_document_path = _resolve_repo_relative_path(
                input_record.get("document_path"),
                label="quality-start input document",
            )
        except ValueError:
            pass
    if (
        set(normalized)
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
        or
        normalized.get("schema") != "valucast_stage2_quality_starts"
        or normalized.get("version") != "1.0.0"
        or normalized.get("status") != "ready"
        or normalized.get("blockers") != []
        or normalized.get("reservation_id") != reservation_id
        or source != QUALITY_STARTS_SOURCE
        or not isinstance(input_record, Mapping)
        or set(input_record)
        != {
            "kind",
            "document_path",
            "json_pointer",
            "sha256",
            "cutoff_date",
        }
        or input_record.get("kind") != QUALITY_STARTS_INPUT_KIND
        or input_record.get("json_pointer") != QUALITY_STARTS_INPUT_POINTER
        or input_document_path is None
        or (
            expected_input_path is not None
            and input_record.get("document_path")
            != _canonical_repo_relative_path(
                expected_input_path, label="quality-start input document"
            )
        )
        or input_record.get("sha256") != expected_input_sha256
        or input_record.get("cutoff_date") != REGISTERED_CUTOFF_DATE
        or not isinstance(coverage, Mapping)
        or expected_hash != actual_hash
    ):
        raise ValueError("quality-start sidecar is not strict, ready, and hash-valid")
    expected_keys = set()
    for identity, season_rows in seasons.items():
        if not str(identity).endswith("_pitcher"):
            continue
        try:
            mlbam_id = int(str(identity).removesuffix("_pitcher"))
            expected_keys.update(
                (mlbam_id, int(season["year"])) for season in season_rows
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("quality-start sidecar source seasons are invalid") from exc
    actual_keys = []
    try:
        for row in normalized.get("rows") or []:
            actual_keys.append((int(row["mlbam_id"]), int(row["season"])))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("quality-start sidecar rows are invalid") from exc
    if len(actual_keys) != len(set(actual_keys)) or set(actual_keys) != expected_keys:
        raise ValueError(
            "quality-start sidecar coverage does not exactly match pitcher seasons"
        )
    expected_pitcher_rows = sum(
        len(season_rows)
        for identity, season_rows in seasons.items()
        if str(identity).endswith("_pitcher")
    )
    if coverage != {
        "source_rows": expected_pitcher_rows,
        "unique_player_seasons": len(expected_keys),
        "resolved_player_seasons": len(expected_keys),
        "post_join_rows_with_qs": expected_pitcher_rows,
    }:
        raise ValueError("quality-start sidecar coverage receipt is not exact")
    try:
        joined = join_quality_starts(seasons, normalized)
    except DirectValueError as exc:
        raise ValueError(f"quality-start sidecar validation failed: {exc}") from exc
    return normalized, joined


def _finite(value: Any, *, label: str, bounded: bool = False) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be finite") from exc
    if not math.isfinite(number) or (bounded and not 0.0 <= number <= 1.0):
        raise ValueError(f"{label} must be finite" + (" in [0,1]" if bounded else ""))
    return number


def _percentile_ranks(values: Sequence[float]) -> list[float]:
    """Return deterministic higher-is-better ranks where zero is best."""
    if len(values) < 2:
        return [0.0] * len(values)
    order = sorted(range(len(values)), key=lambda index: (-values[index], index))
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = ((start + end - 1) / 2) / (len(values) - 1)
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def _pair_credit(left_score: float, right_score: float, left_target: float,
                 right_target: float) -> float | None:
    if left_target == right_target:
        return None
    score_delta = left_score - right_score
    target_delta = left_target - right_target
    if score_delta == 0:
        return 0.5
    return 1.0 if score_delta * target_delta > 0 else 0.0


def _concordance(
    rows: Sequence[Mapping[str, Any]],
    prediction_field: str,
    *,
    target_field: str,
    cross_role: bool,
) -> float:
    credits = []
    for left_index, left in enumerate(rows):
        for right in rows[left_index + 1 :]:
            if cross_role and left["role"] == right["role"]:
                continue
            if not cross_role and left["role"] != right["role"]:
                continue
            credit = _pair_credit(
                float(left[prediction_field]),
                float(right[prediction_field]),
                float(left[target_field]),
                float(right[target_field]),
            )
            if credit is not None:
                credits.append(credit)
    if not credits:
        raise ValueError("concordance requires at least one comparable pair")
    return float(mean(credits))


def _regret(
    rows: Sequence[Mapping[str, Any]], prediction_field: str, target_field: str
) -> float:
    try:
        result = top_k_regret(
            rows,
            prediction_field=prediction_field,
            target_field=target_field,
            k=TOP_K,
        )
    except DirectValueError as exc:
        raise ValueError(str(exc)) from exc
    return float(result["regret"])


def _normalize_identity_map(value: Any, *, label: str) -> dict[tuple[str, str], Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"fold {label} must be an identity mapping")
    normalized = {}
    for raw_key, item in value.items():
        if (
            not isinstance(raw_key, tuple)
            or len(raw_key) != 2
            or str(raw_key[1]) not in {"hitter", "pitcher"}
        ):
            raise ValueError(f"fold {label} has an invalid identity key")
        key = (str(raw_key[0]), str(raw_key[1]))
        if key in normalized:
            raise ValueError(f"fold {label} has a duplicate identity")
        normalized[key] = item
    return normalized


def convert_fold_output(
    scored: Mapping[str, Any],
    *,
    cohort_year: int,
    eligible_identities: set[tuple[str, str]],
    quality_starts_sha256: str,
    mature_cohort_years: Sequence[int],
) -> dict[str, Any]:
    """Convert one production scorer receipt to the frozen gate schema."""
    if not isinstance(scored, Mapping):
        raise ValueError("fold scorer returned a non-object")
    metadata = scored.get("metadata")
    diagnostics = scored.get("diagnostics")
    if (
        not isinstance(metadata, Mapping)
        or set(metadata)
        != {
            "outer_year",
            "train_through",
            "inner_fold_years",
            "calibration_mature_through",
            "calibration_strategy",
            "identity_count",
            "outer_reference_sha256",
            "quality_starts_sha256",
            "candidate_model_flags",
            "incumbent_model_flags",
        }
        or metadata.get("outer_year") != cohort_year
    ):
        raise ValueError("fold scorer returned the wrong outer year")
    if metadata.get("candidate_model_flags") != CANDIDATE_MODEL_FLAGS:
        raise ValueError("fold scorer substituted candidate model flags")
    if metadata.get("incumbent_model_flags") != INCUMBENT_MODEL_FLAGS:
        raise ValueError("fold scorer substituted incumbent model flags")
    if metadata.get("quality_starts_sha256") != quality_starts_sha256:
        raise ValueError("fold scorer did not use the registered quality-start sidecar")
    expected_inner_years = sorted(
        {
            int(year)
            for year in mature_cohort_years
            if int(year) <= cohort_year - OUTCOME_HORIZON_YEARS
        }
    )
    outer_reference_sha256 = metadata.get("outer_reference_sha256")
    if (
        metadata.get("identity_count") != len(eligible_identities)
        or metadata.get("train_through")
        != cohort_year - OUTCOME_HORIZON_YEARS
        or metadata.get("calibration_mature_through")
        != cohort_year - OUTCOME_HORIZON_YEARS
        or metadata.get("calibration_strategy")
        != "leave_one_cohort_out_within_outer_mature_pool"
        or metadata.get("inner_fold_years") != expected_inner_years
        or not isinstance(outer_reference_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", outer_reference_sha256) is None
    ):
        raise ValueError("fold scorer calibration provenance drift")
    if not isinstance(diagnostics, Mapping) or diagnostics.get(
        "identity_sets_equal"
    ) is not True:
        raise ValueError("fold scorer did not prove identical identity sets")
    inner_diagnostics = diagnostics.get("inner_folds")
    if (
        not isinstance(inner_diagnostics, list)
        or len(inner_diagnostics) != len(expected_inner_years)
    ):
        raise ValueError("fold scorer inner-fold provenance drift")
    stable_inner = []
    for expected_year, inner in zip(
        expected_inner_years, inner_diagnostics, strict=True
    ):
        remaining_years = [
            year for year in expected_inner_years if year != expected_year
        ]
        if not remaining_years:
            raise ValueError("fold scorer inner-fold training pool is empty")
        if (
            not isinstance(inner, Mapping)
            or set(inner)
            != {
                "test_year",
                "target_complete_by",
                "train_through",
                "training_strategy",
                "reference_sha256",
                "raw_scorer",
            }
            or inner.get("test_year") != expected_year
            or inner.get("target_complete_by")
            != expected_year + OUTCOME_HORIZON_YEARS
            or inner.get("target_complete_by") > cohort_year
            or inner.get("train_through") != max(remaining_years)
            or inner.get("training_strategy") != "leave_one_cohort_out"
            or not isinstance(inner.get("reference_sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", inner["reference_sha256"]) is None
        ):
            raise ValueError("fold scorer inner-fold provenance drift")
        stable_inner.append(
            {
                key: inner[key]
                for key in (
                    "test_year",
                    "target_complete_by",
                    "train_through",
                    "training_strategy",
                    "reference_sha256",
                )
            }
        )
    outer_diagnostics = diagnostics.get("outer")
    if not isinstance(outer_diagnostics, Mapping) or (
        (outer_diagnostics.get("incumbent_rank") or {}).get("model_score_mode")
        != INCUMBENT_SCORE_MODE
        or (outer_diagnostics.get("candidate_rank") or {}).get("model_score_mode")
        != CANDIDATE_SCORE_MODE
    ):
        raise ValueError("fold scorer substituted a registered rank mode")

    calibrator_hashes = scored.get("calibrator_hashes")
    expected_calibrators = {
        "hitter.outcome",
        "hitter.impact",
        "pitcher.outcome",
        "pitcher.impact",
    }
    if (
        not isinstance(calibrator_hashes, Mapping)
        or set(calibrator_hashes) != expected_calibrators
        or any(
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
            for value in calibrator_hashes.values()
        )
    ):
        raise ValueError("fold calibrator hashes are incomplete or invalid")

    scores = scored.get("scores")
    targets = scored.get("targets")
    if not isinstance(scores, Mapping):
        raise ValueError("fold scores are missing")
    incumbent = _normalize_identity_map(scores.get("incumbent"), label="incumbent")
    candidate = _normalize_identity_map(scores.get("candidate"), label="candidate")
    target_map = _normalize_identity_map(targets, label="targets")
    if (
        set(incumbent) != eligible_identities
        or set(candidate) != eligible_identities
        or set(target_map) != eligible_identities
    ):
        raise ValueError("fold identity coverage does not match the eligible cohort")

    analysis_rows = []
    for identity in sorted(eligible_identities, key=lambda key: (int(key[0]), key[1])):
        target = target_map[identity]
        if not isinstance(target, Mapping):
            raise ValueError("fold target row is invalid")
        analysis_rows.append(
            {
                "mlbam_id": int(identity[0]),
                "role": identity[1],
                "direct_7x7_target": _finite(
                    target.get("direct_7x7_target"),
                    label="direct target",
                    bounded=True,
                ),
                "outcome_tier": _finite(
                    target.get("outcome_tier"), label="outcome tier", bounded=True
                ),
                "incumbent_score": _finite(
                    incumbent[identity], label="incumbent score"
                ),
                "candidate_score": _finite(candidate[identity], label="candidate score"),
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
    players = []
    for index, row in enumerate(analysis_rows):
        players.append(
            {
                "player_id": str(row["mlbam_id"]),
                "role": row["role"],
                "target_percentile_rank": target_ranks[index],
                "incumbent_percentile_rank": incumbent_ranks[index],
                "candidate_percentile_rank": candidate_ranks[index],
                "outcome_tier": row["outcome_tier"],
                "direct_7x7_target": row["direct_7x7_target"],
                "incumbent_score": row["incumbent_score"],
                "candidate_score": row["candidate_score"],
            }
        )

    coverage = {}
    role_concordance = {}
    for role in ("hitter", "pitcher"):
        role_rows = [row for row in analysis_rows if row["role"] == role]
        count = len(role_rows)
        coverage[role] = {
            "eligible_identity_count": count,
            "scored_outcome_count": count,
            "rate": 1.0,
        }
        role_concordance[role] = {
            "incumbent": _concordance(
                role_rows,
                "incumbent_score",
                target_field="outcome_tier",
                cross_role=False,
            ),
            "candidate": _concordance(
                role_rows,
                "candidate_score",
                target_field="outcome_tier",
                cross_role=False,
            ),
        }
    direct_regret = {
        mode: _regret(analysis_rows, f"{mode}_score", "direct_7x7_target")
        for mode in ("incumbent", "candidate")
    }
    ordinal_regret = {
        mode: _regret(analysis_rows, f"{mode}_score", "outcome_tier")
        for mode in ("incumbent", "candidate")
    }
    return {
        "cohort_year": cohort_year,
        "metric": DIRECT_METRIC,
        "players": players,
        "coverage_by_role": coverage,
        "top25_direct_regret": direct_regret,
        "top25_ordinal_regret": ordinal_regret,
        "cross_role_concordance": {
            "incumbent": _concordance(
                analysis_rows,
                "incumbent_score",
                target_field="outcome_tier",
                cross_role=True,
            ),
            "candidate": _concordance(
                analysis_rows,
                "candidate_score",
                target_field="outcome_tier",
                cross_role=True,
            ),
        },
        "role_concordance": role_concordance,
        "receipt": {
            "calibrator_hashes": dict(calibrator_hashes),
            "quality_starts_sha256": quality_starts_sha256,
            "identity_count": len(analysis_rows),
            "scoring_provenance": {
                "calibration_strategy": metadata["calibration_strategy"],
                "calibration_mature_through": metadata[
                    "calibration_mature_through"
                ],
                "outer_train_through": metadata["train_through"],
                "inner_fold_years": expected_inner_years,
                "outer_reference_sha256": outer_reference_sha256,
                "inner_folds": stable_inner,
            },
        },
    }


def _validate_governor_receipt(
    receipt: Any, *, reservation_id: str
) -> dict[str, Any]:
    if not isinstance(receipt, Mapping):
        raise ValueError("current-board governor returned a non-object")
    normalized = dict(receipt)
    role_shape_check = normalized.get("role_shape_governor_check")
    role_shape_metrics = (
        role_shape_check.get("metrics")
        if isinstance(role_shape_check, Mapping)
        else None
    )
    declared_hash = normalized.get("receipt_sha256")
    hash_body = {
        key: value for key, value in normalized.items() if key != "receipt_sha256"
    }
    actual_hash = hashlib.sha256(
        json.dumps(
            hash_body, sort_keys=True, separators=(",", ":"), default=str
        ).encode("utf-8")
    ).hexdigest()
    if (
        not isinstance(normalized.get("passed"), bool)
        or normalized.get("unchanged_thresholds") is not True
        or normalized.get("candidate_model_flags") != CANDIDATE_MODEL_FLAGS
        or normalized.get("model_score_mode") != CANDIDATE_SCORE_MODE
        or normalized.get("reservation_id") != reservation_id
        or normalized.get("governor_scope") != "prospect_top_board_role_shape"
        or normalized.get("full_governor_required_at")
        != "post_look_pre_publication"
        or not isinstance(role_shape_check, Mapping)
        or role_shape_check.get("id") != "prospect_top_board_role_shape"
        or role_shape_check.get("status")
        != ("passed" if normalized.get("passed") else "failed")
        or not isinstance(role_shape_metrics, Mapping)
        or role_shape_metrics.get("max_top25_pitcher_count") != 7
        or role_shape_metrics.get("max_top50_pitcher_rate") != 0.3
        or declared_hash != actual_hash
    ):
        raise ValueError("current-board governor receipt is not bound to the candidate")
    return normalized


def _registration_path(value: Any, *, label: str) -> Path:
    return _resolve_repo_relative_path(value, label=f"registered {label}")


def _load_registered_plan() -> tuple[dict[str, Any], str]:
    if PLAN_REGISTRATION_PATH.is_symlink():
        raise ValueError("Plan 036 registration must not be a symbolic link")
    if not PLAN_REGISTRATION_PATH.is_file():
        raise ValueError("Plan 036 registration must be a regular file")
    text = PLAN_REGISTRATION_PATH.read_text(encoding="utf-8")
    if text.count(REGISTRATION_START) != 1 or text.count(REGISTRATION_END) != 1:
        raise ValueError("exactly one Plan 036 registration block is required")
    start = text.index(REGISTRATION_START) + len(REGISTRATION_START)
    end = text.index(REGISTRATION_END, start)
    match = re.fullmatch(
        r"```json\s*(\{.*\})\s*```",
        text[start:end].strip(),
        flags=re.DOTALL,
    )
    if match is None:
        raise ValueError("Plan 036 registration block is malformed")
    registration = json.loads(match.group(1))
    if not isinstance(registration, Mapping):
        raise ValueError("Plan 036 registration must be an object")
    normalized = dict(registration)
    encoded = json.dumps(
        normalized, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return normalized, _sha256_bytes(encoded)


def _validate_execution_registration(
    registration: Mapping[str, Any], readiness: Mapping[str, Any]
) -> tuple[str, str]:
    if set(registration) != EXPECTED_REGISTRATION_KEYS:
        raise ValueError("registration top-level schema drift")
    readiness_ref = registration.get("readiness")
    if not isinstance(readiness_ref, Mapping) or set(readiness_ref) != {
        "path",
        "sha256",
    }:
        raise ValueError("registration readiness binding is invalid")
    readiness_sha = readiness_ref.get("sha256")
    base_commit = registration.get("implementation_base_commit")
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
        or not isinstance(readiness_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", readiness_sha) is None
        or not isinstance(base_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", base_commit) is None
    ):
        raise ValueError("registration fixed controls are invalid")
    if not _same_path(
        _registration_path(readiness_ref.get("path"), label="readiness"),
        REGISTERED_READINESS_PATH,
    ) or not _same_path(
        _registration_path(registration.get("result_path"), label="result"),
        REGISTERED_RESULT_PATH,
    ):
        raise ValueError("registration fixed path drift")
    if (
        readiness.get("implementation_base_commit") != base_commit
        or registration.get("hashes") != readiness.get("hashes")
        or registration.get("outer_folds") != list(REGISTERED_OUTER_FOLDS)
        or registration.get("primary_endpoint") != DIRECT_METRIC
    ):
        raise ValueError("registration does not bind the readiness contract")
    candidate = registration.get("candidate")
    if not isinstance(candidate, Mapping) or set(candidate) != {
        "candidate_count",
        "pitcher_investment_feature_mode",
        "rank_model_score_mode",
        "calibration",
        "head_blend",
        "governor_thresholds_changed",
        "forbidden_substitutions",
    } or (
        candidate.get("candidate_count") != 1
        or candidate.get("pitcher_investment_feature_mode")
        != CANDIDATE_MODEL_FLAGS["PITCHER_INVESTMENT_FEATURE_MODE"]
        or candidate.get("rank_model_score_mode") != CANDIDATE_SCORE_MODE
        or candidate.get("calibration") != "fold_trained_role_head_isotonic"
        or candidate.get("head_blend") != {"outcome": 0.58, "impact": 0.42}
        or candidate.get("governor_thresholds_changed") is not False
        or candidate.get("forbidden_substitutions")
        != [
            "raw_pick_value",
            "live_role_quantile",
            "governor_relaxation",
        ]
    ):
        raise ValueError("registration candidate drift")
    bootstrap = registration.get("bootstrap")
    if bootstrap != EXPECTED_BOOTSTRAP:
        raise ValueError("registration bootstrap contract drift")
    if registration.get("thresholds") != EXPECTED_THRESHOLDS:
        raise ValueError("registration threshold contract drift")
    if registration.get("governor") != EXPECTED_GOVERNOR:
        raise ValueError("registration governor contract drift")

    source = registration.get("source_contract")
    if not isinstance(source, Mapping) or set(source) != {
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
    } or (
        source.get("cohorts") != list(EXPECTED_COHORTS)
        or source.get("declared_omissions") != [2020]
        or source.get("outcome_complete_through") != OUTCOME_COMPLETE_THROUGH
        or source.get("outcome_horizon_years") != OUTCOME_HORIZON_YEARS
        or source.get("identity_key") != "mlbam_id+role"
        or source.get("parity")
        != {
            "status": "ready",
            "cohort_year": 2014,
            "candidate_count": 1559,
            "committed_count": 1559,
            "extra": [],
            "missing": [],
        }
    ):
        raise ValueError("registration source contract drift")
    registered_sources = (registration.get("hashes") or {}).get("source_files")
    if not isinstance(registered_sources, Mapping):
        raise ValueError("registration source hashes are missing")
    source_bindings = {
        "prepared_artifact": ("prepared_path", "prepared_sha256"),
        "prepared_manifest": (
            "prepared_manifest_path",
            "prepared_manifest_sha256",
        ),
        "draft_facts": ("draft_facts_path", "draft_facts_sha256"),
    }
    for key, (path_key, sha_key) in source_bindings.items():
        record = registered_sources.get(key)
        if (
            not isinstance(record, Mapping)
            or not _same_path(
                _registration_path(source.get(path_key), label=path_key),
                _registration_path(record.get("path"), label=f"hashes.{key}"),
            )
            or source.get(sha_key) != record.get("sha256")
        ):
            raise ValueError("registration source contract hash drift")
    result_contract = registration.get("result_contract")
    if not isinstance(result_contract, Mapping) or (
        set(result_contract)
        != {
            "single_use",
            "claim_authorized",
            "automatic_promotion",
            "terminal_evidence_path",
            "acquisition_checkpoint_path",
            "outcome_cutoff_date",
        }
        or
        result_contract.get("single_use") is not True
        or result_contract.get("claim_authorized") is not False
        or result_contract.get("automatic_promotion") is not False
    ):
        raise ValueError("registration result contract drift")
    fixed_paths = {
        "terminal_evidence_path": REGISTERED_EVIDENCE_PATH,
        "acquisition_checkpoint_path": ACQUISITION_CHECKPOINT_PATH,
    }
    for key, expected in fixed_paths.items():
        if not _same_path(
            _registration_path(result_contract[key], label=key), expected
        ):
            raise ValueError(f"registration {key} drift")
    if (
        result_contract["outcome_cutoff_date"] != REGISTERED_CUTOFF_DATE
    ):
        raise ValueError("registration outcome cutoff drift")
    if registration.get("limitations") != [
        "cohort-season-completion pseudo-replay"
    ]:
        raise ValueError("registration limitations drift")
    return str(readiness_sha), str(base_commit)


def _status_paths() -> set[str]:
    sealed_path = REGISTERED_SOURCE_PATHS["current_prospect_contract"]
    output = _git_text(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
        f":(exclude){sealed_path}",
    )
    paths = set()
    for line in output.splitlines():
        if len(line) >= 4:
            paths.add(line[3:].strip('"').replace("\\", "/"))
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
        raise ValueError(f"{label} must not be a symbolic link")
    if not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    entry = _git_text("ls-tree", commit, "--", repo_path)
    match = re.fullmatch(
        rf"(100644|100755) blob ([0-9a-f]{{40}})\t{re.escape(repo_path)}",
        entry,
    )
    if match is None:
        raise ValueError(f"{label} is not a regular Git blob")
    committed_blob = match.group(2)
    if expected_blob is not None and committed_blob != expected_blob:
        raise ValueError(f"{label} registered Git blob drift")
    working_blob = _git_text(
        "hash-object",
        f"--path={repo_path}",
        str(path.resolve()),
    )
    if working_blob != committed_blob:
        raise ValueError(f"{label} worktree differs from sealed commit")
    return committed_blob


def _validate_execution_registration_files(execution_commit: str) -> None:
    for repo_path in sorted(REGISTRATION_COMMIT_PATHS):
        _validate_git_bound_worktree_file(
            commit=execution_commit,
            repo_path=repo_path,
            label=f"execution registration file:{repo_path}",
        )


def _validate_execution_git_topology(
    *,
    base_commit: str,
    allow_runtime_paths: bool,
    reservation_id: str | None = None,
) -> str:
    runtime_paths = {
        REGISTERED_RESULT_PATH.relative_to(ROOT).as_posix(),
        REGISTERED_EVIDENCE_PATH.relative_to(ROOT).as_posix(),
        ACQUISITION_CHECKPOINT_PATH.relative_to(ROOT).as_posix(),
    }
    dirty = _status_paths()
    allowed_dirty = set(runtime_paths) if allow_runtime_paths else set()
    if allow_runtime_paths and reservation_id:
        for target in (
            REGISTERED_RESULT_PATH,
            REGISTERED_EVIDENCE_PATH,
            ACQUISITION_CHECKPOINT_PATH,
        ):
            relative = target.relative_to(ROOT)
            parent = relative.parent.as_posix()
            prefix = f".{target.name}.{reservation_id}."
            for dirty_path in dirty:
                candidate = PurePosixPath(dirty_path)
                if (
                    candidate.parent.as_posix() == parent
                    and candidate.name.startswith(prefix)
                    and candidate.name.endswith(".tmp")
                    and len(candidate.name) > len(prefix) + len(".tmp")
                ):
                    allowed_dirty.add(dirty_path)
        result_relative = REGISTERED_RESULT_PATH.relative_to(ROOT).as_posix()
        allowed_dirty.update(
            {
                f"{result_relative}.running",
                f"{result_relative}.finalizing",
            }
        )
    if dirty - allowed_dirty:
        raise ValueError(
            "execution worktree is not clean: " + ", ".join(sorted(dirty))
        )
    topology = _git_text("rev-list", "--parents", "-n", "1", "HEAD").split()
    if len(topology) != 2 or topology[1] != base_commit:
        raise ValueError("execution HEAD is not the direct registration child")
    changed: set[str] = set()
    statuses: dict[str, str] = {}
    for line in _git_text(
        "diff", "--name-status", base_commit, "HEAD"
    ).splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError("execution registration diff is malformed")
        status, path = parts
        normalized = path.replace("\\", "/")
        changed.add(normalized)
        statuses[normalized] = status
    if changed != REGISTRATION_COMMIT_PATHS or any(
        status not in {"A", "M"} for status in statuses.values()
    ):
        raise ValueError("execution HEAD contains non-registration changes")
    _validate_execution_registration_files(topology[0])
    return topology[0]


def _registered_source_blobs(
    readiness: Mapping[str, Any], *, base_commit: str, source_keys: Sequence[str]
) -> dict[str, bytes]:
    source_records = (readiness.get("hashes") or {}).get("source_files") or {}
    blobs = {}
    if not set(source_keys).issubset(REGISTERED_SOURCE_PATHS):
        raise ValueError("unregistered source blob key")
    for key in source_keys:
        relative_path = REGISTERED_SOURCE_PATHS[key]
        _validate_hash_record(
            source_records.get(key),
            label=f"source:{key}",
            expected_repo_path=relative_path,
            git_base_commit=base_commit,
            verify_content=key != "current_prospect_contract",
            git_blob_only=key == "current_prospect_contract",
        )
        content = _git_bytes("cat-file", "blob", f"{base_commit}:{relative_path}")
        blobs[key] = content
    return blobs


def _manual_graduated_ids(payload: Mapping[str, Any]) -> list[str]:
    values = []
    for key in ("graduated_mlbam_ids", "excluded_mlbam_ids"):
        raw = payload.get(key)
        if not isinstance(raw, list):
            raise ValueError("manual graduation source is malformed")
        values.extend(str(value) for value in raw)
    if any(not value.isdigit() for value in values):
        raise ValueError("manual graduation identity is malformed")
    return sorted(set(values))


def _milb_history_index(
    season_stats: Mapping[str, Any], card_history: Mapping[str, Any]
) -> dict[tuple[str, str], dict[str, Any]]:
    current_season = season_stats.get("season")
    current: dict[tuple[str, str], list[dict]] = {}
    history: dict[tuple[str, str], list[dict]] = {}
    for role_key in ("hitters", "pitchers"):
        rows = season_stats.get(role_key)
        if not isinstance(rows, list):
            raise ValueError("MiLB season-stat source is malformed")
        for source in rows:
            if not isinstance(source, Mapping):
                raise ValueError("MiLB season-stat row is malformed")
            role = str(source.get("role") or "")
            mlbam_id = str(source.get("mlbam_id") or "")
            if role not in {"hitter", "pitcher"} or not mlbam_id.isdigit():
                continue
            current.setdefault((mlbam_id, role), []).append(
                {**dict(source), "season": source.get("season", current_season)}
            )
    players = card_history.get("players")
    if not isinstance(players, Mapping):
        raise ValueError("MiLB card-history source is malformed")
    for player_rows in players.values():
        if not isinstance(player_rows, list):
            raise ValueError("MiLB card-history rows are malformed")
        for source in player_rows:
            if not isinstance(source, Mapping):
                raise ValueError("MiLB card-history row is malformed")
            role = str(source.get("role") or "")
            mlbam_id = str(source.get("mlbam_id") or "")
            if role in {"hitter", "pitcher"} and mlbam_id.isdigit():
                history.setdefault((mlbam_id, role), []).append(dict(source))
    index = {}
    for key in set(current) | set(history):
        rows = list(current.get(key, [])) + [
            row
            for row in history.get(key, [])
            if row.get("season") != current_season
        ]
        rows.sort(key=lambda row: int(row.get("season") or 0), reverse=True)
        index[key] = {"rows": rows, "current_season": current_season}
    return index


def _checkpoint_binding(
    *, reservation_id: str, registration_sha256: str, readiness_sha256: str
) -> dict[str, Any]:
    return {
        "artifact": "valucast_plan036_sealed_acquisition_checkpoint",
        "schema_version": 1,
        "reservation_id": reservation_id,
        "registration_sha256": registration_sha256,
        "registered_readiness_sha256": readiness_sha256,
        "outcome_cutoff_date": REGISTERED_CUTOFF_DATE,
    }


def _make_registered_outcome_acquirer(
    source_loader: Callable[[], Mapping[str, Mapping[str, Any]]],
    *,
    registration_sha256: str,
    readiness_sha256: str,
    current_contract_record: Mapping[str, Any],
) -> OutcomeAcquirer:
    # The registered production contract is comparison context only.  It is
    # intentionally never opened or used to seed outcome truth here: every
    # target identity must earn a strict provider receipt after reservation.
    del source_loader
    frozen_record = copy.deepcopy(dict(current_contract_record))

    def acquire(
        *,
        reservation_id: str,
        prepared: Mapping[str, Any],
        readiness: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        del readiness
        binding = _checkpoint_binding(
            reservation_id=reservation_id,
            registration_sha256=registration_sha256,
            readiness_sha256=readiness_sha256,
        )
        target_rows = [
            row
            for row in prepared.get("rows") or []
            if int(row["cohort_year"]) <= MATURE_COHORT_THROUGH
        ]
        target_specs = {
            f"{int(row['mlbam_id'])}_{row['role']}": (
                int(row["mlbam_id"]),
                str(row["role"]),
            )
            for row in target_rows
        }
        target_keys = sorted(target_specs)
        fetch_policy = {
            "mode": STRICT_OUTCOME_FETCH_MODE,
            "legacy_contract_cache_used": False,
            "max_attempts_per_identity": ACQUISITION_MAX_ATTEMPTS,
            "checkpoint_batch_size": ACQUISITION_CHECKPOINT_BATCH_SIZE,
        }
        if ACQUISITION_CHECKPOINT_PATH.exists():
            checkpoint = _load_mapping(ACQUISITION_CHECKPOINT_PATH)
            if (
                any(checkpoint.get(key) != value for key, value in binding.items())
                or checkpoint.get("target_identities") != target_keys
                or checkpoint.get("fetch_policy") != fetch_policy
            ):
                raise ValueError(
                    "acquisition checkpoint is bound to another registration"
                )
            receipts = checkpoint.get("raw_response_receipts")
            if not isinstance(receipts, Mapping):
                raise ValueError("acquisition checkpoint is malformed")
            raw_receipts = copy.deepcopy(dict(receipts))
        else:
            raw_receipts = {}
            checkpoint = {
                **binding,
                "status": "acquiring",
                "comparison_context": {
                    "source": "registered_current_prospect_contract",
                    "record": frozen_record,
                    "used_as_outcome_truth": False,
                },
                "fetch_policy": fetch_policy,
                "target_identities": target_keys,
                "raw_response_receipts": raw_receipts,
                "coverage": {
                    "target_identity_count": len(target_keys),
                    "receipt_identity_count": 0,
                    "resolved_identity_count": 0,
                    "remaining_identity_count": len(target_keys),
                },
            }
            _atomic_json(ACQUISITION_CHECKPOINT_PATH, checkpoint)

        source_cache: dict[str, list[dict]] = {}
        for identity, receipt in raw_receipts.items():
            if identity not in target_specs:
                raise ValueError(
                    f"acquisition checkpoint has an unregistered receipt: {identity}"
                )
            if isinstance(receipt, Mapping) and receipt.get("status") == "resolved":
                source_cache[identity] = _resolved_seasons_from_provider_receipt(
                    receipt,
                    identity=identity,
                )

        checkpoint_lock = threading.Lock()
        completed_since_flush = 0

        def checkpoint_payload(status: str, remaining: Sequence[str]) -> dict[str, Any]:
            resolved_count = sum(
                1
                for receipt in raw_receipts.values()
                if isinstance(receipt, Mapping)
                and receipt.get("status") == "resolved"
            )
            payload = {
                **binding,
                "status": status,
                "comparison_context": {
                    "source": "registered_current_prospect_contract",
                    "record": frozen_record,
                    "used_as_outcome_truth": False,
                },
                "fetch_policy": fetch_policy,
                "target_identities": target_keys,
                "raw_response_receipts": raw_receipts,
                "coverage": {
                    "target_identity_count": len(target_keys),
                    "receipt_identity_count": len(raw_receipts),
                    "resolved_identity_count": resolved_count,
                    "remaining_identity_count": len(remaining),
                },
                "remaining": list(remaining),
            }
            quality_starts_state = checkpoint.get("quality_starts_acquisition")
            if isinstance(quality_starts_state, Mapping):
                payload["quality_starts_acquisition"] = quality_starts_state
            return payload

        def flush_checkpoint(status: str, remaining: Sequence[str]) -> None:
            nonlocal checkpoint, completed_since_flush
            checkpoint = checkpoint_payload(status, remaining)
            _atomic_json(ACQUISITION_CHECKPOINT_PATH, checkpoint)
            completed_since_flush = 0

        def fetcher(mlbam_id: int, role: str) -> list[dict] | None:
            identity = f"{int(mlbam_id)}_{role}"
            attempts = []
            seasons = None
            final_status = "unresolved"
            for attempt_index in range(ACQUISITION_MAX_ATTEMPTS):
                seasons, attempt = _fetch_strict_statsapi_with_receipt(
                    mlbam_id, role
                )
                attempts.append(attempt)
                if attempt.get("status") == "resolved":
                    final_status = "resolved"
                    break
                if attempt_index + 1 < ACQUISITION_MAX_ATTEMPTS:
                    time.sleep(0.25 * (2 ** attempt_index))
            receipt: dict[str, Any] = {
                "identity": identity,
                "mlbam_id": int(mlbam_id),
                "role": role,
                "status": final_status,
                "attempt_count": len(attempts),
                "attempts": attempts,
            }
            if final_status == "resolved":
                receipt["season_count"] = len(seasons or [])
            with checkpoint_lock:
                nonlocal completed_since_flush
                raw_receipts[identity] = receipt
                completed_since_flush += 1
                if completed_since_flush >= ACQUISITION_CHECKPOINT_BATCH_SIZE:
                    unresolved = sorted(set(target_keys) - {
                        key
                        for key, value in raw_receipts.items()
                        if isinstance(value, Mapping)
                        and value.get("status") == "resolved"
                    })
                    flush_checkpoint("acquiring", unresolved)
            return seasons

        from scripts.backfill_extended_prospect_outcomes import backfill_outcomes

        report = backfill_outcomes(
            target_rows,
            source_cache,
            fetcher=fetcher,
        )
        terminal_status = (
            "outcomes_ready"
            if report["status"] == "ready"
            else "acquisition_incomplete"
        )
        with checkpoint_lock:
            flush_checkpoint(terminal_status, report["remaining"])
        checkpoint_record = {
            "path": _canonical_repo_relative_path(
                ACQUISITION_CHECKPOINT_PATH, label="acquisition checkpoint"
            ),
            "sha256": _sha256_file(ACQUISITION_CHECKPOINT_PATH),
        }
        if report["status"] != "ready":
            raise ResumableAcquisitionIncomplete(
                "registered outcome acquisition remains resumable: "
                f"remaining={len(report['remaining'])}",
                checkpoint=checkpoint_record,
                remaining_count=len(report["remaining"]),
            )
        reconstructed = {
            identity: _resolved_seasons_from_provider_receipt(
                raw_receipts[identity], identity=identity
            )
            for identity in target_keys
        }
        return {
            "cache": reconstructed,
            "provider_receipt": {
                "mode": STRICT_OUTCOME_FETCH_MODE,
                "reservation_id": reservation_id,
                "outcome_cutoff_date": REGISTERED_CUTOFF_DATE,
                "checkpoint": checkpoint_record,
                "target_identity_count": len(target_keys),
                "receipt_identity_count": len(raw_receipts),
                "resolved_identity_count": len(reconstructed),
                "legacy_contract_cache_used": False,
            },
        }

    return acquire


def parse_strict_statsapi_game_logs(
    payload: Any, *, mlbam_id: int, season: int
) -> list[dict]:
    """Parse a raw StatsAPI pitching game-log response without defaults."""
    if not isinstance(payload, Mapping):
        raise ValueError("StatsAPI game-log payload is not an object")
    if set(payload) not in ({"stats"}, {"copyright", "stats"}) or (
        "copyright" in payload and not isinstance(payload["copyright"], str)
    ):
        raise ValueError("StatsAPI game-log root schema is malformed")
    groups = payload.get("stats")
    if not isinstance(groups, list) or len(groups) != 1:
        raise ValueError("StatsAPI game-log stats are malformed")
    splits: list[dict] = []
    for group in groups:
        if (
            not isinstance(group, Mapping)
            or not isinstance(group.get("type"), Mapping)
            or group["type"].get("displayName") != "gameLog"
            or not isinstance(group.get("group"), Mapping)
            or group["group"].get("displayName") != "pitching"
            or not isinstance(group.get("splits"), list)
        ):
            raise ValueError("StatsAPI game-log splits are malformed")
        for split in group["splits"]:
            if not isinstance(split, Mapping):
                raise ValueError("StatsAPI game-log split is malformed")
            stat = split.get("stat")
            sport = split.get("sport")
            player = split.get("player")
            if (
                not isinstance(split.get("date"), str)
                or str(split.get("season")) != str(int(season))
                or split.get("gameType") != "R"
                or not isinstance(sport, Mapping)
                or str(sport.get("id")) != "1"
                or (
                    player is not None
                    and (
                        not isinstance(player, Mapping)
                        or str(player.get("id")) != str(int(mlbam_id))
                    )
                )
                or not isinstance(stat, Mapping)
                or not {"gamesStarted", "inningsPitched", "earnedRuns"}.issubset(stat)
            ):
                raise ValueError("StatsAPI game-log QS fields are incomplete")
            try:
                int(stat["gamesStarted"])
                parse_innings(stat["inningsPitched"])
                int(stat["earnedRuns"])
            except (TypeError, ValueError) as exc:
                raise ValueError("StatsAPI game-log QS fields are malformed") from exc
            splits.append(copy.deepcopy(dict(split)))
    return splits


def _fetch_strict_qs_game_log_with_receipt(
    mlbam_id: int,
    season: int,
    *,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> tuple[list[dict] | None, dict[str, Any]]:
    url = (
        f"https://statsapi.mlb.com/api/v1/people/{int(mlbam_id)}/stats"
        f"?stats=gameLog&group=pitching&season={int(season)}&gameType=R"
    )
    receipt: dict[str, Any] = {
        "mlbam_id": int(mlbam_id),
        "season": int(season),
        "provider": "MLB StatsAPI",
        "stat": "gameLog",
        "group": "pitching",
        "game_type": "R",
    }
    try:
        with opener(url, timeout=20) as response:
            raw = response.read()
            status = int(getattr(response, "status", 200))
        receipt.update(
            {
                "http_status": status,
                **_compressed_raw_receipt_fields(raw),
            }
        )
        if status != 200:
            receipt["status"] = "unresolved_http_status"
            return None, receipt
        try:
            payload = json.loads(raw.decode("utf-8"))
            games = parse_strict_statsapi_game_logs(
                payload, mlbam_id=mlbam_id, season=season
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
            receipt.update(
                {"status": "invalid_response", "error_type": type(exc).__name__}
            )
            return None, receipt
        receipt.update({"status": "resolved", "game_count": len(games)})
        return games, receipt
    except (OSError, http.client.HTTPException) as exc:
        receipt.update(
            {"status": "unresolved_transport", "error_type": type(exc).__name__}
        )
        return None, receipt


def _resolved_games_from_qs_receipt(receipt: Any, *, key: str) -> list[dict]:
    if not isinstance(receipt, Mapping) or set(receipt) != {
        "key",
        "mlbam_id",
        "season",
        "status",
        "attempt_count",
        "attempts",
        "game_count",
    }:
        raise ValueError(f"quality-start provider receipt is malformed: {key}")
    attempts = receipt.get("attempts")
    if (
        receipt.get("key") != key
        or f"{receipt.get('mlbam_id')}:{receipt.get('season')}" != key
        or receipt.get("status") != "resolved"
        or not isinstance(attempts, list)
        or not attempts
        or receipt.get("attempt_count") != len(attempts)
    ):
        raise ValueError(f"quality-start provider receipt binding drift: {key}")
    common = {
        "mlbam_id",
        "season",
        "provider",
        "stat",
        "group",
        "game_type",
        "status",
    }
    for attempt in attempts:
        if not isinstance(attempt, Mapping):
            raise ValueError(f"quality-start provider attempt is malformed: {key}")
        status = attempt.get("status")
        if status == "unresolved_transport":
            expected = common | {"error_type"}
        elif status in {"unresolved_http_status", "resolved", "invalid_response"}:
            expected = common | {
                "http_status",
                "raw_encoding",
                "raw_sha256",
                "raw_byte_count",
                "compressed_sha256",
                "compressed_byte_count",
                "compressed_body_base64",
            }
            if status == "resolved":
                expected.add("game_count")
            elif status == "invalid_response":
                expected.add("error_type")
        else:
            raise ValueError(f"quality-start provider attempt status drift: {key}")
        if set(attempt) != expected or (
            attempt.get("mlbam_id") != receipt["mlbam_id"]
            or attempt.get("season") != receipt["season"]
            or attempt.get("provider") != "MLB StatsAPI"
            or attempt.get("stat") != "gameLog"
            or attempt.get("group") != "pitching"
            or attempt.get("game_type") != "R"
        ):
            raise ValueError(f"quality-start provider attempt binding drift: {key}")
        if status != "unresolved_transport":
            _raw_bytes_from_compressed_receipt(
                attempt, label=f"quality-start provider body: {key}"
            )
    final = attempts[-1]
    if final.get("status") != "resolved" or final.get("http_status") != 200:
        raise ValueError(f"quality-start provider receipt has no success: {key}")
    raw = _raw_bytes_from_compressed_receipt(
        final, label=f"quality-start provider terminal body: {key}"
    )
    try:
        games = parse_strict_statsapi_game_logs(
            json.loads(raw.decode("utf-8")),
            mlbam_id=int(receipt["mlbam_id"]),
            season=int(receipt["season"]),
        )
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError(f"quality-start provider receipt cannot reparse: {key}") from exc
    if (
        final.get("game_count") != len(games)
        or receipt.get("game_count") != len(games)
    ):
        raise ValueError(f"quality-start provider game count drift: {key}")
    return games


def _quality_start_fetch_targets(contract: Mapping[str, Any]) -> list[str]:
    targets = set()
    for identity, seasons in (contract.get("historical_mlb_seasons") or {}).items():
        if not str(identity).endswith("_pitcher"):
            continue
        mlbam_id = int(str(identity).removesuffix("_pitcher"))
        for season in seasons or []:
            year = int(season["year"])
            games_started = season.get("gs")
            should_fetch = (
                games_started is not None and int(games_started) > 0
            ) or (
                games_started is None and float(season.get("ip") or 0) > 0
            )
            if should_fetch:
                targets.add(f"{mlbam_id}:{year}")
    return sorted(targets)


def _registered_quality_starts_builder(
    contract: Mapping[str, Any], reservation_id: str
) -> Mapping[str, Any]:
    from scripts.build_stage2_quality_starts import build_quality_starts

    payload = _quality_starts_input_payload(contract)
    input_sha256 = _canonical_payload_sha256(payload)
    input_descriptor = _quality_starts_input_descriptor(
        input_sha256, document_path=REGISTERED_EVIDENCE_PATH
    )
    checkpoint = _load_mapping(ACQUISITION_CHECKPOINT_PATH)
    if (
        checkpoint.get("reservation_id") != reservation_id
        or checkpoint.get("status")
        not in {
            "outcomes_ready",
            "acquisition_incomplete",
            "quality_starts_acquiring",
            "quality_starts_incomplete",
            "ready",
        }
    ):
        raise ValueError("quality-start acquisition checkpoint binding drift")
    targets = _quality_start_fetch_targets(contract)
    fetch_policy = {
        "max_attempts_per_player_season": ACQUISITION_MAX_ATTEMPTS,
        "checkpoint_batch_size": ACQUISITION_CHECKPOINT_BATCH_SIZE,
    }
    state = checkpoint.get("quality_starts_acquisition")
    if state is None:
        receipts: dict[str, Any] = {}
    elif not isinstance(state, Mapping) or (
        state.get("reservation_id") != reservation_id
        or state.get("input") != input_descriptor
        or state.get("source") != QUALITY_STARTS_SOURCE
        or state.get("fetch_policy") != fetch_policy
        or state.get("target_player_seasons") != targets
        or not isinstance(state.get("raw_response_receipts"), Mapping)
    ):
        raise ValueError("quality-start acquisition state binding drift")
    else:
        receipts = copy.deepcopy(dict(state["raw_response_receipts"]))

    games_by_key = {}
    for key, receipt in receipts.items():
        if key not in targets:
            raise ValueError(f"unregistered quality-start receipt: {key}")
        if isinstance(receipt, Mapping) and receipt.get("status") == "resolved":
            games_by_key[key] = _resolved_games_from_qs_receipt(receipt, key=key)

    checkpoint_lock = threading.Lock()
    completed_since_flush = 0

    def flush(status: str, remaining: Sequence[str]) -> dict[str, str]:
        nonlocal checkpoint, completed_since_flush
        resolved_count = sum(
            1
            for receipt in receipts.values()
            if isinstance(receipt, Mapping) and receipt.get("status") == "resolved"
        )
        qs_state = {
            "reservation_id": reservation_id,
            "status": status,
            "input": input_descriptor,
            "source": QUALITY_STARTS_SOURCE,
            "fetch_policy": fetch_policy,
            "target_player_seasons": targets,
            "raw_response_receipts": receipts,
            "coverage": {
                "target_player_season_count": len(targets),
                "receipt_player_season_count": len(receipts),
                "resolved_player_season_count": resolved_count,
                "remaining_player_season_count": len(remaining),
            },
            "remaining": list(remaining),
        }
        checkpoint = {
            **checkpoint,
            "status": "ready" if status == "ready" else status,
            "quality_starts_acquisition": qs_state,
        }
        _atomic_json(ACQUISITION_CHECKPOINT_PATH, checkpoint)
        completed_since_flush = 0
        return {
            "path": _canonical_repo_relative_path(
                ACQUISITION_CHECKPOINT_PATH, label="acquisition checkpoint"
            ),
            "sha256": _sha256_file(ACQUISITION_CHECKPOINT_PATH),
        }

    def fetch_one(key: str) -> tuple[str, list[dict] | None]:
        nonlocal completed_since_flush
        mlbam_text, season_text = key.split(":", 1)
        mlbam_id = int(mlbam_text)
        season = int(season_text)
        attempts = []
        games = None
        final_status = "unresolved"
        for attempt_index in range(ACQUISITION_MAX_ATTEMPTS):
            games, attempt = _fetch_strict_qs_game_log_with_receipt(
                mlbam_id, season
            )
            attempts.append(attempt)
            if attempt.get("status") == "resolved":
                final_status = "resolved"
                break
            if attempt_index + 1 < ACQUISITION_MAX_ATTEMPTS:
                time.sleep(0.25 * (2 ** attempt_index))
        receipt: dict[str, Any] = {
            "key": key,
            "mlbam_id": mlbam_id,
            "season": season,
            "status": final_status,
            "attempt_count": len(attempts),
            "attempts": attempts,
        }
        if final_status == "resolved":
            receipt["game_count"] = len(games or [])
        with checkpoint_lock:
            receipts[key] = receipt
            completed_since_flush += 1
            if completed_since_flush >= ACQUISITION_CHECKPOINT_BATCH_SIZE:
                unresolved = sorted(set(targets) - {
                    item
                    for item, value in receipts.items()
                    if isinstance(value, Mapping)
                    and value.get("status") == "resolved"
                })
                flush("quality_starts_acquiring", unresolved)
        return key, games

    missing = [key for key in targets if key not in games_by_key]
    with ThreadPoolExecutor(max_workers=10) as executor:
        for key, games in executor.map(fetch_one, missing):
            if games is not None:
                games_by_key[key] = games

    remaining = sorted(set(targets) - set(games_by_key))
    if remaining:
        with checkpoint_lock:
            record = flush("quality_starts_incomplete", remaining)
        raise ResumableAcquisitionIncomplete(
            "quality-start acquisition remains resumable: "
            f"remaining={len(remaining)}",
            checkpoint=record,
            remaining_count=len(remaining),
        )

    history_rows = []
    for identity, seasons in (
        payload.get("historical_mlb_seasons") or {}
    ).items():
        if not str(identity).endswith("_pitcher"):
            continue
        mlbam_id = int(str(identity).rsplit("_", 1)[0])
        for season in seasons or []:
            if isinstance(season, Mapping) and "gs" in season:
                history_rows.append(
                    {
                        "id": mlbam_id,
                        "season": int(season["year"]),
                        "gs": season["gs"],
                    }
                )
    report = build_quality_starts(
        payload,
        {"rows": history_rows},
        input_path=input_descriptor["document_path"],
        input_sha256=input_sha256,
        fetcher=lambda mlbam_id, _group, season: games_by_key[
            f"{int(mlbam_id)}:{int(season)}"
        ],
        checkpoint_path=None,
        delay=0.0,
    )
    if report.get("status") != "ready":
        with checkpoint_lock:
            flush("fatal_quality_start_validation", [])
        raise ValueError("quality-start sidecar failed semantic validation")
    report["input"] = input_descriptor
    report["reservation_id"] = reservation_id
    report["content_sha256"] = _quality_starts_content_sha256(report)
    with checkpoint_lock:
        flush("ready", [])
    return report


def _current_board_evaluator(
    sources: Mapping[str, Mapping[str, Any]],
) -> GovernorEvaluator:
    from prospects.model import validate_input_contract
    from prospects.pre2014_current_board import (
        make_current_board_governor_evaluator,
    )

    current_contract = copy.deepcopy(dict(sources["current_prospect_contract"]))
    validate_input_contract(current_contract)
    snapshots = {
        name: copy.deepcopy(
            dict((sources[key].get("players_by_mlbam") or {}))
        )
        for name, key in {
            "sts": "sts_snapshot",
            "fangraphs": "fangraphs_snapshot",
            "prospectslive": "prospectslive_snapshot",
            "pipeline": "pipeline_snapshot",
            "hkb": "hkb_snapshot",
        }.items()
    }
    return make_current_board_governor_evaluator(
        current_contract,
        sources["prospect_universe"],
        sources["dynasty_layer"],
        rank_context={
            "manual_graduated_ids": _manual_graduated_ids(
                sources["manual_graduation"]
            ),
            "external_snapshots": snapshots,
        },
        prospect_availability=sources["prospect_availability"],
        milb_history_by_key=_milb_history_index(
            sources["milb_season_stats"], sources["milb_card_history"]
        ),
        mlb_roster_status=sources["mlb_roster_status"],
        investment_evidence=sources["investment_evidence"],
    )


def _spent_payload(
    error: BaseException, evidence_bundle: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "artifact": "valucast_pre2014_cross_role_gate",
        "protocol": PROTOCOL,
        "status": "spent_error",
        "decision": "production_review_not_authorized",
        "production_review_authorized": False,
        "claim_authorized": False,
        "error_type": type(error).__name__,
        "evidence_bundle": dict(evidence_bundle),
    }


def _run_sealed_adjudication_locked(
    *,
    readiness_path: Path | str,
    registered_readiness_sha256: str,
    result_path: Path | str,
    outcome_acquirer: OutcomeAcquirer,
    quality_starts_builder: QualityStartsBuilder,
    governor_evaluator: GovernorEvaluator,
    fold_scorer: FoldScorer = score_outer_fold,
    reservation_id: str | None = None,
    evidence_dir: Path | str | None = None,
    evidence_path: Path | str | None = None,
    preloaded_sources: Mapping[str, Mapping[str, Any]] | None = None,
    existing_reservation: bool = False,
    evidence_context: Mapping[str, Any] | None = None,
    git_base_commit: str | None = None,
    quality_starts_input_path: Path | str | None = None,
) -> dict[str, Any]:
    """Run the registered look once and permanently consume its result path."""
    result_path = Path(result_path)
    readiness, paths = validate_registered_readiness(
        readiness_path,
        registered_readiness_sha256,
        result_path,
        git_base_commit=git_base_commit,
    )
    loaded_sources = dict(preloaded_sources or {})
    prepared = dict(
        loaded_sources.get("prepared_artifact")
        or _load_mapping(paths["prepared_artifact"])
    )
    all_rows = _prepared_rows(prepared)
    rows = [
        row for row in all_rows if int(row["cohort_year"]) <= MATURE_COHORT_THROUGH
    ]
    if not rows or any(int(row["cohort_year"]) > MATURE_COHORT_THROUGH for row in rows):
        raise ValueError("registered mature cohort selection is invalid")
    prepared_for_execution = dict(prepared)
    prepared_for_execution["rows"] = rows
    prepared_for_execution["candidate_count"] = len(rows)
    draft_facts = _draft_facts(
        dict(
            loaded_sources.get("draft_facts")
            or _load_mapping(paths["draft_facts"])
        )
    )

    if existing_reservation:
        if not reservation_id:
            raise ValueError("existing reservation requires a reservation id")
        marker = _load_mapping(result_path)
        if marker != {
            "reservation_id": reservation_id,
            "status": "reserved_before_outer_outcomes",
        }:
            raise ValueError("existing result is not the registered reservation")
        token = reservation_id
    else:
        token = reserve_result_path(result_path, reservation_id=reservation_id)
    if evidence_path is None:
        if evidence_dir is not None:
            evidence_path = Path(evidence_dir) / "terminal-evidence.json"
        else:
            evidence_path = result_path.with_name(
                f"{result_path.stem}-evidence.json"
            )
    evidence_path = Path(evidence_path)
    evidence: dict[str, Any] = {
        "artifact": "valucast_plan036_terminal_evidence",
        "schema_version": 1,
        "status": "in_progress",
        "reservation_id": token,
        "registered_readiness_sha256": registered_readiness_sha256,
        "implementation_base_commit": readiness["implementation_base_commit"],
        "mature_cohort_through": MATURE_COHORT_THROUGH,
        "outcome_horizon_years": OUTCOME_HORIZON_YEARS,
        "outcome_complete_through": OUTCOME_COMPLETE_THROUGH,
        "source_hashes": readiness["hashes"],
        **dict(evidence_context or {}),
    }
    evidence_bundle: dict[str, dict[str, str]] = {}

    def persist_evidence() -> dict[str, dict[str, str]]:
        record = _write_evidence(evidence_path, evidence)
        return {"terminal_evidence": record}

    try:
        evidence_bundle = persist_evidence()
        acquired = outcome_acquirer(
            reservation_id=token,
            prepared=prepared_for_execution,
            readiness=readiness,
        )
        cohort_year_by_identity = {
            f"{int(row['mlbam_id'])}_{row['role']}": int(row["cohort_year"])
            for row in rows
        }
        seasons = _outcomes(acquired, cohort_year_by_identity)
        expected_outcome_keys = {
            f"{int(row['mlbam_id'])}_{row['role']}" for row in rows
        }
        if set(seasons) != expected_outcome_keys:
            missing = sorted(expected_outcome_keys - set(seasons))
            extra = sorted(set(seasons) - expected_outcome_keys)
            raise ValueError(
                "outcome identity set mismatch: "
                f"missing={len(missing)} extra={len(extra)}"
            )
        provider = (
            acquired.get("provider_receipt")
            if isinstance(acquired, Mapping)
            else None
        )
        evidence["canonical_outcomes"] = {
            "provider_receipt": provider or {"mode": "registered_acquirer"},
            "cohort_horizon": {
                "mature_through": MATURE_COHORT_THROUGH,
                "years_forward": OUTCOME_HORIZON_YEARS,
                "complete_through": OUTCOME_COMPLETE_THROUGH,
            },
            "identity_count": len(seasons),
            "historical_mlb_seasons": seasons,
        }
        evidence_bundle = persist_evidence()
        labeled_rows = build_labeled_rows(
            rows,
            seasons,
            draft_facts,
            horizon_years=OUTCOME_HORIZON_YEARS,
        )
        contract: dict[str, Any] = {
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
            "candidate_count": len(rows),
            "labeled_row_count": len(labeled_rows),
            "identity_parity": prepared.get("identity_parity"),
            "rows": labeled_rows,
            "historical_mlb_seasons": seasons,
        }
        if len(labeled_rows) != len(rows):
            raise ValueError("extended labeled contract is incomplete")
        evidence["labeled_contract"] = contract
        evidence_bundle = persist_evidence()
        quality_starts_input = _quality_starts_input_payload(contract)
        quality_starts_input_sha256 = _canonical_payload_sha256(
            quality_starts_input
        )
        quality_starts_document_path = (
            Path(quality_starts_input_path)
            if quality_starts_input_path is not None
            else evidence_path
        )
        quality_starts_input_descriptor = _quality_starts_input_descriptor(
            quality_starts_input_sha256,
            document_path=quality_starts_document_path,
        )
        evidence["quality_starts"] = {
            "input_contract": quality_starts_input,
            "input_descriptor": quality_starts_input_descriptor,
        }
        evidence_bundle = persist_evidence()
        sidecar = quality_starts_builder(contract, token)
        sidecar, joined_seasons = _validate_quality_starts(
            seasons,
            sidecar,
            reservation_id=token,
            expected_input_sha256=quality_starts_input_sha256,
            expected_input_path=(
                quality_starts_document_path
            ),
        )
        if isinstance(provider, dict) and provider.get("mode") == STRICT_OUTCOME_FETCH_MODE:
            provider["checkpoint"] = {
                "path": _canonical_repo_relative_path(
                    ACQUISITION_CHECKPOINT_PATH,
                    label="acquisition checkpoint",
                ),
                "sha256": _sha256_file(ACQUISITION_CHECKPOINT_PATH),
            }
        contract["historical_mlb_seasons"] = joined_seasons
        contract["quality_starts"] = sidecar
        qs_hash = str(sidecar["content_sha256"])
        evidence["quality_starts"] = {
            "input_contract": quality_starts_input,
            "input_descriptor": quality_starts_input_descriptor,
            "sidecar": sidecar,
            "provider": copy.deepcopy(sidecar.get("source")),
        }
        evidence_bundle = persist_evidence()

        converted_folds = []
        for cohort_year in REGISTERED_OUTER_FOLDS:
            eligible = {
                (str(row["mlbam_id"]), str(row["role"]))
                for row in labeled_rows
                if int(row["cohort_year"]) == cohort_year
            }
            if not eligible:
                raise ValueError(f"registered outer fold is empty: {cohort_year}")
            scored = fold_scorer(contract, cohort_year)
            converted_folds.append(
                convert_fold_output(
                    scored,
                    cohort_year=cohort_year,
                    eligible_identities=eligible,
                    quality_starts_sha256=qs_hash,
                    mature_cohort_years=sorted(
                        {
                            int(row["cohort_year"])
                            for row in labeled_rows
                            if int(row["cohort_year"])
                            <= cohort_year - OUTCOME_HORIZON_YEARS
                        }
                    ),
                )
            )
        evidence["fold_outputs"] = converted_folds
        evidence_bundle = persist_evidence()

        governor_receipt = _validate_governor_receipt(
            governor_evaluator(
                reservation_id=token,
                research_contract=contract,
                quality_starts=sidecar,
                readiness=readiness,
            ),
            reservation_id=token,
        )
        evaluation = evaluate_pre2014_cross_role_gate(
            converted_folds,
            cohort_years=EXPECTED_COHORTS,
            declared_omissions={2020},
            current_role_shape_governor_passed=governor_receipt["passed"],
        )
        authorized = evaluation.get("production_review_authorized") is True
        evidence.update(
            {
                "status": "passed" if authorized else "failed",
                "quality_starts_sha256": qs_hash,
                "current_role_shape_governor": governor_receipt,
                "evaluation": evaluation,
            }
        )
        evidence_bundle = persist_evidence()
        payload = {
            "artifact": "valucast_pre2014_cross_role_gate",
            "schema_version": 1,
            "protocol": PROTOCOL,
            "status": "passed" if authorized else "failed",
            "decision": evaluation.get("decision"),
            "production_review_authorized": authorized,
            "claim_authorized": False,
            "registered_readiness_sha256": registered_readiness_sha256,
            "candidate": {
                "model_flags": dict(CANDIDATE_MODEL_FLAGS),
                "model_score_mode": CANDIDATE_SCORE_MODE,
            },
            "outer_folds": list(REGISTERED_OUTER_FOLDS),
            "quality_starts_sha256": qs_hash,
            "current_role_shape_governor": governor_receipt,
            "fold_outputs": converted_folds,
            "evaluation": evaluation,
            "evidence_bundle": evidence_bundle,
        }
        finalized_payload = {
            **payload,
            "reservation_id": token,
            "claim_authorized": False,
        }
        finalize_reserved_result(result_path, token, payload)
        # Match the persisted JSON value without reopening the committed path;
        # a post-commit read error must never enter the spent-error handler.
        return json.loads(
            json.dumps(finalized_payload, sort_keys=True, allow_nan=False)
        )
    except ResumableAcquisitionIncomplete as error:
        evidence.update(
            {
                "status": "acquisition_incomplete",
                "error_type": type(error).__name__,
                "acquisition_checkpoint": error.checkpoint,
                "remaining_identity_count": error.remaining_count,
            }
        )
        # A provider/transport gap is not an adjudication result.  Keep the
        # original reservation marker intact so the same registered look can
        # resume only its unresolved identities.
        try:
            persist_evidence()
        except Exception:
            pass
        raise
    except Exception as error:
        evidence.update(
            {
                "status": "spent_error",
                "error_type": type(error).__name__,
            }
        )
        try:
            try:
                evidence_bundle = persist_evidence()
            except Exception as evidence_error:
                evidence = {
                    "artifact": "valucast_plan036_terminal_evidence",
                    "schema_version": 1,
                    "status": "spent_error",
                    "reservation_id": token,
                    "registered_readiness_sha256": registered_readiness_sha256,
                    "implementation_base_commit": readiness[
                        "implementation_base_commit"
                    ],
                    "error_type": type(error).__name__,
                    "evidence_write_error_type": type(evidence_error).__name__,
                    **dict(evidence_context or {}),
                }
                evidence_bundle = persist_evidence()
            finalize_reserved_result(
                result_path, token, _spent_payload(error, evidence_bundle)
            )
        except FileExistsError:
            # A successful finalization is already permanent.  Never overwrite it
            # merely because a later read/return operation failed.
            pass
        raise


def _run_sealed_adjudication(
    *,
    readiness_path: Path | str,
    registered_readiness_sha256: str,
    result_path: Path | str,
    outcome_acquirer: OutcomeAcquirer,
    quality_starts_builder: QualityStartsBuilder,
    governor_evaluator: GovernorEvaluator,
    fold_scorer: FoldScorer = score_outer_fold,
    reservation_id: str | None = None,
    evidence_dir: Path | str | None = None,
    evidence_path: Path | str | None = None,
    preloaded_sources: Mapping[str, Mapping[str, Any]] | None = None,
    existing_reservation: bool = False,
    evidence_context: Mapping[str, Any] | None = None,
    git_base_commit: str | None = None,
    quality_starts_input_path: Path | str | None = None,
) -> dict[str, Any]:
    """Prevalidate, reserve once, and hold the run lease through finalization."""
    result_path = Path(result_path)
    resolved_evidence_path = (
        Path(evidence_path)
        if evidence_path is not None
        else (
            Path(evidence_dir) / "terminal-evidence.json"
            if evidence_dir is not None
            else result_path.with_name(f"{result_path.stem}-evidence.json")
        )
    )
    readiness, _paths = validate_registered_readiness(
        readiness_path,
        registered_readiness_sha256,
        result_path,
        git_base_commit=git_base_commit,
    )
    if existing_reservation:
        if not reservation_id:
            raise ValueError("existing reservation requires a reservation id")
        token = reservation_id
    else:
        token = reserve_result_path(result_path, reservation_id=reservation_id)
    with sealed_result_run_lease(result_path, token):
        try:
            _cleanup_bound_runtime_json_temps(
                token,
                runtime_paths=(
                    result_path,
                    resolved_evidence_path,
                    ACQUISITION_CHECKPOINT_PATH,
                ),
            )
            return _run_sealed_adjudication_locked(
                readiness_path=readiness_path,
                registered_readiness_sha256=registered_readiness_sha256,
                result_path=result_path,
                outcome_acquirer=outcome_acquirer,
                quality_starts_builder=quality_starts_builder,
                governor_evaluator=governor_evaluator,
                fold_scorer=fold_scorer,
                reservation_id=token,
                evidence_dir=evidence_dir,
                evidence_path=evidence_path,
                preloaded_sources=preloaded_sources,
                existing_reservation=True,
                evidence_context=evidence_context,
                git_base_commit=git_base_commit,
                quality_starts_input_path=quality_starts_input_path,
            )
        except ResumableAcquisitionIncomplete:
            raise
        except Exception as error:
            # The locked core normally consumes its own failures.  This branch
            # seals failures that happen after reservation but before its
            # evidence/finalization handler is installed.
            try:
                marker = _load_mapping(result_path)
            except Exception:
                marker = None
            if marker == {
                "reservation_id": token,
                "status": "reserved_before_outer_outcomes",
            }:
                emergency_evidence = {
                    "artifact": "valucast_plan036_terminal_evidence",
                    "schema_version": 1,
                    "status": "spent_error",
                    "reservation_id": token,
                    "registered_readiness_sha256": registered_readiness_sha256,
                    "implementation_base_commit": readiness[
                        "implementation_base_commit"
                    ],
                    "error_type": type(error).__name__,
                    **dict(evidence_context or {}),
                }
                evidence_bundle = {
                    "terminal_evidence": _write_evidence(
                        resolved_evidence_path, emergency_evidence
                    )
                }
                finalize_reserved_result(
                    result_path,
                    token,
                    _spent_payload(error, evidence_bundle),
                )
            raise


def run_registered_adjudication() -> dict[str, Any]:
    """Execute the single hard-wired Plan 036 registration."""
    prevalidated_execution_commit = _git_text("rev-parse", "HEAD")
    _validate_execution_registration_files(prevalidated_execution_commit)
    registration, registration_sha256 = _load_registered_plan()
    if REGISTERED_READINESS_PATH.is_symlink():
        raise ValueError("registered readiness must not be a symbolic link")
    if not REGISTERED_READINESS_PATH.is_file():
        raise ValueError("registered readiness must be a regular file")
    readiness = _load_mapping(REGISTERED_READINESS_PATH)
    readiness_sha256, base_commit = _validate_execution_registration(
        registration, readiness
    )
    existing_reservation = False
    reservation_id = None
    if REGISTERED_RESULT_PATH.exists():
        marker = _load_mapping(REGISTERED_RESULT_PATH)
        if (
            marker.get("status") != "reserved_before_outer_outcomes"
            or not isinstance(marker.get("reservation_id"), str)
            or not marker["reservation_id"]
        ):
            raise FileExistsError("registered look is already permanently spent")
        existing_reservation = True
        reservation_id = str(marker["reservation_id"])
    execution_commit = _validate_execution_git_topology(
        base_commit=base_commit,
        allow_runtime_paths=existing_reservation,
        reservation_id=reservation_id,
    )
    if execution_commit != prevalidated_execution_commit:
        raise ValueError("execution HEAD changed during registration validation")
    validate_registered_readiness(
        REGISTERED_READINESS_PATH,
        readiness_sha256,
        REGISTERED_RESULT_PATH,
        git_base_commit=base_commit,
    )
    source_blobs = _registered_source_blobs(
        readiness,
        base_commit=base_commit,
        source_keys=EXECUTION_SOURCE_KEYS,
    )
    loaded_sources: dict[str, dict[str, Any]] | None = None

    def load_sources() -> Mapping[str, Mapping[str, Any]]:
        nonlocal loaded_sources
        if loaded_sources is None:
            deferred_keys = [
                key for key in REGISTERED_SOURCE_PATHS if key not in source_blobs
            ]
            deferred_blobs = _registered_source_blobs(
                readiness,
                base_commit=base_commit,
                source_keys=deferred_keys,
            )
            loaded_sources = {
                key: _load_mapping_bytes(
                    content, path=ROOT / REGISTERED_SOURCE_PATHS[key]
                )
                for key, content in {**source_blobs, **deferred_blobs}.items()
            }
        return loaded_sources

    prepared_sources = {
        key: _load_mapping_bytes(
            source_blobs[key], path=ROOT / REGISTERED_SOURCE_PATHS[key]
        )
        for key in EXECUTION_SOURCE_KEYS
    }

    def governor_evaluator(**kwargs: Any) -> Mapping[str, Any]:
        return _current_board_evaluator(load_sources())(**kwargs)

    outcome_acquirer = _make_registered_outcome_acquirer(
        load_sources,
        registration_sha256=registration_sha256,
        readiness_sha256=readiness_sha256,
        current_contract_record=readiness["hashes"]["source_files"][
            "current_prospect_contract"
        ],
    )
    return _run_sealed_adjudication(
        readiness_path=REGISTERED_READINESS_PATH,
        registered_readiness_sha256=readiness_sha256,
        result_path=REGISTERED_RESULT_PATH,
        outcome_acquirer=outcome_acquirer,
        quality_starts_builder=_registered_quality_starts_builder,
        governor_evaluator=governor_evaluator,
        reservation_id=reservation_id,
        evidence_path=REGISTERED_EVIDENCE_PATH,
        preloaded_sources=prepared_sources,
        existing_reservation=existing_reservation,
        evidence_context={
            "registration_sha256": registration_sha256,
            "execution_commit": execution_commit,
            "registration_path": _canonical_repo_relative_path(
                PLAN_REGISTRATION_PATH, label="registration"
            ),
            "acquisition_checkpoint_path": _canonical_repo_relative_path(
                ACQUISITION_CHECKPOINT_PATH,
                label="acquisition checkpoint",
            ),
            "outcome_cutoff_date": REGISTERED_CUTOFF_DATE,
        },
        git_base_commit=base_commit,
        quality_starts_input_path=REGISTERED_EVIDENCE_PATH,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = run_registered_adjudication()
    print(
        "Plan 036 sealed look finalized: "
        f"status={result['status']} result={REGISTERED_RESULT_PATH}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
