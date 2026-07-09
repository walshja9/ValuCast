from __future__ import annotations

from collections import Counter, OrderedDict
import csv
import gzip
import io
import json
import logging
import math
import os
import re
import sys
import threading
import time
from datetime import date
from functools import lru_cache
from html import escape
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote, urlencode

from flask import Flask, abort, render_template, request, make_response, jsonify, redirect

from dataclasses import replace as dc_replace

from league_values.engine import ValuationEngine
from league_values.post_processors import VolumeMultiplier
from league_values.playing_time import filter_by_playing_time
from league_values.models import PlayerPool, ValuationResult
from mlb.dynasty import _percentile, _scale_value

from web.projection_catalog import ProjectionCatalog
from web.category_registry import (
    HITTING_CATEGORIES,
    PITCHING_CATEGORIES,
    CATEGORY_PRESETS,
    DYNASTY_VALUE_PRESETS,
    POINTS_PRESETS,
    DEFAULT_CATS,
    DEFAULT_PCATS,
)
from web.config_builder import build_config, build_url_params, parse_list
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
from web.search_fold import fold as fold_search
from web.prospect_league_ranks import format_ranks_for
from web.value_spark import build_spark
from web import buy_score
from web import prospect_percentiles
from web.share_pages import build_share_preview_html
from prospects.availability import LEVEL_ORDER
from prospects.availability import eta_window as prospect_eta_window
from prospects.availability import eta_window_label
from prospects.universe import MINOR_TEAM_MLB_AFFILIATES
from scouting.mlb_read import build_mlb_scouting_read, stat_line_stats

app = Flask(__name__)
PUBLIC_BASE_URL = os.environ.get("VALUCAST_PUBLIC_URL", "https://valucast.app").rstrip("/")
# Deliberate public hold of the buys/AOTC surface until release; flip to False (and redeploy) to re-enable.
AHEAD_OF_THE_CURVE_HOLD = False
# Deliberate public hold of the call-up receipts board (7/1): the pre-launch exclusion
# fix dropped the sample to 4 hits / 0 misses, too thin and too "perfect" to show
# credibly. The daily build keeps computing valucast_call_up_receipts.json as usual
# (shadow -- grabbing more post-launch data); only the public page/nav/share-card are
# held. Flip to False (and redeploy) once there's a real sample.
RECEIPTS_HOLD = True
_GZIP_MIN_BYTES = 1024
_GZIP_MIMETYPES = {
    "application/javascript",
    "application/json",
    "image/svg+xml",
    "text/css",
    "text/html",
    "text/javascript",
    "text/plain",
    "text/xml",
}
_CSP_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "img-src 'self' data: https:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com data:; "
    "connect-src 'self'; "
    "form-action 'self'"
)
_PNG_CACHE_MAX = 32  # ~32 x ~0.5MB PNGs: bound worst-case RAM on the 512MB Render box
_PNG_CACHE: OrderedDict[tuple, tuple[bytes, dict[str, str]]] = OrderedDict()
# gunicorn runs --threads 4: every _PNG_CACHE mutation must be atomic. Without
# this lock the store path did `_PNG_CACHE[key]=...` then `move_to_end(key)` as
# two statements; a concurrent request could pop the key in between, and
# move_to_end on an absent key raises KeyError inside after_request -> a 500 on
# a request that had already rendered a valid PNG (exactly what unfurl bots hit
# with concurrent same-key fetches). The lock only guards dict ops on
# already-built bytes -- no Pillow render ever runs while it's held.
_PNG_CACHE_LOCK = threading.Lock()


def _append_vary(response, value):
    existing = response.headers.get("Vary")
    if not existing:
        response.headers["Vary"] = value
        return
    values = [part.strip() for part in existing.split(",")]
    if value.lower() not in {part.lower() for part in values}:
        response.headers["Vary"] = existing + ", " + value


def _png_cache_generation():
    parts = []
    for name, attr in (
        ("dd_store", "generated_at"),
        ("store", "as_of"),
        ("valucast_buy_store", "generated_at"),
    ):
        obj = globals().get(name)
        parts.append(str(getattr(obj, attr, "") or ""))
    return "|".join(parts)


# Every param ANY PNG renderer reads (board/share/player cards run the full
# valuation via _build_context, category state via fit_cats, league settings
# via teams/budget/...). Keying the cache on the FULL query string let
# `?junk=1,2,3...` defeat the cache and force a fresh Pillow render per
# request — an unauthenticated CPU hammer on the single 512MB Render worker
# (7/2 audit). But the allowlist must cover ALL render-affecting params, or
# two legitimately different cards collapse to one key and users get the
# WRONG cached image (adversarial review of the first fix). Unknown params
# still collapse to the canonical key.
#
# The w_*/pt_* weight & point-rule params are open-suffixed: keying on the
# prefix alone let `?w_junk1=1&w_junk2=1...` mint unlimited distinct keys →
# guaranteed miss, full render per request, and eviction of all 32 real
# entries. So the SUFFIX is validated against a registry-derived vocabulary
# (below): only real category / point-rule stat ids fold into the key; unknown
# w_/pt_ suffixes collapse to the canonical key like any other junk param.
_PNG_CACHE_PARAMS = frozenset({
    "n", "limit", "pool", "position", "search", "callups",
    "mode", "source", "cats", "pcats", "rules", "split_rp", "display",
    "fit_cats", "preset", "rank_by",
    "teams", "budget", "roster", "pslots",
})
# The complete points-mode stat vocabulary: every stat id a pt_<stat> param may
# legitimately score. Single source of truth shared by the cache key below AND
# the pt_ parse in _build_context — the parse DROPS any pt_ suffix outside this
# set, which is what makes collapsing unknown pt_ keys to the canonical cache
# key sound. Without that parse guard, `?pt_AB=1` (AB is a real key in
# player.stats that the engine's `stats.get(rule.stat)` would score) changes
# the rendered card but not the cache key — the poisoned PNG gets cached under
# the canonical key and served to every legit request (cache-poisoning, worse
# than the DoS). Invariant: any param that affects rendering must be in the
# cache-key vocabulary.
_POINT_STAT_IDS = frozenset(
    {c.id for c in (*HITTING_CATEGORIES, *PITCHING_CATEGORIES)}
    | {rule.stat for rules in POINTS_PRESETS.values() for rule in rules}
)
# w_<cat id> = category weight (_build_context weights[key[2:]]; split-RP looks
#   the weight up by BASE id, so w_SP_K/w_RP_K variants never exist — only base
#   category ids, per web/config_builder.py:80-85; unknown w_ suffixes are
#   render-inert because build_config only reads weights by category id).
# pt_<stat> = points-mode point value (build_config makes a PointRule per stat).
#   The points UI (templates/partials/setup_points.html) only emits stats that
#   are either a category id or a POINTS_PRESETS point-rule stat — the union
#   in _POINT_STAT_IDS covers all of them (verified against that template).
# Deriving from the registry means a new category id is picked up automatically.
_PNG_CACHE_PREFIXED_KEYS = frozenset(
    {f"w_{c.id}" for c in (*HITTING_CATEGORIES, *PITCHING_CATEGORIES)}
    | {f"pt_{stat}" for stat in _POINT_STAT_IDS}
)


def _png_cache_key():
    if request.method != "GET" or not request.path.endswith(".png"):
        return None
    return (
        _png_cache_generation(),
        request.path,
        tuple(sorted(
            (k, v) for k, v in request.args.items(multi=True)
            if k in _PNG_CACHE_PARAMS or k in _PNG_CACHE_PREFIXED_KEYS
        )),
    )


@app.before_request
def _serve_cached_png():
    if app.config.get("TESTING"):
        return None
    key = _png_cache_key()
    if key is None:
        return None
    with _PNG_CACHE_LOCK:
        cached = _PNG_CACHE.pop(key, None)  # pop-or-None: check-then-pop races under gunicorn --threads 4
        if cached is None:
            return None
        _PNG_CACHE[key] = cached  # re-insert as most-recently-used (LRU)
    body, headers = cached
    response = make_response(body)
    for name, value in headers.items():
        response.headers[name] = value
    return response


def _maybe_cache_png(response):
    if response.status_code != 200 or response.mimetype != "image/png":
        return response
    # 10 min, not 6h (7/2): a 6h edge/browser cache served day-old share cards
    # after layout fixes and holds yesterday's board after the daily refresh.
    response.headers.setdefault("Cache-Control", "public, max-age=600")
    if app.config.get("TESTING"):
        return response
    key = _png_cache_key()
    if key is None or response.direct_passthrough:
        return response
    body = response.get_data()
    headers = {
        name: value
        for name, value in response.headers.items()
        if name in {"Content-Type", "Content-Disposition", "Cache-Control"}
    }
    with _PNG_CACHE_LOCK:
        _PNG_CACHE.pop(key, None)
        _PNG_CACHE[key] = (body, headers)  # fresh insert is always last: LRU preserved, no absent-key move_to_end
        while len(_PNG_CACHE) > _PNG_CACHE_MAX:
            _PNG_CACHE.popitem(last=False)
    return response


def _maybe_gzip(response):
    if (
        request.method == "HEAD"
        or response.status_code < 200
        or response.status_code >= 300
        or response.direct_passthrough
        or response.headers.get("Content-Encoding")
        or "gzip" not in request.headers.get("Accept-Encoding", "").lower()
        or response.mimetype not in _GZIP_MIMETYPES
    ):
        return response
    body = response.get_data()
    if len(body) < _GZIP_MIN_BYTES:
        return response
    response.set_data(gzip.compress(body))
    response.headers["Content-Encoding"] = "gzip"
    response.headers["Content-Length"] = str(len(response.get_data()))
    _append_vary(response, "Accept-Encoding")
    return response


@app.after_request
def _security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Content-Security-Policy", _CSP_POLICY)
    response = _maybe_cache_png(response)
    return _maybe_gzip(response)


@app.context_processor
def _snapshot_staleness():
    """Every dd_store-backed surface gets the same honest stale flag — the banner
    used to exist only on the home board while map/backfields/buys/movers served
    the identical stale data silently (7/2)."""
    return {"snapshot_stale": dynasty_data_source == "valucast_public_snapshot_stale"}


@app.context_processor
def _aotc_hold_context():
    return {"aotc_hold": AHEAD_OF_THE_CURVE_HOLD, "receipts_hold": RECEIPTS_HOLD}


def _public_url(path):
    """Absolute public URL for social cards and share wrappers."""
    if not path:
        return PUBLIC_BASE_URL
    if path.startswith(("http://", "https://")):
        return path
    if not path.startswith("/"):
        path = "/" + path
    return PUBLIC_BASE_URL + path


def _browser_direct_partial_request() -> bool:
    return (
        request.headers.get("HX-Request") != "true"
        and "text/html" in request.headers.get("Accept", "")
    )


def _redirect_home(args) -> object:
    query = urlencode(args, doseq=True)
    return redirect("/" + (f"?{query}" if query else ""))


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
    from PIL import Image

    mark = Image.open(_BRAND_MARK_PATH).convert("RGBA").resize(
        (size, size), Image.Resampling.LANCZOS
    )
    # Bare emblem — paste on its own alpha, no box/tile (matches the glass-V previews).
    img.paste(mark, (x, y), mark)


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


# External boards stay initials-only on public surfaces (Alex ruling 7/3):
# single-rank citation is defensible, but two of the five sources are paid
# products and naming them advertises competitors on our own cards.
app.jinja_env.globals["exceptionally_young_for_level"] = (
    prospect_percentiles.exceptionally_young_for_level
)


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
REDRAFT_PITCHER_ANCHOR = 0.92  # demote the pitcher tier on the redraft board, mirroring dynasty's PITCHER_PRODUCTION_ANCHOR


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


PUBLIC_SNAPSHOT_PATH = Path(os.environ.get(
    "VALUCAST_PUBLIC_SNAPSHOT_PATH",
    str(Path(__file__).parent / "data" / "public" / "public_dynasty_snapshot.json"),
))
VALUCAST_BUYS_PATH = Path(os.environ.get(
    "VALUCAST_BUYS_PATH",
    str(Path(__file__).parent / "data" / "models" / "valucast_prospect_buys.json"),
))
VALUCAST_MOVERS_PATH = Path(os.environ.get(
    "VALUCAST_MOVERS_PATH",
    str(Path(__file__).parent / "data" / "models" / "valucast_prospect_movers.json"),
))
VALUCAST_RECEIPTS_PATH = Path(os.environ.get(
    "VALUCAST_RECEIPTS_PATH",
    str(Path(__file__).parent / "data" / "models" / "valucast_call_up_receipts.json"),
))
PROSPECT_COMPS_PATH = Path(
    Path(__file__).parent / "data" / "models" / "valucast_prospect_comps.json"
)
CONSENSUS_GAP_PATH = Path(
    Path(__file__).parent / "data" / "models" / "valucast_consensus_gap.json"
)


def _native_prospect_movers_strip(limit: int = 8, path: Path = VALUCAST_MOVERS_PATH) -> list[dict]:
    """Inline movers strip from the ValuCast-native movers board (no DD data).

    Reads the denoised valucast_prospect_movers.json and surfaces the biggest
    score moves (risers + fallers), so the strip carries zero DD-sourced fields.
    """
    data = _load_artifact(Path(path))
    if not isinstance(data, dict):
        return []
    strip = []
    for row in (data.get("rising") or []) + (data.get("cooling") or []):
        delta = row.get("score_delta")
        if not isinstance(delta, (int, float)) or not row.get("name"):
            continue
        strip.append({
            "id": row.get("player_id") or row.get("id"),
            "name": row.get("name"),
            "change": int(round(delta)),
        })
    strip.sort(key=lambda m: (-abs(m["change"]), m["name"]))
    return strip[:limit]


public_snapshot_store = PublicSnapshotStore(PUBLIC_SNAPSHOT_PATH)
valucast_buy_store = ValuCastBuyStore(VALUCAST_BUYS_PATH)

# Universal prospect profiles for the live settings-aware re-ranking adapter —
# parsed lazily on FIRST USE, not at import: the artifact is ~11MB and workers
# recycle every ~300 requests, so an import-time parse taxed every boot even
# when no prospect re-rank ever ran. Keyed (int(mlbam_id), role) -> profile,
# mirroring prospects.forward_shadow._profile_index. If the artifact is
# missing/empty the feature degrades to unavailable and the board still serves
# its default order (every path returns 200).
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


@lru_cache(maxsize=1)
def _universal_prospect_profiles_cached():
    """One-time lazy parse of the universal model (thread-safe: worst case
    under --threads 4 is a duplicate parse, never a torn read)."""
    return _load_universal_prospect_profiles(UNIVERSAL_PROSPECT_MODEL_PATH)


# Availability gate = a cheap existence stat, so routes can branch without
# triggering the 11MB parse. (A present-but-corrupt artifact now parses to an
# empty index on first use instead of flipping this flag at import — the
# adapter path degrades the same way: no re-rank, still 200.)
_UNIVERSAL_PROSPECT_AVAILABLE = UNIVERSAL_PROSPECT_MODEL_PATH.exists()
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
        generated_at = getattr(snapshot_candidate, "generated_at", None)
        if snapshot_candidate.dynasty_ready:
            # "Ready" is a flag BAKED INTO the snapshot at build time — it says
            # nothing about age. Without the window check here, a silently-broken
            # refresh serves week-old values labeled current with no banner
            # (7/2 audit). A ready snapshot past the window still serves (it
            # passed validation once) but wears the stale label.
            if _within_stale_window(generated_at):
                return snapshot_candidate, "valucast_public_snapshot"
            return snapshot_candidate, "valucast_public_snapshot_stale"
        if _within_stale_window(generated_at):
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
        return f"FLAT OVER {days}D" if days else "FLAT"
    suffix = f" OVER {days}D" if days else ""
    return f"{direction} {delta:+.1f}{suffix}"


def _value_momentum_label(row) -> str:
    return _buy_spark_label(build_spark(getattr(row, "value_history", None)))


dd_store, dynasty_data_source = _select_dynasty_store(public_snapshot_store)
prospect_pool = prospect_percentiles.build_pool(dd_store.get_all()) if dd_store.is_available else {}
_DYNASTY_SNAPSHOT_IDENTITY_INDEX_CACHE = {}


def _dynasty_snapshot_identity_index(snapshot_store=None):
    snapshot_store = snapshot_store or dd_store
    if not getattr(snapshot_store, "is_available", False):
        return {}
    rows = snapshot_store.get_all()
    signature = (
        id(snapshot_store),
        getattr(snapshot_store, "generated_at", None),
        len(rows),
    )
    cached = _DYNASTY_SNAPSHOT_IDENTITY_INDEX_CACHE.get(signature)
    if cached is not None:
        return cached

    index = {}
    for row in rows:
        mlbam_id = getattr(row, "mlbam_id", None)
        role = getattr(row, "role", None)
        if mlbam_id in (None, ""):
            continue
        roles = ("hitter", "pitcher") if role == "two_way" else (role,)
        for row_role in roles:
            if row_role in {"hitter", "pitcher"}:
                index.setdefault((str(mlbam_id), row_role), row)
    if len(_DYNASTY_SNAPSHOT_IDENTITY_INDEX_CACHE) > 8:
        _DYNASTY_SNAPSHOT_IDENTITY_INDEX_CACHE.clear()
    _DYNASTY_SNAPSHOT_IDENTITY_INDEX_CACHE[signature] = index
    return index


def _dynasty_snapshot_row_for(mlbam_id, role):
    if mlbam_id in (None, "") or role not in {"hitter", "pitcher"}:
        return None
    return _dynasty_snapshot_identity_index().get((str(mlbam_id), role))

# Refuse to promote a deploy whose snapshot is MISSING/CORRUPT: the boot failure
# makes the candidate deploy fail health checks so Render keeps the prior healthy
# deploy live. But an AGED-OUT snapshot must NOT raise — prod runs a single worker
# without --preload and recycles at --max-requests, so a wall-clock age-out would
# re-import app.py mid-deploy and crash-loop the LIVE site into a 503 (7/2 audit).
# Aged-out serves the explicit unavailable state instead. DD is never a fallback.
if (
    os.environ.get("VALUCAST_USE_PUBLIC_SNAPSHOT", "1") == "1"
    and dynasty_data_source == "unavailable"
):
    if not public_snapshot_store.is_available:
        raise RuntimeError(
            "Public snapshot missing or unreadable. Refusing to start so the "
            "prior healthy Render deploy stays live."
        )
    logging.getLogger(__name__).critical(
        "ValuCast snapshot is not ready and aged past the stale window; serving "
        "the explicit unavailable state. The daily refresh has likely been "
        "broken for %s+ days.", MAX_SNAPSHOT_STALE_DAYS,
    )

def _compute_dynasty_dollars(rows, settings, value_of=None):
    """Replacement-adjusted auction dollars for a league shaped by `settings`.

    Rostered pool = top (teams x roster) by dynasty value. Replacement value =
    the value at the cutoff rank. Every rostered player gets a $1 floor; the
    remaining budget is split proportionally to value ABOVE replacement.
    Below the cutoff = $0. Total payout == teams x budget (the league's cash), except the degenerate all-equal-values pool where only the $1 floors are paid.
    """
    value_of = value_of or (lambda r: r.dynasty_value)
    ordered = sorted(rows, key=value_of, reverse=True)
    cutoff = min(settings.roster_cutoff, len(ordered))
    rostered, bench = ordered[:cutoff], ordered[cutoff:]
    dollars = {r.id: 0.0 for r in bench}
    if not rostered:
        return dollars
    replacement = value_of(rostered[-1])
    surplus = {r.id: value_of(r) - replacement for r in rostered}
    total_surplus = sum(surplus.values())
    spendable = settings.total_budget - len(rostered)  # $1 floor reserved each
    for r in rostered:
        share = (surplus[r.id] / total_surplus * spendable) if total_surplus > 0 else 0.0
        dollars[r.id] = round(1.0 + share, 1)
    return dollars


DYNASTY_ELITE_FLOOR = 140.0


def _compute_dynasty_tiers(rows, num_tiers=8, value_of=None):
    """Assign tiers from dynasty value gaps.

    Values >= DYNASTY_ELITE_FLOOR (the 140+ band on the 0-150 scale) are always
    tier 1 — elite is an absolute badge, never merged into the tier below by the
    min-3 rule. Gap-based tiering applies below the floor, starting at tier 2.
    """
    value_of = value_of or (lambda r: r.dynasty_value)
    if len(rows) < 2:
        return {r.id: 1 for r in rows}
    elite = [r for r in rows if value_of(r) >= DYNASTY_ELITE_FLOOR]
    if not elite:
        return _gap_tiers(rows, num_tiers, value_of=value_of)
    tiers = {r.id: 1 for r in elite}
    rest = [r for r in rows if value_of(r) < DYNASTY_ELITE_FLOOR]
    if rest:
        for pid, t in _gap_tiers(rest, num_tiers - 1, value_of=value_of).items():
            tiers[pid] = t + 1
    return tiers


