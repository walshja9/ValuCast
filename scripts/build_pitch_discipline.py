"""Build ValuCast's plate-discipline artifact from MLB StatsAPI play-by-play.

This script owns ALL network + file I/O (the counting logic in
prospects/pitch_discipline.py is pure). It mirrors
scripts/refresh_milb_season_stats.py's idioms: a User-Agent Request, a timeout, an
atomic write, and a tiny-refresh guard.

Two fetch modes:
  --backfill     season-wide, checkpointed/resumable: fetch every tracked hitter's
                 game feeds, extract the compact per-pitch slice, flush the cache
                 periodically. A cached gamePk is NEVER re-fetched (a final feed is
                 immutable), so a re-run resumes for free.
  (default)      incremental: re-run each hitter's gameLog, fetch only the NEW
                 gamePks since the last run, update the cache, recompute the
                 artifact. On any StatsAPI failure it no-ops gracefully (keeps the
                 existing artifact + cache, exits 0) so a bad-fetch morning never
                 stalls the daily build.

Then (both modes) it assembles the per-player, per-level artifact: sums counts by
level, fits the global pixel->feet calibration for the estimated zone metrics,
computes per-level cohort percentiles with a hard minimum-pitch gate, and atomically
writes data/models/valucast_pitch_discipline.json.

OBSERVE-ONLY: this artifact is display context, never a value input.
NO exit velocity is ever produced (impossible from public MiLB play-by-play).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from bisect import bisect_left, bisect_right
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from prospects.pitch_discipline import (  # noqa: E402
    EXACT_METRICS,
    ESTIMATED_METRICS,
    PixelCalibration,
    calibration_agreement,
    count_player_pitches,
    fit_pixel_calibration,
    merge_counts,
    rates_from_counts,
)

# --- Paths -----------------------------------------------------------------
UNIVERSE_PATH = ROOT / "data" / "models" / "valucast_prospect_universe.json"
CACHE_PATH = ROOT / "data" / "prospects" / "raw" / "pitch_discipline_pitch_cache.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_pitch_discipline.json"
# Written by the bootstrap workflow ONLY after a complete --backfill succeeds.
# Incremental runs refuse to rebuild the artifact without it: a partial cache
# (e.g. saved by a timed-out bootstrap's if:always() checkpoint) would
# otherwise produce a deceptively fresh artifact from incomplete season data.
READY_MARKER_PATH = ROOT / "data" / "prospects" / "raw" / ".pitch_discipline_cache_ready"

# --- StatsAPI ---------------------------------------------------------------
SPORT_LEVELS = {11: "AAA", 12: "AA", 13: "A+", 14: "A"}
LEVEL_TO_SPORT = {v: k for k, v in SPORT_LEVELS.items()}
_USER_AGENT = "ValuCast plate-discipline refresh"
_FETCH_TIMEOUT = 60
_RATE_LIMIT_SECONDS = 0.15
_FLUSH_EVERY = 50

# Incremental-mode safety budgets (the daily CI invariant: a broken/cold fetch must
# never stall — or silently become a backfill inside — the daily build).
# More than this many NEW gamePks in incremental mode aborts before any feed fetch:
# a cold or stale cache on an ephemeral runner must never turn the ~60-90-game daily
# increment into a ~13k-request backfill inside the publish job.
_INCREMENTAL_NEW_PK_BUDGET = 300
# Failure tolerance: individual transient errors are skipped and counted; only when
# they exceed these budgets does the run keep the stale artifact (partial cache
# progress still persists via the periodic flush).
_INCREMENTAL_FEED_FAILURE_BUDGET = 25
_INCREMENTAL_GAMELOG_FAILURE_FRACTION = 0.10

# --- Tunables (stated in artifact metadata for reproducibility) -------------
# Hard minimum pitches-seen for a player-level bucket to (a) enter the cohort pool
# AND (b) render a bar. Below it, NO percentile bar renders — small-sample honesty,
# analogous to the card's 100 PA / 20 IP floor. Tunable, but 300 is the shipped
# constant.
MIN_PITCHES = 300

# Metric quality orientation. LOWER_IS_BETTER metrics invert the percentile so that,
# after orientation, higher percentile is always "better" (matches the card's
# elite/good/risk fills). Metrics not listed in either set carry a RAW value with NO
# percentile fill judgment (pct=None) — we only attach a quality fill where a
# direction is defensible.
LOWER_IS_BETTER = {"whiff_pct", "swstr_pct", "chase_pct"}
HIGHER_IS_BETTER = {"z_contact_pct"}
# swing_pct / z_swing_pct / zone_pct are contextual -> raw value, no fill.

METRIC_LABELS = {
    "swing_pct": "Swing%",
    "whiff_pct": "Whiff%",
    "swstr_pct": "SwStr%",
    "chase_pct": "Chase%",
    "z_swing_pct": "Z-Swing%",
    "z_contact_pct": "Z-Contact%",
    "zone_pct": "Zone%",
}
ALL_METRICS = tuple(EXACT_METRICS) + tuple(ESTIMATED_METRICS)

# Held-out agreement bar (Step 3): ship the estimated zone group only when the
# pixel calibration agrees with real pX/pZ on at least this fraction of AAA pairs.
_CALIBRATION_AGREEMENT_FLOOR = 85.0


# ---------------------------------------------------------------------------
# Network
# ---------------------------------------------------------------------------
def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_FETCH_TIMEOUT) as response:
        return json.load(response)


def fetch_game_pks(pid: int, season: int, sport_id: int) -> list[int]:
    """gamePks a hitter appeared in at a level, deduped (doubleheaders/resumes)."""
    params = urllib.parse.urlencode({
        "stats": "gameLog", "season": season, "group": "hitting", "sportId": sport_id,
    })
    url = f"https://statsapi.mlb.com/api/v1/people/{pid}/stats?{params}"
    data = _get_json(url)
    stats = data.get("stats") or []
    splits = (stats[0] if stats else {}).get("splits") or []
    pks = []
    seen = set()
    for split in splits:
        pk = ((split.get("game") or {}).get("gamePk"))
        if isinstance(pk, int) and pk not in seen:
            seen.add(pk)
            pks.append(pk)
    return pks


def fetch_compact_feed(game_pk: int) -> list[dict] | None:
    """Fetch a game feed and extract ONLY the per-pitch fields the counter needs.

    Returns None for a game that is not Final (live/suspended/postponed): a
    non-final feed's partial pitch counts must never be cached — a cached gamePk is
    never re-fetched, so caching a partial game would freeze wrong counts into
    every future artifact. The pk simply gets retried on a later run once Final.

    The compact slice (never the raw feed) is what gets cached/committed. Each play:
      {"batter": id, "pitches": [{"description","isInPlay","pX","pZ","x","y",
                                  "szTop","szBottom"}]}
    """
    url = f"https://statsapi.mlb.com/api/v1.1/game/{game_pk}/feed/live"
    data = _get_json(url)
    state = (((data.get("gameData") or {}).get("status") or {}).get("abstractGameState"))
    if state != "Final":
        return None
    all_plays = (((data.get("liveData") or {}).get("plays") or {}).get("allPlays")) or []
    compact = []
    for play in all_plays:
        batter = ((play.get("matchup") or {}).get("batter") or {}).get("id")
        if not isinstance(batter, int):
            continue
        pitches = []
        for ev in play.get("playEvents") or ():
            if not ev.get("isPitch"):
                continue
            det = ev.get("details") or {}
            pd = ev.get("pitchData") or {}
            co = pd.get("coordinates") or {}
            pitches.append({
                "description": det.get("description"),
                "isInPlay": bool(det.get("isInPlay")),
                "pX": co.get("pX"), "pZ": co.get("pZ"),
                "x": co.get("x"), "y": co.get("y"),
                "szTop": pd.get("strikeZoneTop"), "szBottom": pd.get("strikeZoneBottom"),
            })
        compact.append({"batter": batter, "pitches": pitches})
    return compact


# ---------------------------------------------------------------------------
# Compact-cache <-> counter adapters
# ---------------------------------------------------------------------------
def _compact_to_all_plays(compact_plays: list[dict]) -> list[dict]:
    """Re-shape a cached compact game back into the counter's allPlays shape."""
    plays = []
    for cp in compact_plays:
        events = []
        for p in cp.get("pitches") or ():
            events.append({
                "isPitch": True,
                "details": {"description": p.get("description"), "isInPlay": p.get("isInPlay")},
                "pitchData": {
                    "coordinates": {"pX": p.get("pX"), "pZ": p.get("pZ"),
                                    "x": p.get("x"), "y": p.get("y")},
                    "strikeZoneTop": p.get("szTop"), "strikeZoneBottom": p.get("szBottom"),
                },
            })
        plays.append({"matchup": {"batter": {"id": cp.get("batter")}}, "playEvents": events})
    return plays


