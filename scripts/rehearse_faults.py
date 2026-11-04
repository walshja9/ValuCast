"""Break MLB lookups on a real socket and run the real daily build step. Throwaway branch only: no push, no deploy.

Each scenario runs scripts/run_daily_public_build.py's own run_stage on the unmodified availability step, followed
by a marker step that shows whether the build carried on. Prints IDs and counts only.
"""

import hashlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mlb.availability import (  # noqa: E402
    HOLD_MAX_FAILURE_SHARE,
    HOLD_MIN_CALLS_FOR_SEASON_STOP,
    HOLD_MIN_FAILURES_FOR_SHARE_STOP,
)
from scripts.rehearse_proxy import Replay, kind  # noqa: E402

out = Path(os.environ["REHEARSAL_OUT"])
out.mkdir(parents=True, exist_ok=True)
temp = Path(os.environ["RUNNER_TEMP"])
ARTIFACT = ROOT / "data/models/valucast_mlb_availability.json"
SNAPSHOT = ROOT / "data/public/public_dynasty_snapshot.json"
METADATA = ROOT / "data/projections/metadata.json"
MARKER = temp / "next_step_ran"
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
    """Fail these game-log call numbers, counted per season, as {2026: {1, 10}, 2027: {1, 5, 9}}."""
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


def spaced(count, total):
    """`count` call numbers evenly through `total`, so the consecutive stop cannot be what fires."""
    return {round((step + 1) * total / count) for step in range(count)}


def over(calls):
    """The fewest failures that reach the share stop for this many calls."""
    return max(HOLD_MIN_FAILURES_FOR_SHARE_STOP, math.ceil(round(calls * HOLD_MAX_FAILURE_SHARE, 6)))


# name, fault, must the build stop, as-of date, what to confirm
SCENARIOS = (
    ("schedule_http_500", counted("schedule", lambda n, p: "500"), True, None, dict(schedule_calls=1, log_calls=0)),
    ("schedule_hang_hits_15s_timeout", counted("schedule", lambda n, p: "hang"), True, None, dict(seconds=(14, 40), schedule_calls=1)),
    ("schedule_bad_json", counted("schedule", lambda n, p: "garbage"), True, None, dict(schedule_calls=1)),
    ("schedule_missing_field", counted("schedule", lambda n, p: b"{}"), True, None, dict(schedule_calls=1)),
    ("schedule_no_dates", counted("schedule", lambda n, p: b'{"dates": []}'), True, None, dict(schedule_calls=1)),
    ("schedule_slow_drip_hits_600s_step_limit", counted("schedule", lambda n, p: "drip"), True, None, dict(seconds=(590, 660), text="timed out")),
    ("in_season_schedule_500", counted("schedule", lambda n, p: "500"), True, "2026-07-01", dict(schedule_calls=1)),
    ("next_season_schedule_500", next_season("500"), True, "2027-03-01", dict()),
    ("logs_five_straight_500", counted("logs", lambda n, p: "500"), True, None, dict(log_calls=5, schedule_calls=1)),
    ("logs_five_straight_bad_json", counted("logs", lambda n, p: "garbage"), True, None, dict(log_calls=5)),
    ("logs_five_straight_missing_field", counted("logs", lambda n, p: b"{}"), True, None, dict(log_calls=5)),
    ("logs_hang_five_15s_timeouts", counted("logs", lambda n, p: "hang"), True, None, dict(log_calls=5, seconds=(70, 120))),
    ("logs_slow_hits_300s_budget", counted("logs", lambda n, p: ("slow", 14)), True, None, dict(seconds=(295, 345), text="budget exceeded")),
    ("logs_four_then_recover", counted("logs", lambda n, p: "500" if n <= 4 else None), False, None, dict(failures=4)),
    ("logs_zero_game_call_resets", counted("logs", lambda n, p: "500" if n <= 4 or 6 <= n <= 9 else (b'{"stats": []}' if n == 5 else None)), False, None, dict(failures=8)),
    ("logs_four_of_every_five_fail", counted("logs", lambda n, p: None if n % 5 == 0 else "500"), True, None, dict(text="season 2026,")),
    ("logs_next_year_query_always_fails", counted("logs", lambda n, p: "500" if "season=2027" in p else None), True, "2027-03-01", dict(text="season 2027,")),
    ("lockout_empty_next_season", next_season(b'{"dates": []}'), False, "2027-03-01", dict(release="pending", played=0, holds=True)),
    ("thirteen_played_dates_still_held", next_season(days(13)), False, "2027-05-01", dict(release="pending", played=13, holds=True)),
    ("fourteen_played_dates_release", next_season(days(14)), False, "2027-05-01", dict(release="released", played=14, holds=False)),
    ("transactions_feed_500", counted("transactions", lambda n, p: "500"), True, None, dict(schedule_calls=0)),
)

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
control_log_calls = control.count("logs")
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
NEXT_YEAR = "2027-03-01"
fresh(NEXT_YEAR)
replay = Replay(store=store, record=False)
row = build(replay)
replay.close()
next_payload = artifact()
results.append(dict(name="control_next_year_clean_run", **row, hold=next_payload["validation"]["offseason_hold"]))
if row["exit"]:
    problems.append("control_next_year_clean_run")
