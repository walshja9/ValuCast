from __future__ import annotations

import csv
import io
import math
import os
import sys
import time
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from flask import Flask, render_template, request, make_response, jsonify, redirect

from dataclasses import replace as dc_replace

from league_values.engine import ValuationEngine
from league_values.post_processors import VolumeMultiplier
from league_values.playing_time import filter_by_playing_time
from league_values.models import PlayerPool, ValuationResult

from web.projection_catalog import ProjectionCatalog
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
from web.public_snapshot_store import PublicSnapshotStore
from web.valucast_buy_store import ValuCastBuyStore
from web.league_settings import parse_league_settings
from web.league_import import import_league, ImportError_
from web.season_outlook import (
    build_outlook_match_index,
    find_season_outlook,
    find_season_outlook_split,
    find_outlook_projections,
    split_outlook,
)
from web.statcast_store import StatcastStore
from web.player_links import build_player_links
from web.value_spark import build_spark
from web import buy_score
from web import prospect_percentiles

app = Flask(__name__)


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


# Per-category projected-stat formatting for the rankings columns.
_RATE_3DP = {"AVG", "OBP", "SLG", "OPS"}            # .280
_RATE_2DP = {"ERA", "WHIP", "K_BB", "K_9", "BB_9"}  # 3.24
_DECIMAL_1 = {"IP"}                                  # 182.1

_MONTH_NAMES = (
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
)


def _editorial_date(value):
    """Return the same uppercase editorial date used by the buys graphic macro."""
    date_text = (value or "")[:10]
    try:
        month = int(date_text[5:7])
        day = int(date_text[8:10])
    except (TypeError, ValueError):
        return date_text
    if 1 <= month <= 12 and len(date_text) >= 10:
        return f"{_MONTH_NAMES[month - 1]} {day}, {date_text[:4]}"
    return date_text


@app.template_filter("format_stat")
def format_stat(value, cat_id):
    """Format a projected stat for display, keyed by category id."""
    if value is None:
        return "—"  # em dash
    if cat_id in _RATE_3DP:
        s = f"{value:.3f}"
        return s.replace("0.", ".", 1) if s.startswith(("0.", "-0.")) else s
    if cat_id in _RATE_2DP:
        return f"{value:.2f}"
    if cat_id in _DECIMAL_1:
        return f"{value:.1f}"
    return f"{value:.0f}"

# Projection sources. Steamer (season outlook) is the default; ValuCast H+P is the
# opt-in combined in-house source. App only LOADS committed runs — no runtime model.
DATA_PATH = Path(__file__).parent / "data" / "projections" / "current.json"
VALUCAST_HP_PATH = (
    Path(__file__).parent / "projections" / "runs" / "valucast_hp_2026_v1" / "projections.json"
)
CATALOG = ProjectionCatalog(
    {"steamer": str(DATA_PATH), "valucast": str(VALUCAST_HP_PATH)}, default="steamer")
store = CATALOG.store_for("steamer")   # module-level default (kept for existing imports)

# Committed Statcast percentile snapshot (Baseball Savant) for player cards.
# Missing artifact -> cards simply render without the percentile section.
statcast = StatcastStore()

_PITCHER_POOLS = (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER)


def _card_extras(name, pool, metadata):
    """Statcast percentile groups + outbound links for a player card."""
    mlbam_id = (metadata or {}).get("mlbam_id")
    fangraphs_id = (metadata or {}).get("fangraphs_id")
    return {
        "statcast_groups": statcast.display_groups(
            mlbam_id, prefer_pitching=pool in _PITCHER_POOLS),
        "statcast_asof": statcast.as_of,
        "player_links": build_player_links(
            name, mlbam_id=mlbam_id, fangraphs_id=fangraphs_id),
    }


class SourceError(Exception):
    """Raised when a requested ?source= is unknown or its run is unavailable."""


def _active_store(source):
    """Resolve a request's projection source. None/empty/'steamer' -> default store.
    Unknown source or a single-pool/missing valucast run -> SourceError (clean 400);
    never a silent fallback."""
    if not source or source == "steamer":
        return store
    try:
        s = CATALOG.store_for(source)
    except (KeyError, FileNotFoundError):
        raise SourceError(source)
    if source == "valucast":
        pools = {p.pool.value for p in s.get_all()}
        if "hitter" not in pools or not ({"starter", "reliever", "pitcher"} & pools):
            raise SourceError(source)
    return s


@app.errorhandler(SourceError)
def _handle_source_error(_e):
    return "<div class='error'>Unknown or unavailable projection source.</div>", 400


@app.errorhandler(404)
def _handle_not_found(_e):
    return render_template(
        "error.html", code=404,
        message="That page doesn't exist — the boards live on the home page."), 404


@app.errorhandler(500)
def _handle_server_error(_e):
    return render_template(
        "error.html", code=500,
        message="Something broke on our end. Try again in a minute."), 500


@app.route("/robots.txt")
def robots_txt():
    return app.send_static_file("robots.txt")


@app.route("/favicon.ico")
def favicon():
    return app.send_static_file("favicon.ico")


# Engine with volume adjustment
engine = ValuationEngine(post_processors=[VolumeMultiplier()])

# Playing-time floor: drop low-sample filler before valuation so category
# baselines are computed from real players only. VolumeMultiplier still
# discounts the partial-season players that survive these floors.
MIN_HITTER_PA = 100
MIN_SP_IP = 40
MIN_RP_IP = 20


def _valuation_players(always_keep=None, active_store=None):
    """Engine input: all projections minus sub-threshold filler.

    `always_keep` is a set of player ids (display id, suffixed id, or base_id)
    that are retained regardless of playing time, with two-way siblings joined
    on shared base_id inside filter_by_playing_time. `active_store` defaults to the
    module Steamer store (so existing callers/imports are unchanged).
    """
    return filter_by_playing_time(
        (active_store or store).get_all(),
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
        always_keep=always_keep or frozenset(),
    )


# Load DD Dynasty feed once at startup
DD_FEED_PATH = Path(os.environ.get("DD_DYNASTY_FEED_PATH",
                    str(Path(__file__).parent / "data" / "dd" / "dd_dynasty_feed.json")))
PUBLIC_SNAPSHOT_PATH = Path(os.environ.get(
    "VALUCAST_PUBLIC_SNAPSHOT_PATH",
    str(Path(__file__).parent / "data" / "public" / "public_dynasty_snapshot.json"),
))
VALUCAST_BUYS_PATH = Path(os.environ.get(
    "VALUCAST_BUYS_PATH",
    str(Path(__file__).parent / "data" / "models" / "valucast_prospect_buys.json"),
))
legacy_dd_store = DDFeedStore(DD_FEED_PATH)
public_snapshot_store = PublicSnapshotStore(PUBLIC_SNAPSHOT_PATH)
valucast_buy_store = ValuCastBuyStore(VALUCAST_BUYS_PATH)


def _select_dynasty_store(dd_candidate, snapshot_candidate, use_public_snapshot=None):
    enabled = (
        os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT") == "1"
        if use_public_snapshot is None
        else bool(use_public_snapshot)
    )
    if (
        enabled
        and snapshot_candidate.is_available
        and snapshot_candidate.ready_for_live_consumers
    ):
        return snapshot_candidate, "valucast_public_snapshot"
    return dd_candidate, "dd_feed"


def _select_buy_source(
    dd_candidate,
    buy_candidate,
    *,
    use_valucast_buys=None,
    public_snapshot_active=None,
):
    enabled = (
        os.environ.get("VALUCAST_USE_VALUCAST_BUYS") == "1"
        if use_valucast_buys is None
        else bool(use_valucast_buys)
    )
    snapshot_active = (
        dynasty_data_source == "valucast_public_snapshot"
        if public_snapshot_active is None
        else bool(public_snapshot_active)
    )
    if (
        enabled
        and snapshot_active
        and buy_candidate.is_available
        and buy_candidate.ready_for_live_consumers
    ):
        return buy_candidate, "valucast_buys"
    return dd_candidate, "dd_feed"


dd_store, dynasty_data_source = _select_dynasty_store(
    legacy_dd_store, public_snapshot_store
)
prospect_pool = prospect_percentiles.build_pool(dd_store.get_all()) if dd_store.is_available else {}

