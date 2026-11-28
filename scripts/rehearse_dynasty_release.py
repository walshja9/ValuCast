"""Stage and verify an isolated Dynasty-only bundle. Never publish it."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


GATE = "scripts/validate_dynasty_only_release.py"
DRIVER = "scripts/run_daily_public_build.py"
PROBE = "scripts/probe_dynasty_buy_suppression.py"
STAGER = "scripts/stage_daily_public_bundle.sh"
MONITOR = "scripts/validate_valucast_buys_monitor.py"
MONITOR_ARTIFACT = "data/models/valucast_prospect_buys_monitor.json"
GOVERNOR_ARTIFACT = "data/models/valucast_quality_governor.json"
PUBLIC_SNAPSHOT = "data/public/public_dynasty_snapshot.json"


class Blocked(RuntimeError):
    pass


def require(ok, reason):
    if not ok:
        raise Blocked(reason)


def git(root, *args, env=None):
    return subprocess.check_output(["git", "-C", str(root), *args], env=env)


def git_text(root, *args, env=None):
    return git(root, *args, env=env).decode().strip()


def fingerprint(root, tree):
    return {"tree": tree, "tree_sha256": hashlib.sha256(git(root, "cat-file", "tree", tree)).hexdigest()}


def stage(root, scratch, *, staged_copy=False):
    index = scratch / "index"
    require(not index.exists(), "staging_index_already_exists")
    env = {**os.environ, "GIT_INDEX_FILE": str(index)}
    try:
        git(root, "read-tree", "HEAD", env=env)
        if staged_copy:
            git(root, "add", "--all", "--", ".", env=env)
        else:
            subprocess.run(["bash", STAGER], cwd=root, env=env, check=True)
        return fingerprint(root, git_text(root, "write-tree", env=env))
    finally:
        index.unlink(missing_ok=True)


def current_master(root):
    master = subprocess.check_output(
        ["gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/git/ref/heads/master",
         "--jq", ".object.sha"],
        text=True,
    ).strip()
    head = git_text(root, "rev-parse", "HEAD")
    require(master == os.environ.get("VALUCAST_REHEARSAL_MASTER", head), "master_moved")
    git(root, "merge-base", "--is-ancestor", master, head)
    return master


def canonical_prior(root, master):
    path = Path(os.environ["VALUCAST_PREVIOUS_PUBLIC_SNAPSHOT"])
    actual = git_text(root, "hash-object", "--no-filters", "--", str(path))
    require(actual == git_text(root, "rev-parse", f"{master}:{PUBLIC_SNAPSHOT}"), "canonical_prior_mismatch")
    return actual


def passed_command(root, command, *args):
    env = {key: value for key, value in os.environ.items() if key not in {"GH_TOKEN", "GITHUB_TOKEN"}}
    return subprocess.run(
        [sys.executable, "-B", command, *map(str, args)],
        cwd=root, capture_output=True, text=True, check=False,
        env={
            **env,
            "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
            "PYTHONDONTWRITEBYTECODE": "1",
            "VALUCAST_ANALYTICS_DB": "",
            "VALUCAST_USE_PUBLIC_SNAPSHOT": "1",
            "SCOREBOARD_HOLD": "0",
        },
    )


def ordinary_buy_veto(root):
    result = passed_command(root, DRIVER, "--only", "validate")
    lines = result.stdout.splitlines()
    last = next((index for index in reversed(range(len(lines))) if lines[index].startswith("+ ")), None)
    expected = [
        f"VALUCAST BUYS MONITOR VALIDATION FAILED for {root / MONITOR_ARTIFACT}:",
        "  - monitoring.feeds_live_buys must be true",
        "  - monitoring.ready_for_live_consumers must be true",
    ]
    require(
        result.returncode == 1 and last is not None and lines[last].endswith(" " + MONITOR)
        and lines[last + 1:] == expected,
        "ordinary_buy_veto_unverified",
    )
    return {"exit_code": result.returncode, "stopped_at": MONITOR}


def read_json_output(result, reason):
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        payload = {}
    require(isinstance(payload, dict), reason)
    return payload


def verify_publish_boundary(root, scratch, qualification, master, source, day):
    require(
        qualification.get("qualified") is True
        and qualification.get("master") == master
        and qualification.get("source") == source
        and qualification.get("date") == day
        and qualification.get("ordinary_buy_veto") == {"exit_code": 1, "stopped_at": MONITOR},
        "qualification_missing_or_stale",
    )
    actual = stage(root, scratch)
    require(actual == qualification.get("bundle"), "bundle_fingerprint_mismatch")
    return actual


def qualify(root, scratch, receipt):
    sealed = stage(root, scratch)
    receipt["bundle"] = sealed
    env = {**os.environ}
    for role in ("AUTHOR", "COMMITTER"):
        env[f"GIT_{role}_NAME"] = "ValuCast Dynasty Rehearsal"
        env[f"GIT_{role}_EMAIL"] = "rehearsal@valucast.invalid"
    commit = git_text(root, "commit-tree", sealed["tree"], "-p", receipt["source"],
                      "-m", "ValuCast staged Dynasty rehearsal", env=env)
    checkout = scratch / "staged"
    git(root, "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", str(checkout), commit)
    try:
        require(stage(checkout, scratch, staged_copy=True) == sealed, "staged_checkout_mismatch")
        receipt["ordinary_buy_veto"] = ordinary_buy_veto(checkout)
        gate = passed_command(checkout, GATE)
        verdict = read_json_output(gate, "invalid_dynasty_validator_receipt")
        receipt["dynasty_gate"] = {
            key: verdict.get(key) for key in (
                "date", "dynasty_eligible", "issues", "checks", "policy_input_sha256",
            )
        }
        require(
            gate.returncode == 0 and verdict.get("dynasty_eligible") is True
            and verdict.get("publication_authorized") is False
            and verdict.get("date") == receipt["date"],
            "dynasty_validation_failed",
        )
        governor = json.loads((checkout / GOVERNOR_ARTIFACT).read_bytes())
        [shape] = [check["metrics"] for check in governor["checks"] if check["id"] == "prospect_top_board_role_shape"]
        receipt["surface_readiness"] = governor["surface_readiness"]
        receipt["prospect_pitcher_counts"] = {
            "top25": shape["top25_pitcher_count"], "top50": shape["top50_pitcher_count"],
            "limit_top25": 7, "limit_top50": 15,
        }
        surface_result = passed_command(checkout, PROBE, "--run", scratch)
        consumer = read_json_output(surface_result, "invalid_surface_receipt")
        receipt["buy_suppression"] = consumer
        require(
            surface_result.returncode == 0 and consumer.get("qualified") is True
            and consumer.get("candidate_commit") == commit and consumer.get("candidate_tree") == sealed["tree"],
            "buy_suppression_failed",
        )
        require(stage(checkout, scratch, staged_copy=True) == sealed, "staged_bytes_changed_during_validation")
        receipt["qualified"] = True
    finally:
        git(root, "worktree", "remove", "--force", str(checkout))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("qualify", "would-publish"))
    args = parser.parse_args()
    require(os.environ.get("VALUCAST_DYNASTY_REHEARSAL") == "true", "dynasty_rehearsal_disabled")
    require(os.environ.get("GITHUB_ACTIONS") == "true", "isolated_workflow_required")
    root = Path.cwd().resolve()
    runner = Path(os.environ["RUNNER_TEMP"]).resolve()
    require(not runner.is_relative_to(root), "runner_scratch_must_be_outside_checkout")
    scratch = runner / "dynasty-rehearsal"
    if args.phase == "qualify":
        scratch.mkdir()
    path = scratch / ("qualification.json" if args.phase == "qualify" else "receipt.json")
    receipt = {
        "phase": args.phase,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "date": os.environ["VALUCAST_REFRESH_DATE"],
        "publication_authorized": False,
        "would_publish": False,
        "qualified": False,
    }
    try:
        receipt["source"] = git_text(root, "rev-parse", "HEAD")
        receipt["master"] = current_master(root)
        receipt["canonical_prior_blob"] = canonical_prior(root, receipt["master"])
        require(datetime.now(timezone.utc).date().isoformat() == receipt["date"], "refresh_utc_day_changed")
        if args.phase == "qualify":
            qualify(root, scratch, receipt)
            require(canonical_prior(root, receipt["master"]) == receipt["canonical_prior_blob"], "canonical_prior_changed")
        else:
            raw = (scratch / "qualification.json").read_bytes()
            qualification_sha256 = hashlib.sha256(raw).hexdigest()
            require(qualification_sha256 == os.environ.get("VALUCAST_QUALIFICATION_SHA256"),
                    "qualification_receipt_digest_mismatch")
            qualification = json.loads(raw)
            require(qualification.get("run_id") == receipt["run_id"], "qualification_run_mismatch")
            require(qualification.get("canonical_prior_blob") == receipt["canonical_prior_blob"],
                    "canonical_prior_changed")
            receipt["bundle"] = verify_publish_boundary(
                root, scratch, qualification, receipt["master"], receipt["source"], receipt["date"],
            )
            require(current_master(root) == receipt["master"], "master_moved")
            require(datetime.now(timezone.utc).date().isoformat() == receipt["date"], "refresh_utc_day_changed")
            receipt["qualification_sha256"] = qualification_sha256
            receipt["qualified"] = True
            receipt["would_publish"] = True
    except Blocked as exc:
        receipt["stop"] = str(exc)
        receipt["qualified"] = False
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as exc:
        receipt["stop"] = type(exc).__name__
        receipt["qualified"] = False
    path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if args.phase == "qualify" and receipt["qualified"]:
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as outputs:
            outputs.write(f"qualification_sha256={hashlib.sha256(path.read_bytes()).hexdigest()}\n")
    print(f"Dynasty rehearsal {args.phase}: {receipt.get('stop', 'passed')}")
    return int(not receipt["qualified"])


if __name__ == "__main__":
    raise SystemExit(main())
