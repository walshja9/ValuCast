"""Build the AAA-Statcast per-player feature artifact from the cached pitch slices.

PURE aggregation: ZERO network, ZERO Savant fetch. Reads the compact game cache
(scripts/refresh_aaa_statcast.py) and rolls it into a compact per-player artifact:

  Per PITCHER (pitch shape + plate outcomes):
    per pitch_type -> {avg velo, IVB (pfx_z*12 in inches), HB (pfx_x*12), avg spin,
                       avg extension, usage share, n}
    overall        -> {whiff%, csw%, chase%, zone%, gb%} + n_pitches
  Per HITTER (contact quality):
    {avg_ev, hardhit% (EV>=95), max_ev, avg_la, whiff%, chase%, gb%, n_bip, n_pitches}

Everything is keyed by mlbam id as str (pitcher/batter columns ARE mlbam ids). Output
is scoped to the tracked prospect universe to bound size (~400KB). Hard minimum-sample
gates (mirroring build_pitch_discipline.MIN_PITCHES discipline) omit any metric below
threshold. Atomic write with an artifact/schema_version/generated_at/source/counts
envelope + a tiny-refresh guard.

MEASURED, not estimated: unlike the StatsAPI pitch-discipline layer (which pixel-
calibrates zone metrics at AAA), zone% / chase% here come from REAL plate_x/plate_z vs
each pitch's own sz_top/sz_bot. These render WITHOUT any "est." tag.

OBSERVE-ONLY: display context, never a value/rank/peak/AOTC input. AAA only -- EV is
never presented for AA/A+ (this source only carries AAA rows by construction).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.refresh_aaa_statcast import CACHE_PATH, load_cache  # noqa: E402

# --- Paths -----------------------------------------------------------------
UNIVERSE_PATH = ROOT / "data" / "models" / "valucast_prospect_universe.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_aaa_statcast_features.json"

# --- Sample gates (small-sample honesty; analogous to MIN_PITCHES=300) ------
# A pitcher needs this many pitches overall before any plate-outcome rate renders;
# a pitch_type needs this many before its shape row renders (a 6-pitch changeover
# sample is noise). A hitter needs this many balls in play before EV metrics render
# and this many pitches before whiff/chase render.
MIN_PITCHER_PITCHES = 200
MIN_PITCH_TYPE = 25
MIN_HITTER_BIP = 25
MIN_HITTER_PITCHES = 100

# Contact-quality threshold: "hard-hit" is the Statcast standard of EV >= 95 mph.
HARDHIT_EV = 95.0

# Half-plate width in feet for the zone call (17-in plate + ball radius), matching
# prospects.pitch_discipline._ZONE_HALF_WIDTH_FT so the two layers agree on geometry.
_ZONE_HALF_WIDTH_FT = 0.83

_INCHES_PER_FOOT = 12.0

# Whiff = swinging strike (incl. blocked), swinging pitchout, missed bunt, or a
# caught foul tip — by rule a foul tip is a swinging strike, and Savant's own CSW
# definition includes it (fouls excluded, foul tips included).
_WHIFF_DESCS = frozenset({
    "swinging_strike", "swinging_strike_blocked", "swinging_pitchout", "missed_bunt",
    "foul_tip",
})
# A swing = ball in play OR a swing-and-miss OR a foul (contact) + bunt specials.
_SWING_DESCS = frozenset({
    "hit_into_play", "foul", "foul_bunt",
}) | _WHIFF_DESCS
# CSW = called strike + whiff (the "called-strikes-plus-whiffs" rate).
_CALLED_STRIKE_DESCS = frozenset({"called_strike"})


def _is_swing(desc: str | None) -> bool:
    return desc in _SWING_DESCS


def _is_whiff(desc: str | None) -> bool:
    return desc in _WHIFF_DESCS


def _in_zone(plate_x, plate_z, sz_top, sz_bot) -> bool | None:
    """Real-coordinate zone call: True/False in/out, None when inputs are missing.

    Uses each pitch's OWN sz_top/sz_bot (measured), never a default band -- this is
    what makes the AAA layer's zone metrics MEASURED rather than estimated.
    """
    if not all(isinstance(v, (int, float)) for v in (plate_x, plate_z, sz_top, sz_bot)):
        return None
    return (
        abs(float(plate_x)) <= _ZONE_HALF_WIDTH_FT
        and float(sz_bot) <= float(plate_z) <= float(sz_top)
    )


# ---------------------------------------------------------------------------
# Universe scope
# ---------------------------------------------------------------------------
def load_universe_ids(path: Path = UNIVERSE_PATH) -> tuple[set[str], set[str]]:
    """(pitcher_ids, hitter_ids) as str(mlbam) from the tracked universe.

    Both roles are needed: pitch-shape rolls up for pitchers, contact-quality for
    hitters. Fail-soft to empty sets on a missing/malformed universe.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), set()
    pitchers: set[str] = set()
    hitters: set[str] = set()
    for p in payload.get("players") or ():
        mlbam = p.get("mlbam_id")
        if not isinstance(mlbam, int):
            continue
        if p.get("role") == "pitcher":
            pitchers.add(str(mlbam))
        else:
            hitters.add(str(mlbam))
    return pitchers, hitters


