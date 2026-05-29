from __future__ import annotations

import csv
import io
import os
import sys
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, render_template, request, make_response

from dataclasses import replace as dc_replace

from league_values.engine import ValuationEngine
from league_values.post_processors import VolumeMultiplier
from league_values.playing_time import filter_by_playing_time
from league_values.models import PlayerPool, PlayerProjection, ValuationResult

from web.projection_store import ProjectionStore
from web.category_registry import (
    HITTING_CATEGORIES,
    PITCHING_CATEGORIES,
    CATEGORY_PRESETS,
    POINTS_PRESETS,
    DEFAULT_CATS,
    DEFAULT_PCATS,
)
from web.config_builder import build_config, build_url_params, parse_list
from web.dd_feed_store import DDFeedStore
from league_values.risk import RiskModel

app = Flask(__name__)

# Load projections once at startup
DATA_PATH = Path(__file__).parent / "data" / "projections" / "current.json"
store = ProjectionStore(DATA_PATH)

# Engine with volume adjustment
engine = ValuationEngine(post_processors=[VolumeMultiplier()])

# Playing-time floor: drop low-sample filler before valuation so category
# baselines are computed from real players only. VolumeMultiplier still
# discounts the partial-season players that survive these floors.
MIN_HITTER_PA = 100
MIN_SP_IP = 40
MIN_RP_IP = 20


def _valuation_players(always_keep=None):
    """Engine input: all projections minus sub-threshold filler.

    `always_keep` is a set of player ids (display id, suffixed id, or base_id)
    that are retained regardless of playing time, with two-way siblings joined
    on shared base_id inside filter_by_playing_time.
    """
    return filter_by_playing_time(
        store.get_all(),
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
        always_keep=always_keep or frozenset(),
    )


# Load DD Dynasty feed once at startup
DD_FEED_PATH = Path(os.environ.get("DD_DYNASTY_FEED_PATH",
                    str(Path(__file__).parent / "data" / "dd" / "dd_dynasty_feed.json")))
dd_store = DDFeedStore(DD_FEED_PATH)
risk_model = RiskModel()


def _compute_dynasty_dollars(rows, num_teams=12, budget=200):
    """Convert dynasty values to auction dollars proportionally."""
    positive = [r for r in rows if r.dynasty_value > 0]
    total_positive = sum(r.dynasty_value for r in positive)
    total_budget = budget * num_teams
    dollars = {}
    if total_positive > 0:
        for r in rows:
            if r.dynasty_value > 0:
                dollars[r.id] = round(r.dynasty_value / total_positive * total_budget, 1)
            else:
                dollars[r.id] = 0.0
    return dollars


def _compute_dynasty_tiers(rows, num_tiers=8):
    """Assign tiers from dynasty value gaps."""
    if len(rows) < 2:
        return {r.id: 1 for r in rows}
    gaps = []
    for i in range(len(rows) - 1):
        gap = rows[i].dynasty_value - rows[i + 1].dynasty_value
        if gap > 0:
            gaps.append((gap, i))
    sorted_gaps = sorted(gaps, key=lambda x: x[0], reverse=True)
    break_indices = sorted([g[1] for g in sorted_gaps[:num_tiers - 1]])
    tiers_list = []
    current_tier = 1
    for i, r in enumerate(rows):
        tiers_list.append([r.id, current_tier])
        if i in break_indices:
            current_tier += 1
    if len(rows) >= 3:
        changed = True
        while changed:
            changed = False
            tier_counts = {}
            for _, t in tiers_list:
                tier_counts[t] = tier_counts.get(t, 0) + 1
            for tier_num in sorted(tier_counts.keys()):
                if tier_counts[tier_num] < 3:
                    if tier_num == min(tier_counts.keys()):
                        merge_target = tier_num + 1 if tier_num + 1 in tier_counts else tier_num
                    else:
                        merge_target = tier_num - 1
                    if merge_target != tier_num:
                        for entry in tiers_list:
                            if entry[1] == tier_num:
                                entry[1] = merge_target
                        changed = True
                        break
        unique_tiers = sorted(set(t for _, t in tiers_list))
        remap = {old: new for new, old in enumerate(unique_tiers, 1)}
        for entry in tiers_list:
            entry[1] = remap[entry[1]]
    return {pid: t for pid, t in tiers_list}


