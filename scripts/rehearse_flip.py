"""Two-pass, read-only hosted flip rehearsal. Never run the pipeline locally.

Ported from rehearsal/2027-pipeline and rehearsal/injury-final's step recorder.
Raw inputs and process logs stay in RUNNER_TEMP; upload only ARTIFACT_FILES.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ARTIFACT_FILES = {
    "baseline_steps.csv", "candidate_steps.csv", "board_before.csv", "board_after.csv",
    "redraft_before.csv", "redraft_after.csv", "summary.md",
}
INPUT_STEPS = [
    ("-m", "scraper.refresh"),
    ("scripts/fetch_statcast_percentiles.py",),
    ("scripts/refresh_milb_season_stats.py",),
    ("scripts/refresh_milb_season_stats.py", "--stats-type", "byDateRange", "--window-days", "30",
     "--output", "data/prospects/raw/milb_recent_stats.json"),
    ("scripts/refresh_prospect_orgs.py", "--write"),
    ("scripts/build_valucast_prospect_inputs.py", "--refresh-service-cache"),
]


def baseline_source(source):
    result, count = re.subn(r"(?m)^TARGET_SEASON = 2027$", "TARGET_SEASON = 2026", source)
    if count != 1:
        raise ValueError("Expected exactly one TARGET_SEASON = 2027 constant")
    return result


def last_error(text):
    """Retain the last exception class; messages can contain upstream rows."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "process failed without output"
    match = re.match(r"([\w.]+(?:Error|Exception))(?::|$)", lines[-1])
    if match:
        return match[1] + ": [message redacted]"
    return "[last line redacted; sha256=" + hashlib.sha256(lines[-1].encode()).hexdigest() + "]"


def append_row(table, name, code, seconds, error=""):
    exists = table.exists()
    with table.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if not exists:
            writer.writerow(("name", "exit_code", "seconds", "last_error_line"))
        writer.writerow((name, code, round(seconds, 3), error))


def run_step(name, command, root, env, table, private, timeout=None):
    started = time.monotonic()
    log = private / (hashlib.sha256(name.encode()).hexdigest() + ".log")
    with log.open("w", encoding="utf-8") as handle:
        try:
            done = subprocess.run(command, cwd=root, env=env, stdout=handle,
                                  stderr=subprocess.STDOUT, timeout=timeout, check=False)
            code = done.returncode
        except subprocess.TimeoutExpired:
            code = 124
            handle.write("\nTimeoutError: step exceeded deadline\n")
        except OSError as exc:
            code = 125
            handle.write("\n" + type(exc).__name__ + ": process could not start\n")
    error = last_error(log.read_text(encoding="utf-8", errors="replace")) if code else ""
    append_row(table, name, code, time.monotonic() - started, error)
    # Public process output contains numbers only, never subprocess text.
    print(code, round(time.monotonic() - started, 3), flush=True)
    return code


def run_daily_stage(root, stage, table, private):
    """Call the real orchestrator, changing only its stop-on-failure policy."""
    spec = importlib.util.spec_from_file_location("daily_rehearsal", root / "scripts/run_daily_public_build.py")
    daily = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(daily)
    real_run = subprocess.run
    failures = []

    def continuing_run(command, **kwargs):
        # run_step uses the real function while this wrapper is installed.
        subprocess.run = real_run
        try:
            code = run_step(stage + ": " + " ".join(map(str, command[1:])), command, root,
                            os.environ.copy(), table, private, kwargs.get("timeout"))
        finally:
            subprocess.run = continuing_run
        failures.append(code)
        return subprocess.CompletedProcess(command, code)

    subprocess.run = continuing_run
    try:
        daily.main(["--only", stage])
    finally:
        subprocess.run = real_run
    return int(any(failures))


def validate_artifact(out):
    actual = {path.name for path in out.iterdir()}
    if actual != ARTIFACT_FILES or any(not path.is_file() for path in out.iterdir()):
        raise ValueError("Artifact contains missing or unapproved files")
    for name in ARTIFACT_FILES - {"summary.md", "baseline_steps.csv", "candidate_steps.csv"}:
        with (out / name).open(encoding="utf-8", newline="") as handle:
            if next(csv.reader(handle), None) != ["name", "type", "role", "age", "rank", "value"]:
                raise ValueError("Board columns differ from the public allowlist")


