"""One set of inputs, then each rule variant from one restore point. Throwaway branch only: no push, no deploy."""

import csv
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_daily_public_build import BUILD_STEPS, VALIDATE_STEPS  # noqa: E402

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
# Each row adds one rule to the row above it, so neighbours isolate that rule.
VARIANTS = (
    # name, hold scope, prospect cap, run every step
    ("baseline", "off", "off", True),
    ("old_status_fix", "stale", "off", False),
    ("pitchers_existing_discount", "pitchers", "off", False),
    ("proposed", "pitchers", "on", True),
    ("all_players", "all", "on", False),
    ("baseline_replay", "off", "off", False),
)

out = Path(os.environ["REHEARSAL_OUT"])
temp = Path(os.environ["RUNNER_TEMP"])
old = temp / "old"
out.mkdir(parents=True, exist_ok=True)


def git(*args):
    return subprocess.run(("git", *args), cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


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


shared = []
shared_env = dict(os.environ, REHEARSAL_HOLD_SCOPE="off", REHEARSAL_PROSPECT_CAP="off")
shared_path = out / "shared_statuses.json"
for stage, steps in (("input", INPUT_STEPS), ("build", BUILD_STEPS[:SPLIT] + [AVAILABILITY])):
    for step in steps:
        run(shared, stage, step, shared_env, shared_path)
git("add", "-A")
git("-c", "user.name=rehearsal", "-c", "user.email=rehearsal@invalid", "commit", "-qm", "restore point, never pushed")
restore = git("rev-parse", "HEAD")

for name, scope, cap, full in VARIANTS:
    git("reset", "--hard", restore)
    git("clean", "-fdq")
    env = dict(os.environ, REHEARSAL_HOLD_SCOPE=scope, REHEARSAL_PROSPECT_CAP=cap)
    folder = out / name
    folder.mkdir(parents=True, exist_ok=True)
    results = []
    path = folder / "statuses.json"
    tail = BUILD_STEPS[SPLIT + 1:] + AFTER_BUILD if full else BUILD_STEPS[SPLIT + 1:SHORT_END + 1]
    for step in [AVAILABILITY + ("--no-refresh",)] + tail:
        run(results, "build", step, env, path)
    for step in VALIDATE_STEPS if full else SHORT_VALIDATE:
        run(results, "validate", step, env, path)
    try:
        export(name, folder, env)
    except Exception as exc:  # noqa: BLE001
        print(name, "export failed", exc, flush=True)
    print(name, "failed", sum(1 for row in results if row["exit"]), "of", len(results), flush=True)
memo = Path(os.environ["REHEARSAL_LOOKUP_MEMO"])
keys = json.loads(memo.read_text(encoding="utf-8")) if memo.exists() else {}
(out / "lookups.txt").write_text(
    f"schedule {sum(1 for key in keys if key.startswith('_fetch_schedule'))}, "
    f"game_logs {sum(1 for key in keys if key.startswith('_fetch_game_logs'))}\n", encoding="utf-8")
print("restore point", restore, flush=True)