def _gap_tiers(rows, num_tiers=8, value_of=None):
    """Gap-based tiering with the min-3-per-tier merge rule."""
    value_of = value_of or (lambda r: r.dynasty_value)
    if len(rows) < 2:
        return {r.id: 1 for r in rows}
    gaps = []
    for i in range(len(rows) - 1):
        gap = value_of(rows[i]) - value_of(rows[i + 1])
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


def _dynasty_tiers_for(rows, settings, value_of=None):
    """Tiers over the rostered pool; below-cutoff rows are lumped into the LAST
    tier (never 0 — the template renders tier badges and 'T0' is nonsense)."""
    value_of = value_of or (lambda r: r.dynasty_value)
    ordered = sorted(rows, key=value_of, reverse=True)
    cutoff = min(settings.roster_cutoff, len(ordered))
    pool, bench = ordered[:cutoff], ordered[cutoff:]
    tiers = _compute_dynasty_tiers(pool, value_of=value_of)
    last = max(tiers.values()) if tiers else 1
    for r in bench:
        tiers[r.id] = last
    return tiers


_DYNASTY_METADATA_CACHE: OrderedDict[tuple, tuple] = OrderedDict()
# settings fields are clamped user input and presets are a fixed vocabulary, but
# the cross product is still user-driven — bound the LRU like the redraft bundle.
_DYNASTY_METADATA_MAX = 16


def _dynasty_metadata(settings, preset=None):
    """Dynasty $ and tiers computed on the FULL DD universe shaped by league
    settings, so they don't change when the displayed rows are filtered.

    Memoized per (feed generation, settings, preset): `preset` — not a value_of
    callable — is the cache identity because it fully determines the sort key
    (`row.value_for(preset)` when set, `row.dynasty_value` otherwise), and
    LeagueSettings is a frozen dataclass whose four fields are its whole state.
    A daily refresh restamps `generated_at`, so the key can never serve stale
    rows within a process. Returned dicts are read-only to all consumers."""
    key = (
        dd_store.generated_at,
        (settings.teams, settings.budget, settings.roster, settings.pslots),
        preset,
    )
    hit = _DYNASTY_METADATA_CACHE.get(key)
    if hit is not None:
        return hit
    value_of = (
        (lambda r: r.value_for(preset)) if preset else (lambda r: r.dynasty_value)
    )
    all_rows = sorted(dd_store.get_all(), key=value_of, reverse=True)
    result = (
        _compute_dynasty_dollars(all_rows, settings, value_of=value_of),
        _dynasty_tiers_for(all_rows, settings, value_of=value_of),
    )
    _DYNASTY_METADATA_CACHE[key] = result  # single-reference assign, fully built
    while len(_DYNASTY_METADATA_CACHE) > _DYNASTY_METADATA_MAX:
        try:
            _DYNASTY_METADATA_CACHE.popitem(last=False)
        except KeyError:
            break
    return result


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
# Canonical id -> display label for board column headers (SV_HLD -> SV+HLD).
_CAT_DISPLAY_LABELS = {v: k for k, v in FIT_QUERY_ALIASES.items()}
_DYN_Z_CACHE = {"key": None, "map": {}, "stats": {}}


def _dynasty_z_map():
    return _dynasty_match_maps()[0]


def _dynasty_stats_map():
    """Raw projected stats per dynasty row — same matched projections as the
    z map, so the board's stat line always agrees with the card."""
    return _dynasty_match_maps()[1]


def _dynasty_match_maps():
    """Per-player z's for the dynasty board's Category Fit panel, plus raw
    projected stats for the board's stat columns.

    The feed's z_scores field has never been produced (DD-producer gap), so
    matched projections are scored app-side across the fit panel's category
    union — same engine as the cards, so board and card numbers agree.
    The data-z-scores contract is STAT-SPACE (the fit JS sign-flips its
    FIT_INVERSE cats), while the engine emits value-oriented z's — flip
    those here. Cached per feed generation; ~0.1s to build."""
    if not dd_store.is_available:
        return {}, {}
    key = dd_store.generated_at
    if _DYN_Z_CACHE.get("key") == key:
        return _DYN_Z_CACHE["map"], _DYN_Z_CACHE["stats"]
    config = build_config(
        mode="categories", cats=list(FIT_CATS), pcats=list(FIT_PCATS),
        rules_str="", pt_params=None, split_rp=False, weights=None,
    )
    results = _redraft_value_players(_valuation_players(active_store=store), config)
    by_id = {}
    for res in results:
        by_id[res.player.id] = res
        base = res.player.metadata.get("base_id")
        if base:
            by_id.setdefault(base, res)
    match_index = build_outlook_match_index(store.get_all())
    z_map = {}
    stats_map = {}
    for row in dd_store.get_all():
        matches = find_outlook_projections(row, match_index) or []
        res = next((by_id[m.id] for m in matches if m.id in by_id), None)
        if res is None:
            res = next(
                (by_id[m.metadata.get("base_id") or m.id] for m in matches
                 if (m.metadata.get("base_id") or m.id) in by_id), None)
        if res is None:
            continue
        # Full FIT-union stats — the board shows whichever slice the active
        # category selection asks for, so cache everything once.
        stats = {
            cat: raw for cat, raw in res.raw_values.items()
            if isinstance(raw, (int, float))
        }
        if stats:
            stats_map[row.id] = stats
        if not res.z_scores:
            continue
        z_map[row.id] = {
            cat: round(-z if cat in _FIT_STAT_SPACE_FLIP else z, 2)
            for cat, z in res.z_scores.items()
            if isinstance(z, (int, float))
        }
    _DYN_Z_CACHE["key"] = key
    _DYN_Z_CACHE["map"] = z_map
    _DYN_Z_CACHE["stats"] = stats_map
    return z_map, stats_map


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


def _prospect_rows(position=None, search=None, row_filter=None):
    """Return the dedicated Prospects board in DD's authoritative prospect order.
    row_filter runs BEFORE the top-200 slice (like position/search) so a filtered
    view repopulates to full depth — hiding 23 debuted players surfaces the next
    23 ranked prospects instead of leaving a 177-row board."""
    rows = dd_store.filter(pool="prospect", position=position, search=search)
    if row_filter is not None:
        rows = [row for row in rows if row_filter(row)]
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
    results = _redraft_value_players(_valuation_players(active_store=store), config)
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
    "ops_7x7": "7x7 OPS",
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
    profiles = list(_universal_prospect_profiles_cached()[0].values())
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
    # Debut-status view filter (renamed from "MiLB only" 7/2 — debut is the concept
    # users actually reason about). "Debuted" = has reached the majors: on an active
    # roster now (rookie-rule retention) OR a prior call-up since optioned back down
    # (the MLB-taste guys). Applied BEFORE the top-200 slice so the board
    # repopulates to full depth; P# gaps are honest — same as the position filter.
    raw_callups = args.get("callups") or ""
    callups = {"milb": "undebuted"}.get(raw_callups, raw_callups)
    if callups not in ("debuted", "undebuted"):
        callups = ""
    debuted_ids = _debuted_prospect_ids()
    pulse_keys = _call_up_pulse_keys()

    row_filter = None
    if callups == "undebuted":
        row_filter = lambda row: not _prospect_has_debuted(row, debuted_ids, pulse_keys)  # noqa: E731
    elif callups == "debuted":
        row_filter = lambda row: _prospect_has_debuted(row, debuted_ids, pulse_keys)  # noqa: E731
    rows = _prospect_rows(
        position=ctx.get("position") or None,
        search=ctx.get("search") or None,
        row_filter=row_filter,
    )
    ctx["callups"] = callups
    settings = parse_league_settings(args)
    ctx["dynasty_dollars"], _ = _dynasty_metadata(settings)
    ctx["tiers"] = _prospect_tiers()
    ctx["cutoff_rank"] = settings.prospect_cutoff
    ctx["mode"] = "prospects"
    ctx["horizon"] = "prospects"
    ctx["dyn_z_map"] = _dynasty_z_map()
    ctx["prospect_movers"] = (
        _native_prospect_movers_strip()
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
    # Rookie-eligible prospects who've already had a taste of the majors (e.g. a
    # cup-of-coffee call-up since optioned back down) -- so the board doesn't look
    # naive to anyone who already knows the player debuted. Same source as the
    # backfields "Got the Call" MLB-taste badge; display-only, doesn't affect rank.
    ctx["mlb_debut_by_id"] = {
        row.id: debuted_ids[str(row.mlbam_id)]
        for row in rows
        if str(getattr(row, "mlbam_id", "")) in debuted_ids
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
        '<text x="64" y="90" fill="#9197a6" font-family="Space Grotesk,system-ui,Segoe UI,Helvetica,Arial,sans-serif" font-size="18" font-weight="700" letter-spacing="0">Top Prospects</text>',
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


def _prospect_graphic_png(
    rows,
    *,
    limit,
    position=None,
    search=None,
    noun="Prospects",
    hero_kicker=None,
    footer_note=None,
    as_of=None,
):
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
        # Prospects always carry a real minor-league level, so a missing level means MLB.
        # (The old row.status check was dead here — dynasty rows are all "candidate_ready".)
        return row.level or "MLB"

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

    # 200-deep boards get a taller canvas: 5-col dense grid = 40 rows x 52px.
    width, height = 1080, (2400 if limit >= 200 else 1350)
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
    subtitle_date = _editorial_date(as_of if as_of is not None else dd_store.generated_at)
    subtitle = f"Top {limit} {scope}{noun} from the current board"
    if search:
        subtitle = f"{subtitle} | {search}"
    if subtitle_date:
        subtitle = f"{subtitle} - {subtitle_date}"
    _graphic_header(img, draw, headline="AHEAD OF THE CURVE", subtitle=subtitle, tagline=f"Top {noun}")

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
                tag_x = x + cell_w - 170
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
        _graphic_glass_panel(img, draw, (48, 225, 1032, 360), radius=12)
        draw.text((76, 276), "No prospects found for this filter.", fill=text, font=font(30, bold=True))
    elif limit <= 10:
        # Compact variant for position top-10s: same voice, less empty space.
        hero = rows[0]
        leader = hero_kicker or ("POSITION LEADER" if position else "TOP PROSPECT")
        _graphic_glass_panel(img, draw, (48, 226, 1032, 532), radius=12)
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
            _glow_polyline(img, draw, spark[0], green if spark[1] == "up" else muted, body=3, core=1.4, blur=6)
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
            # One line, stepping the size down to fit: two wrapped 24pt lines
            # (y+52 and y+79, ~28px tall) collided with the tag at y+98 on long
            # names like "Pete Crow-Armstrong".
            for name_size in (24, 21, 18):
                card_name_font = font(name_size, bold=True)
                if text_width(draw, row.name, card_name_font) <= 274:
                    break
            draw.text((x + 18, y + 52), fit_text(draw, row.name, card_name_font, 274), fill=text, font=card_name_font)
            draw.text((x + 18, y + 90), fit_text(draw, tag(row), font(16), 274), fill=muted, font=font(16))
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
            # 4 wider columns instead of 5 so FULL names fit (7/2 request) —
            # 100 rows = 25x41px fits the 1350 canvas, 200 = 50x41 fits 2400.
            draw_dense_prospect_grid(
                rows,
                cols=4,
                cell_w=246,
                cell_h=41,
                start_x=48,
                start_y=226,
                show_tag=False,
                full_name=True,
                rank_size=12,
                name_size=13,
                score_size=13,
            )
    else:
        hero = rows[0]
        leader = hero_kicker or ("POSITION LEADER" if position else "TOP PROSPECT")
        _graphic_glass_panel(img, draw, (48, 226, 418, 540), radius=12)
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
            _graphic_glass_panel(img, draw, (x, y, x + 291, y + 149), radius=12)
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
    _graphic_footer(draw, right_note=footer, card_height=height)
    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


_GRAPHIC_PALETTE = {
    # Phase 2 Broadcast Board — neutral cool-black base, teal = the one signal,
    # slate = structure/ranks (no functional blue in a static graphic), clay = decline.
    "bg": (18, 19, 31),       # cool-black #12131F (glass pass)
    "card": (28, 31, 44),     # dark glass, faint cool tint
    "card_2": (36, 40, 54),
    "border": (54, 59, 76),   # hairline, cooler
    "green": (52, 226, 196),   # legacy key, now teal — repaints every old green accent
    "teal": (52, 226, 196),
    "blue": (138, 146, 168),   # legacy key, now slate — ranks/monograms are structural
    "slate": (94, 102, 120),
    "clay": (208, 116, 92),   # matches --c-clay #d0745c — redder than backfields gold
    "text": (231, 233, 240),
    "muted": (150, 151, 166),
}


def _graphic_fill_background(img):
    from PIL import Image, ImageDraw, ImageFilter

    width, height = img.size
    draw = ImageDraw.Draw(img)
    top, bot = (18, 19, 31), (12, 13, 21)          # #12131F -> deeper
    for y in range(height):
        t = y / height
        draw.line([(0, y), (width, y)], fill=(
            round(top[0] + (bot[0] - top[0]) * t),
            round(top[1] + (bot[1] - top[1]) * t),
            round(top[2] + (bot[2] - top[2]) * t),
        ))
    # Soft teal/silver light blooms drifting through (teal top-right, silver bottom-left,
    # faint mid teal). Panels draw opaque on top, so the blooms read through the header
    # and the margins/gutters only.
    glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((width - 520, -260, width + 200, 360),   fill=(52, 226, 196, 46))   # teal, top-right
    gd.ellipse((-260, height - 440, 380, height + 220), fill=(176, 205, 232, 30))  # silver, bottom-left
    gd.ellipse((int(width * 0.34), int(height * 0.46), int(width * 0.86), int(height * 0.9)),
               fill=(19, 180, 156, 15))                                            # faint mid teal
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    img.alpha_composite(glow) if img.mode == "RGBA" else img.paste(glow, (0, 0), glow)


def _graphic_glass_panel(img, draw, box, *, radius=14, fill=None, border=None, shadow=True):
    """Dark-glass panel: soft drop shadow + cool fill + hairline border + faint
    top-edge highlight (the glass bevel). Pure Pillow."""
    from PIL import Image, ImageDraw, ImageFilter
    x0, y0, x1, y1 = box
    fill = fill or _GRAPHIC_PALETTE["card"]
    border = border or _GRAPHIC_PALETTE["border"]
    if shadow:
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((x0, y0 + 10, x1, y1 + 16), radius=radius, fill=(0, 0, 0, 150))
        sh = sh.filter(ImageFilter.GaussianBlur(18))
        img.paste(sh, (0, 0), sh)
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=border, width=1)
    draw.line([(x0 + radius, y0 + 1), (x1 - radius, y0 + 1)], fill=(60, 66, 86), width=1)  # top bevel


def _aa_strokes(img, pts, lines, *, node_fill=None, node_r=0, ring=None, ring_r=0, ring_w=0, ss=4):
    """Anti-alias Pillow's hard polyline strokes (ImageDraw has no AA, which made the rolling
    header curves look 8-bit/blocky): draw on an ss-supersampled layer sized to the curve's
    bbox, then downscale LANCZOS and composite. `lines` = [(rgb, width), ...]; optional
    white-hot node + outline ring at the last point. Cheap — supersamples only the bbox."""
    from PIL import Image, ImageDraw
    if not pts or len(pts) < 2:
        return
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    pad = max([w for _, w in lines] + [node_r, ring_r + ring_w, 2]) + 2
    x0 = int(min(xs) - pad)
    y0 = int(min(ys) - pad)
    bw = max(1, int(max(xs) + pad) - x0)
    bh = max(1, int(max(ys) + pad) - y0)
    layer = Image.new("RGBA", (bw * ss, bh * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    sp = [((x - x0) * ss, (y - y0) * ss) for x, y in pts]
    for rgb, wid in lines:
        d.line(sp, fill=rgb + (255,), width=max(1, int(wid)) * ss, joint="curve")
    nx, ny = sp[-1]
    if ring is not None and ring_r:
        d.ellipse((nx - ring_r * ss, ny - ring_r * ss, nx + ring_r * ss, ny + ring_r * ss),
                  outline=ring + (255,), width=max(1, ring_w) * ss)
    if node_fill is not None and node_r:
        d.ellipse((nx - node_r * ss, ny - node_r * ss, nx + node_r * ss, ny + node_r * ss),
                  fill=node_fill + (255,))
    aa = layer.resize((bw, bh), Image.LANCZOS)
    img.paste(aa, (x0, y0), aa)


def _glow_polyline(img, draw, pts, color, *, body=4, core=1.6, blur=8, node=True):
    """Glossy trend line: wide soft bloom + saturated body + bright near-white core +
    optional hot node. Pure Pillow — shared by every sparkline/trend draw. Crisp strokes
    are anti-aliased (supersampled) so the curve doesn't render 8-bit/blocky."""
    from PIL import Image, ImageDraw, ImageFilter
    if not pts or len(pts) < 2:
        return
    hot = tuple(min(255, int(c + (255 - c) * 0.75)) for c in color)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).line(pts, fill=color + (150,), width=int(body) * 3, joint="curve")
    glow = glow.filter(ImageFilter.GaussianBlur(blur))
    img.paste(glow, (0, 0), glow)
    _aa_strokes(img, pts, [(color, int(body)), (hot, max(1, round(core)))],
                node_fill=(hot if node else None), node_r=(5 if node else 0))


def _graphic_brand_curve(img, draw, *, value_history=None, x0=560, y0=130, x1=1016, y1=42, power=2.4, color=(52, 226, 196)):
    """The rising 'value curve' brand motif in the top-right of the header band. When a
    player's value_history is supplied (the "Ahead of the Curve" player cards), it draws
    that player's REAL rolling form curve here — green rising, clay falling — so the motif
    becomes the player's movement. Otherwise the default decorative accelerating arc."""
    from PIL import Image, ImageDraw, ImageFilter

    pts = None
    spark = build_spark(value_history, width=(x1 - x0), height=(y0 - y1)) if value_history else None
    if spark and spark.get("points"):
        if spark.get("direction") == "down":
            color = _GRAPHIC_PALETTE.get("clay", (208, 116, 92))
        elif spark.get("direction") == "flat":
            color = _GRAPHIC_PALETTE.get("muted", color)
        try:
            real = [(x0 + float(px), y1 + float(py)) for px, py in (p.split(",") for p in spark["points"].split())]
        except (ValueError, KeyError):
            real = []
        if len(real) >= 2:
            pts = real
    if pts is None:
        n = 56
        pts = [(x0 + (x1 - x0) * (i / n), y0 - (y0 - y1) * ((i / n) ** power)) for i in range(n + 1)]
    nx, ny = pts[-1]
    hot = tuple(min(255, int(c + (255 - c) * 0.75)) for c in color)   # near-white core / node

    # 1) wide soft bloom (blurred)
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(pts, fill=color + (150,), width=16, joint="curve")
    gd.ellipse((nx - 34, ny - 34, nx + 34, ny + 34), fill=color + (120,))
    glow = glow.filter(ImageFilter.GaussianBlur(11))
    img.paste(glow, (0, 0), glow)

    # 2+3) saturated body + bright core + hot node/ring, anti-aliased (supersampled bbox)
    _aa_strokes(img, pts, [(color, 5), (hot, 2)],
                node_fill=hot, node_r=6, ring=color, ring_r=12, ring_w=2)


def _draw_glass_text(img, draw, xy, text, font, *, glow=(36, 168, 156)):
    """Glossy 'liquid glass' wordmark matching the brand logo: a horizontal teal->chrome
    fill with a vertical glass sheen and a soft teal outer glow on the dark surface.
    Pure Pillow (no numpy) — Render's deploy is deliberately lean and numpy isn't installed."""
    import math
    from PIL import Image, ImageDraw, ImageFilter

    x0, y0, x1, y1 = draw.textbbox(xy, text, font=font)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        draw.text(xy, text, fill=(180, 246, 234), font=font)
        return
    # Pad scales with font size: the glyph ink sits below the draw anchor by a gap that
    # grows with size, so a fixed 10px clipped letter bottoms at large sizes (the banner).
    pad = max(10, int(getattr(font, "size", 28) * 0.28))
    width, height = w + pad * 2, h + pad * 2
    ox, oy = x0 - pad, y0 - pad
    mask = Image.new("L", (width, height), 0)
    ImageDraw.Draw(mask).text((pad, pad), text, fill=255, font=font)

    # 0) beveled depth: dark drop below + bright top highlight (reads as glass relief)
    bevel = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bevel)
    bd.text((pad, pad + 2), text, fill=(0, 0, 0, 150), font=font)        # dark drop = depth
    bd.text((pad, pad - 1), text, fill=(255, 255, 255, 90), font=font)   # top highlight
    img.paste(bevel, (ox, oy), bevel)

    # 1) soft teal outer glow (the "glowing glass on black" feel)
    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_layer.paste(Image.new("RGBA", (width, height), glow + (255,)), (0, 0), mask)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(8))
    img.paste(glow_layer, (ox, oy), glow_layer)

    # 2) glass fill: horizontal teal->chrome-silver x vertical sheen (bright near the top).
    # ponytail: pure-Python pixel build, fine at wordmark size (~width*height ≈ 10k px).
    teal, silver = (120, 236, 214), (224, 232, 244)
    denom_x, denom_y = max(width - 1, 1), max(height - 1, 1)
    px = []
    for j in range(height):
        ty = j / denom_y
        sheen = 0.92 + 0.30 * math.exp(-((ty - 0.30) ** 2) / (2 * 0.16 ** 2)) - 0.10 * ty
        for i in range(width):
            tx = i / denom_x
            px.append((
                min(255, int((teal[0] * (1 - tx) + silver[0] * tx) * sheen)),
                min(255, int((teal[1] * (1 - tx) + silver[1] * tx) * sheen)),
                min(255, int((teal[2] * (1 - tx) + silver[2] * tx) * sheen)),
            ))
    fill = Image.new("RGB", (width, height))
    fill.putdata(px)
    img.paste(fill, (ox, oy), mask)