# ---------------------------------------------------------------------------
# Cache I/O (atomic)
# ---------------------------------------------------------------------------
def load_cache(path: Path = CACHE_PATH) -> dict:
    """Cache shape: {"games": {"<gamePk>": {"level": "AA", "plays": [...]}}}."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"games": {}}
    if not isinstance(payload, dict) or not isinstance(payload.get("games"), dict):
        return {"games": {}}
    return payload


def _atomic_write(path: Path, payload: dict, *, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=indent) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def flush_cache(cache: dict, path: Path = CACHE_PATH) -> None:
    _atomic_write(path, cache)


def prune_cache(cache: dict, keep_seasons: set[int]) -> None:
    """Drop games tagged with a season outside keep_seasons (in place)."""
    games = cache.get("games") or {}
    for pk in list(games.keys()):
        season = games[pk].get("season")
        if isinstance(season, int) and season not in keep_seasons:
            del games[pk]


# ---------------------------------------------------------------------------
# Universe -> tracked hitters
# ---------------------------------------------------------------------------
def load_tracked_hitters(path: Path = UNIVERSE_PATH) -> list[dict]:
    """Tracked hitters (role != pitcher) with an mlbam id, from the universe."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for p in payload.get("players") or ():
        if p.get("role") == "pitcher":
            continue
        mlbam = p.get("mlbam_id")
        if not isinstance(mlbam, int):
            continue
        out.append({"mlbam_id": mlbam, "name": p.get("name"), "level": p.get("level")})
    return out


