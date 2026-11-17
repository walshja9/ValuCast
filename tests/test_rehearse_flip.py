"""Offline harness contracts; no product imports, data access or network."""
import importlib.util
import csv
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


def test_only_harness_authored_exception_messages_are_public():
    from scripts.rehearsal_errors import HarnessError, exception_evidence

    for exc, visible in ((HarnessError("Board missing or empty"), True),
                         (ValueError("private feed payload"), False)):
        try:
            raise exc
        except Exception as caught:
            detail = exception_evidence(caught)
        assert detail["error_type"] == type(exc).__name__
        assert detail["final_frame"].startswith("tests/test_rehearse_flip.py:")
        assert ("error_message" in detail) == visible
        assert "private feed payload" not in str(detail)


def test_failed_inner_script_has_class_and_final_frame_in_summary(tmp_path):
    module = harness()
    script = tmp_path / "inner.py"
    script.write_text("raise RuntimeError('private feed payload')\n")
    table = tmp_path / "baseline_steps.csv"
    assert module.run_step("build: inner.py", (sys.executable, str(script)), tmp_path,
                           dict(module.os.environ), table, tmp_path) == 1
    with table.open(newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["exception_class"] == "RuntimeError"
    assert row["final_frame"].endswith("inner.py:1")
    assert row["script"].endswith("inner.py")
    summary = module.failure_summary(tmp_path)
    assert "RuntimeError" in summary and "inner.py:1" in summary
    assert "private feed payload" not in summary


def test_probe_diagnostics_are_opt_in_and_repo_output_stays_redacted(tmp_path):
    module = harness()
    source = ("import json\nprint(json.dumps({'ok': False, 'error_type': 'HarnessError', "
              "'error_message': 'Required startup status mismatch', "
              "'final_frame': 'scripts/rehearse_flip_checks.py:10'}))\nraise SystemExit(1)")
    table = tmp_path / "candidate_steps.csv"
    for own in (False, True):
        module.run_step(str(own), (sys.executable, "-c", source), tmp_path,
                        dict(module.os.environ), table, tmp_path, harness_check=own)
    with table.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert "Required startup status mismatch" not in rows[0]["last_error_line"]
    assert "Required startup status mismatch" in rows[1]["last_error_line"]
    assert rows[1]["exception_class"] == "HarnessError"
    assert rows[1]["final_frame"] == "scripts/rehearse_flip_checks.py:10"


def test_rehearsal_checkout_has_history_and_no_credentials():
    workflow = (SOURCE.parents[1] / ".github/workflows/steamer-feed-check.yml").read_text()
    assert "actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5" in workflow
    assert "          fetch-depth: 0\n          persist-credentials: false" in workflow


def test_feed_checker_failure_records_safe_nested_evidence(monkeypatch):
    from types import ModuleType
    from scripts import rehearse_flip_checks as checks

    scraper = ModuleType("scraper")
    fangraphs = ModuleType("scraper.fangraphs")
    fangraphs.fetch_projections = lambda *args: [{"opaque": "private feed row"}]
    monkeypatch.setitem(sys.modules, "scraper", scraper)
    monkeypatch.setitem(sys.modules, "scraper.fangraphs", fangraphs)
    output = ('Traceback (most recent call last):\n'
              '  File "scripts/check_steamer_season.py", line 42, in main\n'
              'RuntimeError: private feed row\n')
    monkeypatch.setattr(checks.subprocess, "run", lambda *args, **kwargs:
                        checks.subprocess.CompletedProcess(args[0], 1, "", output))
    result = checks.feed()
    assert not result["ok"]
    assert result["checker"]["script"] == "scripts/check_steamer_season.py"
    assert result["checker"]["error_type"] == "RuntimeError"
    assert result["checker"]["final_frame"] == "scripts/check_steamer_season.py:42"
    assert "private feed row" not in str(result)
