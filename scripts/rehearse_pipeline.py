"""One set of inputs, then each rule variant from one restore point. Throwaway branch only: no push, no deploy.

The proposed variant runs the reviewed commit's code unmodified. The others patch one rule at run time, and every
variant reads MLB's schedule and game logs through the same replay server. Any failed required check fails the job.
"""

import csv
import filecmp
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.rehearse_proxy import Replay, kind  # noqa: E402
from scripts.run_daily_public_build import BUILD_STEPS, VALIDATE_STEPS  # noqa: E402

REVIEWED = os.environ["REHEARSAL_REVIEWED_SHA"]
TARGET = os.environ["REHEARSAL_TARGET"]
HARNESS = {
    ".github/workflows/steamer-feed-check.yml",
    "scripts/compare_2027_boards.py",
    "scripts/export_redraft_board.py",
    "scripts/rehearsal_site/sitecustomize.py",
    "scripts/rehearse_faults.py",
    "scripts/rehearse_pipeline.py",
    "scripts/rehearse_proxy.py",
    "scripts/rehearse_screens.py",
    "scripts/summarize_rehearsal.py",
}
INPUT_STEPS = [
    ("-m", "scraper.refresh"),
    ("scripts/fetch_statcast_percentiles.py",),
    ("scripts/refresh_milb_season_stats.py",),
    (
        "scripts/refresh_milb_season_stats.py",
        "--stats-type", "byDateRange", "--window-days", "30",
        "--output", "data/prospects/raw/milb_recent_stats.json",
    ),
    ("scripts/refresh_prospect_orgs.py", "--write"),
    ("scripts/build_valucast_prospect_inputs.py", "--refresh-service-cache"),
]
AFTER_BUILD = [("scripts/build_prospect_rank_history.py",)]
AVAILABILITY = ("scripts/build_mlb_availability.py",)
SPLIT = BUILD_STEPS.index(AVAILABILITY)
SHORT_END = BUILD_STEPS.index(("scripts/build_valucast_quality_governor.py",))
SHORT_VALIDATE = [("scripts/validate_mlb_availability.py",), ("scripts/validate_prospect_availability.py",)]
PROPOSED_TESTS = [
    ("-m", "pytest", "-q", "tests/test_mlb_offseason_hold.py"),
    ("-m", "pytest", "-q", "tests/test_redraft_player_card.py", "-k", "offseason or redraft_exemption or held_player"),
    ("-m", "pytest", "-q",
     "tests/test_preseason_switch.py::test_refresh_phase_keeps_actuals_separate",
     "tests/test_preseason_switch.py::test_preseason_retained_ros_requires_matching_target"),
]
# The hold never runs, the pitcher check is off or wide open, or held prospects keep the existing discount.
REGEX_LINE = '            and re.search(r"\\b(?:RHP|LHP)\\b", str(stint.get("description") or ""))\n'
FETCH_LINE = "    fetch_schedule = schedule_fetcher or _fetch_schedule\n"
OFF = ("mlb/availability.py", FETCH_LINE, '    return {"offseason_hold": summary}\n' + FETCH_LINE)
STALE_ONLY = ("mlb/availability.py", REGEX_LINE, "            and False\n")
ALL_PLAYERS = ("mlb/availability.py", REGEX_LINE, "            and True\n")
NO_CAP = ("prospects/availability.py", "        discount = min(discount, HELD_IL_MAX_DISCOUNT)\n", "        pass\n")
# Each row adds one rule to the row above it, so neighbours isolate that rule.
VARIANTS = (
    # name, patches, run every step, take screenshots
    ("baseline", (OFF,), True, True),
    ("old_status_fix", (STALE_ONLY, NO_CAP), False, False),
    ("pitchers_existing_discount", (NO_CAP,), False, False),
    ("proposed", (), True, True),
    ("all_players", (ALL_PLAYERS,), False, False),
    ("baseline_replay", (OFF,), False, False),
)
CONTROL_PLAYER = "Bobby Witt Jr."
HELD_PROSPECT = "dynasty:Robby Snelling"

out =Path(os.environ["REHEARSAL_OUT"])
temp = Path(os.environ["RUNNER_TEMP"])
old = temp / "old"
out.mkdir(parents=True, exist_ok=True)
required = []


def fail(check, detail):
    required.append(dict(check=check, detail=detail))
    print("REQUIRED CHECK FAILED", check, detail, flush=True)