# In production (VALUCAST_REQUIRE_DD=1) treat DD as required: refuse to start if the
# feed failed to load. With gunicorn --preload this raises in the master, so the
# candidate deploy fails and Render keeps the prior healthy deploy live — a corrupt
# snapshot can never replace a working deployment and blank the tabs.
if os.environ.get("VALUCAST_REQUIRE_DD") == "1" and not legacy_dd_store.is_available:
    raise RuntimeError(
        f"DD feed required but unavailable: {DD_FEED_PATH}. Refusing to start so the "
        "prior healthy Render deploy stays live."
    )

def _compute_dynasty_dollars(rows, settings):
    """Replacement-adjusted auction dollars for a league shaped by `settings`.

    Rostered pool = top (teams x roster) by dynasty value. Replacement value =
    the value at the cutoff rank. Every rostered player gets a $1 floor; the
    remaining budget is split proportionally to value ABOVE replacement.
    Below the cutoff = $0. Total payout == teams x budget (the league's cash), except the degenerate all-equal-values pool where only the $1 floors are paid.
    """
    ordered = sorted(rows, key=lambda r: r.dynasty_value, reverse=True)
    cutoff = min(settings.roster_cutoff, len(ordered))
    rostered, bench = ordered[:cutoff], ordered[cutoff:]
    dollars = {r.id: 0.0 for r in bench}
    if not rostered:
        return dollars
    replacement = rostered[-1].dynasty_value
    surplus = {r.id: r.dynasty_value - replacement for r in rostered}
    total_surplus = sum(surplus.values())
    spendable = settings.total_budget - len(rostered)  # $1 floor reserved each
    for r in rostered:
        share = (surplus[r.id] / total_surplus * spendable) if total_surplus > 0 else 0.0
        dollars[r.id] = round(1.0 + share, 1)
    return dollars


DYNASTY_ELITE_FLOOR = 140.0


def _compute_dynasty_tiers(rows, num_tiers=8):
    """Assign tiers from dynasty value gaps.

    Values >= DYNASTY_ELITE_FLOOR (the 140+ band on the 0-150 scale) are always
    tier 1 — elite is an absolute badge, never merged into the tier below by the
    min-3 rule. Gap-based tiering applies below the floor, starting at tier 2.
    """
    if len(rows) < 2:
        return {r.id: 1 for r in rows}
    elite = [r for r in rows if r.dynasty_value >= DYNASTY_ELITE_FLOOR]
    if not elite:
        return _gap_tiers(rows, num_tiers)
    tiers = {r.id: 1 for r in elite}
    rest = [r for r in rows if r.dynasty_value < DYNASTY_ELITE_FLOOR]
    if rest:
        for pid, t in _gap_tiers(rest, num_tiers - 1).items():
            tiers[pid] = t + 1
    return tiers


def _gap_tiers(rows, num_tiers=8):
    """Gap-based tiering with the min-3-per-tier merge rule."""
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


def _dynasty_tiers_for(rows, settings):
    """Tiers over the rostered pool; below-cutoff rows are lumped into the LAST
    tier (never 0 — the template renders tier badges and 'T0' is nonsense)."""
    ordered = sorted(rows, key=lambda r: r.dynasty_value, reverse=True)
    cutoff = min(settings.roster_cutoff, len(ordered))
    pool, bench = ordered[:cutoff], ordered[cutoff:]
    tiers = _compute_dynasty_tiers(pool)
    last = max(tiers.values()) if tiers else 1
    for r in bench:
        tiers[r.id] = last
    return tiers


def _dynasty_metadata(settings):
    """Dynasty $ and tiers computed on the FULL DD universe shaped by league
    settings, so they don't change when the displayed rows are filtered."""
    all_rows = sorted(dd_store.get_all(), key=lambda r: r.dynasty_value, reverse=True)
    return _compute_dynasty_dollars(all_rows, settings), _dynasty_tiers_for(all_rows, settings)


FIT_CATS = ("R", "HR", "RBI", "SB", "AVG", "OBP", "OPS", "SLG", "H", "BB",
            "SO", "TB", "NSB")
FIT_PCATS = ("W", "L", "K", "QS", "SV", "HLD", "SV_HLD", "ERA", "WHIP",
             "K_BB", "IP", "K_9", "BB_9")
FIT_QUERY_ALIASES = {
    "SV+HLD": "SV_HLD",
    "K/BB": "K_BB",
    "K/9": "K_9",
    "BB/9": "BB_9",
}
DYNASTY_DEFAULT_CATS = ("R", "HR", "RBI", "SB", "SO", "AVG", "OPS")
DYNASTY_DEFAULT_PCATS = ("ERA", "WHIP", "K", "SV", "HLD", "K_BB", "QS")
DD_DYNASTY_CATS = ("R", "HR", "RBI", "SB", "AVG", "OPS", "SO")
DD_DYNASTY_PCATS = ("L", "K", "QS", "SV_HLD", "ERA", "WHIP", "K_BB")
DYNASTY_CATEGORY_PRESETS = {
    "7x7": {
        "cats": list(DYNASTY_DEFAULT_CATS),
        "pcats": list(DYNASTY_DEFAULT_PCATS),
    },
    "DD 7x7": {
        "cats": list(DD_DYNASTY_CATS),
        "pcats": list(DD_DYNASTY_PCATS),
    },
    **CATEGORY_PRESETS,
}
_FIT_STAT_SPACE_FLIP = frozenset({"SO", "ERA", "WHIP", "L", "BB_9"})
_DYN_Z_CACHE = {"key": None, "map": {}}


def _dynasty_z_map():
    """Per-player z's for the dynasty board's Category Fit panel.

    The feed's z_scores field has never been produced (DD-producer gap), so
    matched projections are scored app-side across the fit panel's category
    union — same engine as the cards, so board and card numbers agree.
    The data-z-scores contract is STAT-SPACE (the fit JS sign-flips its
    FIT_INVERSE cats), while the engine emits value-oriented z's — flip
    those here. Cached per feed generation; ~0.1s to build."""
    if not dd_store.is_available:
        return {}
    key = dd_store.generated_at
    if _DYN_Z_CACHE.get("key") == key:
        return _DYN_Z_CACHE["map"]
    config = build_config(
        mode="categories", cats=list(FIT_CATS), pcats=list(FIT_PCATS),
        rules_str="", pt_params=None, split_rp=False, weights=None,
    )
    results = _merge_two_way_players(
        engine.value_players(_valuation_players(active_store=store), config))
    by_id = {}
    for res in results:
        by_id[res.player.id] = res
        base = res.player.metadata.get("base_id")
        if base:
            by_id.setdefault(base, res)
    match_index = build_outlook_match_index(store.get_all())
    z_map = {}
    for row in dd_store.get_all():
        matches = find_outlook_projections(row, match_index) or []
        res = next((by_id[m.id] for m in matches if m.id in by_id), None)
        if res is None:
            res = next(
                (by_id[m.metadata.get("base_id") or m.id] for m in matches
                 if (m.metadata.get("base_id") or m.id) in by_id), None)
        if res is None or not res.z_scores:
            continue
        z_map[row.id] = {
            cat: round(-z if cat in _FIT_STAT_SPACE_FLIP else z, 2)
            for cat, z in res.z_scores.items()
            if isinstance(z, (int, float))
        }
    _DYN_Z_CACHE["key"] = key
    _DYN_Z_CACHE["map"] = z_map
    return z_map


def _prospect_tiers():
    """Tiers for the Prospects board, computed on the prospect-ONLY universe (top 200
    by value). The combined-universe tiers from _dynasty_metadata() collapse to ~2
    badges across prospects because every prospect sits below the MLB cluster."""
    pros = sorted(dd_store.filter(pool="prospect"),
                  key=lambda r: r.dynasty_value, reverse=True)[:200]
    return _compute_dynasty_tiers(pros)


def _prospect_rows(position=None, search=None):
    """Return the dedicated Prospects board in DD's authoritative prospect order."""
    rows = dd_store.filter(pool="prospect", position=position, search=search)
    return sorted(
        rows,
        key=lambda row: (
            row.prospect_rank is None,
            row.prospect_rank if row.prospect_rank is not None else row.dynasty_rank,
            row.dynasty_rank,
        ),
    )[:200]


