"""ValuCast-owned plate-discipline counting from MLB StatsAPI play-by-play.

Pure functions over already-fetched game-feed play lists; NO network, NO file I/O
(fetch + I/O live in scripts/build_pitch_discipline.py). Observe-only display
context, NEVER a value input (the milb_translation precedent).

EXACT vs ESTIMATED split:
  - Swing/Whiff/SwStr are MEASURED from pitch-outcome descriptions (exact — matched
    ProspectSavant to the decimal in the 7/10 spike: Sirota mlbam 701527, 41 AA
    games, Swing% 37.4 vs 37.4, SwStr% 9.2 vs 9.25).
  - Zone metrics (Chase/Z-Swing/Z-Contact/Zone) are ESTIMATED from legacy pixel
    coordinates because modern tracked pX/pZ are 100% absent at AA. They carry
    zone_estimated=True and MUST render tagged as estimates.
  - Exit velocity is IMPOSSIBLE from public MiLB play-by-play (no batted-ball
    tracking) and is never produced here. Do not add it.

The counting DEFINITIONS are the contract (they matched ProspectSavant on 7/10):
  swing = ball in play OR swinging/foul (+ bunt specials); whiff = swinging strike
  OR missed bunt OR caught foul tip (Savant convention, unified with the AAA
  Statcast layer 2026-07-30 — a documented display-only re-baseline). Changing
  them re-baselines every number — the fixture test is the regression lock.
"""
from __future__ import annotations

import math

# Plate half-width in feet (rulebook zone ~17in plate + ball radius); used only when
# REAL tracked coords (pX/pZ) exist. Pixel coords go through PixelCalibration instead.
_ZONE_HALF_WIDTH_FT = 0.83

# League-default vertical strike-zone band in feet, used only when a pitch has
# coordinates but no strikeZoneTop/Bottom (a rare edge — the 7/10 pre-flight found
# sz present on 100% of sampled pitches at AAA/AA/A+). Pitches that fall back to this
# band are counted toward an estimated_quality denominator so methodology can state
# what fraction of zone calls used the fallback.
_DEFAULT_SZ_TOP_FT = 3.5
_DEFAULT_SZ_BOTTOM_FT = 1.5

# The metric keys this layer produces, split by measurement honesty. EXACT metrics
# are counted from pitch descriptions; ESTIMATED metrics depend on a pixel->feet
# calibration for the zone and carry estimated=True on the card.
EXACT_METRICS = ("swing_pct", "whiff_pct", "swstr_pct")
ESTIMATED_METRICS = ("chase_pct", "z_swing_pct", "z_contact_pct", "zone_pct")


def _is_swing(desc: str, is_in_play: bool) -> bool:
    """A swing = ball put in play, OR the description says the batter swung/fouled.

    Bunts are special-cased: a foul bunt or missed bunt is a swing attempt.
    """
    if is_in_play:
        return True
    if "foul bunt" in desc or "missed bunt" in desc:
        return True
    return "swinging" in desc or "foul" in desc


def _is_whiff(desc: str) -> bool:
    """A whiff = swing that missed: "swinging strike" (incl. "...blocked"), a
    swinging pitchout, a missed bunt, or a caught foul tip (incl. the bunt
    variant — the substring covers the family). NOT an ordinary foul (contact).

    The foul-tip rule is the Savant convention (a foul tip is by rule a
    swinging strike), adopted 2026-07-30 so this layer and the AAA Statcast
    layer put the same events behind the one "Whiff%" label. Display-only
    re-baseline: Whiff%/SwStr%/Z-Contact% shift slightly at that date."""
    return (
        "swinging strike" in desc
        or "swinging pitchout" in desc
        or "missed bunt" in desc
        or "foul tip" in desc
    )


def _real_zone_coords(pitch_data: dict) -> tuple[float, float, float, float] | None:
    """(pX, pZ, szTop, szBottom) when ALL are usable real numbers, else None.

    This is the single source of truth for "did this pitch carry MEASURED zone
    inputs" — classify_zone uses it to pick the real path, and count_player_pitches
    uses it to count zone_pitches_calibrated (the pitches where the pixel
    calibration, not real coords, made the zone call). Keeping one predicate means
    the estimated/measured split can never drift between the two."""
    co = pitch_data.get("coordinates") or {}
    px, pz = co.get("pX"), co.get("pZ")
    szt, szb = pitch_data.get("strikeZoneTop"), pitch_data.get("strikeZoneBottom")
    if (
        isinstance(px, (int, float))
        and isinstance(pz, (int, float))
        and isinstance(szt, (int, float))
        and isinstance(szb, (int, float))
    ):
        return float(px), float(pz), float(szt), float(szb)
    return None