# ---------------------------------------------------------------------------
# Fetch driver (backfill / incremental)
# ---------------------------------------------------------------------------
def gather_games(
    hitters: list[dict],
    season: int,
    cache: dict,
    *,
    levels: list[str] | None = None,
    limit_games: int | None = None,
    incremental: bool = False,
) -> dict:
    """Fetch new game feeds into the cache. Returns a stats dict.

    Two phases:
      1. Discover NEW gamePks via each tracked hitter's per-level gameLog,
         tolerating per-request failures (skip + count, never abort the run on a
         single transient error).
      2. Fetch only the new feeds, tolerating per-feed failures, checkpoint-
         flushing every _FLUSH_EVERY feeds in BOTH modes so partial progress
         survives interruption. Non-Final games (fetch_compact_feed -> None) are
         skipped WITHOUT caching (retried once Final) and are not failures.

    In incremental mode, a new-pk count over _INCREMENTAL_NEW_PK_BUDGET aborts
    BEFORE any feed fetch (budget_exceeded=True) — a cold or stale cache must never
    turn the daily job into a backfill. The caller (main) applies the failure
    budgets to decide whether the artifact gets rewritten.
    """
    sport_ids = (
        [LEVEL_TO_SPORT[l] for l in levels] if levels else list(SPORT_LEVELS.keys())
    )
    games = cache.setdefault("games", {})
    stats = {
        "fetched": 0, "skipped": 0, "new_pks": 0,
        "gamelog_total": 0, "gamelog_failures": 0,
        "feed_failures": 0, "non_final_skipped": 0,
        "budget_exceeded": False, "cached_total": len(games),
    }
    # Phase 1: gameLog discovery (dedup across players/levels; a shared game
    # between two tracked teammates is fetched once).
    new_items: list[tuple[int, str]] = []
    seen_new: set[str] = set()
    for hitter in hitters:
        pid = hitter["mlbam_id"]
        for sport_id in sport_ids:
            level = SPORT_LEVELS[sport_id]
            stats["gamelog_total"] += 1
            try:
                pks = fetch_game_pks(pid, season, sport_id)
            except Exception as exc:  # noqa: BLE001
                stats["gamelog_failures"] += 1
                print(f"  ! gameLog {pid}/{level} failed: {exc}", flush=True)
                continue
            time.sleep(_RATE_LIMIT_SECONDS)
            for pk in pks:
                key = str(pk)
                if key in games:
                    stats["skipped"] += 1
                elif key not in seen_new:
                    seen_new.add(key)
                    new_items.append((pk, level))
    stats["new_pks"] = len(new_items)
    if incremental and len(new_items) > _INCREMENTAL_NEW_PK_BUDGET:
        stats["budget_exceeded"] = True
        return stats
    # Phase 2: feed fetch (new pks only).
    processed = 0
    for pk, level in new_items:
        if limit_games is not None and stats["fetched"] >= limit_games:
            break
        try:
            compact = fetch_compact_feed(pk)
        except Exception as exc:  # noqa: BLE001
            stats["feed_failures"] += 1
            print(f"  ! feed {pk} failed: {exc}", flush=True)
            continue
        time.sleep(_RATE_LIMIT_SECONDS)
        if compact is None:
            # Live/suspended game: do NOT cache; retried on a future run.
            stats["non_final_skipped"] += 1
            continue
        games[str(pk)] = {"level": level, "season": season, "plays": compact}
        stats["fetched"] += 1
        processed += 1
        if processed % _FLUSH_EVERY == 0:
            flush_cache(cache)
            print(
                f"  … fetched {stats['fetched']}/{len(new_items)}, cached {len(games)}, "
                f"skipped {stats['skipped']}",
                flush=True,
            )
    stats["cached_total"] = len(games)
    return stats