def git(*args):
    return subprocess.run(("git", *args), cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def apply(patch):
    path, before, after = patch
    target = ROOT / path
    with target.open(encoding="utf-8", newline="") as handle:
        text = handle.read()
    nl = "\r\n" if "\r\n" in text else "\n"
    before, after = before.replace("\n", nl), after.replace("\n", nl)
    assert text.count(before) == 1, (path, before)
    with target.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text.replace(before, after))


def check_exact_code(stage):
    """The tree differs from the reviewed commit only by harness files and, at 2027, the one target line."""
    names = git("diff", "--name-only", REVIEWED).splitlines()
    code = [name for name in names if name.endswith((".py", ".html", ".css", ".js", ".yml"))]
    extra = sorted(set(code) - HARNESS - {"scraper/season.py"})
    if extra:
        fail(f"exact_code_{stage}", extra)
    season = git("diff", "--numstat", REVIEWED, "--", "scraper/season.py")
    expected = "1\t1\tscraper/season.py" if TARGET != "2026" else ""
    if season != expected:
        fail(f"exact_code_{stage}", f"scraper/season.py differs: {season!r}")
    return dict(stage=stage, code_differences=sorted(set(code) - HARNESS), season_diff=season)


def run(results, stage, step, env, path):
    started = time.time()
    done = subprocess.run((sys.executable, *step), cwd=ROOT, env=env, text=True, capture_output=True, errors="replace")
    tail = [line[:300] for line in (done.stdout + done.stderr).splitlines()[-25:]] if done.returncode else []
    if step[0] == "scripts/validate_mlb_availability.py":
        tail += [line[:300] for line in done.stdout.splitlines() if line.startswith("WARNING")]
    results.append(dict(stage=stage, step=" ".join(step), exit=done.returncode,
                        seconds=round(time.time() - started), tail=tail))
    print(path.name, stage, done.returncode, results[-1]["seconds"], " ".join(step), flush=True)
    for line in tail:
        print("    ", line, flush=True)
    path.write_text(json.dumps(results, indent=1), encoding="utf-8")
    if done.returncode:
        fail("step", f"{path.parent.name if path.name == 'statuses.json' else 'shared'}: {stage} {' '.join(step)}")