def _dynasty_category_state(args):
    """Canonical dynasty category params and whether custom scoring is active."""
    from web.category_registry import canonicalize_cats
    cats_present = bool(args.getlist("cats"))
    pcats_present = bool(args.getlist("pcats"))
    default_cats = canonicalize_cats(list(DYNASTY_DEFAULT_CATS))
    default_pcats = canonicalize_cats(list(DYNASTY_DEFAULT_PCATS))
    cats = canonicalize_cats(parse_list(args.getlist("cats"))) or default_cats
    pcats = canonicalize_cats(parse_list(args.getlist("pcats"))) or default_pcats
    active = (
        (cats_present or pcats_present)
        and (cats != default_cats or pcats != default_pcats)
    )
    return cats, pcats, active


def _dynasty_detail_category_state(args):
    """Use active Category Fit controls for detail cards when supplied."""
    from web.category_registry import canonicalize_cats
    fit_values = parse_list(args.getlist("fit_cats"))
    if not fit_values:
        cats, pcats, _ = _dynasty_category_state(args)
        return cats, pcats, False

    category_ids = [FIT_QUERY_ALIASES.get(cat, cat) for cat in fit_values]
    cats = canonicalize_cats([cat for cat in category_ids if cat in FIT_CATS])
    pcats = canonicalize_cats([cat for cat in category_ids if cat in FIT_PCATS])
    if not cats and not pcats:
        cats, pcats, _ = _dynasty_category_state(args)
        return cats, pcats, False
    return cats, pcats, True


def _dynasty_category_summary(cats, pcats):
    from web.category_registry import canonicalize_cats
    for name, preset in DYNASTY_CATEGORY_PRESETS.items():
        if (
            cats == canonicalize_cats(preset["cats"])
            and pcats == canonicalize_cats(preset["pcats"])
        ):
            if name == "6x6":
                return "6x6 (OBP, QS)"
            return name
    extras = [cat for cat in cats if cat not in DYNASTY_DEFAULT_CATS]
    extras += [cat for cat in pcats if cat not in DYNASTY_DEFAULT_PCATS]
    detail = ", ".join(extras or list(cats) + list(pcats))
    return f"Custom {len(cats)}x{len(pcats)} ({detail})"


@lru_cache(maxsize=16)
def _custom_dynasty_values(cats, pcats, teams, budget):
    """Feed-row id -> this-season auction dollars for a custom category tuple."""
    config = build_config(mode="categories", cats=list(cats), pcats=list(pcats))
    results = _merge_two_way_players(
        engine.value_players(_valuation_players(active_store=store), config)
    )
    dollars = _compute_dollar_values(results, num_teams=teams, budget=budget)
    result_by_projection_id = {}
    for result in results:
        result_by_projection_id[result.player.id] = result
        base_id = str(result.player.metadata.get("base_id") or "").strip()
        if base_id:
            result_by_projection_id[base_id] = result

    match_index = build_outlook_match_index(store.get_all())
    mapped = {}
    for row in dd_store.get_all():
        if row.is_prospect:
            continue
        for projection in match_index.find(row):
            result = result_by_projection_id.get(projection.id)
            if result is None:
                base_id = str(projection.metadata.get("base_id") or "").strip()
                result = result_by_projection_id.get(base_id)
            if result is not None:
                mapped[row.id] = dollars.get(result.player.id, 0.0)
                break
    return mapped


def _apply_prospect_board_context(ctx, args):
    """Apply dedicated prospect-board rows and metadata to a DD context."""
    ctx["dd_rows"] = _prospect_rows(
        position=ctx.get("position") or None,
        search=ctx.get("search") or None,
    )
    settings = parse_league_settings(args)
    ctx["dynasty_dollars"], _ = _dynasty_metadata(settings)
    ctx["tiers"] = _prospect_tiers()
    ctx["cutoff_rank"] = settings.prospect_cutoff
    ctx["mode"] = "prospects"
    ctx["horizon"] = "prospects"
    ctx["dyn_z_map"] = _dynasty_z_map()
    ctx["prospect_movers"] = (
        prospect_percentiles.top_movers(dd_store.filter(player_type="prospect"))
        if not ctx.get("search") and not ctx.get("position") and not ctx.get("pool")
        else []
    )

def _prospect_graphic_svg(rows, *, limit, position=None, search=None):
    """Render an Ahead of the Curve-style SVG share graphic."""
    width = 1080
    row_height = 58 if limit == 20 else 78
    header_height = 245
    footer_height = 92
    height = header_height + max(len(rows), 1) * row_height + footer_height
    scope = f"{position} " if position else ""
    title = f"Top {limit} {scope}Prospects"
    if search:
        title += f" | {search}"
    updated = dd_store.generated_at[:10] if dd_store.generated_at else "current feed"
    rank_kind = f"{position.upper()} RANK" if position else "LIST RANK"

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#031f1b"/>',
        '<stop offset="48%" stop-color="#064e3b"/>',
        '<stop offset="100%" stop-color="#111827"/>',
        "</linearGradient>",
        '<linearGradient id="card" x1="0" y1="0" x2="1" y2="0">',
        '<stop offset="0%" stop-color="#f8fffb"/>',
        '<stop offset="100%" stop-color="#ecfdf5"/>',
        "</linearGradient>",
        "</defs>",
        '<rect width="1080" height="100%" fill="url(#bg)"/>',
        '<circle cx="905" cy="96" r="225" fill="#34d399" opacity=".12"/>',
        '<circle cx="148" cy="972" r="305" fill="#10b981" opacity=".09"/>',
        '<path d="M710 88 C818 34 920 28 1040 62" fill="none" stroke="#a7f3d0" stroke-width="4" opacity=".35"/>',
        '<path d="M710 116 C828 58 940 52 1040 88" fill="none" stroke="#34d399" stroke-width="3" opacity=".35"/>',
        '<text x="64" y="62" fill="#d1fae5" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="23" font-weight="900" letter-spacing="5">VALUCAST</text>',
        '<text x="64" y="125" fill="#ffffff" font-family="Georgia,Times New Roman,serif" font-size="62" font-weight="900">Ahead of the Curve</text>',
        f'<text x="68" y="174" fill="#a7f3d0" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="32" font-weight="850">{escape(title)}</text>',
        f'<text x="68" y="207" fill="#d1fae5" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="17" font-weight="650">Filtered from the current prospect board | Updated {escape(updated)}</text>',
    ]

    if not rows:
        parts.extend([
            '<rect x="72" y="255" width="952" height="108" rx="22" fill="#000000" opacity=".20"/>',
            '<rect x="64" y="245" width="952" height="108" rx="22" fill="url(#card)"/>',
            '<text x="112" y="310" fill="#065f46" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="30" font-weight="900">No prospects found for this filter.</text>',
        ])
    else:
        for i, row in enumerate(rows):
            y = header_height + i * row_height
            card_h = row_height - 10
            rank = i + 1
            positions = ", ".join(row.positions) if row.positions else "N/A"
            team = row.team or "FA"
            age = row.age if row.age is not None else "N/A"
            detail = f"{positions} | {team} | Age {age}"
            name_size = 25 if limit == 10 else 21
            detail_size = 15 if limit == 10 else 12
            rank_box = card_h - 12
            parts.extend([
                f'<rect x="70" y="{y + 7}" width="952" height="{card_h}" rx="19" fill="#000000" opacity=".18"/>',
                f'<rect x="64" y="{y}" width="952" height="{card_h}" rx="19" fill="url(#card)"/>',
                f'<rect x="82" y="{y + 6}" width="{rank_box}" height="{rank_box}" rx="14" fill="#064e3b"/>',
                f'<text x="{82 + rank_box / 2}" y="{y + card_h / 2 + 9}" text-anchor="middle" fill="#d1fae5" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{18 if limit == 20 else 22}" font-weight="950">#{rank}</text>',
                f'<text x="154" y="{y + (31 if limit == 10 else 24)}" fill="#0f172a" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{name_size}" font-weight="900">{escape(row.name)}</text>',
                f'<text x="154" y="{y + (57 if limit == 10 else 41)}" fill="#64748b" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{detail_size}" font-weight="700">{escape(detail)}</text>',
                f'<text x="842" y="{y + card_h / 2 + 8}" fill="#065f46" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="{18 if limit == 20 else 21}" font-weight="900">{escape(rank_kind)}</text>',
            ])

    parts.extend([
        f'<text x="64" y="{height - 44}" fill="#d1fae5" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="16" font-weight="750">Generated from the Prospects tab filters. Rank numbers are local to this graphic.</text>',
        f'<text x="64" y="{height - 20}" fill="#86efac" font-family="Inter,Segoe UI,Arial,sans-serif" font-size="14" font-weight="700">valucast.app</text>',
        "</svg>",
    ])
    return "".join(parts)