def _graphic_header(img, draw, *, headline, subtitle, extra_line=None, tagline="Ahead of the Curve", value_history=None):
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]
    green = _GRAPHIC_PALETTE["green"]

    # Compact brand lockup, not a billboard — this is an exported app surface.
    # The tagline brands the graphic without dominating it; defaults to "Ahead of
    # the Curve" (the buys brand), overridden per board (e.g. "Top Prospects").
    # (headline arg kept for call-site compatibility.)
    _graphic_brand_curve(img, draw, value_history=value_history)
    _paste_brand_mark(img, 48, 42, size=52)
    _draw_glass_text(img, draw, (116, 48), "VALUCAST", _graphic_font(28, bold=True))
    draw.text((118, 86), tagline, fill=muted, font=_graphic_font(18, bold=True))
    # When the brand curve is a real form curve, caption its movement.
    spark = build_spark(value_history) if value_history else None
    if spark:
        accent = green if spark.get("direction") == "up" else _GRAPHIC_PALETTE.get("clay", (208, 116, 92)) if spark.get("direction") == "down" else muted
        draw.text((560, 132), f'FORM  {spark["delta"]:+.1f} over {spark["window_days"]}d', fill=accent, font=_graphic_font(14, bold=True))
    sub_font = _graphic_font(22)
    draw.text((48, 152), _graphic_fit_text(draw, subtitle, sub_font, 940), fill=text, font=sub_font)
    if extra_line:
        draw.text((48, 183), extra_line, fill=green, font=_graphic_font(15, bold=True))


def _graphic_footer(draw, *, right_note=None, card_height=1350):
    card = _GRAPHIC_PALETTE["card"]
    border = _GRAPHIC_PALETTE["border"]
    muted = _GRAPHIC_PALETTE["muted"]

    foot_y = card_height - 68
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


@lru_cache(maxsize=128)
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