def _build_dynasty_context(args):
    """Build template context for DD Dynasty mode. Bypasses engine entirely."""
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")
    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    rows = rows[:200]
    dynasty_dollars = _compute_dynasty_dollars(rows)
    tiers = _compute_dynasty_tiers(rows)
    risk_assessments = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
    return {
        "mode": "dd_dynasty",
        "pool": pool,
        "position": position,
        "search": search,
        "dd_rows": rows,
        "dynasty_dollars": dynasty_dollars,
        "tiers": tiers,
        "risk_assessments": risk_assessments,
        "dd_available": dd_store.is_available,
        "dd_generated_at": dd_store.generated_at,
        "as_of": store.as_of,
    }


def _merge_two_way_players(results: list[ValuationResult]) -> list[ValuationResult]:
    """Merge results for two-way players (e.g. Ohtani as hitter + pitcher).

    Combines total_value, category_values, raw_values, and z_scores into one entry.
    Uses the hitter entry as the base (positions, metadata) and adds pitcher contributions.
    """
    by_id: dict[str, list[ValuationResult]] = {}
    for r in results:
        # Use base_id (from metadata) to group two-way player entries
        base_id = r.player.metadata.get("base_id", r.player.id)
        by_id.setdefault(base_id, []).append(r)

    merged = []
    for player_id, group in by_id.items():
        if len(group) == 1:
            merged.append(group[0])
            continue

        # Multiple entries for same ID — merge them
        # Use hitter as base (or first entry if no hitter)
        base = next((r for r in group if r.player.pool == PlayerPool.HITTER), group[0])
        others = [r for r in group if r is not base]

        total_value = base.total_value + sum(r.total_value for r in others)
        raw_values = dict(base.raw_values)
        z_scores = dict(base.z_scores)
        category_values = dict(base.category_values)

        for other in others:
            for k, v in other.raw_values.items():
                if raw_values.get(k) is None:
                    raw_values[k] = v
            for k, v in other.z_scores.items():
                if z_scores.get(k, 0) == 0 and v != 0:
                    z_scores[k] = v
            for k, v in other.category_values.items():
                if category_values.get(k, 0) == 0 and v != 0:
                    category_values[k] = v

        # Combine positions
        all_positions = list(base.player.positions)
        for other in others:
            for pos in other.player.positions:
                if pos not in all_positions:
                    all_positions.append(pos)

        merged_player = dc_replace(base.player, positions=tuple(all_positions))
        merged_result = ValuationResult(
            player=merged_player,
            total_value=total_value,
            raw_values=raw_values,
            z_scores=z_scores,
            category_values=category_values,
            points=base.points,
        )
        merged.append(merged_result)

    return sorted(merged, key=lambda r: r.total_value, reverse=True)


def _compute_position_ranks(results: list[ValuationResult]) -> dict[str, str]:
    """Compute rank within position group for each player. Returns player_id -> 'SP12' etc."""
    pos_counters: dict[str, int] = {}
    position_ranks: dict[str, str] = {}
    for r in results:
        positions = r.player.positions
        pool = r.player.pool
        # Determine position key for ranking
        if pool == PlayerPool.STARTER or (pool == PlayerPool.PITCHER and "SP" in positions):
            pos_key = "SP"
        elif pool == PlayerPool.RELIEVER or "RP" in positions:
            pos_key = "RP"
        elif positions:
            # Use primary position; treat two-way hitter-side as their fielding position
            pos_key = positions[0]
        else:
            pos_key = "DH"
        pos_counters[pos_key] = pos_counters.get(pos_key, 0) + 1
        position_ranks[r.player.id] = f"{pos_key}{pos_counters[pos_key]}"
    return position_ranks