def _prospect_graphic_png(rows, *, limit, position=None, search=None):
    """Render an Ahead of the Curve-style PNG for easy posting/saving."""
    from PIL import Image, ImageDraw, ImageFont

    def font(size, *, bold=False, serif=False):
        candidates = []
        if sys.platform.startswith("win"):
            root = Path(os.environ.get("WINDIR", "C:\\Windows")) / "Fonts"
            if serif:
                candidates += [root / ("georgiab.ttf" if bold else "georgia.ttf")]
            candidates += [root / ("segoeuib.ttf" if bold else "segoeui.ttf")]
            candidates += [root / ("arialbd.ttf" if bold else "arial.ttf")]
        if serif:
            candidates += [
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf"),
            ]
        candidates += [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
        ]
        for candidate in candidates:
            try:
                return ImageFont.truetype(str(candidate), size)
            except OSError:
                continue
        return ImageFont.load_default()

    def text_width(draw, text, fnt):
        box = draw.textbbox((0, 0), text, font=fnt)
        return box[2] - box[0]

    def fit_text(draw, text, fnt, max_width):
        if text_width(draw, text, fnt) <= max_width:
            return text
        trimmed = text
        while trimmed and text_width(draw, trimmed + "...", fnt) > max_width:
            trimmed = trimmed[:-1]
        return (trimmed.rstrip() + "...") if trimmed else "..."

    def split_name_lines(draw, name, fnt, max_width):
        if text_width(draw, name, fnt) <= max_width:
            return [name]
        parts = (name or "").split()
        if len(parts) > 1:
            return [
                fit_text(draw, parts[0], fnt, max_width),
                fit_text(draw, " ".join(parts[1:]), fnt, max_width),
            ]
        return [fit_text(draw, name or "Unknown", fnt, max_width)]

    def abbrev_name(name):
        parts = (name or "").split()
        if len(parts) > 1:
            return f"{parts[0][0]}. {' '.join(parts[1:])}"
        return name or "Unknown"

    def level_text(row):
        return row.level or ("MLB" if row.status == "mlb" else "PRO")

    def tag(row, *, age=False):
        pieces = [row.team or "FA", "/".join(row.positions[:2]) if row.positions else "UT"]
        lvl = level_text(row)
        if lvl:
            pieces.append(str(lvl))
        if age and row.age is not None:
            pieces.append(f"Age {row.age}")
        return " - ".join(pieces)

    def rank_label(fallback):
        return f"#{fallback}"

    def note_label(row):
        if row.age is not None:
            return f"AGE {row.age}"
        eta = getattr(row, "eta", None)
        if eta:
            return f"ETA {eta}"
        return "BOARD RANK"

    def spark_points(row, x, y, w, h):
        spark = build_spark(getattr(row, "value_history", None), width=w, height=h)
        if not spark:
            return None
        points = []
        for pair in spark["points"].split():
            px, py = pair.split(",")
            points.append((x + float(px), y + float(py)))
        return points, spark["direction"]

    width, height = 1080, 1350
    bg = (18, 19, 31)
    card = (35, 36, 64)
    card_2 = (32, 33, 58)
    border = (45, 47, 74)
    green = (52, 211, 153)
    blue = (110, 161, 255)
    text = (231, 233, 244)
    muted = (154, 161, 192)

    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        color = (
            round(18 + 6 * t),
            round(19 + 8 * t),
            round(31 + 20 * t),
        )
        draw.line([(0, y), (width, y)], fill=color)

    # Editorial arc from the /buys graphic.
    arc_box = (705, 46, 1040, 312)
    draw.arc(arc_box, start=196, end=286, fill=(35, 44, 73), width=3)

    scope = f"{position.upper()} " if position else ""
    rank_kind = f"{position.upper()} RANK" if position else "LIST RANK"
    title = f"Top {limit} {scope}Prospects"
    if search:
        title += f" | {search}"
    subtitle_date = _editorial_date(dd_store.generated_at)
    subtitle = f"The top {limit} {scope}prospects from the current board"
    if search:
        subtitle = f"{subtitle} | {search}"
    if subtitle_date:
        subtitle = f"{subtitle} - {subtitle_date}"

    draw.text((48, 39), "VALUCAST", fill=green, font=font(24, bold=True))
    draw.text((48, 82), "AHEAD OF THE CURVE", fill=text, font=font(61, bold=True))
    draw.text((48, 156), fit_text(draw, subtitle, font(23), 735), fill=muted, font=font(23))

    if not rows:
        draw.rounded_rectangle((48, 225, 1032, 360), radius=18, fill=card, outline=border, width=2)
        draw.text((76, 276), "No prospects found for this filter.", fill=text, font=font(30, bold=True))
    elif limit <= 10:
        # Compact variant for position top-10s: same voice, less empty space.
        hero = rows[0]
        leader = "POSITION LEADER" if position else "TOP PROSPECT"
        draw.rounded_rectangle((48, 226, 1032, 560), radius=18, fill=card, outline=green, width=2)
        draw.text((70, 252), f"{rank_label(1)} - {leader}", fill=green, font=font(24, bold=True))
        draw.ellipse((72, 315, 222, 465), fill=(28, 30, 54), outline=(54, 57, 92), width=2)
        initials = buy_score.graphic_initials(hero.name)
        mono = font(58, bold=True)
        box = draw.textbbox((0, 0), initials, font=mono)
        draw.text((147 - (box[2] - box[0]) / 2, 390 - (box[3] - box[1]) / 2), initials, fill=blue, font=mono)
        hero_name_font = font(43, bold=True)
        hero_name_lines = split_name_lines(draw, hero.name, hero_name_font, 410)
        for line_idx, line in enumerate(hero_name_lines):
            draw.text((250, 304 + line_idx * 50), line, fill=text, font=hero_name_font)
        draw.text((250, 370 + (len(hero_name_lines) - 1) * 44), fit_text(draw, tag(hero, age=True), font(22), 420), fill=muted, font=font(22))
        draw.text((70, 455), rank_label(1), fill=green, font=font(64, bold=True))
        draw.text((205, 508), rank_kind, fill=muted, font=font(18, bold=True))
        spark = spark_points(hero, 660, 455, 240, 64)
        if spark:
            draw.line(spark[0], fill=green if spark[1] == "up" else muted, width=3, joint="curve")
        draw.text((660, 525), "RECENT MOVEMENT", fill=muted, font=font(18, bold=True))

        grid_rows = rows[1:10]
        cols = 3
        cell_w, cell_h = 312, 166
        start_x, start_y = 48, 590
        for idx, row in enumerate(grid_rows):
            col, r = idx % cols, idx // cols
            x, y = start_x + col * (cell_w + 24), start_y + r * (cell_h + 18)
            draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=14, fill=card_2, outline=border, width=2)
            draw.text((x + 18, y + 16), rank_label(idx + 2), fill=blue, font=font(21, bold=True))
            draw.text((x + 18, y + 56), fit_text(draw, row.name, font(25, bold=True), 220), fill=text, font=font(25, bold=True))
            draw.text((x + 18, y + 93), fit_text(draw, tag(row), font(17), 220), fill=muted, font=font(17))
            draw.text((x + cell_w - 86, y + 20), note_label(row), fill=muted, font=font(14, bold=True))
    else:
        hero = rows[0]
        leader = "POSITION LEADER" if position else "TOP PROSPECT"
        draw.rounded_rectangle((48, 226, 418, 540), radius=18, fill=card, outline=green, width=2)
        draw.text((70, 252), f"{rank_label(1)} - {leader}", fill=green, font=font(22, bold=True))
        draw.ellipse((70, 314, 200, 444), fill=(28, 30, 54), outline=(54, 57, 92), width=2)
        initials = buy_score.graphic_initials(hero.name)
        mono = font(52, bold=True)
        box = draw.textbbox((0, 0), initials, font=mono)
        draw.text((135 - (box[2] - box[0]) / 2, 379 - (box[3] - box[1]) / 2), initials, fill=blue, font=mono)
        hero_name_font = font(31, bold=True)
        hero_name_lines = split_name_lines(draw, hero.name, hero_name_font, 170)
        for line_idx, line in enumerate(hero_name_lines):
            draw.text((220, 318 + line_idx * 37), line, fill=text, font=hero_name_font)
        draw.text((220, 394 + (len(hero_name_lines) - 1) * 26), fit_text(draw, tag(hero), font(18), 165), fill=muted, font=font(18))
        draw.text((70, 455), rank_label(1), fill=green, font=font(58, bold=True))
        draw.text((205, 503), rank_kind, fill=muted, font=font(17, bold=True))

        supports = rows[1:5]
        for idx, row in enumerate(supports):
            x = 435 + (idx % 2) * 307
            y = 226 + (idx // 2) * 164
            draw.rounded_rectangle((x, y, x + 291, y + 149), radius=16, fill=card, outline=border, width=2)
            draw.ellipse((x + 16, y + 18, x + 88, y + 90), fill=(28, 30, 54), outline=(54, 57, 92), width=1)
            initials = buy_score.graphic_initials(row.name)
            mono = font(28, bold=True)
            box = draw.textbbox((0, 0), initials, font=mono)
            draw.text((x + 52 - (box[2] - box[0]) / 2, y + 54 - (box[3] - box[1]) / 2), initials, fill=blue, font=mono)
            draw.text((x + 104, y + 18), rank_label(idx + 2), fill=blue, font=font(19, bold=True))
            support_name_font = font(21, bold=True)
            draw.text((x + 104, y + 48), fit_text(draw, row.name, support_name_font, 172), fill=text, font=support_name_font)
            draw.text((x + 104, y + 78), fit_text(draw, tag(row), font(15), 160), fill=muted, font=font(15))
            draw.line((x + 16, y + 104, x + 275, y + 104), fill=border, width=1)
            draw.text((x + 16, y + 118), note_label(row), fill=muted, font=font(14, bold=True))

        rest = rows[5:20]
        cols = 3
        cell_w, cell_h = 328, 122
        start_x, start_y = 48, 562
        for idx, row in enumerate(rest):
            col, r = idx % cols, idx // cols
            x, y = start_x + col * cell_w, start_y + r * cell_h
            fill = card_2 if r % 2 == 0 else bg
            draw.rectangle((x, y, x + cell_w, y + cell_h), fill=fill)
            if col:
                draw.line((x, y, x, y + cell_h), fill=border, width=1)
            if r:
                draw.line((x, y, x + cell_w, y), fill=border, width=1)
            draw.text((x + 14, y + 14), rank_label(idx + 6), fill=blue, font=font(19, bold=True))
            draw.text((x + cell_w - 86, y + 16), note_label(row), fill=muted, font=font(14, bold=True))
            draw.text((x + 14, y + 50), fit_text(draw, abbrev_name(row.name), font(22, bold=True), 250), fill=text, font=font(22, bold=True))
            draw.text((x + 14, y + 84), fit_text(draw, tag(row), font(18), 250), fill=muted, font=font(18))

    foot_y = height - 68
    draw.rounded_rectangle((48, foot_y, 1032, foot_y + 46), radius=8, fill=card)
    draw.text((60, foot_y + 10), "valucast.app", fill=green, font=font(22, bold=True))
    draw.text((505, foot_y + 14), "rank numbers are local to this graphic - filtered from the Prospects tab", fill=muted, font=font(16))
    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _build_dynasty_context(args):
    """Build template context for DD Dynasty mode."""
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")
    settings = parse_league_settings(args)
    cats, pcats, custom_cats_active = _dynasty_category_state(args)
    rank_by = args.get("rank_by", "dynasty")
    if rank_by not in ("dynasty", "now") or not custom_cats_active:
        rank_by = "dynasty"
    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    now_dollars = (
        _custom_dynasty_values(tuple(cats), tuple(pcats), settings.teams, settings.budget)
        if custom_cats_active else {}
    )
    if rank_by == "now":
        rows = sorted(
            rows,
            key=lambda row: (
                row.id not in now_dollars,
                -now_dollars.get(row.id, 0.0),
                row.dynasty_rank,
            ),
        )
    rows = rows[:200]
    dynasty_dollars, tiers = _dynasty_metadata(settings)
    summary = f"{settings.summary()} · {_dynasty_category_summary(cats, pcats)}"
    return {
        "mode": "dd_dynasty",
        "pool": pool,
        "position": position,
        "search": search,
        "dd_rows": rows,
        "dyn_z_map": _dynasty_z_map(),
        "dynasty_dollars": dynasty_dollars,
        "now_dollars": now_dollars,
        "custom_cats_active": custom_cats_active,
        "rank_by": rank_by,
        "cats": cats,
        "pcats": pcats,
        "hitting_categories": HITTING_CATEGORIES,
        "pitching_categories": PITCHING_CATEGORIES,
        "category_presets": DYNASTY_CATEGORY_PRESETS,
        "tiers": tiers,
        "dd_available": dd_store.is_available,
        "dd_generated_at": dd_store.generated_at,
        "dd_schema_version": dd_store.schema_version,
        "as_of": store.as_of,
        "horizon": "dynasty",
        "league_settings": settings,
        "config_summary": summary,
        "cutoff_rank": settings.roster_cutoff,
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
        if set(cats) == set(preset["cats"]) and set(pcats) == set(preset["pcats"]):
            label = "Standard 5x5" if name == "5x5" else "6x6 (OBP/QS)" if name == "6x6" else name
            suffix = " \u00b7 SP/RP split" if split_rp else ""
            return f"{label} \u00b7 12 teams \u00b7 $200 budget{suffix}"
    cat_count = len(cats) + len(pcats)
    suffix = " \u00b7 SP/RP split" if split_rp else ""
    return f"Custom {cat_count} categories \u00b7 12 teams \u00b7 $200 budget{suffix}"


def _horizon_of(mode: str) -> str:
    """Map a mode to its horizon tab: redraft (categories/roto/points), dynasty, prospects."""
    if mode == "dd_dynasty":
        return "dynasty"
    if mode == "prospects":
        return "prospects"
    return "redraft"


def _build_context(args):
    """Parse request args and build template context."""
    mode = args.get("mode", "categories")
    from web.category_registry import canonicalize_cats
    cats = canonicalize_cats(parse_list(args.getlist("cats"))) or list(DEFAULT_CATS)
    pcats = canonicalize_cats(parse_list(args.getlist("pcats"))) or list(DEFAULT_PCATS)
    pool = args.get("pool", "")
    position = args.get("position", "")
    search = args.get("search", "")
    rules_str = args.get("rules", "")
    split_rp = args.get("split_rp", "") == "on"
    display = args.get("display", "projections")
    if display not in ("projections", "values"):
        display = "projections"

    # Resolve the projection source (default Steamer). Unknown/unavailable -> SourceError
    # (caught by the errorhandler -> 400) before any valuation runs.
    active = _active_store(args.get("source", ""))

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
                w = float(args[key])
            except ValueError:
                continue
            if math.isfinite(w):  # inf/nan parse as floats and would poison the board
                weights[key[2:]] = w

    # Build config and run engine
    config = build_config(
        mode=mode, cats=cats, pcats=pcats,
        rules_str=rules_str, pt_params=pt_params if pt_params else None,
        split_rp=split_rp, weights=weights if weights else None,
    )
    # Value the canonical universe (search/filter-independent) so display metadata is
    # stable. A search may surface sub-threshold players for DISPLAY only; it must not
    # change the pool the metadata is computed on.
    all_results = _merge_two_way_players(
        engine.value_players(_valuation_players(active_store=active), config)
    )
    all_results.sort(key=lambda r: r.total_value, reverse=True)

    # Metadata pool = the fixed top-200-by-value of the full universe (the same set the
    # default unfiltered board shows). Computing $/ranks/tiers here keeps the default
    # board byte-identical AND makes filtered views show the SAME numbers.
    metadata_pool = all_results[:200]

    # Display set: filter the full universe, then surface sub-threshold search matches.
    results = all_results
    if pool:
        if pool == "pitcher":
            results = [
                r for r in results
                if r.player.pool in (PlayerPool.PITCHER, PlayerPool.STARTER, PlayerPool.RELIEVER)
            ]
        else:
            try:
                pool_value = PlayerPool(pool)
            except ValueError:
                pool_value = None
            if pool_value is not None:
                results = [r for r in results if r.player.pool == pool_value]
    if position:
        results = [r for r in results if position in r.player.positions]
    if search:
        query = search.lower()
        results = [r for r in results if query in r.player.name.lower()]
        if not results:
            # Sub-threshold name match: value it on demand for display (no metadata).
            search_keep = {p.id for p in active.get_all() if query in p.name.lower()}
            if search_keep:
                extra = _merge_two_way_players(
                    engine.value_players(
                        _valuation_players(search_keep, active_store=active), config
                    )
                )
                results = [r for r in extra if query in r.player.name.lower()]

    # Limit to top 200 for display
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
    position_ranks = _compute_position_ranks(metadata_pool)
    dollar_values = _compute_dollar_values(metadata_pool)
    tiers = _compute_tiers(metadata_pool)

    # Overall rank from the canonical universe (filter-independent). Players not in the
    # canonical universe (sub-threshold search matches) are below the valuation floor:
    # they show a projection but no rank/value/$/tier.
    overall_ranks = {r.player.id: i for i, r in enumerate(all_results, 1)}
    canonical_ids = {r.player.id for r in all_results}

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
        "player_count": active.player_count,
        "config": config,
        "position_ranks": position_ranks,
        "dollar_values": dollar_values,
        "tiers": tiers,
        "overall_ranks": overall_ranks,
        "canonical_ids": canonical_ids,
        "config_summary": _config_summary(mode, cats, pcats, split_rp),
        "as_of": active.as_of,
        "source": args.get("source", "") or "steamer",
        "display": display,
        "horizon": _horizon_of(mode),
        "active_store": active,
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
            _apply_prospect_board_context(ctx, request.args)
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
                _apply_prospect_board_context(ctx, request.args)
        html = render_template("partials/rankings_response.html", **ctx)
        response = make_response(html)
        params = {"mode": mode}
        if ctx.get("pool") and mode != "prospects":
            params["pool"] = ctx["pool"]
        if ctx.get("position"):
            params["position"] = ctx["position"]
        if ctx.get("search"):
            params["search"] = ctx["search"]
        from web.league_settings import _BOUNDS
        for name in _BOUNDS:
            value = request.args.get(name)
            if value:
                params[name] = value
        for name in ("cats", "pcats", "rank_by"):
            values = request.args.getlist(name)
            if values:
                params[name] = ",".join(parse_list(values)) if name != "rank_by" else values[0]
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
    extra = []
    if ctx.get("source") and ctx["source"] != "steamer":
        extra.append(f"source={ctx['source']}")
    if ctx.get("display") and ctx["display"] != "projections":
        extra.append(f"display={ctx['display']}")
    all_params = "&".join([p for p in [url_params] + extra if p])
    push_url = f"/?{all_params}" if all_params else "/"
    response.headers["HX-Replace-Url"] = push_url
    return response


# /league-import holds a worker for an outbound fetch (up to ~5s) and we run
# only 2 gunicorn workers — a cheap per-IP throttle keeps one client from
# pinning the deploy. In-memory per worker, so the effective ceiling is 2x.
_IMPORT_HITS: dict[str, list[float]] = {}
_IMPORT_RATE_MAX = 5
_IMPORT_RATE_WINDOW = 60.0


def _import_rate_limited(ip: str) -> bool:
    now = time.monotonic()
    if len(_IMPORT_HITS) > 1000:
        stale = [k for k, v in _IMPORT_HITS.items()
                 if not v or now - v[-1] > _IMPORT_RATE_WINDOW]
        for k in stale:
            _IMPORT_HITS.pop(k, None)
    hits = [t for t in _IMPORT_HITS.get(ip, []) if now - t < _IMPORT_RATE_WINDOW]
    limited = len(hits) >= _IMPORT_RATE_MAX
    if not limited:
        hits.append(now)
    _IMPORT_HITS[ip] = hits
    return limited


@app.route("/league-import")
def league_import():
    """Fill the dynasty setup knobs from a league URL. Self-contained seam —
    a future paid gate wraps exactly this route. Always returns the panel
    fragment (200): failures become an inline notice, knobs untouched."""
    current = parse_league_settings(request.args)
    cats, pcats, _ = _dynasty_category_state(request.args)
    setup_context = {
        "cats": cats,
        "pcats": pcats,
        "hitting_categories": HITTING_CATEGORIES,
        "pitching_categories": PITCHING_CATEGORIES,
        "category_presets": DYNASTY_CATEGORY_PRESETS,
    }
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr or "?")
          .split(",")[0].strip())
    if not app.config.get("TESTING") and _import_rate_limited(ip):
        return render_template(
            "partials/setup_dynasty.html",
            league_settings=current, import_refresh=False,
            import_notice="Too many import attempts — wait a minute and try again.",
            **setup_context,
        )
    url = (request.args.get("league_url") or "").strip()
    try:
        partial, notice = import_league(url)
        merged = {
            "teams": partial.get("teams", current.teams),
            "budget": partial.get("budget", current.budget),
            "roster": partial.get("roster", current.roster),
            "pslots": partial.get("pslots", current.pslots),
        }
        settings = parse_league_settings(merged)  # clamp imported values too
        refresh = True
    except ImportError_ as exc:
        settings, notice, refresh = current, str(exc), False
    return render_template(
        "partials/setup_dynasty.html",
        league_settings=settings, import_notice=notice, import_refresh=refresh,
        **setup_context,
    )


