"""Offline harness contracts; no product imports, data access or network."""
import importlib.util
import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "scripts/rehearse_flip.py"


def harness():
    spec = importlib.util.spec_from_file_location("rehearse_flip_test", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_only_target_constant_changes():
    source = "CONTEXT_SEASON = 2026\nTARGET_SEASON = 2027\n"
    assert harness().baseline_source(source) == source.replace("TARGET_SEASON = 2027", "TARGET_SEASON = 2026")


def test_continues_after_inner_failure(tmp_path):
    module = harness()
    table = tmp_path / "steps.csv"
    env = dict(module.os.environ)
    first = module.run_step("failed", (sys.executable, "-c", "raise RuntimeError('private payload')"), tmp_path, env, table, tmp_path)
    second = module.run_step("next", (sys.executable, "-c", "print(3)"), tmp_path, env, table, tmp_path)
    assert first == 1 and second == 0
    text = table.read_text()
    assert "private payload" not in text
    assert "RuntimeError" in text and "next" in text


def test_wrapper_runs_real_stage_and_keeps_all_inner_failures(tmp_path):
    module = harness()
    fixture = tmp_path / "scripts"
    fixture.mkdir()
    (fixture / "run_daily_public_build.py").write_text(
        "import subprocess, sys\n"
        "def main(args):\n"
        "    subprocess.run([sys.executable, '-c', 'raise ValueError(123)'], check=True)\n"
        "    subprocess.run([sys.executable, '-c', 'print(4)'], check=True)\n"
        "    return 0\n"
    )
    table = tmp_path / "steps.csv"
    assert module.run_daily_stage(tmp_path, "build", table, tmp_path) == 1
    assert len(table.read_text().splitlines()) == 3


def test_artifact_allowlist_rejects_raw_outputs(tmp_path):
    module = harness()
    for name in module.ARTIFACT_FILES:
        (tmp_path / name).write_text("name,type,role,age,rank,value\n" if name.startswith(("board_", "redraft_")) else "")
    module.validate_artifact(tmp_path)
    (tmp_path / "raw.json").write_text("[]")
    try:
        module.validate_artifact(tmp_path)
    except ValueError:
        pass
    else:
        raise AssertionError("raw artifact was accepted")