def _compute_dollar_values(results: list[ValuationResult], num_teams: int = 12, budget: int = 200) -> dict[str, float]:
    """Convert z-score values to auction dollar values proportionally."""
    positive_results = [r for r in results if r.total_value > 0]
    total_positive = sum(r.total_value for r in positive_results)
    total_budget = budget * num_teams
    dollar_values: dict[str, float] = {}
    if total_positive > 0:
        for r in results:
            if r.total_value > 0:
                dollar_values[r.player.id] = round(r.total_value / total_positive * total_budget, 1)
            else:
                dollar_values[r.player.id] = 0.0
    return dollar_values


def _compute_tiers(results: list[ValuationResult], num_tiers: int = 8) -> dict[str, int]:
    """Assign tier numbers (1 = best) based on value gaps between consecutive players.

    Finds the largest gaps in the value sequence and uses them as tier boundaries.
    Enforces invariant: no tier has fewer than 3 players (unless total < 3).
    """
    if len(results) < 2:
        return {r.player.id: 1 for r in results}

    gaps = []
    for i in range(len(results) - 1):
        gap = results[i].total_value - results[i + 1].total_value
        gaps.append((gap, i))

    sorted_gaps = sorted(gaps, key=lambda x: x[0], reverse=True)
    # Only use gaps with a positive magnitude as tier boundaries
    break_indices = sorted([g[1] for g in sorted_gaps[:num_tiers - 1] if g[0] > 0])

    tiers_list = []
    current_tier = 1
    for i, r in enumerate(results):
        tiers_list.append([r.player.id, current_tier])
        if i in break_indices:
            current_tier += 1

    if len(results) >= 3:
        changed = True
        while changed:
            changed = False
            tier_counts: dict[int, int] = {}
            for _, t in tiers_list:
                tier_counts[t] = tier_counts.get(t, 0) + 1

            for tier_num in sorted(tier_counts.keys()):
                if tier_counts[tier_num] < 3:
                    if tier_num == min(tier_counts.keys()):
                        merge_target = tier_num + 1 if tier_num + 1 in tier_counts else tier_num
                    else:
                        merge_target = tier_num - 1
                    if merge_target != tier_num:
                        for entry in tiers_list:
                            if entry[1] == tier_num:
                                entry[1] = merge_target
                        changed = True
                        break

        unique_tiers = sorted(set(t for _, t in tiers_list))
        remap = {old: new for new, old in enumerate(unique_tiers, 1)}
        for entry in tiers_list:
            entry[1] = remap[entry[1]]

    return {pid: t for pid, t in tiers_list}


def _config_summary(mode: str, cats: list[str], pcats: list[str], split_rp: bool) -> str:
    """Build a human-readable summary of the active config."""
    from web.category_registry import CATEGORY_PRESETS
    if mode == "points":
        return "Points League \u00b7 12 teams \u00b7 $200 budget"
    for name, preset in CATEGORY_PRESETS.items():
        if cats == preset["cats"] and pcats == preset["pcats"]:
            label = "Standard 5x5" if name == "5x5" else "6x6 (OBP/QS)" if name == "6x6" else name
            suffix = " \u00b7 SP/RP split" if split_rp else ""
            return f"{label} \u00b7 12 teams \u00b7 $200 budget{suffix}"
    cat_count = len(cats) + len(pcats)
    suffix = " \u00b7 SP/RP split" if split_rp else ""
    return f"Custom {cat_count} categories \u00b7 12 teams \u00b7 $200 budget{suffix}"