@app.route("/methodology")
def methodology():
    """Public 'How ValuCast works' page. Renders validation numbers from the committed
    scorecard artifact (drift-locked page<->artifact) and model constants from the params
    modules (drift-locked page<->params)."""
    import json as _json
    from projections.models.marcel_params import MarcelParams
    from projections.models.pitcher_params import PitcherMarcelParams
    scorecard = _json.loads(
        (Path(__file__).parent / "data" / "validation" / "methodology_scorecard.json")
        .read_text(encoding="utf-8")
    )
    hp, pp = MarcelParams(), PitcherMarcelParams()

    # Worked example computed from the REAL params (drift-proof): an age-29 hitter
    # (peak, age factor ~1.0) with no Statcast movement, HR component over 3 seasons.
    ex = [(30, 600), (26, 580), (20, 520)]          # (HR, PA), newest first
    w = hp.season_weights
    w_ev = sum(wi * e for wi, (e, _) in zip(w, ex))
    w_pa = sum(wi * pa for wi, (_, pa) in zip(w, ex))
    league_hr = 0.033
    reg = (w_ev + league_hr * hp.n_reg) / (w_pa + hp.n_reg)
    proj_pa = hp.pa_w1 * ex[0][1] + hp.pa_w2 * ex[1][1] + hp.pa_base
    worked = {
        "ex": ex, "weights": [int(x) for x in w],
        "w_ev": int(w_ev), "w_pa": int(w_pa),
        "rate": round(w_ev / w_pa, 3), "league": league_hr, "n_reg": int(hp.n_reg),
        "reg": round(reg, 4),
        "pa_w1": hp.pa_w1, "pa_w2": hp.pa_w2, "pa_base": int(hp.pa_base),
        "proj_pa": int(round(proj_pa)), "proj_hr": round(reg * proj_pa, 1),
    }
    return render_template(
        "methodology.html", methodology_page=True, scorecard=scorecard,
        hit_weights=",".join(str(w) for w in hp.season_weights),
        hit_n_reg=int(hp.n_reg), pit_n_reg=int(pp.n_reg), worked=worked,
        pct=lambda r: round((1 - r) * 100, 1),
    )