def _failures_over_budget(stats: dict) -> bool:
    """True when incremental fetch failures exceed the keep-stale-artifact budget."""
    if stats["feed_failures"] > _INCREMENTAL_FEED_FAILURE_BUDGET:
        return True
    total = stats["gamelog_total"]
    return bool(total) and (
        stats["gamelog_failures"] / total > _INCREMENTAL_GAMELOG_FAILURE_FRACTION
    )


# ---------------------------------------------------------------------------
# Calibration (Step 3)
# ---------------------------------------------------------------------------
def _split_pairs(pairs: list) -> tuple[list, list]:
    """Deterministic 80/20 train/held-out split: index i%5==0 -> held, else train.

    No randomness — the daily build must produce reproducible calibration metadata
    from the same cache. The two sets are disjoint by construction, so the
    agreement number is honestly out-of-sample.
    """
    train = [p for i, p in enumerate(pairs) if i % 5 != 0]
    held = [p for i, p in enumerate(pairs) if i % 5 == 0]
    return train, held


def build_calibration(cache: dict) -> tuple[PixelCalibration | None, dict]:
    """Fit the global pixel->feet map from cached pitches carrying BOTH x/y and
    pX/pZ (AAA). Honest quality: fit on the deterministic 80% train split, score
    in/out agreement on the held-out 20% against each pitch's OWN strike zone
    (an in-sample number scored on a default band overstates quality).
    Returns (calib, metadata)."""
    pairs = []
    for game in (cache.get("games") or {}).values():
        for cp in game.get("plays") or ():
            for p in cp.get("pitches") or ():
                x, y, px, pz = p.get("x"), p.get("y"), p.get("pX"), p.get("pZ")
                if all(isinstance(v, (int, float)) for v in (x, y, px, pz)):
                    pairs.append((
                        float(x), float(y), float(px), float(pz),
                        p.get("szTop"), p.get("szBottom"),
                    ))
    train, held = _split_pairs(pairs)
    calib, quality = fit_pixel_calibration(train)
    agreement = calibration_agreement(held, calib) if calib is not None else None
    meta = {
        "n_pairs": len(pairs),
        "n_train": len(train),
        "n_held": len(held),
        "fit_r2": quality.get("fit_r2"),
        "fit_r2_x": quality.get("fit_r2_x"),
        "fit_r2_y": quality.get("fit_r2_y"),
        "held_out_agreement_pct": agreement,
        "agreement_floor_pct": _CALIBRATION_AGREEMENT_FLOOR,
        "fitted_at": datetime.now(timezone.utc).isoformat(),
    }
    if calib is not None:
        meta.update(calib.as_dict())
    passes = (
        calib is not None
        and isinstance(agreement, (int, float))
        and agreement >= _CALIBRATION_AGREEMENT_FLOOR
    )
    meta["passes_quality_gate"] = bool(passes)
    return (calib if passes else None), meta


