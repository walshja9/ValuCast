from __future__ import annotations

from collections import Counter
import csv
import io
import json
import math
import os
import sys
import time
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote, urlencode

from flask import Flask, abort, render_template, request, make_response, jsonify, redirect

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
from web.fg_fv_store import FgFvStore
from web.player_links import build_player_links
from web.value_spark import build_spark
from web import buy_score
from web import prospect_percentiles
from web.share_pages import build_share_preview_html
from prospects.universe import MINOR_TEAM_MLB_AFFILIATES

app = Flask(__name__)
PUBLIC_BASE_URL = os.environ.get("VALUCAST_PUBLIC_URL", "https://valucast.app").rstrip("/")
# Deliberate public hold of the buys/AOTC surface until release; flip to False (and redeploy) to re-enable.
AHEAD_OF_THE_CURVE_HOLD = True


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.context_processor
def _aotc_hold_context():
    return {"aotc_hold": AHEAD_OF_THE_CURVE_HOLD}


def _public_url(path):
    """Absolute public URL for social cards and share wrappers."""
    if not path:
        return PUBLIC_BASE_URL
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return PUBLIC_BASE_URL + path


# Per-category projected-stat formatting for the rankings columns.
_RATE_3DP = {"AVG", "OBP", "SLG", "OPS"}            # .280
_RATE_2DP = {"ERA", "WHIP", "K_BB", "K_9", "BB_9"}  # 3.24
_DECIMAL_1 = {"IP"}                                  # 182.1

_MONTH_NAMES = (
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
)
_BRAND_MARK_PATH = Path(__file__).parent / "static" / "brand" / "valucast-mark-192.png"


def _paste_brand_mark(img, x, y, size=58):
    """Paste the ValuCast mark into a PIL graphic if the static asset exists."""
    if not _BRAND_MARK_PATH.exists():
        return
    from PIL import Image, ImageDraw

    mark = Image.open(_BRAND_MARK_PATH).convert("RGBA").resize(
        (size, size), Image.Resampling.LANCZOS
    )
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, size, size), radius=max(10, size // 5), fill=255)
    img.paste(mark, (x, y), mask)


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


@app.template_filter("humanize_since")
def humanize_since(value):
    """Relative freshness, e.g. 'just now' / '8h ago' / 'yesterday' / '3 days ago'."""
    if not value:
        return ""
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return ""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - ts).total_seconds()
    if secs < 3600:
        return "just now"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    days = int(secs // 86400)
    return "yesterday" if days == 1 else f"{days} days ago"

# Projection sources. Steamer (season outlook) is the default; ValuCast H+P is the
# opt-in combined in-house source. App only LOADS committed runs — no runtime model.
DATA_PATH = Path(__file__).parent / "data" / "projections" / "current.json"
VALUCAST_HP_PATH = (
    Path(__file__).parent / "projections" / "runs" / "valucast_hp_2026_v2" / "projections.json"
)
MLB_AVAILABILITY_PATH = Path(__file__).parent / "data" / "models" / "valucast_mlb_availability.json"
CATALOG = ProjectionCatalog(
    {"steamer": str(DATA_PATH), "valucast": str(VALUCAST_HP_PATH)}, default="steamer")
store = CATALOG.store_for("steamer")   # module-level default (kept for existing imports)

# Committed Statcast percentile snapshot (Baseball Savant) for player cards.
# Missing artifact -> cards simply render without the percentile section.
statcast = StatcastStore()

# Committed FanGraphs FV + tool-grade snapshot (The Board) for player cards.
# Display-only scouting reference; never feeds rank/value/score (independence).
fg_fv = FgFvStore()

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

_PROJECTION_ONLY_UNAVAILABLE_STATUSES = {"injured", "rehab"}


@lru_cache(maxsize=1)
def _mlb_availability_by_id():
    if not MLB_AVAILABILITY_PATH.exists():
        return {}
    try:
        payload = json.loads(MLB_AVAILABILITY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out = {}
    for row in payload.get("profiles") or []:
        mlbam_id = row.get("mlbam_id")
        if mlbam_id in (None, ""):
            continue
        out[str(mlbam_id)] = row
    return out


def _has_current_actual_stats(player):
    return bool((player.metadata or {}).get("stats_actual"))


def _mlbam_id(player):
    value = (player.metadata or {}).get("mlbam_id")
    if value in (None, ""):
        return None
    return str(value)


def _is_live_redraft_projection(player):
    """Projection-only rows on IL/rehab should not become live redraft cards."""
    if _has_current_actual_stats(player):
        return True
    mlbam_id = _mlbam_id(player)
    if not mlbam_id:
        return True
    profile = _mlb_availability_by_id().get(mlbam_id) or {}
    status = str(profile.get("status") or "").lower()
    return status not in _PROJECTION_ONLY_UNAVAILABLE_STATUSES


def _valuation_players(always_keep=None, active_store=None):
    """Engine input: all projections minus sub-threshold filler.

    `always_keep` is a set of player ids (display id, suffixed id, or base_id)
    that are retained regardless of playing time, with two-way siblings joined
    on shared base_id inside filter_by_playing_time. `active_store` defaults to the
    module Steamer store (so existing callers/imports are unchanged).
    """
    players = filter_by_playing_time(
        (active_store or store).get_all(),
        hitter_pa=MIN_HITTER_PA,
        sp_ip=MIN_SP_IP,
        rp_ip=MIN_RP_IP,
        always_keep=always_keep or frozenset(),
    )
    return [player for player in players if _is_live_redraft_projection(player)]


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

# Universal prospect profiles loaded ONCE at startup (9.4MB) for the live
# settings-aware re-ranking adapter — never read per-request. Keyed
# (int(mlbam_id), role) -> profile, mirroring prospects.forward_shadow._profile_index.
# If the artifact is missing/empty the feature degrades to unavailable and the
# board still serves its default order (every path returns 200).
UNIVERSAL_PROSPECT_MODEL_PATH = Path(os.environ.get(
    "VALUCAST_UNIVERSAL_PROSPECT_MODEL_PATH",
    str(Path(__file__).parent / "data" / "models" / "valucast_universal_prospect_model.json"),
))


def _load_universal_prospect_profiles(path):
    """Return ((mlbam_id:int, role) -> profile, available:bool)."""
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, False
    index = {}
    for profile in snapshot.get("profiles") or []:
        mlbam_id = profile.get("mlbam_id")
        role = profile.get("role")
        if not isinstance(mlbam_id, int) or role not in {"hitter", "pitcher"}:
            continue
        index.setdefault((mlbam_id, role), profile)
    return index, bool(index)


_UNIVERSAL_PROSPECT_PROFILES, _UNIVERSAL_PROSPECT_AVAILABLE = (
    _load_universal_prospect_profiles(UNIVERSAL_PROSPECT_MODEL_PATH)
)
# Null-object served when no ValuCast snapshot is usable: is_available is False, so
# routes fall through to their existing "unavailable" handling. DD is NEVER served as
# a valuation source — only a ready or stale-but-valid ValuCast snapshot, else this.
_UNAVAILABLE_DYNASTY_STORE = PublicSnapshotStore(
    PUBLIC_SNAPSHOT_PATH.parent / "__no_such_snapshot__.json"
)
# ponytail: 7d is a taste dial — the daily build means older than this signals a
# broken pipeline, so go unavailable rather than serve very stale values.
MAX_SNAPSHOT_STALE_DAYS = 7


def _within_stale_window(generated_at, max_days=MAX_SNAPSHOT_STALE_DAYS):
    try:
        gen = date.fromisoformat(str(generated_at)[:10])
    except (TypeError, ValueError):
        return False
    return (date.today() - gen).days <= max_days


def _select_dynasty_store(snapshot_candidate, use_public_snapshot=None):
    """Serve a ready ValuCast snapshot, else a stale-but-valid one (labeled), else an
    explicit unavailable state. DD is never returned as a valuation fallback."""
    enabled = (
        os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT", "1") == "1"
        if use_public_snapshot is None
        else bool(use_public_snapshot)
    )
    if enabled and snapshot_candidate.is_available:
        if snapshot_candidate.ready_for_live_consumers:
            return snapshot_candidate, "valucast_public_snapshot"
        if _within_stale_window(getattr(snapshot_candidate, "generated_at", None)):
            return snapshot_candidate, "valucast_public_snapshot_stale"
    return _UNAVAILABLE_DYNASTY_STORE, "unavailable"


def _select_buy_source(
    buy_candidate,
    *,
    use_valucast_buys=None,
    public_snapshot_active=None,
):
    if AHEAD_OF_THE_CURVE_HOLD:
        return _UNAVAILABLE_DYNASTY_STORE, "unavailable"
    enabled = (
        os.environ.get("VALUCAST_USE_VALUCAST_BUYS", "1") == "1"
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
    # Never fall back to DD-derived buys — unavailable instead.
    return _UNAVAILABLE_DYNASTY_STORE, "unavailable"


def _buy_source_copy(source: str) -> dict[str, str]:
    if source == "valucast_buys":
        return {
            "label": "ValuCast buy signal",
            "note": "Ranks prospects by model strength, momentum, buy window, and runway.",
            "formula": "buy score = model strength + momentum + buy window + runway",
        }
    return {
        "label": "Prospect buy signal",
        "note": "Ranks prospects by signal strength, recent movement, and runway.",
        "formula": "buy score = momentum + breakout + market gap + runway",
    }


def _buy_spark_label(spark: dict | None) -> str:
    if not spark:
        return ""
    try:
        delta = float(spark.get("delta") or 0.0)
    except (TypeError, ValueError):
        return ""
    direction = "UP" if delta > 0 else ("DOWN" if delta < 0 else "FLAT")
    try:
        first = date.fromisoformat(str(spark.get("first_date")))
        last = date.fromisoformat(str(spark.get("last_date")))
        days = max((last - first).days, 1)
    except (TypeError, ValueError):
        days = None
    if direction == "FLAT":
        return f"FLAT {days}D" if days else "FLAT"
    suffix = f" IN {days}D" if days else ""
    return f"{direction} {delta:+.1f}{suffix}"


dd_store, dynasty_data_source = _select_dynasty_store(public_snapshot_store)
prospect_pool = prospect_percentiles.build_pool(dd_store.get_all()) if dd_store.is_available else {}

# Refuse to promote a deploy with no servable ValuCast snapshot: with gunicorn
# --preload this raises in the master, so the candidate deploy fails and Render keeps
# the prior healthy deploy live. DD is never a valuation fallback — only a ready or
# stale-but-valid ValuCast snapshot is served, else the explicit unavailable state.
if (
    os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT", "1") == "1"
    and dynasty_data_source == "unavailable"
):
    raise RuntimeError(
        "No servable ValuCast snapshot (not ready and not stale-valid). Refusing to "
        "start so the prior healthy Render deploy stays live."
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
            tier_counts = Counter(t for _, t in tiers_list)
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
    """Rank-band tiers for the prospect-only board.

    Prospect scores are intentionally smoother than the old DD feed values, so
    gap hunting collapses the board into a tiny number of tiers. Rank bands keep
    the badge language stable without feeding public ranks into the model.
    """
    bands = ((10, 1), (25, 2), (50, 3), (100, 4), (200, 5))
    rows = sorted(
        dd_store.filter(pool="prospect"),
        key=lambda row: (
            row.prospect_rank is None,
            row.prospect_rank if row.prospect_rank is not None else row.dynasty_rank,
            row.dynasty_rank,
        ),
    )[:200]
    tiers = {}
    for index, row in enumerate(rows, 1):
        for max_rank, tier in bands:
            if index <= max_rank:
                tiers[row.id] = tier
                break
    return tiers


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


# Board vocabulary uses SV_HLD / K_BB; the adapter vocabulary uses SV+HLD / K/BB.
# FIT_QUERY_ALIASES already maps adapter -> board (SV+HLD -> SV_HLD); invert it for
# board -> adapter so the memoized re-scorer can hand the adapter its own keys.
_BOARD_TO_ADAPTER_CATEGORY = {board: adapter for adapter, board in FIT_QUERY_ALIASES.items()}

# Prospect-board presets, sourced from the shipped adapter PRESETS so the board and
# the adapter never drift. Categories are stored in board vocabulary (the URL/state
# contract); _custom_prospect_ranks canonicalizes them back to adapter vocabulary.


def _to_board_category(name):
    return FIT_QUERY_ALIASES.get(name, name)


def _to_adapter_category(name):
    return _BOARD_TO_ADAPTER_CATEGORY.get(name, name)


def _prospect_preset_cats(preset_key):
    """Return ((cat, weight), ...) pairs in board vocabulary for a preset.

    Weights (including the negative signs on SO/ERA/WHIP/L) come straight from the
    shipped adapter PRESETS, so the board never re-derives or drifts from them.
    """
    from prospects.adapters import PRESETS as _ADAPTER_PRESETS
    preset = _ADAPTER_PRESETS[preset_key]
    cats = tuple((_to_board_category(cat), weight) for cat, weight in preset["hitter"].items())
    pcats = tuple((_to_board_category(cat), weight) for cat, weight in preset["pitcher"].items())
    return cats, pcats


PROSPECT_CATEGORY_PRESETS = {
    "dd_7x7": "7x7",
    "roto_5x5": "Standard 5x5",
}


def _prospect_canonical_signs():
    """Per-category sign (+1/-1) in board vocabulary for arbitrary user picks.

    Signs are DERIVED from the shipped adapter PRESETS — every category's
    direction is consistent across presets (lower-is-better cats like ERA/WHIP/SO/L
    carry a negative weight), so the board never invents one. The few supported
    categories absent from any preset (the PA / IP volume anchors) are not flips in
    the existing dynasty fit machinery either, so they default to +1 like every
    other counting stat. Keyed by board vocabulary (SV_HLD / K_BB) to match the
    URL/state contract.
    """
    from prospects.adapters import PRESETS as _ADAPTER_PRESETS
    signs = {}
    for preset in _ADAPTER_PRESETS.values():
        for role in ("hitter", "pitcher"):
            for cat, weight in preset[role].items():
                signs[_to_board_category(cat)] = 1 if weight >= 0 else -1
    return signs


_PROSPECT_CANONICAL_SIGNS = _prospect_canonical_signs()


def _prospect_supported_cats():
    """SUPPORTED prospect categories in board vocabulary, split by role.

    The adapter's projectable universe (prospects.adapters.SUPPORTED_CATEGORIES)
    mapped to board vocabulary — the allowlist for arbitrary user picks and the UI
    chips. Anything outside this set cannot be projected, so it is dropped from
    custom selections (and the coverage guard catches any that slip through).
    """
    from prospects.adapters import SUPPORTED_CATEGORIES as _SUPPORTED
    return {
        role: {_to_board_category(cat) for cat in cats}
        for role, cats in _SUPPORTED.items()
    }


_PROSPECT_SUPPORTED_CATS = _prospect_supported_cats()


@lru_cache(maxsize=16)
def _custom_prospect_ranks(cats_tuple, pcats_tuple):
    """Settings-aware adapter re-rank over the universal prospect pool.

    cats_tuple/pcats_tuple are (category, weight) pairs in BOARD vocabulary. They
    are canonicalized to the adapter vocabulary (SV_HLD -> SV+HLD, K_BB -> K/BB),
    fed to the within-role adapter, and returned as
    {(mlbam_id:int, role): {"adapter_rank","adapter_score"}} plus per-role
    status / missing_categories. Inputs are hashable tuples so the cache is keyed
    by the actual category set. The adapter output is a downstream VIEW only and is
    never fed back into the universal index or rank_v1.
    """
    from prospects.adapters import adapt_categories
    hitter_cats = {_to_adapter_category(cat): weight for cat, weight in cats_tuple}
    pitcher_cats = {_to_adapter_category(cat): weight for cat, weight in pcats_tuple}
    profiles = list(_UNIVERSAL_PROSPECT_PROFILES.values())
    result = adapt_categories(
        profiles,
        name="prospect_board",
        categories={"hitter": hitter_cats, "pitcher": pitcher_cats},
    )
    ranks = {}
    role_status = {}
    for role in ("hitter", "pitcher"):
        role_result = result["roles"][role]
        role_status[role] = {
            "status": role_result["status"],
            "missing_categories": role_result.get("missing_categories") or [],
        }
        for player in role_result["players"]:
            mlbam_id = player.get("mlbam_id")
            adapter_rank = player.get("adapter_rank")
            if not isinstance(mlbam_id, int) or adapter_rank is None:
                continue
            ranks[(mlbam_id, role)] = {
                "adapter_rank": adapter_rank,
                "adapter_score": player.get("adapter_score"),
            }
    return {"ranks": ranks, "role_status": role_status}


def _prospect_custom_cats(args):
    """Arbitrary user-picked prospect cats/pcats as ((cat, weight), ...) pairs.

    Reads cats/pcats from the URL in board vocabulary (comma-separated, like the
    dynasty path) and attaches the canonical sign (magnitude 1.0) so
    lower-is-better cats re-rank correctly. Pure garbage (anything outside the
    recognized league vocabulary FIT_CATS/FIT_PCATS) is dropped here; a recognized
    league category the model cannot project (e.g. a hand-edited W / SV) is kept so
    the adapter's coverage guard in _apply_prospect_board_context explains why the
    board can't re-rank and keeps the default order. The UI chips only ever offer
    the SUPPORTED set, so normal selections never reach that guard.
    """
    picked_cats = parse_list(args.getlist("cats"))
    picked_pcats = parse_list(args.getlist("pcats"))
    cats = tuple(
        (cat, float(_PROSPECT_CANONICAL_SIGNS.get(cat, 1)))
        for cat in picked_cats
        if cat in FIT_CATS
    )
    pcats = tuple(
        (cat, float(_PROSPECT_CANONICAL_SIGNS.get(cat, 1)))
        for cat in picked_pcats
        if cat in FIT_PCATS
    )
    return cats, pcats


def _prospect_category_state(args):
    """Canonical prospect re-ranking params (presets or arbitrary custom cats).

    Returns (cats, pcats, custom_active, preset_label). With rank_by=league a
    named preset wins; otherwise arbitrary cats/pcats (board vocabulary) flow
    through with canonical signs and a "Custom" label. A garbage preset or an
    empty/unsupported custom set falls back to the default board (custom_active
    False) so every path serves 200.
    """
    rank_by = args.get("rank_by", "default")
    if rank_by != "league":
        return (), (), False, ""
    preset_key = (args.get("preset") or "").strip()
    if preset_key in PROSPECT_CATEGORY_PRESETS:
        cats, pcats = _prospect_preset_cats(preset_key)
        return cats, pcats, True, PROSPECT_CATEGORY_PRESETS[preset_key]
    if preset_key:
        # A named-but-unknown preset is garbage, not an invitation to read cats.
        return (), (), False, ""
    cats, pcats = _prospect_custom_cats(args)
    if not cats and not pcats:
        return (), (), False, ""
    return cats, pcats, True, "Custom"


def _apply_prospect_board_context(ctx, args):
    """Apply dedicated prospect-board rows and metadata to a DD context."""
    rows = _prospect_rows(
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
    # Recent-form momentum chips: only the prominent movers (top-25 heating/cooling)
    # earn a board chip so it stays meaningful. Display-only -- never touches score.
    recent_form = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_recent_form_signal.json"
    ) or {}
    form_by_key = {}
    for entry in (recent_form.get("heating_up") or []) + (recent_form.get("cooling_off") or []):
        key = _identity_key(entry.get("mlbam_id"), entry.get("role"))
        if key:
            form_by_key[key] = entry
    ctx["momentum_by_id"] = {
        row.id: form_by_key[key]
        for row in rows
        if (key := _row_identity_key(row)) in form_by_key
    }
    # Same-day call-up pulse: board prospects already on a fresh MLB active roster
    # (called up after the morning build). Display-only "Called up" badge.
    call_up = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_call_up_pulse.json"
    ) or {}
    call_up_by_key = call_up.get("by_identity") or {}
    ctx["call_up_by_id"] = {
        row.id: call_up_by_key[key]
        for row in rows
        if (key := _row_identity_key(row)) in call_up_by_key
    }

    # Live settings-aware re-ranking (presets OR arbitrary custom cats). Re-ranking
    # is a downstream VIEW: it never touches dynasty_value, P#, or the prospect
    # score, and only orders within hitters and pitchers separately.
    cats, pcats, custom_active, preset_label = _prospect_category_state(args)
    ctx["custom_cats_active"] = False
    ctx["prospect_preset"] = (args.get("preset") or "").strip()
    ctx["prospect_rank_by"] = "league" if custom_active else "default"
    ctx["prospect_preset_label"] = preset_label
    # Board-vocabulary allowlist + selection echo for the custom category chips.
    ctx["prospect_supported_cats"] = sorted(_PROSPECT_SUPPORTED_CATS["hitter"])
    ctx["prospect_supported_pcats"] = sorted(_PROSPECT_SUPPORTED_CATS["pitcher"])
    ctx["prospect_selected_cats"] = {cat for cat, _ in cats}
    ctx["prospect_selected_pcats"] = {cat for cat, _ in pcats}
    if custom_active and _UNIVERSAL_PROSPECT_AVAILABLE:
        scored = _custom_prospect_ranks(cats, pcats)
        role_status = scored["role_status"]
        missing = sorted({
            cat
            for role in ("hitter", "pitcher")
            if role_status[role]["status"] == "insufficient_category_coverage"
            for cat in role_status[role]["missing_categories"]
        })
        if missing:
            # Refuse partial coverage: keep the DEFAULT order and tell the user
            # which categories the universal model cannot rank (roto_5x5 hits this
            # because the model has no W / SV projections).
            ctx["coverage_notice"] = (
                f"{preset_label} re-ranking needs categories ValuCast's prospect "
                f"model doesn't project yet ({', '.join(missing)}). Showing the "
                "default prospect order."
            )
        else:
            adapter_ranks = {}
            for row in rows:
                key = _prospect_adapter_key(row)
                hit = scored["ranks"].get(key) if key else None
                if hit:
                    adapter_ranks[row.id] = hit["adapter_rank"]
            # Re-sort by adapter rank; rows with no profile sort LAST in their
            # existing default order.
            rows = sorted(
                rows,
                key=lambda r: (r.id not in adapter_ranks,
                               adapter_ranks.get(r.id, 0)),
            )
            ctx["league_adapter_ranks"] = adapter_ranks
            ctx["custom_cats_active"] = True
    ctx["dd_rows"] = rows


def _prospect_adapter_key(row):
    """(int(mlbam_id), role) join key for a prospect row, or None when unusable."""
    mlbam_id = getattr(row, "mlbam_id", None)
    role = getattr(row, "role", None)
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    try:
        return (int(mlbam_id), role)
    except (TypeError, ValueError):
        return None


def _prospect_graphic_svg(rows, *, limit, position=None, search=None, noun="Prospects", footer_note=None):
    """Render an Ahead of the Curve-style SVG share graphic."""
    width = 1080
    header_height = 245
    footer_height = 92
    dense = limit >= 50
    if dense:
        cols = 2 if limit <= 50 else 5
        cell_h = 42 if cols == 2 else 52
        dense_rows = max(1, math.ceil(len(rows) / cols))
        height = header_height + dense_rows * cell_h + footer_height
    else:
        row_height = 58 if limit == 20 else 78
        height = header_height + max(len(rows), 1) * row_height + footer_height
    scope = f"{position} " if position else ""
    title = f"Top {limit} {scope}{noun}"
    if search:
        title += f" | {search}"
    updated = dd_store.generated_at[:10] if dd_store.generated_at else "current feed"
    rank_kind = f"{position.upper()} RANK" if position else "LIST RANK"

    def svg_value_label(row):
        try:
            return f"{float(row.value):.1f}"
        except (TypeError, ValueError):
            return "--"

    def svg_abbrev_name(name):
        parts = (name or "").split()
        if len(parts) > 1:
            return f"{parts[0][0]}. {' '.join(parts[1:])}"
        return name or "Unknown"

    def svg_clip(label, max_chars):
        label = str(label or "")
        return label if len(label) <= max_chars else label[: max_chars - 3].rstrip() + "..."

    def svg_tag(row):
        pieces = ["/".join(row.positions[:2]) if row.positions else "UT"]
        lvl = row.level or ("MLB" if row.status == "mlb" else "PRO")
        if lvl:
            pieces.append(str(lvl))
        return " ".join(pieces)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)}">',
        "<defs>",
        '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">',
        '<stop offset="0%" stop-color="#0b0c0f"/>',
        '<stop offset="55%" stop-color="#15161b"/>',
        '<stop offset="100%" stop-color="#0a0b0e"/>',
        "</linearGradient>",
        '<linearGradient id="card" x1="0" y1="0" x2="1" y2="0">',
        '<stop offset="0%" stop-color="#1d1f26"/>',
        '<stop offset="100%" stop-color="#15161b"/>',
        "</linearGradient>",
        "</defs>",
        '<rect width="1080" height="100%" fill="url(#bg)"/>',
        '<path d="M828 70 C912 30 996 28 1052 64" fill="none" stroke="#34e2c4" stroke-width="3" opacity=".55"/>',
        '<path d="M828 100 C916 60 996 58 1052 92" fill="none" stroke="#1c7a6c" stroke-width="2" opacity=".5"/>',
        '<text x="64" y="58" fill="#34e2c4" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="26" font-weight="700" letter-spacing="4">VALUCAST</text>',
        '<text x="64" y="90" fill="#9197a6" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="18" font-weight="700" letter-spacing="0">Ahead of the Curve</text>',
        f'<text x="68" y="174" fill="#e8e9ee" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="32" font-weight="600">{escape(title)}</text>',
        f'<text x="68" y="207" fill="#9197a6" font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="17" font-weight="500">Filtered from the current prospect board | Updated {escape(updated)}</text>',
    ]

    if not rows:
        parts.extend([
            '<rect x="72" y="255" width="952" height="108" rx="10" fill="#000000" opacity=".20"/>',
            '<rect x="64" y="245" width="952" height="108" rx="10" fill="url(#card)" stroke="#2a2c34" stroke-width="1"/>',
            '<text x="112" y="310" fill="#9197a6" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="30" font-weight="600">No prospects found for this filter.</text>',
        ])
    elif dense:
        cols = 2 if limit <= 50 else 5
        cell_w = 984 / cols
        cell_h = 42 if cols == 2 else 52
        n_rows = max(1, math.ceil(len(rows) / cols))
        table_h = n_rows * cell_h
        start_x, start_y = 48, header_height
        parts.append(
            f'<rect x="{start_x}" y="{start_y}" width="984" height="{table_h}" fill="#0b0c0f" stroke="#2a2c34" stroke-width="1"/>'
        )
        for i, row in enumerate(rows):
            # Column-major: 1..n_rows down the first column, then the next.
            col, r = i // n_rows, i % n_rows
            x, y = start_x + col * cell_w, start_y + r * cell_h
            fill = "#1c1e25" if r % 2 == 0 else "#0b0c0f"
            parts.append(
                f'<rect x="{x:.1f}" y="{y}" width="{cell_w:.1f}" height="{cell_h}" fill="{fill}"/>'
            )
            if col:
                parts.append(
                    f'<line x1="{x:.1f}" y1="{y}" x2="{x:.1f}" y2="{y + cell_h}" stroke="#2a2c34" stroke-width="1"/>'
                )
            if r:
                parts.append(
                    f'<line x1="{x:.1f}" y1="{y}" x2="{x + cell_w:.1f}" y2="{y}" stroke="#2a2c34" stroke-width="1"/>'
                )
            rank = i + 1
            value = svg_value_label(row)
            if cols == 2:
                parts.extend([
                    f'<text x="{x + 12:.1f}" y="{y + 27}" fill="#8a92a8" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="15" font-weight="700">#{rank}</text>',
                    f'<text x="{x + 68:.1f}" y="{y + 27}" fill="#e8e9ee" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="16" font-weight="600">{escape(svg_clip(row.name, 26))}</text>',
                    f'<text x="{x + 292:.1f}" y="{y + 27}" fill="#9197a6" font-family="JetBrains Mono,Consolas,monospace" font-size="12" font-weight="500">{escape(svg_clip(svg_tag(row), 12))}</text>',
                    f'<text x="{x + cell_w - 12:.1f}" y="{y + 27}" text-anchor="end" fill="#34e2c4" font-family="JetBrains Mono,Consolas,monospace" font-size="16" font-weight="700">{escape(value)}</text>',
                ])
            else:
                parts.extend([
                    f'<text x="{x + 10:.1f}" y="{y + 30}" fill="#8a92a8" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="13" font-weight="700">#{rank}</text>',
                    f'<text x="{x + 48:.1f}" y="{y + 30}" fill="#e8e9ee" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="13" font-weight="600">{escape(svg_clip(svg_abbrev_name(row.name), 12))}</text>',
                    f'<text x="{x + cell_w - 10:.1f}" y="{y + 30}" text-anchor="end" fill="#34e2c4" font-family="JetBrains Mono,Consolas,monospace" font-size="13" font-weight="700">{escape(value)}</text>',
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
                f'<rect x="70" y="{y + 7}" width="952" height="{card_h}" rx="10" fill="#000000" opacity=".18"/>',
                f'<rect x="64" y="{y}" width="952" height="{card_h}" rx="10" fill="url(#card)" stroke="#2a2c34" stroke-width="1"/>',
                f'<rect x="82" y="{y + 6}" width="{rank_box}" height="{rank_box}" rx="8" fill="#23252c"/>',
                f'<text x="{82 + rank_box / 2}" y="{y + card_h / 2 + 9}" text-anchor="middle" fill="#cfd3e0" font-family="JetBrains Mono,Consolas,monospace" font-size="{18 if limit == 20 else 22}" font-weight="700">#{rank}</text>',
                f'<text x="154" y="{y + (31 if limit == 10 else 24)}" fill="#e8e9ee" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="{name_size}" font-weight="600">{escape(row.name)}</text>',
                f'<text x="154" y="{y + (57 if limit == 10 else 41)}" fill="#9197a6" font-family="JetBrains Mono,Consolas,monospace" font-size="{detail_size}" font-weight="500">{escape(detail)}</text>',
                f'<text x="842" y="{y + card_h / 2 + 8}" fill="#9197a6" font-family="JetBrains Mono,Consolas,monospace" font-size="{18 if limit == 20 else 21}" font-weight="600">{escape(rank_kind)}</text>',
            ])

    parts.extend([
        f'<text x="64" y="{height - 44}" fill="#9197a6" font-family="system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="16" font-weight="500">Generated from the Prospects tab filters. Rank numbers are local to this graphic.</text>',
        f'<text x="64" y="{height - 20}" fill="#34e2c4" font-family="JetBrains Mono,Consolas,monospace" font-size="14" font-weight="600">valucast.app</text>',
        "</svg>",
    ])
    return "".join(parts)