def _build_context(args):
    """Parse request args and build template context."""
    mode = args.get("mode", "categories")
    cats = parse_list(args.getlist("cats")) or DEFAULT_CATS
    pcats = parse_list(args.getlist("pcats")) or DEFAULT_PCATS
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")
    rules_str = args.get("rules", "")
    split_rp = args.get("split_rp", "") == "on"

    # Collect pt_* params for points mode
    pt_params = {}
    for key in args:
        if key.startswith("pt_"):
            pt_params[key[3:]] = args[key]

    # Collect w_* params for category weights
    weights: dict[str, float] = {}
    for key in args:
        if key.startswith("w_"):
            try:
                weights[key[2:]] = float(args[key])
            except ValueError:
                pass

    # Build config and run engine
    config = build_config(
        mode=mode, cats=cats, pcats=pcats,
        rules_str=rules_str, pt_params=pt_params if pt_params else None,
        split_rp=split_rp, weights=weights if weights else None,
    )
    results = engine.value_players(store.get_all(), config)
    results = _merge_two_way_players(results)

    # Filter results for display
    if pool:
        if pool == "pitcher":
            results = [
                r for r in results
                if r.player.pool in (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER)
            ]
        else:
            results = [r for r in results if r.player.pool == PlayerPool(pool)]
    if position:
        results = [r for r in results if position in r.player.positions]
    if search:
        query = search.lower()
        results = [r for r in results if query in r.player.name.lower()]

    # Limit to top 200
    results = results[:200]

    # Active categories for column headers
    active_categories = list(config.categories) if hasattr(config, "categories") else []

    # Build display columns — collapse SP/RP pairs into single columns
    if split_rp and mode != "points":
        display_columns = []
        seen_base = set()
        for cat in active_categories:
            if cat.id.startswith("SP_"):
                base_id = cat.id[3:]
                if base_id not in seen_base:
                    seen_base.add(base_id)
                    from web.category_registry import _ALL_CATEGORIES
                    orig = _ALL_CATEGORIES.get(base_id)
                    label = orig.label if orig else base_id
                    display_columns.append({
                        "id": base_id, "label": label,
                        "sp_id": f"SP_{base_id}", "rp_id": f"RP_{base_id}",
                        "split": True,
                    })
            elif cat.id.startswith("RP_"):
                pass  # Handled by SP_ entry
            else:
                display_columns.append({
                    "id": cat.id, "label": cat.label, "split": False,
                })
    else:
        display_columns = [
            {"id": cat.id, "label": cat.label, "split": False}
            for cat in active_categories
        ]

    # Position ranks, auction dollar values, and tier visualization
    position_ranks = _compute_position_ranks(results)
    dollar_values = _compute_dollar_values(results)
    tiers = _compute_tiers(results)

    return {
        "mode": mode,
        "cats": cats,
        "pcats": pcats,
        "pool": pool,
        "position": position,
        "search": search,
        "rules_str": rules_str,
        "pt_params": pt_params,
        "split_rp": split_rp,
        "weights": weights,
        "results": results,
        "active_categories": active_categories,
        "display_columns": display_columns,
        "hitting_categories": HITTING_CATEGORIES,
        "pitching_categories": PITCHING_CATEGORIES,
        "category_presets": CATEGORY_PRESETS,
        "points_presets": POINTS_PRESETS,
        "player_count": store.player_count,
        "config": config,
        "position_ranks": position_ranks,
        "dollar_values": dollar_values,
        "tiers": tiers,
        "config_summary": _config_summary(mode, cats, pcats, split_rp),
        "as_of": store.as_of,
    }


@app.route("/")
def index():
    mode = request.args.get("mode", "categories")
    if mode in ("dd_dynasty", "prospects"):
        if not dd_store.is_available:
            fallback_args = request.args.to_dict(flat=False)
            fallback_args["mode"] = ["categories"]
            from werkzeug.datastructures import ImmutableMultiDict
            ctx = _build_context(ImmutableMultiDict(
                (k, v) for k, vals in fallback_args.items() for v in vals
            ))
            ctx["notice"] = "Dynasty data is not available. Showing default rankings."
            ctx["dd_available"] = False
            return render_template("index.html", **ctx)
        ctx = _build_dynasty_context(request.args)
        if mode == "prospects":
            rows = dd_store.filter(
                pool="prospect",
                position=ctx.get("position") or None,
                search=ctx.get("search") or None,
            )
            rows = rows[:200]
            ctx["dd_rows"] = rows
            ctx["dynasty_dollars"] = _compute_dynasty_dollars(rows)
            ctx["tiers"] = _compute_dynasty_tiers(rows)
            ctx["risk_assessments"] = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
            ctx["mode"] = "prospects"
        return render_template("index.html", **ctx)
    ctx = _build_context(request.args)
    ctx["dd_available"] = dd_store.is_available
    return render_template("index.html", **ctx)


