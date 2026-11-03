"""Compare rehearsal boards offline, emitting only identities and our values."""
from __future__ import annotations

import argparse
import ast
import csv
from dataclasses import replace as dc_replace
from functools import lru_cache
import json
import math
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from league_values.engine import ValuationEngine  # noqa: E402
from league_values.models import PlayerPool, ValuationResult  # noqa: E402
from league_values.playing_time import filter_by_playing_time  # noqa: E402
from league_values.post_processors import VolumeMultiplier  # noqa: E402
from web.config_builder import build_config  # noqa: E402
from web.projection_store import ProjectionStore  # noqa: E402

FIELDS = ("mlbam_id", "name", "role", "team", "age", "rank", "value")
MOVER_FIELDS = ("mlbam_id", "name", "role", "team", "age", "old_rank",
                "new_rank", "rank_shift", "old_value", "new_value", "value_shift")
AGE_BANDS = ("<=22", "23-25", "26-28", "29-31", "32+", "Unknown")


def _existing_nodes(path, names, namespace):
    """Execute only named original definitions, never module startup or imports."""
    selected = []
    found = set()
    for node in ast.parse(path.read_text(encoding="utf-8"), filename=str(path)).body:
        if isinstance(node, ast.FunctionDef):
            targets = {node.name}
        elif isinstance(node, ast.Assign):
            targets = {target.id for target in node.targets if isinstance(target, ast.Name)}
        else:
            continue
        if targets & names:
            if not targets <= names:
                raise RuntimeError("A shared assignment changed; review helper isolation")
            selected.append(node)
            found.update(targets)
    if found != names:
        raise RuntimeError("Existing redraft helpers changed; review helper isolation")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)


def app_helpers():
    """Reuse app functions verbatim without starting its archive-reading stores."""
    namespace = dict(__file__=str(ROOT / "app.py"), Path=Path, json=json, math=math,
                     lru_cache=lru_cache, dc_replace=dc_replace, PlayerPool=PlayerPool,
                     ValuationResult=ValuationResult, ValuationEngine=ValuationEngine,
                     VolumeMultiplier=VolumeMultiplier,
                     filter_by_playing_time=filter_by_playing_time)
    _existing_nodes(ROOT / "mlb/dynasty.py", {"_percentile", "_scale_value"}, namespace)
    _existing_nodes(ROOT / "app.py", {
        "_PITCHER_POOLS", "REDRAFT_PITCHER_ANCHOR", "engine", "MIN_HITTER_PA",
        "MIN_SP_IP", "MIN_RP_IP", "_PROJECTION_ONLY_UNAVAILABLE_STATUSES",
        "_INELIGIBLE_PLAYERS_PATH", "MLB_AVAILABILITY_PATH", "_ineligible_mlbam_ids",
        "_mlb_availability_by_id", "_has_current_actual_stats", "_mlbam_id",
        "_is_live_redraft_projection", "_valuation_players", "_merge_two_way_players",
        "_apply_redraft_pitcher_anchor", "_redraft_value_players", "_redraft_value_scale",
        "_redraft_scaled_value",
    }, namespace)
    return namespace


def redraft_rows(projections_path, ages=None, helpers=None):
    helpers = helpers if helpers is not None else app_helpers()
    ages = ages or {}
    # This is the value/rank path in app.py's _redraft_board_bundle, without
    # display-only metadata or a route call. No scoring formula lives here.
    players = helpers["_valuation_players"](active_store=ProjectionStore(projections_path))
    results = helpers["_redraft_value_players"](players, build_config())
    results.sort(key=lambda result: result.total_value, reverse=True)
    scale = helpers["_redraft_value_scale"](results)
    rows = []
    for rank, result in enumerate(results, 1):
        player = result.player
        mlbam_id = helpers["_mlbam_id"](player)
        role = "pitcher" if player.pool in helpers["_PITCHER_POOLS"] else "hitter"
        age = ages.get((mlbam_id, role))
        if age is None:
            age = player.metadata.get("age")
        rows.append(dict(mlbam_id=mlbam_id, name=player.name, role=role,
                         team=player.metadata.get("team") or "",
                         age=age,
                         rank=rank,
                         value=helpers["_redraft_scaled_value"](result.total_value, scale)))
    return rows