def _prospect_graphic_png(rows, *, limit, position=None, search=None, noun="Prospects", hero_kicker=None, footer_note=None):
    """Render an Ahead of the Curve-style PNG for easy posting/saving.

    noun/hero_kicker/footer_note let other ranked boards (Dynasty, Redraft) reuse
    this renderer with their own labels; defaults keep the prospect output identical.
    """
    from PIL import Image, ImageDraw

    # ponytail: reuse the module-level graphic helpers instead of re-defining them here
    font = _graphic_font
    text_width = _graphic_text_width
    fit_text = _graphic_fit_text

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

    def tag(row, *, age=False, compact=False):
        positions = "/".join(row.positions[:2]) if row.positions else "UT"
        lvl = level_text(row)
        if compact:
            # Position + level only (drop team) for tight dense cells.
            pieces = [positions]
            if lvl:
                pieces.append(str(lvl))
            return " - ".join(pieces)
        pieces = [row.team or "FA", positions]
        if lvl:
            pieces.append(str(lvl))
        if age and row.age is not None:
            pieces.append(f"Age {row.age}")
        return " - ".join(pieces)

    def rank_label(fallback):
        return f"#{fallback}"

    def hero_rank_heading(fallback):
        if position:
            return f"position rank #{fallback}"
        return f"list rank #{fallback}"

    def value_label(row):
        try:
            return f"{float(row.value):.1f}"
        except (TypeError, ValueError):
            return None

    def overall_label(row):
        if getattr(row, "prospect_rank", None) is not None:
            return f"P#{row.prospect_rank}"
        return None

    def draw_chip(x, y, label, *, fill=None, fg=None, outline=None, fnt=None):
        if not label:
            return x
        fill = fill or (24, 26, 32)
        fg = fg or muted
        outline = outline or border
        fnt = fnt or font(15, bold=True)
        pad_x = 13
        chip_w = text_width(draw, label, fnt) + pad_x * 2
        draw.rounded_rectangle((x, y, x + chip_w, y + 31), radius=8, fill=fill, outline=outline, width=1)
        draw.text((x + pad_x, y + 7), label, fill=fg, font=fnt)
        return x + chip_w + 8

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
    bg = _GRAPHIC_PALETTE["bg"]
    card = _GRAPHIC_PALETTE["card"]
    card_2 = _GRAPHIC_PALETTE["card_2"]
    border = _GRAPHIC_PALETTE["border"]
    green = _GRAPHIC_PALETTE["green"]
    blue = _GRAPHIC_PALETTE["blue"]
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)

    scope = f"{position.upper()} " if position else ""
    subtitle_date = _editorial_date(dd_store.generated_at)
    subtitle = f"Top {limit} {scope}{noun} from the current board"
    if search:
        subtitle = f"{subtitle} | {search}"
    if subtitle_date:
        subtitle = f"{subtitle} - {subtitle_date}"
    _graphic_header(img, draw, headline="AHEAD OF THE CURVE", subtitle=subtitle)

    def draw_dense_prospect_grid(
        grid_rows,
        *,
        cols,
        cell_w,
        cell_h,
        start_x,
        start_y,
        show_tag=False,
        full_name=False,
        rank_size=14,
        name_size=14,
        tag_size=12,
        score_size=14,
    ):
        row_count = max(1, math.ceil(len(grid_rows) / cols))
        table_w = cols * cell_w
        table_h = row_count * cell_h
        draw.rectangle((start_x, start_y, start_x + table_w, start_y + table_h), fill=bg, outline=border, width=1)

        rank_font = font(rank_size, bold=True)
        name_font = font(name_size, bold=True)
        tag_font = font(tag_size, mono=True)
        score_font = font(score_size, bold=True, mono=True)

        for slot in range(row_count * cols):
            # Column-major: fill the first column top-to-bottom (ranks 1..row_count),
            # then the next column -- so a Top-50 reads 1-25 | 26-50 down each column.
            col, r = slot // row_count, slot % row_count
            x, y = start_x + col * cell_w, start_y + r * cell_h
            fill = card_2 if r % 2 == 0 else bg
            draw.rectangle((x, y, x + cell_w, y + cell_h), fill=fill)
            if col:
                draw.line((x, y, x, y + cell_h), fill=border, width=1)
            if r:
                draw.line((x, y, x + cell_w, y), fill=border, width=1)
            if slot >= len(grid_rows):
                continue

            row = grid_rows[slot]
            row_rank = slot + 1
            rank_text = rank_label(row_rank)
            score = value_label(row) or "--"
            # Wider right margin on the 2-col (tagged) layout so the value clears the
            # column divider instead of creeping into the next column.
            score_margin = 16 if show_tag else 10
            score_x = x + cell_w - score_margin - text_width(draw, score, score_font)
            text_y = y + max(8, (cell_h - name_size) // 2 - 1)

            draw.text((x + 10, text_y), rank_text, fill=blue, font=rank_font)
            draw.text((score_x, text_y - 1), score, fill=green, font=score_font)

            name_x = x + (68 if show_tag else 48)
            if show_tag:
                tag_x = x + cell_w - 142
                # Bound the tag so it always stops short of the value (no overlap).
                tag_text = fit_text(draw, tag(row, compact=True), tag_font, max(36, score_x - tag_x - 10))
                draw.text((tag_x, text_y + 2), tag_text, fill=muted, font=tag_font)
                name_max = max(72, tag_x - name_x - 10)
            else:
                name_max = max(54, score_x - name_x - 8)
            draw.text(
                (name_x, text_y),
                fit_text(draw, row.name if full_name else abbrev_name(row.name), name_font, name_max),
                fill=text,
                font=name_font,
            )

    if not rows:
        draw.rounded_rectangle((48, 225, 1032, 360), radius=10, fill=card, outline=border, width=1)
        draw.text((76, 276), "No prospects found for this filter.", fill=text, font=font(30, bold=True))
    elif limit <= 10:
        # Compact variant for position top-10s: same voice, less empty space.
        hero = rows[0]
        leader = hero_kicker or ("POSITION LEADER" if position else "TOP PROSPECT")
        draw.rounded_rectangle((48, 226, 1032, 532), radius=10, fill=card, outline=border, width=1)
        draw.text((70, 252), leader, fill=muted, font=font(20, bold=True))
        draw.text((70, 282), hero_rank_heading(1).upper(), fill=muted, font=font(16, bold=True))
        hero_name_font = font(43, bold=True)
        hero_name_lines = split_name_lines(draw, hero.name, hero_name_font, 540)
        for line_idx, line in enumerate(hero_name_lines):
            draw.text((70, 320 + line_idx * 50), line, fill=text, font=hero_name_font)
        draw.text((70, 386 + (len(hero_name_lines) - 1) * 44), fit_text(draw, tag(hero, age=True), font(20, mono=True), 540), fill=muted, font=font(20, mono=True))

        value = value_label(hero)
        draw.rounded_rectangle((650, 320, 990, 462), radius=10, fill=(14, 29, 30), outline=(20, 59, 55), width=1)
        draw.text((672, 342), "VALUCAST VALUE", fill=muted, font=font(15, bold=True))
        draw.text((672, 366), value or "--", fill=green, font=font(46, bold=True, mono=True))
        draw_chip(810, 350, overall_label(hero), fill=card, fg=muted, outline=border)
        draw_chip(810, 392, "current board", fill=card, fg=muted, outline=border, fnt=font(14, bold=True))
        spark = spark_points(hero, 670, 484, 260, 34)
        if spark:
            draw.line(spark[0], fill=green if spark[1] == "up" else muted, width=3, joint="curve")
            draw.text((670, 522), "RECENT MOVEMENT", fill=muted, font=font(15, bold=True))

        grid_rows = rows[1:10]
        cols = 3
        cell_w, cell_h = 312, 166
        start_x, start_y = 48, 568
        for idx, row in enumerate(grid_rows):
            col, r = idx % cols, idx // cols
            x, y = start_x + col * (cell_w + 24), start_y + r * (cell_h + 18)
            draw.rounded_rectangle((x, y, x + cell_w, y + cell_h), radius=8, fill=card_2, outline=border, width=1)
            draw.text((x + 18, y + 16), rank_label(idx + 2), fill=blue, font=font(21, bold=True))
            card_name_font = font(24, bold=True)
            name_lines = split_name_lines(draw, row.name, card_name_font, 220)
            for line_idx, line in enumerate(name_lines[:2]):
                draw.text((x + 18, y + 52 + line_idx * 27), line, fill=text, font=card_name_font)
            tag_y = y + (98 if len(name_lines) > 1 else 90)
            draw.text((x + 18, tag_y), fit_text(draw, tag(row), font(16), 220), fill=muted, font=font(16))
            draw.text((x + cell_w - 86, y + 20), note_label(row), fill=muted, font=font(14, bold=True))
            draw.line((x + 18, y + 120, x + cell_w - 18, y + 120), fill=border, width=1)
            draw.text((x + 18, y + 132), "VAL", fill=muted, font=font(13, bold=True))
            cell_val = value_label(row) or "--"
            cell_val_font = font(26, bold=True, mono=True)
            draw.text(
                (x + cell_w - 18 - text_width(draw, cell_val, cell_val_font), y + 126),
                cell_val, fill=green, font=cell_val_font,
            )
    elif limit >= 50:
        if limit <= 50:
            draw_dense_prospect_grid(
                rows,
                cols=2,
                cell_w=492,
                cell_h=41,
                start_x=48,
                start_y=226,
                show_tag=True,
                full_name=True,
                rank_size=15,
                name_size=16,
                tag_size=12,
                score_size=16,
            )
        else:
            draw_dense_prospect_grid(
                rows,
                cols=5,
                cell_w=196,
                cell_h=52,
                start_x=48,
                start_y=226,
                show_tag=False,
                rank_size=13,
                name_size=13,
                score_size=13,
            )
    else:
        hero = rows[0]
        leader = hero_kicker or ("POSITION LEADER" if position else "TOP PROSPECT")
        draw.rounded_rectangle((48, 226, 418, 540), radius=10, fill=card, outline=border, width=1)
        draw.text((70, 252), leader, fill=muted, font=font(20, bold=True))
        draw.text((70, 282), hero_rank_heading(1).upper(), fill=muted, font=font(15, bold=True))
        hero_name_font = font(31, bold=True)
        hero_name_lines = split_name_lines(draw, hero.name, hero_name_font, 320)
        for line_idx, line in enumerate(hero_name_lines):
            draw.text((70, 322 + line_idx * 37), line, fill=text, font=hero_name_font)
        draw.text((70, 398 + (len(hero_name_lines) - 1) * 26), fit_text(draw, tag(hero), font(18, mono=True), 320), fill=muted, font=font(18, mono=True))
        hero_value = value_label(hero)
        draw.text((70, 455), f"VAL {hero_value or '--'}", fill=green, font=font(39, bold=True, mono=True))
        draw.text((70, 503), "MODEL SCORE", fill=muted, font=font(16, bold=True))

        supports = rows[1:5]
        for idx, row in enumerate(supports):
            x = 435 + (idx % 2) * 307
            y = 226 + (idx // 2) * 164
            draw.rounded_rectangle((x, y, x + 291, y + 149), radius=10, fill=card, outline=border, width=1)
            draw.text((x + 18, y + 18), rank_label(idx + 2), fill=blue, font=font(19, bold=True))
            support_name_font = font(20, bold=True)
            support_name_lines = split_name_lines(draw, row.name, support_name_font, 250)
            for line_idx, line in enumerate(support_name_lines[:2]):
                draw.text((x + 18, y + 44 + line_idx * 23), line, fill=text, font=support_name_font)
            support_tag_y = _graphic_support_tag_y(
                y, len(support_name_lines), one_line_offset=76, wrapped_offset=91
            )
            draw.text((x + 18, support_tag_y), fit_text(draw, tag(row), font(14, mono=True), 250), fill=muted, font=font(14, mono=True))
            draw.line((x + 16, y + 104, x + 275, y + 104), fill=border, width=1)
            draw.text((x + 16, y + 118), note_label(row), fill=muted, font=font(14, bold=True))
            sup_val = value_label(row) or "--"
            sup_val_font = font(22, bold=True, mono=True)
            draw.text((x + 275 - text_width(draw, sup_val, sup_val_font), y + 112), sup_val, fill=green, font=sup_val_font)

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
            draw.text((x + 14, y + 50), fit_text(draw, row.name, font(22, bold=True), 290), fill=text, font=font(22, bold=True))
            draw.text((x + 14, y + 84), fit_text(draw, tag(row), font(18), 230), fill=muted, font=font(18))
            rest_val = value_label(row) or "--"
            rest_val_font = font(20, bold=True, mono=True)
            draw.text((x + cell_w - 14 - text_width(draw, rest_val, rest_val_font), y + 82), rest_val, fill=green, font=rest_val_font)

    footer = footer_note or "ValuCast Prospect Rank - stats + age/level + investment + availability"
    _graphic_footer(draw, right_note=footer)
    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


_GRAPHIC_PALETTE = {
    # Phase 2 Broadcast Board — neutral cool-black base, teal = the one signal,
    # slate = structure/ranks (no functional blue in a static graphic), clay = decline.
    "bg": (11, 12, 15),
    "card": (21, 22, 27),
    "card_2": (28, 30, 37),
    "border": (42, 44, 52),
    "green": (52, 226, 196),   # legacy key, now teal — repaints every old green accent
    "teal": (52, 226, 196),
    "blue": (138, 146, 168),   # legacy key, now slate — ranks/monograms are structural
    "slate": (94, 102, 120),
    "clay": (204, 138, 102),
    "text": (231, 233, 240),
    "muted": (150, 151, 166),
}


def _graphic_fill_background(img):
    from PIL import ImageDraw

    width, height = img.size
    draw = ImageDraw.Draw(img)
    for y in range(height):
        t = y / height
        draw.line(
            [(0, y), (width, y)],
            fill=(round(11 + 5 * t), round(12 + 5 * t), round(15 + 7 * t)),
        )


def _graphic_header(img, draw, *, headline, subtitle, extra_line=None):
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]
    green = _GRAPHIC_PALETTE["green"]

    # Compact brand lockup, not a billboard — this is an exported app surface.
    # "Ahead of the Curve" brands the graphic without dominating the player.
    # (headline arg kept for call-site compatibility; the tagline is fixed.)
    draw.arc((792, 26, 1052, 250), start=200, end=300, fill=(52, 226, 196), width=3)
    draw.arc((792, 48, 1052, 228), start=204, end=296, fill=(28, 120, 108), width=2)
    _paste_brand_mark(img, 48, 42, size=52)
    draw.text((116, 48), "VALUCAST", fill=green, font=_graphic_font(28, bold=True))
    draw.text((118, 86), "Ahead of the Curve", fill=muted, font=_graphic_font(18, bold=True))
    sub_font = _graphic_font(22)
    draw.text((48, 152), _graphic_fit_text(draw, subtitle, sub_font, 940), fill=text, font=sub_font)
    if extra_line:
        draw.text((48, 183), extra_line, fill=green, font=_graphic_font(15, bold=True))


def _graphic_footer(draw, *, right_note=None):
    card = _GRAPHIC_PALETTE["card"]
    border = _GRAPHIC_PALETTE["border"]
    muted = _GRAPHIC_PALETTE["muted"]

    foot_y = 1350 - 68
    draw.rounded_rectangle((48, foot_y, 1032, foot_y + 46), radius=8, fill=card, outline=border, width=1)
    draw.text((60, foot_y + 10), "valucast.app", fill=muted, font=_graphic_font(22))
    if right_note:
        note_font = _graphic_font(16)
        draw.text(
            (1032 - 14 - _graphic_text_width(draw, right_note, note_font), foot_y + 14),
            right_note,
            fill=muted,
            font=note_font,
        )


def _graphic_monogram(draw, cx, cy, r, name, *, size=None):
    blue = _GRAPHIC_PALETTE["blue"]
    initials = buy_score.graphic_initials(name or "")
    mono = _graphic_font(size or max(12, int(r * 0.8)), bold=True, mono=True)

    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(24, 26, 32), outline=(44, 46, 54), width=2)
    box = draw.textbbox((0, 0), initials, font=mono)
    draw.text(
        (cx - (box[2] - box[0]) / 2, cy - (box[3] - box[1]) / 2),
        initials,
        fill=blue,
        font=mono,
    )