def classify_zone(pitch_data: dict, calib: "PixelCalibration | None" = None) -> bool | None:
    """True=in-zone, False=out-of-zone, None=cannot determine.

    Order of preference:
      1. Real tracked pX/pZ (present at AAA, absent at AA): |pX| <= 0.83 ft and
         szBottom <= pZ <= szTop. This is the ground truth the pixel calibration
         is fit against.
      2. Legacy pixel coords.{x,y} + strikeZoneTop/Bottom, mapped to feet via a
         fitted affine calibration (PixelCalibration). ESTIMATE.
      3. Missing strikeZoneTop/Bottom -> a league-default vertical band (still an
         estimate; PixelCalibration.classify flags it toward estimated_quality).
      4. No usable coords at all -> None (excluded from zone denominators).
    """
    real = _real_zone_coords(pitch_data)
    if real is not None:
        px, pz, szt, szb = real
        return abs(px) <= _ZONE_HALF_WIDTH_FT and szb <= pz <= szt
    co = pitch_data.get("coordinates") or {}
    x, y = co.get("x"), co.get("y")
    szt = pitch_data.get("strikeZoneTop")
    szb = pitch_data.get("strikeZoneBottom")
    if calib is not None and isinstance(x, (int, float)) and isinstance(y, (int, float)):
        return calib.classify(x, y, szt, szb)
    return None


def count_player_pitches(all_plays: list, batter_id: int, calib: "PixelCalibration | None" = None) -> dict:
    """Per-pitch counts for one batter across one game's allPlays.

    Returns a dict of raw integer counts (never rates): pitches, swings, whiffs,
    contact, plus zone-conditioned counts when coordinates are usable:
    in_zone, out_zone, o_swings (chase), z_swings, z_contact, plus
    zone_pitches_with_coords (denominator honesty), zone_pitches_calibrated (zone
    calls made by the pixel calibration rather than real pX/pZ — the per-pitch
    truth behind the level's zone_estimated flag), and zone_pitches_fallback_sz
    (how many zone calls used the default vertical band). Rates are computed later,
    once, from summed counts (rates_from_counts) — so multi-game aggregation stays
    exact (sum counts, then divide once; never average rates).

    `calib` is an optional pixel->feet calibration for the estimated zone metrics.
    When None, only the exact counts and any real-pX/pZ zone counts are produced.
    """
    c = {
        "pitches": 0, "swings": 0, "whiffs": 0, "contact": 0,
        "in_zone": 0, "out_zone": 0, "o_swings": 0, "z_swings": 0,
        "z_contact": 0, "zone_pitches_with_coords": 0,
        "zone_pitches_calibrated": 0, "zone_pitches_fallback_sz": 0,
    }
    for play in all_plays:
        matchup = play.get("matchup") or {}
        if (matchup.get("batter") or {}).get("id") != batter_id:
            continue
        for ev in play.get("playEvents") or ():
            if not ev.get("isPitch"):
                continue
            det = ev.get("details") or {}
            desc = (det.get("description") or "").lower()
            is_in_play = bool(det.get("isInPlay"))
            # Intentional balls / pitchouts / automatic balls are not swing
            # opportunities in the usual sense but ARE pitches seen; they simply
            # never register as swings (no swinging/foul/inplay in the description).
            c["pitches"] += 1
            swing = _is_swing(desc, is_in_play)
            if swing:
                c["swings"] += 1
                if _is_whiff(desc):
                    c["whiffs"] += 1
                else:
                    c["contact"] += 1
            # Zone conditioning (estimated at pixel levels) — only when usable.
            pd = ev.get("pitchData") or {}
            zone = classify_zone(pd, calib)   # True=in, False=out, None=unusable
            if zone is not None:
                c["zone_pitches_with_coords"] += 1
                if _real_zone_coords(pd) is None:
                    # The pixel calibration (not real pX/pZ) made this zone call.
                    c["zone_pitches_calibrated"] += 1
                szt = pd.get("strikeZoneTop")
                szb = pd.get("strikeZoneBottom")
                if not (isinstance(szt, (int, float)) and isinstance(szb, (int, float))):
                    c["zone_pitches_fallback_sz"] += 1
                if zone:
                    c["in_zone"] += 1
                    if swing:
                        c["z_swings"] += 1
                        if not _is_whiff(desc):
                            c["z_contact"] += 1
                else:
                    c["out_zone"] += 1
                    if swing:
                        c["o_swings"] += 1   # chase
    return c


def merge_counts(a: dict, b: dict) -> dict:
    """Sum two count dicts key-by-key (season aggregation across games)."""
    keys = set(a) | set(b)
    return {k: int(a.get(k, 0)) + int(b.get(k, 0)) for k in keys}


