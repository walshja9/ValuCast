"""Build the outcome-blind readiness receipt for the Plan 037 supersession."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.pre2014_readiness import (  # noqa: E402
    REGISTERED_IMPLEMENTATION_PATHS as PLAN036_IMPLEMENTATION_PATHS,
)
from scripts.run_pre2014_cross_role_gate import (  # noqa: E402
    CANDIDATE_SCORE_MODE,
    EXPECTED_BOOTSTRAP,
    EXPECTED_GOVERNOR,
    EXPECTED_THRESHOLDS,
    REGISTERED_OUTER_FOLDS,
)


PLAN036_IMPLEMENTATION_COMMIT = "f7d3304bde6e57a02db4a5c7347ce9fc5e4c0af3"
PLAN036_EXECUTION_COMMIT = "568aea2e91bf473ba4491dec394e16afdffd5478"
PLAN036_ARTIFACT_COMMIT = "f06f14599659863bbacf459a1e2fa654529b6c01"
PLAN036_REGISTRATION_SHA256 = (
    "0dc66697a38226df0e05af9b0e9740638d419972d1a83671accfdbd08cf231dd"
)
PLAN036_READINESS_SHA256 = (
    "12a1023bd1000e54520c2ac445aebbe603c27c69f2bcc0badf3cbbf1fae7e610"
)
PLAN036_REGISTRATION_PATH = "plans/036-pre2014-cross-role-calibration-gate.md"
PLAN036_READINESS_PATH = (
    "data/validation/valucast_pre2014_cross_role_readiness.json"
)
PLAN036_OUTCOME_PATHS = (
    "data/validation/valucast_pre2014_cross_role_gate.json",
    "data/validation/valucast_pre2014_cross_role_evidence.json",
    "data/research/extended_prospect_history/sealed-acquisition-checkpoint.json",
)
CURRENT_CONTRACT_PATH = "data/prospects/prospect_model_inputs.json"
DEFAULT_RESULT_PATH = (
    ROOT
    / "data"
    / "validation"
    / "valucast_pre2014_cross_role_supersession_gate.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "data"
    / "validation"
    / "valucast_pre2014_cross_role_supersession_readiness.json"
)
PLAN037_IMPLEMENTATION_CHANGE_PATHS = (
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
)
PLAN037_IMPLEMENTATION_CHANGE_STATUSES = {
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
PLAN037_IMPLEMENTATION_PATHS = tuple(
    sorted(
        dict.fromkeys(
            (
                *PLAN036_IMPLEMENTATION_PATHS,
                *PLAN037_IMPLEMENTATION_CHANGE_PATHS,
            )
        )
    )
)
OUTCOME_METADATA_BINDING = "git_blob_only_pre_reservation"


def _git(*args: str) -> str:
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
        ["git", *args], cwd=ROOT, check=True, capture_output=True
    )
    return completed.stdout


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _repo_path(path: Path | str) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        relative = candidate.resolve().relative_to(ROOT.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError("registered paths must stay inside the repository") from exc
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
        raise ValueError("registered path is not canonical repository-relative POSIX")
    return value


def _tree_blob_record(
    repo_path: str, *, commit: str, binding: str = OUTCOME_METADATA_BINDING
) -> dict[str, str]:
    """Bind one committed blob using tree metadata without opening its bytes."""
    logical_path = _repo_path(repo_path)
    try:
        raw = _git("ls-tree", "-z", commit, "--", logical_path)
    except subprocess.CalledProcessError as exc:
        raise ValueError(f"cannot inspect registered Git tree: {commit}") from exc
    entries = [entry for entry in raw.split("\0") if entry]
    if len(entries) != 1 or "\t" not in entries[0]:
        raise ValueError(f"registered Git blob is missing: {commit}:{logical_path}")
    header, actual_path = entries[0].split("\t", 1)
    parts = header.split()
    if (
        len(parts) != 3
        or parts[0] != "100644"
        or parts[1] != "blob"
        or actual_path != logical_path
        or len(parts[2]) != 40
        or any(character not in "0123456789abcdef" for character in parts[2])
    ):
        raise ValueError(f"registered object is not a regular Git blob: {logical_path}")
    return {"path": logical_path, "git_blob": parts[2], "binding": binding}


def _content_record(repo_path: str, *, commit: str) -> dict[str, str]:
    """Bind one outcome-blind committed blob and its exact content hash."""
    metadata = _tree_blob_record(repo_path, commit=commit)
    content = _git_bytes("cat-file", "blob", metadata["git_blob"])
    return {
        "path": metadata["path"],
        "git_blob": metadata["git_blob"],
        "sha256": _sha256(content),
    }


def _implementation_record(repo_path: str, *, commit: str) -> dict[str, str]:
    logical_path = _repo_path(repo_path)
    record = _content_record(logical_path, commit=commit)
    working_blob = _git(
        "hash-object", f"--path={logical_path}", str((ROOT / logical_path).resolve())
    )
    if working_blob != record["git_blob"]:
        raise ValueError(f"implementation differs from HEAD: {logical_path}")
    return record


def _parents(commit: str) -> list[str]:
    fields = _git("rev-list", "--parents", "-n", "1", commit).split()
    if not fields or fields[0] != commit:
        raise ValueError(f"cannot resolve commit topology: {commit}")
    return fields[1:]


def _require_topology(implementation_commit: str) -> None:
    if _parents(implementation_commit) != [PLAN036_ARTIFACT_COMMIT]:
        raise ValueError("Plan 037 implementation must be the direct child of S036")
    if _parents(PLAN036_ARTIFACT_COMMIT) != [PLAN036_EXECUTION_COMMIT]:
        raise ValueError("Plan 036 artifact commit topology drift")
    if _parents(PLAN036_EXECUTION_COMMIT) != [PLAN036_IMPLEMENTATION_COMMIT]:
        raise ValueError("Plan 036 execution commit topology drift")
    artifact_diff: dict[str, str] = {}
    for line in _git(
        "diff-tree",
        "--no-commit-id",
        "--name-status",
        "-r",
        PLAN036_ARTIFACT_COMMIT,
    ).splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or parts[1] in artifact_diff:
            raise ValueError("Plan 036 artifact commit diff is malformed")
        artifact_diff[parts[1]] = parts[0]
    if artifact_diff != {path: "A" for path in PLAN036_OUTCOME_PATHS}:
        raise ValueError("Plan 036 artifact commit is not the exact A-only receipt")
    implementation_diff = {}
    for line in _git(
        "diff", "--name-status", PLAN036_ARTIFACT_COMMIT, implementation_commit
    ).splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or parts[1] in implementation_diff:
            raise ValueError("Plan 037 implementation diff is malformed")
        implementation_diff[parts[1]] = parts[0]
    if implementation_diff != PLAN037_IMPLEMENTATION_CHANGE_STATUSES:
        raise ValueError("Plan 037 implementation change set drift")


def _require_clean_worktree() -> None:
    exclusions = [CURRENT_CONTRACT_PATH, *PLAN036_OUTCOME_PATHS]
    pathspecs = [".", *(f":(exclude){path}" for path in exclusions)]
    if _git("status", "--porcelain=v1", "--untracked-files=all", "--", *pathspecs):
        raise ValueError("readiness requires a clean implementation commit")


def build_readiness(
    *,
    implementation_commit: str,
    result_path: str,
    result_exists: bool,
    implementation_files: list[dict[str, str]],
    plan036_registration: dict[str, str],
    plan036_readiness: dict[str, str],
    outcome_blob_records: list[dict[str, str]],
    current_contract: dict[str, str],
) -> dict[str, Any]:
    blockers = []
    if result_exists:
        blockers.append("registered supersession result already exists")
    expected_outcome_paths = list(PLAN036_OUTCOME_PATHS)
    if [record.get("path") for record in outcome_blob_records] != expected_outcome_paths:
        blockers.append("Plan 036 outcome blob set is incomplete or reordered")
    if any(
        set(record) != {"path", "git_blob", "binding"}
        or record.get("binding") != OUTCOME_METADATA_BINDING
        for record in outcome_blob_records
    ):
        blockers.append("Plan 036 outcome blobs are not metadata-only bindings")
    status = "ready" if not blockers else "blocked"
    return {
        "artifact": "valucast_pre2014_cross_role_supersession_readiness",
        "schema_version": 1,
        "status": status,
        "blockers": blockers,
        "execution_authorized": not blockers,
        "look_spent": False,
        "research_only": True,
        "claim_authorized": False,
        "automatic_promotion": False,
        "implementation_base_commit": implementation_commit,
        "supersedes": {
            "plan036_artifact_commit": PLAN036_ARTIFACT_COMMIT,
            "plan036_execution_commit": PLAN036_EXECUTION_COMMIT,
            "prior_status": "spent_error",
            "prior_error_type": "FoldScoringError",
            "same_look_lineage": True,
            "network_refetch_forbidden": True,
            "plan036_registration": plan036_registration,
            "plan036_readiness": plan036_readiness,
            "outcome_blob_records": outcome_blob_records,
        },
        "candidate": {
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
        },
        "outer_folds": list(REGISTERED_OUTER_FOLDS),
        "bootstrap": EXPECTED_BOOTSTRAP,
        "primary_endpoint": "direct_7x7_target_percentile_rank_mae",
        "thresholds": EXPECTED_THRESHOLDS,
        "governor": EXPECTED_GOVERNOR,
        "corrections": {
            "allowed": [
                "zero_walk_positive_strikeout_k_bb_ordinal_target",
                "statsapi_bare_dash_missing_numeric_sentinel",
            ],
            "row_or_identity_drops": 0,
            "category_drops": 0,
            "threshold_changes": 0,
            "candidate_changes": 0,
        },
        "hashes": {
            "implementation_files": implementation_files,
            "implementation_change_paths": list(
                PLAN037_IMPLEMENTATION_CHANGE_PATHS
            ),
            "current_prospect_contract": current_contract,
        },
        "result": {
            "path": result_path,
            "exists": result_exists,
            "unspent": not result_exists,
        },
    }


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-path", type=Path, default=DEFAULT_RESULT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _require_clean_worktree()
    implementation_commit = _git("rev-parse", "HEAD")
    _require_topology(implementation_commit)
    result_path = _repo_path(args.result_path)
    output_path = _repo_path(args.output)
    if output_path in {
        result_path,
        CURRENT_CONTRACT_PATH,
        PLAN036_REGISTRATION_PATH,
        PLAN036_READINESS_PATH,
        *PLAN036_OUTCOME_PATHS,
        *PLAN037_IMPLEMENTATION_PATHS,
    }:
        raise ValueError("readiness output would overwrite a protected file")
    report = build_readiness(
        implementation_commit=implementation_commit,
        result_path=result_path,
        result_exists=args.result_path.exists(),
        implementation_files=[
            _implementation_record(path, commit=implementation_commit)
            for path in PLAN037_IMPLEMENTATION_PATHS
        ],
        plan036_registration=_content_record(
            PLAN036_REGISTRATION_PATH, commit=PLAN036_ARTIFACT_COMMIT
        ),
        plan036_readiness=_content_record(
            PLAN036_READINESS_PATH, commit=PLAN036_ARTIFACT_COMMIT
        ),
        outcome_blob_records=[
            _tree_blob_record(path, commit=PLAN036_ARTIFACT_COMMIT)
            for path in PLAN036_OUTCOME_PATHS
        ],
        current_contract=_tree_blob_record(
            CURRENT_CONTRACT_PATH, commit=implementation_commit
        ),
    )
    _write_atomic(args.output, report)
    print(
        "Plan 037 supersession readiness: "
        f"status={report['status']} blockers={len(report['blockers'])} "
        f"execution_authorized={report['execution_authorized']} -> {args.output}",
        flush=True,
    )
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