_GRAPHIC_FONT_DIR = Path(__file__).parent / "static" / "fonts"
_GRAPHIC_BRAND_FONTS = {
    "display": _GRAPHIC_FONT_DIR / "SpaceGrotesk[wght].ttf",
    "mono": _GRAPHIC_FONT_DIR / "JetBrainsMono[wght].ttf",
}


def _graphic_font(size, *, bold=False, serif=False, mono=False):
    from PIL import ImageFont

    # Brand fonts first — Broadcast Board parity (Space Grotesk display / JetBrains Mono figures).
    # Variable TTFs: set the weight axis numerically (robust across instance-name sets);
    # fall back silently to the system/DejaVu stack if the font or axis is unavailable.
    brand = _GRAPHIC_BRAND_FONTS["mono" if mono else "display"]
    if brand.exists():
        try:
            font = ImageFont.truetype(str(brand), size)
            try:
                font.set_variation_by_axes([700 if bold else 500])
            except Exception:
                pass
            return font
        except OSError:
            pass

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
        Path(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ),
        Path("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"),
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(str(candidate), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _graphic_text_width(draw, text, fnt):
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def _graphic_fit_text(draw, text, fnt, max_width):
    text = str(text or "")
    if _graphic_text_width(draw, text, fnt) <= max_width:
        return text
    trimmed = text
    while trimmed and _graphic_text_width(draw, trimmed + "...", fnt) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed.rstrip() + "...") if trimmed else "..."


def _graphic_wrap_text(draw, text, fnt, max_width, max_lines=3):
    words = str(text or "").split()
    lines = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or _graphic_text_width(draw, candidate, fnt) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and words:
        lines[-1] = _graphic_fit_text(draw, lines[-1], fnt, max_width)
    return lines


def _graphic_support_tag_y(base_y: int, line_count: int, *, one_line_offset: int, wrapped_offset: int) -> int:
    """Return the tag baseline for compact share-card support cells."""
    return base_y + (wrapped_offset if line_count > 1 else one_line_offset)


_GRAPHIC_DANGLING_READ_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "for",
    "her",
    "his",
    "in",
    "of",
    "or",
    "the",
    "to",
    "with",
}


def _graphic_last_sentence_boundary(text):
    for idx in range(len(text) - 1, -1, -1):
        char = text[idx]
        if char not in ".!?":
            continue
        prev_char = text[idx - 1] if idx else ""
        next_char = text[idx + 1] if idx + 1 < len(text) else ""
        if prev_char.isdigit() and next_char.isdigit():
            continue
        if not next_char or next_char.isspace():
            return idx
    return -1


def _graphic_wrap_read_text(draw, text, fnt, max_width, max_lines=4):
    """Fit player-card prose without hard-clipping mid-thought."""
    max_lines = max(1, int(max_lines or 1))
    text = " ".join(str(text or "").split())
    if not text:
        return []
    full_lines = _graphic_wrap_text(
        draw, text, fnt, max_width, max_lines=max_lines + 1
    )
    if len(full_lines) <= max_lines:
        return full_lines

    best = ""
    words = text.split()
    for idx in range(1, len(words) + 1):
        candidate = " ".join(words[:idx])
        candidate_lines = _graphic_wrap_text(
            draw, candidate, fnt, max_width, max_lines=max_lines + 1
        )
        if len(candidate_lines) > max_lines:
            break
        best = candidate

    if not best:
        return [_graphic_fit_text(draw, "...", fnt, max_width)]

    sentence_boundary = _graphic_last_sentence_boundary(best)
    if sentence_boundary >= 90:
        return _graphic_wrap_text(
            draw, best[: sentence_boundary + 1], fnt, max_width, max_lines=max_lines
        )

    clipped_words = best.rstrip(",;:").split()
    while (
        len(clipped_words) > 1
        and clipped_words[-1].strip(".,;:").lower() in _GRAPHIC_DANGLING_READ_WORDS
    ):
        clipped_words.pop()
    clipped = " ".join(clipped_words).rstrip(",;:")
    lines = _graphic_wrap_text(draw, clipped, fnt, max_width, max_lines=max_lines)
    if not lines:
        return []
    last = lines[-1].rstrip(".")
    while last and _graphic_text_width(draw, last + "...", fnt) > max_width:
        parts = last.split()
        last = " ".join(parts[:-1]) if len(parts) > 1 else last[:-1].rstrip()
    lines[-1] = f"{last.rstrip(',;:')}..." if last else "..."
    return lines[:max_lines]


def _graphic_stat_value(value, key):
    if not isinstance(value, (int, float)):
        return str(value or "")
    if key in {"avg", "obp", "slg", "ops", "iso"}:
        return f"{value:.3f}"
    if key in {"k_pct", "bb_pct", "k_bb_pct"}:
        return f"{value:.1f}%"
    if key in {"era", "whip", "k_per_9", "bb_per_9"}:
        return f"{value:.2f}"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _graphic_prose_stat(value, key):
    if not isinstance(value, (int, float)):
        return None
    text = _graphic_stat_value(value, key)
    if key in {"avg", "obp", "slg", "ops", "iso"} and text.startswith("0."):
        return text[1:]
    return text


