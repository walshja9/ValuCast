"""Read-only, source-bound access boundary for the pinned-source serving candidate.

Use bind_candidate before install_guard, then verify_after in a finally block.
Only aggregate receipts may leave the hosted runner. This is a Python audit
boundary, not an operating-system sandbox or a proof of native-library IO.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import sysconfig

SYSTEM_TIMEZONE = "/usr/share/zoneinfo/America/New_York"
OPTIONAL_STDLIB_ZIP = str(Path(sysconfig.get_path("stdlib")).parent /
                         f"python{sys.version_info.major}{sys.version_info.minor}.zip")



def _hash(path: Path) -> dict:
    if not path.is_file():
        return {"state": "missing", "sha256": None, "git_blob": None, "bytes": 0}
    size = path.stat().st_size
    sha = hashlib.sha256()
    blob = hashlib.sha1(b"blob " + str(size).encode() + b"\0")
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
            blob.update(block)
    return {"state": "present", "sha256": sha.hexdigest(), "git_blob": blob.hexdigest(), "bytes": size}


def _system_hash(path: Path) -> dict:
    observed = _hash(path)
    return {key: observed[key] for key in ("state", "sha256", "bytes")}


def _archive_names(directory: Path) -> list[str]:
    # Filename metadata only; only the normal producer-selected payload is hashed/read.
    if not directory.is_dir():
        raise ValueError("Normal public rank archive directory is missing")
    return sorted(path.name for path in directory.glob("*.json"))


def _tree_records(raw: bytes) -> dict[str, str]:
    result = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        header, name = record.split(b"\t", 1)
        mode, kind, oid = header.decode().split()
        name = name.decode()
        if mode not in {"100644", "100755"} or kind != "blob" or not re.fullmatch(r"[0-9a-f]{40}", oid) or name in result:
            raise ValueError("Staged checkout contains an invalid or duplicate admitted leaf")
        result[name] = oid
    return result


def _stage_contract(root: Path, contract: dict) -> dict:
    """Bind the fixed read scope to the caller's detached staged HEAD, not old data bytes."""
    if contract.get("binding_mode") != "detached_staged_HEAD":
        raise ValueError("Detached staged HEAD contract required")
    def git(*arguments):
        return subprocess.check_output(["git", "--no-lazy-fetch", *arguments], cwd=root)
    identity = git("rev-parse", "HEAD", "HEAD^{tree}").decode().splitlines()
    if len(identity) != 2 or any(len(value) != 40 for value in identity):
        raise ValueError("Invalid staged checkout identity")
    branch = subprocess.run(["git", "--no-lazy-fetch", "symbolic-ref", "--quiet", "HEAD"],
                            cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if branch.returncode != 1:
        raise ValueError("Serving rehearsal must run from a detached staged checkout")
    paths = [row["path"] for row in contract["read_files"]]
    sources = list(contract["source_bindings"])
    if len(paths) != len(set(paths)) or any(Path(path).is_absolute() or ".." in Path(path).parts
                                          for path in (*paths, *sources)):
        raise ValueError("Invalid staged file path scope")
    admitted = set(paths) | set(sources)
    blobs = _tree_records(git("ls-tree", "-r", "-z", "HEAD", "--", *sorted(admitted)))
    if not set(blobs).issubset(admitted):
        raise ValueError("Git metadata escaped exact admitted source/data paths")
    for row in contract["read_files"]:
        row["git_blob"] = blobs.get(row["path"])
        row.pop("expected_sha256", None)
    for path in sources:
        candidate = root / path
        if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
            raise ValueError("Admitted source is not a regular in-checkout leaf")
        observed = _hash(candidate)
        if path not in blobs or observed["git_blob"] != blobs[path]:
            raise ValueError("Source file differs from staged HEAD")
        contract["source_bindings"][path] = {"git_blob": observed["git_blob"], "sha256": observed["sha256"]}
    for row in contract.get("protected_code_imports", {}).values():
        if row["path"] not in contract["source_bindings"]:
            raise ValueError("Protected source seam is not staged-source bound")
        row["sha256"] = contract["source_bindings"][row["path"]]["sha256"]
    archive = contract.get("public_rank_archive")
    if archive:
        directory = archive["directory"]
        rows = _tree_records(git("ls-tree", "-r", "-z", "HEAD", "--", directory))
        if any(Path(path).parent.as_posix() != directory or not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", Path(path).name)
               for path in rows):
            raise ValueError("Public rank archive differs from the normal dated JSON family")
        archive["files"] = [{"path": path, "git_blob": oid} for path, oid in sorted(rows.items())]
    contract["candidate_data_commit"] = identity[0]
    contract["runtime_source_commit"] = identity[0]
    contract["staged_tree"] = identity[1]
    contract["system_read_files"][1]["path"] = OPTIONAL_STDLIB_ZIP
    return contract


def bind_candidate(root: Path, contract_path: Path) -> dict:
    """Hosted only: verify exact source/data identities before importing app."""
    root, contract_path = Path(root).resolve(), Path(contract_path).resolve()
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Candidate data binding is restricted to the hosted qualification")
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("VALUCAST_ANALYTICS_DB"):
        raise RuntimeError("Keyless and analytics-disabled qualification required")
    if os.environ.get("VALUCAST_MLB_LIVE_PROJECTION_SOURCE", "current") != "current":
        raise RuntimeError("Steamer/current source required")
    if os.environ.get("VALUCAST_ACTUALS_SEASON") or os.environ.get("VALUCAST_FRESHNESS_MAX_AGE_DAYS") not in (None, "", "0"):
        raise RuntimeError("Production freshness limits and actuals-season check required")
    raw = contract_path.read_bytes()
    contract = json.loads(raw)
    contract = _stage_contract(root, contract)
    today = datetime.now(timezone.utc).date().isoformat()
    if os.environ.get("VALUCAST_REFRESH_DATE") not in (None, "", today):
        raise ValueError("Backdated freshness override is prohibited")
    reads = {}
    for entry in contract["read_files"]:
        rel = entry["path"]
        candidate_path = root / rel
        path = candidate_path.resolve()
        if not path.is_relative_to(root) or candidate_path.is_symlink() or rel in reads:
            raise ValueError("Invalid or duplicate admitted path")
        if entry.get("git_blob") is None and path.exists():
            raise ValueError("HEAD-absent optional input unexpectedly exists")
        observed = _hash(path)
        if observed["git_blob"] != entry.get("git_blob"):
            raise ValueError("Candidate file is not the admitted bound blob")
        if entry.get("expected_sha256") and observed["sha256"] != entry["expected_sha256"]:
            raise ValueError("Committed candidate differs from retained byte binding")
        reads[rel] = observed
    if any(reads.get(path, {}).get("state") != "present" for path in contract["required_files"]):
        raise ValueError("Required serving candidate is missing")
    source = {}
    for rel, expected in contract["source_bindings"].items():
        source[rel] = _hash(root / rel)
        if any(source[rel][key] != expected[key] for key in ("git_blob", "sha256")):
            raise ValueError("Serving source differs from pinned code")
    system_rows = contract.get("system_read_files", [])
    if [entry["path"] for entry in system_rows] != [SYSTEM_TIMEZONE, OPTIONAL_STDLIB_ZIP]:
        raise ValueError("System-read scope differs from the two exact admitted runtime lookups")
    runtime_zip = Path(sysconfig.get_path("stdlib")).parent / f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    if str(runtime_zip) != OPTIONAL_STDLIB_ZIP or OPTIONAL_STDLIB_ZIP not in sys.path:
        raise ValueError("Optional runtime ZIP differs from the admitted actual Python sys.path entry")
    system_before = {}
    for entry in system_rows:
        path = Path(entry["path"])
        if path.exists() and not path.is_file():
            raise ValueError("Admitted system lookup unexpectedly names a non-file")
        system_before[entry["path"]] = _system_hash(path)
        if entry["path"] == SYSTEM_TIMEZONE and system_before[entry["path"]]["state"] != "present":
            raise ValueError("Required public timezone runtime file is missing")
        if entry["path"] == OPTIONAL_STDLIB_ZIP and entry.get("optional") is not True:
            raise ValueError("Optional runtime ZIP absence must retain its genuine OS behavior")
    archive = contract.get("public_rank_archive")
    archive_listing = None
    if archive:
        directory = (root / archive["directory"]).resolve()
        if not directory.is_relative_to(root) or (root / archive["directory"]).is_symlink():
            raise ValueError("Invalid normal public rank archive directory")
        if archive["listing_pattern"] != "*.json":
            raise ValueError("Normal public rank lookup pattern changed")
        expected_names = sorted(Path(row["path"]).name for row in archive["files"])
        if len(expected_names) != len(set(expected_names)) or any(
                Path(row["path"]).parent.as_posix() != archive["directory"]
                or len(row["git_blob"]) != 40 for row in archive["files"]):
            raise ValueError("Invalid frozen public rank archive bindings")
        for row in archive["files"]:
            candidate_path = root / row["path"]
            if candidate_path.is_symlink() or candidate_path.resolve().parent != directory:
                raise ValueError("Public rank archive path is not an admitted regular leaf")
        archive_listing = _archive_names(directory)
        if archive_listing != expected_names:
            raise ValueError("Public rank archive names differ from frozen HEAD family")
    return {"root": root, "contract_path": contract_path, "contract": contract,
            "manifest_sha256": hashlib.sha256(raw).hexdigest(), "before": reads,
            "source_before": source, "evaluation_as_of": today,
            "archive_listing_before": archive_listing, "system_before": system_before}


class _ExactCodeLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, name, path, expected_sha256, guard):
        super().__init__(name, path)
        self.expected_sha256 = expected_sha256
        self.guard = guard

    def get_code(self, fullname):
        # Read only the bound .py file; no pyc lookup or protected-directory scan.
        raw = self.get_data(self.path)
        if hashlib.sha256(raw).hexdigest() != self.expected_sha256:
            self.guard._deny("code_identity_mismatch", self.path)
        return compile(raw, self.path, "exec", dont_inherit=True)