def _value_map_players(rows):
    """Slim, committed-feed-only payload for the value map."""
    payload = []
    pitcher_positions = {"SP", "RP", "P"}
    for row in rows:
        if row.age is None or row.dynasty_value is None:
            continue
        positions = list(row.positions or ())
        primary = positions[0] if positions else "DH"
        if row.is_prospect:
            group = "prospect"
        elif "SP" in positions:
            group = "sp"
        elif positions and set(positions) <= pitcher_positions:
            group = "rp"
        else:
            group = "hitter"
        payload.append({
            "id": row.id,
            "name": row.name,
            "age": row.age,
            "value": row.dynasty_value,
            "position": primary,
            "group": group,
            "player_type": row.player_type,
            "prospect_rank": row.prospect_rank,
        })
    return payload


@app.route("/map")
def value_map():
    players = _value_map_players(dd_store.get_all()) if dd_store.is_available else []
    return render_template(
        "value_map.html",
        players=players,
        player_count=len(players),
        dd_generated_at=dd_store.generated_at,
        dd_available=dd_store.is_available,
        map_page=True,
        mode="dd_dynasty",
        as_of=store.as_of,
    )


@app.route("/buys")
def buys():
    """Top-40 prospect buys + the shareable 1080x1350 graphic node."""
    n = buy_score.clamp_n(request.args.get("n", buy_score.BOARD_SIZE))
    buy_store, buy_data_source = _select_buy_source(dd_store, valucast_buy_store)
    if buy_data_source == "valucast_buys" and buy_store.is_available:
        graphic_rows = buy_score.build_valucast_board(buy_store.get_all())
        # n drives the interactive list only; the 2x20 graphic always takes 40
        list_rows = (graphic_rows[:n] if n <= buy_score.BOARD_SIZE
                     else buy_score.build_valucast_board(buy_store.get_all(), n=n))
        data_generated_at = buy_store.generated_at
        data_available = True
    elif dd_store.is_available:
        graphic_rows = buy_score.build_board(dd_store.get_all())
        # n drives the interactive list only; the 2x20 graphic always takes 40
        list_rows = (graphic_rows[:n] if n <= buy_score.BOARD_SIZE
                     else buy_score.build_board(dd_store.get_all(), n=n))
        data_generated_at = dd_store.generated_at
        data_available = True
    else:
        graphic_rows, list_rows = [], []
        data_generated_at = None
        data_available = False
    for row in graphic_rows:
        row["spark"] = build_spark(row["value_history"])
    for row in list_rows:
        if "spark" not in row:
            row["spark"] = build_spark(row["value_history"])
    return render_template(
        "buys.html",
        list_rows=list_rows,
        graphic_rows=graphic_rows,
        n=n,
        dd_available=data_available,
        dd_generated_at=data_generated_at,
        buy_data_source=buy_data_source,
        as_of=store.as_of,
    )