@app.route("/rankings")
def rankings():
    mode = request.args.get("mode", "categories")
    if mode in ("dd_dynasty", "prospects"):
        if not dd_store.is_available:
            from werkzeug.datastructures import ImmutableMultiDict
            fallback_args = request.args.to_dict(flat=False)
            fallback_args["mode"] = ["categories"]
            ctx = _build_context(ImmutableMultiDict(
                (k, v) for k, vals in fallback_args.items() for v in vals
            ))
            ctx["dd_available"] = False
        else:
            ctx = _build_dynasty_context(request.args)
            if mode == "prospects":
                rows = dd_store.filter(
                    pool="prospect",
                    position=ctx.get("position") or None,
                    search=ctx.get("search") or None,
                )
                rows = rows[:200]
                ctx["dd_rows"] = rows
                ctx["dynasty_dollars"] = _compute_dynasty_dollars(rows)
                ctx["tiers"] = _compute_dynasty_tiers(rows)
                ctx["risk_assessments"] = {row.id: risk_model.evaluate_dynasty(row) for row in rows}
                ctx["mode"] = "prospects"
        html = render_template("partials/rankings_response.html", **ctx)
        response = make_response(html)
        params = {"mode": mode}
        if ctx.get("pool") and mode != "prospects":
            params["pool"] = ctx["pool"]
        if ctx.get("position"):
            params["position"] = ctx["position"]
        if ctx.get("search"):
            params["search"] = ctx["search"]
        url_params = urlencode({k: v for k, v in params.items() if v})
        push_url = f"/?{url_params}" if url_params else "/"
        response.headers["HX-Replace-Url"] = push_url
        return response
    ctx = _build_context(request.args)
    ctx["dd_available"] = dd_store.is_available
    html = render_template("partials/rankings_response.html", **ctx)
    response = make_response(html)
    url_params = build_url_params(
        mode=ctx["mode"], cats=ctx["cats"], pcats=ctx["pcats"],
        pool=ctx["pool"], position=ctx["position"], search=ctx["search"],
        rules_str=ctx["rules_str"], split_rp=ctx["split_rp"],
        weights=ctx["weights"] if ctx["weights"] else None,
    )
    push_url = f"/?{url_params}" if url_params else "/"
    response.headers["HX-Replace-Url"] = push_url
    return response


@app.route("/player/<player_id>")
def player_detail(player_id):
    mode = request.args.get("mode", "categories")

    if mode in ("dd_dynasty", "prospects") and dd_store.is_available:
        dd_row = dd_store.get_by_id(player_id)
        if dd_row is None:
            return "<div class='error'>Player not found</div>", 404

        risk = risk_model.evaluate_dynasty(dd_row)

        mlb_stats = None
        mlb_stats_actual = None
        mlb_stats_ros = None
        if not dd_row.is_prospect:
            # Try to find matching season outlook by name
            name_lower = dd_row.name.lower()
            for proj in store.get_all():
                if proj.name.lower() == name_lower:
                    mlb_stats = proj.stats
                    mlb_stats_actual = proj.metadata.get("stats_actual")
                    mlb_stats_ros = proj.metadata.get("stats_ros")
                    break

        return render_template(
            "partials/player_detail_dynasty.html",
            row=dd_row,
            risk=risk,
            mlb_stats=mlb_stats,
            mlb_stats_actual=mlb_stats_actual,
            mlb_stats_ros=mlb_stats_ros,
        )

    player_proj = store.get_by_id(player_id)
    if not player_proj:
        return "<div class='error'>Player not found</div>", 404

    ctx = _build_context(request.args)
    result = next((r for r in ctx["results"] if r.player.id == player_id), None)

    if result is None:
        config = ctx["config"]
        all_results = engine.value_players(store.get_all(), config)
        result = next((r for r in all_results if r.player.id == player_id), None)

    return render_template(
        "partials/player_detail.html",
        player=player_proj,
        result=result,
        active_categories=ctx["active_categories"],
    )