class _ExactIdentityFinder:
    def __init__(self, root, imports, guard):
        self.root, self.imports, self.guard = root, imports, guard

    def find_spec(self, fullname, path=None, target=None):
        if fullname != "projections.data" and not fullname.startswith("projections.data."):
            return None
        record = self.imports.get(fullname)
        if record is None:
            self.guard._deny("protected_code_import", fullname)
        source = self.root / record["path"]
        loader = _ExactCodeLoader(fullname, str(source), record["sha256"], self.guard)
        self.guard.events["exact_code_import"] += 1
        return importlib.util.spec_from_file_location(
            fullname, source, loader=loader,
            submodule_search_locations=[str(source.parent)] if record["package"] else None)


class _ServingGuard:
    def __init__(self, root: Path, allowed: set[Path], helper_root: Path,
                 read_files=(), write_files=(), archive=None):
        self.root = Path(root).resolve()
        self.allowed = {Path(p).resolve() for p in allowed}
        self.external_reads = {Path(p).resolve() for p in read_files}
        self.external_writes = {Path(p).resolve() for p in write_files}
        self.scratch_parents = {path.parent for path in self.external_writes}
        self.helper_root = Path(helper_root).resolve()
        runtime = sysconfig.get_paths()
        self.library_roots = {Path(runtime[key]).resolve() for key in ("stdlib", "platstdlib", "purelib", "platlib") if runtime.get(key)}
        self.font_roots = {Path(p) for p in ("/usr/share/fonts", "/usr/local/share/fonts", "/etc/fonts")}
        self.optional_runtime_zip = None
        self.archive_directory = (self.root / archive["directory"]).resolve() if archive else None
        self.archive_bindings = {(self.root / row["path"]).resolve(): row for row in archive["files"]} if archive else {}
        self.archive_before = {}
        self.events = Counter()
        self.denied = []
        self.active = True
        self._inside = False
        self._audit_event = None

    def _deny(self, kind: str, path=None):
        self.events[kind] += 1
        item = {"kind": kind, "audit_event": self._audit_event or kind, "source_frames": []}
        # Frame metadata only: do not invoke traceback/linecache, read source text,
        # or capture arguments, locals, URLs, identifiers or exception messages.
        frame = sys._getframe(1)
        try:
            while frame is not None and len(item["source_frames"]) < 24:
                filename = frame.f_code.co_filename
                if isinstance(filename, str) and filename.endswith(".py"):
                    source = Path(filename)
                    if source.is_absolute() and source.is_relative_to(self.root):
                        item["source_frames"].append({
                            "path": source.relative_to(self.root).as_posix(),
                            "function": frame.f_code.co_name, "line": frame.f_lineno})
                frame = frame.f_back
        finally:
            del frame
        if path is not None:
            item["path_sha256"] = hashlib.sha256(str(path).encode()).hexdigest()
        self.denied.append(item)
        raise PermissionError("Qualification access contract denied an operation")

    def _path(self, value):
        if isinstance(value, int):
            return None
        return Path(os.fsdecode(value)).resolve()

    def _read_allowed(self, path: Path) -> bool:
        if path in self.allowed or path in self.external_reads or path in self.external_writes or path in self.archive_bindings:
            return True
        if path.is_relative_to(self.root):
            rel = path.relative_to(self.root)
            if not rel.parts:
                return False
            if rel.parts[0] == "data":
                return False
            if rel.parts[:2] in (("projections", "data"), ("projections", "runs")):
                return False
            return (path.suffix in {".py", ".pyc"}
                    or rel.parts[0] in {"templates", "static"})
        if path.is_relative_to(self.helper_root):
            return path.suffix in {".py", ".pyc"}
        return any(path.is_relative_to(parent) for parent in self.library_roots | self.font_roots)

    def _listing_allowed(self, path: Path) -> bool:
        if self.optional_runtime_zip is not None and path == self.optional_runtime_zip:
            return True
        if self.archive_directory is not None and path == self.archive_directory:
            return True
        if path.is_relative_to(self.root):
            rel = path.relative_to(self.root)
            return not (rel.parts and rel.parts[0] == "data" or
                        rel.parts[:2] in (("projections", "data"), ("projections", "runs")))
        return (path.is_relative_to(self.helper_root)
                or any(path.is_relative_to(parent) for parent in self.library_roots | self.font_roots))

    def audit(self, event, args):
        if not self.active or self._inside:
            return
        self._inside = True
        previous_event = self._audit_event
        self._audit_event = event
        try:
            if event in {"socket.connect", "socket.connect_ex", "socket.getaddrinfo", "socket.sendto",
                         "socket.sendmsg", "socket.bind", "socket.listen", "socket.gethostbyname",
                         "socket.gethostbyaddr", "socket.getnameinfo"}:
                self._deny("network_attempt")
            if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork"}:
                self._deny("subprocess_attempt")
            if event == "os.chdir":
                self._deny("cwd_change")
            if event == "open":
                path = self._path(args[0])
                if path is None:
                    if args[0] not in (0, 1, 2):
                        self._deny("unbound_descriptor")
                    return
                if path in self.archive_bindings and path not in self.archive_before:
                    observed = _hash(path)
                    if path.is_symlink() or observed["git_blob"] != self.archive_bindings[path]["git_blob"]:
                        self._deny("archive_identity_mismatch", path)
                    self.archive_before[path] = observed
                mode, flags = args[1:3]
                write = (isinstance(mode, str) and any(c in mode for c in "wax+")) or bool(
                    flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC))
                if write:
                    if path not in self.external_writes:
                        self._deny("write_attempt", path)
                elif not self._read_allowed(path):
                    self._deny("undeclared_read", path)
                else:
                    self.events["allowed_read"] += 1
            if event in {"os.listdir", "os.scandir", "os.walk", "pathlib.Path.glob", "pathlib.Path.rglob"}:
                path = self._path(args[0])
                if self.optional_runtime_zip is not None and path == self.optional_runtime_zip:
                    if event != "os.listdir":
                        self._deny("optional_zip_listing_kind", path)
                    self.events["optional_stdlib_zip_lookup"] += 1
                if self.archive_directory is not None and path == self.archive_directory:
                    if event == "pathlib.Path.rglob" or event == "pathlib.Path.glob" and args[1] != "*.json":
                        self._deny("archive_listing_pattern", path)
                    self.events["normal_archive_listing"] += 1
                if path is None or not self._listing_allowed(path):
                    self._deny("directory_enumeration", path)
            if event in {"os.remove", "os.rmdir", "os.mkdir", "os.chmod", "os.truncate", "os.utime",
                         "os.symlink", "os.link", "os.rename"}:
                if event == "os.mkdir":
                    path = self._path(args[0])
                    if path in self.scratch_parents and path.is_dir():
                        self.events["idempotent_scratch_mkdir"] += 1
                        return
                targets = args[:2] if event in {"os.rename", "os.link", "os.symlink"} else args[:1]
                if any(self._path(target) not in self.external_writes for target in targets):
                    self._deny("filesystem_mutation")
        finally:
            self._audit_event = previous_event
            self._inside = False