@app.route("/health/ready")
def health_ready():
    """Readiness probe (Render healthCheckPath). 200 only when all three projection
    stores are available, else 503 — so a deploy missing any data store is never
    promoted over the prior healthy one. Also reports the deployed git revision."""
    def _store_ok(source):
        try:
            return CATALOG.store_for(source).player_count > 0
        except Exception:  # noqa: BLE001
            return False

    stores = {
        "steamer": _store_ok("steamer"),
        "valucast": _store_ok("valucast"),
        "dd": legacy_dd_store.is_available,
    }
    if os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT") == "1":
        stores["public_snapshot_ready"] = (
            public_snapshot_store.is_available
            and public_snapshot_store.ready_for_live_consumers
        )
    if os.environ.get("VALUCAST_USE_VALUCAST_BUYS") == "1":
        stores["valucast_buys_ready"] = (
            valucast_buy_store.is_available
            and valucast_buy_store.ready_for_live_consumers
            and dynasty_data_source == "valucast_public_snapshot"
        )
    ready = all(stores.values())
    body = {
        "ready": ready,
        "stores": stores,
        "public_snapshot": {
            "available": public_snapshot_store.is_available,
            "ready_for_live_consumers": public_snapshot_store.ready_for_live_consumers,
            "active": dynasty_data_source == "valucast_public_snapshot",
        },
        "valucast_buys": {
            "available": valucast_buy_store.is_available,
            "ready_for_live_consumers": valucast_buy_store.ready_for_live_consumers,
        },
        "dynasty_data_source": dynasty_data_source,
        "commit": os.environ.get("RENDER_GIT_COMMIT", ""),
    }
    return jsonify(body), (200 if ready else 503)


