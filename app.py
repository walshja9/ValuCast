from __future__ import annotations

import sys
from pathlib import Path

from flask import Flask, render_template, request, make_response

from league_values.engine import ValuationEngine
from league_values.post_processors import VolumeMultiplier
from league_values.models import PlayerPool

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

app = Flask(__name__)

# Load projections once at startup
DATA_PATH = Path(__file__).parent / "data" / "projections" / "current.json"
store = ProjectionStore(DATA_PATH)

# Engine with volume adjustment
engine = ValuationEngine(post_processors=[VolumeMultiplier()])


def _build_context(args):
    """Parse request args and build template context."""
    mode = args.get("mode", "categories")
    cats = parse_list(args.getlist("cats")) or DEFAULT_CATS
    pcats = parse_list(args.getlist("pcats")) or DEFAULT_PCATS
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")
    rules_str = args.get("rules", "")

    # Collect pt_* params for points mode
    pt_params = {}
    for key in args:
        if key.startswith("pt_"):
            pt_params[key[3:]] = args[key]

    # Build config and run engine
    config = build_config(
        mode=mode, cats=cats, pcats=pcats,
        rules_str=rules_str, pt_params=pt_params if pt_params else None,
    )
    results = engine.value_players(store.get_all(), config)

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

    return {
        "mode": mode,
        "cats": cats,
        "pcats": pcats,
        "pool": pool,
        "position": position,
        "search": search,
        "rules_str": rules_str,
        "pt_params": pt_params,
        "results": results,
        "active_categories": active_categories,
        "hitting_categories": HITTING_CATEGORIES,
        "pitching_categories": PITCHING_CATEGORIES,
        "category_presets": CATEGORY_PRESETS,
        "points_presets": POINTS_PRESETS,
        "player_count": store.player_count,
        "config": config,
    }


@app.route("/")
def index():
    ctx = _build_context(request.args)
    return render_template("index.html", **ctx)


@app.route("/rankings")
def rankings():
    ctx = _build_context(request.args)
    html = render_template("partials/rankings_response.html", **ctx)
    response = make_response(html)
    url_params = build_url_params(
        mode=ctx["mode"], cats=ctx["cats"], pcats=ctx["pcats"],
        pool=ctx["pool"], position=ctx["position"], search=ctx["search"],
        rules_str=ctx["rules_str"],
    )
    push_url = f"/?{url_params}" if url_params else "/"
    response.headers["HX-Replace-Url"] = push_url
    return response


@app.route("/player/<player_id>")
def player_detail(player_id):
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


if __name__ == "__main__":
    app.run(debug=True, port=5001)