def _graphic_ordinal(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return ""
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _graphic_join(parts):
    parts = [part for part in parts if part]
    if len(parts) <= 1:
        return parts[0] if parts else ""
    if len(parts) == 2:
        return f"{parts[0]} and {parts[1]}"
    return f"{', '.join(parts[:-1])}, and {parts[-1]}"


def _graphic_level_phrase(row):
    labels = {
        "A": "Single-A",
        "A+": "High-A",
        "AA": "Double-A",
        "AAA": "Triple-A",
        "MLB": "the majors",
    }
    if getattr(row, "is_prospect", False) and row.level == "MLB":
        if row.age is not None:
            return f"At {row.age}, on the latest MiLB sample"
        return "On the latest MiLB sample"
    level = labels.get(row.level, row.level)
    if row.age is not None and level:
        return f"At {row.age} in {level}"
    if row.age is not None:
        return f"At {row.age}"
    if level:
        return f"In {level}"
    return "In the current sample"


def _graphic_sample_phrase(row, context, line):
    sample = context.get("stat_line_sample")
    unit = context.get("stat_line_sample_unit")
    if not isinstance(sample, (int, float)) or not unit:
        if isinstance(line.get("pa"), (int, float)):
            sample, unit = line["pa"], "PA"
        elif isinstance(line.get("ip"), (int, float)):
            sample, unit = line["ip"], "IP"
    if not isinstance(sample, (int, float)) or not unit:
        return ""
    number = str(int(sample)) if float(sample).is_integer() else f"{float(sample):.1f}"
    return f" over {number} {unit}"


def _graphic_sample_context_label(row, context):
    label = getattr(row, "sample_context_label", None)
    if label:
        return str(label)
    sample = context.get("stat_line_sample")
    unit = context.get("stat_line_sample_unit")
    if not isinstance(sample, (int, float)) or not unit:
        return ""
    number = str(int(sample)) if float(sample).is_integer() else f"{float(sample):.1f}"
    level = context.get("stat_line_level") or getattr(row, "level", None)
    current = f"Current {level}: {number} {unit}" if level else f"Current sample: {number} {unit}"
    return current


def _graphic_context_sample_season(context):
    try:
        return int(float(context.get("stat_line_sample_season")))
    except (TypeError, ValueError):
        return None


def _graphic_updated_year(row):
    candidates = [
        getattr(row, "updated_at", None),
        getattr(row, "metadata", {}).get("updated_at") if isinstance(getattr(row, "metadata", None), dict) else None,
        getattr(row, "metadata", {}).get("last_updated") if isinstance(getattr(row, "metadata", None), dict) else None,
        dd_store.generated_at,
    ]
    for candidate in candidates:
        text = str(candidate or "")[:4]
        if text.isdigit():
            return int(text)
    return None


def _graphic_availability_status(row):
    context = getattr(row, "availability_context", {})
    if isinstance(context, dict):
        return str(context.get("status") or "").lower()
    return ""


def _graphic_availability_badge(row):
    """Short caution label for genuine availability risks; None otherwise.

    Only injured / inactive get a share-card badge — thin-sample is a data
    caveat already shown via the sample-context line, not an availability flag.
    """
    return {"injured": "INJURED", "stale_or_inactive": "INACTIVE"}.get(
        _graphic_availability_status(row)
    )


def _graphic_stale_stat_context(row, context):
    sample_season = _graphic_context_sample_season(context)
    updated_year = _graphic_updated_year(row)
    return (
        context.get("stat_line_source_kind") == "latest_milb_history"
        or (
            sample_season is not None
            and updated_year is not None
            and sample_season < updated_year
        )
    )


def _graphic_read_intro(row, last, core, sample, context):
    level_phrase = _graphic_level_phrase(row)
    sample_season = _graphic_context_sample_season(context)
    sample_label = f"{sample_season} MiLB sample" if sample_season else "latest MiLB sample"
    stale = _graphic_stale_stat_context(row, context)
    injured = _graphic_availability_status(row) == "injured"
    if injured and stale:
        return f"{level_phrase}, {last} is currently injured; this read leans on the {sample_label}: {core}{sample}."
    if injured:
        return f"{level_phrase}, {last} is currently injured, so availability is a real risk; he has {core}{sample}."
    if stale:
        return f"{level_phrase}, {last} has no current stat line; this read leans on the {sample_label}: {core}{sample}."
    return f"{level_phrase}, {last} has put up {core}{sample}."


def _graphic_last_name(name):
    parts = str(name or "").split()
    return parts[-1] if parts else "This profile"


def _graphic_hitter_callout(key, line, pct):
    value = _graphic_prose_stat(line.get(key), key)
    if value is None or pct is None:
        return None
    ord_pct = _graphic_ordinal(pct)
    if key == "ops":
        return f"{value} OPS ({ord_pct} percentile)"
    if key == "iso":
        return f"{value} ISO ({ord_pct} percentile)"
    if key == "k_pct":
        return f"{value} K rate ({ord_pct} percentile contact)"
    if key == "bb_pct":
        return f"{value} walk rate ({ord_pct} percentile)"
    if key == "avg":
        return f"{value} AVG ({ord_pct} percentile)"
    if key == "obp":
        return f"{value} OBP ({ord_pct} percentile)"
    if key == "slg":
        return f"{value} SLG ({ord_pct} percentile)"
    return None


def _graphic_pitcher_callout(key, line, pct):
    value = _graphic_prose_stat(line.get(key), key)
    if value is None or pct is None:
        return None
    ord_pct = _graphic_ordinal(pct)
    if key == "k_per_9":
        return f"{value} K/9 ({ord_pct} percentile bat-missing)"
    if key == "bb_per_9":
        return f"{value} BB/9 ({ord_pct} percentile command)"
    if key == "k_bb_pct":
        return f"{value} K-BB% ({ord_pct} percentile)"
    if key == "era":
        return f"{value} ERA ({ord_pct} percentile)"
    if key == "whip":
        return f"{value} WHIP ({ord_pct} percentile)"
    return None


def _graphic_best_single_read(best_line, best_level, stat_percentiles, last):
    """Read off the best single-level 2026 sample when the current level is too thin."""
    role_is_pitcher = any(
        key in best_line for key in ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct")
    )
    unit = "IP" if role_is_pitcher else "PA"
    sample = best_line.get("sample")
    if role_is_pitcher:
        era = _graphic_prose_stat(best_line.get("era"), "era")
        whip = _graphic_prose_stat(best_line.get("whip"), "whip")
        core = " / ".join(
            part for part in (f"{era} ERA" if era else None, f"{whip} WHIP" if whip else None) if part
        ) or "a steady arm shape"
        keys = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
        callouts = [
            _graphic_pitcher_callout(key, best_line, stat_percentiles.get(key))
            for key in keys
            if isinstance(stat_percentiles.get(key), int) and stat_percentiles[key] >= 70
        ][:3]
    else:
        avg = _graphic_prose_stat(best_line.get("avg"), "avg")
        obp = _graphic_prose_stat(best_line.get("obp"), "obp")
        slg = _graphic_prose_stat(best_line.get("slg"), "slg")
        if avg and obp and slg:
            core = f"a {avg}/{obp}/{slg} line"
        else:
            ops = _graphic_prose_stat(best_line.get("ops"), "ops")
            core = f"a {ops} OPS" if ops else "a steady bat shape"
        keys = ("ops", "iso", "k_pct", "avg", "obp", "slg", "bb_pct")
        callouts = [
            _graphic_hitter_callout(key, best_line, stat_percentiles.get(key))
            for key in keys
            if isinstance(stat_percentiles.get(key), int) and stat_percentiles[key] >= 70
        ][:3]
    loud = f" He's carrying {_graphic_join(callouts)}." if callouts else ""
    return (
        f"{last}'s current level is a thin sample, so this reads off the best 2026 look: "
        f"{best_level} over {sample} {unit}, where he put up {core}.{loud}"
    )


def _prospect_player_card_read(row, stat_percentiles, context, scouting_report=None):
    scouting_text = _scouting_display_report_text(scouting_report)
    if scouting_text:
        return scouting_text
    line = row.stat_line or {}
    if not line:
        return prospect_percentiles.identity_line(row, stat_percentiles) or ""

    last = _graphic_last_name(row.name)
    card_stat_line, best_level, is_best = prospect_percentiles.card_line(row)
    if is_best and card_stat_line:
        return _graphic_best_single_read(card_stat_line, best_level, stat_percentiles, last)
    sample = _graphic_sample_phrase(row, context, line)
    if any(key in line for key in ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct")):
        era = _graphic_prose_stat(line.get("era"), "era")
        whip = _graphic_prose_stat(line.get("whip"), "whip")
        k9 = _graphic_prose_stat(line.get("k_per_9"), "k_per_9")
        core = " / ".join(part for part in (f"{era} ERA" if era else None, f"{whip} WHIP" if whip else None) if part)
        if not core and k9:
            core = f"{k9} K/9"
        intro = _graphic_read_intro(
            row,
            last,
            core or "a current arm shape",
            sample,
            context,
        )
        strength_keys = ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
        strengths = [
            _graphic_pitcher_callout(key, line, stat_percentiles.get(key))
            for key in strength_keys
            if isinstance(stat_percentiles.get(key), int) and stat_percentiles[key] >= 70
        ][:3]
        if not stat_percentiles:
            loud = "The sample is too small to read the skill shape yet."
        else:
            loud = f"He's carrying {_graphic_join(strengths)}." if strengths else "The shape is more steady than loud."
        weak_key = min(
            (key for key in strength_keys if isinstance(stat_percentiles.get(key), int)),
            key=lambda key: stat_percentiles[key],
            default=None,
        )
        weak = ""
        if weak_key and stat_percentiles[weak_key] <= 40:
            weak = f" The drag is {_graphic_pitcher_callout(weak_key, line, stat_percentiles[weak_key])}, which still caps the role projection."
        return f"{intro} {loud}{weak}"

    avg = _graphic_prose_stat(line.get("avg"), "avg")
    obp = _graphic_prose_stat(line.get("obp"), "obp")
    slg = _graphic_prose_stat(line.get("slg"), "slg")
    if avg and obp and slg:
        core = f"a {avg}/{obp}/{slg} line"
    else:
        ops = _graphic_prose_stat(line.get("ops"), "ops")
        core = f"a {ops} OPS" if ops else "a current bat shape"
    intro = _graphic_read_intro(row, last, core, sample, context)
    strength_keys = ("ops", "iso", "k_pct", "avg", "obp", "slg", "bb_pct")
    strengths = [
        _graphic_hitter_callout(key, line, stat_percentiles.get(key))
        for key in strength_keys
        if isinstance(stat_percentiles.get(key), int) and stat_percentiles[key] >= 70
    ][:3]
    if not stat_percentiles:
        loud = "The sample is too small to read the skill shape yet."
    else:
        loud = f"He's carrying {_graphic_join(strengths)}." if strengths else "The shape is more solid than explosive."
    weak_key = min(
        (key for key in strength_keys if isinstance(stat_percentiles.get(key), int)),
        key=lambda key: stat_percentiles[key],
        default=None,
    )
    weak = ""
    if weak_key and stat_percentiles[weak_key] <= 40:
        weak = f" The check is the {_graphic_hitter_callout(weak_key, line, stat_percentiles[weak_key])}, which keeps this short of a clean everyday read."
    return f"{intro} {loud}{weak}"


def _prospect_player_card_png(row):
    """Render a single-prospect share card from ValuCast-owned current context."""
    from PIL import Image, ImageDraw

    stat_percentiles = prospect_percentiles.card_percentiles(prospect_pool, row)
    profile_bars = prospect_percentiles.profile_bars(row, stat_percentiles)
    skill_grades = prospect_percentiles.skill_grades(row, stat_percentiles)
    peak_shape = tuple(getattr(row, "peak_shape_items", ()) or ())
    shape_items = peak_shape or skill_grades
    shape_title = "PROJECTED PEAK SHAPE" if peak_shape else "CURRENT SKILL SHAPE"
    pool_label = prospect_percentiles.pool_label(row)
    fg_scouting = fg_fv.get(getattr(row, "mlbam_id", None))
    context = getattr(row, "context", None)
    if not isinstance(context, dict):
        context = row.metadata.get("context") if isinstance(row.metadata, dict) else {}
    if not isinstance(context, dict):
        context = {}
    scouting_report = _artifact_context_for_row(row).get("scouting_report")
    identity = _prospect_player_card_read(
        row, stat_percentiles, context, scouting_report=scouting_report
    )

    width, height = 1080, 1350
    bg = _GRAPHIC_PALETTE["bg"]
    card = _GRAPHIC_PALETTE["card"]
    card_2 = _GRAPHIC_PALETTE["card_2"]
    border = _GRAPHIC_PALETTE["border"]
    green = _GRAPHIC_PALETTE["green"]
    amber = (251, 191, 36)
    # ValuCast ramp — matches the site percentile bars: teal = elite, slate = average, clay = low.
    bar_elite = green
    bar_mid = _GRAPHIC_PALETTE["slate"]
    bar_low = _GRAPHIC_PALETTE["clay"]
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)

    subtitle = "player skill percentiles + peak projection context"
    generated = _editorial_date(dd_store.generated_at)
    if generated:
        subtitle = f"{subtitle} - {generated}"
    _graphic_header(img, draw, headline="AHEAD OF THE CURVE", subtitle=subtitle)

    # Identity row — flat panel, name leads (no monogram). Value folds into an
    # app-style faint-teal chip (label over number), not a separate boxed module.
    draw.rounded_rectangle((48, 218, 1032, 410), radius=10, fill=card, outline=border, width=1)

    name_font = _graphic_font(48, bold=True)
    draw.text((74, 250), _graphic_fit_text(draw, row.name, name_font, 600), fill=text, font=name_font)
    meta = " - ".join(
        piece for piece in [
            row.team or "FA",
            "/".join(row.positions[:2]) if row.positions else "UT",
            row.level or "PRO",
            f"Age {row.age}" if row.age is not None else "",
        ]
        if piece
    )
    draw.text((76, 314), _graphic_fit_text(draw, meta, _graphic_font(22, mono=True), 600), fill=muted, font=_graphic_font(22, mono=True))
    draw.text((76, 350), _graphic_fit_text(draw, pool_label, _graphic_font(18, mono=True), 600), fill=muted, font=_graphic_font(18, mono=True))

    draw.rounded_rectangle((806, 250, 984, 360), radius=8, fill=(14, 29, 30), outline=(20, 59, 55), width=1)
    draw.text((824, 266), "VALUCAST VALUE", fill=muted, font=_graphic_font(13, bold=True))
    draw.text((824, 286), f"{row.dynasty_value:.1f}", fill=green, font=_graphic_font(38, bold=True, mono=True))
    rank_text = f"P#{row.prospect_rank}" if row.prospect_rank is not None else f"#{row.dynasty_rank}"
    draw.text((824, 332), rank_text, fill=muted, font=_graphic_font(16, bold=True, mono=True))

    avail_badge = _graphic_availability_badge(row)
    if avail_badge:
        badge_font = _graphic_font(15, bold=True)
        bbox = draw.textbbox((0, 0), avail_badge, font=badge_font)
        draw.rounded_rectangle(
            (76, 378, 76 + (bbox[2] - bbox[0]) + 24, 404),
            radius=6,
            fill=(46, 36, 28),
            outline=(150, 110, 78),
            width=1,
        )
        draw.text((88, 382), avail_badge, fill=amber, font=badge_font)

    # Skill bars
    draw.rounded_rectangle((48, 438, 1032, 812), radius=10, fill=card, outline=border, width=1)
    draw.text((74, 468), "CURRENT SKILL PERCENTILES", fill=muted, font=_graphic_font(20, bold=True))
    sample_context = _graphic_sample_context_label(row, context)
    if sample_context:
        draw.text((74, 500), _graphic_fit_text(draw, sample_context, _graphic_font(17, bold=True), 890), fill=muted, font=_graphic_font(17, bold=True))

    y = 542
    if profile_bars:
        for item in profile_bars[:7]:
            pct = int(item["percentile"])
            label = item["label"]
            value = _graphic_stat_value(item["value"], item["key"])
            draw.text((82, y + 6), label, fill=muted, font=_graphic_font(18, bold=True))
            x0, y0, x1, y1 = 190, y + 9, 762, y + 23
            draw.rounded_rectangle((x0, y0, x1, y1), radius=4, fill=(30, 32, 40))
            fill = bar_elite if pct >= 75 else bar_mid if pct > 25 else bar_low
            draw.rounded_rectangle((x0, y0, x0 + int((x1 - x0) * pct / 100), y1), radius=4, fill=fill)
            knob_x = max(x0 + 14, min(x1 - 14, x0 + int((x1 - x0) * pct / 100)))
            draw.rounded_rectangle((knob_x - 18, y0 - 3, knob_x + 18, y1 + 3), radius=4, fill=(10, 11, 15))
            draw.text((knob_x - 10, y0 - 2), str(pct), fill=text, font=_graphic_font(14, bold=True))
            draw.text((792, y + 1), value, fill=text, font=_graphic_font(20, bold=True, mono=True))
            y += 39
    else:
        draw.text((74, 560), "Current sample does not meet the percentile-pool threshold.", fill=muted, font=_graphic_font(22))

    # Narrative + 20-80 shape
    draw.rounded_rectangle((48, 840, 1032, 1132), radius=10, fill=card, outline=border, width=1)
    draw.text((74, 870), "THE VALUCAST READ", fill=muted, font=_graphic_font(20, bold=True))
    read_font = _graphic_font(22)
    for idx, line in enumerate(_graphic_wrap_read_text(draw, identity, read_font, 890, max_lines=4)):
        draw.text((74, 910 + idx * 31), line, fill=text, font=read_font)

    draw.text((74, 1040), shape_title, fill=muted, font=_graphic_font(18, bold=True))
    for idx, skill in enumerate(shape_items[:4]):
        x = 74 + idx * 235
        draw.rounded_rectangle((x, 1068, x + 205, 1114), radius=10, fill=card_2, outline=(44, 46, 54), width=1)
        grade = int(skill["grade"])
        color = bar_elite if grade >= 60 else bar_low if grade <= 40 else text
        draw.text((x + 14, 1078), _graphic_fit_text(draw, skill["label"], _graphic_font(15, bold=True), 120), fill=muted, font=_graphic_font(15, bold=True))
        draw.text((x + 150, 1075), str(grade), fill=color, font=_graphic_font(25, bold=True))
        draw.text((x + 14, 1096), _graphic_fit_text(draw, skill["metrics"], _graphic_font(12), 132), fill=muted, font=_graphic_font(12))

    # FanGraphs scouting reference -- FV + key tool grades, display-only (never in
    # ValuCast value/rank). Neutral color marks it as the scouts' read, not ours.
    # Skipped when the player has no FG board entry.
    if fg_scouting and fg_scouting.get("fv"):
        draw.rounded_rectangle((48, 1146, 1032, 1272), radius=10, fill=card, outline=border, width=1)
        draw.text((74, 1160), "FANGRAPHS SCOUTING - FV 20-80 - scouting reference, not in ValuCast value",
                  fill=muted, font=_graphic_font(14, bold=True))
        draw.text((74, 1186), f"FV {fg_scouting['fv']}", fill=text, font=_graphic_font(40, bold=True))
        org = fg_scouting.get("org")
        org_rk = fg_scouting.get("fg_org_rank")
        if org:
            org_label = f"{org}" + (f" - org #{int(org_rk)}" if org_rk else "")
            draw.text((74, 1238), org_label, fill=muted, font=_graphic_font(16, mono=True))
        hit_g = fg_scouting.get("hit_grades") or {}
        pit_g = fg_scouting.get("pitch_grades") or {}
        if hit_g:
            tools = [("HIT", hit_g.get("Hit")), ("GAME PWR", hit_g.get("Game Pwr")),
                     ("RAW PWR", hit_g.get("Raw Pwr")), ("SPD", hit_g.get("Spd")), ("FLD", hit_g.get("Fld"))]
        else:
            tools = [("FB", pit_g.get("FB")), ("SL", pit_g.get("SL")), ("CB", pit_g.get("CB")),
                     ("CH", pit_g.get("CH")), ("CMD", pit_g.get("CMD"))]
        tx = 290
        for label, val in tools:
            if not val:
                continue
            draw.text((tx, 1184), label, fill=muted, font=_graphic_font(13, bold=True))
            draw.text((tx, 1204), str(val), fill=text, font=_graphic_font(19, bold=True, mono=True))
            tx += 150

    source = (
        "Current bars use ValuCast-owned MiLB stats. Peak shape is role context, not public scouting grades."
        if peak_shape
        else "Stats from ValuCast-owned MiLB context. Skill shape is percentile-derived, not sourced scouting grades."
    )
    _graphic_footer(draw, right_note=source)

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
        "as_of": dd_store.generated_at or store.as_of,
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
            tier_counts = Counter(t for _, t in tiers_list)

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
        ctx["snapshot_stale"] = dynasty_data_source == "valucast_public_snapshot_stale"
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
        for name in ("cats", "pcats", "rank_by", "preset"):
            values = request.args.getlist(name)
            if values:
                params[name] = (
                    ",".join(parse_list(values))
                    if name in ("cats", "pcats")
                    else values[0]
                )
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


@app.route("/front-office")
def front_office_report():
    path = Path(__file__).parent / "data" / "models" / "valucast_front_office_report.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        report = None
    return render_template("front_office.html", report=report)


_ARTIFACT_CACHE: dict[Path, tuple[int, dict | None]] = {}


def _load_artifact(path: Path) -> dict | None:
    try:
        stamp = path.stat().st_mtime_ns
    except OSError:
        return None
    cached = _ARTIFACT_CACHE.get(path)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _ARTIFACT_CACHE[path] = (stamp, None)
        return None
    payload = payload if isinstance(payload, dict) else None
    _ARTIFACT_CACHE[path] = (stamp, payload)
    return payload


def _artifact_ready(payload: dict | None, *keys: str) -> bool:
    if not payload:
        return False
    if not keys:
        return True
    cursor = payload
    for key in keys:
        if not isinstance(cursor, dict):
            return False
        cursor = cursor.get(key)
    return bool(cursor)


def _artifact_date(payload: dict | None) -> str | None:
    raw = (payload or {}).get("generated_at") or (payload or {}).get("as_of")
    return str(raw)[:10] if raw else None


@app.route("/intelligence")
def intelligence_hub():
    root = Path(__file__).parent
    models = root / "data" / "models"
    quality = _load_artifact(models / "valucast_quality_governor.json")
    repository = _load_artifact(models / "valucast_scouting_reports.json")
    recent_signal = _load_artifact(models / "valucast_recent_signal_report.json")
    card_audit = _load_artifact(models / "valucast_prospect_card_data_audit.json")
    role_tracker = _load_artifact(models / "valucast_playing_time_role_tracker.json")
    hp_sanity = _load_artifact(models / "valucast_hp_promotion_sanity_report.json")
    peak_calibration = _load_artifact(
        models / "valucast_prospect_peak_projection_calibration.json"
    )
    front_office = _load_artifact(models / "valucast_front_office_report.json")
    pipeline = (
        (front_office or {}).get("operations_watchlist", {}).get("pipeline_observability")
        if isinstance((front_office or {}).get("operations_watchlist"), dict)
        else {}
    )

    lanes = [
        {
            "name": "Scouting Reports",
            "status": "Ready" if _artifact_ready(repository, "validation", "ready_for_repository") else "Next build",
            "kicker": "player intelligence",
            "copy": (
                "Searchable stat-grounded prospect reads, peak notes, confidence labels, "
                "and player-card links in one scouting surface."
            ),
            "metric": f"{((repository or {}).get('summary') or {}).get('report_count', 0)} reports",
            "href": "/scouting",
            "cta": "Open reports",
        },
        {
            "name": "Player Card V2 Visuals",
            "status": "Live" if _artifact_ready(repository) else "Next build",
            "kicker": "cards and share graphics",
            "copy": (
                "Cards now center the ValuCast read, current percentiles, peak outlook, "
                "confidence context, and shareable visual summaries."
            ),
            "metric": "card v2",
            "href": "/?mode=prospects",
            "cta": "Open cards",
        },
        {
            "name": "Recent Signals",
            "status": "Ready" if _artifact_ready(recent_signal, "validation", "ready_for_recent_signal") else "Collecting",
            "kicker": "why now",
            "copy": (
                "ValuCast archives now publish score and rank movement context, "
                "so buy graphics and reports can show who is actually moving."
            ),
            "metric": (
                f"{((recent_signal or {}).get('summary') or {}).get('top_mover_count', 0)} movers"
            ),
            "href": "/scouting",
            "cta": "See signals",
        },
        {
            "name": "Prospect Peak Projection V2",
            "status": "Ready" if _artifact_ready(peak_calibration, "validation", "ready_for_review") else "Collecting",
            "kicker": "role and ceiling context",
            "copy": (
                "Current skill shape is paired with peak role, floor, risk, confidence, "
                "and bucket watch items without moving the live rank by hand."
            ),
            "metric": (
                f"{((peak_calibration or {}).get('summary') or {}).get('bucket_count', 0)} buckets"
            ),
            "href": "/?mode=prospects",
            "cta": "View prospects",
        },
        {
            "name": "League Tools",
            "status": "Live",
            "kicker": "custom values",
            "copy": (
                "Dynasty customization, league import, Category Fit, Value Map, Buys, "
                "and CSV export are the bridge from model output to league decisions."
            ),
            "metric": "custom league settings",
            "href": "/?mode=dd_dynasty",
            "cta": "Customize values",
        },
        {
            "name": "Launch Stability",
            "status": "Ready" if _artifact_ready(quality, "ready_for_public_snapshot") else "Next build",
            "kicker": "publish checks",
            "copy": (
                "Daily publish checks watch freshness, identity coverage, board shape, "
                "Buys readiness, and stale stat context before the public surfaces move."
            ),
            "metric": (quality or {}).get("status", "unavailable").replace("_", " ").title(),
            "href": "/front-office",
            "cta": "View front-office track",
        },
        {
            "name": "Player Card Health",
            "status": "Ready" if _artifact_ready(card_audit, "validation", "ready_for_cards") else "Needs review",
            "kicker": "card coverage",
            "copy": (
                "Prospect cards get a daily identity, level, stat-context, "
                "graduation, and peak-projection audit before they publish."
            ),
            "metric": (
                f"{((card_audit or {}).get('metrics') or {}).get('top200_count', 0)} top-200 checked"
            ),
            "href": "/scouting",
            "cta": "Review card health",
        },
        {
            "name": "Playing-Time / Role Tracker",
            "status": "Ready" if _artifact_ready(role_tracker, "validation", "ready_for_role_context") else "Next build",
            "kicker": "MLB role context",
            "copy": (
                "Official MLB ID role profiles separate active roster status, injury risk, "
                "projected volume, and role basis from the value score."
            ),
            "metric": (
                f"{((role_tracker or {}).get('summary') or {}).get('profile_count', 0)} profiles"
            ),
            "href": "/scouting",
            "cta": "See role mix",
        },
        {
            "name": "MLB Projection Track",
            "status": "Opt-in" if _artifact_ready(hp_sanity, "validation", "ready_for_opt_in_source") else "Building",
            "kicker": "projection evidence",
            "copy": (
                "The ValuCast Hitter + Pitcher source stays opt-in while the methodology "
                "page publishes the held-out scorecard and what has not been proven yet."
            ),
            "metric": "ValuCast Hitter + Pitcher v1",
            "href": "/methodology",
            "cta": "Read methodology",
        },
    ]
    readiness = {
        "quality_date": _artifact_date(quality),
        "repository_date": _artifact_date(repository),
        "recent_signal_date": _artifact_date(recent_signal),
        "card_audit_date": _artifact_date(card_audit),
        "role_tracker_date": _artifact_date(role_tracker),
        "pipeline_ready": bool(pipeline.get("ready_for_daily_publication")),
        "pipeline_expected_date": pipeline.get("expected_date"),
        "front_office_grade": ((front_office or {}).get("overall") or {}).get("grade"),
        "front_office_score": ((front_office or {}).get("overall") or {}).get("score"),
        "default_projection_source": ((hp_sanity or {}).get("promotion") or {}).get(
            "default_source", "steamer"
        ),
    }
    return render_template(
        "intelligence.html",
        intelligence_page=True,
        lanes=lanes,
        readiness=readiness,
        as_of=readiness["quality_date"] or readiness["repository_date"],
    )


def _identity_key(mlbam_id, role) -> str | None:
    if mlbam_id in (None, "") or role in (None, ""):
        return None
    return f"{mlbam_id}_{str(role).lower()}"


def _row_identity_key(row) -> str | None:
    return _identity_key(getattr(row, "mlbam_id", None), getattr(row, "role", None))


def _format_context_label(value) -> str | None:
    if value in (None, ""):
        return None
    return str(value).replace("_", " ").title()


def _valid_scouting_llm_text(report: dict | None) -> str | None:
    if not isinstance(report, dict):
        return None
    llm = report.get("report_llm")
    if not isinstance(llm, dict) or llm.get("valid") is not True:
        return None
    text = str(llm.get("text") or "").strip()
    return text or None


def _scouting_display_report_text(report: dict | None) -> str:
    """Public scouting text, with valid LLM reports promoted and deterministic fallback."""
    if not isinstance(report, dict):
        return ""
    published = str(report.get("published_report") or "").strip()
    if published:
        return published
    llm_text = _valid_scouting_llm_text(report)
    if llm_text:
        return llm_text
    return str(report.get("report") or "").strip()


def _scouting_display_report(report: dict | None) -> dict | None:
    if not isinstance(report, dict):
        return None
    item = dict(report)
    item["display_report"] = _scouting_display_report_text(item)
    if str(item.get("published_report_source") or "").strip():
        item["display_report_source"] = str(item["published_report_source"]).strip()
    elif _valid_scouting_llm_text(item):
        item["display_report_source"] = "llm"
    else:
        item["display_report_source"] = "deterministic"
    return item


def _indexed_artifact_rows(payload: dict | None, rows_key: str) -> dict[str, dict]:
    rows = (payload or {}).get(rows_key) or []
    indexed = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = row.get("identity_key") or _identity_key(row.get("mlbam_id"), row.get("role"))
        if key and key not in indexed:
            indexed[str(key)] = row
    return indexed


def _artifact_context_for_row(row) -> dict:
    key = _row_identity_key(row)
    if not key:
        return {}
    root = Path(__file__).parent / "data" / "models"
    scouting = _indexed_artifact_rows(
        _load_artifact(root / "valucast_scouting_reports.json"), "reports"
    ).get(key)
    scouting = _scouting_display_report(scouting)
    recent_signal = _indexed_artifact_rows(
        _load_artifact(root / "valucast_recent_signal_report.json"), "signals"
    ).get(key)
    recent_form = (
        (_load_artifact(root / "valucast_recent_form_signal.json") or {}).get("by_identity") or {}
    ).get(key)
    call_up = (
        (_load_artifact(root / "valucast_call_up_pulse.json") or {}).get("by_identity") or {}
    ).get(key)
    card_data_status = _indexed_artifact_rows(
        _load_artifact(root / "valucast_prospect_card_data_audit.json"), "cards"
    ).get(key)
    role_profile = _indexed_artifact_rows(
        _load_artifact(root / "valucast_playing_time_role_tracker.json"), "profiles"
    ).get(key)
    if role_profile:
        role_profile = dict(role_profile)
        role_profile["projected_role_label"] = _format_context_label(
            role_profile.get("projected_role")
        )
        role_profile["availability_status_label"] = _format_context_label(
            role_profile.get("availability_status")
        )
    return {
        "scouting_report": scouting,
        "recent_signal": recent_signal,
        "recent_form": recent_form,
        "call_up": call_up,
        "card_data_status": card_data_status,
        "role_profile": role_profile,
    }


@app.route("/scouting")
def scouting_reports():
    repository = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_scouting_reports.json"
    )
    role_tracker = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_playing_time_role_tracker.json"
    )
    hp_sanity = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_hp_promotion_sanity_report.json"
    )
    peak_calibration = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_prospect_peak_projection_calibration.json"
    )
    recent_signal = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_recent_signal_report.json"
    )
    card_audit = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_prospect_card_data_audit.json"
    )
    reports = list((repository or {}).get("reports") or [])
    reports.sort(
        key=lambda row: (
            int(row.get("prospect_rank") or 999999),
            str(row.get("name") or ""),
        )
    )
    filters = {
        "q": (request.args.get("q") or "").strip(),
        "team": (request.args.get("team") or "").strip().upper(),
        "role": (request.args.get("role") or "").strip().lower(),
        "status": (request.args.get("status") or "").strip().lower(),
    }
    teams = sorted({str(row.get("team") or "") for row in reports if row.get("team")})
    roles = sorted({str(row.get("role") or "") for row in reports if row.get("role")})
    statuses = sorted(
        {str(row.get("report_status") or "") for row in reports if row.get("report_status")}
    )
    if filters["q"]:
        needle = filters["q"].lower()
        reports = [
            row for row in reports
            if needle in str(row.get("name") or "").lower()
            or needle in str(row.get("team") or "").lower()
            or needle in " ".join(str(p) for p in row.get("positions") or ()).lower()
        ]
    if filters["team"]:
        reports = [row for row in reports if str(row.get("team") or "").upper() == filters["team"]]
    if filters["role"]:
        reports = [row for row in reports if str(row.get("role") or "").lower() == filters["role"]]
    if filters["status"]:
        reports = [
            row for row in reports
            if str(row.get("report_status") or "").lower() == filters["status"]
        ]
    report_rows = []
    for row in reports[:60]:
        item = dict(row)
        item["display_report"] = _scouting_display_report_text(item)
        item["display_report_source"] = (
            item.get("published_report_source")
            or ("llm" if _valid_scouting_llm_text(item) else "deterministic")
        )
        confidence = item.get("confidence")
        if isinstance(confidence, dict):
            item["confidence_label"] = _format_context_label(confidence.get("level"))
        else:
            item["confidence_label"] = _format_context_label(confidence)
        source_fields = item.get("source_fields")
        if not isinstance(source_fields, dict):
            source_fields = {}
        sample = source_fields.get("stat_line_sample")
        sample_unit = source_fields.get("stat_line_sample_unit")
        if isinstance(sample, float) and sample.is_integer():
            sample = int(sample)
        item["sample_label"] = (
            f"{sample} {sample_unit}" if sample not in (None, "") and sample_unit else None
        )
        item["player_url"] = "/?" + urlencode(
            {"mode": "prospects", "search": item.get("name") or ""}
        )
        item["status_label"] = _format_context_label(item.get("report_status"))
        recent_context = item.get("recent_signal")
        if isinstance(recent_context, dict):
            item["movement_label"] = recent_context.get("movement_label")
            item["buy_rank_label"] = (
                f"B#{recent_context.get('buy_rank')}"
                if recent_context.get("buy_rank") not in (None, "")
                else None
            )
        card_context = item.get("card_data_status")
        if isinstance(card_context, dict):
            item["card_status_label"] = _format_context_label(card_context.get("status"))
        report_rows.append(item)
    role_counts = ((role_tracker or {}).get("summary") or {}).get("role_counts") or {}
    role_rows = [
        {"role": str(role).replace("_", " ").title(), "count": count}
        for role, count in sorted(role_counts.items(), key=lambda item: (-item[1], item[0]))
    ][:10]
    return render_template(
        "scouting.html",
        scouting_page=True,
        repository=repository,
        role_tracker=role_tracker,
        hp_sanity=hp_sanity,
        peak_calibration=peak_calibration,
        recent_signal=recent_signal,
        card_audit=card_audit,
        reports=report_rows,
        filters=filters,
        teams=teams,
        roles=roles,
        statuses=statuses,
        filtered_count=len(reports),
        role_rows=role_rows,
        as_of=(repository or {}).get("generated_at"),
    )


