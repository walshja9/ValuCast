"""Break MLB lookups on a real socket and run the real daily build step. Throwaway branch only: no push, no deploy.

Each scenario runs scripts/run_daily_public_build.py's own run_stage on the unmodified availability step, followed
by a marker step that shows whether the build carried on. Prints IDs and counts only.
"""

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.rehearse_proxy import Replay, kind  # noqa: E402

out = Path(os.environ["REHEARSAL_OUT"])
out.mkdir(parents=True, exist_ok=True)
temp = Path(os.environ["RUNNER_TEMP"])
ARTIFACT = ROOT / "data/models/valucast_mlb_availability.json"
SNAPSHOT = ROOT / "data/public/public_dynasty_snapshot.json"
METADATA = ROOT / "data/projections/metadata.json"
MARKER = temp / "next_step_ran"
NEXT_YEAR = "2027-03-01"
CHILD = (
    "import scripts.run_daily_public_build as b;"
    "b.STAGES['build']=[('scripts/build_mlb_availability.py',),('-c',\"open(r'%s','w').close()\")];"
    "b.main(['--only','build'])" % MARKER
)


def git(*args):
    return subprocess.run(("git", *args), cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact():
    payload = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    payload.pop("generated_at", None)
    return payload


def build(replay, small=False):
    MARKER.unlink(missing_ok=True)
    env = {**os.environ, "REHEARSAL_MLB_PROXY": replay.base,
           "PYTHONPATH": f"{ROOT}/scripts/rehearsal_site:{os.environ.get('PYTHONPATH', '')}"}
    if small:
        # A cut-down feed is the point of these scenarios, so the feed-collapse guard would stop them for another reason.
        env["VALUCAST_SKIP_AVAILABILITY_RATIO_GUARD"] = "1"
    started = time.time()
    done = subprocess.run((sys.executable, "-c", CHILD), cwd=ROOT, env=env, text=True, capture_output=True,
                          errors="replace", timeout=900)
    lines = [line for line in (done.stdout + done.stderr).splitlines() if line.strip()]
    causes = [line for line in lines if "Error" in line and "CalledProcessError" not in line]
    return dict(exit=done.returncode, seconds=round(time.time() - started, 1), marker=MARKER.exists(),
                last_line=(causes[-1] if causes else lines[-1] if lines else "")[:240])


def counted(which, rule):
    """Fault by the call number of one lookup kind, starting at 1."""
    state = {"n": 0}

    def fault(path, replay):
        if kind(path) != which:
            return None
        state["n"] += 1
        return rule(state["n"], path)
    return fault


def days(count):
    rows = [{"date": f"2027-04-{day:02d}", "games": [{"status": {"detailedState": "Final"}}]} for day in range(1, count + 1)]
    return json.dumps({"dates": rows}).encode("utf-8")


def next_season(body):
    def fault(path, replay):
        return body if kind(path) == "schedule" and "season=2027" in path else None
    return fault


def log_fault(plan, feed=None):
    """Fail these game-log call numbers, counted per season, as {2026: {1}, 2027: {5}}."""
    seen = {}

    def fault(path, replay):
        which = kind(path)
        if which == "transactions" and feed is not None:
            return feed
        year = next((year for year in plan if f"season={year}" in path), None)
        if which != "logs" or year is None:
            return None
        seen[year] = seen.get(year, 0) + 1
        return "500" if seen[year] in plan[year] else None
    return fault


def season_calls(replay, year):
    return sum(1 for path in replay.calls if kind(path) == "logs" and f"season={year}" in path)


results = []
problems = []
control = Replay()
first = build(control)
if first["exit"]:
    print("control failed", first, flush=True)
    raise SystemExit(1)
store = control.store
control_payload = artifact()
control_hold = control_payload["validation"]["offseason_hold"]
now_calls = control.count("logs")
control.close()
git("add", "-A")
git("-c", "user.name=rehearsal", "-c", "user.email=rehearsal@invalid", "commit", "-qm", "restore point, never pushed")
restore = git("rev-parse", "HEAD")
good_artifact, good_snapshot = sha(ARTIFACT), sha(SNAPSHOT)
real_as_of = json.loads(METADATA.read_text(encoding="utf-8"))["as_of"]
print("control", first, control_hold, "as_of", real_as_of, flush=True)


def fresh(as_of=None):
    git("reset", "--hard", restore)
    git("clean", "-fdq")
    if as_of:
        meta = json.loads(METADATA.read_text(encoding="utf-8"))
        meta["as_of"] = as_of
        METADATA.write_text(json.dumps(meta), encoding="utf-8")


def changed_files():
    # metadata.json is the scenario's own as-of edit; the transaction cache and archive are never served on failure.
    status = subprocess.run(("git", "status", "--porcelain"), cwd=ROOT, check=True, text=True, capture_output=True).stdout
    return sorted(line[3:] for line in status.splitlines() if line.strip())


# With no fault the replay must reproduce the real run, or none of the scenarios mean anything.
fresh()
replay = Replay(store=store, record=False)
row = build(replay)
same = row["exit"] == 0 and artifact() == control_payload
results.append(dict(name="control_replay_matches_real_run", **row, identical=same))
if not same:
    problems.append("control_replay_matches_real_run")
replay.close()

# A clean run with next-season lookups switched on, to size the season scenarios and compare recovery against.
fresh(NEXT_YEAR)
replay = Replay(store=store, record=False)
row = build(replay)
then_2026, then_2027 = season_calls(replay, 2026), season_calls(replay, 2027)
replay.close()
next_payload = artifact()
results.append(dict(name="control_next_year_clean_run", **row, hold=next_payload["validation"]["offseason_hold"],
                    calls_2026=then_2026, calls_2027=then_2027))
if row["exit"]:
    problems.append("control_next_year_clean_run")

# Held players made no game in the control, so each of them makes a next-season call too.
held_ids = sorted(str(p["mlbam_id"]) for p in control_payload["profiles"] if p.get("offseason_hold"))
all_rows = json.loads(next(body for key, body in store.items() if kind(key) == "transactions"))["transactions"]


def small_feed(count):
    keep = set(held_ids[:count])
    return json.dumps({"transactions": [row for row in all_rows if str((row.get("person") or {}).get("id")) in keep]}).encode("utf-8")


# name, fault, must the build stop, as-of date, what to confirm
SCENARIOS = (
    ("schedule_http_500", counted("schedule", lambda n, p: "500"), True, None, dict(schedule_calls=1, log_calls=0)),
    ("schedule_hang_hits_15s_timeout", counted("schedule", lambda n, p: "hang"), True, None, dict(seconds=(14, 40), schedule_calls=1)),
    ("schedule_bad_json", counted("schedule", lambda n, p: "garbage"), True, None, dict(schedule_calls=1)),
    ("schedule_missing_field", counted("schedule", lambda n, p: b"{}"), True, None, dict(schedule_calls=1)),
    ("schedule_no_dates", counted("schedule", lambda n, p: b'{"dates": []}'), True, None, dict(schedule_calls=1)),
    ("schedule_slow_drip_hits_600s_step_limit", counted("schedule", lambda n, p: "drip"), True, None, dict(seconds=(590, 660), text="timed out")),
    ("in_season_schedule_500", counted("schedule", lambda n, p: "500"), True, "2026-07-01", dict(schedule_calls=1)),
    ("next_season_schedule_500", next_season("500"), True, NEXT_YEAR, dict()),
    ("transactions_feed_500", counted("transactions", lambda n, p: "500"), True, None, dict(schedule_calls=0)),
    # One failed game-log call anywhere stops the build there, whatever kind of failure it is.
    ("logs_first_call_500", counted("logs", lambda n, p: "500" if n == 1 else None), True, None, dict(log_calls=1, schedule_calls=1, text="game_log")),
    ("logs_middle_call_500", counted("logs", lambda n, p: "500" if n == now_calls // 2 else None), True, None, dict(log_calls=now_calls // 2, text="game_log")),
    ("logs_last_call_500", counted("logs", lambda n, p: "500" if n == now_calls else None), True, None, dict(log_calls=now_calls, text="game_log")),
    ("logs_bad_json", counted("logs", lambda n, p: "garbage" if n == 1 else None), True, None, dict(log_calls=1, text="game_log")),
    ("logs_missing_field", counted("logs", lambda n, p: b"{}" if n == 1 else None), True, None, dict(log_calls=1, text="game_log")),
    ("logs_hang_hits_15s_timeout", counted("logs", lambda n, p: "hang" if n == 1 else None), True, None, dict(log_calls=1, seconds=(14, 40), text="timed out")),
    ("logs_slow_hits_300s_budget", counted("logs", lambda n, p: ("slow", 14)), True, None, dict(seconds=(295, 345), text="budget exceeded")),
    ("next_year_first_call_500", log_fault({2027: {1}}), True, NEXT_YEAR, dict(text="season 2027")),
    ("next_year_last_call_500", log_fault({2027: {then_2027}}), True, NEXT_YEAR, dict(text="season 2027")),
    ("this_year_last_call_500_next_year_fine", log_fault({2026: {then_2026}}), True, NEXT_YEAR, dict(text="season 2026")),
    ("small_one_of_one_fails", log_fault({2026: {1}}, small_feed(1)), True, None, dict(log_calls=1, text="season 2026", small=True)),
    ("small_second_of_two_fails", log_fault({2026: {2}}, small_feed(2)), True, None, dict(log_calls=2, text="season 2026", small=True)),
    ("small_next_year_one_of_one_fails", log_fault({2027: {1}}, small_feed(1)), True, NEXT_YEAR, dict(log_calls=2, text="season 2027", small=True)),
    ("small_three_clean_lookups_publish", log_fault({}, small_feed(3)), False, None, dict(log_calls=3, held=3, small=True)),
    # None of these is a failed lookup, so the build must carry on.
    ("logs_zero_game_call_is_not_a_failure", counted("logs", lambda n, p: b'{"stats": []}' if n == 1 else None), False, None, dict(log_calls=now_calls)),
    ("lockout_empty_next_season", next_season(b'{"dates": []}'), False, NEXT_YEAR, dict(release="pending", played=0, holds=True)),
    ("thirteen_played_dates_still_held", next_season(days(13)), False, "2027-05-01", dict(release="pending", played=13, holds=True)),
    ("fourteen_played_dates_release", next_season(days(14)), False, "2027-05-01", dict(release="released", played=14, holds=False, log_calls=0)),
)

for name, fault, must_stop, as_of, expect in SCENARIOS:
    fresh(as_of)
    replay = Replay(store=store, fault=fault, record=False)
    row = dict(name=name, must_stop=must_stop, as_of=as_of or real_as_of, **build(replay, small=expect.get("small", False)))
    row.update(schedule_calls=replay.count("schedule"), log_calls=replay.count("logs"))
    replay.close()
    bad = []
    if must_stop:
        if row["exit"] == 0:
            bad.append("build did not stop")
        if row["marker"]:
            bad.append("next step ran after the failure")
        if sha(ARTIFACT) != good_artifact:
            bad.append("availability artifact changed")
        leftovers = list((ROOT / "data/models").glob("*.tmp"))
        if leftovers:
            bad.append(f"temp files left: {leftovers}")
    else:
        if row["exit"]:
            bad.append("build stopped")
        if not row["marker"]:
            bad.append("next step did not run")
        payload = artifact()
        hold = payload["validation"]["offseason_hold"]
        row["hold"] = hold
        if "offseason_hold_error" in payload["validation"]:
            bad.append("a retained-failure report appeared")
        if as_of is None and not expect.get("small"):
            done = subprocess.run((sys.executable, "scripts/validate_mlb_availability.py"), cwd=ROOT, text=True,
                                  capture_output=True, errors="replace")
            row["validator_exit"] = done.returncode
            if done.returncode:
                bad.append("validator failed")
        if "release" in expect and hold["release_state"] != expect["release"]:
            bad.append(f"release {hold['release_state']}, expected {expect['release']}")
        if "played" in expect and hold["played_date_count"] != expect["played"]:
            bad.append(f"played {hold['played_date_count']}, expected {expect['played']}")
        if "holds" in expect and bool(hold["held_count"]) != expect["holds"]:
            bad.append(f"held {hold['held_count']}")
        if "held" in expect and hold["held_count"] != expect["held"]:
            bad.append(f"held {hold['held_count']}, expected {expect['held']}")
    if sha(SNAPSHOT) != good_snapshot:
        bad.append("public snapshot changed")
    if "seconds" in expect and not expect["seconds"][0] <= row["seconds"] <= expect["seconds"][1]:
        bad.append(f"took {row['seconds']}s, expected {expect['seconds']}")
    for key in ("schedule_calls", "log_calls"):
        if key in expect and row[key] != expect[key]:
            bad.append(f"{key} {row[key]}, expected {expect[key]}")
    if "text" in expect and expect["text"] not in row["last_line"]:
        bad.append(f"last line lacks {expect['text']!r}")
    row.update(changed_files=changed_files(), problems=bad)
    results.append(row)
    print(row, flush=True)
    if bad:
        problems.append(name)


def recovery(name, as_of, fault, clean_payload):
    """A build stops, the last good artifact survives, and the next clean run publishes what an undisturbed run would."""
    fresh(as_of)
    replay = Replay(store=store, fault=fault, record=False)
    failed = build(replay)
    replay.close()
    intact = sha(ARTIFACT) == good_artifact
    replay = Replay(store=store, record=False)
    next_run = build(replay)
    replay.close()
    ok = failed["exit"] != 0 and not failed["marker"] and intact and next_run["exit"] == 0 and artifact() == clean_payload
    results.append(dict(name=name, failed_run=failed, artifact_intact=intact, next_run=next_run, identical_to_clean_run=ok))
    if not ok:
        problems.append(name)


# There is no in-process retry: a failed call stops the build, and the next hourly run is the retry.
recovery("schedule_blip_then_next_run_recovers", None, counted("schedule", lambda n, p: "500"), control_payload)
recovery("log_blip_then_next_run_recovers", None, log_fault({2026: {1}}), control_payload)
recovery("next_year_blip_then_next_run_recovers", NEXT_YEAR, log_fault({2027: {1}}), next_payload)

# The accepted cost: one player's lookup that keeps failing blocks every attempt, and the last good board stays,
# until it is fixed. Each attempt has to stop the same way, with no state building up between them.
stuck = held_ids[len(held_ids) // 2]


def stuck_fault(path, replay):
    return "500" if kind(path) == "logs" and f"/people/{stuck}/" in path else None


fresh()
attempts = []
for _ in range(3):
    replay = Replay(store=store, fault=stuck_fault, record=False)
    attempts.append(build(replay))
    replay.close()
intact = sha(ARTIFACT) == good_artifact and sha(SNAPSHOT) == good_snapshot
replay = Replay(store=store, record=False)
fixed = build(replay)
replay.close()
ok = (all(run["exit"] != 0 and not run["marker"] and stuck in run["last_line"] for run in attempts)
      and intact and fixed["exit"] == 0 and artifact() == control_payload)
results.append(dict(name="one_persistent_failure_blocks_every_attempt_then_recovers", attempts=attempts,
                    artifact_intact=intact, after_fix=fixed, ok=ok))
if not ok:
    problems.append("one_persistent_failure_blocks_every_attempt_then_recovers")

# What the daily workflow does after this step fails. Read from the file, not assumed.
workflow = yaml.safe_load((ROOT / ".github/workflows/daily-public-data.yml").read_text(encoding="utf-8"))
steps = workflow["jobs"]["refresh"]["steps"]
names = [step.get("name", "") for step in steps]
build_at = next(i for i, step in enumerate(steps) if "run_daily_public_build.py --only build" in step.get("run", ""))
publish_at = names.index("Commit and publish refreshed data")
deploy_at = names.index("Trigger Render deploy")
after_failure = [names[i] for i in range(build_at + 1, len(steps)) if "always()" in str(steps[i].get("if", ""))]
publish_blocked = (
    build_at < publish_at < deploy_at
    and not any(step.get("continue-on-error") for step in steps[:publish_at + 1])
    and "always()" not in str(steps[publish_at].get("if", "")) and "failure()" not in str(steps[publish_at].get("if", ""))
    and "always()" not in str(steps[deploy_at].get("if", ""))
)
alert = workflow["jobs"]["alert-on-missed-day"]
alert_run = "\n".join(step.get("run", "") for step in alert["steps"])
alert_wired = (
    alert["needs"] == "refresh" and "always()" in alert["if"] and "'failure'" in alert["if"] and "'cancelled'" in alert["if"]
    and alert["permissions"].get("issues") == "write" and '"$hour" -lt 19' in alert_run
    and '--assignee "$GITHUB_REPOSITORY_OWNER"' in alert_run
)
results.append(dict(name="workflow_skips_publish_and_alerts_after_a_failed_build", ok=publish_blocked and alert_wired,
                    publish_blocked=publish_blocked, alert_wired=alert_wired, steps_that_still_run=after_failure,
                    retry_crons=[c["cron"] for c in workflow[True]["schedule"]]))
if not (publish_blocked and alert_wired):
    problems.append("workflow_skips_publish_and_alerts_after_a_failed_build")

(out / "faults.json").write_text(json.dumps(dict(
    reviewed_sha=os.environ["REHEARSAL_REVIEWED_SHA"], control_hold=control_hold,
    calls=dict(now=now_calls, next_year_2026=then_2026, next_year_2027=then_2027),
    results=results, problems=problems,
), indent=1), encoding="utf-8")
print("scenarios", len(results), "problems", problems, flush=True)
raise SystemExit(1 if problems else 0)