def _ratio(num: int, den: int) -> float | None:
    """num/den*100 rounded to 1 decimal, or None when the denominator is 0.

    Never a divide-by-zero, never a fabricated 0%.
    """
    return round(float(num) / float(den) * 100.0, 1) if den else None


def rates_from_counts(counts: dict) -> dict:
    """Display rates from summed counts (aggregation stays exact: sum then divide).

    Exact rates:  swing_pct = swings/pitches, whiff_pct = whiffs/swings,
                  swstr_pct = whiffs/pitches.
    Estimated rates (zone): chase_pct = o_swings/out_zone,
                  z_swing_pct = z_swings/in_zone, z_contact_pct = z_contact/z_swings,
                  zone_pct = in_zone/zone_pitches_with_coords.
    Each rate is None when its denominator is 0.
    """
    return {
        "swing_pct": _ratio(counts.get("swings", 0), counts.get("pitches", 0)),
        "whiff_pct": _ratio(counts.get("whiffs", 0), counts.get("swings", 0)),
        "swstr_pct": _ratio(counts.get("whiffs", 0), counts.get("pitches", 0)),
        "chase_pct": _ratio(counts.get("o_swings", 0), counts.get("out_zone", 0)),
        "z_swing_pct": _ratio(counts.get("z_swings", 0), counts.get("in_zone", 0)),
        "z_contact_pct": _ratio(counts.get("z_contact", 0), counts.get("z_swings", 0)),
        "zone_pct": _ratio(
            counts.get("in_zone", 0), counts.get("zone_pitches_with_coords", 0)
        ),
    }


class PixelCalibration:
    """Fitted affine pixel->feet map for the ESTIMATED zone metrics (Step 3).

    Legacy pitchData.coordinates.{x,y} are screen pixels; pX/pZ are feet. A single
    global affine map (pX ~= a*x + b, pZ ~= c*y + d) is fit by least squares over
    (pixel, feet) pairs where BOTH exist (AAA carries both on ~99.7% of pitches).
    The fitted coefficients live in the artifact metadata so the numbers on the card
    are reproducible from the committed artifact.

    This is an ESTIMATE. Every zone metric derived from it carries estimated=True and
    the card tags it "est." with a methodology link.
    """

    def __init__(self, a: float, b: float, c: float, d: float) -> None:
        self.a, self.b, self.c, self.d = float(a), float(b), float(c), float(d)

    def to_feet(self, x: float, y: float) -> tuple[float, float]:
        """Map a pixel (x, y) to estimated (pX, pZ) in feet."""
        return self.a * x + self.b, self.c * y + self.d

    def classify(self, x: float, y: float, sz_top, sz_bottom) -> bool:
        """True=in-zone, False=out, from pixel coords via the affine map.

        Missing sz_top/sz_bottom falls back to the documented league-default band.
        """
        px_est, pz_est = self.to_feet(x, y)
        top = sz_top if isinstance(sz_top, (int, float)) else _DEFAULT_SZ_TOP_FT
        bottom = sz_bottom if isinstance(sz_bottom, (int, float)) else _DEFAULT_SZ_BOTTOM_FT
        return abs(px_est) <= _ZONE_HALF_WIDTH_FT and bottom <= pz_est <= top

    def as_dict(self) -> dict:
        return {"a": self.a, "b": self.b, "c": self.c, "d": self.d}

    @classmethod
    def from_dict(cls, data: dict | None) -> "PixelCalibration | None":
        if not isinstance(data, dict):
            return None
        try:
            return cls(data["a"], data["b"], data["c"], data["d"])
        except (KeyError, TypeError, ValueError):
            return None


def fit_pixel_calibration(pairs: list[tuple]) -> tuple["PixelCalibration | None", dict]:
    """Least-squares fit of pX~=a*x+b and pZ~=c*y+d over paired samples.

    Each pair's first four elements are (x, y, pX, pZ); longer tuples (e.g. the
    6-tuples carrying szTop/szBottom for the held-out agreement check) are fine —
    only the first four are read. Returns (PixelCalibration or None, quality dict).
    The two axes fit independently (a 1-D least squares each). Quality reports
    n_pairs and per-axis R^2 so the global-vs-per-venue-fit follow-up decision is
    data-driven. Returns (None, {...}) when there are too few pairs to fit
    (needs >= 2 distinct x and 2 distinct y).
    """
    xs = [p[0] for p in pairs]
    ys = [p[1] for p in pairs]
    pxs = [p[2] for p in pairs]
    pzs = [p[3] for p in pairs]
    fit_x = _fit_line(xs, pxs)
    fit_y = _fit_line(ys, pzs)
    quality = {
        "n_pairs": len(pairs),
        "fit_r2_x": None if fit_x is None else round(fit_x[2], 4),
        "fit_r2_y": None if fit_y is None else round(fit_y[2], 4),
    }
    if fit_x is None or fit_y is None:
        return None, quality
    a, b, _ = fit_x
    c, d, _ = fit_y
    quality["fit_r2"] = round(min(fit_x[2], fit_y[2]), 4)
    return PixelCalibration(a, b, c, d), quality