@app.route("/player/<player_id>")
def player_detail(player_id):
    mode = request.args.get("mode", "categories")

    if request.headers.get("HX-Request") != "true":
        player_name = None
        if mode in ("dd_dynasty", "prospects") and dd_store.is_available:
            row = dd_store.get_by_id(player_id)
            player_name = row.name if row else None
        else:
            try:
                active = _active_store(request.args.get("source", ""))
            except SourceError:
                active = store
            projection = active.get_by_id(player_id)
            player_name = projection.name if projection else None
        if player_name:
            return redirect("/?" + urlencode({"mode": mode, "search": player_name}))

    if mode in ("dd_dynasty", "prospects") and dd_store.is_available:
        dd_row = dd_store.get_by_id(player_id)
        if dd_row is None:
            return "<div class='error'>Player not found</div>", 404

        mlb_stats = None
        mlb_stats_actual = None
        mlb_stats_ros = None
        mlb_stats_split = None
        mlb_stats_actual_split = None
        mlb_stats_ros_split = None
        extras = {"statcast_groups": [], "statcast_asof": None, "player_links": []}
        match_index = build_outlook_match_index(store.get_all())
        if not dd_row.is_prospect:
            outlook = find_season_outlook(dd_row, match_index)
            if outlook:
                mlb_stats, mlb_stats_actual, mlb_stats_ros = outlook
            split = find_season_outlook_split(dd_row, match_index)
            if split:
                mlb_stats_split, mlb_stats_actual_split, mlb_stats_ros_split = split
            # Identity (mlbam/fangraphs ids) comes from the safely-matched
            # projection row — the feed itself carries no ids today.
            matches = find_outlook_projections(dd_row, match_index)
            if matches:
                extras = _card_extras(dd_row.name, matches[0].pool, matches[0].metadata)

        prospect_context = {}
        if dd_row.is_prospect:
            matches = find_outlook_projections(dd_row, match_index)
            if matches:
                extras = _card_extras(dd_row.name, matches[0].pool, matches[0].metadata)
            stat_percentiles = prospect_percentiles.card_percentiles(prospect_pool, dd_row)
            stat_captions = {
                m: c for m in prospect_percentiles.CAPTION_METRICS
                if (c := prospect_percentiles.caption_for(m, stat_percentiles.get(m))) is not None
            }
            identity = prospect_percentiles.identity_line(dd_row, stat_percentiles)
            prospect_context = {
                "stat_percentiles": stat_percentiles,
                "stat_captions": stat_captions,
                "identity": identity,
            }

        # Same-engine category z's as the active dynasty category configuration.
        # The feed's z_scores field has never been produced (DD-producer gap),
        # so the card scores the safely matched projection app-side.
        dyn_result = None
        dyn_categories = []
        dyn_category_summary = None
        if matches:
            dyn_cats, dyn_pcats, fit_active = _dynasty_detail_category_state(
                request.args
            )
            # build_config treats an empty side as "use default"; use one
            # harmless category instead, then filter it from the detail table.
            config = build_config(
                mode="categories", cats=dyn_cats or ["R"],
                pcats=dyn_pcats or ["K"], rules_str="",
                pt_params=None, split_rp=False, weights=None,
            )
            detail_results = _merge_two_way_players(
                engine.value_players(
                    _valuation_players(active_store=store), config)
            )
            ids = {m.id for m in matches}
            ids |= {m.metadata.get("base_id") or m.id for m in matches}
            dyn_result = next(
                (r for r in detail_results if r.player.id in ids), None)
            dyn_categories = list(getattr(config, "categories", []) or [])
            if fit_active:
                requested = set(dyn_cats + dyn_pcats)
                dyn_categories = [
                    category for category in dyn_categories
                    if category.id in requested
                ]
            dyn_category_summary = _dynasty_category_summary(dyn_cats, dyn_pcats)

        return render_template(
            "partials/player_detail_dynasty.html",
            row=dd_row,
            dyn_result=dyn_result,
            dyn_categories=dyn_categories,
            dyn_category_summary=dyn_category_summary,
            spark=build_spark(dd_row.value_history),
            mlb_stats=mlb_stats,
            mlb_stats_actual=mlb_stats_actual,
            mlb_stats_ros=mlb_stats_ros,
            mlb_stats_split=mlb_stats_split,
            mlb_stats_actual_split=mlb_stats_actual_split,
            mlb_stats_ros_split=mlb_stats_ros_split,
            **prospect_context,
            **extras,
        )

    # _build_context resolves + guards the source first (SourceError -> 400), then we
    # look the player up in the ACTIVE store so detail honors ?source=.
    ctx = _build_context(request.args)
    active = ctx["active_store"]
    player_proj = active.get_by_id(player_id)
    if not player_proj:
        return "<div class='error'>Player not found</div>", 404

    config = ctx["config"]
    # Value the canonical universe (no on-demand force-keep) so the detail value matches
    # the board exactly. A below-floor player isn't in the canonical set -> result None,
    # and the template shows the projection without a (non-canonical) value.
    detail_results = _merge_two_way_players(
        engine.value_players(_valuation_players(active_store=active), config)
    )
    result = next((r for r in detail_results if r.player.id == player_id), None)
    base_id = player_proj.metadata.get("base_id") or player_proj.id
    siblings = [
        projection for projection in active.get_all()
        if (projection.metadata.get("base_id") or projection.id) == base_id
    ]
    projection_split = split_outlook(siblings)[0]

    return render_template(
        "partials/player_detail.html",
        player=player_proj,
        result=result,
        active_categories=ctx["active_categories"],
        projection_split=projection_split,
        **_card_extras(player_proj.name, player_proj.pool, player_proj.metadata),
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
    # Use canonical results so compare matches the board (not an on-demand mini-pool).
    all_results = _merge_two_way_players(
        engine.value_players(
            _valuation_players(active_store=ctx["active_store"]), config)
    )

    r1 = next((r for r in all_results if r.player.id == p1_id), None)
    r2 = next((r for r in all_results if r.player.id == p2_id), None)

    return render_template(
        "partials/compare_modal.html",
        r1=r1,
        r2=r2,
        active_categories=ctx["active_categories"],
    )


def _csv_safe(value):
    """Excel executes cells starting with = + - @ (or tab/CR) as formulas;
    names come from scraped feeds, so prefix rather than trust."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", chr(9), chr(13)):
        return chr(39) + value
    return value

@app.route("/export")
def export_csv():
    mode = request.args.get("mode", "categories")

    if mode in ("dd_dynasty", "prospects") and dd_store.is_available:
        ctx = _build_dynasty_context(request.args)
        if mode == "prospects":
            ctx["dd_rows"] = _prospect_rows(
                position=ctx.get("position") or None,
                search=ctx.get("search") or None,
            )
            ctx["dynasty_dollars"], _ = _dynasty_metadata(parse_league_settings(request.args))
            ctx["tiers"] = _prospect_tiers()
        rows = ctx["dd_rows"]
        dynasty_dollars = ctx["dynasty_dollars"]
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Overall Dynasty Rank", "Player", "Type", "Positions", "Team",
                         "Age", "Dynasty Value", "Dynasty $", "Confidence Level",
                         "Value Low", "Value High", "Prospect Rank", "Level", "ETA"])
        for row in rows:
            confidence = row.confidence or {}
            value_range = confidence.get("range") or {}
            writer.writerow([
                row.dynasty_rank, _csv_safe(row.name), row.player_type.upper(),
                ", ".join(row.positions) or "", row.team, row.age or "",
                row.dynasty_value, dynasty_dollars.get(row.id, 0),
                confidence.get("level", ""),
                value_range.get("low", ""),
                value_range.get("high", ""),
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
    overall_ranks = ctx["overall_ranks"]
    canonical_ids = ctx["canonical_ids"]
    export_display = ctx.get("display", "projections")

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row — value view labels columns "<Category> value".
    header = ["Rank", "Player", "Positions", "Team", "Position Rank", "Tier", "Auction $", "Value"]
    suffix = " value" if export_display == "values" else ""
    for col in display_columns:
        header.append(col["label"] + suffix)
    writer.writerow(header)

    # Data rows
    pitcher_pos = {"SP", "RP", "P"}
    for result in results:
        below_floor = result.player.id not in canonical_ids
        # For hitter-pool results, strip pitcher positions from display
        if result.player.pool == PlayerPool.HITTER:
            display_positions = [p for p in result.player.positions if p not in pitcher_pos]
        else:
            display_positions = list(result.player.positions)
        row = [
            overall_ranks.get(result.player.id, ""),
            _csv_safe(result.player.name),
            ", ".join(display_positions) or "DH",
            result.player.metadata.get("team", ""),
            position_ranks.get(result.player.id, ""),
            tiers.get(result.player.id, ""),
            dollar_values.get(result.player.id, 0),
            "" if below_floor else round(result.total_value, 2),
        ]
        for col in display_columns:
            if col.get("split"):
                sp_raw = result.raw_values.get(col["sp_id"])
                rp_raw = result.raw_values.get(col["rp_id"])
                raw = sp_raw if sp_raw is not None else rp_raw
                val = result.category_values.get(col["sp_id"], 0) + result.category_values.get(col["rp_id"], 0)
            else:
                raw = result.raw_values.get(col["id"])
                val = result.category_values.get(col["id"], 0)
            if raw is None:
                row.append("")
            elif export_display == "values":
                row.append(round(val, 1))
            else:
                row.append(format_stat(raw, col["id"]))
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=valucast-rankings.csv"
    return response


def _prospect_graphic_payload():
    limit = 20 if request.args.get("limit") == "20" else 10
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    rows = _prospect_rows(position=position, search=search)[:limit]
    svg = _prospect_graphic_svg(rows, limit=limit, position=position, search=search)
    scope = (position or "all").lower()
    filename = f"valucast-top-{limit}-{scope}-prospects.svg"
    return svg, filename, limit, position, search


@app.route("/prospects/share-card")
def prospects_share_card():
    if not dd_store.is_available:
        return "<!doctype html><title>Prospect graphic unavailable</title>", 503

    limit = 20 if request.args.get("limit") == "20" else 10
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    params = {"limit": limit}
    if position:
        params["position"] = position
    if search:
        params["search"] = search
    png_url = "/prospects/share-card.png?" + urlencode(params)
    scope = (position or "all").lower()
    filename = f"valucast-top-{limit}-{scope}-prospects.png"
    title = f"Top {limit} {position + ' ' if position else ''}Prospects"
    if search:
        title = f"{title} | {search}"
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Ahead of the Curve | {escape(filename)}</title>
  <style>
    body {{ margin: 0; background: #020617; color: #d1fae5; font-family: Inter, Segoe UI, Arial, sans-serif; }}
    main {{ min-height: 100vh; display: grid; place-items: center; gap: 16px; padding: 24px; }}
    .meta {{ width: min(1080px, 100%); }}
    h1 {{ margin: 0 0 4px; color: #f8fafc; font-size: 22px; }}
    p {{ margin: 0; color: #9ca3c0; font-weight: 700; }}
    .card-wrap {{ width: min(1080px, 100%); }}
    img {{ width: 100%; height: auto; display: block; border-radius: 24px; box-shadow: 0 24px 80px rgba(0,0,0,.45); }}
    .actions {{ width: min(1080px, 100%); display: flex; justify-content: flex-end; }}
    .download {{ color: #052e2b; background: #a7f3d0; border-radius: 999px; padding: 10px 16px; text-decoration: none; font-weight: 900; }}
  </style>
</head>
<body>
  <main>
    <div class="meta">
      <h1>Ahead of the Curve</h1>
      <p>{escape(title)}</p>
    </div>
    <div class="card-wrap"><img src="{escape(png_url)}" alt="Ahead of the Curve - {escape(title)}"></div>
    <div class="actions"><a class="download" href="{escape(png_url)}" download="{escape(filename)}">Download PNG</a></div>
  </main>
</body>
</html>"""
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/prospects/share-card.png")
def prospects_share_card_png():
    if not dd_store.is_available:
        return "", 503

    limit = 20 if request.args.get("limit") == "20" else 10
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    rows = _prospect_rows(position=position, search=search)[:limit]
    png = _prospect_graphic_png(rows, limit=limit, position=position, search=search)
    scope = (position or "all").lower()
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-top-{limit}-{scope}-prospects.png"'
    )
    return response


@app.route("/prospects/share-card.svg")
@app.route("/prospects/graphic")
def prospects_graphic():
    if not dd_store.is_available:
        return "<svg xmlns='http://www.w3.org/2000/svg'></svg>", 503

    svg, filename, *_ = _prospect_graphic_payload()
    response = make_response(svg)
    response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
    response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="0.0.0.0", port=port)
