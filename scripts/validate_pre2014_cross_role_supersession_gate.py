#!/usr/bin/env python3
"""Read-only validator for the sealed Plan 037 supersession adjudication.

The supersession spends no new outcome look.  It must reuse the exact three
Plan 036 terminal blobs committed at the frozen artifact commit and may change
only the registered implementation used to score those inherited facts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
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
    evaluate_pre2014_cross_role_gate,
)
from prospects.pre2014_readiness import (  # noqa: E402
    EXPECTED_COHORTS,
    REGISTERED_OUTER_FOLDS,
)
from quality.valucast_governor import (  # noqa: E402
    MAX_TOP25_PROSPECT_PITCHER_COUNT,
    MAX_TOP50_PROSPECT_PITCHER_RATE,
)
from scripts.build_pre2014_cross_role_supersession_readiness import (  # noqa: E402
    PLAN037_IMPLEMENTATION_CHANGE_STATUSES,
    PLAN037_IMPLEMENTATION_PATHS,
)
import scripts.run_pre2014_cross_role_supersession_gate as runner  # noqa: E402


PROTOCOL = "plan_037_pre2014_cross_role_calibration_supersession"
PLAN036_ARTIFACT_COMMIT = "f06f14599659863bbacf459a1e2fa654529b6c01"
PLAN036_EXECUTION_COMMIT = "568aea2e91bf473ba4491dec394e16afdffd5478"
REGISTRATION_START = "<!-- plan037-registration:start -->"
REGISTRATION_END = "<!-- plan037-registration:end -->"
REGISTERED_PLAN_REPO_PATH = (
    "plans/037-pre2014-cross-role-calibration-supersession.md"
)
REGISTERED_READINESS_REPO_PATH = (
    "data/validation/valucast_pre2014_cross_role_supersession_readiness.json"
)
REGISTERED_RESULT_REPO_PATH = (
    "data/validation/valucast_pre2014_cross_role_supersession_gate.json"
)
REGISTERED_EVIDENCE_REPO_PATH = (
    "data/validation/valucast_pre2014_cross_role_supersession_evidence.json"
)
PLAN036_RESULT_REPO_PATH = "data/validation/valucast_pre2014_cross_role_gate.json"
PLAN036_EVIDENCE_REPO_PATH = (
    "data/validation/valucast_pre2014_cross_role_evidence.json"
)
PLAN036_CHECKPOINT_REPO_PATH = (
    "data/research/extended_prospect_history/sealed-acquisition-checkpoint.json"
)
PLAN036_OUTCOME_PATHS = (
    PLAN036_RESULT_REPO_PATH,
    PLAN036_EVIDENCE_REPO_PATH,
    PLAN036_CHECKPOINT_REPO_PATH,
)
CANDIDATE_SCORE_MODE = "common_target"
GOVERNOR_CHECK_ID = "prospect_top_board_role_shape"

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
    "check_id": GOVERNOR_CHECK_ID,
    "max_top25_pitcher_count": MAX_TOP25_PROSPECT_PITCHER_COUNT,
    "max_top50_pitcher_rate": MAX_TOP50_PROSPECT_PITCHER_RATE,
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
REGISTRATION_COMMIT_PATHS = {
    REGISTERED_PLAN_REPO_PATH: "A",
    "plans/README.md": "M",
    REGISTERED_READINESS_REPO_PATH: "A",
    "tests/test_pre2014_cross_role_supersession_registration.py": "A",
}
RUNTIME_COMMIT_PATHS = {
    REGISTERED_RESULT_REPO_PATH: "A",
    REGISTERED_EVIDENCE_REPO_PATH: "A",
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


class ResultValidationError(ValueError):
    """Raised when a Plan 037 seal or terminal receipt drifts."""


def _reject_constant(value: str) -> None:
    raise ResultValidationError(f"non-finite JSON constant is forbidden: {value}")


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResultValidationError("result contains non-canonical values") from exc


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value)
    )


def _is_git_oid(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{40}", value)
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


def _same_path(left: Path | str, right: Path | str) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(
        os.path.abspath(right)
    )


def _require_exact_keys(value: Any, expected: set[str], *, label: str) -> Mapping:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ResultValidationError(f"{label} schema drift")
    return value


def _validate_fixed_gate(registration: Mapping[str, Any]) -> None:
    if registration.get("candidate") != EXPECTED_CANDIDATE:
        raise ResultValidationError("candidate drift")
    if registration.get("outer_folds") != list(REGISTERED_OUTER_FOLDS):
        raise ResultValidationError("outer folds drift")
    if registration.get("bootstrap") != EXPECTED_BOOTSTRAP:
        raise ResultValidationError("bootstrap drift")
    if registration.get("primary_endpoint") != DIRECT_METRIC:
        raise ResultValidationError("primary endpoint drift")
    if registration.get("thresholds") != EXPECTED_THRESHOLDS:
        raise ResultValidationError("thresholds drift")
    if registration.get("governor") != EXPECTED_GOVERNOR:
        raise ResultValidationError("governor thresholds drift")


def _validate_supersession(supersedes: Any) -> None:
    supersedes = _require_exact_keys(
        supersedes,
        {
            "plan036_artifact_commit",
            "plan036_execution_commit",
            "prior_status",
            "prior_error_type",
            "same_look_lineage",
            "network_refetch_forbidden",
            "outcome_blob_records",
            "plan036_registration",
            "plan036_readiness",
        },
        label="supersession",
    )
    if (
        supersedes.get("plan036_artifact_commit") != PLAN036_ARTIFACT_COMMIT
        or supersedes.get("plan036_execution_commit") != PLAN036_EXECUTION_COMMIT
        or supersedes.get("prior_status") != "spent_error"
        or supersedes.get("prior_error_type") != "FoldScoringError"
        or supersedes.get("same_look_lineage") is not True
        or supersedes.get("network_refetch_forbidden") is not True
    ):
        raise ResultValidationError("supersession controls drift")
    records = supersedes.get("outcome_blob_records")
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
        or len(records) != len(PLAN036_OUTCOME_PATHS)
    ):
        raise ResultValidationError("outcome blob path drift")
    paths = []
    for index, (record, expected_path) in enumerate(
        zip(records, PLAN036_OUTCOME_PATHS, strict=True)
    ):
        record = _require_exact_keys(
            record, {"path", "git_blob", "binding"}, label="outcome blob record"
        )
        path = _registration_path(
            record.get("path"), label=f"outcome_blob_records[{index}]"
        )
        paths.append(os.path.normcase(os.path.abspath(path)))
        if (
            not _same_path(path, ROOT / expected_path)
            or not _is_git_oid(record.get("git_blob"))
            or record.get("binding") != "git_blob_only_pre_reservation"
        ):
            raise ResultValidationError("outcome blob path drift")
    if len(set(paths)) != len(paths):
        raise ResultValidationError("outcome blob path drift")
    if _canonical(supersedes) != _canonical(runner._expected_supersedes()):
        raise ResultValidationError("supersession artifact seals drift")


def _validate_content_record(record: Any, *, expected_path: str, label: str) -> None:
    record = _require_exact_keys(
        record, {"path", "git_blob", "sha256"}, label=label
    )
    if (
        not _same_path(
            _registration_path(record.get("path"), label=label),
            ROOT / expected_path,
        )
        or not _is_git_oid(record.get("git_blob"))
        or not _is_sha256(record.get("sha256"))
    ):
        raise ResultValidationError(f"{label} drift")


def _validate_readiness_contract(
    readiness: Mapping[str, Any], *, implementation_paths: Sequence[str]
) -> None:
    expected_keys = {
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
    _require_exact_keys(readiness, expected_keys, label="readiness")
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
        or not _is_git_oid(readiness.get("implementation_base_commit"))
    ):
        raise ResultValidationError("readiness fixed controls drift")
    _validate_fixed_gate(readiness)
    _validate_supersession(readiness.get("supersedes"))
    supersedes = readiness["supersedes"]
    _validate_content_record(
        supersedes.get("plan036_registration"),
        expected_path="plans/036-pre2014-cross-role-calibration-gate.md",
        label="Plan 036 registration record",
    )
    _validate_content_record(
        supersedes.get("plan036_readiness"),
        expected_path="data/validation/valucast_pre2014_cross_role_readiness.json",
        label="Plan 036 readiness record",
    )
    if readiness.get("corrections") != EXPECTED_CORRECTIONS:
        raise ResultValidationError("correction contract drift")
    hashes = _require_exact_keys(
        readiness.get("hashes"),
        {
            "implementation_files",
            "implementation_change_paths",
            "current_prospect_contract",
        },
        label="readiness hashes",
    )
    if hashes.get("implementation_change_paths") != EXPECTED_IMPLEMENTATION_CHANGE_PATHS:
        raise ResultValidationError("implementation change paths drift")
    records = hashes.get("implementation_files")
    if (
        not isinstance(records, Sequence)
        or isinstance(records, (str, bytes))
        or len(records) != len(implementation_paths)
    ):
        raise ResultValidationError("implementation hash record drift")
    observed_paths = [
        record.get("path") if isinstance(record, Mapping) else None
        for record in records
    ]
    if observed_paths != sorted(implementation_paths):
        raise ResultValidationError("implementation hash record order drift")
    for record, expected_path in zip(records, implementation_paths, strict=True):
        try:
            _validate_content_record(
                record,
                expected_path=expected_path,
                label="implementation hash record",
            )
        except ResultValidationError as exc:
            raise ResultValidationError("implementation hash record drift") from exc
    if set(implementation_paths) != set(PLAN037_IMPLEMENTATION_PATHS):
        raise ResultValidationError("implementation dependency set drift")
    if not set(EXPECTED_IMPLEMENTATION_CHANGE_PATHS).issubset(implementation_paths):
        raise ResultValidationError("implementation change paths are not all bound")
    current = _require_exact_keys(
        hashes.get("current_prospect_contract"),
        {"path", "git_blob", "binding"},
        label="current prospect contract",
    )
    if (
        not _same_path(
            _registration_path(
                current.get("path"), label="current prospect contract"
            ),
            ROOT / "data/prospects/prospect_model_inputs.json",
        )
        or not _is_git_oid(current.get("git_blob"))
        or current.get("binding") != "git_blob_only_pre_reservation"
    ):
        raise ResultValidationError("current prospect contract drift")
    result = _require_exact_keys(
        readiness.get("result"), {"path", "exists", "unspent"}, label="result"
    )
    if (
        not _same_path(
            _registration_path(result.get("path"), label="readiness result"),
            ROOT / REGISTERED_RESULT_REPO_PATH,
        )
        or result.get("exists") is not False
        or result.get("unspent") is not True
    ):
        raise ResultValidationError("readiness result contract drift")


def _validate_registration_contract(
    registration: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any],
    readiness_sha256: str,
) -> None:
    expected_keys = {
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
    _require_exact_keys(registration, expected_keys, label="registration")
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
        or registration.get("implementation_base_commit")
        != readiness.get("implementation_base_commit")
    ):
        raise ResultValidationError("registration fixed controls drift")
    readiness_ref = _require_exact_keys(
        registration.get("readiness"), {"path", "sha256"}, label="readiness ref"
    )
    if (
        not _same_path(
            _registration_path(readiness_ref.get("path"), label="readiness ref"),
            ROOT / REGISTERED_READINESS_REPO_PATH,
        )
        or readiness_ref.get("sha256") != readiness_sha256
        or not _same_path(
            _registration_path(registration.get("result_path"), label="result"),
            ROOT / REGISTERED_RESULT_REPO_PATH,
        )
    ):
        raise ResultValidationError("registration path/hash drift")
    _validate_fixed_gate(registration)
    _validate_supersession(registration.get("supersedes"))
    if _canonical(registration.get("supersedes")) != _canonical(
        readiness.get("supersedes")
    ):
        raise ResultValidationError("registration/readiness supersession drift")
    contract = _require_exact_keys(
        registration.get("result_contract"),
        {
            "single_use",
            "claim_authorized",
            "automatic_promotion",
            "terminal_evidence_path",
            "network_refetch_forbidden",
        },
        label="result contract",
    )
    if (
        contract.get("single_use") is not True
        or contract.get("claim_authorized") is not False
        or contract.get("automatic_promotion") is not False
        or contract.get("network_refetch_forbidden") is not True
        or contract.get("terminal_evidence_path")
        != REGISTERED_EVIDENCE_REPO_PATH
        or registration.get("limitations")
        != ["cohort-season-completion pseudo-replay"]
    ):
        raise ResultValidationError("result contract drift")


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


def _name_status(base: str, head: str) -> dict[str, str]:
    changed: dict[str, str] = {}
    for line in _git_text("diff", "--name-status", base, head).splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or parts[1] in changed:
            raise ResultValidationError("registered Git diff is malformed")
        changed[parts[1].replace("\\", "/")] = parts[0]
    return changed


def _worktree_status() -> dict[str, str]:
    changed: dict[str, str] = {}
    for line in _git_text(
        "status", "--porcelain=v1", "--untracked-files=all", "--", "."
    ).splitlines():
        if len(line) < 4 or " -> " in line[3:]:
            raise ResultValidationError("registered Git status is malformed")
        path = line[3:].strip('"').replace("\\", "/")
        if path in changed:
            raise ResultValidationError("registered Git status repeats a path")
        changed[path] = line[:2]
    return changed


def _validate_commit_blob(*, commit: str, repo_path: str) -> None:
    entry = _git_text("ls-tree", commit, "--", repo_path)
    if re.fullmatch(
        rf"(100644|100755) blob [0-9a-f]{{40}}\t{re.escape(repo_path)}", entry
    ) is None:
        raise ResultValidationError(f"sealed path is not a regular blob: {repo_path}")


def _parents(commit: str) -> list[str]:
    return _git_text("rev-list", "--parents", "-n", "1", commit).split()


def _validate_git_topology(
    *,
    implementation_commit: str,
    execution_commit: str,
    head: str,
    result_status: str,
) -> str:
    if _parents(implementation_commit) != [
        implementation_commit,
        PLAN036_ARTIFACT_COMMIT,
    ]:
        raise ResultValidationError(
            "Plan 037 implementation is not the direct child of Plan 036 S"
        )
    if _parents(execution_commit) != [execution_commit, implementation_commit]:
        raise ResultValidationError("execution commit is not the direct registration child")
    if _name_status(implementation_commit, execution_commit) != REGISTRATION_COMMIT_PATHS:
        raise ResultValidationError("execution commit registration diff drift")
    for repo_path in REGISTRATION_COMMIT_PATHS:
        _validate_commit_blob(commit=execution_commit, repo_path=repo_path)

    dirty = _worktree_status()
    if head == execution_commit:
        if set(dirty) != set(RUNTIME_COMMIT_PATHS) or any(
            status != "??" for status in dirty.values()
        ):
            raise ResultValidationError("runtime result worktree topology drift")
        return "execution_worktree"
    if _parents(head) != [head, execution_commit]:
        raise ResultValidationError("terminal commit is not the direct execution child")
    if _name_status(execution_commit, head) != RUNTIME_COMMIT_PATHS:
        raise ResultValidationError("terminal commit runtime diff drift")
    for repo_path in RUNTIME_COMMIT_PATHS:
        _validate_commit_blob(commit=head, repo_path=repo_path)
    if dirty:
        raise ResultValidationError("terminal result worktree is not clean")
    if result_status not in {"passed", "failed", "spent_error"}:
        raise ResultValidationError("terminal result status drift")
    return "artifact_commit"


def _validate_runtime_record(
    record: Any, *, expected_path: str
) -> tuple[Path, str]:
    record = _require_exact_keys(record, {"path", "sha256"}, label="runtime record")
    path = _registration_path(record.get("path"), label="runtime record")
    if not _same_path(path, ROOT / expected_path):
        raise ResultValidationError("runtime record path drift")
    sha256 = record.get("sha256")
    if not _is_sha256(sha256):
        raise ResultValidationError("runtime record hash is invalid")
    if path.is_symlink():
        raise ResultValidationError("runtime record must not be a symbolic link")
    if not path.is_file():
        raise ResultValidationError("runtime record must be a regular file")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ResultValidationError("runtime record is unreadable") from exc
    if actual != sha256:
        raise ResultValidationError("runtime record content hash drift")
    return path, str(sha256)


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_constant
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResultValidationError(f"{label} is not valid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ResultValidationError(f"{label} must be a JSON object")
    return dict(payload)


def _load_registration(path: Path) -> dict[str, Any]:
    try:
        content = path.read_bytes()
        registration = runner._parse_registration_bytes(content, plan037=True)
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise ResultValidationError("Plan 037 registration is invalid") from exc
    return dict(registration)


def _validate_frozen_plan036_git_seals(supersedes: Mapping[str, Any]) -> None:
    if _parents(PLAN036_ARTIFACT_COMMIT) != [
        PLAN036_ARTIFACT_COMMIT,
        PLAN036_EXECUTION_COMMIT,
    ]:
        raise ResultValidationError("Plan 036 artifact topology drift")
    expected = {path: "A" for path in PLAN036_OUTCOME_PATHS}
    if _name_status(PLAN036_EXECUTION_COMMIT, PLAN036_ARTIFACT_COMMIT) != expected:
        raise ResultValidationError("Plan 036 artifact diff drift")
    for record in supersedes["outcome_blob_records"]:
        repo_path = str(record["path"])
        entry = _git_text("ls-tree", PLAN036_ARTIFACT_COMMIT, "--", repo_path)
        match = re.fullmatch(
            rf"100644 blob ([0-9a-f]{{40}})\t{re.escape(repo_path)}", entry
        )
        if match is None or match.group(1) != record["git_blob"]:
            raise ResultValidationError("Plan 036 outcome blob seal drift")
    for key in ("plan036_registration", "plan036_readiness"):
        record = supersedes[key]
        repo_path = str(record["path"])
        entry = _git_text("ls-tree", PLAN036_EXECUTION_COMMIT, "--", repo_path)
        match = re.fullmatch(
            rf"100644 blob ([0-9a-f]{{40}})\t{re.escape(repo_path)}", entry
        )
        if match is None or match.group(1) != record["git_blob"]:
            raise ResultValidationError("Plan 036 metadata blob seal drift")
        content = subprocess.run(
            ["git", "cat-file", "blob", f"{PLAN036_EXECUTION_COMMIT}:{repo_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise ResultValidationError("Plan 036 metadata SHA-256 drift")


def _validate_implementation_git_seals(
    readiness: Mapping[str, Any], *, implementation_commit: str
) -> None:
    hashes = readiness["hashes"]
    records = hashes["implementation_files"]
    for record in records:
        repo_path = str(record["path"])
        entry = _git_text("ls-tree", implementation_commit, "--", repo_path)
        match = re.fullmatch(
            rf"(100644|100755) blob ([0-9a-f]{{40}})\t{re.escape(repo_path)}",
            entry,
        )
        if match is None or match.group(2) != record["git_blob"]:
            raise ResultValidationError(f"implementation Git blob drift: {repo_path}")
        content = subprocess.run(
            ["git", "cat-file", "blob", f"{implementation_commit}:{repo_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        if hashlib.sha256(content).hexdigest() != record["sha256"]:
            raise ResultValidationError(f"implementation SHA-256 drift: {repo_path}")
    changed = _name_status(PLAN036_ARTIFACT_COMMIT, implementation_commit)
    if changed != PLAN037_IMPLEMENTATION_CHANGE_STATUSES:
        raise ResultValidationError("Plan 037 implementation diff drift")
    current = readiness["hashes"]["current_prospect_contract"]
    current_path = str(current["path"])
    entry = _git_text("ls-tree", implementation_commit, "--", current_path)
    match = re.fullmatch(
        rf"100644 blob ([0-9a-f]{{40}})\t{re.escape(current_path)}", entry
    )
    if match is None or match.group(1) != current["git_blob"]:
        raise ResultValidationError("current prospect contract Git blob drift")


def _recompute_from_frozen_blobs(
    *, readiness: Mapping[str, Any], reservation_id: str
) -> Mapping[str, Any]:
    supersedes = readiness["supersedes"]
    content: dict[str, bytes] = {}
    receipt: dict[str, dict[str, str]] = {}
    for record in supersedes["outcome_blob_records"]:
        repo_path = str(record["path"])
        raw = subprocess.run(
            ["git", "cat-file", "blob", f"{PLAN036_ARTIFACT_COMMIT}:{repo_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        content[repo_path] = raw
        receipt[repo_path] = {
            "commit": PLAN036_ARTIFACT_COMMIT,
            "git_blob": str(record["git_blob"]),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    for key in ("plan036_registration", "plan036_readiness"):
        record = supersedes[key]
        repo_path = str(record["path"])
        raw = subprocess.run(
            ["git", "cat-file", "blob", f"{PLAN036_EXECUTION_COMMIT}:{repo_path}"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        ).stdout
        content[repo_path] = raw
        receipt[repo_path] = {
            "commit": PLAN036_EXECUTION_COMMIT,
            "git_blob": str(record["git_blob"]),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    inherited = {
        "result": runner._load_mapping_bytes(
            content[PLAN036_RESULT_REPO_PATH], label="Plan 036 result"
        ),
        "evidence": runner._load_mapping_bytes(
            content[PLAN036_EVIDENCE_REPO_PATH], label="Plan 036 evidence"
        ),
        "checkpoint": runner._load_mapping_bytes(
            content[PLAN036_CHECKPOINT_REPO_PATH], label="Plan 036 checkpoint"
        ),
        "registration_bytes": content[
            str(supersedes["plan036_registration"]["path"])
        ],
        "readiness_bytes": content[str(supersedes["plan036_readiness"]["path"])],
        "blob_receipt": receipt,
    }
    sources = runner._load_source_documents(
        inherited,
        registered_current_contract=readiness["hashes"][
            "current_prospect_contract"
        ],
    )
    return runner.recompute_supersession_payload(
        inherited_artifacts=inherited,
        source_documents=sources,
        reservation_id=reservation_id,
    )


def _validate_terminal_documents(
    result: Mapping[str, Any],
    *,
    readiness: Mapping[str, Any],
    registration: Mapping[str, Any],
    readiness_sha256: str,
    registration_sha256: str,
) -> dict[str, Any]:
    status = result.get("status")
    success_keys = {
        "artifact",
        "schema_version",
        "protocol",
        "status",
        "decision",
        "production_review_authorized",
        "claim_authorized",
        "registered_readiness_sha256",
        "registration_sha256",
        "supersedes",
        "candidate",
        "outer_folds",
        "quality_starts_sha256",
        "current_role_shape_governor",
        "fold_outputs",
        "evaluation",
        "evidence_bundle",
        "reservation_id",
    }
    spent_keys = {
        "artifact",
        "schema_version",
        "protocol",
        "status",
        "decision",
        "production_review_authorized",
        "claim_authorized",
        "error_type",
        "registered_readiness_sha256",
        "registration_sha256",
        "supersedes",
        "evidence_bundle",
        "reservation_id",
    }
    _require_exact_keys(
        result,
        spent_keys if status == "spent_error" else success_keys,
        label="terminal result",
    )
    reservation_id = result.get("reservation_id")
    if (
        result.get("artifact")
        != "valucast_pre2014_cross_role_supersession_gate"
        or result.get("schema_version") != 1
        or result.get("protocol") != PROTOCOL
        or status not in {"passed", "failed", "spent_error"}
        or result.get("claim_authorized") is not False
        or not isinstance(reservation_id, str)
        or not reservation_id
        or result.get("registered_readiness_sha256") != readiness_sha256
        or result.get("registration_sha256") != registration_sha256
        or _canonical(result.get("supersedes"))
        != _canonical(readiness.get("supersedes"))
    ):
        raise ResultValidationError("result fixed contract drift")
    bundle = _require_exact_keys(
        result.get("evidence_bundle"), {"terminal_evidence"}, label="evidence bundle"
    )
    evidence_path, _ = _validate_runtime_record(
        bundle["terminal_evidence"], expected_path=REGISTERED_EVIDENCE_REPO_PATH
    )
    evidence = _load_json_object(evidence_path, label="terminal evidence")
    base_evidence_keys = {
        "artifact",
        "schema_version",
        "status",
        "reservation_id",
        "registered_readiness_sha256",
        "registration_sha256",
        "implementation_base_commit",
        "supersedes",
        "network_refetch_used",
        "execution_commit",
    }
    success_evidence_keys = base_evidence_keys | {
        "inherited_validation",
        "fold_outputs",
        "current_role_shape_governor",
        "evaluation",
        "quality_starts_sha256",
    }
    spent_evidence_keys = base_evidence_keys | {"error_type"}
    _require_exact_keys(
        evidence,
        spent_evidence_keys if status == "spent_error" else success_evidence_keys,
        label="terminal evidence",
    )
    if (
        evidence.get("artifact")
        != "valucast_plan037_supersession_terminal_evidence"
        or evidence.get("schema_version") != 1
        or evidence.get("status") != status
        or evidence.get("reservation_id") != reservation_id
        or evidence.get("registered_readiness_sha256") != readiness_sha256
        or evidence.get("registration_sha256") != registration_sha256
        or evidence.get("implementation_base_commit")
        != readiness.get("implementation_base_commit")
        or _canonical(evidence.get("supersedes"))
        != _canonical(readiness.get("supersedes"))
        or evidence.get("network_refetch_used") is not False
        or not _is_git_oid(evidence.get("execution_commit"))
    ):
        raise ResultValidationError("terminal evidence binding drift")
    if status == "spent_error":
        if (
            result.get("decision") != "production_review_not_authorized"
            or result.get("production_review_authorized") is not False
            or not isinstance(result.get("error_type"), str)
            or evidence.get("error_type") != result.get("error_type")
        ):
            raise ResultValidationError("spent result drift")
        try:
            _recompute_from_frozen_blobs(
                readiness=readiness, reservation_id=str(reservation_id)
            )
        except Exception as exc:
            if type(exc).__name__ != result.get("error_type"):
                raise ResultValidationError("spent error does not replay") from exc
        else:
            raise ResultValidationError("spent result now replays without its error")
        return evidence
    expected_candidate = {
        "model_flags": dict(runner.CANDIDATE_MODEL_FLAGS),
        "model_score_mode": CANDIDATE_SCORE_MODE,
    }
    if (
        result.get("candidate") != expected_candidate
        or result.get("outer_folds") != list(REGISTERED_OUTER_FOLDS)
        or not _is_sha256(result.get("quality_starts_sha256"))
    ):
        raise ResultValidationError("result fixed contract drift")
    replay = _recompute_from_frozen_blobs(
        readiness=readiness, reservation_id=str(reservation_id)
    )
    links = {
        "inherited_validation": replay["inherited_validation"],
        "fold_outputs": replay["fold_outputs"],
        "current_role_shape_governor": replay["current_role_shape_governor"],
        "evaluation": replay["evaluation"],
        "quality_starts_sha256": replay["quality_starts"]["sidecar"][
            "content_sha256"
        ],
    }
    if any(
        _canonical(evidence.get(key)) != _canonical(value)
        for key, value in links.items()
    ) or any(
        _canonical(result.get(key)) != _canonical(value)
        for key, value in links.items()
        if key != "inherited_validation"
    ):
        raise ResultValidationError("terminal frozen-replay drift")
    governor = result.get("current_role_shape_governor")
    if not isinstance(governor, Mapping) or not isinstance(governor.get("passed"), bool):
        raise ResultValidationError("governor receipt is malformed")
    replay_terminal_decision(
        result,
        folds=result["fold_outputs"],
        governor_passed=bool(governor["passed"]),
    )
    return evidence


def replay_terminal_decision(
    result: Mapping[str, Any], *, folds: Sequence[Mapping[str, Any]], governor_passed: bool
) -> Mapping[str, Any]:
    """Replay the registered pure gate and bind terminal status to its decision."""
    recomputed = evaluate_pre2014_cross_role_gate(
        folds,
        cohort_years=EXPECTED_COHORTS,
        declared_omissions={2020},
        current_role_shape_governor_passed=governor_passed,
        bootstrap_seed=BOOTSTRAP_SEED,
        bootstrap_resamples=DEFAULT_BOOTSTRAP_RESAMPLES,
    )
    if _canonical(result.get("evaluation")) != _canonical(recomputed):
        raise ResultValidationError(
            "stored evaluation does not match deterministic replay"
        )
    authorized = recomputed.get("production_review_authorized") is True
    expected_status = "passed" if authorized else "failed"
    if (
        result.get("status") != expected_status
        or result.get("production_review_authorized") is not authorized
        or result.get("decision") != recomputed.get("decision")
        or result.get("claim_authorized") is not False
    ):
        raise ResultValidationError("result status/decision does not match evaluation")
    return recomputed


def validate_result_files(
    *,
    result_path: Path | str,
    readiness_path: Path | str,
    registration_path: Path | str,
) -> dict[str, Any]:
    """Validate Plan 037 seals and rebuild its terminal decision from S036."""
    result_path = Path(result_path)
    readiness_path = Path(readiness_path)
    registration_path = Path(registration_path)
    fixed = (
        (result_path, ROOT / REGISTERED_RESULT_REPO_PATH, "result"),
        (readiness_path, ROOT / REGISTERED_READINESS_REPO_PATH, "readiness"),
        (registration_path, ROOT / REGISTERED_PLAN_REPO_PATH, "registration"),
    )
    for path, expected, label in fixed:
        if not _same_path(path, expected):
            raise ResultValidationError(f"{label} fixed path drift")
        if path.is_symlink():
            raise ResultValidationError(f"{label} must not be a symbolic link")
        if not path.is_file():
            raise ResultValidationError(f"{label} must be a regular file")
    if not (ROOT / ".git").exists():
        raise ResultValidationError("sealed-checkout Git metadata is required")

    result = _load_json_object(result_path, label="terminal result")
    readiness = _load_json_object(readiness_path, label="readiness")
    registration = _load_registration(registration_path)
    readiness_sha256 = hashlib.sha256(readiness_path.read_bytes()).hexdigest()
    registration_sha256 = hashlib.sha256(
        _canonical(registration).encode("utf-8")
    ).hexdigest()
    _validate_readiness_contract(
        readiness, implementation_paths=tuple(PLAN037_IMPLEMENTATION_PATHS)
    )
    _validate_registration_contract(
        registration,
        readiness=readiness,
        readiness_sha256=readiness_sha256,
    )
    implementation_commit = str(readiness["implementation_base_commit"])
    _validate_frozen_plan036_git_seals(readiness["supersedes"])
    _validate_implementation_git_seals(
        readiness, implementation_commit=implementation_commit
    )
    evidence = _validate_terminal_documents(
        result,
        readiness=readiness,
        registration=registration,
        readiness_sha256=readiness_sha256,
        registration_sha256=registration_sha256,
    )
    execution_commit = str(evidence["execution_commit"])
    head = _git_text("rev-parse", "HEAD")
    topology = _validate_git_topology(
        implementation_commit=implementation_commit,
        execution_commit=execution_commit,
        head=head,
        result_status=str(result["status"]),
    )
    return {
        "valid": True,
        "status": result["status"],
        "production_review_authorized": (
            result.get("production_review_authorized") is True
        ),
        "claim_authorized": False,
        "topology": topology,
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
        print(f"Plan 037 result invalid: {exc}", file=sys.stderr, flush=True)
        return 1
    print(
        "Plan 037 result valid: "
        f"status={report['status']} "
        "production_review_authorized="
        f"{report['production_review_authorized']} "
        "claim_authorized=false "
        f"topology={report['topology']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