# ---------------------------------------------------------------------------
# Per-player per-level counts + cohort percentiles (Step 4)
# ---------------------------------------------------------------------------
def assemble_player_levels(
    hitters: list[dict], cache: dict, calib: PixelCalibration | None
) -> dict:
    """{ "<mlbam>": { "AA": {counts+rates, "zone_estimated": bool}, ... } }.

    Level buckets are NEVER blended: a player's AA games and AAA games sum into
    separate buckets. zone_estimated comes from the per-pitch
    zone_pitches_calibrated counter (True when ANY of the level's zone calls were
    made by the pixel calibration rather than real pX/pZ) — not a per-game
    coordinate heuristic, so mixed-coordinate games and pixel-fallback pitches at
    AAA stay honestly labeled.
    """
    ids = {h["mlbam_id"] for h in hitters}
    games = cache.get("games") or {}
    # counts[mlbam][level] = merged counts
    counts: dict[int, dict[str, dict]] = {}
    for game in games.values():
        level = game.get("level")
        all_plays = _compact_to_all_plays(game.get("plays") or [])
        # Which batters in this game are tracked hitters?
        present = {
            (play.get("matchup") or {}).get("batter", {}).get("id")
            for play in all_plays
        } & ids
        for pid in present:
            c = count_player_pitches(all_plays, pid, calib=calib)
            pc = counts.setdefault(pid, {})
            pc[level] = merge_counts(pc.get(level, {}), c)
    out = {}
    for pid, per_level in counts.items():
        levels_out = {}
        for level, c in per_level.items():
            rates = rates_from_counts(c)
            levels_out[level] = {
                "pitches": c.get("pitches", 0),
                "counts": c,
                "rates": rates,
                "zone_estimated": c.get("zone_pitches_calibrated", 0) > 0,
            }
        out[str(pid)] = levels_out
    return out


def _midrank_percentile(sorted_vals: list[float], value: float, lower_is_better: bool) -> int:
    below = bisect_left(sorted_vals, value)
    ties = bisect_right(sorted_vals, value) - below
    pct = 100.0 * (below + 0.5 * ties) / len(sorted_vals)
    if lower_is_better:
        pct = 100.0 - pct
    return max(1, min(99, round(pct)))


def compute_cohort_percentiles(player_levels: dict) -> tuple[dict, dict]:
    """Add per-level percentiles to qualifying buckets (>= MIN_PITCHES). Returns
    (player_levels, cohorts_meta). Percentiles compare within the SAME level cohort,
    and only qualifying players enter the pool. Below the floor: no percentiles.
    """
    # Build per-level pools from qualifying buckets only.
    pools: dict[str, dict[str, list[float]]] = {}
    for levels in player_levels.values():
        for level, bucket in levels.items():
            if bucket.get("pitches", 0) < MIN_PITCHES:
                continue
            metric_pool = pools.setdefault(level, {m: [] for m in ALL_METRICS})
            for m in ALL_METRICS:
                v = (bucket.get("rates") or {}).get(m)
                if isinstance(v, (int, float)):
                    metric_pool[m].append(float(v))
    for level in pools:
        for m in pools[level]:
            pools[level][m].sort()
    # Attach percentiles to qualifying buckets, only for metrics with a defensible
    # quality direction.
    cohort_sizes: dict[str, int] = {}
    for levels in player_levels.values():
        for level, bucket in levels.items():
            if bucket.get("pitches", 0) < MIN_PITCHES:
                bucket["percentiles"] = {}
                bucket["position_percentiles"] = {}
                bucket["qualifies"] = False
                continue
            bucket["qualifies"] = True
            cohort_sizes[level] = cohort_sizes.get(level, 0) + 1
            pcts = {}
            pos_pcts = {}
            for m in ALL_METRICS:
                v = (bucket.get("rates") or {}).get(m)
                vals = pools.get(level, {}).get(m) or []
                if not (isinstance(v, (int, float)) and vals):
                    continue
                if m in LOWER_IS_BETTER or m in HIGHER_IS_BETTER:
                    pcts[m] = _midrank_percentile(vals, float(v), m in LOWER_IS_BETTER)
                else:
                    # Contextual metric (Swing%, Z-Swing%, Zone%): no quality
                    # direction, so it gets a cohort POSITION (never inverted,
                    # never a grade) kept in a separate key so consumers cannot
                    # confuse position with quality.
                    pos_pcts[m] = _midrank_percentile(vals, float(v), False)
            bucket["percentiles"] = pcts
            bucket["position_percentiles"] = pos_pcts
    cohorts_meta = {
        "min_pitches": MIN_PITCHES,
        "cohort_sizes": cohort_sizes,
        "lower_is_better": sorted(LOWER_IS_BETTER),
        "higher_is_better": sorted(HIGHER_IS_BETTER),
    }
    return player_levels, cohorts_meta