def _fit_line(xs: list[float], ys: list[float]) -> tuple[float, float, float] | None:
    """Simple 1-D OLS: returns (slope, intercept, r2) or None if under-determined."""
    n = len(xs)
    if n < 2:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    syy = sum((y - mean_y) ** 2 for y in ys)
    if syy == 0:
        r2 = 1.0
    else:
        ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in zip(xs, ys))
        r2 = max(0.0, 1.0 - ss_res / syy)
    return slope, intercept, r2


def calibration_agreement(pairs: list[tuple],
                          calib: "PixelCalibration") -> float | None:
    """Held-out agreement %: on (x, y, pX, pZ, szTop, szBottom) tuples where the
    REAL pX/pZ give a ground-truth in/out call, what fraction does the pixel
    calibration match?

    Each pair's OWN strike zone scores BOTH sides (the real-coords truth and the
    calibrated call); the league-default band is only the fallback when a pair's
    szTop/szBottom are absent. Score this on pairs HELD OUT of the fit — an
    in-sample number overstates quality.

    This is the calibration-quality check (Step 3): ship the estimate only when the
    calibrated call agrees with the real coords on a high fraction (plan bar: >85%).
    """
    if not pairs:
        return None
    agree = 0
    total = 0
    for x, y, px, pz, szt, szb in pairs:
        top = szt if isinstance(szt, (int, float)) else _DEFAULT_SZ_TOP_FT
        bottom = szb if isinstance(szb, (int, float)) else _DEFAULT_SZ_BOTTOM_FT
        real = abs(px) <= _ZONE_HALF_WIDTH_FT and bottom <= pz <= top
        est = calib.classify(x, y, szt, szb)
        total += 1
        if real == est:
            agree += 1
    return round(100.0 * agree / total, 1) if total else None


def _edge_distance_in(px: float, pz: float, top: float, bottom: float) -> float:
    """Distance (inches) from the REAL pitch location to the strike-zone
    RECTANGLE's boundary — small values are the borderline calls where a
    calibration's overall agreement number can hide its worst behavior.

    Inside the zone this is the distance to the nearest edge; outside it is
    the Euclidean distance to the nearest point of the rectangle (diagonal
    past a corner). Never the distance to a boundary LINE's infinite
    extension — a pitch far outside can align with the top line's height
    while being nowhere near the zone."""
    dx = abs(px) - _ZONE_HALF_WIDTH_FT
    dz = max(bottom - pz, pz - top)
    if dx <= 0 and dz <= 0:
        return min(-dx, -dz) * 12.0
    return math.hypot(max(dx, 0.0), max(dz, 0.0)) * 12.0


def calibration_agreement_bands(
    pairs: list[tuple],
    calib: "PixelCalibration",
    edge_bands_in: tuple[float, ...] = (3.0, 1.0),
) -> dict:
    """Agreement overall AND on borderline subsets (audit F3).

    Same held-out (x, y, pX, pZ, szTop, szBottom) pairs and per-pair-zone
    scoring as calibration_agreement, but also scored on the subsets whose
    real location lies within each edge band (inches from the zone boundary).
    Returns {"overall": {"n", "agreement_pct"}, "within_<band>in": {...}} with
    agreement_pct None when a subset is empty — a thin borderline sample must
    read as unmeasured, never as perfect.
    """
    buckets: dict[str, list[int]] = {
        "overall": [0, 0],
        **{f"within_{band:g}in": [0, 0] for band in edge_bands_in},
    }
    for x, y, px, pz, szt, szb in pairs:
        top = szt if isinstance(szt, (int, float)) else _DEFAULT_SZ_TOP_FT
        bottom = szb if isinstance(szb, (int, float)) else _DEFAULT_SZ_BOTTOM_FT
        real = abs(px) <= _ZONE_HALF_WIDTH_FT and bottom <= pz <= top
        agreed = calib.classify(x, y, szt, szb) == real
        dist = _edge_distance_in(px, pz, top, bottom)
        keys = ["overall"] + [
            f"within_{band:g}in" for band in edge_bands_in if dist <= band
        ]
        for key in keys:
            buckets[key][0] += 1
            if agreed:
                buckets[key][1] += 1
    return {
        key: {
            "n": n,
            "agreement_pct": round(100.0 * agree / n, 1) if n else None,
        }
        for key, (n, agree) in buckets.items()
    }