# ---------------------------------------------------------------------------
# Accumulators
# ---------------------------------------------------------------------------
def _iter_pitches(cache: dict):
    for game in (cache.get("games") or {}).values():
        for pitch in game.get("pitches") or ():
            yield pitch


def _mean(total: float, n: int) -> float | None:
    return round(total / n, 2) if n else None


def aggregate_pitchers(cache: dict, pitcher_ids: set[str]) -> dict:
    """Per-pitcher pitch-shape + plate outcomes, scoped to tracked pitchers."""
    # shape[pid][pitch_type] = running sums; outcome[pid] = running plate-outcome sums.
    shape: dict[str, dict[str, dict]] = {}
    outcome: dict[str, dict] = {}
    for p in _iter_pitches(cache):
        pid = p.get("pitcher")
        if not isinstance(pid, str) or pid not in pitcher_ids:
            continue
        oc = outcome.setdefault(pid, {
            "n": 0, "swings": 0, "whiffs": 0, "called": 0,
            "zone": 0, "zone_denom": 0, "out_swings": 0, "out_pitches": 0,
            "bip": 0, "gb": 0,
        })
        oc["n"] += 1
        desc = p.get("description")
        swing = _is_swing(desc)
        if swing:
            oc["swings"] += 1
        if _is_whiff(desc):
            oc["whiffs"] += 1
        if desc in _CALLED_STRIKE_DESCS:
            oc["called"] += 1
        zone = _in_zone(p.get("plate_x"), p.get("plate_z"), p.get("sz_top"), p.get("sz_bot"))
        if zone is not None:
            oc["zone_denom"] += 1
            if zone:
                oc["zone"] += 1
            else:
                # Chase = swing at a pitch OUTSIDE the zone / out-of-zone pitches.
                oc["out_pitches"] += 1
                if swing:
                    oc["out_swings"] += 1
        bb_type = p.get("bb_type")
        if isinstance(bb_type, str) and bb_type:
            oc["bip"] += 1
            if bb_type == "ground_ball":
                oc["gb"] += 1
        # Pitch-shape sums (only when the pitch is typed + has the field).
        pt = p.get("pitch_type")
        if not isinstance(pt, str) or not pt:
            continue
        row = shape.setdefault(pid, {}).setdefault(pt, {
            "n": 0, "velo": 0.0, "velo_n": 0, "ivb": 0.0, "ivb_n": 0,
            "hb": 0.0, "hb_n": 0, "spin": 0.0, "spin_n": 0, "ext": 0.0, "ext_n": 0,
        })
        row["n"] += 1
        _add(row, "velo", p.get("release_speed"))
        _add(row, "ivb", p.get("pfx_z"), scale=_INCHES_PER_FOOT)
        _add(row, "hb", p.get("pfx_x"), scale=_INCHES_PER_FOOT)
        _add(row, "spin", p.get("release_spin_rate"))
        _add(row, "ext", p.get("release_extension"))

    out: dict[str, dict] = {}
    for pid, oc in outcome.items():
        if oc["n"] < MIN_PITCHER_PITCHES:
            continue
        player: dict = {"n_pitches": oc["n"]}
        rates = _pitcher_rates(oc)
        if rates:
            player["overall"] = rates
        pitches = _pitch_type_rows(shape.get(pid, {}), oc["n"])
        if pitches:
            player["pitch_types"] = pitches
        if len(player) > 1:  # more than just n_pitches
            out[pid] = player
    return out