def install_guard(bound: dict, read_files=(), write_files=()):
    """Install before the real app import. Scratch paths must be exact, external files."""
    root = bound["root"]
    temp = Path(os.environ["RUNNER_TEMP"]).resolve()
    external = [Path(p).resolve() for p in (*read_files, *write_files)]
    if any(path.is_relative_to(root) or not path.is_relative_to(temp) for path in external):
        raise ValueError("Scenario files must be exact paths outside checkout under RUNNER_TEMP")
    guard = _ServingGuard(root, {root / p for p in (*bound["before"], *bound["source_before"])} | {Path(p) for p in bound["system_before"]},
                          bound["contract_path"].parent,
                          read_files=(*read_files, bound["contract_path"]), write_files=write_files,
                          archive=bound["contract"].get("public_rank_archive"))
    guard.optional_runtime_zip = Path(OPTIONAL_STDLIB_ZIP).resolve()
    imports = bound["contract"].get("protected_code_imports", {})
    expected = {"projections.data": "projections/data/__init__.py",
                "projections.data.identity": "projections/data/identity.py"}
    if set(imports) != set(expected) or any(imports[name]["path"] != file for name, file in expected.items()):
        raise ValueError("Protected code import seam differs from the two admitted source modules")
    if any(name == "projections.data" or name.startswith("projections.data.") for name in sys.modules):
        raise ValueError("Protected source was loaded before the access guard")
    sys.dont_write_bytecode = True
    sys.addaudithook(guard.audit)
    guard.code_finder = _ExactIdentityFinder(root, imports, guard)
    sys.meta_path.insert(0, guard.code_finder)
    return guard


