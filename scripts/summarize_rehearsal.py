"""Summarize a rehearsal: step failures, governor and snapshot before and after. Our values only, no stat lines."""

import csv
import json
import sys
from pathlib import Path

old, new, out = map(Path, sys.argv[1:4])
SAMPLE = ("Shohei Ohtani", "Aaron Judge", "Juan Soto", "Bobby Witt Jr.", "Randy Arozarena", "Tarik Skubal", "Chris Sale",
          "Mason Miller", "David Bednar", "Kenley Jansen", "Raisel Iglesias", "Pete Fairbanks", "Jazz Chisholm Jr.", "Kade Anderson", "Paul Skenes",
          "Junior Caminero", "Luke Keaschall", "Kerry Carpenter", "Nick Lodolo", "Trevor Rogers", "Colt Keith", "Kody Clemens", "Connor Norby", "Jose Caballero")


def load(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def failing(governor):
    return [(c.get("id"), c.get("surface"), c.get("message")) for c in governor.get("checks", []) if c.get("status") not in ("pass", "passed")]


def shape(governor):
    return next(({k: v for k, v in c["metrics"].items() if k != "pitcher_samples"}
                 for c in governor.get("checks", []) if c.get("id") == "prospect_top_board_role_shape"), {})


lines = ["# Rehearsal summary\n"]
statuses = load(out / "statuses.json") or []
failed = [row for row in statuses if row["exit"]]
lines.append(f"Steps run {len(statuses)}, failed {len(failed)}, total minutes {sum(r['seconds'] for r in statuses) // 60}.\n")
for row in failed:
    lines.append(f"## FAILED {row['stage']}: {row['step']} (exit {row['exit']})\n\n```\n" + "\n".join(row["tail"]) + "\n```\n")
for label, base in (("Before", old), ("After", new)):
    governor = load(base / "valucast_quality_governor.json")
    snapshot = load(base / "public_dynasty_snapshot.json")
    players = snapshot.get("players") or []
    lines.append(f"## {label}\n")
    lines.append(f"Governor generated {governor.get('generated_at')}, readiness {governor.get('surface_readiness')}, "
                 f"ready_for_public_snapshot {governor.get('ready_for_public_snapshot')}, failing {failing(governor)}\n")
    lines.append(f"Prospect role shape {shape(governor)}\n")
    lines.append(f"Snapshot generated {snapshot.get('generated_at')}, rows {len(players)}, readiness {snapshot.get('surface_readiness')}, "
                 f"blockers {snapshot.get('blockers')}\n")
    ordered = sorted(players, key=lambda r: r.get("rank") or 10**9)
    lines.append("Top 30: " + "; ".join(f"{r.get('rank')} {r.get('name')} {r.get('value')} {r.get('player_type')}" for r in ordered[:30]) + "\n")
    lines.append("Sample: " + "; ".join(f"{r.get('rank')} {r.get('name')} {r.get('value')} {r.get('player_type')}"
                                        for r in ordered if r.get("name") in SAMPLE) + "\n")
boards = [{r.get("id"): r for r in load(base / "public_dynasty_snapshot.json").get("players") or []} for base in (old, new)]
with (out / "combined_board.csv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(("id", "name", "type", "old_rank", "old_value", "new_rank", "new_value"))
    for key in sorted(set(boards[0]) | set(boards[1]), key=str):
        a, b = boards[0].get(key, {}), boards[1].get(key, {})
        writer.writerow((key, a.get("name") or b.get("name"), a.get("player_type") or b.get("player_type"),
                         a.get("rank"), a.get("value"), b.get("rank"), b.get("value")))
(out / "summary.md").write_text("\n".join(lines), encoding="utf-8", errors="backslashreplace")
print(len(failed), "failed steps")