def _add(row: dict, key: str, value, *, scale: float = 1.0) -> None:
    if isinstance(value, (int, float)):
        row[key] += float(value) * scale
        row[f"{key}_n"] += 1


def _pitcher_rates(oc: dict) -> dict:
    rates: dict = {}
    if oc["swings"]:
        rates["whiff_pct"] = round(100.0 * oc["whiffs"] / oc["swings"], 1)
    if oc["n"]:
        rates["csw_pct"] = round(100.0 * (oc["called"] + oc["whiffs"]) / oc["n"], 1)
    if oc["zone_denom"]:
        rates["zone_pct"] = round(100.0 * oc["zone"] / oc["zone_denom"], 1)
    if oc["out_pitches"]:
        rates["chase_pct"] = round(100.0 * oc["out_swings"] / oc["out_pitches"], 1)
    if oc["bip"]:
        rates["gb_pct"] = round(100.0 * oc["gb"] / oc["bip"], 1)
    return rates


def _pitch_type_rows(shape: dict, total_pitches: int) -> dict:
    rows: dict = {}
    for pt, s in shape.items():
        if s["n"] < MIN_PITCH_TYPE:
            continue
        row = {
            "n": s["n"],
            "usage_pct": round(100.0 * s["n"] / total_pitches, 1) if total_pitches else None,
            "velo": _mean(s["velo"], s["velo_n"]),
            "ivb": _mean(s["ivb"], s["ivb_n"]),
            "hb": _mean(s["hb"], s["hb_n"]),
            "spin": round(s["spin"] / s["spin_n"]) if s["spin_n"] else None,
            "ext": _mean(s["ext"], s["ext_n"]),
        }
        rows[pt] = row
    return rows


def aggregate_hitters(cache: dict, hitter_ids: set[str]) -> dict:
    """Per-hitter contact-quality + plate outcomes, scoped to tracked hitters."""
    acc: dict[str, dict] = {}
    for p in _iter_pitches(cache):
        bid = p.get("batter")
        if not isinstance(bid, str) or bid not in hitter_ids:
            continue
        h = acc.setdefault(bid, {
            "n": 0, "swings": 0, "whiffs": 0,
            "out_swings": 0, "out_pitches": 0,
            "bip": 0, "gb": 0,
            "ev_sum": 0.0, "ev_n": 0, "max_ev": None, "hardhit": 0,
            "la_sum": 0.0, "la_n": 0,
        })
        h["n"] += 1
        desc = p.get("description")
        swing = _is_swing(desc)
        if swing:
            h["swings"] += 1
        if _is_whiff(desc):
            h["whiffs"] += 1
        zone = _in_zone(p.get("plate_x"), p.get("plate_z"), p.get("sz_top"), p.get("sz_bot"))
        if zone is not None and not zone:
            h["out_pitches"] += 1
            if swing:
                h["out_swings"] += 1
        bb_type = p.get("bb_type")
        if isinstance(bb_type, str) and bb_type:
            h["bip"] += 1
            if bb_type == "ground_ball":
                h["gb"] += 1
            # Contact quality counts batted-ball events ONLY: Savant populates
            # launch_speed on routine fouls too, and including them tanks avg
            # EV / hard-hit% on a card labeled as measured.
            ev = p.get("launch_speed")
            if isinstance(ev, (int, float)):
                h["ev_sum"] += float(ev)
                h["ev_n"] += 1
                if h["max_ev"] is None or ev > h["max_ev"]:
                    h["max_ev"] = float(ev)
                if ev >= HARDHIT_EV:
                    h["hardhit"] += 1
            la = p.get("launch_angle")
            if isinstance(la, (int, float)):
                h["la_sum"] += float(la)
                h["la_n"] += 1

    out: dict[str, dict] = {}
    for bid, h in acc.items():
        if h["n"] < MIN_HITTER_PITCHES:
            continue
        player: dict = {"n_pitches": h["n"], "n_bip": h["bip"]}
        # Plate outcomes gate on pitches seen.
        if h["swings"]:
            player["whiff_pct"] = round(100.0 * h["whiffs"] / h["swings"], 1)
        if h["out_pitches"]:
            player["chase_pct"] = round(100.0 * h["out_swings"] / h["out_pitches"], 1)
        if h["bip"]:
            player["gb_pct"] = round(100.0 * h["gb"] / h["bip"], 1)
        # Contact quality gates on batted-ball sample.
        if h["ev_n"] >= MIN_HITTER_BIP:
            player["avg_ev"] = round(h["ev_sum"] / h["ev_n"], 1)
            player["max_ev"] = round(h["max_ev"], 1) if h["max_ev"] is not None else None
            player["hardhit_pct"] = round(100.0 * h["hardhit"] / h["ev_n"], 1)
        if h["la_n"] >= MIN_HITTER_BIP:
            player["avg_la"] = round(h["la_sum"] / h["la_n"], 1)
        # Keep a player only if some metric beyond the counts survived the gate.
        if len(player) > 2:
            out[bid] = player
    return out