def _graphic_combined_sample_phrase(line):
    """`over N PA/IP` from the combined line's OWN sample, so the read sample matches
    the label/bars line (not the thinner current-level context sample)."""
    pitcher = any(key in line for key in ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct"))
    sample = line.get("sample")
    if not isinstance(sample, (int, float)):
        sample = line.get("ip") if pitcher else line.get("pa")
    if not isinstance(sample, (int, float)):
        return ""
    unit = line.get("sample_unit") or ("IP" if pitcher else "PA")
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


def _with_note(text, note):
    return f"{text} {note}" if note else text


@lru_cache(maxsize=1)
def _prospect_exposure_history() -> dict:
    """Per-prospect season exposure (games + PA/IP, draft year) for the card honesty
    layer. Out-of-band artifact (scripts/build_prospect_exposure_history.py); absent in
    dev is fine -- the note just omits the lost-development-time mitigation."""
    try:
        payload = json.loads(
            (Path(__file__).parent / "data" / "prospects" / "raw" / "prospect_exposure_history.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    return payload.get("history") or {}


def _prospect_player_card_read(row, stat_percentiles, context, scouting_report=None):
    scouting_text = _scouting_display_report_text(scouting_report)
    if scouting_text:
        return scouting_text
    line = row.stat_line or {}
    if not line:
        return prospect_percentiles.identity_line(row, stat_percentiles) or ""

    last = _graphic_last_name(row.name)
    card_selection = prospect_percentiles.card_line(row)
    card_stat_line, best_level, is_best = card_selection
    exposure = _prospect_exposure_history().get(str(getattr(row, "mlbam_id", "")))
    note = prospect_percentiles.value_suppressor_note(row, stat_percentiles, exposure=exposure)
    if is_best and card_stat_line:
        return _with_note(
            _graphic_best_single_read(card_stat_line, best_level, stat_percentiles, last),
            note,
        )
    # Value/percentile parity: when card_line selected the combined season line, the
    # callout VALUES and the sample must come from THAT line — the one stat_percentiles
    # were ranked on — not the thin current stat_line. Otherwise a 9-PA .444 OPS value
    # gets paired with the combined line's 99th percentile.
    if card_selection.is_combined and card_stat_line:
        line = card_stat_line
        sample = _graphic_combined_sample_phrase(card_stat_line)
    else:
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
        return _with_note(f"{intro} {loud}{weak}", note)

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
    return _with_note(f"{intro} {loud}{weak}", note)


def _share_card_comp_lines(comp):
    """Twins + cohort strings for the share card, or None when not comped.

    Copy rules mirror the on-site card (7/8 review): tier words describe
    playing time, never a role verdict, and the cohort is counts, not odds.
    """
    if not comp or not comp.get("twins"):
        return None
    twins = "   ".join(
        f"{twin['name']} '{twin['season'] % 100:02d} ({twin.get('pos') or '?'})"
        for twin in comp["twins"][:3]
    )
    cohort = comp.get("cohort") or {}
    tiers = cohort.get("tiers") or {}
    if cohort.get("size"):
        short = {
            "impact_regular": "above-avg regular",
            "everyday": "everyday",
            "part_time": "limited time",
            "faded": "faded out",
        }
        parts = ", ".join(
            f"{tiers.get(key, 0)} {label}" for key, label in short.items()
        )
        cohort_line = (
            f"How the {cohort['size']} nearest resolved matches aged: {parts}"
        )
    else:
        cohort_line = "No matches old enough to grade a five-year outcome yet."
    return twins, cohort_line


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
    comps_payload = _load_artifact(PROSPECT_COMPS_PATH) or {}
    comp_lines = _share_card_comp_lines(
        (comps_payload.get("players") or {}).get(str(getattr(row, "mlbam_id", "") or ""))
    )
    comps_extra = 132 if comp_lines else 0
    context = getattr(row, "context", None)
    if not isinstance(context, dict):
        context = row.metadata.get("context") if isinstance(row.metadata, dict) else {}
    if not isinstance(context, dict):
        context = {}
    artifact_context = _artifact_context_for_row(row)
    if artifact_context.get("ahead_of_consensus"):
        context = dict(context)
        context["ahead_of_consensus"] = artifact_context["ahead_of_consensus"]
    scouting_report = artifact_context.get("scouting_report")
    identity = _prospect_player_card_read(
        row, stat_percentiles, context, scouting_report=scouting_report
    )

    STATS_BLOCK_H = 210

    def _season_number(value):
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None

    def _season_sum(rows, key):
        return sum(_season_number(stats_row.get(key)) or 0.0 for stats_row in rows)

    def _season_ratio(numerator, denominator, *, scale=1.0):
        if not denominator:
            return None
        return scale * numerator / denominator

    def _season_wavg(rows, key, weight_key="plate_appearances"):
        """PA/IP-weighted mean of the official per-level rate. Recomputing rates
        from summed counting omits HBP (absent in the feed) and can push the OBP/OPS
        total below every per-level value; weighting the official rate avoids that
        and matches the combined-line percentile bars."""
        num = den = 0.0
        for stats_row in rows:
            value = _season_number(stats_row.get(key))
            weight = _season_number(stats_row.get(weight_key))
            if value is None or weight is None or weight <= 0:
                continue
            num += value * weight
            den += weight
        return round(num / den, 3) if den else None

    def _season_role_for_card(card_row):
        role = str(getattr(card_row, "role", "") or "").strip().lower()
        if role in {"hitter", "pitcher"}:
            return role
        positions = {str(pos).upper() for pos in (getattr(card_row, "positions", ()) or ())}
        return "pitcher" if positions and positions <= {"P", "SP", "RP"} else "hitter"

    def _season_level_sort(level):
        label = str(level or "").strip().upper()
        return LEVEL_ORDER.get(label, 0)

    def _season_rows_for_card(card_row):
        mlbam_id = getattr(card_row, "mlbam_id", None)
        if mlbam_id in (None, ""):
            return [], _season_role_for_card(card_row)
        raw_rows = [
            stats_row for stats_row in MILB_SEASON_STATS_BY_MLBAM.get(str(mlbam_id), ())
            if isinstance(stats_row, dict)
        ]
        role = _season_role_for_card(card_row)
        role_rows = [
            stats_row for stats_row in raw_rows
            if str(stats_row.get("role") or "").strip().lower() == role
        ]
        season_rows = role_rows or raw_rows
        if season_rows:
            row_role = str(season_rows[0].get("role") or role).strip().lower()
            if row_role in {"hitter", "pitcher"}:
                role = row_role
        season_rows = sorted(
            season_rows,
            key=lambda stats_row: (
                -_season_level_sort(stats_row.get("level")),
                str(stats_row.get("level") or ""),
            ),
        )
        return season_rows, role

    def _hitter_total_row(rows):
        # Counting stats sum; rate stats are PA-weighted from the official per-level
        # rates (so the Total matches the combined-line bars and stays between the
        # per-level values). See _season_wavg for why rates are not recomputed.
        return {
            "level": "Total",
            "plate_appearances": _season_sum(rows, "plate_appearances"),
            "avg": _season_wavg(rows, "avg"),
            "obp": _season_wavg(rows, "obp"),
            "slg": _season_wavg(rows, "slg"),
            "ops": _season_wavg(rows, "ops"),
            "home_runs": _season_sum(rows, "home_runs"),
            "stolen_bases": _season_sum(rows, "stolen_bases"),
            "bb_pct": _season_wavg(rows, "bb_pct"),
            "k_pct": _season_wavg(rows, "k_pct"),
        }

    def _pitcher_total_row(rows):
        ip = _season_sum(rows, "innings_pitched")
        hits = _season_sum(rows, "hits")
        walks = _season_sum(rows, "walks")
        strikeouts = _season_sum(rows, "strikeouts")
        earned_runs = _season_sum(rows, "earned_runs")
        batters_faced = _season_sum(rows, "batters_faced")
        return {
            "level": "Total",
            "innings_pitched": ip,
            "era": _season_ratio(9 * earned_runs, ip),
            "whip": _season_ratio(walks + hits, ip),
            "strikeouts": strikeouts,
            "walks": walks,
            "k_bb_pct": _season_ratio(strikeouts - walks, batters_faced, scale=100.0),
        }

    season_rows, season_role = _season_rows_for_card(row)
    season_levels = {
        str(stats_row.get("level") or "").strip().upper()
        for stats_row in season_rows
        if stats_row.get("level")
    }
    season_table_rows = list(season_rows)
    if len(season_levels) >= 2:
        season_table_rows.append(
            _pitcher_total_row(season_rows)
            if season_role == "pitcher"
            else _hitter_total_row(season_rows)
        )

    # The scouting read is the in-depth report when present; render it in full (plus
    # the engine's one-line Projection verdict) and grow the card so the narrative
    # block isn't clipped. Measure now (font metrics are draw-independent) so the
    # canvas height absorbs the overflow; the no-report case stays pixel-identical.
    _measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    read_font = _graphic_font(22)
    proj_font = _graphic_font(19)
    read_lines = _graphic_wrap_read_text(_measure, identity, read_font, 890, max_lines=16)
    proj_text = str((scouting_report or {}).get("peak_summary") or "").strip()
    proj_lines = _graphic_wrap_read_text(_measure, proj_text, proj_font, 890, max_lines=3) if proj_text else []

    read_body_bottom = 1120 + len(read_lines) * 31
    if proj_lines:
        proj_y0 = read_body_bottom + 10
        peak_label_y = proj_y0 + len(proj_lines) * 26 + 12
    else:
        proj_y0 = read_body_bottom
        peak_label_y = read_body_bottom + 6
    read_extra = peak_label_y - 1250  # delta applied to the shape/FG/footer below

    width, height = 1080, 1350 + STATS_BLOCK_H + read_extra + comps_extra
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
    _graphic_header(img, draw, headline="AHEAD OF THE CURVE", subtitle=subtitle, value_history=getattr(row, "value_history", None))

    # Identity row — flat panel, name leads (no monogram). Value folds into an
    # app-style faint-teal chip (label over number), not a separate boxed module.
    _graphic_glass_panel(img, draw, (48, 218, 1032, 410), radius=12)

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

    receipt = context.get("ahead_of_consensus")
    receipt_text = _ahead_of_consensus_receipt_text(receipt)
    receipt_box = (300, 376, 984, 404)
    receipt_font = _graphic_font(15, bold=True)
    if receipt_text:
        # Ahead of consensus: the green receipt already carries "vs field ~#Y".
        draw.rounded_rectangle(receipt_box, radius=7, fill=(14, 29, 30), outline=(20, 59, 55), width=1)
        draw.text(
            (receipt_box[0] + 14, receipt_box[1] + 7),
            _graphic_fit_text(draw, receipt_text, receipt_font, receipt_box[2] - receipt_box[0] - 28),
            fill=green,
            font=receipt_font,
        )
    else:
        # No ahead receipt: still show the field's read so the divergence is the story.
        consensus_value = _card_consensus_value(receipt, fg_scouting, row)
        if consensus_value:
            draw.rounded_rectangle(receipt_box, radius=7, fill=card_2, outline=(44, 46, 54), width=1)
            label = "CONSENSUS  "
            draw.text((receipt_box[0] + 14, receipt_box[1] + 7), label, fill=muted, font=receipt_font)
            lx = receipt_box[0] + 14 + draw.textbbox((0, 0), label, font=receipt_font)[2]
            draw.text(
                (lx, receipt_box[1] + 7),
                _graphic_fit_text(draw, consensus_value, receipt_font, receipt_box[2] - lx - 14),
                fill=text,
                font=receipt_font,
            )

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

    # Ranks by format — settings-aware prospect ranks (the open-lane differentiator).
    fr = format_ranks_for(getattr(row, "mlbam_id", None))
    if fr:
        fx, fy = 74, 414
        lf = _graphic_font(13, bold=True, mono=True)
        vf = _graphic_font(15, bold=True, mono=True)
        draw.text((fx, fy + 1), "RANKS BY FORMAT", fill=muted, font=lf)
        fx += draw.textbbox((0, 0), "RANKS BY FORMAT", font=lf)[2] + 18
        for item in fr:
            draw.text((fx, fy), item["label"], fill=text, font=vf)
            fx += draw.textbbox((0, 0), item["label"], font=vf)[2] + 6
            num = f"#{item['rank']}"
            draw.text((fx, fy), num, fill=green, font=vf)
            fx += draw.textbbox((0, 0), num, font=vf)[2] + 18

    # Skill bars
    _graphic_glass_panel(img, draw, (48, 438, 1032, 812), radius=12)
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

    # 2026 season production by MiLB level
    if season_table_rows:
        stats_top = 820
        stats_bottom = stats_top + STATS_BLOCK_H
        draw.rounded_rectangle(
            (48, stats_top, 1032, stats_bottom),
            radius=10,
            fill=card,
            outline=border,
            width=1,
        )
        draw.rounded_rectangle(
            (48, stats_top, 1032, stats_top + 38),
            radius=10,
            fill=(14, 29, 30),
            outline=(20, 59, 55),
            width=1,
        )
        draw.text((74, stats_top + 10), "2026 SEASON", fill=green, font=_graphic_font(20, bold=True))
        draw.text(
            (820, stats_top + 14),
            "MILB PRODUCTION",
            fill=muted,
            font=_graphic_font(13, bold=True, mono=True),
        )

        header_font = _graphic_font(13, bold=True, mono=True)
        value_font = _graphic_font(17, bold=True, mono=True)
        level_font = _graphic_font(16, bold=True)
        row_gap = 24 if len(season_table_rows) >= 5 else 27
        header_y = stats_top + 52
        first_row_y = stats_top + 76

        def _season_display(stats_row, key):
            value = stats_row.get(key)
            if value is None:
                value = "---"
            return _graphic_stat_value(value, key)

        def _draw_right_cell(x, y_pos, value, font, fill):
            value = str(value)
            draw.text((x - _graphic_text_width(draw, value, font), y_pos), value, fill=fill, font=font)

        if season_role == "pitcher":
            columns = (
                ("level", "Level", 74, 118, "left"),
                ("innings_pitched", "IP", 248, 0, "right"),
                ("era", "ERA", 404, 0, "right"),
                ("whip", "WHIP", 560, 0, "right"),
                ("strikeouts", "K", 690, 0, "right"),
                ("walks", "BB", 806, 0, "right"),
                ("k_bb_pct", "K-BB%", 966, 0, "right"),
            )
        else:
            columns = (
                ("level", "Level", 74, 112, "left"),
                ("plate_appearances", "PA", 214, 0, "right"),
                ("avg", "AVG", 309, 0, "right"),
                ("obp", "OBP", 404, 0, "right"),
                ("slg", "SLG", 499, 0, "right"),
                ("ops", "OPS", 594, 0, "right"),
                ("home_runs", "HR", 680, 0, "right"),
                ("stolen_bases", "SB", 758, 0, "right"),
                ("bb_pct", "BB%", 860, 0, "right"),
                ("k_pct", "K%", 966, 0, "right"),
            )

        for key, label, x, col_width, align in columns:
            if align == "left":
                draw.text((x, header_y), label, fill=muted, font=header_font)
            else:
                _draw_right_cell(x, header_y, label, header_font, muted)

        for idx, stats_row in enumerate(season_table_rows):
            row_y = first_row_y + idx * row_gap
            is_total = str(stats_row.get("level") or "").lower() == "total"
            row_fill = green if is_total else text
            if is_total:
                draw.line((74, row_y - 6, 1004, row_y - 6), fill=border, width=1)
            elif idx % 2 == 1:
                draw.rounded_rectangle(
                    (64, row_y - 3, 1016, row_y + 20),
                    radius=5,
                    fill=(18, 20, 25),
                )
            for key, _label, x, col_width, align in columns:
                value = _season_display(stats_row, key)
                if align == "left":
                    draw.text(
                        (x, row_y),
                        _graphic_fit_text(draw, value, level_font, col_width),
                        fill=row_fill,
                        font=level_font,
                    )
                else:
                    _draw_right_cell(x, row_y, value, value_font, row_fill)

    # Narrative + 20-80 shape. The read box grows with the full report (read_extra);
    # everything below shifts down by the same delta so the short-report case is
    # pixel-identical (read_extra == 0).
    _graphic_glass_panel(img, draw, (48, 1050, 1032, 1342 + read_extra), radius=12)
    draw.text((74, 1080), "THE VALUCAST READ", fill=muted, font=_graphic_font(20, bold=True))
    for idx, line in enumerate(read_lines):
        draw.text((74, 1120 + idx * 31), line, fill=text, font=read_font)
    for idx, line in enumerate(proj_lines):
        draw.text((74, proj_y0 + idx * 26), line, fill=muted, font=proj_font)

    draw.text((74, 1250 + read_extra), shape_title, fill=muted, font=_graphic_font(18, bold=True))
    for idx, skill in enumerate(shape_items[:4]):
        x = 74 + idx * 235
        draw.rounded_rectangle((x, 1278 + read_extra, x + 205, 1324 + read_extra), radius=10, fill=card_2, outline=(44, 46, 54), width=1)
        grade = int(skill["grade"])
        color = bar_elite if grade >= 60 else bar_low if grade <= 40 else text
        draw.text((x + 14, 1288 + read_extra), _graphic_fit_text(draw, skill["label"], _graphic_font(15, bold=True), 120), fill=muted, font=_graphic_font(15, bold=True))
        draw.text((x + 150, 1285 + read_extra), str(grade), fill=color, font=_graphic_font(25, bold=True))
        draw.text((x + 14, 1306 + read_extra), _graphic_fit_text(draw, skill["metrics"], _graphic_font(12), 132), fill=muted, font=_graphic_font(12))

    # Measured shape comps -- twins + how the shape aged, display-only. Sits
    # between the skill shape and the FG reference; everything below shifts by
    # comps_extra so non-comped players stay pixel-identical.
    if comp_lines:
        twins_line, cohort_line = comp_lines
        comps_y = 1356 + read_extra
        _graphic_glass_panel(img, draw, (48, comps_y, 1032, comps_y + 118), radius=12)
        draw.text((74, comps_y + 14),
                  "CLOSEST MLB SHAPES - era-adjusted match on translated K%/BB%/ISO - descriptive, not a forecast",
                  fill=muted, font=_graphic_font(14, bold=True))
        twins_font = _graphic_font(21, bold=True)
        draw.text((74, comps_y + 42), _graphic_fit_text(draw, twins_line, twins_font, 934),
                  fill=text, font=twins_font)
        cohort_font = _graphic_font(15)
        draw.text((74, comps_y + 82), _graphic_fit_text(draw, cohort_line, cohort_font, 934),
                  fill=muted, font=cohort_font)

    # FanGraphs scouting reference -- FV + key tool grades, display-only (never in
    # ValuCast value/rank). Neutral color marks it as the scouts' read, not ours.
    # Skipped when the player has no FG board entry.
    fg_y = read_extra + comps_extra
    if fg_scouting and fg_scouting.get("fv"):
        _graphic_glass_panel(img, draw, (48, 1356 + fg_y, 1032, 1482 + fg_y), radius=12)
        draw.text((74, 1370 + fg_y), "FANGRAPHS SCOUTING - FV 20-80 - scouting reference, not in ValuCast value",
                  fill=muted, font=_graphic_font(14, bold=True))
        draw.text((74, 1396 + fg_y), f"FV {fg_scouting['fv']}", fill=text, font=_graphic_font(40, bold=True))
        org = fg_scouting.get("org")
        org_rk = fg_scouting.get("fg_org_rank")
        if org:
            org_label = f"{org}" + (f" - org #{int(org_rk)}" if org_rk else "")
            draw.text((74, 1448 + fg_y), org_label, fill=muted, font=_graphic_font(16, mono=True))
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
            draw.text((tx, 1394 + fg_y), label, fill=muted, font=_graphic_font(13, bold=True))
            draw.text((tx, 1414 + fg_y), str(val), fill=text, font=_graphic_font(19, bold=True, mono=True))
            tx += 150

    source = (
        "Current bars use ValuCast-owned MiLB stats. Peak shape is role context, not public scouting grades."
        if peak_shape
        else "Stats from ValuCast-owned MiLB context. Skill shape is percentile-derived, not sourced scouting grades."
    )
    _graphic_footer(draw, right_note=source, card_height=height)

    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _dynasty_statcast_card_items(context):
    groups = context.get("statcast_groups") or []
    group_count = len(groups)
    items = []
    for group in groups:
        group_label = str(group.get("label") or "").strip()
        for metric in group.get("metrics") or ():
            pct = metric.get("pct")
            if not isinstance(pct, (int, float)):
                continue
            label = str(metric.get("label") or "").strip()
            if group_count > 1 and group_label:
                label = f"{group_label[:3].upper()} {label}"
            items.append({
                "key": label.lower().replace(" ", "_"),
                "label": label,
                "percentile": int(max(0, min(100, pct))),
                "value": metric.get("display") or "",
            })
    return items


def _dynasty_value_preset_items(row):
    value_by_preset = getattr(row, "value_by_preset", None)
    if not isinstance(value_by_preset, dict) or not value_by_preset:
        return []
    labels = {
        "5x5": "5x5",
        "sv_hld": "SV+HLD",
        "7x7": "7x7",
        "7x7_ops": "7x7 OPS",
        "points": "PTS",
    }
    items = []
    for preset_id in ("5x5", "sv_hld", "7x7", "7x7_ops", "points"):
        value = value_by_preset.get(preset_id)
        if isinstance(value, (int, float)):
            items.append((labels.get(preset_id, preset_id.upper()), f"{float(value):.1f}"))
    return items


def _dynasty_confidence_lines(row):
    confidence = getattr(row, "confidence", None)
    if not isinstance(confidence, dict):
        return []
    lines = []
    level = _format_context_label(confidence.get("level"))
    if level:
        lines.append(f"{level} confidence")
    value_range = confidence.get("range") or {}
    low = value_range.get("low")
    high = value_range.get("high")
    if isinstance(low, (int, float)) and isinstance(high, (int, float)):
        lines.append(f"Range {low:.0f}-{high:.0f}")
    return lines


_ARTICLE_AN_TOKENS = {"SS", "SP", "RP", "RF", "LF", "CF", "IP", "OF", "IF", "MI", "CI"}
_ARTICLE_AN_STARTS = set("AEIOUFHLMNRSX")


def _indefinite_article(text):
    token = str(text or "").strip().split(" ", 1)[0].strip("\"'([{")
    token = token.rstrip(".,;:)]}")
    if not token:
        return "a"
    upper = token.upper()
    if upper in _ARTICLE_AN_TOKENS or upper[0] in _ARTICLE_AN_STARTS:
        return "an"
    return "a"


def _capitalize_first(text):
    text = str(text or "")
    return text[:1].upper() + text[1:] if text else text


def _statcast_profile_phrase(statcast_items):
    """One-sentence read of an MLB Statcast percentile profile (deterministic)."""
    if not statcast_items:
        return None

    def ordinal(n):
        n = int(n)
        suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"

    def grade(pct):
        if pct >= 80:
            return "elite"
        if pct >= 65:
            return "above-average"
        if pct >= 45:
            return "average"
        if pct >= 25:
            return "below-average"
        return "soft"

    def metric_phrase(item):
        return f"{grade(item['percentile'])} {item['label']} ({ordinal(item['percentile'])} pct)"

    def drag_phrase(item):
        return f"{item['label'].lower()} at the {ordinal(item['percentile'])} pct"

    ranked = sorted(statcast_items, key=lambda it: it["percentile"], reverse=True)
    top, bottom = ranked[0], ranked[-1]
    if top["percentile"] >= 60 and bottom["percentile"] <= 40 and top["key"] != bottom["key"]:
        framings = (
            "Statcast points first to {top}, with {bottom} the clearest drag.",
            "{top} gives the Statcast card its shape, but {bottom} pulls it back.",
        )
        index = (top["percentile"] + len(top["label"])) % len(framings)
        return framings[index].format(top=metric_phrase(top), bottom=drag_phrase(bottom))
    if top["percentile"] >= 65:
        framings = (
            "Statcast points to {top} as the separator.",
            "The loudest Statcast mark is {top}.",
        )
        index = (top["percentile"] + len(top["label"])) % len(framings)
        return framings[index].format(top=metric_phrase(top))
    if top["percentile"] <= 40:
        framings = (
            "The Statcast card is light across the board; {top} is still the best mark.",
            "There is not a carrying Statcast mark here; {top} leads the card.",
        )
        index = (top["percentile"] + len(top["label"])) % len(framings)
        return framings[index].format(top=metric_phrase(top))
    return f"The Statcast card is balanced, led by {metric_phrase(top)}."


_PROJECTED_ROLE_PHRASES = {
    "everyday_regular": "an everyday role",
    "regular": "a regular role",
    "part_time_or_strong_side": "a strong-side role",
    "rotation_workhorse": "a rotation workhorse role",
    "rotation_starter": "a rotation starter role",
    "leverage_reliever": "a high-leverage relief role",
    "middle_relief": "a middle-relief role",
    "swingman_or_bulk": "a swingman/bulk role",
    "depth_arm": "a depth-arm role",
    "bench_or_depth": "a depth role",
}

_AVAILABILITY_STATUS_SENTENCES = {
    "active_mlb_roster": "He is on an active MLB roster.",
    "injured_list": "He is on the injured list.",
    "minors": "He is in the minors for now.",
}


def _enum_key(value):
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _projected_role_phrase(role_profile):
    raw_key = _enum_key(role_profile.get("projected_role"))
    if raw_key in _PROJECTED_ROLE_PHRASES:
        return _PROJECTED_ROLE_PHRASES[raw_key]
    label_key = _enum_key(role_profile.get("projected_role_label"))
    if label_key in _PROJECTED_ROLE_PHRASES:
        return _PROJECTED_ROLE_PHRASES[label_key]
    label = str(role_profile.get("projected_role_label") or role_profile.get("projected_role") or "").strip()
    if not label:
        return None
    label = label.replace("_", " ").lower()
    noun = label if label.endswith(" role") else f"{label} role"
    return f"{_indefinite_article(noun)} {noun}"


def _availability_status_sentence(role_profile):
    raw_key = _enum_key(role_profile.get("availability_status"))
    if raw_key in _AVAILABILITY_STATUS_SENTENCES:
        return _AVAILABILITY_STATUS_SENTENCES[raw_key]
    label = str(role_profile.get("availability_status_label") or role_profile.get("availability_status") or "").strip()
    return f"Status: {label}." if label else None


def _dynasty_card_read(row, context):
    dna = str(getattr(row, "dna", "") or "").strip()
    if dna:
        return dna
    scouting = _scouting_display_report_text(context.get("scouting_report"))
    if scouting:
        return scouting

    sentences = []
    rank = getattr(row, "dynasty_rank", None)
    value = getattr(row, "dynasty_value", None)
    role_profile = context.get("role_profile")
    if not isinstance(role_profile, dict):
        role_profile = {}

    pos = "/".join(row.positions[:2]) if getattr(row, "positions", None) else None
    role_bits = []
    role_phrase = _projected_role_phrase(role_profile)
    if role_phrase:
        role_bits.append(f"projected for {role_phrase}")
    if role_profile.get("projected_volume") is not None and role_profile.get("projected_volume_unit"):
        volume = f"{float(role_profile['projected_volume']):.0f} {role_profile['projected_volume_unit']}"
        role_bits.append(f"({volume})" if role_bits else f"projected for {volume}")

    lead = []
    if pos and not role_bits:
        lead.append(pos)
    if rank is not None and isinstance(value, (int, float)):
        lead.append(f"#{rank} on the dynasty board at {value:.1f}")
    elif isinstance(value, (int, float)):
        lead.append(f"{value:.1f} dynasty value")

    if lead:
        sentences.append(f"{row.name}: " + ", ".join(lead) + ".")
        if role_bits:
            if pos:
                sentences.append(
                    f"{_indefinite_article(pos).capitalize()} {pos} {' '.join(role_bits)}."
                )
            else:
                sentences.append(f"{_capitalize_first(' '.join(role_bits))}.")
    elif role_bits:
        if pos:
            sentences.append(
                f"{row.name} is {_indefinite_article(pos)} {pos} {' '.join(role_bits)}."
            )
        else:
            sentences.append(f"{row.name} is {' '.join(role_bits)}.")

    # Read the SAME metrics the card draws as bars (now the full set), so copy matches visuals.
    profile = _statcast_profile_phrase(_dynasty_statcast_card_items(context)[:12])
    if profile:
        sentences.append(profile)

    status = _availability_status_sentence(role_profile)
    if not role_bits and not profile and not status:
        projection = _dynasty_projection_stat_read(row)
        if projection:
            sentences.append(projection)
    if status:
        sentences.append(status)

    read = re.sub(r"\bMlb\b", "MLB", " ".join(s for s in sentences if s).strip())
    if read:
        return read
    if rank is not None and isinstance(value, (int, float)):
        return (
            f"{row.name} sits #{rank} on the ValuCast dynasty board with a "
            f"{value:.1f} long-term value, framed against current MLB role and skills."
        )
    return f"{row.name} is evaluated through ValuCast's dynasty lens against current MLB context."


def _dynasty_projection_stat_read(row):
    stats = stat_line_stats(getattr(row, "stat_line", None))
    if not stats:
        return None
    role = str(getattr(row, "role", "") or "").strip().lower()
    if role not in {"hitter", "pitcher"}:
        positions = set(getattr(row, "positions", ()) or ())
        role = "pitcher" if positions and positions <= {"P", "SP", "RP"} else "hitter"
    return build_mlb_scouting_read(SimpleNamespace(role=role), None, stats)


def _dynasty_category_card_items(context):
    dyn_result = context.get("dyn_result")
    dyn_categories = context.get("dyn_categories") or []
    if not dyn_result or not dyn_categories:
        return []
    raw_values = getattr(dyn_result, "raw_values", {}) or {}
    z_scores = getattr(dyn_result, "z_scores", {}) or {}
    category_values = getattr(dyn_result, "category_values", {}) or {}
    items = []
    for category in dyn_categories:
        raw = raw_values.get(category.id)
        if raw is None:
            continue
        z = z_scores.get(category.id, 0)
        value = category_values.get(category.id, 0)
        if not isinstance(z, (int, float)):
            z = 0
        if not isinstance(value, (int, float)):
            value = 0
        items.append({
            "label": category.label,
            "raw": raw,
            "z": z,
            "value": value,
        })
    items.sort(key=lambda item: abs(item["z"]), reverse=True)
    return items


def _redraft_card_read(row, context):
    role = "pitcher" if row.pool in _PITCHER_POOLS else "hitter"
    shim = SimpleNamespace(role=role)
    read = build_mlb_scouting_read(
        shim,
        context.get("statcast_groups"),
        row.stats,
    )
    status = _snapshot_availability_status_sentence(context.get("redraft_dynasty_row"))
    if status:
        return f"{read} {status}"
    return read


def _snapshot_availability_status_sentence(row):
    if row is None:
        return None
    availability = getattr(row, "availability_context", {}) or {}
    if not isinstance(availability, dict):
        availability = {}
    return _availability_status_sentence({
        "availability_status": availability.get("status"),
        "availability_status_label": getattr(row, "availability_status_label", None),
    })


def _card_value_fields(mode, row, context):
    """Mode-switched values for the shared player card renderer."""
    if mode == "dynasty":
        subtitle = "dynasty value + MLB Statcast context"
        generated = _editorial_date(dd_store.generated_at)
        if generated:
            subtitle = f"{subtitle} - {generated}"
        meta = " - ".join(
            piece for piece in [
                row.team or "FA",
                "/".join(row.positions[:2]) if row.positions else "UT",
                row.level or "MLB",
                f"Age {row.age}" if row.age is not None else "",
            ]
            if piece
        )
        value_notes = _dynasty_confidence_lines(row)
        preset_items = _dynasty_value_preset_items(row)
        if preset_items:
            value_notes.append(" / ".join(f"{label} {val}" for label, val in preset_items[:2]))
        momentum_label = _value_momentum_label(row)
        return {
            "headline": "DYNASTY VALUE CARD",
            "subtitle": subtitle,
            "meta": meta,
            "value": getattr(row, "dynasty_value", None),
            "rank": getattr(row, "dynasty_rank", None),
            "momentum_label": momentum_label,
            "value_notes": value_notes,
            "read_label": "THE DYNASTY READ",
            "read_text": _dynasty_card_read(row, context),
            "category_summary": context.get("dyn_category_summary"),
            "footer_note": "Dynasty value context. Statcast bars are vs MLB league percentiles.",
        }
    if mode == "redraft":
        subtitle = "redraft value + MLB Statcast context"
        generated = _editorial_date(context.get("as_of"))
        if generated:
            subtitle = f"{subtitle} - {generated}"
        role = "Pitcher" if row.pool in _PITCHER_POOLS else "Hitter"
        dynasty_row = context.get("redraft_dynasty_row")
        meta = " - ".join(
            piece for piece in [
                (row.metadata or {}).get("team") or "FA",
                "/".join(row.positions[:2]) if row.positions else "UT",
                role,
                f"Age {dynasty_row.age}" if dynasty_row is not None and dynasty_row.age is not None else "",
            ]
            if piece
        )
        result = context.get("dyn_result")
        ranks = context.get("overall_ranks") or {}
        value_notes = ["0-100 redraft scale"]
        if dynasty_row is not None:
            value_notes.extend(_dynasty_confidence_lines(dynasty_row))
        momentum_label = _value_momentum_label(dynasty_row) if dynasty_row is not None else ""
        return {
            "headline": "REDRAFT VALUE CARD",
            "subtitle": subtitle,
            "meta": meta,
            "value": _redraft_scaled_value(
                getattr(result, "total_value", None),
                context.get("redraft_value_scale"),
            ),
            "rank": ranks.get(row.id),
            "momentum_label": momentum_label,
            "value_notes": value_notes,
            "read_label": "THE REDRAFT READ",
            "read_text": _redraft_card_read(row, context),
            "category_summary": context.get("dyn_category_summary"),
            "footer_note": "Redraft value context. Statcast bars are vs MLB league percentiles.",
        }
    raise ValueError(f"Unknown player value card mode: {mode}")


def _player_value_card_png(row, context, mode):
    """Render a single player value card from a dynasty or redraft context."""
    from PIL import Image, ImageDraw

    category_items = _dynasty_category_card_items(context)
    # Categories wrap 4-per-row so every category in the active league format is
    # shown (not just the top 4) — the card grows downward to fit extra rows and
    # the footer shifts with it; nothing above the category panel moves.
    category_rows = -(-len(category_items) // 4) if category_items else 0
    category_extra = max(0, category_rows - 1) * 54

    width, height = 1080, 1350 + category_extra
    bg = _GRAPHIC_PALETTE["bg"]
    card = _GRAPHIC_PALETTE["card"]
    card_2 = _GRAPHIC_PALETTE["card_2"]
    border = _GRAPHIC_PALETTE["border"]
    green = _GRAPHIC_PALETTE["green"]
    bar_elite = green
    bar_mid = _GRAPHIC_PALETTE["slate"]
    bar_low = _GRAPHIC_PALETTE["clay"]
    text = _GRAPHIC_PALETTE["text"]
    muted = _GRAPHIC_PALETTE["muted"]

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    fields = _card_value_fields(mode, row, context)
    statcast_items = _dynasty_statcast_card_items(context)

    _graphic_header(img, draw, headline=fields["headline"], subtitle=fields["subtitle"], value_history=getattr(row, "value_history", None))

    _graphic_glass_panel(img, draw, (48, 218, 1032, 410), radius=12)
    name_font = _graphic_font(48, bold=True)
    draw.text((74, 250), _graphic_fit_text(draw, row.name, name_font, 610), fill=text, font=name_font)
    meta = fields["meta"]
    draw.text((76, 314), _graphic_fit_text(draw, meta, _graphic_font(22, mono=True), 610), fill=muted, font=_graphic_font(22, mono=True))
    if statcast_items:
        draw.text((76, 350), "vs MLB Statcast", fill=muted, font=_graphic_font(18, mono=True))

    draw.rounded_rectangle((760, 244, 1002, 402), radius=8, fill=(14, 29, 30), outline=(20, 59, 55), width=1)
    draw.text((780, 262), "VALUCAST VALUE", fill=muted, font=_graphic_font(13, bold=True))
    value = fields["value"]
    value_text = f"{float(value):.1f}" if isinstance(value, (int, float)) else "-"
    draw.text((780, 282), value_text, fill=green, font=_graphic_font(38, bold=True, mono=True))
    rank = fields["rank"]
    rank_text = f"#{rank}" if rank is not None else "#-"
    draw.text((900, 294), rank_text, fill=muted, font=_graphic_font(18, bold=True, mono=True))
    momentum_label = fields.get("momentum_label") or ""
    note_y = 334
    if momentum_label:
        chip_font = _graphic_font(13, bold=True, mono=True)
        chip_text = _graphic_fit_text(draw, momentum_label, chip_font, 176)
        chip_w = min(198, _graphic_text_width(draw, chip_text, chip_font) + 22)
        accent = bar_low if momentum_label.startswith("DOWN") else green if momentum_label.startswith("UP") else muted
        draw.rounded_rectangle((780, 324, 780 + chip_w, 348), radius=7, fill=(16, 35, 34), outline=(20, 59, 55), width=1)
        draw.text((791, 329), chip_text, fill=accent, font=chip_font)
        note_y = 356
    value_notes = fields["value_notes"]
    for idx, note in enumerate(value_notes[:2]):
        draw.text((780, note_y + idx * 20), _graphic_fit_text(draw, note, _graphic_font(15, bold=True), 198), fill=muted, font=_graphic_font(15, bold=True))

    y = 542
    if statcast_items:
        _graphic_glass_panel(img, draw, (48, 438, 1032, 794), radius=12)
        heading = "MLB STATCAST PERCENTILES"
        asof = context.get("statcast_asof")
        if asof:
            heading = f"{heading} - {asof}"
        draw.text((74, 468), _graphic_fit_text(draw, heading, _graphic_font(20, bold=True), 900), fill=muted, font=_graphic_font(20, bold=True))
        draw.text((74, 500), "100 = best against MLB league percentile baselines.", fill=muted, font=_graphic_font(17, bold=True))
        def _draw_statcast_bar(item, lx, lw, x0, x1, vx, vw, ry, lf, vf):
            pct = int(item["percentile"])
            draw.text((lx, ry + 6), _graphic_fit_text(draw, item["label"], lf, lw), fill=muted, font=lf)
            y0b, y1b = ry + 9, ry + 23
            draw.rounded_rectangle((x0, y0b, x1, y1b), radius=4, fill=(30, 32, 40))
            fill = bar_elite if pct >= 75 else bar_mid if pct > 25 else bar_low
            draw.rounded_rectangle((x0, y0b, x0 + int((x1 - x0) * pct / 100), y1b), radius=4, fill=fill)
            knob_x = max(x0 + 14, min(x1 - 14, x0 + int((x1 - x0) * pct / 100)))
            draw.rounded_rectangle((knob_x - 18, y0b - 3, knob_x + 18, y1b + 3), radius=4, fill=(10, 11, 15))
            draw.text((knob_x - 10, y0b - 2), str(pct), fill=text, font=_graphic_font(14, bold=True))
            draw.text((vx, ry + 2), _graphic_fit_text(draw, item["value"] or "-", vf, vw), fill=text, font=vf)
        # All available percentiles. <=6 (thin samples): one full-width column. More
        # (a full hitter is 12, pitcher 11): two columns so they all fit the same box.
        items = statcast_items[:12]
        if len(items) <= 6:
            lf, vf = _graphic_font(18, bold=True), _graphic_font(20, bold=True, mono=True)
            for idx, item in enumerate(items):
                _draw_statcast_bar(item, 82, 138, 238, 790, 820, 158, y + idx * 43, lf, vf)
        else:
            per_col = (len(items) + 1) // 2
            lf, vf = _graphic_font(16, bold=True), _graphic_font(16, bold=True, mono=True)
            for idx, item in enumerate(items):
                if idx < per_col:
                    _draw_statcast_bar(item, 76, 116, 198, 440, 450, 84, y + idx * 43, lf, vf)
                else:
                    _draw_statcast_bar(item, 558, 116, 680, 922, 932, 92, y + (idx - per_col) * 43, lf, vf)

    read_y0 = 824 if statcast_items else 438
    read_font = _graphic_font(24 if not category_items else 22)
    read_lines = _graphic_wrap_read_text(draw, fields["read_text"], read_font, 890, max_lines=5)
    if statcast_items:
        read_y1 = 1120 if category_items else 1238
        category_y0, category_y1 = 1146, 1238 + category_extra
    else:
        read_y1 = min(1238, read_y0 + 104 + len(read_lines) * 32)
        category_y0, category_y1 = read_y1 + 26, read_y1 + 118 + category_extra
    _graphic_glass_panel(img, draw, (48, read_y0, 1032, read_y1), radius=12)
    draw.text((74, read_y0 + 30), fields["read_label"], fill=muted, font=_graphic_font(20, bold=True))
    for idx, line in enumerate(read_lines):
        draw.text((74, read_y0 + 72 + idx * 32), line, fill=text, font=read_font)

    if category_items:
        _graphic_glass_panel(img, draw, (48, category_y0, 1032, category_y1), radius=12)
        summary = fields["category_summary"]
        title = "CATEGORY BREAKDOWN (z-SCORE)"
        if summary:
            title = f"{title} - {summary}"
        draw.text((74, category_y0 + 16), _graphic_fit_text(draw, title, _graphic_font(16, bold=True), 890), fill=muted, font=_graphic_font(16, bold=True))
        for idx, item in enumerate(category_items):
            col, row_num = idx % 4, idx // 4
            x = 74 + col * 235
            box_y0 = category_y0 + 40 + row_num * 54
            z = float(item["z"] or 0)
            z_color = green if z > 0 else bar_low if z < 0 else text
            draw.rounded_rectangle((x, box_y0, x + 205, box_y0 + 46), radius=8, fill=card_2, outline=(44, 46, 54), width=1)
            draw.text((x + 14, box_y0 + 5), _graphic_fit_text(draw, item["label"], _graphic_font(12, bold=True), 176), fill=muted, font=_graphic_font(12, bold=True))
            draw.text((x + 14, box_y0 + 22), f"{z:+.1f}", fill=z_color, font=_graphic_font(18, bold=True, mono=True))

    _graphic_footer(draw, right_note=fields["footer_note"], card_height=height)

    output = io.BytesIO()
    img.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _dynasty_player_card_png(row, context):
    """Render a single dynasty player card from the dynasty detail context."""
    return _player_value_card_png(row, context, "dynasty")


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
    raw_preset = args.get("preset")
    preset_value_enabled = os.environ.get("VALUCAST_DYNASTY_PRESET_VALUE", "1") == "1"
    active_preset = (
        raw_preset
        if (preset_value_enabled and raw_preset in DYNASTY_VALUE_PRESETS)
        else None
    )
    value_of = (lambda r: r.value_for(active_preset)) if active_preset else None
    rows = dd_store.filter(pool=pool or None, position=position or None, search=search or None)
    now_dollars = (
        _custom_dynasty_values(tuple(cats), tuple(pcats), settings.teams, settings.budget)
        if custom_cats_active else {}
    )
    if active_preset:
        rows = sorted(
            rows,
            key=lambda row: (-value_of(row), row.dynasty_rank, row.name),
        )
    elif rank_by == "now":
        rows = sorted(
            rows,
            key=lambda row: (
                row.id not in now_dollars,
                -now_dollars.get(row.id, 0.0),
                row.dynasty_rank,
            ),
        )
    rows = rows[:200]
    if active_preset:
        preset_rank_rows = sorted(
            dd_store.get_all(),
            key=lambda row: (-value_of(row), row.dynasty_rank, row.name),
        )
        preset_rank_by_id = {
            row.id: position for position, row in enumerate(preset_rank_rows, 1)
        }
    else:
        preset_rank_by_id = {}
    # `active_preset` (not the value_of closure) is the cache identity: it fully
    # determines value_of above, and it's a stable string/None.
    dynasty_dollars, tiers = _dynasty_metadata(settings, preset=active_preset)
    summary = f"{settings.summary()} · {_dynasty_category_summary(cats, pcats)}"
    return {
        "mode": "dd_dynasty",
        "pool": pool,
        "position": position,
        "search": search,
        "dd_rows": rows,
        "dyn_z_map": _dynasty_z_map(),
        "dyn_stats_map": _dynasty_stats_map(),
        # Stat columns follow the active category selection (7/2: they were
        # pinned to the classic 10, so preset swaps never changed the board).
        "dyn_stat_cats": tuple(cats) + tuple(pcats),
        "dyn_stat_labels": _CAT_DISPLAY_LABELS,
        "dynasty_dollars": dynasty_dollars,
        "now_dollars": now_dollars,
        "custom_cats_active": custom_cats_active,
        "rank_by": rank_by,
        "cats": cats,
        "pcats": pcats,
        "hitting_categories": HITTING_CATEGORIES,
        "pitching_categories": PITCHING_CATEGORIES,
        "category_presets": DYNASTY_CATEGORY_PRESETS,
        "active_preset": active_preset,
        "preset_rank_by_id": preset_rank_by_id,
        "preset_value_enabled": preset_value_enabled,
        "dynasty_value_presets": list(DYNASTY_VALUE_PRESETS),
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


def _apply_redraft_pitcher_anchor(results: list[ValuationResult]) -> list[ValuationResult]:
    return [
        dc_replace(result, total_value=result.total_value * REDRAFT_PITCHER_ANCHOR)
        if result.player.pool in _PITCHER_POOLS and result.total_value > 0
        else result
        for result in results
    ]


def _redraft_value_players(players, config) -> list[ValuationResult]:
    return _apply_redraft_pitcher_anchor(
        _merge_two_way_players(engine.value_players(players, config))
    )


def _redraft_value_scale(results: list[ValuationResult]) -> tuple[float, float]:
    values = [
        float(result.total_value)
        for result in results
        if isinstance(result.total_value, (int, float)) and math.isfinite(result.total_value)
    ]
    if not values:
        return 0.0, 0.0
    return _percentile(values, 0.05), max(values)


def _redraft_scaled_value(value, scale: tuple[float, float] | None):
    if not isinstance(value, (int, float)):
        return None
    floor, ceiling = scale or (0.0, 0.0)
    return _scale_value(float(value), floor, ceiling)


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


_REDRAFT_BUNDLE_CACHE: OrderedDict[tuple, dict] = OrderedDict()
# weights/pt params are raw user input -> unbounded key space; bound the LRU so a
# fuzzed query stream can't grow this without limit on the 512MB worker.
_REDRAFT_BUNDLE_MAX = 16


def _redraft_board_bundle(active, config, source_name, generation,
                          mode, cats_t, pcats_t, rules_str, pt_t, split_rp, weights_t):
    """Value the canonical universe and its display metadata once per
    (source, config) generation. Everything here depends ONLY on the active
    store and the config — never on pool/position/search filter args — so it's
    safe to memoize across every filtered view of the same board. The key
    includes the store's generation (`active.as_of`), so a daily refresh (new
    `as_of`) misses and recomputes; nothing can go stale within a process.
    Cached objects are treated as immutable by callers (filtering rebinds new
    lists; it never mutates `all_results`/`metadata_pool`/the metadata dicts)."""
    key = (source_name, generation, mode, cats_t, pcats_t, rules_str, pt_t,
           split_rp, weights_t)
    hit = _REDRAFT_BUNDLE_CACHE.get(key)
    if hit is not None:
        return hit
    all_results = _redraft_value_players(_valuation_players(active_store=active), config)
    all_results.sort(key=lambda r: r.total_value, reverse=True)
    redraft_value_scale = _redraft_value_scale(all_results)
    metadata_pool = all_results[:200]
    position_ranks = _compute_position_ranks(metadata_pool)
    dollar_values = _compute_dollar_values(metadata_pool)
    tiers = _compute_tiers(metadata_pool)
    overall_ranks = {r.player.id: i for i, r in enumerate(all_results, 1)}
    canonical_ids = {r.player.id for r in all_results}
    bundle = {
        "all_results": all_results,
        "redraft_value_scale": redraft_value_scale,
        "metadata_pool": metadata_pool,
        "position_ranks": position_ranks,
        "dollar_values": dollar_values,
        "tiers": tiers,
        "overall_ranks": overall_ranks,
        "canonical_ids": canonical_ids,
    }
    _REDRAFT_BUNDLE_CACHE[key] = bundle  # single-reference assign, fully built above
    while len(_REDRAFT_BUNDLE_CACHE) > _REDRAFT_BUNDLE_MAX:
        try:
            _REDRAFT_BUNDLE_CACHE.popitem(last=False)
        except KeyError:
            break
    return bundle


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

    # Collect pt_* params for points mode. Same guard as the w_* weights below:
    # raw query params, so `pt_HR=abc` must not 500 and `pt_HR=inf` must not
    # poison the valuation with non-finite point values (7/2 audit).
    # Suffixes outside _POINT_STAT_IDS are DROPPED: any param that affects
    # rendering must be in the PNG cache-key vocabulary, and the cache collapses
    # unknown pt_ suffixes to the canonical key. A real-but-unlisted stat like
    # pt_AB would render a different card under the canonical key — a poisoned
    # PNG served to every legit request. Dropping it here makes unknown pt_
    # params render-inert, so the key collapse is sound.
    pt_params = {}
    for key in args:
        if key.startswith("pt_"):
            stat = key[3:]
            if stat not in _POINT_STAT_IDS:
                continue
            try:
                pts = float(args[key])
            except ValueError:
                continue
            if math.isfinite(pts):
                pt_params[stat] = pts

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
    # change the pool the metadata is computed on. The whole bundle (results, scale,
    # metadata_pool, $/ranks/tiers, overall ranks) depends only on (source, config)
    # generation, so it is memoized per that key — filtering below rebinds new lists
    # and never mutates the cached objects.
    bundle = _redraft_board_bundle(
        active, config,
        args.get("source", "") or "steamer", active.as_of,
        mode, tuple(cats), tuple(pcats), rules_str,
        tuple(sorted(pt_params.items())), split_rp,
        tuple(sorted(weights.items())),
    )
    all_results = bundle["all_results"]
    redraft_value_scale = bundle["redraft_value_scale"]
    # Metadata pool = the fixed top-200-by-value of the full universe (the same set the
    # default unfiltered board shows). Computing $/ranks/tiers here keeps the default
    # board byte-identical AND makes filtered views show the SAME numbers.
    metadata_pool = bundle["metadata_pool"]

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
        query = fold_search(search)
        results = [r for r in results if query in fold_search(r.player.name)]
        if not results:
            # Sub-threshold name match: value it on demand for display (no metadata).
            search_keep = {p.id for p in active.get_all() if query in fold_search(p.name)}
            if search_keep:
                extra = _redraft_value_players(
                    _valuation_players(search_keep, active_store=active), config
                )
                results = [r for r in extra if query in fold_search(r.player.name)]

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

    # Position ranks, auction dollar values, and tier visualization (from the bundle).
    position_ranks = bundle["position_ranks"]
    dollar_values = bundle["dollar_values"]
    tiers = bundle["tiers"]

    # Overall rank from the canonical universe (filter-independent). Players not in the
    # canonical universe (sub-threshold search matches) are below the valuation floor:
    # they show a projection but no rank/value/$/tier.
    overall_ranks = bundle["overall_ranks"]
    canonical_ids = bundle["canonical_ids"]

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
        "redraft_value_scale": redraft_value_scale,
        "config_summary": _config_summary(mode, cats, pcats, split_rp),
        "as_of": active.as_of,
        "source": args.get("source", "") or "steamer",
        "display": display,
        "horizon": _horizon_of(mode),
        "active_store": active,
    }


def _front_door_digest():
    """"Today on ValuCast" strip — assembled from the same committed artifacts
    the deep pages render, so every line deep-links to its source. Every slot
    is optional: a missing/corrupt artifact just drops its cell, and an empty
    dict hides the strip entirely. Counts only from the AOTC scorecard — the
    headline RATE stays behind the pre-registered gate."""
    digest = {}
    movers = _load_movers_payload()
    rising = [r for r in (movers.get("rising") or []) if isinstance(r, dict)]
    cooling = [r for r in (movers.get("cooling") or []) if isinstance(r, dict)]
    if rising:
        digest["risers"] = rising[:2]
        digest["mover_window"] = next(
            (r.get("window_days") for r in rising if r.get("window_days")), 10)
    if cooling:
        digest["faller"] = cooling[0]
    pulse = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_call_up_pulse.json"
    ) or {}
    call_ups = [c for c in (pulse.get("call_ups") or []) if isinstance(c, dict)]
    if call_ups:
        digest["callup_count"] = len(call_ups)
        digest["callup_top"] = min(
            call_ups, key=lambda c: c.get("prospect_rank") or 10 ** 6)
    buys = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_prospect_buys.json"
    ) or {}
    board = buys.get("board") or []
    if board and isinstance(board[0], dict) and board[0].get("name"):
        digest["top_buy"] = board[0]
    scorecard = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_ahead_of_consensus_scorecard.json"
    ) or {}
    calls = [c for c in (scorecard.get("calls") or []) if isinstance(c, dict)]
    if calls:
        newest = max(calls, key=lambda c: str(c.get("ahead_since") or ""))
        if newest.get("name") and newest.get("ahead_since"):
            digest["newest_call"] = newest
    funnel = scorecard.get("funnel") or {}
    total = (scorecard.get("summary") or {}).get("ever_flagged")
    if funnel and total:
        digest["ledger"] = {
            "total": total,
            "wins": (funnel.get("open_toward") or 0) + (funnel.get("closed_caught_up") or 0),
            "losses": funnel.get("open_away") or 0,
            "retreats": funnel.get("retired_we_backed_off") or 0,
        }
    return digest


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
            ctx["today_digest"] = _front_door_digest()
            return render_template("index.html", **ctx)
        ctx = _build_dynasty_context(request.args)
        if mode == "prospects":
            _apply_prospect_board_context(ctx, request.args)
        ctx["snapshot_stale"] = dynasty_data_source == "valucast_public_snapshot_stale"
        ctx["today_digest"] = _front_door_digest()
        return render_template("index.html", **ctx)
    ctx = _build_context(request.args)
    ctx["dd_available"] = dd_store.is_available
    ctx["today_digest"] = _front_door_digest()
    return render_template("index.html", **ctx)


@app.route("/rankings")
def rankings():
    if _browser_direct_partial_request():
        return _redirect_home(request.args.to_dict(flat=False))
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
        if ctx.get("callups"):
            params["callups"] = ctx["callups"]
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
    if _browser_direct_partial_request():
        args = request.args.to_dict(flat=False)
        args.setdefault("mode", ["dd_dynasty"])
        return _redirect_home(args)
    current = parse_league_settings(request.args)
    cats, pcats, _ = _dynasty_category_state(request.args)
    setup_context = {
        "cats": cats,
        "pcats": pcats,
        "hitting_categories": HITTING_CATEGORIES,
        "pitching_categories": PITCHING_CATEGORIES,
        "category_presets": DYNASTY_CATEGORY_PRESETS,
    }
    # Rightmost XFF hop is the one Render's proxy appended; the leftmost is
    # client-supplied and made the rate limit trivially spoofable.
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = (forwarded.split(",")[-1].strip() if forwarded
          else (request.remote_addr or "?"))
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
    # A bad daily refresh must never 500 the site (7/2 audit): every sibling
    # route degrades on a missing/corrupt artifact -- this one did not.
    try:
        scorecard = _json.loads(
            (Path(__file__).parent / "data" / "validation" / "methodology_scorecard.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        scorecard = None
    try:
        sensitivity = _json.loads(
            (Path(__file__).parent / "data" / "validation" / "sensitivity_scorecard.json")
            .read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        sensitivity = None
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
        sensitivity=sensitivity,
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


def _index_milb_season_stats(payload: dict | None) -> dict[str, list[dict]]:
    indexed: dict[str, list[dict]] = {}
    if not isinstance(payload, dict):
        return indexed
    for bucket in ("hitters", "pitchers"):
        for row in payload.get(bucket) or ():
            if not isinstance(row, dict):
                continue
            mlbam_id = row.get("mlbam_id")
            if mlbam_id in (None, ""):
                continue
            indexed.setdefault(str(mlbam_id), []).append(row)
    return indexed


MILB_SEASON_STATS_BY_MLBAM = _index_milb_season_stats(
    _load_artifact(
        Path(__file__).parent / "data" / "prospects" / "raw" / "milb_season_stats.json"
    )
)


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


def _ahead_of_consensus_for_key(key) -> dict | None:
    if not key:
        return None
    payload = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_ahead_of_consensus.json"
    )
    if not isinstance(payload, dict):
        return None

    key = str(key)
    receipt = {}
    divergence = payload.get("divergence_by_identity") or {}
    if isinstance(divergence, dict) and isinstance(divergence.get(key), dict):
        receipt.update(divergence[key])

    for row in payload.get("ahead_of_consensus") or []:
        if isinstance(row, dict) and str(row.get("identity_key") or "") == key:
            receipt.update(row)
            break

    if not receipt:
        return None
    return {
        "valucast_rank": receipt.get("valucast_rank"),
        "consensus_rank": receipt.get("consensus_rank"),
        "divergence": receipt.get("divergence"),
        "board_count": receipt.get("board_count"),
        "days_ahead": receipt.get("days_ahead"),
        "ahead_since": receipt.get("ahead_since"),
        "ahead_since_is_archive_start": receipt.get("ahead_since_is_archive_start"),
    }


def _ahead_of_consensus_receipt_text(receipt) -> str | None:
    if not isinstance(receipt, dict):
        return None
    try:
        divergence = int(receipt.get("divergence"))
    except (TypeError, ValueError):
        return None
    if divergence <= 0:
        return None
    try:
        valucast_rank = int(receipt.get("valucast_rank"))
        consensus_rank = int(receipt.get("consensus_rank"))
    except (TypeError, ValueError):
        return None

    text = (
        f"AHEAD OF THE CURVE \u2014 VC #{valucast_rank} "
        f"vs field ~#{consensus_rank} \u00b7 +{divergence}"
    )
    try:
        days_ahead = int(receipt.get("days_ahead"))
    except (TypeError, ValueError):
        days_ahead = 0
    if days_ahead > 0 and receipt.get("ahead_since"):
        # "+" when the streak reaches the archive's first day: the true streak may
        # predate our records, so the number is a floor, not an origin.
        suffix = "+" if receipt.get("ahead_since_is_archive_start") else ""
        text = f"{text} \u00b7 {days_ahead}d{suffix} early"
    return text


def _card_consensus_value(receipt, fg_scouting, row=None) -> str | None:
    """Consensus-rank value for the share card: the ahead-receipt's multi-board
    number when ValuCast has one, else the row's public-board median (~#N — deep
    boards rank past 100, so the divergence stays quantified instead of hiding
    behind 'outside top 100'), else the honest fallbacks: silent if FanGraphs
    ranks him (we'd mislabel a listed player), 'outside top 100' when no public
    board has him at all."""
    if isinstance(receipt, dict):
        try:
            return f"#{int(receipt.get('consensus_rank'))}"
        except (TypeError, ValueError):
            pass
    consensus = getattr(row, "public_source_consensus", None)
    if consensus:
        # Board count keeps the claim honest — "~#512" from one deep board reads
        # very differently from a 4-board median, and says so on the card.
        n = len(getattr(row, "public_source_ranks", None) or {})
        return f"~#{int(consensus)} ({n} board{'s' if n != 1 else ''})"
    if (fg_scouting or {}).get("fg_top100"):
        return None
    return "outside top 100"


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


def _role_tracker_profile_for_row(indexed: dict[str, dict], row) -> dict | None:
    mlbam_id = getattr(row, "mlbam_id", None)
    role = str(getattr(row, "role", "") or "").strip().lower()
    if role == "pitcher":
        roles = ("pitcher", "starter", "reliever")
    elif role == "two_way":
        roles = ("hitter", "pitcher")
    else:
        roles = (role,)
    for profile_role in roles:
        profile = indexed.get(_identity_key(mlbam_id, profile_role))
        if profile:
            return profile
    return None


def _artifact_context_for_row(row) -> dict:
    key = _row_identity_key(row)
    if not key:
        return {}
    root = Path(__file__).parent / "data" / "models"
    ahead_of_consensus = _ahead_of_consensus_for_key(key)
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
    role_profiles = _indexed_artifact_rows(
        _load_artifact(root / "valucast_playing_time_role_tracker.json"), "profiles"
    )
    role_profile = _role_tracker_profile_for_row(role_profiles, row)
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
        "ahead_of_consensus": ahead_of_consensus,
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
        needle = fold_search(filters["q"])
        reports = [
            row for row in reports
            if needle in fold_search(row.get("name"))
            or needle in fold_search(row.get("team"))
            or needle in fold_search(" ".join(str(p) for p in row.get("positions") or ()))
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
    """Full prospect pool for org boards; intentionally not the public top-200 slice.

    Deduped by player identity (7/6): a two-way player has separate hitter/pitcher
    store rows sharing one mlbam_id (e.g. Sean Barnett, SDP). Undeduped, every count
    downstream (org pool size, the picker pill, the top-N slice) double-counts them,
    and a two-way player ranked inside an org's top-N would render as two identical
    rows. Kept the best-ranked (first, since rows are sorted below) role per player.
    """
    if rows is None:
        if not dd_store.is_available:
            return []
        rows = dd_store.filter(pool="prospect")
    rows = [
        row for row in rows
        if _team_board_org_for(row) is not None
    ]
    rows = sorted(rows, key=_team_board_prospect_sort_key)
    seen = set()
    deduped = []
    for row in rows:
        mlbam_id = getattr(row, "mlbam_id", None)
        key = str(mlbam_id) if mlbam_id not in (None, "") else f"name:{str(getattr(row, 'name', '') or '').casefold()}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


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
    label = getattr(row, "eta_display", None)
    if label:
        return f"ETA {label}"
    eta = getattr(row, "eta", None)
    if eta not in (None, ""):
        return f"ETA {eta}"
    label = eta_window_label(_team_board_eta_window(row))
    return f"ETA {label}" if label else ""


def _team_board_eta_window(row):
    metadata = getattr(row, "metadata", None)
    if isinstance(metadata, dict) and metadata.get("eta_window"):
        return metadata["eta_window"]
    peak = getattr(row, "peak_projection_context", None)
    if isinstance(peak, dict) and peak.get("eta_window"):
        return peak["eta_window"]
    return prospect_eta_window({"eta": getattr(row, "eta", None), "level": _team_board_level(row)})


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
    level = _team_board_level(row)
    affiliate = _team_board_affiliate(row)
    return {
        "org_rank": org_rank,
        "name": name,
        "id": str(getattr(row, "id", "") or ""),
        "team": org,
        "team_name": _team_board_org_name(org),
        "position": _team_board_position(row),
        "level": level,
        "level_sort": LEVEL_ORDER.get(level, 0),
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
        window = _team_board_eta_window(row)
        try:
            eta_year = int(window)
        except (TypeError, ValueError):
            if window in {"now", "near_term"}:
                return "This year"
            if window == "one_to_two_years":
                return "Next year"
            if window in {"two_to_three_years", "long_range"}:
                return "Later"
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


def _team_board_callups(org_rows, movements, debuted_ids, pulse_keys, *, limit=5):
    candidates = [
        row for row in org_rows
        if _team_board_level(row) in _TEAM_BOARD_CALLUP_LEVELS
        and not _prospect_has_debuted(row, debuted_ids, pulse_keys)
    ]
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
    debuted_ids = _debuted_prospect_ids()
    pulse_keys = _call_up_pulse_keys()
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
        "callups": _team_board_callups(org_rows, movements, debuted_ids, pulse_keys),
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
    tiers = _prospect_tiers() if dd_store.is_available else {}
    all_prospects = _prospect_rows() if dd_store.is_available else []
    debuted_ids = _debuted_prospect_ids()
    pulse_keys = _call_up_pulse_keys()
    # The debut/level filter pills are client-side only (no server round trip), so a
    # naive top-100-of-everyone slice starves a filtered view: if 30 of the top 100
    # have already debuted, "Not debuted" only ever has 70 rows to show, even though
    # there are genuinely top-100-worthy undebuted prospects ranked 101+. Walk the
    # full ranked pool (true rank preserved per row, NOT re-enumerated) until both the
    # debuted and undebuted subsets independently reach 100 -- same "repopulate to
    # full depth" fix the main board already applies via row_filter-before-slice
    # (_apply_prospect_board_context).
    ranked_prospect_rows = []
    if dd_store.is_available:
        seen_debuted = 0
        seen_undebuted = 0
        for true_rank, row in enumerate(all_prospects, 1):
            if _prospect_has_debuted(row, debuted_ids, pulse_keys):
                if seen_debuted >= 100:
                    continue
                seen_debuted += 1
            else:
                if seen_undebuted >= 100:
                    continue
                seen_undebuted += 1
            ranked_prospect_rows.append((true_rank, row))
            if seen_debuted >= 100 and seen_undebuted >= 100:
                break

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
        return _team_board_eta(row)

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
        return _team_board_year_bucket(row)

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
    for rank, row in ranked_prospect_rows:
        key = identity_for(row)
        signal = signal_by_key.get(key) or signal_by_mlbam.get(str(getattr(row, "mlbam_id", "")))
        link_fields = player_link_fields(row.name, row.id)
        level = level_for(row)
        rankings.append({
            # Debut filter: shared predicate (active roster / MLB service / pulse).
            "debuted": _prospect_has_debuted(row, debuted_ids, pulse_keys),
            "rank": rank,
            "name": row.name,
            **link_fields,
            "report_url": report_url(row.name),
            "position": position_for(row),
            "affiliate": affiliate_for(row),
            "eta": eta_for(row),
            "level": level or "-",
            "level_sort": LEVEL_ORDER.get(level, 0),
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
        and not _prospect_has_debuted(row, debuted_ids, pulse_keys)
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

    # "Got the Call" — the companion to the doorstep desk: rookie-eligible prospects who
    # have already reached an MLB active roster (so they're off the ranked minors board).
    # Top graduates show as cards; the rest fold into a "see all" dropdown so the rail
    # stays compact while still accounting for everyone.
    called_up_all = []
    for r in _active_mlb_roster_rows():
        positions = r.get("positions") or []
        pos = "/".join(str(p) for p in positions[:2] if p) or "-"
        team = r.get("mlb_team") or "-"
        val = fmt_value(r.get("score"))
        called_up_all.append({
            "name": r.get("name") or "Unknown",
            "flag": f"{team} · {pos}",
            "why": f"Val {val} · rookie-eligible",
            "status": "In the show",
            "value": val,
        })
    recently_called_up = called_up_all[:8]
    recently_called_up_more = called_up_all[8:]

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

    def _shape_aotc(raw_rows):
        shaped = []
        for row in raw_rows or []:
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
            shaped.append({
                "name": name,
                **player_link_fields(name, resolved_id or row.get("mlbam_id")),
                "valucast_rank": int(valucast_rank),
                "consensus_rank": int(consensus_rank),
                "divergence": int(divergence),
                "board_count": int(board_count) if board_count is not None else 0,
                "ahead_since": row.get("ahead_since"),
                "ahead_since_is_archive_start": bool(row.get("ahead_since_is_archive_start")),
                "days_ahead": int(row.get("days_ahead") or 0),
            })
        return shaped

    _aotc_artifact = ahead_of_consensus_artifact or {}
    ahead_of_consensus = _shape_aotc(_aotc_artifact.get("ahead_of_consensus"))
    ahead_of_consensus_thin = _shape_aotc(_aotc_artifact.get("ahead_of_consensus_thin"))

    return {
        "backfields_page": True,
        "mode": "prospects",
        "as_of": dd_store.generated_at,
        "dd_available": dd_store.is_available,
        "rankings": rankings,
        "risers": risers,
        "callups": callups,
        "recently_called_up": recently_called_up,
        "recently_called_up_more": recently_called_up_more,
        "recently_called_up_total": len(_active_mlb_roster_rows()),
        "stats": {
            "hitting": hitting_stats,
            "pitching": pitching_stats,
        },
        "team_boards": _build_team_board_context(),
        "scouting_reports": scouting_reports,
        "ahead_of_consensus": ahead_of_consensus,
        "ahead_of_consensus_thin": ahead_of_consensus_thin,
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


_ACTIVE_ROSTER_ROWS = None
_ACTIVE_ROSTER_PULSE_PATH = Path(__file__).parent / "data" / "models" / "valucast_call_up_pulse.json"


def _active_mlb_roster_rows():
    """Rookie-eligible prospects currently on an MLB active roster — the 'Got the
    Call' companion to the Call-Up Desk. Sourced from the served snapshot's RETAINED
    rows (7/2): rookie-rule retention keeps these players ranked on the board, so
    the rank artifact's active_mlb_roster_board is graduates-only and correctly
    empty — reading it here showed a false '0 rookie-eligible in the majors'.

    Keyed on the call-up pulse file's mtime (7/6): the pulse refreshes intraday,
    independent of the morning build, so a bare "compute once" cache could freeze a
    long-lived worker's answer from before a same-day promotion. Without this, a
    freshly-pulsed player could show debuted=True in the rankings (which reads the
    pulse through the mtime-aware _load_artifact) while still missing from 'Got the
    Call' and undercounted in recently_called_up_total — two facts about the same
    player disagreeing purely from cache-freshness skew, not real data.
    """
    global _ACTIVE_ROSTER_ROWS
    try:
        pulse_stamp = _ACTIVE_ROSTER_PULSE_PATH.stat().st_mtime_ns
    except OSError:
        pulse_stamp = None
    if _ACTIVE_ROSTER_ROWS is not None and _ACTIVE_ROSTER_ROWS[0] == pulse_stamp:
        return _ACTIVE_ROSTER_ROWS[1]
    rows = []
    seen = set()
    if dd_store.is_available:
        for r in dd_store.get_all():
            if getattr(r, "is_prospect", False) and getattr(r, "active_mlb_callup", False):
                seen.add(_row_identity_key(r) or "")
                rows.append({
                    "name": getattr(r, "name", None),
                    "positions": list(getattr(r, "positions", None) or []),
                    "mlb_team": getattr(r, "mlb_team", None) or getattr(r, "team", None),
                    "score": getattr(r, "value", None),
                })
        # Same-day pulse call-ups: promoted AFTER the morning feed build, so
        # the feed flag doesn't know them yet (7/3: Jim Jarvis was invisible
        # here for a day). The pulse entry is thin — enrich from the feed row.
        row_by_key = {_row_identity_key(r): r for r in dd_store.get_all()}
        pulse = _load_artifact(_ACTIVE_ROSTER_PULSE_PATH) or {}
        for key, entry in (pulse.get("by_identity") or {}).items():
            if not isinstance(entry, dict) or key in seen:
                continue
            r = row_by_key.get(key)
            rows.append({
                "name": entry.get("name") or (getattr(r, "name", None) if r else None) or "Unknown",
                "positions": (list(getattr(r, "positions", None) or []) if r else [])
                             or ([entry.get("position")] if entry.get("position") else []),
                "mlb_team": entry.get("mlb_team")
                            or (getattr(r, "mlb_team", None) or getattr(r, "team", None) if r else None),
                "score": getattr(r, "value", None) if r else None,
            })
    result = sorted(rows, key=lambda r: r.get("score") or 0, reverse=True)
    _ACTIVE_ROSTER_ROWS = (pulse_stamp, result)
    return result


_DEBUTED_PROSPECT_IDS = None
_DEBUTED_PROSPECT_IDS_PATH = Path(__file__).parent / "data" / "prospects" / "prospect_model_inputs.json"


def _debuted_prospect_ids():
    """{mlbam(str): taste} for rookie-eligible prospects who have logged MLB service
    (graduated=False) — taste is the MLB sample so far, e.g. '2 PA' or '27 IP'.
    Powers the backfields 'MLB · <taste>' badge. Sourced offline from the model inputs.

    Keyed on this file's mtime (7/6) — same cache-freshness fix as
    _active_mlb_roster_rows, so a rebuilt prospect_model_inputs.json is picked up by
    a long-lived worker instead of frozen from its first-ever read."""
    global _DEBUTED_PROSPECT_IDS
    try:
        stamp = _DEBUTED_PROSPECT_IDS_PATH.stat().st_mtime_ns
    except OSError:
        stamp = None
    if _DEBUTED_PROSPECT_IDS is not None and _DEBUTED_PROSPECT_IDS[0] == stamp:
        return _DEBUTED_PROSPECT_IDS[1]
    try:
        svc = (json.loads(_DEBUTED_PROSPECT_IDS_PATH.read_text(encoding="utf-8")) or {}).get("mlb_service") or []
    except (OSError, ValueError):
        svc = []
    out = {}
    for s in svc:
        if not isinstance(s, dict) or s.get("mlbam_id") is None or s.get("graduated"):
            continue
        pa, ip = s.get("pa") or 0, s.get("ip") or 0
        if pa > 0:
            out[str(s["mlbam_id"])] = f"{int(pa)} PA"
        elif ip > 0:
            out[str(s["mlbam_id"])] = f"{ip:g} IP"
    _DEBUTED_PROSPECT_IDS = (stamp, out)
    return out


def _row_mlb_debut(row):
    """MLB-taste string ('2 PA' / '27 IP') if this row's player has debuted, else None."""
    mid = next((p for p in str(row.get("id", "")).split("_") if p.isdigit()), None)
    return _debuted_prospect_ids().get(mid) if mid else None


def _call_up_pulse_keys() -> frozenset:
    """Identity keys ('687312_pitcher') on a fresh MLB active roster per the
    same-day call-up pulse — called up AFTER the morning feed build, so neither
    active_mlb_callup nor the MLB-service taste knows them yet."""
    pulse = _load_artifact(
        Path(__file__).parent / "data" / "models" / "valucast_call_up_pulse.json"
    ) or {}
    return frozenset(pulse.get("by_identity") or ())


def _prospect_has_debuted(row, debuted_ids, pulse_keys) -> bool:
    """The ONE debut predicate for every surface (board filter, share cards,
    backfields). 7/3 bug: the filter didn't check the same-day pulse, so the
    'Not debuted' board kept players the UI was simultaneously badging
    CALLED UP (Gabriel Hughes) — filter and badge must read the same sources."""
    return bool(
        getattr(row, "active_mlb_callup", False)
        or str(getattr(row, "mlbam_id", "")) in debuted_ids
        or (_row_identity_key(row) or "") in pulse_keys
    )


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
        fitted_name = _graphic_fit_text(draw, row["name"], name_font, 470)
        draw.text((118, name_y), fitted_name, fill=text, font=name_font)
        debut_taste = _row_mlb_debut(row)
        if debut_taste:
            label = f"MLB · {debut_taste}"
            bx = 118 + _graphic_text_width(draw, fitted_name, name_font) + 12
            bw = _graphic_text_width(draw, label, small_font) + 14
            by = name_y + 4
            draw.rounded_rectangle((bx, by, bx + bw, by + 20), radius=5, fill=warm_card_2, outline=slate, width=1)
            draw.text((bx + 7, by + 3), label, fill=muted, font=small_font)
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
        try:
            limit = max(5, min(25, int(request.args.get("n", 20))))
        except (TypeError, ValueError):
            limit = 20  # `n=abc` is a bad link, not a 500
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


_VALUE_MAP_CACHE = (None, None)  # (generation_key, players) — swapped atomically


def _value_map_payload():
    """Memoized value-map payload, keyed on the DD feed generation. The map's
    three consumers (/map, /api/value-map-players, the share card) all read this
    ~2,700-row list built from the full dd_store; it changes only on a daily
    refresh (new `generated_at`). Consumers treat the list as read-only."""
    global _VALUE_MAP_CACHE
    key = dd_store.generated_at
    cached_key, cached_players = _VALUE_MAP_CACHE  # one read of the tuple ref
    if cached_key == key and cached_players is not None:
        return cached_players
    players = _value_map_players(dd_store.get_all()) if dd_store.is_available else []
    # Build the (key, players) pair fully, then swap the tuple in one assignment
    # (no key-before-payload window under --threads 4; worst case = duplicate build).
    _VALUE_MAP_CACHE = (key, players)
    return players


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
    players = _value_map_payload()
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
    players = _value_map_payload()
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
    players = _value_map_payload()
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


def _load_movers_payload(path=VALUCAST_MOVERS_PATH):
    payload = _load_artifact(Path(path))
    return payload if isinstance(payload, dict) else {}


def _build_movers_page_context(window=None):
    payload = _load_movers_payload()
    # Window presets are precomputed in the artifact (never crunched per
    # request). Fail-soft to the default board when the artifact predates the
    # feature, and report the window we actually served so the pills stay honest.
    sides = payload
    if window:
        windowed = (payload.get("windows") or {}).get(f"{window}d")
        if windowed:
            sides = windowed
        else:
            window = None
    rising = list(sides.get("rising") or [])
    cooling = list(sides.get("cooling") or [])
    generated_at = payload.get("generated_at")
    return {
        "rising": rising,
        "cooling": cooling,
        "mover_count": len(rising) + len(cooling),
        "movers_available": bool(payload),
        "movers_generated_at": generated_at,
        "movers_summary": payload.get("summary") or {},
        "movers_validation": payload.get("validation") or {},
        "movers_window": window,
        "movers_window_choices": SPARK_WINDOW_CHOICES,
        "as_of": generated_at or store.as_of,
    }


@app.route("/movers")
def movers():
    context = _build_movers_page_context(
        window=_parse_spark_window(request.args.get("window")) or DEFAULT_MOVER_WINDOW
    )
    return render_template("movers.html", **context)


def _movers_share_card_png(rising, cooling, *, generated_at=None):
    """Deterministic server-side Prospect Movers graphic."""
    import io as _io
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    palette = _GRAPHIC_PALETTE
    bg = palette["bg"]
    card = palette["card"]
    card_2 = palette["card_2"]
    border = palette["border"]
    green = palette["green"]
    red = palette["clay"]
    text = palette["text"]
    muted = palette["muted"]
    blue = palette["blue"]

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    date_label = _editorial_date(generated_at)
    # Window comes from the artifact rows — a hardcoded "7-day" shipped while the
    # metric actually ran 10 days, contradicting the per-row labels (7/2).
    window = next(
        (r.get("window_days") for r in list(rising) + list(cooling) if r.get("window_days")),
        10,
    )
    subtitle = f"Biggest {window}-day risers & fallers on the prospect board"
    if date_label:
        subtitle = f"{subtitle} - {date_label}"
    _graphic_header(
        img,
        draw,
        headline="PROSPECT MOVERS",
        subtitle=subtitle,
        extra_line="Real, sustained moves - model re-baselines filtered out",
        tagline="Prospect Movers",
    )

    f_section = _graphic_font(28, bold=True)
    f_rank = _graphic_font(17, bold=True, mono=True)
    f_name = _graphic_font(22, bold=True)
    f_meta = _graphic_font(14)
    f_delta = _graphic_font(21, bold=True, mono=True)
    f_why = _graphic_font(13)
    row_h = 78

    def draw_section(title, rows, x, y, w, color):
        draw.rounded_rectangle((x, y, x + w, y + 926), radius=10, fill=card, outline=border, width=1)
        draw.text((x + 20, y + 18), title, fill=color, font=f_section)
        if not rows:
            draw.text((x + 20, y + 98), "Sparse board: no clean movers passed +/-2.0.", fill=muted, font=f_name)
            return
        for idx, row in enumerate(rows[:12]):
            top = y + 70 + idx * row_h
            fill = card_2 if idx % 2 == 0 else card
            draw.rectangle((x + 1, top, x + w - 1, top + row_h), fill=fill)
            if idx:
                draw.line((x + 16, top, x + w - 16, top), fill=border, width=1)
            rank = f"#{row.get('current_rank') or '-'}"
            draw.text((x + 18, top + 14), rank, fill=blue, font=f_rank)
            delta = row.get("score_delta")
            try:
                delta_text = f"{float(delta):+.1f}"
            except (TypeError, ValueError):
                delta_text = "--"
            draw.text((x + w - 18 - _graphic_text_width(draw, delta_text, f_delta), top + 10), delta_text, fill=color, font=f_delta)
            draw.text((x + 74, top + 10), _graphic_fit_text(draw, row.get("name"), f_name, 260), fill=text, font=f_name)
            meta = " - ".join(str(part) for part in (row.get("team"), row.get("pos"), row.get("level")) if part)
            draw.text((x + 74, top + 39), _graphic_fit_text(draw, row.get("movement_label") or meta, f_meta, 310), fill=muted, font=f_meta)
            why = row.get("why") or meta
            draw.text((x + 74, top + 58), _graphic_fit_text(draw, why, f_why, 370), fill=muted, font=f_why)

    draw_section("RISING", rising, 48, 242, 480, green)
    draw_section("COOLING", cooling, 552, 242, 480, red)
    # Same derived window as the subtitle — a literal "last 7 days" survived the
    # 7->10 subtitle fix and contradicted it on the same image (7/3 review).
    _graphic_footer(draw, right_note=f"ValuCast prospect score - last {window} days")

    out = _io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


@app.route("/movers/share-card.png")
def movers_share_card_png():
    # Honors ?window= so the graphic matches the board view it was exported
    # from; the bare og:image URL serves the same default window as the page.
    # The renderer derives its "N-day" subtitle/footer from the rows, so the
    # windowed variant labels itself correctly for free.
    context = _build_movers_page_context(
        window=_parse_spark_window(request.args.get("window")) or DEFAULT_MOVER_WINDOW
    )
    png = _movers_share_card_png(
        context["rising"],
        context["cooling"],
        generated_at=context["movers_generated_at"],
    )
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = 'inline; filename="valucast-prospect-movers.png"'
    return response


@app.route("/movers/share-card")
def movers_share_card():
    window = _parse_spark_window(request.args.get("window"))
    png_path = f"/movers/share-card.png?window={window}" if window else "/movers/share-card.png"
    html = build_share_preview_html(
        title="Prospect Movers",
        subtitle=(
            f"Biggest {window}-day risers & fallers on the prospect board"
            if window else "Biggest risers & fallers on the prospect board"
        ),
        png_url=png_path,
        filename="valucast-prospect-movers.png",
        public_png_url=_public_url(png_path),
        public_page_url=_public_url("/movers/share-card"),
        description="The biggest recent risers and fallers on the ValuCast prospect board.",
        image_alt="ValuCast Prospect Movers board",
        back_url="/movers",
        back_label="Back to Prospect Movers",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


def _load_receipts_payload(path=VALUCAST_RECEIPTS_PATH):
    payload = _load_artifact(Path(path))
    return payload if isinstance(payload, dict) else {}


def _build_receipts_page_context():
    payload = _load_receipts_payload()
    receipts = [] if RECEIPTS_HOLD else list(payload.get("receipts") or [])
    misses = [] if RECEIPTS_HOLD else list(payload.get("misses") or [])
    generated_at = payload.get("generated_at")
    return {
        "receipts": receipts,
        "receipt_count": len(receipts),
        "misses": misses,
        "miss_count": len(misses),
        "receipts_available": bool(payload) and not RECEIPTS_HOLD,
        "receipts_generated_at": generated_at,
        "as_of": generated_at or store.as_of,
    }


_LEDGER_SCORECARD_PATH = (
    Path(__file__).parent / "data" / "models" / "valucast_ahead_of_consensus_scorecard.json"
)


def _load_scorecard_payload():
    sc = _load_artifact(_LEDGER_SCORECARD_PATH)
    return sc if isinstance(sc, dict) else None


@app.route("/gaps")
def gaps():
    """Two-sided consensus-gap board — where the ValuCast board diverges most
    from the public consensus, published as testable claims. The higher side is
    the AOTC ledger's input; the fade side is published-but-not-scored and the
    page says so."""
    payload = _load_artifact(CONSENSUS_GAP_PATH) or {}
    higher = payload.get("higher") or []
    lower = payload.get("lower") or []
    return render_template(
        "gaps.html",
        gaps_available=bool(higher or lower),
        gaps_generated_at=payload.get("generated_at"),
        gaps_method=payload.get("method") or {},
        gaps_summary=payload.get("summary") or {},
        gaps_higher=higher,
        gaps_lower=lower,
        gap_count=len(higher) + len(lower),
        as_of=payload.get("generated_at") or store.as_of,
    )


@app.route("/ledger")
def ledger():
    """Human-readable Ahead-of-the-Curve ledger — the JSON artifact rendered for
    people (7/2: "no one could see the ledger hidden behind a json file"). The
    aggregate headline still honors the 30-day publish gate; the full funnel and
    per-call ledger are live immediately, misses included. "It's on the ledger"
    is the brand phrase — the URL matches it."""
    return render_template("track_record.html", sc=_load_scorecard_payload())


@app.route("/track-record")
def track_record():
    return redirect("/ledger", code=301)


@app.route("/aotc-scorecard.json")
def aotc_scorecard_json():
    """Public ledger: the raw Ahead-of-the-Curve scorecard artifact — definitions,
    targets, funnel, and every call including the retreats. Third parties can
    snapshot it themselves; that's the point."""
    path = _LEDGER_SCORECARD_PATH
    if not path.exists():
        abort(404)
    response = make_response(path.read_text(encoding="utf-8"))
    response.headers["Content-Type"] = "application/json"
    # 10 min, matching the PNG cards: a 1h edge cache held yesterday's ledger
    # after the daily refresh.
    response.headers.setdefault("Cache-Control", "public, max-age=600")
    return response


@app.route("/receipts")
def receipts():
    context = _build_receipts_page_context()
    return render_template("receipts.html", **context)


def _receipts_share_card_png(receipts, misses=None, *, generated_at=None):
    """Deterministic two-sided Call-Up Receipts graphic (ahead of the field + behind it)."""
    import io as _io
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    palette = _GRAPHIC_PALETTE
    bg = palette["bg"]
    card = palette["card"]
    card_2 = palette["card_2"]
    border = palette["border"]
    green = palette["green"]
    clay = palette.get("clay", "#c98a6a")
    blue = palette["blue"]
    text = palette["text"]
    muted = palette["muted"]

    receipts = list(receipts or [])
    misses = list(misses or [])

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    date_label = _editorial_date(generated_at)
    subtitle = f"{len(receipts)} ahead of the field - {len(misses)} behind"
    if date_label:
        subtitle = f"{subtitle} - {date_label}"
    _graphic_header(
        img,
        draw,
        headline="CALL-UP RECEIPTS",
        subtitle=subtitle,
        extra_line="Every prospect call-up vs the public-board consensus, both directions",
        tagline="Call-Up Receipts",
    )

    f_section = _graphic_font(25, bold=True)
    f_date = _graphic_font(15, bold=True, mono=True)
    f_name = _graphic_font(23, bold=True)
    f_meta = _graphic_font(14)
    f_rank = _graphic_font(15, bold=True, mono=True)
    f_gap = _graphic_font(24, bold=True, mono=True)
    row_h = 60
    x, w = 48, 984

    def draw_section(title, rows, top_y, accent, is_miss):
        n = max(1, len(rows))
        panel_h = 50 + n * row_h + 8
        draw.rounded_rectangle((x, top_y, x + w, top_y + panel_h), radius=10, fill=card, outline=border, width=1)
        draw.text((x + 20, top_y + 14), title, fill=accent, font=f_section)
        if not rows:
            draw.text((x + 20, top_y + 62), "None logged yet.", fill=muted, font=f_name)
        for idx, row in enumerate(rows):
            top = top_y + 48 + idx * row_h
            fill = card_2 if idx % 2 == 0 else card
            draw.rectangle((x + 1, top, x + w - 1, top + row_h), fill=fill)
            if idx:
                draw.line((x + 16, top, x + w - 16, top), fill=border, width=1)
            call_date = str(row.get("call_up_date") or "")[:10]
            draw.text((x + 18, top + 11), call_date, fill=blue, font=f_date)
            name = _graphic_fit_text(draw, row.get("name"), f_name, 350)
            draw.text((x + 150, top + 7), name, fill=text, font=f_name)
            meta = " - ".join(str(part) for part in (row.get("team"), row.get("pos"), row.get("level")) if part)
            draw.text((x + 150, top + 35), _graphic_fit_text(draw, meta, f_meta, 350), fill=muted, font=f_meta)
            consensus_rank = row.get("consensus_rank")
            if consensus_rank not in (None, ""):
                ranks = f"VC #{row.get('valucast_rank')} vs field #{consensus_rank}"
            else:
                ranks = f"VC #{row.get('valucast_rank')} - {row.get('field_label') or 'field outside top 100'}"
            draw.text((x + 560, top + 21), _graphic_fit_text(draw, ranks, f_rank, 330), fill=muted, font=f_rank)
            div = row.get("divergence")
            if isinstance(div, int):
                label = str(div) if is_miss else f"+{div}"
                color = clay if is_miss else green
                draw.text((x + w - 22 - _graphic_text_width(draw, label, f_gap), top + 16), label, fill=color, font=f_gap)
            else:
                label = "AHEAD"
                draw.text((x + w - 22 - _graphic_text_width(draw, label, f_rank), top + 22), label, fill=green, font=f_rank)
        return top_y + panel_h

    y = 242
    y = draw_section("AHEAD OF THE FIELD", receipts[:8], y, green, False)
    if misses:
        draw_section("BEHIND THE FIELD", misses[:6], y + 16, clay, True)

    _graphic_footer(draw, right_note="ValuCast vs the public-board consensus on every call-up")

    out = _io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


@app.route("/receipts/share-card.png")
def receipts_share_card_png():
    if RECEIPTS_HOLD:
        abort(404)
    context = _build_receipts_page_context()
    png = _receipts_share_card_png(
        context["receipts"],
        context["misses"],
        generated_at=context["receipts_generated_at"],
    )
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = 'inline; filename="valucast-call-up-receipts.png"'
    return response


@app.route("/receipts/share-card")
def receipts_share_card():
    if RECEIPTS_HOLD:
        abort(404)
    html = build_share_preview_html(
        title="Call-Up Receipts",
        subtitle="Prospects ValuCast ranked above consensus before MLB call-up",
        png_url="/receipts/share-card.png",
        filename="valucast-call-up-receipts.png",
        public_png_url=_public_url("/receipts/share-card.png"),
        public_page_url=_public_url("/receipts/share-card"),
        description="Permanent receipts for prospects ValuCast ranked above consensus before MLB call-up.",
        image_alt="ValuCast Call-Up Receipts board",
        back_url="/receipts",
        back_label="Back to Call-Up Receipts",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


def _ledger_share_card_png(sc):
    """Counts-only Ledger graphic. Pre-gate rule: funnel counts and call rows
    only — the success RATE never renders anywhere until the publish gate
    matures (scorecard freeze). The card must stay honest without it."""
    import io as _io
    from PIL import Image, ImageDraw

    width, height = 1080, 1350
    palette = _GRAPHIC_PALETTE
    bg = palette["bg"]
    card = palette["card"]
    card_2 = palette["card_2"]
    border = palette["border"]
    green = palette["green"]
    clay = palette.get("clay", "#c98a6a")
    blue = palette["blue"]
    text = palette["text"]
    muted = palette["muted"]

    funnel = (sc or {}).get("funnel") or {}
    summary = (sc or {}).get("summary") or {}
    calls = list((sc or {}).get("calls") or [])
    wins = int(funnel.get("open_toward") or 0) + int(funnel.get("closed_caught_up") or 0)
    losses = int(funnel.get("open_away") or 0)
    retreats = int(funnel.get("retired_we_backed_off") or 0)
    undecided = int(funnel.get("open_flat") or 0)
    total = summary.get("ever_flagged") or 0

    img = Image.new("RGB", (width, height), bg)
    _graphic_fill_background(img)
    draw = ImageDraw.Draw(img)
    subtitle = f"{total} calls tracked publicly"
    first = summary.get("first_call_date")
    if first:
        subtitle = f"{subtitle} since {first}"
    date_label = _editorial_date((sc or {}).get("generated_at"))
    if date_label:
        subtitle = f"{subtitle} - {date_label}"
    _graphic_header(
        img,
        draw,
        headline="THE LEDGER",
        subtitle=subtitle,
        extra_line="Wins, losses, and the calls we backed off - no call leaves this page silently",
        tagline="The Ledger",
    )

    # Funnel tiles: the counts ARE the story pre-gate.
    tiles = [
        (str(wins), "WINS", "field came to us", green),
        (str(losses), "LOSSES", "field moved away", clay),
        (str(retreats), "RETREATS", "we backed off", clay),
        (str(undecided), "UNDECIDED", "below the noise floor", muted),
    ]
    f_tile_n = _graphic_font(52, bold=True, mono=True)
    f_tile_label = _graphic_font(17, bold=True)
    f_tile_sub = _graphic_font(13)
    x, w = 48, 984
    tile_gap = 14
    tile_w = (w - 3 * tile_gap) // 4
    tile_y, tile_h = 242, 128
    for i, (n_label, label, sub, accent) in enumerate(tiles):
        tx = x + i * (tile_w + tile_gap)
        draw.rounded_rectangle((tx, tile_y, tx + tile_w, tile_y + tile_h), radius=10,
                               fill=card, outline=border, width=1)
        draw.text((tx + 18, tile_y + 14), n_label, fill=accent, font=f_tile_n)
        draw.text((tx + 18, tile_y + 76), label, fill=text, font=f_tile_label)
        draw.text((tx + 18, tile_y + 100),
                  _graphic_fit_text(draw, sub, f_tile_sub, tile_w - 34),
                  fill=muted, font=f_tile_sub)

    # Newest calls, statuses included — the two-sided ledger in miniature.
    status_labels = {
        "open_toward": ("FIELD MOVING TO US", green),
        "closed_caught_up": ("CAUGHT UP - WIN", green),
        "open_away": ("MOVING AWAY", clay),
        "retired_we_backed_off": ("WE BACKED OFF", clay),
        "open_flat": ("NO DECISIVE MOVE", muted),
        "resolved_called_up_or_graduated": ("CALLED UP", blue),
        "left_universe": ("LEFT UNIVERSE", muted),
    }
    newest = sorted(calls, key=lambda c: str(c.get("ahead_since") or ""), reverse=True)[:13]
    f_section = _graphic_font(25, bold=True)
    f_date = _graphic_font(15, bold=True, mono=True)
    f_name = _graphic_font(22, bold=True)
    f_rank = _graphic_font(15, bold=True, mono=True)
    f_status = _graphic_font(14, bold=True)
    row_h = 58
    panel_y = tile_y + tile_h + 16
    panel_h = 50 + max(1, len(newest)) * row_h + 8
    draw.rounded_rectangle((x, panel_y, x + w, panel_y + panel_h), radius=10,
                           fill=card, outline=border, width=1)
    draw.text((x + 20, panel_y + 14), "NEWEST CALLS", fill=text, font=f_section)
    if not newest:
        draw.text((x + 20, panel_y + 62), "No calls on the ledger yet.", fill=muted, font=f_name)
    for idx, c in enumerate(newest):
        top = panel_y + 48 + idx * row_h
        fill = card_2 if idx % 2 == 0 else card
        draw.rectangle((x + 1, top, x + w - 1, top + row_h), fill=fill)
        if idx:
            draw.line((x + 16, top, x + w - 16, top), fill=border, width=1)
        draw.text((x + 18, top + 20), str(c.get("ahead_since") or "")[:10], fill=blue, font=f_date)
        draw.text((x + 150, top + 15),
                  _graphic_fit_text(draw, c.get("name"), f_name, 320), fill=text, font=f_name)
        vc_then, cons_then = c.get("valucast_then"), c.get("consensus_then")
        if vc_then is not None and cons_then is not None:
            ranks = f"us #{vc_then} vs field ~#{cons_then}"
            draw.text((x + 500, top + 20),
                      _graphic_fit_text(draw, ranks, f_rank, 240), fill=muted, font=f_rank)
        label, accent = status_labels.get(c.get("status"), ("OPEN", muted))
        draw.text((x + w - 22 - _graphic_text_width(draw, label, f_status), top + 21),
                  label, fill=accent, font=f_status)

    _graphic_footer(
        draw,
        right_note="Success rate publishes when the 30-day gate matures - rules pre-registered",
    )

    out = _io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


@app.route("/ledger/share-card.png")
def ledger_share_card_png():
    sc = _load_scorecard_payload()
    if not sc:
        abort(404)
    png = _ledger_share_card_png(sc)
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = 'inline; filename="valucast-ledger.png"'
    return response


@app.route("/ledger/share-card")
def ledger_share_card():
    html = build_share_preview_html(
        title="The Ledger",
        subtitle="Every ahead-of-consensus call tracked to an outcome",
        png_url="/ledger/share-card.png",
        filename="valucast-ledger.png",
        public_png_url=_public_url("/ledger/share-card.png"),
        public_page_url=_public_url("/ledger/share-card"),
        description="Every ValuCast ahead-of-consensus call tracked publicly — wins, losses, and the calls we backed off.",
        image_alt="ValuCast Ledger scorecard",
        back_url="/ledger",
        back_label="Back to The Ledger",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


def _artifact_is_fresh(generated_at, hours=36):
    """FRESH badge honesty: computed from the artifact's own stamp, never assumed."""
    if not generated_at:
        return False
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
    except ValueError:
        return False
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).total_seconds() <= hours * 3600


@app.route("/llms.txt")
def llms_txt():
    """LLM-citation discoverability file (llmstxt.org convention)."""
    return app.send_static_file("llms.txt")


@app.route("/cards")
def cards_gallery():
    """Every share graphic in one place — the destination gallery for social
    posts (7/3 landscape review: rankings-as-images is the growth loop; the
    missing piece was a place to send people)."""
    dd_gen = dd_store.generated_at if dd_store.is_available else None
    movers_gen = _load_movers_payload().get("generated_at")
    sc = _load_scorecard_payload()
    entries = [
        {
            "title": "Top Prospects",
            "caption": "The top of the prospect board — the whole 300 is free behind it.",
            "page_url": "/prospects/share-card",
            "png_url": "/prospects/share-card.png",
            "board_url": "/?mode=prospects",
            "generated_at": dd_gen,
        },
        {
            "title": "Prospect Movers",
            "caption": "Real risers and fallers — nightly re-baselines filtered out.",
            "page_url": "/movers/share-card",
            "png_url": "/movers/share-card.png",
            "board_url": "/movers",
            "generated_at": movers_gen,
        },
        {
            "title": "The Ledger",
            "caption": "Every ahead-of-consensus call tracked to an outcome — misses included.",
            "page_url": "/ledger/share-card",
            "png_url": "/ledger/share-card.png",
            "board_url": "/ledger",
            "generated_at": (sc or {}).get("generated_at"),
        },
        {
            "title": "Value Map",
            "caption": "Dynasty value vs age — the whole market on one chart.",
            "page_url": "/map/share-card",
            "png_url": "/map/share-card.png",
            "board_url": "/map",
            "generated_at": dd_gen,
        },
    ]
    if not AHEAD_OF_THE_CURVE_HOLD:
        entries.insert(2, {
            "title": "Ahead of the Curve",
            "caption": "The 40 best prospect buys by signal, not reputation.",
            "page_url": "/buys/share-card",
            "png_url": "/buys/share-card.png",
            "board_url": "/buys",
            "generated_at": valucast_buy_store.generated_at,
        })
    if not RECEIPTS_HOLD:
        entries.append({
            "title": "Call-Up Receipts",
            "caption": "Every call-up vs the public consensus — both directions.",
            "page_url": "/receipts/share-card",
            "png_url": "/receipts/share-card.png",
            "board_url": "/receipts",
            "generated_at": _load_receipts_payload().get("generated_at"),
        })
    for entry in entries:
        entry["fresh"] = _artifact_is_fresh(entry["generated_at"])
        entry["date_label"] = _editorial_date(entry["generated_at"])
    return render_template("cards.html", entries=entries)


# Form-curve window presets. None = the full (epoch-masked) tracked history;
# the spark label renders the actual span, so oversized windows self-clamp.
SPARK_WINDOW_CHOICES = (7, 14, 21, 30)
# The movers page has no "All" pill — every view is a fixed window so each
# pill means the same thing every day; 14d is the default horizon.
DEFAULT_MOVER_WINDOW = 14


def _parse_spark_window(raw) -> int | None:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value in SPARK_WINDOW_CHOICES else None


@app.route("/buys")
def buys():
    """Top-40 prospect buys + the shareable 1080x1350 graphic node."""
    context = _build_buys_page_context(
        request.args.get("n", buy_score.BOARD_SIZE),
        spark_window=_parse_spark_window(request.args.get("window")),
    )
    return render_template("buys.html", **context)


def _build_buys_page_context(raw_n=None, spark_window=None):
    """Shared buys context for the page and deterministic share-card PNG.

    spark_window trims the form curves (page list + on-page export share the
    same rows, so the user downloads what they see); the server-rendered
    share-card PNG builds its own context without a window and stays on the
    canonical epoch view."""
    n = buy_score.clamp_n(raw_n if raw_n is not None else buy_score.BOARD_SIZE)
    buy_store, buy_data_source = _select_buy_source(valucast_buy_store)
    if buy_data_source == "valucast_buys" and buy_store.is_available:
        graphic_rows = buy_score.build_valucast_board(buy_store.get_all())
        # n drives the interactive list only; the 2x20 graphic always takes 40
        list_rows = (graphic_rows[:n] if n <= buy_score.BOARD_SIZE
                     else buy_score.build_valucast_board(buy_store.get_all(), n=n))
        data_generated_at = buy_store.generated_at
        data_available = True
        buy_validation = buy_store.validation
    else:
        # No ValuCast buys ready -> explicit unavailable. Never a DD-derived board.
        graphic_rows, list_rows = [], []
        data_generated_at = None
        data_available = False
        buy_validation = {}
    # Why-line: first sentence of the existing deterministic scouting read,
    # joined by identity — never regenerated (Batch 2 trust grammar).
    reads_by_identity = _indexed_artifact_rows(
        _load_artifact(Path(__file__).parent / "data" / "models" / "valucast_scouting_reports.json"),
        "reports",
    )
    for row in list_rows:
        report_row = reads_by_identity.get(
            _identity_key(row.get("mlbam_id"), row.get("role")) or ""
        )
        row["why"] = _first_read_sentence(report_row)
    buy_pool = buy_validation.get("candidate_count")
    buy_qualified = buy_validation.get("row_count")
    buy_source_copy = _buy_source_copy(buy_data_source)
    for row in graphic_rows:
        row["spark"] = build_spark(row["value_history"], window_days=spark_window)
        row["spark_label"] = _buy_spark_label(row["spark"])
    for row in list_rows:
        if "spark" not in row:
            row["spark"] = build_spark(row["value_history"], window_days=spark_window)
        if "spark_label" not in row:
            row["spark_label"] = _buy_spark_label(row["spark"])
    return {
        "list_rows": list_rows,
        "graphic_rows": graphic_rows,
        "n": n,
        "spark_window": spark_window,
        "spark_window_choices": SPARK_WINDOW_CHOICES,
        "dd_available": data_available,
        "dd_generated_at": data_generated_at,
        "buy_data_source": buy_data_source,
        "buy_source_label": buy_source_copy["label"],
        "buy_source_note": buy_source_copy["note"],
        "buy_formula_note": buy_source_copy["formula"],
        # Qualification funnel straight from the artifact's validation block —
        # the transparency header shows the math at point of use.
        "buy_pool_count": buy_pool,
        "buy_qualified_count": buy_qualified,
        "buy_excluded_mlb_count": buy_validation.get("active_mlb_roster_excluded_count"),
        "buy_qualified_pct": (
            round(100 * buy_qualified / buy_pool)
            if buy_qualified and buy_pool else None
        ),
        "aotc_hold": AHEAD_OF_THE_CURVE_HOLD,
        "aotc_hold_message": "Ahead of the Curve returns later this week",
        "as_of": data_generated_at or store.as_of,
    }


_READ_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _first_read_sentence(report_row):
    """One-line 'why' for a buys row: the deterministic read's first sentence."""
    if not isinstance(report_row, dict):
        return ""
    text = str(report_row.get("report") or "").strip()
    if not text:
        return ""
    first = _READ_SENTENCE_SPLIT.split(text, 1)[0].strip()
    if len(first) > 160:
        first = first[:157].rstrip() + "..."
    return first


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
    red = _GRAPHIC_PALETTE["clay"]

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

    def score_text(row):
        # Integers, matching the HTML card's `round | int` — raw decimals
        # ("74.6") overflow the fixed "/100" positions below (7/3, found the
        # first day the PNG faced humans on /cards instead of crawlers).
        value = row.get("score")
        try:
            return str(int(round(float(value))))
        except (TypeError, ValueError):
            return "--"

    hero_rows = list(rows or [])[:5]
    grid_rows = list(rows or [])[5:40]
    if not hero_rows:
        _graphic_glass_panel(img, draw, (48, 226, 1032, 370), radius=12)
        draw.text((76, 278), "No prospect buys are available.", fill=text, font=f_name)
    else:
        hero = hero_rows[0]
        _graphic_glass_panel(img, draw, (48, 226, 418, 540), radius=12)
        draw.text((70, 252), "#1 - TOP BUY", fill=muted, font=f_rank)
        name_lines = split_lines(hero.get("name"), _graphic_font(34, bold=True), 320)
        for idx, line in enumerate(name_lines[:2]):
            draw.text((70, 320 + idx * 39), line, fill=text, font=_graphic_font(34, bold=True))
        draw.text((70, 403), _graphic_fit_text(draw, tag(hero), _graphic_font(16, mono=True), 320), fill=muted, font=_graphic_font(16, mono=True))
        hero_score = score_text(hero)
        draw.text((70, 455), hero_score, fill=green, font=f_hero_score)
        draw.text((70 + _graphic_text_width(draw, hero_score, f_hero_score) + 8, 498),
                  "/100", fill=muted, font=f_small)
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
            _graphic_glass_panel(img, draw, (x, y, x + 291, y + 149), radius=12)
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
            support_score = score_text(row)
            draw.text((x + 14, y + 112), support_score, fill=green, font=f_support_score)
            draw.text((x + 14 + _graphic_text_width(draw, support_score, f_support_score) + 6, y + 126),
                      "/100", fill=muted, font=_graphic_font(11))
            _draw_buys_spark(
                draw, row.get("spark"), x + 104, y + 117, 68, 18,
                up_color=green, down_color=red, flat_color=muted,
            )
            # Compact form for the 92px support slot — the full "UP +5.2 OVER 11D"
            # truncated to "UP +5.2 OV..." (7/3).
            label = row.get("spark_label") or (row.get("reason") or "").upper()
            label = label.replace(" OVER ", " - ").removeprefix("UP ").removeprefix("DOWN ")
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
        score = score_text(row)
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
        "dynasty_data_source": dynasty_data_source,
        "commit": os.environ.get("RENDER_GIT_COMMIT", ""),
    }
    return jsonify(body), (200 if ready else 503)


def _build_dynasty_player_detail_context(player_id, args):
    """Shared DD player-detail context for dynasty/prospect detail surfaces."""
    dd_row = dd_store.get_by_id(player_id)
    if dd_row is None:
        return None

    mlb_stats = None
    mlb_stats_actual = None
    mlb_stats_ros = None
    mlb_stats_split = None
    mlb_stats_actual_split = None
    mlb_stats_ros_split = None
    extras = {"statcast_groups": [], "statcast_asof": None, "player_links": []}
    match_index = build_outlook_match_index(store.get_all())
    matches = []
    if not dd_row.is_prospect:
        outlook = find_season_outlook(dd_row, match_index)
        if outlook:
            mlb_stats, mlb_stats_actual, mlb_stats_ros = outlook
        split = find_season_outlook_split(dd_row, match_index)
        if split:
            mlb_stats_split, mlb_stats_actual_split, mlb_stats_ros_split = split
        # Identity (mlbam/fangraphs ids) comes from the safely-matched
        # projection row; the feed itself carries no ids today.
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
        # Measured shape comps (display-only artifact; absent players/artifact
        # simply render no section).
        comps_payload = _load_artifact(PROSPECT_COMPS_PATH) or {}
        shape_comps = (comps_payload.get("players") or {}).get(
            str(getattr(dd_row, "mlbam_id", "") or "")
        )
        prospect_context = {
            "stat_percentiles": stat_percentiles,
            "stat_captions": stat_captions,
            "identity": identity,
            "profile_bars": profile_bars,
            "skill_grades": skill_grades,
            "skill_shape": skill_shape,
            "profile_pool_label": prospect_percentiles.pool_label(dd_row),
            "profile_stat_context": profile_stat_context,
            "shape_comps": shape_comps,
            "shape_comp_tier_labels": comps_payload.get("tier_labels") or {},
        }

    # Same-engine category z's as the active dynasty category configuration.
    # The feed's z_scores field has never been produced (DD-producer gap),
    # so the card scores the safely matched projection app-side.
    dyn_result = None
    dyn_categories = []
    dyn_category_summary = None
    if matches:
        dyn_cats, dyn_pcats, fit_active = _dynasty_detail_category_state(args)
        # build_config treats an empty side as "use default"; use one
        # harmless category instead, then filter it from the detail table.
        config = build_config(
            mode="categories", cats=dyn_cats or ["R"],
            pcats=dyn_pcats or ["K"], rules_str="",
            pt_params=None, split_rp=False, weights=None,
        )
        detail_results = _redraft_value_players(_valuation_players(active_store=store), config)
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

    context = {
        "row": dd_row,
        "dyn_result": dyn_result,
        "dyn_categories": dyn_categories,
        "dyn_category_summary": dyn_category_summary,
        "spark": build_spark(dd_row.value_history),
        "mlb_stats": mlb_stats,
        "mlb_stats_actual": mlb_stats_actual,
        "mlb_stats_ros": mlb_stats_ros,
        "mlb_stats_split": mlb_stats_split,
        "mlb_stats_actual_split": mlb_stats_actual_split,
        "mlb_stats_ros_split": mlb_stats_ros_split,
        "fangraphs": fg_fv.get(getattr(dd_row, "mlbam_id", None)),
        "format_ranks": (
            format_ranks_for(getattr(dd_row, "mlbam_id", None))
            if dd_row.is_prospect else []
        ),
    }
    context.update(prospect_context)
    context.update(artifact_context)
    context.update(extras)
    return context


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
        context = _build_dynasty_player_detail_context(player_id, request.args)
        if context is None:
            abort(404)
        return render_template("partials/player_detail_dynasty.html", **context)
    # _build_context resolves + guards the source first (SourceError -> 400), then we
    # look the player up in the ACTIVE store so detail honors ?source=.
    ctx = _build_context(request.args)
    active = ctx["active_store"]
    player_proj = active.get_by_id(player_id)
    if not player_proj:
        abort(404)

    config = ctx["config"]
    # Value the canonical universe (no on-demand force-keep) so the detail value matches
    # the board exactly. A below-floor player isn't in the canonical set -> result None,
    # and the template shows the projection without a (non-canonical) value.
    detail_results = _redraft_value_players(_valuation_players(active_store=active), config)
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
    all_results = _redraft_value_players(
        _valuation_players(active_store=ctx["active_store"]), config
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
    return limit if limit in {10, 20, 50, 100, 200} else 10


def _prospect_share_debut_view(args):
    """(row_filter, view) for the debut filter on share surfaces — the same
    semantics as the board filter, so a shared graphic matches the board the
    sharer was looking at. view is None / "debuted" / "undebuted"."""
    raw = args.get("callups") or ""
    callups = {"milb": "undebuted"}.get(raw, raw)
    if callups not in ("debuted", "undebuted"):
        return None, None
    debuted_ids = _debuted_prospect_ids()
    pulse_keys = _call_up_pulse_keys()

    if callups == "debuted":
        return (lambda row: _prospect_has_debuted(row, debuted_ids, pulse_keys)), "debuted"
    return (lambda row: not _prospect_has_debuted(row, debuted_ids, pulse_keys)), "undebuted"


_DEBUT_VIEW_NOUN = {"debuted": "Debuted Prospects", "undebuted": "Not-Yet-Debuted Prospects"}


def _prospect_graphic_payload():
    limit = _prospect_share_limit(request.args)
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    row_filter, debut_view = _prospect_share_debut_view(request.args)
    rows = _prospect_rows(position=position, search=search, row_filter=row_filter)[:limit]
    noun = _DEBUT_VIEW_NOUN.get(debut_view, "Prospects")
    svg = _prospect_graphic_svg(rows, limit=limit, position=position, search=search, noun=noun)
    scope = (position or "all").lower()
    view_slug = f"-{debut_view}" if debut_view else ""
    filename = f"valucast-top-{limit}-{scope}{view_slug}-prospects.svg"
    return svg, filename, limit, position, search


@app.route("/prospects/share-card")
def prospects_share_card():
    if not dd_store.is_available:
        return "<!doctype html><title>Prospect graphic unavailable</title>", 503

    limit = _prospect_share_limit(request.args)
    position = request.args.get("position") or None
    search = request.args.get("search") or None
    _, debut_view = _prospect_share_debut_view(request.args)
    params = {"limit": limit}
    if position:
        params["position"] = position
    if search:
        params["search"] = search
    if debut_view:
        params["callups"] = debut_view
    png_url = "/prospects/share-card.png?" + urlencode(params)
    scope = (position or "all").lower()
    view_slug = f"-{debut_view}" if debut_view else ""
    filename = f"valucast-top-{limit}-{scope}{view_slug}-prospects.png"
    noun = _DEBUT_VIEW_NOUN.get(debut_view, "Prospects")
    title = f"Top {limit} {position + ' ' if position else ''}{noun}"
    if search:
        title = f"{title} | {search}"
    html = build_share_preview_html(
        title=f"ValuCast Prospects Top {limit}",
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
    row_filter, debut_view = _prospect_share_debut_view(request.args)
    rows = _prospect_rows(position=position, search=search, row_filter=row_filter)[:limit]
    noun = _DEBUT_VIEW_NOUN.get(debut_view, "Prospects")
    png = _prospect_graphic_png(rows, limit=limit, position=position, search=search, noun=noun)
    scope = (position or "all").lower()
    view_slug = f"-{debut_view}" if debut_view else ""
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-top-{limit}-{scope}{view_slug}-prospects.png"'
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


def _share_player_slug(name, fallback="player"):
    return "-".join(
        piece for piece in "".join(
            ch.lower() if ch.isalnum() else "-" for ch in str(name or "")
        ).split("-") if piece
    ) or fallback


def _build_redraft_player_card_context(player_id, args):
    ctx = _build_context(args)
    active = ctx["active_store"]
    if getattr(active, "player_count", 0) <= 0:
        return None, 503

    player = active.get_by_id(player_id)
    if player is None:
        return None, 404

    config = ctx["config"]
    detail_results = _redraft_value_players(_valuation_players(active_store=active), config)
    result = next((r for r in detail_results if r.player.id == player_id), None)
    card_ctx = dict(ctx)
    card_ctx.update(_card_extras(player.name, player.pool, player.metadata))
    mlbam_id = (
        (player.metadata or {}).get("mlbam_id")
        if isinstance(player.metadata, dict)
        else None
    )
    role = "pitcher" if player.pool in _PITCHER_POOLS else "hitter"
    dynasty_row = _dynasty_snapshot_row_for(mlbam_id, role)
    card_ctx.update({
        "player": player,
        "dyn_result": result,
        "dyn_categories": ctx["active_categories"],
        "dyn_category_summary": ctx["config_summary"],
        "as_of": active.as_of,
        "redraft_value_scale": _redraft_value_scale(detail_results),
        "redraft_dynasty_row": dynasty_row,
    })
    return card_ctx, 200


@app.route("/redraft/player-card/<player_id>")
def redraft_player_card_preview(player_id):
    context, status = _build_redraft_player_card_context(player_id, request.args)
    if status != 200:
        return "", status

    player = context["player"]
    slug = _share_player_slug(player.name, "redraft-player")
    filename = f"valucast-{slug}.png"
    query = request.query_string.decode("utf-8")
    suffix = f"?{query}" if query else ""
    png_url = f"/redraft/player-card/{escape(player_id)}.png{suffix}"
    page_url = f"/redraft/player-card/{player_id}{suffix}"
    back_url = f"/?{query}" if query else "/"
    html = build_share_preview_html(
        title=f"{player.name} | Redraft Value Card",
        subtitle=f"{player.name} - redraft value + MLB Statcast context",
        png_url=png_url,
        filename=filename,
        public_png_url=_public_url(png_url),
        public_page_url=_public_url(page_url),
        description=f"{player.name} ValuCast redraft card with value, MLB Statcast context, and category fit.",
        image_alt=f"{player.name} ValuCast redraft player card",
        back_url=back_url,
        back_label="Back to redraft",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/redraft/player-card/<player_id>.png")
def redraft_player_card_png(player_id):
    context, status = _build_redraft_player_card_context(player_id, request.args)
    if status != 200:
        return "", status

    player = context["player"]
    png = _player_value_card_png(player, context, "redraft")
    slug = _share_player_slug(player.name, "redraft-player")
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-{slug}.png"'
    )
    return response


@app.route("/dynasty/player-card/<player_id>")
def dynasty_player_card_preview(player_id):
    if not dd_store.is_available:
        return "", 503
    context = _build_dynasty_player_detail_context(player_id, request.args)
    if context is None:
        return "", 404

    row = context["row"]
    slug = _share_player_slug(row.name, "dynasty-player")
    filename = f"valucast-{slug}.png"
    png_url = f"/dynasty/player-card/{escape(player_id)}.png"
    html = build_share_preview_html(
        title=f"{row.name} | Dynasty Value Card",
        subtitle=f"{row.name} - dynasty value + MLB Statcast context",
        png_url=png_url,
        filename=filename,
        public_png_url=_public_url(png_url),
        public_page_url=_public_url(f"/dynasty/player-card/{player_id}"),
        description=f"{row.name} ValuCast dynasty card with value, MLB Statcast context, and category fit.",
        image_alt=f"{row.name} ValuCast dynasty player card",
        back_url="/?mode=dd_dynasty",
        back_label="Back to dynasty",
    )
    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    return response


@app.route("/dynasty/player-card/<player_id>.png")
def dynasty_player_card_png(player_id):
    if not dd_store.is_available:
        return "", 503
    context = _build_dynasty_player_detail_context(player_id, request.args)
    if context is None:
        return "", 404

    row = context["row"]
    png = _player_value_card_png(row, context, "dynasty")
    slug = _share_player_slug(row.name, "dynasty-player")
    response = make_response(png)
    response.headers["Content-Type"] = "image/png"
    response.headers["Content-Disposition"] = (
        f'inline; filename="valucast-{slug}.png"'
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
    preview_title = f"ValuCast Dynasty Top {limit}"
    if scope:
        preview_title = f"{preview_title} - {scope}"
    if search:
        preview_title = f"{preview_title} | {search}"
    html = build_share_preview_html(
        title=preview_title,
        subtitle=title,
        png_url=png_url,
        filename=f"valucast-dynasty-top-{limit}.png",
        public_png_url=_public_url(png_url),
        public_page_url=_public_url("/dynasty/share-card?" + urlencode(params)),
        description="ValuCast's current dynasty board, from the live Dynasty tab.",
        image_alt=preview_title,
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

    def __init__(self, result, value_scale):
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
        scaled_value = _redraft_scaled_value(result.total_value, value_scale)
        self.value = round(scaled_value, 1) if scaled_value is not None else None
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
    rows = [
        _RedraftShareRow(r, ctx.get("redraft_value_scale"))
        for r in (ctx.get("results") or [])[:limit]
    ]
    mode, src = _redraft_share_labels(ctx, request.args)
    png = _prospect_graphic_png(
        rows,
        limit=limit,
        noun="Redraft",
        hero_kicker="TOP REDRAFT VALUE",
        footer_note=f"ValuCast Redraft 0-100 - {mode} ({src})",
        as_of=ctx.get("as_of"),
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
    preview_title = f"ValuCast Redraft Top {limit}"
    html = build_share_preview_html(
        title=preview_title,
        subtitle=title,
        png_url=png_url,
        filename=f"valucast-redraft-top-{limit}.png",
        public_png_url=_public_url(png_url),
        public_page_url=_public_url("/redraft/share-card?" + urlencode(params)),
        description="ValuCast redraft values, from the live board.",
        image_alt=preview_title,
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
    rows = [
        _RedraftShareRow(r, ctx.get("redraft_value_scale"))
        for r in (ctx.get("results") or [])[:limit]
    ]
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