_TEAM_BOARD_ORG_ALIASES = {
    "KCR": "KC",
}
_TEAM_BOARD_EXCLUDED_ORGS = {"FA"}
_TEAM_BOARD_ORG_NAMES = {
    "ARI": "Arizona Diamondbacks",
    "ATH": "Athletics",
    "ATL": "Atlanta Braves",
    "BAL": "Baltimore Orioles",
    "BOS": "Boston Red Sox",
    "CHC": "Chicago Cubs",
    "CHW": "Chicago White Sox",
    "CIN": "Cincinnati Reds",
    "CLE": "Cleveland Guardians",
    "COL": "Colorado Rockies",
    "DET": "Detroit Tigers",
    "HOU": "Houston Astros",
    "KC": "Kansas City Royals",
    "LAA": "Los Angeles Angels",
    "LAD": "Los Angeles Dodgers",
    "MIA": "Miami Marlins",
    "MIL": "Milwaukee Brewers",
    "MIN": "Minnesota Twins",
    "NYM": "New York Mets",
    "NYY": "New York Yankees",
    "PHI": "Philadelphia Phillies",
    "PIT": "Pittsburgh Pirates",
    "SDP": "San Diego Padres",
    "SEA": "Seattle Mariners",
    "SFG": "San Francisco Giants",
    "STL": "St. Louis Cardinals",
    "TBR": "Tampa Bay Rays",
    "TEX": "Texas Rangers",
    "TOR": "Toronto Blue Jays",
    "WSN": "Washington Nationals",
}
_TEAM_BOARD_FANTRAX_FILES = (
    Path(__file__).parent / "data" / "prospects" / "raw" / "fantrax" / "Fantrax-Players-Diamond Dynasties-OwnedHitters.csv",
    Path(__file__).parent / "data" / "prospects" / "raw" / "fantrax" / "Fantrax-Players-Diamond Dynasties-OwnedPitchers.csv",
)


def _team_board_normalized_name(name):
    text = str(name or "").strip()
    if not text:
        return ""
    text = text.replace(".", "").replace("'", "").replace("\u2019", "").replace("-", " ")
    return " ".join(text.split()).casefold()


def _canonical_team_board_org(value):
    """Return the MLB org key used for Backfields team boards."""
    if value in (None, ""):
        return None
    org = str(value).strip().upper()
    if not org:
        return None
    org = _TEAM_BOARD_ORG_ALIASES.get(org, org)
    if org in _TEAM_BOARD_EXCLUDED_ORGS:
        return None
    return org


def _team_board_org_name(org):
    return _TEAM_BOARD_ORG_NAMES.get(str(org or "").upper(), str(org or "").upper())


@lru_cache(maxsize=1)
def _team_board_current_roster_org_lookup():
    by_name = {}
    for path in _TEAM_BOARD_FANTRAX_FILES:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                name = _team_board_normalized_name(row.get("Player"))
                org = _canonical_team_board_org(row.get("Team"))
                if name and org:
                    by_name.setdefault(name, set()).add(org)
    return {
        name: next(iter(orgs))
        for name, orgs in by_name.items()
        if len(orgs) == 1
    }


def _team_board_current_roster_org(row):
    return _team_board_current_roster_org_lookup().get(
        _team_board_normalized_name(getattr(row, "name", None))
    )


def _team_board_affiliate_context_is_current(context):
    season = None
    for key in ("stat_line_sample_season", "stat_line_season", "season"):
        try:
            season = int(float(context.get(key)))
            break
        except (TypeError, ValueError):
            continue
    return season is None or season >= date.today().year


def _team_board_context_for(row):
    context = getattr(row, "context", None)
    if isinstance(context, dict):
        return context
    metadata = getattr(row, "metadata", None)
    if isinstance(metadata, dict) and isinstance(metadata.get("context"), dict):
        return metadata["context"]
    return {}


def _team_board_org_for(row):
    """Resolve the current MLB org for a Backfields row.

    The public snapshot and MiLB stat line can each be stale in different ways:
    row.team may lag a trade, while stat_line_team can be an older affiliate
    from historical MiLB context. Prefer the current Fantrax roster org when it
    is uniquely available, then use affiliate and snapshot fallbacks.
    """
    roster_org = _team_board_current_roster_org(row)
    if roster_org:
        return roster_org
    context = _team_board_context_for(row)
    affiliate = str(context.get("stat_line_team") or "").strip()
    if affiliate and _team_board_affiliate_context_is_current(context):
        org = _canonical_team_board_org(MINOR_TEAM_MLB_AFFILIATES.get(affiliate))
        if org:
            return org
    for key in ("mlb_team", "current_org", "org", "parent_org"):
        org = _canonical_team_board_org(context.get(key))
        if org:
            return org
    for attr in ("team", "mlb_team"):
        org = _canonical_team_board_org(getattr(row, attr, None))
        if org:
            return org
    return None