# ---------------------------------------------------------------------------
# Artifact assembly + write
# ---------------------------------------------------------------------------
def build_artifact(hitters: list[dict], cache: dict, season: int) -> dict:
    calib, calib_meta = build_calibration(cache)
    player_levels = assemble_player_levels(hitters, cache, calib)
    player_levels, cohorts_meta = compute_cohort_percentiles(player_levels)
    cohorts_meta["calibration"] = calib_meta
    cohorts_meta["zone_metrics_shipped"] = calib is not None
    return {
        "artifact": "valucast_pitch_discipline",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": date.today().isoformat(),
        "season": season,
        "schema_version": 1,
        "source": "mlb_statsapi_play_by_play",
        "source_policy": {
            "kind": "valucast_pitch_discipline",
            "observe_only": True,
            "feeds_value": False,
            "feeds_rank": False,
            "exit_velocity": False,
        },
        "metric_labels": METRIC_LABELS,
        "exact_metrics": list(EXACT_METRICS),
        "estimated_metrics": list(ESTIMATED_METRICS),
        "cohorts": cohorts_meta,
        "players": player_levels,
    }


def _artifact_qualifying_count(payload: dict) -> int:
    n = 0
    for levels in (payload.get("players") or {}).values():
        for bucket in levels.values():
            if bucket.get("qualifies"):
                n += 1
    return n


def _assert_not_tiny_refresh(payload: dict, path: Path) -> None:
    """Refuse to overwrite a healthy artifact with a suspiciously small one."""
    if os.environ.get("VALUCAST_SKIP_DISCIPLINE_TINY_GUARD") == "1":
        return
    if not path.exists():
        return
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    prior_n = _artifact_qualifying_count(prior)
    if prior_n <= 0:
        return
    new_n = _artifact_qualifying_count(payload)
    floor = max(1, int(prior_n * 0.5))
    if new_n < floor:
        raise ValueError(
            "refusing to write tiny plate-discipline refresh: "
            f"qualifying={new_n} prior={prior_n} floor={floor} "
            "(set VALUCAST_SKIP_DISCIPLINE_TINY_GUARD=1 to override)"
        )