def tree_hash(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


def replace_tree(source, destination):
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def hosted(root):
    if (os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("GITHUB_REF") != "refs/heads/rehearsal/flip-2027-20261116"):
        raise RuntimeError("Pipeline mode is restricted to the throwaway hosted branch")
    from rehearse_proxy import Replay
    from summarize_rehearsal import export_boards, summarize

    temp = Path(os.environ["RUNNER_TEMP"]) / "flip-private"
    temp.mkdir()
    out = Path(os.environ["REHEARSAL_OUT"])
    out.mkdir(parents=True)
    if any(out.iterdir()):
        raise RuntimeError("Artifact directory must start empty")
    committed = temp / "committed"
    committed.mkdir()
    # Snapshot this checkout only, never another rehearsal branch's data.
    for path in ("data", "projections/runs", "projections/data"):
        shutil.copytree(root / path, committed / path)
    inhouse = Path("projections/runs/valucast_hp_2026_v2")
    committed_hash = tree_hash(committed / inhouse)
    season_path = root / "scraper/season.py"
    original = season_path.read_text(encoding="utf-8")
    baseline = baseline_source(original)
    replay = Replay()
    env = {**os.environ, "REHEARSAL_PROXY": replay.base,
           "REHEARSAL_COMMITTED_ROOT": str(committed),
           "REHEARSAL_COMMITTED_METADATA": str(committed / "data/projections/metadata.json"),
           "PYTHONPATH": os.pathsep.join((str(root / "scripts/rehearsal_site"), str(root / "src"), str(root))),
           "PYTHONDONTWRITEBYTECODE": "1", "VALUCAST_SCOUTING_LLM": "0",
           "VALUCAST_BUYS_REVIEW_APPROVED": "1"}
    notes = []
    exports = {}
    failures = []

    def check(label, mode, table):
        command = (sys.executable, str(root / "scripts/rehearse_flip_checks.py"), *mode)
        code = run_step(label, command, root, env, table, temp)
        log = temp / (hashlib.sha256(label.encode()).hexdigest() + ".log")
        # Probe commands emit sanitized JSON, not process logs or source rows.
        try:
            detail = json.loads(log.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            detail = {"exit_code": code, "detail": "probe did not produce a complete result"}
        notes.append((label, detail))
        failures.append(code)

    try:
        table = out / "candidate_steps.csv"
        check("candidate committed startup", ("startup", "committed"), table)
        check("candidate empty-feed fault", ("fault",), table)
        check("candidate full-season feed", ("feed",), table)
        for label, text, board_label in (("baseline", baseline, "before"), ("candidate", original, "after")):
            for path in ("data", "projections/runs", "projections/data"):
                replace_tree(committed / path, root / path)
            season_path.write_text(text, encoding="utf-8")
            # Do not allow stale .pyc files to conceal a same-size season patch.
            for cache in (root / "scraper").glob("__pycache__/season.*.pyc"):
                cache.unlink()
            table = out / (label + "_steps.csv")
            for step in INPUT_STEPS:
                failures.append(run_step("input: " + " ".join(step), (sys.executable, *step), root, env, table, temp))
                if step == ("-m", "scraper.refresh"):
                    check(label + " requested feed rows", ("refresh-counts",), table)
            for stage in ("build", "validate"):
                if stage == "validate":
                    step = ("scripts/build_prospect_rank_history.py",)
                    failures.append(run_step("after build: " + step[0], (sys.executable, *step), root, env, table, temp))
                failures.append(run_step("stage: " + stage,
                    (sys.executable, str(root / "scripts/rehearse_flip.py"), "--stage", stage,
                     "--table", str(table), "--private", str(temp)), root, env, table, temp))
            # Execute H+P genuinely, then restore the exact committed 2026 run for startup (c).
            replace_tree(committed / inhouse, root / inhouse)
            intact = tree_hash(root / inhouse) == committed_hash
            append_row(table, "committed 2026 in-house run restored", int(not intact), 0)
            failures.append(int(not intact))
            try:
                exports[board_label] = export_boards(root, out, board_label)
                append_row(table, "export boards", 0, 0)
            except Exception as exc:
                failures.append(1)
                append_row(table, "export boards", 1, 0, type(exc).__name__ + ": [message redacted]")
            if label == "candidate":
                check("candidate refreshed startup", ("startup", "refreshed"), table)
                check("candidate in-house isolation", ("isolation",), table)
    finally:
        season_path.write_text(original, encoding="utf-8")
        replace_tree(committed / inhouse, root / inhouse)
        counts = replay.counts()
        replay.close()

    if len(exports) == 2:
        summary = summarize(out, exports["before"], exports["after"])
        unchanged = exports["before"]["prospects"] == exports["after"]["prospects"]
        append_row(out / "candidate_steps.csv", "prospect score and rank invariance", int(not unchanged), 0)
        failures.append(int(not unchanged))
    else:
        summary = "# Flip rehearsal\n\nBoard export failed; no board comparison is claimed.\n"
    summary += "\n## Checks\n\n"
    for label, detail in notes:
        summary += "### " + label + "\n\n```json\n" + json.dumps(detail, indent=2, sort_keys=True) + "\n```\n\n"
    summary += "## Execution\n\n"
    summary += "- Baseline patches only TARGET_SEASON from 2027 to 2026; candidate code is unchanged.\n"
    summary += "- Each pass starts from this checkout's committed data, H+P runs and projection identity inputs.\n"
    summary += "- Real H+P build output is used by downstream build stages, then the committed 2026 run is restored before startup checks.\n"
    summary += "- LLM generation is disabled: no secrets are supplied. This is not paid scouting-generation evidence.\n"
    summary += "- Error messages are redacted to exception class or last-line digest. Raw subprocess logs and feed bodies are not uploaded.\n"
    summary += "- External HTTP replay counts: " + json.dumps(counts, sort_keys=True) + ".\n"
    summary += "- Failed outer steps/checks: " + str(sum(bool(code) for code in failures)) + ". See step tables for every inner failure.\n"
    (out / "summary.md").write_text(summary, encoding="utf-8")
    validate_artifact(out)
    print(len(failures), sum(bool(code) for code in failures), flush=True)
    return int(any(failures))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("build", "validate"))
    parser.add_argument("--table", type=Path)
    parser.add_argument("--private", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.stage:
        if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("REHEARSAL_PROXY"):
            raise RuntimeError("Stages are hosted-only")
        return run_daily_stage(root, args.stage, args.table, args.private)
    return hosted(root)


if __name__ == "__main__":
    raise SystemExit(main())