def _team_board_as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _team_board_rank_value(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 10_000_000
    return number if number > 0 else 10_000_000


def _team_board_value(row):
    for attr in ("dynasty_value", "value", "score"):
        number = _team_board_as_float(getattr(row, attr, None))
        if number is not None:
            return number
    return None


def _team_board_fmt_value(value):
    number = _team_board_as_float(value)
    return "-" if number is None else f"{number:.1f}"


def _team_board_role(row):
    context = _team_board_context_for(row)
    role = getattr(row, "role", None) or context.get("role")
    if role:
        return str(role).lower()
    positions = set(getattr(row, "positions", ()) or ())
    return "pitcher" if positions and positions <= {"P", "SP", "RP"} else "hitter"


def _team_board_identity_keys(row):
    keys = []
    identity = _identity_key(getattr(row, "mlbam_id", None), _team_board_role(row))
    if identity:
        keys.append(str(identity))
    mlbam = getattr(row, "mlbam_id", None)
    if mlbam not in (None, ""):
        keys.append(f"mlbam:{mlbam}")
    org = _team_board_org_for(row)
    name = str(getattr(row, "name", "") or "").strip().casefold()
    if name and org:
        keys.append(f"name:{name}|team:{org}")
    return keys


def _team_board_prospect_sort_key(row):
    prospect_rank = _team_board_rank_value(getattr(row, "prospect_rank", None))
    dynasty_rank = _team_board_rank_value(getattr(row, "dynasty_rank", None))
    value = _team_board_value(row)
    name = str(getattr(row, "name", "") or "").casefold()
    return (
        0 if prospect_rank < 10_000_000 else 1,
        prospect_rank,
        dynasty_rank,
        -(value or 0.0),
        name,
    )


def _team_board_prospect_rows(rows=None):
    """Full prospect pool for org boards; intentionally not the public top-200 slice."""
    if rows is None:
        if not dd_store.is_available:
            return []
        rows = dd_store.filter(pool="prospect")
    rows = [
        row for row in rows
        if _team_board_org_for(row) is not None
    ]
    return sorted(rows, key=_team_board_prospect_sort_key)


def _team_board_movements():
    payload = _load_artifact(Path(__file__).parent / "data" / "models" / "valucast_recent_signal_report.json")
    signals = []
    for key in ("signals", "top_movers"):
        signals.extend(row for row in (payload or {}).get(key) or [] if isinstance(row, dict))
    by_key = {}
    for row in signals:
        if row.get("identity_key"):
            by_key[str(row["identity_key"])] = row
        if row.get("mlbam_id") not in (None, ""):
            by_key[f"mlbam:{row['mlbam_id']}"] = row
        org = _canonical_team_board_org(row.get("team"))
        name = str(row.get("name") or "").strip().casefold()
        if name and org:
            by_key[f"name:{name}|team:{org}"] = row
    return by_key


def _team_board_move_from_signal(signal):
    delta = _team_board_as_float((signal or {}).get("rank_delta_7d"))
    if delta is None:
        delta = _team_board_as_float((signal or {}).get("rank_delta"))
    if delta is None or delta == 0:
        return {"direction": "flat", "label": "-", "sort": 0.0}
    label = str(int(abs(delta))) if float(delta).is_integer() else f"{abs(delta):.1f}"
    return {
        "direction": "up" if delta > 0 else "down",
        "label": label,
        "sort": float(delta),
    }


def _team_board_signal_for(row, movements):
    for key in _team_board_identity_keys(row):
        if key in movements:
            return movements[key]
    return None


def _team_board_position(row):
    positions = [str(pos) for pos in (getattr(row, "positions", ()) or ()) if pos]
    return "/".join(positions) if positions else (str(getattr(row, "position", "") or "") or "-")


def _team_board_level(row):
    context = _team_board_context_for(row)
    level = context.get("stat_line_level") or getattr(row, "level", None)
    return str(level or "").strip().upper() or "-"


def _team_board_affiliate(row):
    context = _team_board_context_for(row)
    return str(context.get("stat_line_team") or "").strip()


def _team_board_eta(row):
    eta = getattr(row, "eta", None)
    return f"ETA {eta}" if eta not in (None, "") else ""


def _team_board_player_url(row):
    player_id = getattr(row, "id", None)
    if player_id not in (None, ""):
        return f"/player/{quote(str(player_id), safe='')}?mode=prospects"
    name = str(getattr(row, "name", "") or "").strip()
    return "/?mode=prospects" if not name else "/?" + urlencode({"mode": "prospects", "search": name})


def _team_board_report_url(name):
    clean = " ".join(str(name or "").split())
    return "/scouting" if not clean else "/scouting?" + urlencode({"q": clean})


def _team_board_row(row, org_rank, movements, reports_by_key):
    signal = _team_board_signal_for(row, movements)
    move = _team_board_move_from_signal(signal)
    org = _team_board_org_for(row)
    player_url = _team_board_player_url(row)
    value = _team_board_value(row)
    has_report = any(key in reports_by_key for key in _team_board_identity_keys(row))
    name = getattr(row, "name", None) or "Unknown"
    affiliate = _team_board_affiliate(row)
    return {
        "org_rank": org_rank,
        "name": name,
        "id": str(getattr(row, "id", "") or ""),
        "team": org,
        "team_name": _team_board_org_name(org),
        "position": _team_board_position(row),
        "level": _team_board_level(row),
        "affiliate": affiliate,
        "eta": _team_board_eta(row),
        "meta": " / ".join(part for part in (_team_board_position(row), affiliate, _team_board_eta(row)) if part),
        "url": player_url,
        "detail_url": player_url,
        "report_url": _team_board_report_url(name),
        "has_report": has_report,
        "move": move,
        "move_sort": move["sort"],
        "value": _team_board_fmt_value(value),
        "value_sort": value or 0.0,
        "prospect_rank": getattr(row, "prospect_rank", None),
    }


_TEAM_BOARD_CALLUP_LEVELS = {"AAA", "AA"}
_TEAM_BOARD_LEVEL_POINTS = {"AAA": 36.0, "AA": 12.0}
_TEAM_BOARD_ETA_POINTS = {"This year": 28.0, "Next year": 12.0, "Monitor": 4.0, "Later": 0.0}


def _team_board_year_bucket(row):
    label = getattr(row, "graduation_context_label", None)
    if label:
        return str(label)
    graduation = getattr(row, "graduation_context", {}) or {}
    if graduation.get("label"):
        return str(graduation["label"])
    eta = getattr(row, "eta", None)
    try:
        eta_year = int(eta)
    except (TypeError, ValueError):
        return "Monitor"
    current_year = date.today().year
    if eta_year <= current_year:
        return "This year"
    if eta_year == current_year + 1:
        return "Next year"
    return "Later"


def _team_board_callup_score(row, movements):
    move = _team_board_move_from_signal(_team_board_signal_for(row, movements))
    return (
        _TEAM_BOARD_LEVEL_POINTS.get(_team_board_level(row), 0.0)
        + _TEAM_BOARD_ETA_POINTS.get(_team_board_year_bucket(row), 0.0)
        + (_team_board_value(row) or 0.0)
        + max(move["sort"], 0.0) * 1.5
    )


def _team_board_callup_status(row):
    level = _team_board_level(row)
    bucket = _team_board_year_bucket(row)
    if level == "AAA" and bucket == "This year":
        return "On the doorstep"
    if level == "AAA" or bucket in {"This year", "Next year"}:
        return "Near-term watch"
    return "Monitor"


def _team_board_callups(org_rows, movements, *, limit=5):
    candidates = [row for row in org_rows if _team_board_level(row) in _TEAM_BOARD_CALLUP_LEVELS]
    candidates.sort(key=lambda row: _team_board_callup_score(row, movements), reverse=True)
    callups = []
    for row in candidates[:limit]:
        move = _team_board_move_from_signal(_team_board_signal_for(row, movements))
        callups.append({
            "name": getattr(row, "name", None) or "Unknown",
            "url": _team_board_player_url(row),
            "level": _team_board_level(row),
            "affiliate": _team_board_affiliate(row),
            "eta": _team_board_year_bucket(row),
            "status": _team_board_callup_status(row),
            "move": move,
            "value": _team_board_fmt_value(_team_board_value(row)),
        })
    return callups


def _team_board_reports(org_rows, reports_by_key, repository, *, limit=5):
    reports = []
    seen = set()
    for row in org_rows:
        report = next((reports_by_key[key] for key in _team_board_identity_keys(row) if key in reports_by_key), None)
        if report is None or id(report) in seen:
            continue
        seen.add(id(report))
        name = report.get("name") or getattr(row, "name", None) or "Unknown"
        positions = "/".join(str(pos) for pos in report.get("positions") or () if pos)
        line = " ".join(str(_scouting_display_report_text(report) or "").split())
        if len(line) > 230:
            line = line[:227].rstrip() + "..."
        reports.append({
            "tag": _format_context_label(report.get("report_status")) or "Report",
            "date": report.get("published_at") or report.get("updated_at") or report.get("generated_at") or (repository or {}).get("generated_at"),
            "name": name,
            "url": _team_board_player_url(row),
            "report_url": _team_board_report_url(name),
            "meta": " / ".join(str(part) for part in (positions, report.get("level"), report.get("team")) if part),
            "line": line,
        })
        if len(reports) >= limit:
            break
    return reports


def _build_team_board_context(org=None, limit=20):
    rows = _team_board_prospect_rows()
    grouped = {}
    for row in rows:
        canonical = _team_board_org_for(row)
        if canonical is None:
            continue
        grouped.setdefault(canonical, []).append(row)
    teams = [
        {
            "org": key,
            "name": _team_board_org_name(key),
            "count": len(value),
            "url": f"/backfields/team/{quote(key, safe='')}",
        }
        for key, value in grouped.items()
    ]
    teams.sort(key=lambda row: row["name"])
    context = {
        "teams": teams,
        "selected": None,
        "rows": [],
        "callups": [],
        "reports": [],
        "limit": limit,
    }
    if org is None:
        return context
    canonical = _canonical_team_board_org(org)
    if canonical is None or canonical not in grouped:
        raise KeyError(org)
    org_rows = grouped[canonical]
    selected_rows = org_rows[:limit]
    scouting_repository = _load_artifact(Path(__file__).parent / "data" / "models" / "valucast_scouting_reports.json")
    reports_by_key = _indexed_artifact_rows(scouting_repository, "reports")
    movements = _team_board_movements()
    context.update({
        "selected": {
            "org": canonical,
            "name": _team_board_org_name(canonical),
            "count": len(org_rows),
            "url": f"/backfields/team/{quote(canonical, safe='')}",
        },
        "rows": [
            _team_board_row(row, idx, movements, reports_by_key)
            for idx, row in enumerate(selected_rows, 1)
        ],
        "callups": _team_board_callups(org_rows, movements),
        "reports": _team_board_reports(org_rows, reports_by_key, scouting_repository),
    })
    return context


def _build_backfields_page_context():
    root = Path(__file__).parent
    models = root / "data" / "models"
    recent_signal = _load_artifact(models / "valucast_recent_signal_report.json")
    ahead_of_consensus_artifact = _load_artifact(models / "valucast_ahead_of_consensus.json")
    aotc_scorecard = _load_artifact(models / "valucast_ahead_of_consensus_scorecard.json") or {}
    scouting_repository = _load_artifact(models / "valucast_scouting_reports.json")
    stat_payload = _load_artifact(root / "data" / "prospects" / "raw" / "milb_season_stats.json")
    prospect_rows = _prospect_rows()[:100] if dd_store.is_available else []
    tiers = _prospect_tiers() if dd_store.is_available else {}
    all_prospects = _prospect_rows() if dd_store.is_available else []

    def as_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def fmt_value(value, digits=1):
        number = as_float(value)
        return "-" if number is None else f"{number:.{digits}f}"

    def fmt_rate(value, digits=3):
        number = as_float(value)
        if number is None:
            return "-"
        text = f"{number:.{digits}f}"
        return text.replace("0.", ".", 1)

    def context_for(row):
        context = getattr(row, "context", None)
        if isinstance(context, dict):
            return context
        metadata = getattr(row, "metadata", None)
        if isinstance(metadata, dict) and isinstance(metadata.get("context"), dict):
            return metadata["context"]
        return {}

    def role_for(row):
        role = getattr(row, "role", None) or context_for(row).get("role")
        if role:
            return str(role).lower()
        positions = set(getattr(row, "positions", ()) or ())
        return "pitcher" if positions and positions <= {"P", "SP", "RP"} else "hitter"

    def identity_for(row):
        return _identity_key(getattr(row, "mlbam_id", None), role_for(row))

    def level_for(row):
        level = getattr(row, "level", None) or context_for(row).get("stat_line_level")
        return str(level or "").strip().upper()

    def affiliate_for(row):
        context = context_for(row)
        return (
            context.get("stat_line_team")
            or getattr(row, "team", None)
            or ""
        )

    def position_for(row):
        positions = [str(pos) for pos in (getattr(row, "positions", ()) or ()) if pos]
        return "/".join(positions) if positions else "-"

    def eta_for(row):
        eta = getattr(row, "eta", None)
        return f"ETA {eta}" if eta else ""

    def tier_for(row):
        try:
            tier = int(tiers.get(row.id, 5))
        except (TypeError, ValueError):
            tier = 5
        return max(1, min(tier, 5))

    def move_from_signal(signal):
        delta = as_float((signal or {}).get("rank_delta_7d"))
        if delta is None or delta == 0:
            return {"direction": "flat", "label": "-"}
        return {
            "direction": "up" if delta > 0 else "down",
            "label": str(int(abs(delta))) if delta.is_integer() else f"{abs(delta):.1f}",
        }

    def current_year_bucket(row):
        label = getattr(row, "graduation_context_label", None)
        if label:
            return label
        graduation = getattr(row, "graduation_context", {}) or {}
        if graduation.get("label"):
            return str(graduation["label"])
        eta = getattr(row, "eta", None)
        current_year = date.today().year
        if eta is None:
            return "Monitor"
        if eta <= current_year:
            return "This year"
        if eta == current_year + 1:
            return "Next year"
        return "Later"

    def short_text(text, limit=230):
        clean = " ".join(str(text or "").split())
        if len(clean) <= limit:
            return clean
        return clean[: limit - 3].rstrip() + "..."

    def player_search_url(name):
        clean = " ".join(str(name or "").split())
        if not clean:
            return "/?mode=prospects"
        return "/?" + urlencode({"mode": "prospects", "search": clean})

    def player_detail_url(player_id, name=None):
        if player_id not in (None, ""):
            return f"/player/{quote(str(player_id), safe='')}?mode=prospects"
        return player_search_url(name)

    def player_link_fields(name, player_id):
        url = player_detail_url(player_id, name)
        return {
            "id": str(player_id or ""),
            "url": url,
            "detail_url": url,
        }

    def report_url(name):
        clean = " ".join(str(name or "").split())
        if not clean:
            return "/scouting"
        return "/scouting?" + urlencode({"q": clean})

    signals = []
    for key in ("signals", "top_movers"):
        signals.extend(row for row in (recent_signal or {}).get(key) or [] if isinstance(row, dict))
    signal_by_key = {
        str(row.get("identity_key")): row
        for row in signals
        if row.get("identity_key")
    }
    signal_by_mlbam = {
        str(row.get("mlbam_id")): row
        for row in signals
        if row.get("mlbam_id") not in (None, "")
    }
    reports_by_key = _indexed_artifact_rows(scouting_repository, "reports")
    row_by_key = {identity_for(row): row for row in all_prospects if identity_for(row)}
    row_by_mlbam = {
        str(getattr(row, "mlbam_id")): row
        for row in all_prospects
        if getattr(row, "mlbam_id", None) not in (None, "")
    }
    rows_by_name = {}
    duplicate_names = set()
    for row in all_prospects:
        clean_name = str(getattr(row, "name", "") or "").strip().casefold()
        if not clean_name:
            continue
        if clean_name in rows_by_name:
            duplicate_names.add(clean_name)
        else:
            rows_by_name[clean_name] = row
    for name in duplicate_names:
        rows_by_name.pop(name, None)

    def row_for_raw_stat(raw_row):
        mlbam = raw_row.get("mlbam_id")
        if mlbam not in (None, ""):
            row = row_by_mlbam.get(str(mlbam))
            if row is not None:
                return row
        clean_name = str(raw_row.get("name") or "").strip().casefold()
        return rows_by_name.get(clean_name)

    rankings = []
    for rank, row in enumerate(prospect_rows, 1):
        key = identity_for(row)
        signal = signal_by_key.get(key) or signal_by_mlbam.get(str(getattr(row, "mlbam_id", "")))
        link_fields = player_link_fields(row.name, row.id)
        rankings.append({
            "rank": rank,
            "name": row.name,
            **link_fields,
            "report_url": report_url(row.name),
            "position": position_for(row),
            "affiliate": affiliate_for(row),
            "eta": eta_for(row),
            "level": level_for(row) or "-",
            "tier": tier_for(row),
            "move": move_from_signal(signal),
            "move_sort": as_float((signal or {}).get("rank_delta_7d")) or 0.0,
            "value": fmt_value(getattr(row, "dynasty_value", None)),
            "value_sort": as_float(getattr(row, "dynasty_value", None)) or 0.0,
            "has_report": bool(key and key in reports_by_key),
        })

    risers = []
    buys_context = _build_buys_page_context(buy_score.BOARD_SIZE)
    for item in (buys_context.get("graphic_rows") or [])[:5]:
        row = (
            dd_store.get_by_id(str(item.get("id")))
            if item.get("id") not in (None, "")
            else None
        )
        player_id = item.get("id") or (row.id if row else None)
        spark = item.get("spark") or build_spark(item.get("value_history"), width=120, height=30)
        spark_label = item.get("spark_label") or _buy_spark_label(spark)
        direction = str((spark or {}).get("direction") or "flat")
        move_label = str(spark_label or "-")
        for prefix in ("UP ", "DOWN "):
            if move_label.startswith(prefix):
                move_label = move_label[len(prefix):]
        name = item.get("name") or (row.name if row else "Unknown")
        risers.append({
            "name": name,
            **player_link_fields(name, player_id),
            "source": buys_context.get("buy_data_source"),
            "meta": " / ".join(str(part) for part in (item.get("level"), item.get("pos")) if part),
            "move": {
                "direction": direction if direction in {"up", "down"} else "flat",
                "label": move_label,
            },
            "value": fmt_value(item.get("score")),
            "spark": spark,
        })

    callups = []
    callup_rows = [
        row for row in all_prospects
        if level_for(row) in {"AAA", "AA"}
    ]
    eta_points = {
        "This year": 28.0,
        "Next year": 12.0,
        "Monitor": 4.0,
        "Later": 0.0,
    }
    level_points = {"AAA": 36.0, "AA": 12.0}

    def callup_sort_score(row):
        signal = signal_by_key.get(identity_for(row)) or signal_by_mlbam.get(str(getattr(row, "mlbam_id", "")))
        move = as_float((signal or {}).get("rank_delta_7d")) or 0.0
        bucket = current_year_bucket(row)
        return (
            level_points.get(level_for(row), 0.0)
            + eta_points.get(bucket, 0.0)
            + (as_float(getattr(row, "dynasty_value", None)) or 0.0)
            + max(move, 0.0) * 1.5
        )

    def callup_status(row):
        level = level_for(row)
        bucket = current_year_bucket(row)
        if level == "AAA" and bucket == "This year":
            return "On the doorstep"
        if level == "AAA" or bucket in {"This year", "Next year"}:
            return "Near-term watch"
        return "Monitor"

    for row in sorted(callup_rows, key=callup_sort_score, reverse=True)[:14]:
        signal = signal_by_key.get(identity_for(row)) or signal_by_mlbam.get(str(getattr(row, "mlbam_id", "")))
        move = move_from_signal(signal)
        value = fmt_value(getattr(row, "dynasty_value", None))
        why_parts = [level_for(row), current_year_bucket(row), f"Val {value}"]
        if move["direction"] == "up":
            why_parts.append(f"up {move['label']}")
        elif move["direction"] == "down":
            why_parts.append(f"down {move['label']}")
        callups.append({
            "name": row.name,
            **player_link_fields(row.name, row.id),
            "flag": " / ".join(part for part in (level_for(row), affiliate_for(row)) if part),
            "eta": current_year_bucket(row),
            "status": callup_status(row),
            "sort_score": round(callup_sort_score(row), 2),
            "why": " - ".join(part for part in why_parts if part),
            "value": value,
        })

    def leaders(rows, stat_key, label, *, high=True, value_format=fmt_value, limit=2):
        qualified = [
            row for row in rows
            if as_float(row.get(stat_key)) is not None and row_for_raw_stat(row) is not None
        ]
        if not qualified:
            return []
        winners = sorted(
            qualified,
            key=lambda row: as_float(row.get(stat_key)) or 0.0,
            reverse=high,
        )[:limit]
        rows_out = []
        for winner in winners:
            app_row = row_for_raw_stat(winner)
            if app_row is None:
                continue
            name = winner.get("name") or app_row.name or "Unknown"
            rows_out.append({
                "stat": label,
                "name": name,
                **player_link_fields(name, app_row.id),
                "level": winner.get("level") or "",
                "team": winner.get("team") or "",
                "value": value_format(winner.get(stat_key)),
            })
        return rows_out

    hitters = [
        row for row in (stat_payload or {}).get("hitters") or []
        if isinstance(row, dict) and (as_float(row.get("plate_appearances")) or 0) >= 50
    ]
    pitchers = [
        row for row in (stat_payload or {}).get("pitchers") or []
        if isinstance(row, dict) and (as_float(row.get("innings_pitched")) or 0) >= 20
    ]
    hitting_stats = []
    for stat_key, label, kwargs in (
        ("ops", "OPS", {"value_format": lambda value: fmt_rate(value, 3)}),
        ("iso", "ISO", {"value_format": lambda value: fmt_rate(value, 3)}),
        ("home_runs", "HR", {"value_format": lambda value: fmt_value(value, 0)}),
        ("stolen_bases", "SB", {"value_format": lambda value: fmt_value(value, 0)}),
        ("avg", "AVG", {"value_format": lambda value: fmt_rate(value, 3)}),
        ("obp", "OBP", {"value_format": lambda value: fmt_rate(value, 3)}),
    ):
        hitting_stats.extend(leaders(hitters, stat_key, label, **kwargs))
    pitching_stats = []
    for stat_key, label, kwargs in (
        ("k_per_9", "K9", {"value_format": lambda value: fmt_value(value, 1)}),
        ("k_bb_pct", "K-BB%", {"value_format": lambda value: f"{fmt_value(value, 1)}%"}),
        ("era", "ERA", {"high": False, "value_format": lambda value: fmt_value(value, 2)}),
        ("whip", "WHIP", {"high": False, "value_format": lambda value: fmt_value(value, 2)}),
        ("bb_per_9", "BB9", {"high": False, "value_format": lambda value: fmt_value(value, 1)}),
        ("innings_pitched", "IP", {"value_format": lambda value: fmt_value(value, 1)}),
    ):
        pitching_stats.extend(leaders(pitchers, stat_key, label, **kwargs))

    def report_date(row):
        return (
            row.get("published_at")
            or row.get("updated_at")
            or row.get("generated_at")
            or (scouting_repository or {}).get("generated_at")
        )

    report_items = [
        dict(row) for row in (scouting_repository or {}).get("reports") or []
        if isinstance(row, dict)
    ]
    report_items.sort(key=lambda row: int(row.get("prospect_rank") or 999999))
    report_items.sort(key=lambda row: str(report_date(row) or ""), reverse=True)
    scouting_reports = []
    for row in report_items[:6]:
        linked_row = (
            row_by_key.get(str(row.get("identity_key")))
            or row_by_mlbam.get(str(row.get("mlbam_id")))
            or rows_by_name.get(str(row.get("name") or "").strip().casefold())
        )
        positions = "/".join(str(pos) for pos in row.get("positions") or () if pos)
        meta_parts = [positions, row.get("level"), row.get("team")]
        name = row.get("name") or "Unknown"
        scouting_reports.append({
            "tag": _format_context_label(row.get("report_status")) or "Report",
            "date": report_date(row),
            "name": name,
            **player_link_fields(name, getattr(linked_row, "id", None)),
            "meta": " / ".join(str(part) for part in meta_parts if part),
            "line": short_text(_scouting_display_report_text(row)),
        })

    # The artifact carries only mlbam+role; the player-detail route resolves the
    # row's real id (e.g. vc_prospect_<mlbam>_<role>), so map it from the store
    # rather than passing the raw mlbam (which 404s -> "could not load card").
    prospect_id_by_key = {}
    try:
        for store_row in dd_store.get_all():
            mid = getattr(store_row, "mlbam_id", None)
            rl = getattr(store_row, "role", None)
            rid = getattr(store_row, "id", None)
            if mid and rl and rid:
                prospect_id_by_key[(str(mid), str(rl))] = rid
    except Exception:  # noqa: BLE001
        prospect_id_by_key = {}

    ahead_of_consensus = []
    for row in (ahead_of_consensus_artifact or {}).get("ahead_of_consensus") or []:
        if not isinstance(row, dict):
            continue
        valucast_rank = as_float(row.get("valucast_rank"))
        consensus_rank = as_float(row.get("consensus_rank"))
        divergence = as_float(row.get("divergence"))
        if valucast_rank is None or consensus_rank is None or divergence is None:
            continue
        board_count = as_float(row.get("board_count"))
        name = row.get("name") or "Unknown"
        resolved_id = prospect_id_by_key.get(
            (str(row.get("mlbam_id")), str(row.get("role")))
        )
        ahead_of_consensus.append({
            "name": name,
            **player_link_fields(name, resolved_id or row.get("mlbam_id")),
            "valucast_rank": int(valucast_rank),
            "consensus_rank": int(consensus_rank),
            "divergence": int(divergence),
            "board_count": int(board_count) if board_count is not None else 0,
            "ahead_since": row.get("ahead_since"),
            "days_ahead": int(row.get("days_ahead") or 0),
        })

    return {
        "backfields_page": True,
        "mode": "prospects",
        "as_of": dd_store.generated_at,
        "dd_available": dd_store.is_available,
        "rankings": rankings,
        "risers": risers,
        "callups": callups,
        "stats": {
            "hitting": hitting_stats,
            "pitching": pitching_stats,
        },
        "team_boards": _build_team_board_context(),
        "scouting_reports": scouting_reports,
        "ahead_of_consensus": ahead_of_consensus,
        "aotc_scorecard": aotc_scorecard,
    }


@app.route("/backfields")
def backfields():
    return render_template("backfields.html", **_build_backfields_page_context())


@app.route("/backfields/team/<org>")
def backfields_team(org):
    try:
        context = _build_backfields_page_context()
        context["team_boards"] = _build_team_board_context(org, limit=20)
    except KeyError:
        abort(404)
    return render_template("backfields.html", **context)


@app.route("/backfields/team/<org>/share-card")
def backfields_team_share_card(org):
    try:
        board = _build_team_board_context(org, limit=20)
    except KeyError:
        abort(404)
    return render_template(
        "backfields_team_share.html",
        backfields_page=True,
        mode="prospects",
        as_of=dd_store.generated_at,
        board=board,
    )


def _team_board_share_limit():
    raw = request.args.get("n", "10")
    try:
        limit = int(raw)
    except (TypeError, ValueError):
        abort(400)
    if limit not in {10, 20}:
        abort(400)
    return limit


def _team_board_share_card_png(board, *, limit):
    from PIL import Image, ImageDraw

    palette = _GRAPHIC_PALETTE
    img = Image.new("RGB", (1080, 1350), palette["bg"])
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    selected = board["selected"]
    date_label = _editorial_date(dd_store.generated_at)
    subtitle = f"{selected['org']} Team Board - {date_label}"
    _graphic_header(
        img,
        draw,
        headline="Backfields",
        subtitle=subtitle,
        extra_line="ValuCast team board",
    )

    title_font = _graphic_font(46, bold=True)
    label_font = _graphic_font(15, bold=True, mono=True)
    name_font = _graphic_font(24 if limit == 20 else 26, bold=True)
    meta_font = _graphic_font(16, mono=True)
    value_font = _graphic_font(30, bold=True, mono=True)
    small_font = _graphic_font(15, bold=True, mono=True)

    text = palette["text"]
    muted = palette["muted"]
    teal = palette["teal"]
    clay = palette["clay"]
    slate = palette["slate"]
    amber = (200, 146, 63)
    warm_card = (17, 16, 14)
    warm_card_2 = (22, 21, 18)
    warm_border = (58, 45, 28)
    warm_rule = (42, 32, 21)

    draw.text((48, 226), "BACKFIELDS TEAM BOARD", fill=amber, font=label_font)
    draw.text((48, 256), selected["name"], fill=text, font=title_font)
    deck = f"Top {limit} prospects · {selected['count']} prospects in pool · ValuCast order"
    draw.text((48, 314), _graphic_fit_text(draw, deck, meta_font, 820), fill=muted, font=meta_font)

    header_y = 360
    table_x1, table_x2 = 48, 1032
    row_h = 40 if limit == 20 else 68
    y = 392
    rows = board["rows"][:limit]
    table_bottom = y + row_h * max(1, len(rows))
    draw.rounded_rectangle(
        (table_x1, header_y - 10, table_x2, table_bottom + 8),
        radius=10,
        fill=warm_card,
        outline=warm_border,
        width=1,
    )
    draw.text((64, header_y), "#", fill=slate, font=label_font)
    draw.text((118, header_y), "PLAYER", fill=slate, font=label_font)
    draw.text((666, header_y), "POS", fill=slate, font=label_font)
    draw.text((728, header_y), "LEVEL", fill=slate, font=label_font)
    draw.text((804, header_y), "MOVE", fill=slate, font=label_font)
    draw.text((906, header_y), "VALUE", fill=slate, font=label_font)
    draw.line((table_x1, header_y + 28, table_x2, header_y + 28), fill=warm_border, width=1)

    for idx, row in enumerate(rows, 1):
        fill = warm_card if idx % 2 else warm_card_2
        draw.rectangle((table_x1 + 1, y, table_x2 - 1, y + row_h), fill=fill)
        draw.line((table_x1, y + row_h, table_x2, y + row_h), fill=warm_rule, width=1)
        draw.rectangle((table_x1, y, table_x1 + 4, y + row_h), fill=slate)
        rank_text = str(idx)
        draw.text((68, y + 12), rank_text, fill=muted, font=meta_font)
        name_y = y + (7 if limit == 20 else 10)
        draw.text(
            (118, name_y),
            _graphic_fit_text(draw, row["name"], name_font, 470),
            fill=text,
            font=name_font,
        )
        meta = row["eta"]
        if meta and limit != 20:
            draw.text(
                (118, name_y + 29),
                _graphic_fit_text(draw, meta, meta_font, 500),
                fill=muted,
                font=meta_font,
            )
        draw.text((666, y + 13), row["position"], fill=muted, font=meta_font)
        draw.text((728, y + 13), row["level"], fill=amber, font=meta_font)
        move = row.get("move") or {}
        if move.get("direction") == "up":
            label = str(move.get("label") or "").strip()
            move_text = f"▲ {label if label.startswith('+') else '+' + label}" if label else "▲"
            move_color = teal
        elif move.get("direction") == "down":
            label = str(move.get("label") or "").strip()
            move_text = f"▼ {label if label.startswith('-') else '-' + label}" if label else "▼"
            move_color = clay
        else:
            move_text, move_color = "-", muted
        draw.text((804, y + 13), move_text, fill=move_color, font=small_font)
        val = str(row["value"])
        draw.text((table_x2 - 20 - _graphic_text_width(draw, val, value_font), y + 8), val, fill=teal, font=value_font)
        y += row_h

    footer = f"{selected['org']} team board · top {limit} · ValuCast order"
    _graphic_footer(draw, right_note=footer)
    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


@app.route("/backfields/team/<org>/share-card.png")
def backfields_team_share_card_png(org):
    limit = _team_board_share_limit()
    try:
        board = _build_team_board_context(org, limit=limit)
    except KeyError:
        abort(404)
    response = make_response(_team_board_share_card_png(board, limit=limit))
    response.headers["Content-Type"] = "image/png"
    filename = f"valucast-{board['selected']['org'].lower()}-top-{limit}-prospects.png"
    response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    return response


# Positional share cards: (label, role, position codes). Hitter groups match on
# eligibility (a 1B/OF shows on both). Prospect pitchers carry no SP/RP split in
# the feed (all tagged "P"), so there is one combined Pitcher group.
_POSITION_SHARE_GROUPS = {
    "c": ("Catcher", "hitter", ("C",)),
    "1b": ("First Base", "hitter", ("1B",)),
    "2b": ("Second Base", "hitter", ("2B",)),
    "3b": ("Third Base", "hitter", ("3B",)),
    "ss": ("Shortstop", "hitter", ("SS",)),
    "of": ("Outfield", "hitter", ("OF", "LF", "CF", "RF")),
    "p": ("Pitching", "pitcher", ("P", "SP", "RP")),
}


def _positional_prospect_rows(position, limit):
    """Top-`limit` prospects eligible at `position`, in board (prospect_rank) order."""
    _, role, codes = _POSITION_SHARE_GROUPS[position]
    rows = sorted(
        dd_store.filter(pool="prospect"),
        key=lambda r: (r.prospect_rank is None, r.prospect_rank or r.dynasty_rank or 99999),
    )
    out = []
    for row in rows:
        if getattr(row, "role", None) != role:
            continue
        # Hitters filter by position eligibility; pitchers are a single pool.
        if role == "hitter" and not any(code in (row.positions or ()) for code in codes):
            continue
        out.append(row)
        if len(out) >= limit:
            break
    return out


def _positional_share_card_png(rows, *, position, limit):
    from PIL import Image, ImageDraw

    palette = _GRAPHIC_PALETTE
    label, _role, _codes = _POSITION_SHARE_GROUPS[position]
    img = Image.new("RGB", (1080, 1350), palette["bg"])
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    date_label = _editorial_date(dd_store.generated_at)
    _graphic_header(
        img,
        draw,
        headline="ValuCast",
        subtitle="Ahead of the Curve",
        extra_line=f"Prospect rankings · {date_label}",
    )

    title_font = _graphic_font(46, bold=True)
    label_font = _graphic_font(15, bold=True, mono=True)
    name_font = _graphic_font(24, bold=True)
    meta_font = _graphic_font(16, mono=True)
    value_font = _graphic_font(30, bold=True, mono=True)
    small_font = _graphic_font(15, bold=True, mono=True)

    text, muted, teal, slate = (
        palette["text"], palette["muted"], palette["teal"], palette["slate"],
    )
    amber = (200, 146, 63)
    warm_card, warm_card_2 = (17, 16, 14), (22, 21, 18)
    warm_border, warm_rule = (58, 45, 28), (42, 32, 21)

    draw.text((48, 226), f"TOP {len(rows)} {label.upper()}", fill=amber, font=label_font)
    draw.text((48, 256), f"{label} Prospects", fill=text, font=title_font)
    deck = f"ValuCast board · {date_label} · teal = ahead of consensus"
    draw.text((48, 314), _graphic_fit_text(draw, deck, meta_font, 900), fill=muted, font=meta_font)

    # Divergence map (mlbam_role -> +N) so the brand marker rides on the card.
    divergence = (
        _load_artifact(Path(__file__).parent / "data" / "models" / "valucast_ahead_of_consensus.json")
        or {}
    ).get("divergence_by_identity") or {}

    header_y, y, row_h = 360, 392, 44
    table_x1, table_x2 = 48, 1032
    table_bottom = y + row_h * max(1, len(rows))
    draw.rounded_rectangle(
        (table_x1, header_y - 10, table_x2, table_bottom + 8),
        radius=10, fill=warm_card, outline=warm_border, width=1,
    )
    draw.text((64, header_y), "#", fill=slate, font=label_font)
    draw.text((118, header_y), "PLAYER", fill=slate, font=label_font)
    draw.text((648, header_y), "OVERALL", fill=slate, font=label_font)
    draw.text((772, header_y), "AHEAD", fill=slate, font=label_font)
    draw.text((906, header_y), "VALUE", fill=slate, font=label_font)
    draw.line((table_x1, header_y + 28, table_x2, header_y + 28), fill=warm_border, width=1)

    for idx, row in enumerate(rows, 1):
        fill = warm_card if idx % 2 else warm_card_2
        draw.rectangle((table_x1 + 1, y, table_x2 - 1, y + row_h), fill=fill)
        draw.line((table_x1, y + row_h, table_x2, y + row_h), fill=warm_rule, width=1)
        draw.rectangle((table_x1, y, table_x1 + 4, y + row_h), fill=slate)
        key = _identity_key(getattr(row, "mlbam_id", None), getattr(row, "role", None))
        ahead = divergence.get(key) if key else None
        name_color = teal if ahead else text
        draw.text((68, y + 14), str(idx), fill=muted, font=meta_font)
        name_meta = " · ".join(p for p in (row.team, str(row.age) if row.age else None) if p)
        draw.text((118, y + 6), _graphic_fit_text(draw, row.name, name_font, 500), fill=name_color, font=name_font)
        if name_meta:
            draw.text((118, y + 26), name_meta, fill=muted, font=_graphic_font(13, mono=True))
        overall = f"#{row.prospect_rank}" if row.prospect_rank else "-"
        draw.text((648, y + 15), overall, fill=muted, font=meta_font)
        ahead_text = f"+{ahead['divergence']}" if ahead else "-"
        draw.text((772, y + 15), ahead_text, fill=teal if ahead else muted, font=small_font)
        val = f"{row.dynasty_value:.1f}" if row.dynasty_value is not None else "-"
        draw.text((table_x2 - 20 - _graphic_text_width(draw, val, value_font), y + 8), val, fill=teal, font=value_font)
        y += row_h

    _graphic_footer(draw, right_note=f"Top {len(rows)} {label} · ValuCast order")
    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


@app.route("/share/prospects/<position>.png")
def positional_share_card_png(position):
    position = (position or "").lower()
    if position not in _POSITION_SHARE_GROUPS or not dd_store.is_available:
        abort(404)
    try:
        limit = max(5, min(25, int(request.args.get("n", 20))))
    except (TypeError, ValueError):
        limit = 20
    rows = _positional_prospect_rows(position, limit)
    if not rows:
        abort(404)
    response = make_response(_positional_share_card_png(rows, position=position, limit=limit))
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-top-{len(rows)}-{position}-prospects.png"'
    )
    return response


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
        player_count=len(players),
        map_data_url="/api/value-map-players",
        dd_generated_at=dd_store.generated_at,
        dd_available=dd_store.is_available,
        map_page=True,
        mode="dd_dynasty",
        as_of=dd_store.generated_at or store.as_of,
    )


