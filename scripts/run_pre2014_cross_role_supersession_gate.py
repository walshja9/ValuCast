#!/usr/bin/env python3
"""Run the offline Plan 037 supersession of the spent Plan 036 look.

Plan 036 acquired and committed a complete set of outcome and quality-start
receipts before a deterministic fold-scoring defect consumed its result.  This
runner does not acquire data.  It first reserves a new single-use result path,
then reads the exact committed Plan 036 blobs, reparses every raw receipt,
reconstructs the labeled contract, and reruns the unchanged registered gate.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.extended_history import build_labeled_rows  # noqa: E402
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
from prospects.pre2014_fold_scoring import (  # noqa: E402
    CANDIDATE_MODEL_FLAGS,
    score_outer_fold,
)
from prospects.pre2014_readiness import (  # noqa: E402
    EXPECTED_COHORTS,
    REGISTERED_OUTER_FOLDS,
    REGISTERED_SOURCE_PATHS,
)
from quality.valucast_governor import (  # noqa: E402
    MAX_TOP25_PROSPECT_PITCHER_COUNT,
    MAX_TOP50_PROSPECT_PITCHER_RATE,
)
from scripts.build_stage2_quality_starts import build_quality_starts  # noqa: E402
import scripts.run_pre2014_cross_role_gate as plan036  # noqa: E402


PROTOCOL = "plan_037_pre2014_cross_role_calibration_supersession"
CANDIDATE_SCORE_MODE = "common_target"
OUTCOME_HORIZON_YEARS = 4
MATURE_COHORT_THROUGH = 2021

PLAN036_ARTIFACT_COMMIT = "f06f14599659863bbacf459a1e2fa654529b6c01"
PLAN036_EXECUTION_COMMIT = "568aea2e91bf473ba4491dec394e16afdffd5478"
PLAN036_IMPLEMENTATION_COMMIT = "f7d3304bde6e57a02db4a5c7347ce9fc5e4c0af3"
PLAN036_REGISTRATION_SHA256 = (
    "0dc66697a38226df0e05af9b0e9740638d419972d1a83671accfdbd08cf231dd"
)
PLAN036_READINESS_SHA256 = (
    "12a1023bd1000e54520c2ac445aebbe603c27c69f2bcc0badf3cbbf1fae7e610"
)

PLAN036_RESULT_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_gate.json"
)
PLAN036_EVIDENCE_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_evidence.json"
)
PLAN036_CHECKPOINT_PATH = (
    ROOT
    / "data"
    / "research"
    / "extended_prospect_history"
    / "sealed-acquisition-checkpoint.json"
)
PLAN036_REGISTRATION_PATH = (
    ROOT / "plans" / "036-pre2014-cross-role-calibration-gate.md"
)
PLAN036_READINESS_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_readiness.json"
)

PLAN_REGISTRATION_PATH = (
    ROOT / "plans" / "037-pre2014-cross-role-calibration-supersession.md"
)
REGISTERED_READINESS_PATH = (
    ROOT
    / "data"
    / "validation"
    / "valucast_pre2014_cross_role_supersession_readiness.json"
)
REGISTERED_RESULT_PATH = (
    ROOT
    / "data"
    / "validation"
    / "valucast_pre2014_cross_role_supersession_gate.json"
)
REGISTERED_EVIDENCE_PATH = (
    ROOT
    / "data"
    / "validation"
    / "valucast_pre2014_cross_role_supersession_evidence.json"
)

REGISTRATION_START = "<!-- plan037-registration:start -->"
REGISTRATION_END = "<!-- plan037-registration:end -->"
REGISTRATION_COMMIT_PATHS = frozenset(
    {
        "plans/037-pre2014-cross-role-calibration-supersession.md",
        "plans/README.md",
        "data/validation/valucast_pre2014_cross_role_supersession_readiness.json",
        "tests/test_pre2014_cross_role_supersession_registration.py",
    }
)

PLAN036_OUTCOME_BLOB_RECORDS = (
    {
        "path": "data/validation/valucast_pre2014_cross_role_gate.json",
        "git_blob": "b65f34f0c302e98269c25216fc7c325d79769e0c",
        "binding": "git_blob_only_pre_reservation",
    },
    {
        "path": "data/validation/valucast_pre2014_cross_role_evidence.json",
        "git_blob": "41153259894183f9cbf311e6855c22e9c8f05a61",
        "binding": "git_blob_only_pre_reservation",
    },
    {
        "path": (
            "data/research/extended_prospect_history/"
            "sealed-acquisition-checkpoint.json"
        ),
        "git_blob": "1ed2ff8476333c8ebd193659084e68eb5133f345",
        "binding": "git_blob_only_pre_reservation",
    },
)
PLAN036_REGISTRATION_RECORD = {
    "path": "plans/036-pre2014-cross-role-calibration-gate.md",
    "git_blob": "69a51320771c2a147191d005ff1665156700002c",
    "sha256": "70cfe7948a5bb82bcaaa16308c60eabafcf0d7f72e3d618978232d15155fd862",
}
PLAN036_READINESS_RECORD = {
    "path": "data/validation/valucast_pre2014_cross_role_readiness.json",
    "git_blob": "d9061c337bf1f9fc78d8e997a94071554599afd0",
    "sha256": PLAN036_READINESS_SHA256,
}

EXPECTED_CANDIDATE = {
    "candidate_count": 1,
    "pitcher_investment_feature_mode": "drop_raw_pick_value",
    "rank_model_score_mode": CANDIDATE_SCORE_MODE,
    "calibration": "fold_trained_role_head_isotonic",
    "head_blend": {"outcome": 0.58, "impact": 0.42},
    "governor_thresholds_changed": False,
    "forbidden_substitutions": [
        "raw_pick_value",
        "live_role_quantile",
        "governor_relaxation",
    ],
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
EXPECTED_GATE = {
    "outer_folds": list(REGISTERED_OUTER_FOLDS),
    "bootstrap": EXPECTED_BOOTSTRAP,
    "primary_endpoint": DIRECT_METRIC,
    "thresholds": EXPECTED_THRESHOLDS,
    "governor": EXPECTED_GOVERNOR,
}
EXPECTED_CORRECTIONS = {
    "allowed": [
        "zero_walk_positive_strikeout_k_bb_ordinal_target",
        "statsapi_bare_dash_missing_numeric_sentinel",
    ],
    "row_or_identity_drops": 0,
    "category_drops": 0,
    "threshold_changes": 0,
    "candidate_changes": 0,
}
EXPECTED_READINESS_KEYS = {
    "artifact",
    "schema_version",
    "status",
    "blockers",
    "execution_authorized",
    "look_spent",
    "research_only",
    "claim_authorized",
    "automatic_promotion",
    "implementation_base_commit",
    "supersedes",
    "candidate",
    "outer_folds",
    "bootstrap",
    "primary_endpoint",
    "thresholds",
    "governor",
    "corrections",
    "hashes",
    "result",
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
    "supersedes",
    "candidate",
    "outer_folds",
    "bootstrap",
    "primary_endpoint",
    "thresholds",
    "governor",
    "result_contract",
    "limitations",
}
EXPECTED_IMPLEMENTATION_CHANGE_PATHS = [
    ".gitattributes",
    "prospects/direct_7x7.py",
    "scripts/build_pre2014_cross_role_supersession_readiness.py",
    "scripts/run_pre2014_cross_role_gate.py",
    "scripts/run_pre2014_cross_role_supersession_gate.py",
    "scripts/validate_pre2014_cross_role_supersession_gate.py",
    "tests/test_direct_7x7.py",
    "tests/test_pre2014_cross_role_readiness.py",
    "tests/test_pre2014_cross_role_supersession_readiness.py",
    "tests/test_run_pre2014_cross_role_gate.py",
    "tests/test_run_pre2014_cross_role_supersession_gate.py",
    "tests/test_validate_pre2014_cross_role_supersession_gate.py",
]
EXPECTED_IMPLEMENTATION_CHANGE_STATUSES = {
    ".gitattributes": "M",
    "prospects/direct_7x7.py": "M",
    "scripts/build_pre2014_cross_role_supersession_readiness.py": "A",
    "scripts/run_pre2014_cross_role_gate.py": "M",
    "scripts/run_pre2014_cross_role_supersession_gate.py": "A",
    "scripts/validate_pre2014_cross_role_supersession_gate.py": "A",
    "tests/test_direct_7x7.py": "M",
    "tests/test_pre2014_cross_role_readiness.py": "M",
    "tests/test_pre2014_cross_role_supersession_readiness.py": "A",
    "tests/test_run_pre2014_cross_role_gate.py": "M",
    "tests/test_run_pre2014_cross_role_supersession_gate.py": "A",
    "tests/test_validate_pre2014_cross_role_supersession_gate.py": "A",
}

FoldScorer = Callable[[Mapping[str, Any], int], Mapping[str, Any]]
GovernorEvaluator = Callable[..., Mapping[str, Any]]
BlobLoader = Callable[[str, str], bytes]


def _git_text(*args: str) -> str:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return completed.stdout.strip()


def _git_bytes(*args: str) -> bytes:
    completed = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True
    )
    return completed.stdout


def _sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return _sha256_bytes(encoded)


def _load_mapping(path: Path | str) -> dict[str, Any]:
    candidate = Path(path)
    payload = json.loads(candidate.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON artifact must contain an object: {candidate}")
    return dict(payload)


def _load_mapping_bytes(content: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"committed JSON is malformed: {label}") from exc
    if not isinstance(payload, Mapping):
        raise ValueError(f"committed JSON must contain an object: {label}")
    return dict(payload)


def _canonical_repo_path(path: Path | str, *, label: str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        relative = candidate.resolve().relative_to(ROOT.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} must be inside the repository") from exc
    value = relative.as_posix()
    pure = PurePosixPath(value)
    if (
        not value
        or pure.is_absolute()
        or str(pure) != value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or ":" in value
        or "\\" in value
    ):
        raise ValueError(f"{label} must be a canonical repo-relative path")
    return value


def _same_repo_path(value: Any, expected: Path, *, label: str) -> bool:
    if not isinstance(value, str):
        return False
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or str(pure) != value
        or any(part in {"", ".", ".."} for part in pure.parts)
        or ":" in value
        or "\\" in value
    ):
        return False
    return ROOT.joinpath(*pure.parts).resolve() == expected.resolve()


def _atomic_json(path: Path | str, payload: Mapping[str, Any]) -> None:
    plan036._atomic_json(Path(path), payload)


def _write_evidence(path: Path, payload: Mapping[str, Any]) -> dict[str, str]:
    _atomic_json(path, payload)
    return {
        "path": _canonical_repo_path(path, label="terminal evidence"),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _expected_supersedes() -> dict[str, Any]:
    return {
        "plan036_artifact_commit": PLAN036_ARTIFACT_COMMIT,
        "plan036_execution_commit": PLAN036_EXECUTION_COMMIT,
        "prior_status": "spent_error",
        "prior_error_type": "FoldScoringError",
        "same_look_lineage": True,
        "network_refetch_forbidden": True,
        "outcome_blob_records": copy.deepcopy(list(PLAN036_OUTCOME_BLOB_RECORDS)),
        "plan036_registration": dict(PLAN036_REGISTRATION_RECORD),
        "plan036_readiness": dict(PLAN036_READINESS_RECORD),
    }


def _parse_registration_bytes(content: bytes, *, plan037: bool) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("registration is not UTF-8") from exc
    start_marker = REGISTRATION_START if plan037 else plan036.REGISTRATION_START
    end_marker = REGISTRATION_END if plan037 else plan036.REGISTRATION_END
    label = "Plan 037" if plan037 else "Plan 036"
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise ValueError(f"exactly one {label} registration block is required")
    start = text.index(start_marker) + len(start_marker)
    end = text.index(end_marker, start)
    match = re.fullmatch(
        r"```json\s*(\{.*\})\s*```", text[start:end].strip(), flags=re.DOTALL
    )
    if match is None:
        raise ValueError(f"{label} registration block is malformed")
    payload = json.loads(match.group(1))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} registration must be an object")
    return dict(payload)


def _load_registered_plan() -> tuple[dict[str, Any], str]:
    if PLAN_REGISTRATION_PATH.is_symlink() or not PLAN_REGISTRATION_PATH.is_file():
        raise ValueError("Plan 037 registration must be a regular file")
    registration = _parse_registration_bytes(
        PLAN_REGISTRATION_PATH.read_bytes(), plan037=True
    )
    return registration, _canonical_json_sha256(registration)


def _validate_implementation_records(
    records: Any, *, implementation_commit: str
) -> set[str]:
    if not isinstance(records, list) or not records:
        raise ValueError("readiness implementation file records are missing")
    normalized_paths = []
    for record in records:
        if not isinstance(record, Mapping) or set(record) != {
            "path",
            "sha256",
            "git_blob",
        }:
            raise ValueError("readiness implementation file record is malformed")
        path = record.get("path")
        if not isinstance(path, str) or _canonical_repo_path(path, label="implementation") != path:
            raise ValueError("readiness implementation path is malformed")
        blob = _git_text("rev-parse", f"{implementation_commit}:{path}")
        if blob != record.get("git_blob"):
            raise ValueError(f"implementation Git blob drift: {path}")
        content = _git_bytes("cat-file", "blob", blob)
        if _sha256_bytes(content) != record.get("sha256"):
            raise ValueError(f"implementation SHA-256 drift: {path}")
        normalized_paths.append(path)
    normalized = set(normalized_paths)
    expected = set(plan036.REGISTERED_IMPLEMENTATION_PATHS) | set(
        EXPECTED_IMPLEMENTATION_CHANGE_PATHS
    )
    if (
        normalized_paths != sorted(normalized_paths)
        or len(normalized_paths) != len(normalized)
        or normalized != expected
    ):
        raise ValueError("implementation file record set drift")
    return normalized


def validate_registered_readiness(
    readiness: Mapping[str, Any], *, readiness_sha256: str
) -> str:
    if set(readiness) != EXPECTED_READINESS_KEYS:
        raise ValueError("supersession readiness top-level schema drift")
    base_commit = readiness.get("implementation_base_commit")
    if (
        readiness.get("artifact")
        != "valucast_pre2014_cross_role_supersession_readiness"
        or readiness.get("schema_version") != 1
        or readiness.get("status") != "ready"
        or readiness.get("blockers") != []
        or readiness.get("execution_authorized") is not True
        or readiness.get("look_spent") is not False
        or readiness.get("research_only") is not True
        or readiness.get("claim_authorized") is not False
        or readiness.get("automatic_promotion") is not False
        or not isinstance(base_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", base_commit) is None
        or readiness.get("supersedes") != _expected_supersedes()
        or readiness.get("candidate") != EXPECTED_CANDIDATE
        or readiness.get("outer_folds") != EXPECTED_GATE["outer_folds"]
        or readiness.get("bootstrap") != EXPECTED_GATE["bootstrap"]
        or readiness.get("primary_endpoint") != EXPECTED_GATE["primary_endpoint"]
        or readiness.get("thresholds") != EXPECTED_GATE["thresholds"]
        or readiness.get("governor") != EXPECTED_GATE["governor"]
        or readiness.get("corrections") != EXPECTED_CORRECTIONS
    ):
        raise ValueError("supersession readiness fixed controls drift")
    hashes = readiness.get("hashes")
    if not isinstance(hashes, Mapping) or set(hashes) != {
        "implementation_files",
        "implementation_change_paths",
        "current_prospect_contract",
    }:
        raise ValueError("supersession readiness hash schema drift")
    _validate_implementation_records(
        hashes["implementation_files"], implementation_commit=base_commit
    )
    if hashes.get("implementation_change_paths") != EXPECTED_IMPLEMENTATION_CHANGE_PATHS:
        raise ValueError("supersession implementation change path drift")
    bound_paths = {record["path"] for record in hashes["implementation_files"]}
    if not set(EXPECTED_IMPLEMENTATION_CHANGE_PATHS).issubset(bound_paths):
        raise ValueError("supersession changed path is not implementation-bound")
    current = hashes.get("current_prospect_contract")
    if not isinstance(current, Mapping) or set(current) != {
        "path",
        "git_blob",
        "binding",
    } or (
        current.get("path")
        != REGISTERED_SOURCE_PATHS["current_prospect_contract"]
        or re.fullmatch(r"[0-9a-f]{40}", str(current.get("git_blob") or ""))
        is None
        or current.get("binding") != "git_blob_only_pre_reservation"
    ):
        raise ValueError("current prospect contract binding drift")
    result = readiness.get("result")
    if not isinstance(result, Mapping) or result != {
        "path": _canonical_repo_path(REGISTERED_RESULT_PATH, label="result"),
        "exists": False,
        "unspent": True,
    }:
        raise ValueError("supersession readiness result contract drift")
    if readiness_sha256 != _sha256_bytes(REGISTERED_READINESS_PATH.read_bytes()):
        raise ValueError("supersession readiness SHA-256 drift")
    return str(base_commit)


def _validate_registration(
    registration: Mapping[str, Any],
    readiness: Mapping[str, Any],
    *,
    readiness_sha256: str,
) -> str:
    if set(registration) != EXPECTED_REGISTRATION_KEYS:
        raise ValueError("supersession registration top-level schema drift")
    base_commit = registration.get("implementation_base_commit")
    readiness_ref = registration.get("readiness")
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
        or base_commit != readiness.get("implementation_base_commit")
        or not isinstance(readiness_ref, Mapping)
        or readiness_ref
        != {
            "path": _canonical_repo_path(REGISTERED_READINESS_PATH, label="readiness"),
            "sha256": readiness_sha256,
        }
        or not _same_repo_path(
            registration.get("result_path"), REGISTERED_RESULT_PATH, label="result"
        )
        or registration.get("supersedes") != readiness.get("supersedes")
        or registration.get("candidate") != EXPECTED_CANDIDATE
        or registration.get("outer_folds") != list(REGISTERED_OUTER_FOLDS)
        or registration.get("bootstrap") != EXPECTED_BOOTSTRAP
        or registration.get("primary_endpoint") != DIRECT_METRIC
        or registration.get("thresholds") != EXPECTED_THRESHOLDS
        or registration.get("governor") != EXPECTED_GOVERNOR
    ):
        raise ValueError("supersession registration fixed controls drift")
    if registration.get("result_contract") != {
        "single_use": True,
        "claim_authorized": False,
        "automatic_promotion": False,
        "terminal_evidence_path": _canonical_repo_path(
            REGISTERED_EVIDENCE_PATH, label="evidence"
        ),
        "network_refetch_forbidden": True,
    } or registration.get("limitations") != [
        "cohort-season-completion pseudo-replay"
    ]:
        raise ValueError("supersession result contract drift")
    return str(base_commit)


def _diff_name_status(base: str, head: str) -> dict[str, str]:
    records: dict[str, str] = {}
    output = _git_text("diff", "--name-status", base, head)
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError("sealed topology diff is malformed")
        status, path = parts
        records[path.replace("\\", "/")] = status
    return records


def _direct_parent(commit: str) -> str:
    topology = _git_text("rev-list", "--parents", "-n", "1", commit).split()
    if len(topology) != 2:
        raise ValueError(f"sealed commit is not a direct child: {commit}")
    return topology[1]


def _validate_plan036_identity_only() -> None:
    """Validate only Git identities; never open inherited outcome bytes here."""
    if _direct_parent(PLAN036_ARTIFACT_COMMIT) != PLAN036_EXECUTION_COMMIT:
        raise ValueError("Plan 036 artifact topology drift")
    if _direct_parent(PLAN036_EXECUTION_COMMIT) != PLAN036_IMPLEMENTATION_COMMIT:
        raise ValueError("Plan 036 registration topology drift")
    artifact_diff = _diff_name_status(
        PLAN036_EXECUTION_COMMIT, PLAN036_ARTIFACT_COMMIT
    )
    if artifact_diff != {
        record["path"]: "A" for record in PLAN036_OUTCOME_BLOB_RECORDS
    }:
        raise ValueError("Plan 036 artifact commit contains unexpected paths")
    old_registration_paths = plan036.REGISTRATION_COMMIT_PATHS
    registration_diff = _diff_name_status(
        PLAN036_IMPLEMENTATION_COMMIT, PLAN036_EXECUTION_COMMIT
    )
    if set(registration_diff) != old_registration_paths or any(
        status not in {"A", "M"} for status in registration_diff.values()
    ):
        raise ValueError("Plan 036 registration commit topology drift")
    for record in PLAN036_OUTCOME_BLOB_RECORDS:
        if (
            _git_text(
                "rev-parse", f"{PLAN036_ARTIFACT_COMMIT}:{record['path']}"
            )
            != record["git_blob"]
        ):
            raise ValueError(f"Plan 036 outcome Git identity drift: {record['path']}")
    for record in (PLAN036_REGISTRATION_RECORD, PLAN036_READINESS_RECORD):
        if (
            _git_text(
                "rev-parse", f"{PLAN036_EXECUTION_COMMIT}:{record['path']}"
            )
            != record["git_blob"]
        ):
            raise ValueError(f"Plan 036 metadata Git identity drift: {record['path']}")


def _status_paths_without_sealed_inputs() -> set[str]:
    excluded = [
        record["path"] for record in PLAN036_OUTCOME_BLOB_RECORDS
    ] + [REGISTERED_SOURCE_PATHS["current_prospect_contract"]]
    args = ["status", "--porcelain=v1", "--untracked-files=all", "--", "."]
    args.extend(f":(exclude){path}" for path in excluded)
    output = _git_text(*args)
    return {
        line[3:].strip('"').replace("\\", "/")
        for line in output.splitlines()
        if len(line) >= 4
    }


def _validate_worktree_file(commit: str, path: str) -> None:
    candidate = ROOT / path
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"sealed execution file must be regular: {path}")
    entry = _git_text("ls-tree", commit, "--", path)
    match = re.fullmatch(
        rf"(100644|100755) blob ([0-9a-f]{{40}})\t{re.escape(path)}", entry
    )
    if match is None:
        raise ValueError(f"sealed execution path is not a regular Git blob: {path}")
    worktree_blob = _git_text(
        "hash-object", f"--path={path}", str(candidate.resolve())
    )
    if worktree_blob != match.group(2):
        raise ValueError(f"sealed execution file differs from HEAD: {path}")


def _is_bound_runtime_json_temp(
    repo_path: str, *, target: Path, reservation_id: str
) -> bool:
    candidate = PurePosixPath(repo_path)
    parent = target.parent.relative_to(ROOT).as_posix()
    prefix = f".{target.name}.{reservation_id}."
    name = candidate.name
    middle = name[len(prefix) : -len(".tmp")] if (
        name.startswith(prefix) and name.endswith(".tmp")
    ) else ""
    return (
        candidate.parent.as_posix() == parent
        and name.startswith(prefix)
        and name.endswith(".tmp")
        and bool(middle)
    )


def _validate_execution_topology(
    *,
    implementation_commit: str,
    implementation_paths: set[str],
    implementation_change_paths: set[str],
    existing_reservation: bool = False,
    reservation_id: str | None = None,
) -> str:
    head = _git_text("rev-parse", "HEAD")
    if _direct_parent(head) != implementation_commit:
        raise ValueError("execution HEAD is not the direct Plan 037 registration child")
    if _direct_parent(implementation_commit) != PLAN036_ARTIFACT_COMMIT:
        raise ValueError("Plan 037 implementation does not directly supersede Plan 036")
    implementation_diff = _diff_name_status(
        PLAN036_ARTIFACT_COMMIT, implementation_commit
    )
    if (
        implementation_change_paths != set(EXPECTED_IMPLEMENTATION_CHANGE_PATHS)
        or implementation_diff != EXPECTED_IMPLEMENTATION_CHANGE_STATUSES
    ):
        raise ValueError("Plan 037 implementation commit does not match readiness")
    registration_diff = _diff_name_status(implementation_commit, head)
    expected_status = {
        "plans/037-pre2014-cross-role-calibration-supersession.md": "A",
        "plans/README.md": "M",
        "data/validation/valucast_pre2014_cross_role_supersession_readiness.json": "A",
        "tests/test_pre2014_cross_role_supersession_registration.py": "A",
    }
    if registration_diff != expected_status:
        raise ValueError("Plan 037 registration commit contains unexpected changes")
    dirty = _status_paths_without_sealed_inputs()
    allowed_dirty: set[str] = set()
    if existing_reservation:
        if not reservation_id:
            raise ValueError("existing Plan 037 reservation id is missing")
        result_relative = _canonical_repo_path(
            REGISTERED_RESULT_PATH, label="result"
        )
        evidence_relative = _canonical_repo_path(
            REGISTERED_EVIDENCE_PATH, label="evidence"
        )
        allowed_dirty.update(
            {
                result_relative,
                evidence_relative,
                f"{result_relative}.running",
                f"{result_relative}.finalizing",
            }
        )
        for target in (REGISTERED_RESULT_PATH, REGISTERED_EVIDENCE_PATH):
            for path in dirty:
                if _is_bound_runtime_json_temp(
                    path, target=target, reservation_id=reservation_id
                ):
                    allowed_dirty.add(path)
    if dirty - allowed_dirty:
        raise ValueError("execution worktree is not clean: " + ", ".join(sorted(dirty)))
    for path in sorted(REGISTRATION_COMMIT_PATHS | implementation_paths):
        _validate_worktree_file(head, path)
    _validate_plan036_identity_only()
    return head


def _git_blob_loader(commit: str, path: str) -> bytes:
    return _git_bytes("cat-file", "blob", f"{commit}:{path}")


def _load_plan036_artifacts(
    *,
    result_path: Path | str,
    reservation_id: str,
    supersedes: Mapping[str, Any],
    blob_loader: BlobLoader = _git_blob_loader,
    validate_metadata_hashes: bool = True,
) -> dict[str, Any]:
    """Open inherited blobs only after proving the new look is reserved."""
    marker_path = Path(result_path)
    if not marker_path.is_file() or _load_mapping(marker_path) != {
        "reservation_id": reservation_id,
        "status": "reserved_before_outer_outcomes",
    }:
        raise ValueError("Plan 037 must reserve before inherited outcomes are read")
    if dict(supersedes) != _expected_supersedes():
        raise ValueError("Plan 037 inherited blob registration drift")

    content_by_path: dict[str, bytes] = {}
    receipt: dict[str, dict[str, str]] = {}
    for record in supersedes["outcome_blob_records"]:
        path = str(record["path"])
        content = blob_loader(PLAN036_ARTIFACT_COMMIT, path)
        content_by_path[path] = content
        receipt[path] = {
            "commit": PLAN036_ARTIFACT_COMMIT,
            "git_blob": str(record["git_blob"]),
            "sha256": _sha256_bytes(content),
        }
    for key in ("plan036_registration", "plan036_readiness"):
        record = supersedes[key]
        path = str(record["path"])
        content = blob_loader(PLAN036_EXECUTION_COMMIT, path)
        if validate_metadata_hashes and _sha256_bytes(content) != record["sha256"]:
            raise ValueError(f"inherited metadata SHA-256 drift: {path}")
        content_by_path[path] = content
        receipt[path] = {
            "commit": PLAN036_EXECUTION_COMMIT,
            "git_blob": str(record["git_blob"]),
            "sha256": _sha256_bytes(content),
        }
    return {
        "result": _load_mapping_bytes(
            content_by_path[PLAN036_OUTCOME_BLOB_RECORDS[0]["path"]],
            label="Plan 036 result",
        ),
        "evidence": _load_mapping_bytes(
            content_by_path[PLAN036_OUTCOME_BLOB_RECORDS[1]["path"]],
            label="Plan 036 evidence",
        ),
        "checkpoint": _load_mapping_bytes(
            content_by_path[PLAN036_OUTCOME_BLOB_RECORDS[2]["path"]],
            label="Plan 036 checkpoint",
        ),
        "registration_bytes": content_by_path[PLAN036_REGISTRATION_RECORD["path"]],
        "readiness_bytes": content_by_path[PLAN036_READINESS_RECORD["path"]],
        "blob_receipt": receipt,
    }


def _validate_plan036_artifacts(
    inherited: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    prior_result = inherited.get("result")
    evidence = inherited.get("evidence")
    checkpoint = inherited.get("checkpoint")
    receipt = inherited.get("blob_receipt")
    if not all(isinstance(value, Mapping) for value in (prior_result, evidence, checkpoint, receipt)):
        raise ValueError("inherited Plan 036 artifacts are incomplete")
    evidence_path = PLAN036_OUTCOME_BLOB_RECORDS[1]["path"]
    checkpoint_path = PLAN036_OUTCOME_BLOB_RECORDS[2]["path"]
    if set(prior_result) != {
        "artifact",
        "protocol",
        "status",
        "decision",
        "production_review_authorized",
        "claim_authorized",
        "error_type",
        "evidence_bundle",
        "reservation_id",
    } or (
        prior_result.get("artifact") != "valucast_pre2014_cross_role_gate"
        or prior_result.get("protocol") != plan036.PROTOCOL
        or prior_result.get("status") != "spent_error"
        or prior_result.get("production_review_authorized") is not False
        or prior_result.get("claim_authorized") is not False
        or prior_result.get("error_type") != "FoldScoringError"
        or not isinstance(prior_result.get("reservation_id"), str)
        or not prior_result["reservation_id"]
    ):
        raise ValueError("Plan 036 terminal result is not the registered spent look")
    evidence_record = (prior_result.get("evidence_bundle") or {}).get(
        "terminal_evidence"
    )
    if evidence_record != {
        "path": evidence_path,
        "sha256": receipt[evidence_path]["sha256"],
    }:
        raise ValueError("Plan 036 result does not hash-bind its evidence")
    old_reservation = str(prior_result["reservation_id"])

    old_registration = _parse_registration_bytes(
        inherited["registration_bytes"], plan037=False
    )
    old_registration_sha = _canonical_json_sha256(old_registration)
    old_readiness = _load_mapping_bytes(
        inherited["readiness_bytes"], label="Plan 036 readiness"
    )
    old_readiness_sha = _sha256_bytes(inherited["readiness_bytes"])
    if (
        old_registration_sha != PLAN036_REGISTRATION_SHA256
        or old_readiness_sha != PLAN036_READINESS_SHA256
    ):
        raise ValueError("Plan 036 registration or readiness seal drift")
    readiness_sha, base_commit = plan036._validate_execution_registration(
        old_registration, old_readiness
    )
    if (
        readiness_sha != PLAN036_READINESS_SHA256
        or base_commit != PLAN036_IMPLEMENTATION_COMMIT
    ):
        raise ValueError("Plan 036 registration fixed lineage drift")

    if (
        evidence.get("artifact") != "valucast_plan036_terminal_evidence"
        or evidence.get("schema_version") != 1
        or evidence.get("status") != "spent_error"
        or evidence.get("error_type") != "FoldScoringError"
        or evidence.get("reservation_id") != old_reservation
        or evidence.get("registration_sha256") != old_registration_sha
        or evidence.get("registered_readiness_sha256") != old_readiness_sha
        or evidence.get("execution_commit") != PLAN036_EXECUTION_COMMIT
        or evidence.get("implementation_base_commit")
        != PLAN036_IMPLEMENTATION_COMMIT
        or evidence.get("registration_path")
        != PLAN036_REGISTRATION_RECORD["path"]
        or evidence.get("acquisition_checkpoint_path") != checkpoint_path
        or evidence.get("outcome_horizon_years") != OUTCOME_HORIZON_YEARS
        or evidence.get("outcome_complete_through") != OUTCOME_COMPLETE_THROUGH
        or evidence.get("mature_cohort_through") != MATURE_COHORT_THROUGH
    ):
        raise ValueError("Plan 036 terminal evidence lineage drift")

    if (
        checkpoint.get("artifact")
        != "valucast_plan036_sealed_acquisition_checkpoint"
        or checkpoint.get("schema_version") != 1
        or checkpoint.get("status") != "ready"
        or checkpoint.get("reservation_id") != old_reservation
        or checkpoint.get("registration_sha256") != old_registration_sha
        or checkpoint.get("registered_readiness_sha256") != old_readiness_sha
        or checkpoint.get("remaining") != []
        or not isinstance(checkpoint.get("raw_response_receipts"), Mapping)
        or not isinstance(checkpoint.get("target_identities"), list)
    ):
        raise ValueError("Plan 036 acquisition checkpoint lineage drift")
    raw_receipts = checkpoint["raw_response_receipts"]
    targets = checkpoint["target_identities"]
    coverage = checkpoint.get("coverage")
    if (
        len(targets) != len(set(targets))
        or set(targets) != set(raw_receipts)
        or coverage
        != {
            "target_identity_count": len(targets),
            "receipt_identity_count": len(raw_receipts),
            "resolved_identity_count": len(raw_receipts),
            "remaining_identity_count": 0,
        }
        or any(
            not isinstance(value, Mapping) or value.get("status") != "resolved"
            for value in raw_receipts.values()
        )
    ):
        raise ValueError("Plan 036 outcome receipt coverage is incomplete")
    provider = (evidence.get("canonical_outcomes") or {}).get("provider_receipt")
    if not isinstance(provider, Mapping) or provider.get("checkpoint") != {
        "path": checkpoint_path,
        "sha256": receipt[checkpoint_path]["sha256"],
    } or (
        provider.get("reservation_id") != old_reservation
        or provider.get("target_identity_count") != len(targets)
        or provider.get("receipt_identity_count") != len(targets)
        or provider.get("resolved_identity_count") != len(targets)
        or provider.get("legacy_contract_cache_used") is not False
    ):
        raise ValueError("Plan 036 canonical outcome provider receipt drift")

    return old_registration, old_readiness, dict(checkpoint), old_reservation


def _rebuild_quality_starts(
    *,
    contract: dict[str, Any],
    evidence: Mapping[str, Any],
    checkpoint: Mapping[str, Any],
    old_reservation: str,
) -> tuple[dict[str, Any], dict[str, list[dict]]]:
    quality = evidence.get("quality_starts")
    if not isinstance(quality, Mapping) or set(quality) != {
        "input_contract",
        "input_descriptor",
        "sidecar",
        "provider",
    }:
        raise ValueError("Plan 036 quality-start evidence is incomplete")
    input_payload = plan036._quality_starts_input_payload(contract)
    input_sha = plan036._canonical_payload_sha256(input_payload)
    descriptor = plan036._quality_starts_input_descriptor(
        input_sha, document_path=PLAN036_EVIDENCE_PATH
    )
    if (
        quality.get("input_contract") != input_payload
        or quality.get("input_descriptor") != descriptor
        or quality.get("provider") != plan036.QUALITY_STARTS_SOURCE
    ):
        raise ValueError("Plan 036 quality-start input binding drift")
    state = checkpoint.get("quality_starts_acquisition")
    if not isinstance(state, Mapping) or (
        state.get("reservation_id") != old_reservation
        or state.get("status") != "ready"
        or state.get("input") != descriptor
        or state.get("source") != plan036.QUALITY_STARTS_SOURCE
        or state.get("remaining") != []
        or not isinstance(state.get("target_player_seasons"), list)
        or not isinstance(state.get("raw_response_receipts"), Mapping)
    ):
        raise ValueError("Plan 036 quality-start receipt state drift")
    targets = state["target_player_seasons"]
    receipts = state["raw_response_receipts"]
    coverage = state.get("coverage")
    if (
        len(targets) != len(set(targets))
        or set(targets) != set(receipts)
        or coverage
        != {
            "target_player_season_count": len(targets),
            "receipt_player_season_count": len(receipts),
            "resolved_player_season_count": len(receipts),
            "remaining_player_season_count": 0,
        }
    ):
        raise ValueError("Plan 036 quality-start receipt coverage drift")
    expected_targets = plan036._quality_start_fetch_targets(contract)
    if targets != expected_targets:
        raise ValueError("Plan 036 quality-start target set drift")
    games_by_key = {
        key: plan036._resolved_games_from_qs_receipt(value, key=key)
        for key, value in receipts.items()
    }
    history_rows = []
    for identity, seasons in input_payload["historical_mlb_seasons"].items():
        if not str(identity).endswith("_pitcher"):
            continue
        mlbam_id = int(str(identity).rsplit("_", 1)[0])
        for season in seasons:
            if "gs" in season:
                history_rows.append(
                    {
                        "id": mlbam_id,
                        "season": int(season["year"]),
                        "gs": season["gs"],
                    }
                )
    rebuilt = build_quality_starts(
        input_payload,
        {"rows": history_rows},
        input_path=descriptor["document_path"],
        input_sha256=input_sha,
        fetcher=lambda mlbam_id, _group, season: games_by_key[
            f"{int(mlbam_id)}:{int(season)}"
        ],
        checkpoint_path=None,
        delay=0.0,
    )
    rebuilt["input"] = descriptor
    rebuilt["reservation_id"] = old_reservation
    rebuilt["content_sha256"] = plan036._quality_starts_content_sha256(rebuilt)
    if rebuilt != quality.get("sidecar"):
        raise ValueError("Plan 036 quality-start sidecar does not replay from receipts")
    return plan036._validate_quality_starts(
        contract["historical_mlb_seasons"],
        rebuilt,
        reservation_id=old_reservation,
        expected_input_sha256=input_sha,
        expected_input_path=PLAN036_EVIDENCE_PATH,
    )


def recompute_supersession_payload(
    *,
    inherited_artifacts: Mapping[str, Any],
    source_documents: Mapping[str, Mapping[str, Any]],
    reservation_id: str,
    fold_scorer: FoldScorer = score_outer_fold,
    governor_evaluator: GovernorEvaluator | None = None,
) -> dict[str, Any]:
    """Pure deterministic replay from frozen documents plus injected scorers."""
    _old_registration, old_readiness, checkpoint, old_reservation = (
        _validate_plan036_artifacts(inherited_artifacts)
    )
    evidence = inherited_artifacts["evidence"]
    prepared = source_documents.get("prepared_artifact")
    draft_payload = source_documents.get("draft_facts")
    if not isinstance(prepared, Mapping) or not isinstance(draft_payload, Mapping):
        raise ValueError("registered prepared or draft source is missing")
    rows = [
        row
        for row in plan036._prepared_rows(prepared)
        if int(row["cohort_year"]) <= MATURE_COHORT_THROUGH
    ]
    cohort_by_identity = {
        f"{int(row['mlbam_id'])}_{row['role']}": int(row["cohort_year"])
        for row in rows
    }
    expected_identities = set(cohort_by_identity)
    raw_receipts = checkpoint["raw_response_receipts"]
    if set(raw_receipts) != expected_identities:
        raise ValueError("Plan 036 receipts do not cover the registered mature cohort")
    receipt_seasons = {
        identity: plan036._resolved_seasons_from_provider_receipt(
            raw_receipts[identity], identity=identity
        )
        for identity in sorted(expected_identities)
    }
    canonical_seasons = plan036._outcomes(
        {"outcomes": receipt_seasons}, cohort_by_identity
    )
    canonical = evidence.get("canonical_outcomes")
    if not isinstance(canonical, Mapping) or (
        canonical.get("identity_count") != len(expected_identities)
        or canonical.get("historical_mlb_seasons") != canonical_seasons
        or canonical.get("cohort_horizon")
        != {
            "mature_through": MATURE_COHORT_THROUGH,
            "years_forward": OUTCOME_HORIZON_YEARS,
            "complete_through": OUTCOME_COMPLETE_THROUGH,
        }
    ):
        raise ValueError("Plan 036 canonical outcomes do not replay from raw receipts")

    draft_facts = plan036._draft_facts(draft_payload)
    labeled_rows = build_labeled_rows(
        rows, canonical_seasons, draft_facts, horizon_years=OUTCOME_HORIZON_YEARS
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
        "historical_mlb_seasons": canonical_seasons,
    }
    if len(labeled_rows) != len(rows):
        raise ValueError("reconstructed labeled contract is incomplete")
    sidecar, joined = _rebuild_quality_starts(
        contract=contract,
        evidence=evidence,
        checkpoint=checkpoint,
        old_reservation=old_reservation,
    )
    contract["historical_mlb_seasons"] = joined
    contract["quality_starts"] = sidecar
    if contract != evidence.get("labeled_contract"):
        raise ValueError("Plan 036 labeled contract does not replay from receipts")

    converted_folds = []
    for cohort_year in REGISTERED_OUTER_FOLDS:
        eligible = {
            (str(row["mlbam_id"]), str(row["role"]))
            for row in labeled_rows
            if int(row["cohort_year"]) == cohort_year
        }
        if not eligible:
            raise ValueError(f"registered outer fold is empty: {cohort_year}")
        converted_folds.append(
            plan036.convert_fold_output(
                fold_scorer(contract, cohort_year),
                cohort_year=cohort_year,
                eligible_identities=eligible,
                quality_starts_sha256=sidecar["content_sha256"],
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
    governor = _evaluate_current_governor(
        governor_evaluator=(
            governor_evaluator
            if governor_evaluator is not None
            else plan036._current_board_evaluator(source_documents)
        ),
        reservation_id=reservation_id,
        research_contract=contract,
        quality_starts=sidecar,
        plan036_readiness=old_readiness,
    )
    evaluation = evaluate_pre2014_cross_role_gate(
        converted_folds,
        cohort_years=EXPECTED_COHORTS,
        declared_omissions={2020},
        current_role_shape_governor_passed=governor["passed"],
        bootstrap_seed=BOOTSTRAP_SEED,
        bootstrap_resamples=DEFAULT_BOOTSTRAP_RESAMPLES,
    )
    blob_receipt = inherited_artifacts["blob_receipt"]
    qs_state = checkpoint["quality_starts_acquisition"]
    return {
        "inherited_validation": {
            "status": "validated",
            "plan036_artifact_commit": PLAN036_ARTIFACT_COMMIT,
            "plan036_execution_commit": PLAN036_EXECUTION_COMMIT,
            "plan036_registration_sha256": PLAN036_REGISTRATION_SHA256,
            "plan036_readiness_sha256": PLAN036_READINESS_SHA256,
            "plan036_result_sha256": blob_receipt[
                PLAN036_OUTCOME_BLOB_RECORDS[0]["path"]
            ]["sha256"],
            "plan036_evidence_sha256": blob_receipt[
                PLAN036_OUTCOME_BLOB_RECORDS[1]["path"]
            ]["sha256"],
            "plan036_checkpoint_sha256": blob_receipt[
                PLAN036_OUTCOME_BLOB_RECORDS[2]["path"]
            ]["sha256"],
            "prior_reservation_id": old_reservation,
            "outcome_receipt_identity_count": len(raw_receipts),
            "quality_start_receipt_player_season_count": len(
                qs_state["raw_response_receipts"]
            ),
            "network_refetch_used": False,
        },
        "canonical_outcomes": copy.deepcopy(dict(canonical)),
        "labeled_contract": contract,
        "quality_starts": copy.deepcopy(dict(evidence["quality_starts"])),
        "fold_outputs": converted_folds,
        "current_role_shape_governor": governor,
        "evaluation": evaluation,
    }


replay_supersession_result = recompute_supersession_payload


def _evaluate_current_governor(
    *,
    governor_evaluator: GovernorEvaluator,
    reservation_id: str,
    research_contract: Mapping[str, Any],
    quality_starts: Mapping[str, Any],
    plan036_readiness: Mapping[str, Any],
) -> dict[str, Any]:
    """Run the frozen governor with the exact readiness it was built for."""
    return plan036._validate_governor_receipt(
        governor_evaluator(
            reservation_id=reservation_id,
            research_contract=research_contract,
            quality_starts=quality_starts,
            readiness=plan036_readiness,
        ),
        reservation_id=reservation_id,
    )


def _load_source_documents(
    inherited: Mapping[str, Any],
    *,
    registered_current_contract: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    old_readiness = _load_mapping_bytes(
        inherited["readiness_bytes"], label="Plan 036 readiness"
    )
    old_current = (old_readiness.get("hashes") or {}).get("source_files", {}).get(
        "current_prospect_contract"
    )
    if registered_current_contract != old_current:
        raise ValueError("Plan 037 current contract is not the Plan 036 frozen blob")
    source_blobs = plan036._registered_source_blobs(
        old_readiness,
        base_commit=PLAN036_IMPLEMENTATION_COMMIT,
        source_keys=list(REGISTERED_SOURCE_PATHS),
    )
    return {
        key: plan036._load_mapping_bytes(
            content, path=ROOT / REGISTERED_SOURCE_PATHS[key]
        )
        for key, content in source_blobs.items()
    }


def _spent_payload(
    error: BaseException,
    *,
    reservation_id: str,
    registered_readiness_sha256: str,
    registration_sha256: str,
    supersedes: Mapping[str, Any],
    evidence_bundle: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "artifact": "valucast_pre2014_cross_role_supersession_gate",
        "schema_version": 1,
        "protocol": PROTOCOL,
        "status": "spent_error",
        "decision": "production_review_not_authorized",
        "production_review_authorized": False,
        "claim_authorized": False,
        "error_type": type(error).__name__,
        "registered_readiness_sha256": registered_readiness_sha256,
        "registration_sha256": registration_sha256,
        "supersedes": copy.deepcopy(dict(supersedes)),
        "evidence_bundle": dict(evidence_bundle),
        "reservation_id": reservation_id,
    }


def _run_reserved_supersession(
    *,
    result_path: Path | str,
    evidence_path: Path | str,
    registered_readiness_sha256: str,
    registration_sha256: str,
    implementation_base_commit: str,
    execution_commit: str,
    supersedes: Mapping[str, Any],
    inherited_loader: Callable[..., Mapping[str, Any]],
    replay_builder: Callable[..., Mapping[str, Any]],
    reservation_id: str | None = None,
    existing_reservation: bool = False,
) -> dict[str, Any]:
    """Reserve, load inherited outcomes, replay, and permanently finalize."""
    result_path = Path(result_path)
    evidence_path = Path(evidence_path)
    if existing_reservation:
        if not reservation_id or not result_path.is_file() or _load_mapping(
            result_path
        ) != {
            "reservation_id": reservation_id,
            "status": "reserved_before_outer_outcomes",
        }:
            raise ValueError("existing Plan 037 reservation marker drift")
        token = reservation_id
    else:
        token = reserve_result_path(result_path, reservation_id=reservation_id)
    if re.fullmatch(r"[0-9a-f]{40}", execution_commit) is None:
        raise ValueError("Plan 037 execution commit must be a Git object id")
    evidence_lineage: dict[str, Any] = {
        "artifact": "valucast_plan037_supersession_terminal_evidence",
        "schema_version": 1,
        "reservation_id": token,
        "registered_readiness_sha256": registered_readiness_sha256,
        "registration_sha256": registration_sha256,
        "implementation_base_commit": implementation_base_commit,
        "execution_commit": execution_commit,
        "supersedes": copy.deepcopy(dict(supersedes)),
        "network_refetch_used": False,
    }
    evidence: dict[str, Any] = {**evidence_lineage, "status": "in_progress"}
    evidence_bundle: dict[str, Any] = {}

    def persist() -> dict[str, Any]:
        return {"terminal_evidence": _write_evidence(evidence_path, evidence)}

    with sealed_result_run_lease(result_path, token):
        try:
            plan036._cleanup_bound_runtime_json_temps(
                token, runtime_paths=(result_path, evidence_path)
            )
            inherited = inherited_loader(
                result_path=result_path, reservation_id=token
            )
            evidence_bundle = persist()
            replay = replay_builder(
                inherited_artifacts=inherited, reservation_id=token
            )
            required = {
                "inherited_validation",
                "canonical_outcomes",
                "labeled_contract",
                "quality_starts",
                "fold_outputs",
                "current_role_shape_governor",
                "evaluation",
            }
            if not isinstance(replay, Mapping) or set(replay) != required:
                raise ValueError("supersession replay payload schema drift")
            evaluation = replay["evaluation"]
            if not isinstance(evaluation, Mapping):
                raise ValueError("supersession evaluation is malformed")
            authorized = evaluation.get("production_review_authorized") is True
            sidecar = replay["quality_starts"].get("sidecar")
            if not isinstance(sidecar, Mapping) or not isinstance(
                sidecar.get("content_sha256"), str
            ):
                raise ValueError("supersession quality-start hash is missing")
            evidence.update(
                {
                    "inherited_validation": copy.deepcopy(
                        replay["inherited_validation"]
                    ),
                    "fold_outputs": copy.deepcopy(replay["fold_outputs"]),
                    "current_role_shape_governor": copy.deepcopy(
                        replay["current_role_shape_governor"]
                    ),
                    "evaluation": copy.deepcopy(dict(evaluation)),
                    "quality_starts_sha256": sidecar["content_sha256"],
                }
            )
            evidence["status"] = "passed" if authorized else "failed"
            evidence_bundle = persist()
            payload = {
                "artifact": "valucast_pre2014_cross_role_supersession_gate",
                "schema_version": 1,
                "protocol": PROTOCOL,
                "status": "passed" if authorized else "failed",
                "decision": evaluation.get("decision"),
                "production_review_authorized": authorized,
                "claim_authorized": False,
                "registered_readiness_sha256": registered_readiness_sha256,
                "registration_sha256": registration_sha256,
                "supersedes": copy.deepcopy(dict(supersedes)),
                "candidate": {
                    "model_flags": dict(CANDIDATE_MODEL_FLAGS),
                    "model_score_mode": CANDIDATE_SCORE_MODE,
                },
                "outer_folds": list(REGISTERED_OUTER_FOLDS),
                "quality_starts_sha256": sidecar["content_sha256"],
                "current_role_shape_governor": replay[
                    "current_role_shape_governor"
                ],
                "fold_outputs": replay["fold_outputs"],
                "evaluation": evaluation,
                "evidence_bundle": evidence_bundle,
            }
            finalize_reserved_result(result_path, token, payload)
            return {
                **json.loads(
                    json.dumps(payload, sort_keys=True, allow_nan=False)
                ),
                "reservation_id": token,
            }
        except Exception as error:
            # A late write/finalization failure may occur after success-only
            # fields were assembled.  Rebuild the fail-closed receipt from the
            # immutable lineage instead of carrying those fields into the
            # exact spent-evidence schema.
            evidence = {
                **copy.deepcopy(evidence_lineage),
                "status": "spent_error",
                "error_type": type(error).__name__,
            }
            try:
                evidence_bundle = persist()
                finalize_reserved_result(
                    result_path,
                    token,
                    _spent_payload(
                        error,
                        reservation_id=token,
                        registered_readiness_sha256=registered_readiness_sha256,
                        registration_sha256=registration_sha256,
                        supersedes=supersedes,
                        evidence_bundle=evidence_bundle,
                    ),
                )
            except FileExistsError:
                pass
            raise


def run_registered_adjudication() -> dict[str, Any]:
    """Execute the single hard-wired Plan 037 offline supersession."""
    existing_reservation = False
    reservation_id = None
    if REGISTERED_RESULT_PATH.exists():
        marker = _load_mapping(REGISTERED_RESULT_PATH)
        if (
            set(marker) != {"reservation_id", "status"}
            or marker.get("status") != "reserved_before_outer_outcomes"
            or not isinstance(marker.get("reservation_id"), str)
            or not marker["reservation_id"]
        ):
            raise FileExistsError("registered Plan 037 look is already permanently spent")
        existing_reservation = True
        reservation_id = str(marker["reservation_id"])
    registration, registration_sha = _load_registered_plan()
    if REGISTERED_READINESS_PATH.is_symlink() or not REGISTERED_READINESS_PATH.is_file():
        raise ValueError("Plan 037 readiness must be a regular file")
    readiness = _load_mapping(REGISTERED_READINESS_PATH)
    readiness_sha = _sha256_bytes(REGISTERED_READINESS_PATH.read_bytes())
    base_commit = validate_registered_readiness(
        readiness, readiness_sha256=readiness_sha
    )
    if _validate_registration(
        registration, readiness, readiness_sha256=readiness_sha
    ) != base_commit:
        raise ValueError("Plan 037 implementation binding drift")
    implementation_paths = {
        str(record["path"])
        for record in readiness["hashes"]["implementation_files"]
    }
    execution_commit = _validate_execution_topology(
        implementation_commit=base_commit,
        implementation_paths=implementation_paths,
        implementation_change_paths=set(
            readiness["hashes"]["implementation_change_paths"]
        ),
        existing_reservation=existing_reservation,
        reservation_id=reservation_id,
    )
    supersedes = readiness["supersedes"]

    def inherited_loader(**kwargs: Any) -> Mapping[str, Any]:
        return _load_plan036_artifacts(
            supersedes=supersedes,
            **kwargs,
        )

    def replay_builder(
        *, inherited_artifacts: Mapping[str, Any], reservation_id: str
    ) -> Mapping[str, Any]:
        sources = _load_source_documents(
            inherited_artifacts,
            registered_current_contract=readiness["hashes"][
                "current_prospect_contract"
            ],
        )
        return recompute_supersession_payload(
            inherited_artifacts=inherited_artifacts,
            source_documents=sources,
            reservation_id=reservation_id,
        )

    return _run_reserved_supersession(
        result_path=REGISTERED_RESULT_PATH,
        evidence_path=REGISTERED_EVIDENCE_PATH,
        registered_readiness_sha256=readiness_sha,
        registration_sha256=registration_sha,
        implementation_base_commit=base_commit,
        execution_commit=execution_commit,
        supersedes=supersedes,
        inherited_loader=inherited_loader,
        replay_builder=replay_builder,
        reservation_id=reservation_id,
        existing_reservation=existing_reservation,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    result = run_registered_adjudication()
    print(
        "Plan 037 offline supersession finalized: "
        f"status={result['status']} result={REGISTERED_RESULT_PATH}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