def _index(rows):
    indexed = {}
    for row in rows:
        if row.get("mlbam_id") in (None, "") or not row.get("role"):
            raise ValueError("Board row is missing an MLBAM identity or role")
        clean = {field: row.get(field) for field in FIELDS}
        clean["mlbam_id"] = str(clean["mlbam_id"])
        key = (clean["mlbam_id"], clean["role"])
        if key in indexed:
            raise ValueError("Board has duplicate (mlbam_id, role) identities")
        rank, value, age = clean["rank"], clean["value"], clean["age"]
        if (isinstance(rank, bool) or not isinstance(rank, int) or rank < 1
                or isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError("Board rank must be a positive integer and value must be finite")
        if age is not None and (not isinstance(age, (int, float)) or not math.isfinite(age)):
            raise ValueError("Board age must be finite or missing")
        indexed[key] = clean
    return indexed


def _spearman(pairs):
    if len(pairs) < 2:
        return None

    def average_ranks(values):
        ordered = sorted(range(len(values)), key=values.__getitem__)
        ranks = [0.0] * len(values)
        start = 0
        while start < len(values):
            end = start + 1
            while end < len(values) and values[ordered[end]] == values[ordered[start]]:
                end += 1
            for i in ordered[start:end]:
                ranks[i] = (start + 1 + end) / 2
            start = end
        return ranks

    xs, ys = (average_ranks([pair[i] for pair in pairs]) for i in (0, 1))
    x_mean, y_mean = mean(xs), mean(ys)
    xs = [x - x_mean for x in xs]
    ys = [y - y_mean for y in ys]
    denominator = math.sqrt(sum(x * x for x in xs) * sum(y * y for y in ys))
    return sum(x * y for x, y in zip(xs, ys)) / denominator if denominator else None


def _age_band(age):
    if age is None:
        return "Unknown"
    for ceiling, label in zip((22, 25, 28, 31), AGE_BANDS):
        if age <= ceiling:
            return label
    return "32+"


def _groups(rows, group_for, labels):
    groups = []
    for label in labels:
        group = [row for row in rows if group_for(row) == label]
        groups.append(dict(group=label, count=len(group),
                           mean_value_shift=mean(r["value_shift"] for r in group) if group else None,
                           mean_rank_shift=mean(r["rank_shift"] for r in group) if group else None))
    return groups


def _change(old, new):
    row = dict(new or old)
    row.pop("rank")
    row.pop("value")
    row.update(old_rank=old["rank"] if old else None, new_rank=new["rank"] if new else None,
               old_value=old["value"] if old else None, new_value=new["value"] if new else None,
               rank_shift=new["rank"] - old["rank"] if old and new else None,
               value_shift=new["value"] - old["value"] if old and new else None)
    return row


def compare_rows(old_rows, new_rows):
    old, new = _index(old_rows), _index(new_rows)
    common = old.keys() & new.keys()
    matched = [_change(old[key], new[key]) for key in sorted(common)]
    overlap = {}
    for cutoff in (100, 300):
        old_top = {key for key, row in old.items() if row["rank"] <= cutoff}
        new_top = {key for key, row in new.items() if row["rank"] <= cutoff}
        count = len(old_top & new_top)
        percent = 100 * count / len(old_top) if old_top else (100.0 if not new_top else 0.0)
        overlap[cutoff] = dict(count=count, old_count=len(old_top), new_count=len(new_top),
                               percent=percent)
    old_top = {key for key, row in old.items() if row["rank"] <= 300}
    new_top = {key for key, row in new.items() if row["rank"] <= 300}
    movers = [row for row in matched if row["old_rank"] <= 300 or row["new_rank"] <= 300]
    return dict(
        old_count=len(old), new_count=len(new), matched_count=len(common),
        old_only_count=len(old.keys() - new.keys()), new_only_count=len(new.keys() - old.keys()),
        spearman=_spearman([(r["old_rank"], r["new_rank"]) for r in matched]),
        overlap=overlap, matched=matched, movers=movers,
        by_role=_groups(matched, lambda row: row["role"], sorted({r["role"] for r in matched})),
        by_age_band=_groups(matched, lambda row: _age_band(row["age"]), AGE_BANDS),
        old_top50=sorted(old.values(), key=lambda row: row["rank"])[:50],
        new_top50=sorted(new.values(), key=lambda row: row["rank"])[:50],
        risers=sorted((r for r in movers if r["rank_shift"] < 0),
                      key=lambda row: (row["rank_shift"], row["new_rank"]))[:25],
        fallers=sorted((r for r in movers if r["rank_shift"] > 0),
                       key=lambda row: (-row["rank_shift"], row["new_rank"]))[:25],
        entered_top300=[_change(old.get(key), new[key]) for key in
                        sorted(new_top - old_top, key=lambda key: new[key]["rank"])],
        dropped_top300=[_change(old[key], new.get(key)) for key in
                        sorted(old_top - new_top, key=lambda key: old[key]["rank"])],
    )


def _ascii(value):
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _cell(value):
    if value is None:
        return "N/A"
    text = f"{value:.6f}" if isinstance(value, float) else str(value)
    return _ascii(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(_cell(value) for value in row) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def _report(summaries, validation):
    lines = [
        "# 2027 board rehearsal comparison\n",
        "The feed has no season label; 2027 is inferred. This report is a rehearsal, not live approval.\n",
        "All shifts are new minus old; negative rank shifts are risers. Joins use (mlbam_id, role). "
        "Overlap percentages are the share of the old top-N retained in the new top-N, using actual "
        "row counts when fewer than N exist. Spearman uses all matched rows and average ranks for ties; "
        "N/A means fewer than two matches or constant ranks.\n",
        "Group tables use all matched rows. Dynasty ages rise by one on the new board; age bands use "
        "the new board's age without adding another year. Redraft ages come from the corresponding "
        "dynasty artifact, falling back to projection age metadata. Both boards bucket matched rows "
        "by new board age; missing ages are Unknown. Old-only dropped players display old ages.\n",
        "Redraft reuses the original app helpers without importing app or calling /board. "
        "Both projection files use the same current availability and editorial exclusions. "
        "ProjectionStore may read adjacent metadata.json; values use the full eligible universe "
        "before display limits. Non-ASCII text is escaped.\n",
        "Public redraft defaults: categories mode; 5x5 hitting R, HR, RBI, SB, AVG; pitching W, SV, K, "
        "ERA, WHIP; no custom weights, split RP, rules, points, fixed baselines, or roster. "
        "Sources: app.py:4784-4839; web/category_registry.py:106-118; "
        "web/config_builder.py:30-98; src/league_values/models.py:60,166-169. "
        "Default source is Steamer (app.py:679-684). The engine uses VolumeMultiplier "
        "(app.py:733), floors of 100 PA / 40 SP IP / 20 RP IP (app.py:738-740), "
        "two-way merging and the 0.92 positive-pitcher anchor (app.py:4527-4599), "
        "then the existing fifth-percentile/max 0-100 scale (app.py:4602-4617).\n",
        "## New dynasty artifact readiness\n",
    ]
    for key in ("ready_for_live_consumers", "age_coverage_count", "age_coverage_rate", "age_coverage_threshold"):
        lines.append(f"- {key}: {_cell(validation.get(key))}")
    blockers = validation.get("blockers")
    lines.append("\nBlockers: " + ("N/A (not supplied)" if blockers is None else "None" if not blockers else ""))
    lines.extend("- " + _cell(blocker) for blocker in (blockers or []))
    for board, summary in summaries.items():
        lines.extend([f"\n## {board.title()}\n",
                      f"Rows: old={summary['old_count']}; new={summary['new_count']}; "
                      f"matched={summary['matched_count']}; old-only={summary['old_only_count']}; "
                      f"new-only={summary['new_only_count']}. "
                      f"Spearman on matched rows: {_cell(summary['spearman'])}.\n",
                      _table(["Cutoff", "Old rows", "New rows", "Overlap", "Retained %"],
                             ((cutoff, data["old_count"], data["new_count"], data["count"], data["percent"])
                              for cutoff, data in summary["overlap"].items()))])
        for key, title in (("by_role", "By role"), ("by_age_band", "By new board age band")):
            lines.extend([f"### {title}\n", _table(
                ["Group", "Count", "Mean value shift", "Mean rank shift"],
                ((r["group"], r["count"], r["mean_value_shift"], r["mean_rank_shift"])
                 for r in summary[key]))])
        old, new = summary["old_top50"], summary["new_top50"]
        side_by_side = []
        for i in range(max(len(old), len(new))):
            left = [old[i][field] for field in FIELDS] if i < len(old) else [None] * len(FIELDS)
            right = [new[i][field] for field in FIELDS] if i < len(new) else [None] * len(FIELDS)
            side_by_side.append(left + right)
        lines.extend(["### Top 50 side by side\n", _table(
            [f"{side} {field}" for side in ("Old", "New") for field in FIELDS], side_by_side)])
        for key, title in (("risers", "25 biggest risers among either top 300"),
                           ("fallers", "25 biggest fallers among either top 300"),
                           ("entered_top300", "New to top 300"), ("dropped_top300", "Dropped from top 300")):
            lines.extend([f"### {title}\n", _table(list(MOVER_FIELDS),
                          ([row[field] for field in MOVER_FIELDS] for row in summary[key]))
                          if summary[key] else "None.\n"])
    return "\n".join(lines) + "\n"


def compare_files(old_dynasty, new_dynasty, old_projections, new_projections, out):
    artifacts = [json.loads(Path(path).read_text(encoding="utf-8"))
                 for path in (old_dynasty, new_dynasty)]
    dynasty = compare_rows(artifacts[0]["players"], artifacts[1]["players"])
    ages = [{key: row["age"] for key, row in _index(artifact["players"]).items()}
            for artifact in artifacts]
    helpers = app_helpers()
    redraft = compare_rows(redraft_rows(old_projections, ages[0], helpers),
                           redraft_rows(new_projections, ages[1], helpers))
    summaries = dict(dynasty=dynasty, redraft=redraft)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(_report(summaries, artifacts[1].get("validation") or {}),
                                   encoding="ascii")
    with (out / "movers.csv").open("w", encoding="ascii", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("board",) + MOVER_FIELDS)
        writer.writeheader()
        for board, summary in summaries.items():
            for row in summary["movers"]:
                writer.writerow(dict(board=board, **{field: _ascii(row[field]) if row[field] is not None else ""
                                                     for field in MOVER_FIELDS}))
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("old-dynasty", "new-dynasty", "old-projections", "new-projections", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    summaries = compare_files(**vars(parser.parse_args()))
    for board, summary in summaries.items():
        print(f"{board}: old_rows={summary['old_count']} new_rows={summary['new_count']} "
              f"matched_rows={summary['matched_count']}")


if __name__ == "__main__":
    main()