@app.route("/api/value-map-players")
def value_map_players_api():
    players = _value_map_players(dd_store.get_all()) if dd_store.is_available else []
    return jsonify({
        "players": players,
        "count": len(players),
        "generated_at": dd_store.generated_at,
    })


def _value_map_share_card_png(players, *, pool="all", position=None):
    """1080x1350 ValuCast 'Ahead of the Curve' value-vs-age scatter, rendered
    server-side to share the prospect/player share-card brand system (same
    wordmark, date, arc, footer, sizing) with deterministic output."""
    import io as _io
    import math as _math
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    bg = _GRAPHIC_PALETTE["bg"]
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]
    grid = (30, 32, 40)
    # Restrained cool family — teal is the one signal (prospects/future); the rest
    # are muted slate tones so the scatter reads as structure, not a rainbow.
    group_colors = {
        "hitter": (110, 124, 152),
        "sp": (150, 130, 116),
        "rp": (96, 142, 150),
        "prospect": (52, 226, 196),
    }
    legend_order = [("hitter", "Hitters"), ("sp", "SP"), ("rp", "RP"), ("prospect", "Prospects")]

    # Filter to match the live map exactly (value_map.html JS: pool vs player_type,
    # position vs primary). pool 'all' keeps everything.
    pts = []
    for p in players:
        if p.get("age") is None or p.get("value") is None:
            continue
        if pool and pool != "all" and p.get("player_type") != pool:
            continue
        if position and p.get("position") != position:
            continue
        pts.append(p)

    f_axis = _graphic_font(18)
    f_axisb = _graphic_font(18, bold=True)
    f_leg = _graphic_font(19)
    f_lbl = _graphic_font(16, bold=True)
    f_empty = _graphic_font(28, bold=True)

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)

    generated = _editorial_date(dd_store.generated_at)
    sub = "Dynasty value vs age - {} players".format(len(pts))
    if generated:
        sub = "{} - {}".format(sub, generated)
    _graphic_header(img, draw, headline="AHEAD OF THE CURVE", subtitle=sub)

    plot_left, plot_right = 132, 1032
    plot_top, plot_bottom = 322, 1150

    # Legend row above the plot.
    lx = plot_left
    ly = plot_top - 44
    for key, label in legend_order:
        draw.ellipse((lx, ly, lx + 16, ly + 16), fill=group_colors[key])
        draw.text((lx + 24, ly - 2), label, fill=muted, font=f_leg)
        lx += 24 + _graphic_text_width(draw, label, f_leg) + 34

    if not pts:
        draw.text((plot_left, (plot_top + plot_bottom) // 2), "No players match this view.",
                  fill=muted, font=f_empty)
    else:
        ages = [p["age"] for p in pts]
        values = [p["value"] for p in pts]
        age_min = _math.floor(min(ages)) - 1
        age_max = _math.ceil(max(ages)) + 1
        if age_max <= age_min:
            age_max = age_min + 1
        value_max = max(10, _math.ceil(max(values) / 10.0) * 10)
        aspan = float(age_max - age_min)

        def x_of(age):
            return plot_left + (age - age_min) / aspan * (plot_right - plot_left)

        def y_of(val):
            return plot_bottom - (val / value_max) * (plot_bottom - plot_top)

        # Value gridlines + labels (every 25).
        v = 0
        while v <= value_max:
            yy = y_of(v)
            draw.line([(plot_left, yy), (plot_right, yy)], fill=grid, width=1)
            lbl = str(int(v))
            draw.text((plot_left - 14 - _graphic_text_width(draw, lbl, f_axis), yy - 10),
                      lbl, fill=muted, font=f_axis)
            v += 25
        # Age gridlines + labels (every 5).
        a = _math.ceil(age_min / 5.0) * 5
        while a <= age_max:
            xx = x_of(a)
            draw.line([(xx, plot_top), (xx, plot_bottom)], fill=grid, width=1)
            lbl = str(int(a))
            draw.text((xx - _graphic_text_width(draw, lbl, f_axis) / 2, plot_bottom + 12),
                      lbl, fill=muted, font=f_axis)
            a += 5
        draw.text((plot_left, plot_bottom + 44), "AGE", fill=muted, font=f_axisb)

        # Points: draw all (lowest value first so leaders sit on top), then label
        # only a small collision-checked leader set so the card shows the shape
        # without becoming confetti.
        point_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        point_draw = ImageDraw.Draw(point_layer)
        for p in sorted(pts, key=lambda r: r["value"]):
            cx, cy = x_of(p["age"]), y_of(p["value"])
            col = group_colors.get(p.get("group"), muted)
            point_draw.ellipse((cx - 3.2, cy - 3.2, cx + 3.2, cy + 3.2),
                               fill=(*col, 178))
        img = Image.alpha_composite(img.convert("RGBA"), point_layer).convert("RGB")
        draw = ImageDraw.Draw(img)

        occupied = []

        def overlaps(box):
            return any(
                box[0] < other[2] and box[2] > other[0]
                and box[1] < other[3] and box[3] > other[1]
                for other in occupied
            )

        placed = 0
        for p in sorted(pts, key=lambda r: r["value"], reverse=True)[:16]:
            if placed >= 10:
                break
            cx, cy = x_of(p["age"]), y_of(p["value"])
            name = p.get("name") or ""
            bbox = draw.textbbox((0, 0), name, font=f_lbl)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            placements = (
                (12, -18, "right"),
                (12, 8, "right"),
                (-12, -18, "left"),
                (-12, 8, "left"),
                (0, -32, "center"),
                (0, 20, "center"),
            )
            chosen = None
            for dx, dy, align in placements:
                if align == "left":
                    tx = cx + dx - tw
                elif align == "center":
                    tx = cx - tw / 2
                else:
                    tx = cx + dx
                ty = cy + dy
                box = (tx - 5, ty - 4, tx + tw + 5, ty + th + 6)
                if (
                    box[0] >= plot_left and box[2] <= plot_right
                    and box[1] >= plot_top - 6 and box[3] <= plot_bottom
                    and not overlaps(box)
                ):
                    chosen = (tx, ty, box)
                    break
            if not chosen:
                continue
            tx, ty, box = chosen
            col = group_colors.get(p.get("group"), muted)
            draw.ellipse((cx - 4.5, cy - 4.5, cx + 4.5, cy + 4.5),
                         fill=col, outline=bg, width=2)
            draw.line((cx, cy, tx, ty + th / 2), fill=grid, width=1)
            draw.text((tx + 2, ty + 2), name, fill=bg, font=f_lbl)
            draw.text((tx, ty), name, fill=text, font=f_lbl)
            occupied.append(box)
            placed += 1

    foot_r = "dynasty value vs age"
    if generated:
        foot_r = "dynasty value vs age - updated {}".format(generated)
    _graphic_footer(draw, right_note=foot_r)

    out = _io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _value_map_share_query(pool, position):
    parts = []
    if pool and pool != "all":
        parts.append("pool=" + pool)
    if position:
        parts.append("position=" + position)
    return ("?" + "&".join(parts)) if parts else ""


@app.route("/map/share-card.png")
def value_map_share_card_png():
    if not dd_store.is_available:
        return "", 503
    pool = request.args.get("pool") or "all"
    position = request.args.get("position") or None
    players = _value_map_players(dd_store.get_all())
    png = _value_map_share_card_png(players, pool=pool, position=position)
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = 'inline; filename="valucast-value-map.png"'
    return response


@app.route("/map/share-card")
def value_map_share_card():
    pool = request.args.get("pool") or "all"
    position = request.args.get("position") or None
    png_url = "/map/share-card.png" + _value_map_share_query(pool, position)
    html = build_share_preview_html(
        title="Ahead of the Curve - Value Map",
        subtitle="Dynasty value vs age across the ValuCast player universe",
        png_url=png_url,
        filename="valucast-value-map.png",
        public_png_url=_public_url(png_url),
        public_page_url=_public_url("/map/share-card" + _value_map_share_query(pool, position)),
        description="Dynasty value vs age across the ValuCast player universe.",
        image_alt="ValuCast value map",
        back_url="/map",
        back_label="Back to the map",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/buys")
def buys():
    """Top-40 prospect buys + the shareable 1080x1350 graphic node."""
    context = _build_buys_page_context(request.args.get("n", buy_score.BOARD_SIZE))
    return render_template("buys.html", **context)


def _build_buys_page_context(raw_n=None):
    """Shared buys context for the page and deterministic share-card PNG."""
    n = buy_score.clamp_n(raw_n if raw_n is not None else buy_score.BOARD_SIZE)
    buy_store, buy_data_source = _select_buy_source(valucast_buy_store)
    if buy_data_source == "valucast_buys" and buy_store.is_available:
        graphic_rows = buy_score.build_valucast_board(buy_store.get_all())
        # n drives the interactive list only; the 2x20 graphic always takes 40
        list_rows = (graphic_rows[:n] if n <= buy_score.BOARD_SIZE
                     else buy_score.build_valucast_board(buy_store.get_all(), n=n))
        data_generated_at = buy_store.generated_at
        data_available = True
    else:
        # No ValuCast buys ready -> explicit unavailable. Never a DD-derived board.
        graphic_rows, list_rows = [], []
        data_generated_at = None
        data_available = False
    buy_source_copy = _buy_source_copy(buy_data_source)
    for row in graphic_rows:
        row["spark"] = build_spark(row["value_history"])
        row["spark_label"] = _buy_spark_label(row["spark"])
    for row in list_rows:
        if "spark" not in row:
            row["spark"] = build_spark(row["value_history"])
        if "spark_label" not in row:
            row["spark_label"] = _buy_spark_label(row["spark"])
    return {
        "list_rows": list_rows,
        "graphic_rows": graphic_rows,
        "n": n,
        "dd_available": data_available,
        "dd_generated_at": data_generated_at,
        "buy_data_source": buy_data_source,
        "buy_source_label": buy_source_copy["label"],
        "buy_source_note": buy_source_copy["note"],
        "buy_formula_note": buy_source_copy["formula"],
        "aotc_hold": AHEAD_OF_THE_CURVE_HOLD,
        "aotc_hold_message": "Ahead of the Curve returns later this week",
        "as_of": data_generated_at or store.as_of,
    }


def _draw_buys_spark(draw, spark, x, y, w, h, *, up_color, down_color, flat_color):
    if not spark:
        return
    points = []
    try:
        for pair in str(spark.get("points", "")).split():
            px, py = pair.split(",", 1)
            points.append((x + float(px) / spark.get("width", w) * w,
                           y + float(py) / spark.get("height", h) * h))
    except (AttributeError, TypeError, ValueError, ZeroDivisionError):
        return
    if len(points) < 2:
        return
    color = up_color if spark.get("direction") == "up" else (
        down_color if spark.get("direction") == "down" else flat_color
    )
    draw.line(points, fill=color, width=3, joint="curve")
    lx, ly = points[-1]
    draw.ellipse((lx - 3, ly - 3, lx + 3, ly + 3), fill=color)


def _buys_share_card_png(
    rows,
    *,
    generated_at=None,
    source_label="ValuCast buy signal",
    formula_note="buy score = model strength + momentum + buy window + runway",
):
    """Deterministic server-side Buys graphic for social crawlers and previews."""
    import io as _io
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    bg = _GRAPHIC_PALETTE["bg"]
    card = _GRAPHIC_PALETTE["card"]
    card_2 = _GRAPHIC_PALETTE["card_2"]
    border = _GRAPHIC_PALETTE["border"]
    green = _GRAPHIC_PALETTE["green"]
    blue = _GRAPHIC_PALETTE["blue"]
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]
    red = (204, 138, 102)

    f_source = _graphic_font(17, bold=True)
    f_rank = _graphic_font(21, bold=True)
    f_hero_score = _graphic_font(62, bold=True, mono=True)
    f_support_score = _graphic_font(29, bold=True, mono=True)
    f_cell_score = _graphic_font(22, bold=True, mono=True)
    f_name = _graphic_font(28, bold=True)
    f_support_name = _graphic_font(22, bold=True)
    f_cell_name = _graphic_font(19, bold=True)
    f_tag = _graphic_font(16)
    f_small = _graphic_font(14, bold=True)

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    date_label = _editorial_date(generated_at)
    subtitle = "Top 40 prospect buys by signal, not reputation"
    if date_label:
        subtitle = f"{subtitle} - {date_label}"
    _graphic_header(img, draw, headline="AHEAD OF THE CURVE", subtitle=subtitle, extra_line=source_label)

    def split_lines(name, fnt, max_width, max_lines=2):
        return _graphic_wrap_text(draw, name or "Unknown", fnt, max_width, max_lines=max_lines)

    def tag(row):
        pieces = [row.get("team"), row.get("pos"), row.get("level")]
        return " - ".join(str(p) for p in pieces if p)

    hero_rows = list(rows or [])[:5]
    grid_rows = list(rows or [])[5:40]
    if not hero_rows:
        draw.rounded_rectangle((48, 226, 1032, 370), radius=10, fill=card, outline=border, width=1)
        draw.text((76, 278), "No prospect buys are available.", fill=text, font=f_name)
    else:
        hero = hero_rows[0]
        draw.rounded_rectangle((48, 226, 418, 540), radius=10, fill=card, outline=border, width=1)
        draw.text((70, 252), "#1 - TOP BUY", fill=muted, font=f_rank)
        name_lines = split_lines(hero.get("name"), _graphic_font(34, bold=True), 320)
        for idx, line in enumerate(name_lines[:2]):
            draw.text((70, 320 + idx * 39), line, fill=text, font=_graphic_font(34, bold=True))
        draw.text((70, 403), _graphic_fit_text(draw, tag(hero), _graphic_font(16, mono=True), 320), fill=muted, font=_graphic_font(16, mono=True))
        draw.text((70, 455), str(hero.get("score", "--")), fill=green, font=f_hero_score)
        draw.text((155, 498), "/100", fill=muted, font=f_small)
        _draw_buys_spark(
            draw, hero.get("spark"), 226, 432, 130, 42,
            up_color=green, down_color=red, flat_color=muted,
        )
        draw.text((226, 484), hero.get("spark_label") or "30-DAY SIGNAL", fill=muted, font=f_small)
        draw.text((70, 515), _graphic_fit_text(draw, hero.get("reason"), f_source, 250).upper(),
                  fill=blue, font=f_source)

        for idx, row in enumerate(hero_rows[1:5]):
            x = 435 + (idx % 2) * 307
            y = 226 + (idx // 2) * 164
            draw.rounded_rectangle((x, y, x + 291, y + 149), radius=10, fill=card, outline=border, width=1)
            draw.text((x + 18, y + 13), f"#{idx + 2}", fill=blue, font=f_rank)
            support_lines = split_lines(row.get("name"), f_support_name, 250)
            for line_idx, line in enumerate(support_lines[:2]):
                draw.text((x + 18, y + 38 + line_idx * 25), line, fill=text, font=f_support_name)
            tag_y = _graphic_support_tag_y(
                y, len(support_lines), one_line_offset=80, wrapped_offset=92
            )
            draw.text((x + 18, tag_y), _graphic_fit_text(draw, tag(row), f_small, 250),
                      fill=muted, font=f_small)
            draw.line((x + 14, y + 104, x + 275, y + 104), fill=border, width=1)
            draw.text((x + 14, y + 112), str(row.get("score", "--")), fill=green, font=f_support_score)
            draw.text((x + 58, y + 126), "/100", fill=muted, font=_graphic_font(11))
            _draw_buys_spark(
                draw, row.get("spark"), x + 104, y + 117, 68, 18,
                up_color=green, down_color=red, flat_color=muted,
            )
            label = row.get("spark_label") or _graphic_fit_text(draw, row.get("reason"), f_small, 90).upper()
            draw.text((x + 183, y + 119), _graphic_fit_text(draw, label, f_small, 92),
                      fill=muted, font=f_small)

    cols = 5
    cell_w, cell_h = 196, 100
    start_x, start_y = 48, 562
    for idx, row in enumerate(grid_rows[:35]):
        col, r = idx % cols, idx // cols
        x, y = start_x + col * cell_w, start_y + r * cell_h
        fill = card_2 if r % 2 == 0 else bg
        draw.rectangle((x, y, x + cell_w, y + cell_h), fill=fill)
        if col:
            draw.line((x, y, x, y + cell_h), fill=border, width=1)
        if r:
            draw.line((x, y, x + cell_w, y), fill=border, width=1)
        draw.text((x + 10, y + 12), f"#{idx + 6}", fill=blue, font=_graphic_font(17, bold=True))
        score = str(row.get("score", "--"))
        draw.text((x + cell_w - 10 - _graphic_text_width(draw, score, f_cell_score), y + 10),
                  score, fill=green, font=f_cell_score)
        name = row.get("name") or "Unknown"
        parts = name.split()
        short = f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else name
        draw.text((x + 10, y + 42), _graphic_fit_text(draw, short, f_cell_name, 150),
                  fill=text, font=f_cell_name)
        draw.text((x + 10, y + 72), _graphic_fit_text(draw, tag(row), f_tag, 145),
                  fill=muted, font=f_tag)

    note = f"{source_label} - {formula_note}"
    _graphic_footer(draw, right_note=note)

    out = _io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def _buys_hold_share_card_png():
    """Branded AOTC placeholder for the public OG image while buys are held."""
    import io as _io
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    bg = _GRAPHIC_PALETTE["bg"]
    card = _GRAPHIC_PALETTE["card"]
    border = _GRAPHIC_PALETTE["border"]
    green = _GRAPHIC_PALETTE["green"]
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    _graphic_header(
        img,
        draw,
        headline="AHEAD OF THE CURVE",
        subtitle="Prospect buy signals return later this week",
        extra_line="ValuCast prospect board",
    )

    panel = (120, 500, 960, 850)
    draw.rounded_rectangle(panel, radius=18, fill=card, outline=border, width=2)

    title_font = _graphic_font(58, bold=True)
    sub_font = _graphic_font(28)
    small_font = _graphic_font(18, bold=True)

    def centered(label, y, font, fill):
        draw.text(((width - _graphic_text_width(draw, label, font)) / 2, y), label, fill=fill, font=font)

    centered("AHEAD OF THE CURVE", 585, title_font, text)
    centered("returns later this week", 670, sub_font, green)
    centered("The public buys surface is intentionally held.", 740, small_font, muted)

    _graphic_footer(draw, right_note="Returns later this week")

    out = _io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


@app.route("/buys/share-card.png")
def buys_share_card_png():
    context = _build_buys_page_context()
    if context.get("aotc_hold"):
        png = _buys_hold_share_card_png()
        response = make_response(png)
        response.headers["Content-Type"] = "image/png"
        response.headers["Content-Disposition"] = 'inline; filename="valucast-aotc-hold.png"'
        return response
    if not context["dd_available"]:
        return "", 503
    png = _buys_share_card_png(
        context["graphic_rows"],
        generated_at=context["dd_generated_at"],
        source_label=context["buy_source_label"],
        formula_note=context["buy_formula_note"],
    )
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = 'inline; filename="valucast-buys.png"'
    return response


@app.route("/buys/share-card")
def buys_share_card():
    held = AHEAD_OF_THE_CURVE_HOLD
    html = build_share_preview_html(
        title="Ahead of the Curve",
        subtitle=("Returns later this week" if held
                  else "Top prospect buys by signal, not reputation"),
        png_url="/buys/share-card.png",
        filename=("valucast-aotc-hold.png" if held else "valucast-buys.png"),
        public_png_url=_public_url("/buys/share-card.png"),
        public_page_url=_public_url("/buys/share-card"),
        description=("Ahead of the Curve returns later this week."
                     if held else "The top prospect buys by ValuCast signal, not reputation."),
        image_alt=("ValuCast Ahead of the Curve hold card" if held
                   else "ValuCast top prospect buys"),
        back_url="/buys",
        back_label="Back to Ahead of the Curve",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/health/ready")
def health_ready():
    """Readiness probe (Render healthCheckPath). 200 only when the core public
    surfaces are servable (projection stores + dynasty snapshot), else 503 — so a
    deploy missing core data is never promoted over the prior healthy one. Buys
    readiness is reported but does NOT gate health: a governor block on /buys must
    not fail the deploy of Board/Map/Scouting. Also reports the deployed git rev."""
    def _store_ok(source):
        try:
            return CATALOG.store_for(source).player_count > 0
        except Exception:  # noqa: BLE001
            return False

    stores = {
        "steamer": _store_ok("steamer"),
        "valucast": _store_ok("valucast"),
    }
    if os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT", "1") == "1":
        # Gate the deploy on the snapshot being SERVABLE (valid + present), not on
        # live-readiness. When the quality governor withholds live consumption
        # (e.g. "risky prospect bucket concentration"), the dynasty/prospect
        # routes fall back to stale-snapshot mode and still return 200 — so the
        # core surfaces (Board, Map, Scouting) and the daily refresh must still
        # deploy rather than freezing the whole site on the prior build. The
        # live-readiness flag stays reported under "public_snapshot" below for
        # observability; it gates what those pages show, never the deploy.
        stores["public_snapshot_available"] = public_snapshot_store.is_available
    # Buys readiness is informational only — a governor block on /buys must not
    # fail health and block the deploy. ponytail: reported, never gating.
    buys_live = (
        os.environ.get("VALUCAST_USE_VALUCAST_BUYS", "1") == "1"
        and valucast_buy_store.is_available
        and valucast_buy_store.ready_for_live_consumers
        and dynasty_data_source == "valucast_public_snapshot"
        and not AHEAD_OF_THE_CURVE_HOLD
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
            "live": buys_live,
        },
        "dd_comparison_feed": {"available": legacy_dd_store.is_available},
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

        artifact_context = _artifact_context_for_row(dd_row)
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
            profile_bars = prospect_percentiles.profile_bars(dd_row, stat_percentiles)
            skill_grades = prospect_percentiles.skill_grades(dd_row, stat_percentiles)
            skill_shape = prospect_percentiles.skill_shape_compare(
                skill_grades, getattr(dd_row, "peak_shape_items", ()) or ()
            )
            profile_stat_context = getattr(dd_row, "context", None)
            if not isinstance(profile_stat_context, dict):
                profile_stat_context = (
                    dd_row.metadata.get("context")
                    if isinstance(dd_row.metadata, dict)
                    else {}
                )
            if not isinstance(profile_stat_context, dict):
                profile_stat_context = {}
            identity = _prospect_player_card_read(dd_row, stat_percentiles, profile_stat_context)
            prospect_context = {
                "stat_percentiles": stat_percentiles,
                "stat_captions": stat_captions,
                "identity": identity,
                "profile_bars": profile_bars,
                "skill_grades": skill_grades,
                "skill_shape": skill_shape,
                "profile_pool_label": prospect_percentiles.pool_label(dd_row),
                "profile_stat_context": profile_stat_context,
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
            fangraphs=fg_fv.get(getattr(dd_row, "mlbam_id", None)),
            **prospect_context,
            **artifact_context,
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
    p1_id = request.args.get("p1", "")
    p2_id = request.args.get("p2", "")

    if mode in ("dd_dynasty", "prospects"):
        ctx = _build_dynasty_context(request.args)
        if mode == "prospects":
            _apply_prospect_board_context(ctx, request.args)
        rows = ctx["dd_rows"]
        r1 = next((row for row in rows if row.id == p1_id), None)
        r2 = next((row for row in rows if row.id == p2_id), None)
        return render_template(
            "partials/compare_modal_dynasty.html",
            r1=r1,
            r2=r2,
            mode=mode,
            dynasty_dollars=ctx.get("dynasty_dollars", {}),
            now_dollars=ctx.get("now_dollars", {}),
            tiers=ctx.get("tiers", {}),
            dd_schema_version=ctx.get("dd_schema_version"),
        )

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


def _prospect_share_limit(args):
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        return 10
    return limit if limit in {10, 20, 50, 100} else 10


def _prospect_graphic_payload():
    limit = _prospect_share_limit(request.args)
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

    limit = _prospect_share_limit(request.args)
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
    html = build_share_preview_html(
        title="Ahead of the Curve",
        subtitle=title,
        png_url=png_url,
        filename=filename,
        public_png_url=_public_url(png_url),
        public_page_url=_public_url("/prospects/share-card?" + urlencode(params)),
        description="ValuCast's current prospect board, filtered from the live Prospects tab.",
        image_alt=f"Ahead of the Curve - {title}",
        back_url="/?mode=prospects",
        back_label="Back to prospects",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/prospects/share-card.png")
def prospects_share_card_png():
    if not dd_store.is_available:
        return "", 503

    limit = _prospect_share_limit(request.args)
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


@app.route("/prospects/player-card/<player_id>")
def prospect_player_card_preview(player_id):
    if not dd_store.is_available:
        return "<!doctype html><title>Player card unavailable</title>", 503
    row = dd_store.get_by_id(player_id)
    if row is None or not row.is_prospect:
        return "<!doctype html><title>Player card not found</title>", 404

    filename_slug = "-".join(
        piece for piece in "".join(
            ch.lower() if ch.isalnum() else "-" for ch in row.name
        ).split("-") if piece
    )
    filename = f"valucast-{filename_slug or 'prospect'}-card.png"
    png_url = f"/prospects/player-card/{escape(player_id)}.png"
    title = f"{row.name} | Ahead of the Curve"
    html = build_share_preview_html(
        title=title,
        subtitle=f"{row.name} - current skill percentiles + peak context",
        png_url=png_url,
        filename=filename,
        public_png_url=_public_url(png_url),
        public_page_url=_public_url(f"/prospects/player-card/{player_id}"),
        description=f"{row.name} ValuCast prospect card with current skill percentiles and peak context.",
        image_alt=f"{row.name} ValuCast player card",
        back_url="/?mode=prospects",
        back_label="Back to prospects",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/prospects/player-card/<player_id>.png")
def prospect_player_card_png(player_id):
    if not dd_store.is_available:
        return "", 503
    row = dd_store.get_by_id(player_id)
    if row is None or not row.is_prospect:
        return "", 404

    png = _prospect_player_card_png(row)
    filename_slug = "-".join(
        piece for piece in "".join(
            ch.lower() if ch.isalnum() else "-" for ch in row.name
        ).split("-") if piece
    )
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-{filename_slug or "prospect"}-card.png"'
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


# --- Dynasty board share graphics (reuse the prospect renderer with Dynasty labels) ---
DYNASTY_SHARE_FOOTER = "ValuCast Dynasty Rank - value, age, position, role"


def _dynasty_share_rows(pool=None, position=None, search=None):
    rows = dd_store.filter(pool or None, position or None, search or None)
    return sorted(
        rows, key=lambda r: (r.dynasty_rank if r.dynasty_rank is not None else 999999)
    )


def _dynasty_share_scope(pool, position):
    parts = []
    if pool and pool.lower() not in ("all", ""):
        parts.append(pool)
    if position:
        parts.append(position)
    return " ".join(parts)


@app.route("/dynasty/share-card")
def dynasty_share_card():
    if not dd_store.is_available:
        return "<!doctype html><title>Dynasty graphic unavailable</title>", 503
    limit = _prospect_share_limit(request.args)
    pool = request.args.get("pool") or None
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    params = {"limit": limit}
    if pool:
        params["pool"] = pool
    if position:
        params["position"] = position
    if search:
        params["search"] = search
    png_url = "/dynasty/share-card.png?" + urlencode(params)
    scope = _dynasty_share_scope(pool, position)
    title = f"Top {limit} {scope + ' ' if scope else ''}Dynasty"
    if search:
        title = f"{title} | {search}"
    html = build_share_preview_html(
        title="Ahead of the Curve",
        subtitle=title,
        png_url=png_url,
        filename=f"valucast-dynasty-top-{limit}.png",
        public_png_url=_public_url(png_url),
        public_page_url=_public_url("/dynasty/share-card?" + urlencode(params)),
        description="ValuCast's current dynasty board, from the live Dynasty tab.",
        image_alt=f"Ahead of the Curve - {title}",
        back_url="/?mode=dd_dynasty",
        back_label="Back to dynasty",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/dynasty/share-card.png")
def dynasty_share_card_png():
    if not dd_store.is_available:
        return "", 503
    limit = _prospect_share_limit(request.args)
    pool = request.args.get("pool") or None
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    rows = _dynasty_share_rows(pool, position, search)[:limit]
    png = _prospect_graphic_png(
        rows,
        limit=limit,
        position=position,
        search=search,
        noun="Dynasty",
        hero_kicker="TOP DYNASTY ASSET",
        footer_note=DYNASTY_SHARE_FOOTER,
    )
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-dynasty-top-{limit}.png"'
    )
    return response


@app.route("/dynasty/share-card.svg")
def dynasty_share_card_svg():
    if not dd_store.is_available:
        return "<svg xmlns='http://www.w3.org/2000/svg'></svg>", 503
    limit = _prospect_share_limit(request.args)
    pool = request.args.get("pool") or None
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    rows = _dynasty_share_rows(pool, position, search)[:limit]
    svg = _prospect_graphic_svg(
        rows, limit=limit, position=position, search=search, noun="Dynasty",
        footer_note=DYNASTY_SHARE_FOOTER,
    )
    response = make_response(svg)
    response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-dynasty-top-{limit}.svg"'
    )
    return response


# --- Redraft board share graphics (adapt ValuationResult to the shared renderer) ---
_REDRAFT_PITCHER_POS = {"SP", "RP", "P"}


class _RedraftShareRow:
    """Adapt a ValuationResult to the attributes the share renderer reads."""

    def __init__(self, result):
        player = result.player
        meta = player.metadata or {}
        if player.pool == PlayerPool.HITTER:
            positions = [p for p in player.positions if p not in _REDRAFT_PITCHER_POS]
        else:
            positions = list(player.positions)
        self.name = player.name
        self.positions = positions or ["DH"]
        self.team = meta.get("team") or "FA"
        self.age = meta.get("age")
        self.value = round(result.total_value, 1)
        self.value_history = []   # redraft has no daily history -> no sparkline
        self.level = "MLB"
        self.status = "mlb"
        self.prospect_rank = None
        self.eta = None
        self.confidence = {}


def _redraft_share_labels(ctx, args):
    mode = (ctx.get("mode") or "categories").replace("_", " ").title()
    src = (args.get("source") or "steamer").title()
    return mode, src


@app.route("/redraft/share-card.png")
def redraft_share_card_png():
    limit = _prospect_share_limit(request.args)
    ctx = _build_context(request.args)
    rows = [_RedraftShareRow(r) for r in (ctx.get("results") or [])[:limit]]
    mode, src = _redraft_share_labels(ctx, request.args)
    png = _prospect_graphic_png(
        rows,
        limit=limit,
        noun="Redraft",
        hero_kicker="TOP REDRAFT VALUE",
        footer_note=f"ValuCast Redraft - {mode} ({src})",
    )
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-redraft-top-{limit}.png"'
    )
    return response


@app.route("/redraft/share-card")
def redraft_share_card():
    limit = _prospect_share_limit(request.args)
    ctx = _build_context(request.args)
    mode, src = _redraft_share_labels(ctx, request.args)
    params = request.args.to_dict()
    params["limit"] = limit
    png_url = "/redraft/share-card.png?" + urlencode(params)
    title = f"Top {limit} Redraft - {mode} ({src})"
    html = build_share_preview_html(
        title="Ahead of the Curve",
        subtitle=title,
        png_url=png_url,
        filename=f"valucast-redraft-top-{limit}.png",
        public_png_url=_public_url(png_url),
        public_page_url=_public_url("/redraft/share-card?" + urlencode(params)),
        description="ValuCast redraft values, from the live board.",
        image_alt=f"Ahead of the Curve - {title}",
        back_url="/",
        back_label="Back to redraft",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/redraft/share-card.svg")
def redraft_share_card_svg():
    limit = _prospect_share_limit(request.args)
    ctx = _build_context(request.args)
    rows = [_RedraftShareRow(r) for r in (ctx.get("results") or [])[:limit]]
    svg = _prospect_graphic_svg(rows, limit=limit, noun="Redraft")
    response = make_response(svg)
    response.headers["Content-Type"] = "image/svg+xml; charset=utf-8"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-redraft-top-{limit}.svg"'
    )
    return response


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", host="0.0.0.0", port=port)
