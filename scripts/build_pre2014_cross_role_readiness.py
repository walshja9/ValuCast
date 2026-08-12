"""Build the no-outcome pre-2014 cross-role readiness artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.pre2014_readiness import (  # noqa: E402
    REGISTERED_IMPLEMENTATION_PATHS,
    REGISTERED_PREPARED_SOURCE_PATHS,
    REGISTERED_SOURCE_PATHS,
    SEALED_OUTCOME_SOURCE_BINDING,
    SEALED_OUTCOME_SOURCE_KEY,
    build_pre2014_readiness,
    replay_pre2014_source_contract,
)


RESEARCH_DIR = ROOT / "data" / "research" / "extended_prospect_history"
DEFAULT_PREPARED = RESEARCH_DIR / "prepared.json"
DEFAULT_PREPARED_MANIFEST = RESEARCH_DIR / "prepared-source-manifest.json"
DEFAULT_DRAFT_FACTS = RESEARCH_DIR / "draft-facts.json"
DEFAULT_RESULT_PATH = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_gate.json"
)
DEFAULT_OUTPUT = (
    ROOT / "data" / "validation" / "valucast_pre2014_cross_role_readiness.json"
)


def _read_bytes(path: Path) -> bytes:
    return Path(path).read_bytes()


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _load_json(content: bytes, *, path: Path) -> Any:
    try:
        return json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON input: {path}") from exc


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
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _require_clean_worktree() -> None:
    # The sealed outcome source is never consumed from the worktree.  Excluding
    # it from the cleanliness pathspec also prevents Git from content-hashing it
    # before reservation; execution later reads the registered base-commit blob.
    dirty = _git(
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        "--",
        ".",
        f":(exclude){REGISTERED_SOURCE_PATHS[SEALED_OUTCOME_SOURCE_KEY]}",
    )
    if dirty:
        raise ValueError(
            "readiness must be built from a completely clean implementation commit"
        )


def _repo_path(path: Path) -> str:
    try:
        relative = Path(path).resolve().relative_to(ROOT.resolve())
    except (OSError, ValueError) as exc:
        raise ValueError("registered paths must remain inside the repository") from exc
    value = relative.as_posix()
    if not value or value == "." or "\\" in value or ":" in value:
        raise ValueError("registered path is not canonical repository-relative POSIX")
    return value


def _record(path: Path, *, base_commit: str) -> dict[str, str]:
    logical_path = _repo_path(path)
    try:
        blob = _git("rev-parse", f"{base_commit}:{logical_path}")
        working_blob = _git(
            "hash-object", f"--path={logical_path}", str(Path(path).resolve())
        )
        blob_content = _git_bytes("cat-file", "blob", blob)
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"registered input is not committed at {base_commit}: {logical_path}"
        ) from exc
    if working_blob != blob:
        raise ValueError(f"registered input differs from base commit: {logical_path}")
    return {
        "path": logical_path,
        "sha256": _sha256(blob_content),
        "git_blob": blob,
    }


def _metadata_record(path: Path, *, base_commit: str) -> dict[str, str]:
    """Bind the sealed outcome source without opening worktree or blob bytes."""
    logical_path = _repo_path(path)
    try:
        blob = _git("rev-parse", f"{base_commit}:{logical_path}")
        object_type = _git("cat-file", "-t", blob)
    except subprocess.CalledProcessError as exc:
        raise ValueError(
            f"registered input is not committed at {base_commit}: {logical_path}"
        ) from exc
    if object_type != "blob" or len(blob) != 40 or any(
        character not in "0123456789abcdef" for character in blob.lower()
    ):
        raise ValueError(f"registered input is not a Git blob: {logical_path}")
    return {
        "path": logical_path,
        "git_blob": blob,
        "binding": SEALED_OUTCOME_SOURCE_BINDING,
    }


def _committed_prepared_source_bytes(
    logical_path: str, *, base_commit: str
) -> bytes:
    """Read one allowlisted outcome-blind source from the sealed Git tree."""
    if logical_path not in REGISTERED_PREPARED_SOURCE_PATHS:
        raise ValueError(f"unregistered prepared source path: {logical_path}")
    return _git_bytes("cat-file", "blob", f"{base_commit}:{logical_path}")


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(left)) == os.path.normcase(os.path.abspath(right))


def _guard_output(
    output: Path,
    *,
    inputs: list[Path],
    implementations: list[Path],
    result_path: Path,
) -> None:
    protected = [*inputs, *implementations, result_path]
    if any(_same_path(output, path) for path in protected):
        raise ValueError(f"readiness output would overwrite protected input: {output}")


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
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
    parser.add_argument("--prepared", type=Path, default=DEFAULT_PREPARED)
    parser.add_argument(
        "--prepared-manifest", type=Path, default=DEFAULT_PREPARED_MANIFEST
    )
    parser.add_argument("--draft-facts", type=Path, default=DEFAULT_DRAFT_FACTS)
    parser.add_argument("--result-path", type=Path, default=DEFAULT_RESULT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    _require_clean_worktree()
    inputs = [args.prepared, args.prepared_manifest, args.draft_facts]
    implementations = [ROOT / path for path in REGISTERED_IMPLEMENTATION_PATHS]
    current_source_paths = {
        key: ROOT / path
        for key, path in REGISTERED_SOURCE_PATHS.items()
        if key not in {"prepared_artifact", "prepared_manifest", "draft_facts"}
    }
    prepared_source_paths = [
        ROOT / path for path in REGISTERED_PREPARED_SOURCE_PATHS
    ]
    _guard_output(
        args.output,
        inputs=[
            *inputs,
            *current_source_paths.values(),
            *prepared_source_paths,
        ],
        implementations=implementations,
        result_path=args.result_path,
    )

    implementation_base_commit = _git("rev-parse", "HEAD")
    prepared_bytes = _read_bytes(args.prepared)
    manifest_bytes = _read_bytes(args.prepared_manifest)
    draft_bytes = _read_bytes(args.draft_facts)
    source_files = {
        "prepared_artifact": _record(
            args.prepared, base_commit=implementation_base_commit
        ),
        "prepared_manifest": _record(
            args.prepared_manifest,
            base_commit=implementation_base_commit,
        ),
        "draft_facts": _record(
            args.draft_facts, base_commit=implementation_base_commit
        ),
        **{
            key: (
                _metadata_record(
                    current_source_paths[key],
                    base_commit=implementation_base_commit,
                )
                if key == SEALED_OUTCOME_SOURCE_KEY
                else _record(
                    current_source_paths[key],
                    base_commit=implementation_base_commit,
                )
            )
            for key in current_source_paths
        },
    }
    implementation_files = [
        _record(path, base_commit=implementation_base_commit)
        for path in implementations
    ]
    prepared_source_files = [
        _record(path, base_commit=implementation_base_commit)
        for path in prepared_source_paths
    ]
    prepared_payload = _load_json(prepared_bytes, path=args.prepared)
    manifest_payload = _load_json(manifest_bytes, path=args.prepared_manifest)
    draft_payload = _load_json(draft_bytes, path=args.draft_facts)
    # Replay the exact committed bytes, not platform-specific checkout bytes.
    # This keeps source receipts identical under core.autocrlf while `_record`
    # above separately proves every live file clean-filters to the same blob.
    source_replay = replay_pre2014_source_contract(
        prepared_payload,
        manifest_payload,
        draft_payload,
        load_bytes=lambda path: _committed_prepared_source_bytes(
            path, base_commit=implementation_base_commit
        ),
    )
    report = build_pre2014_readiness(
        prepared_payload,
        manifest_payload,
        draft_payload,
        source_files=source_files,
        implementation_files=implementation_files,
        prepared_source_files=prepared_source_files,
        source_replay=source_replay,
        implementation_base_commit=implementation_base_commit,
        result_path=_repo_path(args.result_path),
        result_path_exists=args.result_path.exists(),
    )
    _write_atomic(args.output, report)
    print(
        "pre-2014 cross-role readiness: "
        f"status={report['status']} blockers={len(report['blockers'])} "
        f"execution_authorized={report['execution_authorized']} -> {args.output}",
        flush=True,
    )
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