# ---------------------------------------------------------------------------
# Artifact assembly + write
# ---------------------------------------------------------------------------
def build_artifact(cache: dict, season: int, universe_path: Path = UNIVERSE_PATH) -> dict:
    pitcher_ids, hitter_ids = load_universe_ids(universe_path)
    pitchers = aggregate_pitchers(cache, pitcher_ids)
    hitters = aggregate_hitters(cache, hitter_ids)
    return {
        "artifact": "valucast_aaa_statcast_features",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": date.today().isoformat(),
        "season": season,
        "source": "baseball_savant_statcast_minors_aaa",
        "source_policy": {
            "kind": "valucast_aaa_statcast_features",
            "level": "AAA",
            "measured": True,
            "observe_only": True,
            "feeds_value": False,
            "feeds_rank": False,
        },
        "gates": {
            "min_pitcher_pitches": MIN_PITCHER_PITCHES,
            "min_pitch_type": MIN_PITCH_TYPE,
            "min_hitter_bip": MIN_HITTER_BIP,
            "min_hitter_pitches": MIN_HITTER_PITCHES,
            "hardhit_ev": HARDHIT_EV,
        },
        "counts": {
            "games": len(cache.get("games") or {}),
            "pitchers": len(pitchers),
            "hitters": len(hitters),
        },
        "pitchers": pitchers,
        "hitters": hitters,
    }


def _artifact_player_count(payload: dict) -> int:
    return len(payload.get("pitchers") or {}) + len(payload.get("hitters") or {})


def _assert_not_tiny_refresh(payload: dict, path: Path) -> None:
    """Refuse to overwrite a healthy artifact with a drastically smaller one."""
    if os.environ.get("VALUCAST_SKIP_AAA_STATCAST_TINY_GUARD") == "1":
        return
    if not path.exists():
        return
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    prior_n = _artifact_player_count(prior)
    if prior_n <= 0:
        return
    new_n = _artifact_player_count(payload)
    floor = max(1, int(prior_n * 0.5))
    if new_n < floor:
        raise ValueError(
            "refusing to write tiny AAA-statcast refresh: "
            f"players={new_n} prior={prior_n} floor={floor} "
            "(set VALUCAST_SKIP_AAA_STATCAST_TINY_GUARD=1 to override)"
        )


def write_artifact(payload: dict, path: Path = ARTIFACT_PATH) -> Path:
    _assert_not_tiny_refresh(payload, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, separators=(",", ":")) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=date.today().year)
    parser.add_argument("--cache-path", type=Path, default=CACHE_PATH)
    parser.add_argument("--out", type=Path, default=ARTIFACT_PATH)
    args = parser.parse_args(argv)

    cache = load_cache(args.cache_path)
    if not (cache.get("games") or {}):
        # Cold cache: no data to aggregate. Keep the stale artifact (if any) and
        # no-op so the daily build continues (the reader/card fail soft too).
        print(
            "empty AAA statcast cache; skipping feature build, keeping stale artifact "
            "(cold cache -- run refresh_aaa_statcast.py --backfill first)",
            flush=True,
        )
        return 0

    payload = build_artifact(cache, args.season)
    try:
        path = write_artifact(payload, args.out)
    except ValueError as exc:
        print(f"tiny-refresh guard tripped; keeping stale artifact: {exc}", flush=True)
        return 0
    print(
        "AAA statcast features: "
        f"games={payload['counts']['games']} "
        f"pitchers={payload['counts']['pitchers']} "
        f"hitters={payload['counts']['hitters']} -> {path}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