def export(name, folder, env):
    new = temp / "new" / name
    new.mkdir(parents=True, exist_ok=True)
    for path in ("data/models/valucast_quality_governor.json", "data/public/public_dynasty_snapshot.json"):
        shutil.copy(ROOT / path, new)
    shutil.copy(ROOT / "data/models/valucast_mlb_availability.json", folder)
    prospects = json.loads((ROOT / "data/models/valucast_prospect_availability.json").read_text(encoding="utf-8"))
    rows = [row for row in prospects.get("profiles") or []
            if row.get("risk_discount") or row.get("offseason_hold")]
    with (folder / "prospect_discounts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("mlbam_id", "name", "role", "status", "risk_basis", "risk_discount", "offseason_hold"))
        for row in rows:
            writer.writerow((row.get("mlbam_id"), row.get("name"), row.get("role"), row.get("status"),
                             row.get("risk_basis"), row.get("risk_discount"), row.get("offseason_hold")))
    for command in (
        ("scripts/compare_2027_boards.py",
         "--old-dynasty", str(old / "valucast_mlb_dynasty_layer.json"),
         "--new-dynasty", "data/models/valucast_mlb_dynasty_layer.json",
         "--old-projections", str(old / "current.json"),
         "--new-projections", "data/projections/current.json",
         "--old-app", str(old / "app.py"),
         "--out", str(folder)),
        ("scripts/export_redraft_board.py", str(folder / "redraft_board.csv")),
        ("scripts/summarize_rehearsal.py", str(old), str(new), str(folder)),
    ):
        done = subprocess.run((sys.executable, *command), cwd=ROOT, env=env, text=True, capture_output=True, errors="replace")
        print(name, "export", done.returncode, command[0], flush=True)
        if done.returncode:
            print((done.stdout + done.stderr)[-1500:], flush=True)
            fail("export", f"{name}: {command[0]}")


def screens(label, names, env):
    """Serve this tree on the runner and photograph it. The board values come from this variant's files."""
    log = (temp / f"app_{label}.log").open("w")
    server = subprocess.Popen(
        ("gunicorn", "app:app", "--bind", "127.0.0.1:5000", "--workers", "1", "--threads", "4", "--timeout", "300"),
        cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(90):
            try:
                urllib.request.urlopen("http://127.0.0.1:5000/health/ready", timeout=10).close()
                break
            except urllib.error.HTTPError:
                break  # The app answered; a not-ready status is the page's concern, not this wait's.
            except Exception:  # noqa: BLE001
                time.sleep(5)
        else:
            fail("screens", f"{label}: app never became ready")
            return []
        done = subprocess.run((sys.executable, "scripts/rehearse_screens.py", str(out / "screens"), label, *names),
                              cwd=ROOT, env=env, text=True, capture_output=True, errors="replace")
        print(done.stdout[-3000:], done.stderr[-1500:], flush=True)
        if done.returncode:
            fail("screens", f"{label}: exit {done.returncode}")
            return []
    finally:
        server.terminate()
        server.wait(timeout=60)
        log.close()
    path = out / "screens" / f"{label}_results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def same(check, left, right, name):
    a, b = out / left / name, out / right / name
    if not (a.exists() and b.exists() and filecmp.cmp(a, b, shallow=False)):
        fail(check, f"{left} and {right} differ in {name}")


def screen_names(variant):
    if TARGET == "2027":
        return ["Justin Steele", "Ryan Pepiot", CONTROL_PLAYER, HELD_PROSPECT]
    if variant == "baseline":
        return [CONTROL_PLAYER, HELD_PROSPECT]
    # At 2026 the held pitchers on the redraft board are whoever the data says.
    payload = json.loads((out / variant / "valucast_mlb_availability.json").read_text(encoding="utf-8"))
    held = {str(row["mlbam_id"]) for row in payload["profiles"] if row.get("offseason_hold")}
    with (out / variant / "redraft_board.csv").open(encoding="ascii") as handle:
        rows = sorted((row for row in csv.DictReader(handle) if row["mlbam_id"] in held), key=lambda row: int(row["rank"]))
    return [row["name"] for row in rows[:2]] + [CONTROL_PLAYER, HELD_PROSPECT]


shared_env = dict(os.environ)
if sys.argv[1:] == ["--preflight"]:
    # Fail in minutes, not hours, if a rule patch no longer applies or the screenshots cannot run.
    for patch in {OFF, STALE_ONLY, ALL_PLAYERS, NO_CAP}:
        apply(patch)
        git("checkout", "--", patch[0])
    rows = screens("preflight", [CONTROL_PLAYER], shared_env)
    if not (rows and all(row.get("found") and row.get("card_overflow") is not None and row.get("rank_in_view")
                         and not row.get("dynasty_error") for row in rows)):
        fail("screens_preflight", rows)
    (out / "preflight_checks.json").write_text(json.dumps(required, indent=1), encoding="utf-8")
    raise SystemExit(1 if required else 0)

info = dict(reviewed_sha=REVIEWED, target=TARGET, harness_sha=git("rev-parse", "HEAD"))
if subprocess.run(("git", "merge-base", "--is-ancestor", REVIEWED, "HEAD"), cwd=ROOT).returncode:
    fail("exact_code_start", f"{REVIEWED} is not an ancestor of the rehearsal branch")
info["start"] = check_exact_code("start")
(out / "run_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
if required:
    print("Stopping before the pipeline:", required, flush=True)
    (out / "required_checks.json").write_text(json.dumps(required, indent=1), encoding="utf-8")
    raise SystemExit(1)

replay = Replay()
availability_env = {**shared_env, "REHEARSAL_MLB_PROXY": replay.base,
                    "PYTHONPATH": f"{ROOT}/scripts/rehearsal_site:{shared_env.get('PYTHONPATH', '')}"}
shared = []
shared_path = out / "shared_statuses.json"
for stage, steps in (("input", INPUT_STEPS), ("build", BUILD_STEPS[:SPLIT])):
    for step in steps:
        run(shared, stage, step, shared_env, shared_path)
apply(OFF)
run(shared, "build", AVAILABILITY, availability_env, shared_path)
git("checkout", "--", OFF[0])
git("add", "-A")
git("-c", "user.name=rehearsal", "-c", "user.email=rehearsal@invalid", "commit", "-qm", "restore point, never pushed")
restore = git("rev-parse", "HEAD")

screen_rows = {}
for name, patches, full, shots in VARIANTS:
    git("reset", "--hard", restore)
    git("clean", "-fdq")
    if name == "proposed":
        info["proposed"] = check_exact_code("proposed")
    for patch in patches:
        apply(patch)
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    path = folder / "statuses.json"
    tail = BUILD_STEPS[SPLIT + 1:] + AFTER_BUILD if full else BUILD_STEPS[SPLIT + 1:SHORT_END + 1]
    run(results, "build", AVAILABILITY + ("--no-refresh",), availability_env, path)
    for step in tail:
        run(results, "build", step, shared_env, path)
    for step in VALIDATE_STEPS if full else SHORT_VALIDATE:
        run(results, "validate", step, shared_env, path)
    try:
        export(name, folder, shared_env)
    except Exception as exc:  # noqa: BLE001
        fail("export", f"{name}: {exc}")
    if shots:
        try:
            screen_rows[name] = screens(name, screen_names(name), shared_env)
        except Exception as exc:  # noqa: BLE001
            fail("screens", f"{name}: {exc}")
    if name == "proposed":
        for step in PROPOSED_TESTS:
            run(results, "reviewed_tests", step, shared_env, path)
    print(name, "failed", sum(1 for row in results if row["exit"]), "of", len(results), flush=True)

# The replay must equal the baseline, and the hold must leave the redraft board alone.
same("aa_replay", "baseline", "baseline_replay", "combined_board.csv")
same("aa_replay", "baseline", "baseline_replay", "redraft_board.csv")
same("redraft_unchanged", "baseline", "proposed", "redraft_board.csv")
try:
    proposed_payload = json.loads((out / "proposed/valucast_mlb_availability.json").read_text(encoding="utf-8"))
    hold_summary = proposed_payload["validation"]["offseason_hold"]
    if not (hold_summary["active"] and hold_summary["held_count"]) or "offseason_hold_error" in proposed_payload["validation"]:
        fail("proposed_lookups", hold_summary)
except (OSError, KeyError, ValueError) as exc:
    fail("proposed_lookups", str(exc))
for row in screen_rows.get("proposed", []):
    if row["name"] == CONTROL_PLAYER:
        if row.get("badge") or row.get("note") or row.get("dynasty_note") or row.get("dynasty_badge"):
            fail("screens_control", row)
    elif row.get("dynasty_only"):
        if not (row.get("dynasty_badge") and row.get("dynasty_badge_in_view")
                and row.get("dynasty_note") and row.get("dynasty_note_in_view") and row.get("risk_adjustment_shown")
                and not row.get("dynasty_overflow")):
            fail("screens_held_prospect", row)
    elif not (
        row.get("found") and row.get("badge") and row.get("badge_in_view") and row.get("note")
        and row.get("no_discount_line") and row.get("redraft_note_in_view")
        and row.get("dynasty_badge") and row.get("dynasty_badge_in_view")
        and row.get("dynasty_note") and row.get("dynasty_note_in_view") and row.get("dynasty_discount")
        and not row.get("row_overflow") and not row.get("card_overflow") and not row.get("dynasty_overflow")
    ):
        fail("screens_held", row)
for row in screen_rows.get("baseline", []):
    if row.get("badge") or row.get("note") or row.get("dynasty_note") or row.get("dynasty_badge"):
        fail("screens_baseline", row)
    match = next((other for other in screen_rows.get("proposed", [])
                  if other["name"] == row["name"] and other["width"] == row["width"]), None)
    if match and row.get("found") and (match.get("value"), match.get("rank")) != (row.get("value"), row.get("rank")):
        fail("screens_redraft_value", dict(baseline=row, proposed=match))

replay.dump(temp / "lookups.json")
(out / "lookups.txt").write_text(
    f"real schedule {sum(1 for key in replay.store if kind(key) == 'schedule')}, "
    f"real game_logs {sum(1 for key in replay.store if kind(key) == 'logs')}, "
    f"real transactions {sum(1 for key in replay.store if kind(key) == 'transactions')}, "
    f"calls served {len(replay.calls)}\n", encoding="utf-8")
info["restore_point"] = restore
(out / "run_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
(out / "required_checks.json").write_text(json.dumps(required, indent=1), encoding="utf-8")
print("required check failures", len(required), flush=True)
raise SystemExit(1 if required else 0)