@app.route("/compare")
def compare():
    mode = request.args.get("mode", "categories")
    if mode in ("dd_dynasty", "prospects"):
        return "<div class='error'>Compare is not available in this mode.</div>", 400

    p1_id = request.args.get("p1", "")
    p2_id = request.args.get("p2", "")

    ctx = _build_context(request.args)
    config = ctx["config"]
    all_results = engine.value_players(store.get_all(), config)

    r1 = next((r for r in all_results if r.player.id == p1_id), None)
    r2 = next((r for r in all_results if r.player.id == p2_id), None)

    return render_template(
        "partials/compare_modal.html",
        r1=r1,
        r2=r2,
        active_categories=ctx["active_categories"],
    )


@app.route("/export")
def export_csv():
    mode = request.args.get("mode", "categories")

    if mode in ("dd_dynasty", "prospects") and dd_store.is_available:
        ctx = _build_dynasty_context(request.args)
        if mode == "prospects":
            rows = dd_store.filter(
                pool="prospect",
                position=ctx.get("position") or None,
                search=ctx.get("search") or None,
            )
            rows = rows[:200]
            ctx["dd_rows"] = rows
            ctx["dynasty_dollars"] = _compute_dynasty_dollars(rows)
        rows = ctx["dd_rows"]
        dynasty_dollars = ctx["dynasty_dollars"]
        risk_assessments = {row.id: risk_model.evaluate_dynasty(row) for row in rows}

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Overall Dynasty Rank", "Player", "Type", "Positions", "Team",
                         "Age", "Dynasty Value", "Dynasty $", "Risk Level", "Value Low",
                         "Value High", "Risk Drivers", "Prospect Rank", "Level", "ETA"])
        for row in rows:
            risk = risk_assessments.get(row.id)
            writer.writerow([
                row.dynasty_rank, row.name, row.player_type.upper(),
                ", ".join(row.positions) or "", row.team, row.age or "",
                row.dynasty_value, dynasty_dollars.get(row.id, 0),
                risk.risk_level if risk else "",
                risk.value_low if risk else "",
                risk.value_high if risk else "",
                ", ".join(risk.driver_labels) if risk else "",
                row.prospect_rank or "", row.level or "", row.eta or "",
            ])

        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = "attachment; filename=valucast-dynasty-rankings.csv"
        return response

    ctx = _build_context(request.args)
    results = ctx["results"]
    display_columns = ctx["display_columns"]
    position_ranks = ctx["position_ranks"]
    dollar_values = ctx["dollar_values"]
    tiers = ctx["tiers"]

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    header = ["Rank", "Player", "Positions", "Team", "Position Rank", "Tier", "Auction $", "Value"]
    for col in display_columns:
        header.append(col["label"])
    writer.writerow(header)

    # Data rows
    pitcher_pos = {"SP", "RP", "P"}
    for i, result in enumerate(results, 1):
        # For hitter-pool results, strip pitcher positions from display
        if result.player.pool == PlayerPool.HITTER:
            display_positions = [p for p in result.player.positions if p not in pitcher_pos]
        else:
            display_positions = list(result.player.positions)
        row = [
            i,
            result.player.name,
            ", ".join(display_positions) or "DH",
            result.player.metadata.get("team", ""),
            position_ranks.get(result.player.id, ""),
            tiers.get(result.player.id, ""),
            dollar_values.get(result.player.id, 0),
            round(result.total_value, 2),
        ]
        for col in display_columns:
            if col.get("split"):
                sp_raw = result.raw_values.get(col["sp_id"])
                rp_raw = result.raw_values.get(col["rp_id"])
                val = result.category_values.get(col["sp_id"], 0) + result.category_values.get(col["rp_id"], 0)
                row.append(round(val, 1) if sp_raw is not None or rp_raw is not None else "")
            else:
                raw = result.raw_values.get(col["id"])
                val = result.category_values.get(col["id"], 0)
                row.append(round(val, 1) if raw is not None else "")
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=valucast-rankings.csv"
    return response


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=True, host="0.0.0.0", port=port)