def write_artifact(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    _assert_not_tiny_refresh(payload, path)
    # Single atomic pretty write (indent=2 for parity with other data/models files).
    _atomic_write(path, payload, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=date.today().year)
    parser.add_argument("--backfill", action="store_true",
                        help="Season-wide checkpointed backfill (resumable).")
    parser.add_argument("--player", type=int, action="append",
                        help="Restrict to one or more mlbam ids (dev smoke).")
    parser.add_argument("--level", action="append", choices=list(SPORT_LEVELS.values()),
                        help="Restrict to one or more levels (dev smoke).")
    parser.add_argument("--limit-games", type=int, default=None,
                        help="Cap total feed fetches (dev smoke).")
    parser.add_argument("--prune-before-season", type=int, default=None,
                        help="Drop cached games from seasons before this.")
    parser.add_argument("--no-write-artifact", action="store_true",
                        help="Fetch/cache only; skip artifact assembly (dev).")
    args = parser.parse_args(argv)

    hitters = load_tracked_hitters()
    if args.player:
        wanted = set(args.player)
        hitters = [h for h in hitters if h["mlbam_id"] in wanted]
        # Allow smoke on ids not in the universe file.
        have = {h["mlbam_id"] for h in hitters}
        for pid in wanted - have:
            hitters.append({"mlbam_id": pid, "name": None, "level": None})
    if not hitters:
        print("no tracked hitters; nothing to do", flush=True)
        return 0

    cache = load_cache()
    if args.prune_before_season is not None:
        keep = set(range(args.prune_before_season, args.season + 1))
        prune_cache(cache, keep)

    incremental = not args.backfill
    if incremental and not READY_MARKER_PATH.exists():
        # Readiness guard: without the marker the cache is absent OR a partial
        # checkpoint from an interrupted bootstrap. Either way an incremental
        # rebuild would emit a deceptively fresh artifact from incomplete data —
        # preserve the prior artifact instead. If bootstrap recovery takes more
        # than 3 days, validate_pitch_discipline.py fails the build closed.
        print(
            "pitch-discipline cache not marked ready; skipping incremental "
            "refresh, keeping prior artifact (bootstrap workflow owns --backfill "
            "and writes the marker on completion)",
            flush=True,
        )
        return 0
    if incremental and not (cache.get("games") or {}):
        # Cold-cache guard: GitHub runners are ephemeral and the cache is
        # uncommitted, so an empty cache in incremental mode means the "increment"
        # would be a full backfill inside the daily job. Never do that here.
        print(
            "empty pitch cache; skipping incremental fetch, keeping stale artifact "
            "(cold cache — run --backfill manually to rebuild)",
            flush=True,
        )
        return 0

    try:
        stats = gather_games(
            hitters, args.season, cache,
            levels=args.level, limit_games=args.limit_games, incremental=incremental,
        )
    except Exception as exc:  # noqa: BLE001
        if not incremental:
            raise
        # Backstop for unexpected (non-per-request) errors: leave artifact + cache
        # untouched, exit 0 so the daily build continues.
        print(f"plate-discipline incremental fetch failed, keeping stale artifact: {exc}",
              flush=True)
        return 0

    flush_cache(cache)
    print(
        f"fetched={stats['fetched']} cached_total={stats['cached_total']} "
        f"skipped={stats['skipped']} new_pks={stats['new_pks']} "
        f"gamelog_failures={stats['gamelog_failures']}/{stats['gamelog_total']} "
        f"feed_failures={stats['feed_failures']} non_final={stats['non_final_skipped']}",
        flush=True,
    )

    if incremental and stats["budget_exceeded"]:
        print(
            f"incremental new-game budget exceeded ({stats['new_pks']} > "
            f"{_INCREMENTAL_NEW_PK_BUDGET}); skipping fetch, keeping stale artifact "
            "(stale cache — run --backfill manually to catch up)",
            flush=True,
        )
        return 0
    if incremental and _failures_over_budget(stats):
        print(
            "incremental fetch failures over budget; keeping stale artifact "
            f"(feed_failures={stats['feed_failures']}, "
            f"gamelog_failures={stats['gamelog_failures']}/{stats['gamelog_total']})",
            flush=True,
        )
        return 0

    if args.no_write_artifact:
        return 0

    payload = build_artifact(hitters, cache, args.season)
    try:
        path = write_artifact(payload)
    except ValueError as exc:
        if not incremental:
            raise  # backfill/manual runs must fail loudly on a tiny refresh
        print(f"tiny-refresh guard tripped; keeping stale artifact: {exc}", flush=True)
        return 0
    cal = payload["cohorts"]["calibration"]
    print(
        "plate-discipline artifact: "
        f"players={len(payload['players'])} "
        f"qualifying={_artifact_qualifying_count(payload)} "
        f"cohorts={payload['cohorts']['cohort_sizes']} "
        f"calib_n_pairs={cal.get('n_pairs')} calib_r2={cal.get('fit_r2')} "
        f"agreement={cal.get('held_out_agreement_pct')} "
        f"zone_shipped={payload['cohorts']['zone_metrics_shipped']} "
        f"-> {path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
