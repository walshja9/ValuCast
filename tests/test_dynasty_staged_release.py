"""Exercise the rehearsal's local staged boundary with disposable Git trees."""

import os
from pathlib import Path
import shutil
import subprocess

import pytest

from scripts import rehearse_dynasty_release as rehearsal


SNAPSHOT = "data/public/public_dynasty_snapshot.json"
DAY = "2026-11-27"


def git(root, *args):
    result = subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    return result.stdout.strip()


@pytest.fixture
def staged_candidate(tmp_path, monkeypatch):
    if not shutil.which("git"):
        pytest.skip("Git is required for the staged tree fixture")
    root, scratch = tmp_path / "repo", tmp_path / "scratch"
    root.mkdir()
    scratch.mkdir()
    if os.name == "nt":
        exec_path = Path(git(root, "--exec-path").decode())
        # Prefer Git for Windows Bash over the Windows Subsystem for Linux shim.
        bash = next((p / "bin/bash.exe" for p in exec_path.parents if (p / "bin/bash.exe").is_file()), None)
        if bash is not None:
            monkeypatch.setenv("PATH", str(bash.parent) + os.pathsep + os.environ["PATH"])
    if not shutil.which("bash"):
        pytest.skip("Bash is required for the staged tree fixture")

    git(root, "-c", "init.templateDir=", "init", "-q")
    snapshot = root / SNAPSHOT
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text('{"fixture":"baseline"}\n', encoding="utf-8")
    stager = root / rehearsal.STAGER
    stager.parent.mkdir(parents=True)
    stager.write_text(f"set -eu\ngit add -- {SNAPSHOT}\n", encoding="utf-8", newline="\n")
    (root / "unrelated.txt").write_text("baseline\n", encoding="utf-8")
    git(root, "add", "--", SNAPSHOT, rehearsal.STAGER, "unrelated.txt")
    git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "commit", "-qm", "Synthetic release fixture")
    source = git(root, "rev-parse", "HEAD").decode()
    index = (root / ".git/index").read_bytes()
    snapshot.write_text('{"fixture":"candidate"}\n', encoding="utf-8")
    (root / "unrelated.txt").write_text("out-of-scope local change\n", encoding="utf-8")
    fingerprint = rehearsal.stage(root, scratch)
    qualification = {
        "qualified": True, "master": source, "source": source, "date": DAY,
        "ordinary_buy_veto": {"exit_code": 1, "stopped_at": rehearsal.MONITOR},
        "bundle": fingerprint,
    }
    return root, scratch, qualification, index


def test_stage_seals_exact_allowlisted_bytes_without_touching_primary_index(staged_candidate):
    root, scratch, qualification, index = staged_candidate
    source = qualification["source"]
    bundle = qualification["bundle"]

    assert bundle["tree"] != git(root, "rev-parse", "HEAD^{tree}").decode()
    assert git(root, "show", bundle["tree"] + ":" + SNAPSHOT) == b'{"fixture":"candidate"}'
    assert git(root, "show", bundle["tree"] + ":unrelated.txt") == b"baseline"
    assert rehearsal.verify_publish_boundary(root, scratch, qualification, source, source, DAY) == bundle
    assert not (scratch / "index").exists()
    assert (root / ".git/index").read_bytes() == index


@pytest.mark.parametrize("field", ["master", "source", "date", "ordinary_buy_veto", "qualified"])
def test_would_publish_rejects_stale_or_unproven_qualification(staged_candidate, field):
    root, scratch, qualification, _ = staged_candidate
    source = qualification["source"]
    qualification[field] = None

    with pytest.raises(rehearsal.Blocked, match="qualification_missing_or_stale"):
        rehearsal.verify_publish_boundary(root, scratch, qualification, source, source, DAY)


def test_would_publish_rejects_artifact_changed_after_validation(staged_candidate):
    root, scratch, qualification, index = staged_candidate
    source = qualification["source"]
    (root / SNAPSHOT).write_text('{"fixture":"changed after validation"}\n', encoding="utf-8")

    with pytest.raises(rehearsal.Blocked, match="bundle_fingerprint_mismatch"):
        rehearsal.verify_publish_boundary(root, scratch, qualification, source, source, DAY)

    assert not (scratch / "index").exists()
    assert (root / ".git/index").read_bytes() == index
