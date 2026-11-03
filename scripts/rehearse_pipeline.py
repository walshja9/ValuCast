"""Run the daily pipeline without stopping at a failure. Throwaway branch only: no commit, push or deploy."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_daily_public_build import BUILD_STEPS, VALIDATE_STEPS  # noqa: E402

INPUT_STEPS = [
    ("-m", "scraper.refresh"),
    ("scripts/audit_reliever_roles.py",),
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

results = []
out = Path(os.environ["REHEARSAL_OUT"])
out.mkdir(parents=True, exist_ok=True)
for stage, steps in (("input", INPUT_STEPS), ("build", BUILD_STEPS + AFTER_BUILD), ("validate", VALIDATE_STEPS)):
    for step in steps:
        started = time.time()
        done = subprocess.run((sys.executable, *step), cwd=ROOT, text=True, capture_output=True, errors="replace")
        tail = [line[:300] for line in (done.stdout + done.stderr).splitlines()[-25:]] if done.returncode else []
        if step[0] == "scripts/audit_reliever_roles.py":
            print(done.stdout, flush=True)
        results.append(dict(stage=stage, step=" ".join(step), exit=done.returncode,
                            seconds=round(time.time() - started), tail=tail))
        print(stage, done.returncode, round(time.time() - started), " ".join(step), flush=True)
        for line in tail:
            print("    ", line, flush=True)
        (out / "statuses.json").write_text(json.dumps(results, indent=1), encoding="utf-8")
print("failed", sum(1 for row in results if row["exit"]), "of", len(results), flush=True)