now_calls = control_hold["lookups_by_season"]["2026"]["attempted"]
then = next_payload["validation"]["offseason_hold"]["lookups_by_season"]
then_2026, then_2027 = then["2026"]["attempted"], then["2027"]["attempted"]
just_under = over(now_calls) - 1

# Held players made no game in the control, so each of them makes a next-season call too.
held_ids = sorted(str(p["mlbam_id"]) for p in control_payload["profiles"] if p.get("offseason_hold"))
all_rows = json.loads(next(body for key, body in store.items() if kind(key) == "transactions"))["transactions"]


def small_feed(count):
    keep = set(held_ids[:count])
    return json.dumps({"transactions": [row for row in all_rows if str((row.get("person") or {}).get("id")) in keep]}).encode("utf-8")


SCENARIOS += (
    ("partial_just_under_share", log_fault({2026: spaced(just_under, now_calls)}), False, None, dict(failures=just_under)),
    ("partial_just_over_share", log_fault({2026: spaced(over(now_calls), now_calls)}), True, None, dict(text=f"season 2026, {over(now_calls)} of {now_calls}")),
    ("partial_every_fourth_call", counted("logs", lambda n, p: "500" if n % 4 == 0 else None), True, None, dict(text="season 2026,")),
    ("partial_every_other_call", counted("logs", lambda n, p: "500" if n % 2 == 0 else None), True, None, dict(text="season 2026,")),
    ("partial_short_outage_window", counted("logs", lambda n, p: "500" if 40 <= n < 80 and n % 5 else None), True, None, dict(text="season 2026,")),
    ("next_year_just_under_share", log_fault({2027: spaced(over(then_2027) - 1, then_2027)}), False, NEXT_YEAR, dict(failures=over(then_2027) - 1)),
    ("next_year_just_over_share", log_fault({2027: spaced(over(then_2027), then_2027)}), True, NEXT_YEAR, dict(text=f"season 2027, {over(then_2027)} of {then_2027}")),
    ("this_year_just_over_share_next_year_fine", log_fault({2026: spaced(over(then_2026), then_2026)}), True, NEXT_YEAR, dict(text=f"season 2026, {over(then_2026)} of {then_2026}")),
    ("small_one_of_one_fails", log_fault({2026: {1}}, small_feed(1)), False, None, dict(failures=1, small=True)),
    ("small_two_of_two_fail", log_fault({2026: {1, 2}}, small_feed(2)), False, None, dict(failures=2, small=True)),
    ("small_three_of_three_fail", log_fault({2026: {1, 2, 3}}, small_feed(3)), True, None, dict(text="season 2026, 3 of 3", small=True)),
    ("small_three_of_four_fail", log_fault({2026: {1, 2, 3}}, small_feed(4)), False, None, dict(failures=3, small=True)),
    ("small_four_of_five_fail", log_fault({2026: {1, 2, 4, 5}}, small_feed(5)), False, None, dict(failures=4, small=True)),
    ("small_five_of_six_fail", log_fault({2026: {1, 2, 4, 5, 6}}, small_feed(6)), True, None, dict(text="season 2026, 5 of 6", small=True)),
    ("small_next_year_two_of_two_fail", log_fault({2027: {1, 2}}, small_feed(2)), False, NEXT_YEAR, dict(failures=2, small=True)),
    ("small_next_year_three_of_three_fail", log_fault({2027: {1, 2, 3}}, small_feed(3)), True, NEXT_YEAR, dict(text="season 2027, 3 of 3", small=True)),
    ("small_two_seasons_whole_build_only", log_fault({2026: {1, 10}, 2027: {1, 5, 9}}, small_feed(20)), True, NEXT_YEAR, dict(text="all seasons, 5 of 38", small=True)),
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
        errors = payload["validation"].get("offseason_hold_error") or []
        row.update(hold=hold, reported_errors=len(errors))
        if hold["lookup_failure_count"] != len(errors):
            bad.append("failures and reported errors disagree")
        if name.startswith(("logs_", "partial_", "next_year_")):
            control_by_id = {p["mlbam_id"]: p for p in control_payload["profiles"]}
            moved = []
            for profile in payload["profiles"]:
                before = control_by_id.get(profile["mlbam_id"]) or {}
                if (profile.get("status"), bool(profile.get("offseason_hold"))) != (
                        before.get("status"), bool(before.get("offseason_hold"))):
                    moved.append(profile)
            row["status_differs_from_control"] = len(moved)
            # The zero-game scenario answers one lookup falsely on purpose, so that player may differ too.
            if as_of is None and name != "logs_zero_game_call_resets":
                failed_ids = {error.split()[1].rstrip(":") for error in errors}
                strays = [p["mlbam_id"] for p in moved if str(p["mlbam_id"]) not in failed_ids]
                if strays:
                    bad.append(f"status changed for a player whose lookup worked: {strays[:10]}")
            done = subprocess.run((sys.executable, "scripts/validate_mlb_availability.py"), cwd=ROOT, text=True,
                                  capture_output=True, errors="replace")
            row["validator_exit"] = done.returncode
            row["validator_warnings"] = sum(1 for line in done.stdout.splitlines() if line.startswith("WARNING"))
            if done.returncode or (errors and not row["validator_warnings"]):
                bad.append("validator did not report the failures")
        if "failures" in expect and hold["lookup_failure_count"] != expect["failures"]:
            bad.append(f"failures {hold['lookup_failure_count']}, expected {expect['failures']}")
        if "release" in expect and hold["release_state"] != expect["release"]:
            bad.append(f"release {hold['release_state']}, expected {expect['release']}")
        if "played" in expect and hold["played_date_count"] != expect["played"]:
            bad.append(f"played {hold['played_date_count']}, expected {expect['played']}")
        if "holds" in expect and bool(hold["held_count"]) != expect["holds"]:
            bad.append(f"held {hold['held_count']}")
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

# There is no in-process retry: a failed call counts at once, and the next hourly run is the retry.
fresh()
replay = Replay(store=store, fault=counted("schedule", lambda n, p: "500" if n == 1 else None), record=False)
failed = build(replay)
second = build(replay)
recovered = failed["exit"] != 0 and second["exit"] == 0 and artifact() == control_payload
results.append(dict(name="blip_then_next_run_recovers", failed_run=failed, next_run=second,
                    schedule_calls=replay.count("schedule"), identical_to_control=recovered))
if not recovered:
    problems.append("blip_then_next_run_recovers")
replay.close()

# The last four calls of one build and the first four of the next fail: eight in a row, but nothing carries over.
fresh()
replay = Replay(store=store, record=False, fault=counted(
    "logs", lambda n, p: "500" if control_log_calls - 4 < n <= control_log_calls + 4 else None))
one, two = build(replay), build(replay)
carried = one["exit"] == 0 and two["exit"] == 0
results.append(dict(name="failure_count_does_not_carry_between_builds", first=one, second=two, ok=carried))
if not carried:
    problems.append("failure_count_does_not_carry_between_builds")
replay.close()


def recovery(name, as_of, plan, clean_payload):
    """A build stops on the totals, the last good artifact survives, and the next clean run publishes normally."""
    fresh(as_of)
    replay = Replay(store=store, fault=log_fault(plan), record=False)
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


recovery("share_stop_then_next_run_recovers", None, {2026: set(range(2, now_calls + 1, 2))}, control_payload)
recovery("season_stop_then_next_run_recovers", NEXT_YEAR, {2027: set(range(1, then_2027 + 1))}, next_payload)

# Failures just under the stop publish with those holds retained. The next clean run must put every status right.
fresh()
replay = Replay(store=store, fault=log_fault({2026: spaced(just_under, now_calls)}), record=False)
low = build(replay)
replay.close()
replay = Replay(store=store, record=False)
clean = build(replay)
replay.close()
ok = low["exit"] == 0 and clean["exit"] == 0 and artifact() == control_payload
results.append(dict(name="publish_under_the_stop_then_clean_run_matches_control", first=low, second=clean, ok=ok))
if not ok:
    problems.append("publish_under_the_stop_then_clean_run_matches_control")

# Two builds each just under the stop: the totals must not add up across them.
fresh()
runs = []
for _ in range(2):
    replay = Replay(store=store, fault=log_fault({2026: spaced(just_under, now_calls)}), record=False)
    runs.append(build(replay))
    replay.close()
ok = all(run["exit"] == 0 for run in runs)
results.append(dict(name="totals_do_not_carry_between_builds", runs=runs, ok=ok))
if not ok:
    problems.append("totals_do_not_carry_between_builds")

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
results.append(dict(name="workflow_skips_publish_after_a_failed_build", ok=publish_blocked,
                    steps_that_still_run=after_failure, retry_crons=[c["cron"] for c in workflow[True]["schedule"]]))
if not publish_blocked:
    problems.append("workflow_skips_publish_after_a_failed_build")

(out / "faults.json").write_text(json.dumps(dict(
    reviewed_sha=os.environ["REHEARSAL_REVIEWED_SHA"], control_hold=control_hold,
    thresholds=dict(share=HOLD_MAX_FAILURE_SHARE, min_failures=HOLD_MIN_FAILURES_FOR_SHARE_STOP,
                    min_season_calls=HOLD_MIN_CALLS_FOR_SEASON_STOP),
    calls=dict(now=now_calls, next_year_2026=then_2026, next_year_2027=then_2027),
    results=results, problems=problems,
), indent=1), encoding="utf-8")
print("scenarios", len(results), "problems", problems, flush=True)
raise SystemExit(1 if problems else 0)