def verify_after(bound: dict, guard) -> dict:
    """Return aggregate evidence even after a denied app operation; never publish."""
    after = {path: _hash(bound["root"] / path) for path in bound["before"]}
    source_after = {path: _hash(bound["root"] / path) for path in bound["source_before"]}
    changed = [path for path in after if after[path] != bound["before"][path]]
    source_changed = [path for path in source_after if source_after[path] != bound["source_before"][path]]
    system_after = {path: _system_hash(Path(path)) for path in bound["system_before"]}
    system_unchanged = system_after == bound["system_before"]
    archive_after = {path: _hash(path) for path in guard.archive_before}
    archive_changed = [str(path.relative_to(bound["root"])) for path in archive_after
                       if archive_after[path] != guard.archive_before[path]]
    archive_listing = _archive_names(guard.archive_directory) if guard.archive_directory is not None else None
    archive_listing_unchanged = archive_listing == bound.get("archive_listing_before")
    return {"kind": "committed_candidate_access", "candidate_data_commit": bound["contract"]["candidate_data_commit"],
            "runtime_source_commit": bound["contract"]["runtime_source_commit"],
            "staged_tree": bound["contract"]["staged_tree"],
            "candidate_kind": bound["contract"]["candidate_kind"],
            "manifest_sha256": bound["manifest_sha256"],
            "evaluation_as_of": bound["evaluation_as_of"],
            "before": bound["before"], "after": after,
            "changed_candidate_paths": changed, "source_changed_paths": source_changed,
            "guard_counts": dict(guard.events), "denied_operations": guard.denied,
            "normal_rank_archive": {"directory": bound["contract"].get("public_rank_archive", {}).get("directory"),
                                    "frozen_file_count": len(guard.archive_bindings),
                                    "listing_unchanged": archive_listing_unchanged,
                                    "touched_file_count": len(guard.archive_before),
                                    "before": {str(path.relative_to(bound["root"])): value for path, value in guard.archive_before.items()},
                                    "after": {str(path.relative_to(bound["root"])): value for path, value in archive_after.items()},
                                    "changed_touched_paths": archive_changed},
            "system_runtime": {"before": bound["system_before"], "after": system_after,
                               "unchanged": system_unchanged, "head_bound_candidate_data": False},
            "access_qualified": not changed and not source_changed and not guard.denied and not archive_changed and archive_listing_unchanged and system_unchanged,
            "publication_authorized": False,
            "freshness_qualified_by_this_helper": False,
            "exact_identity_source_seam": True,
            "identity_data_read_permitted": False,
            "limitations": bound["contract"]["limitations"]}


def _staged_binding_self_test():
    import tempfile
    from types import SimpleNamespace
    with tempfile.TemporaryDirectory(prefix="staged-binding-", dir=Path(__file__).parent) as directory:
        root = Path(directory)
        code = root / "probe.py"
        code.write_text("synthetic source")
        data = root / "synthetic.json"
        data.write_text('{"synthetic":true}')
        entries = {"probe.py": _hash(code)["git_blob"], "synthetic.json": _hash(data)["git_blob"]}
        records = b"".join(("100644 blob " + oid + "\t" + name + "\0").encode() for name, oid in entries.items())
        template = {"binding_mode":"detached_staged_HEAD", "read_files":[{"path":"synthetic.json"}],
                    "source_bindings":{"probe.py":{}}, "protected_code_imports":{},
                    "system_read_files":[{"path":SYSTEM_TIMEZONE},{"path":"runtime"}]}
        check, execute = subprocess.check_output, subprocess.run
        def fake_git(arguments, **kwargs):
            if arguments[2] == "rev-parse":
                return ("1" * 40 + "\n" + "2" * 40 + "\n").encode()
            if arguments[2] == "ls-tree":
                return records
            raise AssertionError("Unexpected staged metadata query")
        try:
            subprocess.check_output = fake_git
            subprocess.run = lambda *a, **k: SimpleNamespace(returncode=1)
            bound = _stage_contract(root, json.loads(json.dumps(template)))
            assert bound["candidate_data_commit"] == "1" * 40 and bound["staged_tree"] == "2" * 40
            assert bound["read_files"][0]["git_blob"] == entries["synthetic.json"]
            assert bound["system_read_files"][1]["path"] == OPTIONAL_STDLIB_ZIP
            code.write_text("uncommitted change")
            try:
                _stage_contract(root, json.loads(json.dumps(template)))
            except ValueError:
                pass
            else:
                raise AssertionError("Uncommitted source accepted")
            subprocess.run = lambda *a, **k: SimpleNamespace(returncode=0)
            try:
                _stage_contract(root, json.loads(json.dumps(template)))
            except ValueError:
                pass
            else:
                raise AssertionError("Attached checkout accepted")
        finally:
            subprocess.check_output, subprocess.run = check, execute


def _self_test():
    _staged_binding_self_test()
    sample = b"100644 blob " + b"a" * 40 + b"\tsynthetic/a.json\0"
    assert _tree_records(sample) == {"synthetic/a.json": "a" * 40}
    for bad in (sample + sample, b"120000 blob " + b"a" * 40 + b"\tsynthetic/a.json\0"):
        try:
            _tree_records(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid staged metadata accepted")

    import encodings.idna  # Resolve the stdlib codec before installing the synthetic IO boundary.
    import socket
    import tempfile
    with tempfile.TemporaryDirectory(prefix="candidate-access-", dir=Path(__file__).parent) as directory:
        top = Path(directory)
        root = top / "candidate"
        data = root / "data/projections/current.json"
        data.parent.mkdir(parents=True)
        data.write_text("synthetic")
        denied_path = root / "data/prospects/raw/not-admitted.json"
        denied_path.parent.mkdir(parents=True)
        denied_path.write_text("synthetic only")
        archive_directory = root / "data/prediction_archive/valucast_prospect_rank_v1"
        archive_directory.mkdir(parents=True)
        archive_file = archive_directory / "2026-01-01.json"
        archive_file.write_text('{"synthetic":true}')
        unknown_archive = archive_directory / "2026-01-02.json"
        unknown_archive.write_text('{"synthetic":true}')
        bad_archive = archive_directory / "2026-01-03.json"
        bad_archive.write_text('{"synthetic":true}')
        archive = {"directory": "data/prediction_archive/valucast_prospect_rank_v1",
                   "files": [{"path": "data/prediction_archive/valucast_prospect_rank_v1/2026-01-01.json",
                              "git_blob": _hash(archive_file)["git_blob"]},
                             {"path": "data/prediction_archive/valucast_prospect_rank_v1/2026-01-03.json",
                              "git_blob": "0" * 40}]}
        output = top / "receipt.json"
        code_directory = root / "projections/data"
        code_directory.mkdir(parents=True)
        (code_directory.parent / "__init__.py").write_text("")
        package_source = code_directory / "__init__.py"
        package_source.write_text("")
        identity_source = code_directory / "identity.py"
        identity_source.write_text("from pathlib import Path\nVALUE = 'synthetic identity code'\ndef forbidden_data():\n    return Path(__file__).with_name('identity.json').read_text()\n")
        (code_directory / "identity.json").write_text('{"synthetic":"not admitted"}')
        (code_directory / "unknown.py").write_text("VALUE = 'must never load'\n")
        code_imports = {
            "projections.data": {"path": "projections/data/__init__.py", "sha256": _hash(package_source)["sha256"], "package": True},
            "projections.data.identity": {"path": "projections/data/identity.py", "sha256": _hash(identity_source)["sha256"], "package": False}}
        system_file = top / "runtime-zoneinfo/America/New_York"
        system_file.parent.mkdir(parents=True)
        system_file.write_text("synthetic public timezone bytes")
        system_other = system_file.with_name("Not_Admitted")
        system_other.write_text("synthetic unadmitted sibling")
        system_before = _system_hash(system_file)
        fake_stdlib = top / "runtime-python/python3.12"
        missing_zip = fake_stdlib.parent / "python312.zip"
        missing_zip.parent.mkdir(parents=True)
        zip_sibling = missing_zip.with_name("python313.zip")
        zip_sibling.write_bytes(b"synthetic unadmitted sibling")
        missing_exposure = denied_path.with_name("prospect_exposure_history.json")
        missing_before = _system_hash(missing_zip)
        scope = {}
        exec(compile("def synthetic_source_probe(path, ignored_secret):\n    return path.read_text()\n",
                     str(root / "synthetic_source_probe.py"), "exec"), scope)
        before = _hash(data)
        guard = _ServingGuard(root, {data, package_source, identity_source, system_file, missing_zip, missing_exposure}, top / "helpers", write_files=(output,), archive=archive)
        guard.optional_runtime_zip = missing_zip.resolve()
        original_bytecode_setting = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        sys.addaudithook(guard.audit)
        finder = _ExactIdentityFinder(root, code_imports, guard)
        sys.meta_path.insert(0, finder)
        sys.path.insert(0, str(root))
        try:
            import importlib
            before_import_denials = len(guard.denied)
            identity_module = importlib.import_module("projections.data.identity")
            assert identity_module.VALUE == "synthetic identity code"
            assert Path(identity_module.__file__).resolve() == identity_source.resolve()
            assert len(guard.denied) == before_import_denials
            assert data.read_text() == "synthetic"
            assert system_file.read_text() == "synthetic public timezone bytes"
            before_missing_denials = len(guard.denied)
            for missing_operation in (lambda: missing_zip.read_bytes(), lambda: os.listdir(missing_zip),
                                      lambda: missing_exposure.read_text()):
                try:
                    missing_operation()
                except FileNotFoundError:
                    pass
                else:
                    raise AssertionError("Missing optional input did not keep the real OS error")
            assert len(guard.denied) == before_missing_denials
            assert sorted(path.name for path in archive_directory.glob("*.json")) == ["2026-01-01.json", "2026-01-02.json", "2026-01-03.json"]
            assert archive_file.read_text() == '{"synthetic":true}'
            assert len(guard.archive_before) == 1
            for operation in (lambda: scope["synthetic_source_probe"](denied_path, "PRIVATE_ROW_SENTINEL"), lambda: data.write_text("bad"),
                              lambda: list(data.parent.iterdir()),
                              lambda: socket.getaddrinfo("never-contact.invalid", 443),
                              lambda: unknown_archive.read_text(),
                              lambda: list(archive_directory.rglob("*.json")), lambda: bad_archive.read_text(),
                              lambda: list(code_directory.iterdir()), lambda: identity_module.forbidden_data(),
                              lambda: importlib.import_module("projections.data.unknown"),
                              lambda: system_file.write_text("bad"), lambda: system_other.read_text(),
                              lambda: list(system_file.parent.iterdir()), lambda: missing_zip.write_bytes(b"bad"),
                              lambda: zip_sibling.read_bytes(), lambda: list(missing_zip.parent.iterdir())):
                try:
                    operation()
                except PermissionError:
                    pass
                else:
                    raise AssertionError("Denied operation unexpectedly succeeded")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text('{"synthetic":true}')
            assert _hash(data) == before
            assert len(guard.denied) == 16, dict(guard.events)
            assert _system_hash(missing_zip) == missing_before
            assert not missing_zip.exists() and not missing_exposure.exists()
            assert guard.events["optional_stdlib_zip_lookup"] == 1
            assert _system_hash(system_file) == system_before
            assert "PRIVATE_ROW_SENTINEL" not in json.dumps(guard.denied)
            assert any(item["source_frames"] and item["source_frames"][0]["function"] == "synthetic_source_probe"
                       and item["audit_event"] == "open" for item in guard.denied)
            assert all(set(frame) == {"path", "function", "line"} for item in guard.denied for frame in item["source_frames"])
            assert guard.events["network_attempt"] == 1
            assert guard.events["undeclared_read"] == 5
            assert guard.events["write_attempt"] == 3
            assert guard.events["directory_enumeration"] == 4
            assert guard.events["archive_listing_pattern"] == 1
            assert guard.events["archive_identity_mismatch"] == 1
            assert guard.events["idempotent_scratch_mkdir"] == 1
            assert guard.events["protected_code_import"] == 1
            assert guard.events["exact_code_import"] == 2
            assert _hash(archive_file) == guard.archive_before[archive_file.resolve()]
        finally:
            guard.active = False
            sys.meta_path.remove(finder)
            sys.path.remove(str(root))
            sys.dont_write_bytecode = original_bytecode_setting
            for name in ("projections.data.identity", "projections.data", "projections"):
                sys.modules.pop(name, None)
        print(json.dumps({"self_test": "passed", "synthetic_only": True, "expected_denials": 16, "prior_thirteen_denials_retained": True, "genuine_optional_absence_preserved": True, "only_selected_archive_hashed": True, "exact_source_import_without_data_listing": True, "system_file_exact_read_only": True, "source_frames_no_private_arguments": True}))


if __name__ == "__main__":
    if sys.argv[1:] != ["--self-test"]:
        raise SystemExit("Use from the external controller; standalone mode is --self-test only")
    _self_test()
