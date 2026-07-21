"""ValuCast-owned MLB-equivalent translation of a prospect's STICKY minor-league
peripheral rates, plus best-single-level sample selection.

Independence note: this is the ValuCast-owned port of what DD's milb_translation.py
+ generate_valucast_feed._best_single_level_stat_line used to compute. The math is
ported verbatim (the per-level retention multipliers and MLB-mean anchors are
research-grounded constants, not derived) so the owned output matches the prior
DD-produced values — an ownership move, not a model change. Improving the math is a
separate later quality pass.

Scope (deliberately narrow): only the peripherals that survive the minors->MLB jump
per the stickiness literature — K%, BB%, ISO for hitters; K/9, BB/9, K-BB% for
pitchers. NOT a projection and NOT a value input: AVG/OPS/ERA/WHIP and counting
totals are omitted because they don't translate without playing-time + park
assumptions. Pure functions over already-loaded MiLB rows; NO file I/O, NO import of
valuation / z-scores / projections — cannot affect the 0-150 value by construction.
"""
from __future__ import annotations

# Minor-league level ordering (higher = closer to MLB) for picking the top level.
_LEVEL_RANK = {
    "AAA": 7, "AA": 6, "A+": 5, "HIGH-A": 5, "A": 4, "LOW-A": 3,
    "ROK": 2, "ROOKIE": 2, "CPX": 2, "DSL": 1,
}

# Per-stat MLB-equivalent translation: (key, label, fmt, mlb_mean, {level: mult}, (lo, hi)).
_HITTER = [
    ("k_pct",  "K%",  "pct", 22.0,  {"AAA": 1.08, "AA": 1.15, "A+": 1.25, "A": 1.35}, (8.0, 45.0)),
    ("bb_pct", "BB%", "pct", 8.5,   {"AAA": 0.92, "AA": 0.88, "A+": 0.82, "A": 0.78}, (2.0, 22.0)),
    ("iso",    "ISO", "iso", 0.150, {"AAA": 0.80, "AA": 0.76, "A+": 0.68, "A": 0.60}, (0.030, 0.350)),
]
_PITCHER = [
    ("k_per_9",  "K/9",   "rate", 8.6,  {"AAA": 0.88, "AA": 0.82, "A+": 0.74, "A": 0.66}, (3.0, 16.0)),
    ("bb_per_9", "BB/9",  "rate", 3.2,  {"AAA": 1.06, "AA": 1.12, "A+": 1.20, "A": 1.30}, (1.0, 9.0)),
    ("k_bb_pct", "K-BB%", "pct",  13.5, {"AAA": 0.80, "AA": 0.72, "A+": 0.62, "A": 0.52}, (-5.0, 35.0)),
]

_REG_K = {"hitter": 200.0, "pitcher": 50.0}        # regression-to-mean strength (PA / IP)
_SAMPLE_FLOOR = {"hitter": 120.0, "pitcher": 40.0}  # below this the panel is low-confidence
_FMT_DP = {"pct": 1, "rate": 1, "iso": 3}

# best_single_level: minimum qualifying sample + the level set it ranks over.
_BEST_SINGLE_LEVEL_MIN_SAMPLE = {"hitter": 100.0, "pitcher": 20.0}
_BEST_SINGLE_LEVEL_REASON = "current_level_too_thin_best_prior_level"
_BEST_HITTER_RATE_KEYS = ("avg", "obp", "slg", "ops", "iso", "k_pct", "bb_pct")
_BEST_PITCHER_RATE_KEYS = ("era", "whip", "k_per_9", "bb_per_9", "k_bb_pct")
_BEST_LEVEL_RANK = {"AAA": 4, "AA": 3, "A+": 2, "HIGH-A": 2, "A": 1}


def _level_rank(level: str | None) -> int:
    return _LEVEL_RANK.get((level or "").upper(), 0)


def _mult_key(level: str | None) -> str:
    """Map a row level to one of the multiplier keys AAA/AA/A+/A."""
    lv = (level or "").upper()
    if lv in ("AAA", "AA", "A+", "A"):
        return lv
    if lv in ("HIGH-A",):
        return "A+"
    return "A"  # Low-A / Rookie / CPX / DSL / unknown -> most conservative tier


def translate_peripherals(rows: list, role: str | None = None) -> dict | None:
    """Translate a prospect's most-recent-season sticky peripherals to MLB-equivalents.
    `rows` = newest-first MiLB rows for ONE player (season/level/role + rate keys +
    plate_appearances|innings_pitched). Returns None when there's no credible row.
    Observe-only: the result is display context, never a value input."""
    if not rows:
        return None
    role = role or rows[0].get("role")
    if role not in ("hitter", "pitcher"):
        return None
    samp_field = "innings_pitched" if role == "pitcher" else "plate_appearances"

    latest_season = rows[0].get("season")
    season_rows = [r for r in rows if r.get("season") == latest_season]
    total_sample = sum((r.get(samp_field) or 0) for r in season_rows)
    if total_sample <= 0:
        return None
    top_level = max(season_rows, key=lambda r: _level_rank(r.get("level"))).get("level")

    # A multi-level latest season blends rates PA/IP-weighted, so the display must name
    # every level (a AAA+AA blend labeled plain "AAA" looks like it contradicts the
    # single AAA row in the stat-history table).
    levels_in_season = []
    for r in sorted(season_rows, key=lambda r: _level_rank(r.get("level")), reverse=True):
        lv = (r.get("level") or "").upper()
        if lv and (r.get(samp_field) or 0) > 0 and lv not in levels_in_season:
            levels_in_season.append(lv)
    # " & " not "+": the "A+" level contains a literal "+", so a "+" join reads as "A++A".
    level_label = " & ".join(levels_in_season) if levels_in_season else (top_level or "")

    spec = _PITCHER if role == "pitcher" else _HITTER
    out_stats = []
    for key, label, fmt, mean, mults, (lo, hi) in spec:
        weighted_equiv = 0.0
        weighted_milb = 0.0
        wt = 0.0
        for r in season_rows:
            v = r.get(key)
            s = r.get(samp_field) or 0
            if v is None or s <= 0:
                continue
            mult = mults.get(_mult_key(r.get("level")), mults["A"])
            weighted_equiv += (v * mult) * s
            weighted_milb += v * s
            wt += s
        if wt <= 0:
            continue
        translated = weighted_equiv / wt
        milb_raw = weighted_milb / wt
        shrink = wt / (wt + _REG_K[role])            # small samples regress toward the MLB mean
        mlb_equiv = mean + (translated - mean) * shrink
        mlb_equiv = max(lo, min(hi, mlb_equiv))      # clamp to a sane MLB range
        dp = _FMT_DP[fmt]
        out_stats.append({
            "key": key, "label": label, "fmt": fmt,
            "milb": round(milb_raw, dp), "mlb": round(mlb_equiv, dp),
            "mlb_avg": mean,
        })
    if not out_stats:
        return None

    low_sample = total_sample < _SAMPLE_FLOOR[role]
    lvl = _level_rank(top_level)
    if low_sample:
        confidence = "low"
    elif lvl >= 7 and total_sample >= _SAMPLE_FLOOR[role] * 1.5:
        confidence = "high"
    elif lvl >= 6:
        confidence = "moderate"
    else:
        confidence = "low"

    return {
        "role": role,
        "season": latest_season,
        "level": top_level,
        "levels": levels_in_season,
        "level_label": level_label,
        "sample": round(total_sample),
        "sample_unit": "IP" if role == "pitcher" else "PA",
        "low_sample": low_sample,
        "confidence": confidence,
        "stats": out_stats,
    }


def _line_sample(row: dict | None, role: str) -> float:
    if not isinstance(row, dict):
        return 0.0
    if role == "pitcher":
        value = row.get("ip", row.get("innings_pitched"))
    else:
        value = row.get("pa", row.get("plate_appearances"))
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _normalize_level(level) -> str:
    return str(level or "").upper().replace("HIGH-A", "A+")


def _round_line_value(value):
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, 3)


def _numeric(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _sample_value(total: float, role: str):
    if role == "hitter":
        return int(total) if float(total).is_integer() else round(total, 1)
    return round(total, 1)


def _sum_numeric(rows: list[dict], key: str, *aliases: str):
    total = 0.0
    found = False
    for row in rows:
        value = None
        for candidate in (key, *aliases):
            value = _numeric(row.get(candidate))
            if value is not None:
                break
        if value is None:
            continue
        total += value
        found = True
    if not found:
        return None
    return int(total) if float(total).is_integer() else round(total, 3)


def _ratio(numerator, denominator, *, scale: float = 1.0) -> float | None:
    numerator = _numeric(numerator)
    denominator = _numeric(denominator)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return scale * numerator / denominator


def _hitter_rate_value(row: dict, key: str) -> float | None:
    direct = _numeric(row.get(key))
    if direct is not None:
        return direct
    hits = _numeric(row.get("hits"))
    at_bats = _numeric(row.get("at_bats"))
    walks = _numeric(row.get("walks"))
    pa = _line_sample(row, "hitter")
    strikeouts = _numeric(row.get("strikeouts"))
    home_runs = _numeric(row.get("home_runs"))
    doubles = _numeric(row.get("doubles"))
    triples = _numeric(row.get("triples"))
    sac_flies = _numeric(row.get("sac_flies")) or 0.0
    hit_by_pitch = _numeric(row.get("hit_by_pitch")) or 0.0

    if key == "avg":
        return _ratio(hits, at_bats)
    if key == "obp":
        return _ratio(
            (hits or 0.0) + (walks or 0.0) + hit_by_pitch,
            (at_bats or 0.0) + (walks or 0.0) + hit_by_pitch + sac_flies,
        )
    if key in {"slg", "ops", "iso"}:
        if hits is None or at_bats is None or at_bats <= 0:
            return None
        doubles = doubles or 0.0
        triples = triples or 0.0
        home_runs = home_runs or 0.0
        total_bases = hits + doubles + (2 * triples) + (3 * home_runs)
        slg = total_bases / at_bats
        avg = _hitter_rate_value(row, "avg")
        if key == "slg":
            return slg
        if key == "iso":
            return slg - avg if avg is not None else None
        obp = _hitter_rate_value(row, "obp")
        return obp + slg if obp is not None else None
    if key == "babip":
        denominator = (at_bats or 0.0) - (strikeouts or 0.0) - (home_runs or 0.0) + sac_flies
        return _ratio((hits or 0.0) - (home_runs or 0.0), denominator)
    if key == "k_pct":
        return _ratio(strikeouts, pa, scale=100.0)
    if key == "bb_pct":
        return _ratio(walks, pa, scale=100.0)
    return None


def _pitcher_rate_value(row: dict, key: str) -> float | None:
    direct = _numeric(row.get(key))
    if direct is not None:
        return direct
    ip = _line_sample(row, "pitcher")
    strikeouts = _numeric(row.get("strikeouts"))
    walks = _numeric(row.get("walks"))
    hits = _numeric(row.get("hits"))
    earned_runs = _numeric(row.get("earned_runs"))
    batters_faced = _numeric(row.get("batters_faced"))

    if key == "k_per_9":
        return _ratio(strikeouts, ip, scale=9.0)
    if key == "bb_per_9":
        return _ratio(walks, ip, scale=9.0)
    if key == "k_bb_pct":
        return _ratio((strikeouts or 0.0) - (walks or 0.0), batters_faced, scale=100.0)
    if key == "era":
        return _ratio(earned_runs, ip, scale=9.0)
    if key == "whip":
        return _ratio((walks or 0.0) + (hits or 0.0), ip)
    return None


def _weighted_rate(rows: list[dict], role: str, key: str):
    weighted = 0.0
    weight = 0.0
    value_for = _pitcher_rate_value if role == "pitcher" else _hitter_rate_value
    for row in rows:
        sample = _line_sample(row, role)
        if sample <= 0:
            continue
        value = value_for(row, key)
        if value is None:
            continue
        weighted += value * sample
        weight += sample
    if weight <= 0:
        return None
    return _round_line_value(weighted / weight)


# The counting components a correct multi-level slash line needs. SLG/OBP/AVG are
# per-AB (or per-PA) rates, so PA-weighting the per-level rates across levels is
# wrong (a 60-AB AA line and a 300-AB A+ line don't share a denominator). Sum the
# components and rebuild the rate from the totals instead. Total bases needs every
# extra-base component: if doubles/triples are absent we cannot rebuild SLG, so
# the caller falls back rather than understate it as HR-only.
_HITTER_SLASH_COMPONENTS = ("hits", "at_bats", "doubles", "triples", "home_runs")


def _reconstructed_hitter_slash(rows: list[dict]) -> dict | None:
    """AVG/OBP/SLG/OPS/ISO rebuilt from summed counting components across levels.

    Returns None when any contributing (positive-sample) row is missing the H/AB
    or total-bases components, so the caller falls back to the legacy PA-weighted
    rate for the whole line rather than reconstructing from a partial subset.
    """
    total_h = total_ab = total_tb = 0.0
    obp_num = obp_den = 0.0
    complete_obp_components = True
    for row in rows:
        if _line_sample(row, "hitter") <= 0:
            continue
        if any(row.get(component) is None for component in _HITTER_SLASH_COMPONENTS):
            return None  # components absent for a contributing row -> fall back
        hits = _numeric(row.get("hits"))
        at_bats = _numeric(row.get("at_bats"))
        if hits is None or at_bats is None or at_bats <= 0:
            return None
        doubles = _numeric(row.get("doubles")) or 0.0
        triples = _numeric(row.get("triples")) or 0.0
        home_runs = _numeric(row.get("home_runs")) or 0.0
        walks = _numeric(row.get("walks")) or 0.0
        hbp = _numeric(row.get("hit_by_pitch"))
        if hbp is None:
            complete_obp_components = False
            hbp = 0.0
        sac_flies = _numeric(row.get("sac_flies")) or 0.0
        total_h += hits
        total_ab += at_bats
        total_tb += hits + doubles + (2 * triples) + (3 * home_runs)
        obp_num += hits + walks + hbp
        obp_den += at_bats + walks + hbp + sac_flies
    if total_ab <= 0:
        return None
    avg = total_h / total_ab
    slg = total_tb / total_ab
    slash = {
        "avg": _round_line_value(avg),
        "slg": _round_line_value(slg),
        "iso": _round_line_value(slg - avg),
    }
    if complete_obp_components and obp_den > 0:
        obp = obp_num / obp_den
        slash.update({"obp": _round_line_value(obp), "ops": _round_line_value(obp + slg)})
    return slash


def combined_season_stat_line(history_rows: list[dict], role: str, season: int) -> dict | None:
    """All-level same-season line for display-only card percentile reads.

    Counting stats are summed; rate stats are PA/IP-weighted across per-level
    rows. This is not used by prospect scoring.
    """
    if role not in ("hitter", "pitcher"):
        return None
    try:
        target_season = int(season)
    except (TypeError, ValueError):
        return None

    rows = []
    for row in history_rows or []:
        if row.get("role") != role:
            continue
        try:
            row_season = int(row.get("season"))
        except (TypeError, ValueError):
            continue
        if row_season != target_season or _line_sample(row, role) <= 0:
            continue
        rows.append(row)
    if not rows:
        return None

    total_sample = sum(_line_sample(row, role) for row in rows)
    if total_sample <= 0:
        return None
    levels = []
    for row in sorted(rows, key=lambda r: _level_rank(_normalize_level(r.get("level"))), reverse=True):
        level = _normalize_level(row.get("level"))
        if level and level not in levels:
            levels.append(level)
    level = levels[0] if levels else None
    # " & " not "+": the "A+" level contains a literal "+", so a "+" join reads as "A++A".
    level_label = " & ".join(levels) if levels else None
    sample = _sample_value(total_sample, role)

    out = {
        "role": role,
        "season": target_season,
        "level": level,
        "levels": levels,
        "level_label": level_label,
        "sample": sample,
        "sample_unit": "IP" if role == "pitcher" else "PA",
    }
    if role == "hitter":
        # k_pct/bb_pct are per-PA rates, so PA-weighting them across levels is
        # correct; babip is left on the legacy path (out of this fix's scope).
        out.update({
            key: _weighted_rate(rows, role, key)
            for key in ("babip", "k_pct", "bb_pct")
        })
        # AVG/SLG/ISO are rebuilt from counting components. OBP is rebuilt only
        # when HBP is present; absence is unknown, not zero.
        slash = _reconstructed_hitter_slash(rows)
        for key in ("avg", "slg", "iso"):
            out[key] = (
                slash[key] if slash is not None
                else _weighted_rate(rows, role, key)
            )
        out["obp"] = (
            slash["obp"]
            if slash is not None and "obp" in slash
            else _weighted_rate(rows, role, "obp")
        )
        out["ops"] = (
            _round_line_value(out["obp"] + out["slg"])
            if out["obp"] is not None and out["slg"] is not None
            else _weighted_rate(rows, role, "ops")
        )
        out.update({
            "home_runs": _sum_numeric(rows, "home_runs"),
            "stolen_bases": _sum_numeric(rows, "stolen_bases"),
            "walks": _sum_numeric(rows, "walks"),
            "hits": _sum_numeric(rows, "hits"),
            "at_bats": _sum_numeric(rows, "at_bats"),
            "plate_appearances": _sum_numeric(rows, "plate_appearances", "pa"),
            "pa": sample,
        })
        return out

    out.update({
        key: _weighted_rate(rows, role, key)
        for key in ("k_per_9", "bb_per_9", "k_bb_pct", "era", "whip")
    })
    out.update({
        "strikeouts": _sum_numeric(rows, "strikeouts"),
        "walks": _sum_numeric(rows, "walks"),
        "innings_pitched": _sum_numeric(rows, "innings_pitched", "ip"),
        "batters_faced": _sum_numeric(rows, "batters_faced"),
        "games_started": _sum_numeric(rows, "games_started"),
        "ip": sample,
    })
    return out


def _stat_line_from_history_row(row: dict, role: str) -> dict | None:
    sample = _line_sample(row, role)
    if sample <= 0:
        return None
    if role == "hitter":
        values = {key: _round_line_value(row.get(key)) for key in _BEST_HITTER_RATE_KEYS}
        if values["ops"] is None and values["obp"] is not None and values["slg"] is not None:
            values["ops"] = round(values["obp"] + values["slg"], 3)
        if any(value is None for value in values.values()):
            return None
        return {**values, "pa": int(sample)}

    values = {key: _round_line_value(row.get(key)) for key in _BEST_PITCHER_RATE_KEYS}
    if any(value is None for value in values.values()):
        return None
    return {**values, "ip": round(sample, 1)}


def best_single_level_stat_line(
    *,
    current_line: dict | None,
    current_level,
    history_rows: list[dict],
    role: str,
    season: int,
) -> dict | None:
    """Best same-season, single-level line when the current-level line is thin.

    Intentionally NOT a combined line: it exists only so the card can say "current
    level is thin, but the best 2026 read is AA over 250 PA". Reads per-level rows
    (use the un-slimmed milb_season_stats source, which retains every level)."""
    if role not in ("hitter", "pitcher"):
        return None
    threshold = _BEST_SINGLE_LEVEL_MIN_SAMPLE[role]
    if not isinstance(current_line, dict) or not current_line:
        return None
    if _line_sample(current_line, role) >= threshold:
        return None

    current_level_norm = _normalize_level(current_level)
    if current_level_norm not in _BEST_LEVEL_RANK:
        return None

    candidates = []
    for row in history_rows or []:
        if row.get("role") != role:
            continue
        try:
            row_season = int(row.get("season"))
        except (TypeError, ValueError):
            continue
        if row_season != season:
            continue
        level = _normalize_level(row.get("level"))
        if level == current_level_norm or level not in _BEST_LEVEL_RANK:
            continue
        sample = _line_sample(row, role)
        if sample < threshold:
            continue
        candidates.append((sample, _BEST_LEVEL_RANK[level], row, level))

    if not candidates:
        return None

    sample, _rank, row, level = max(candidates, key=lambda item: (item[0], item[1]))
    line = _stat_line_from_history_row(row, role)
    if not line:
        return None
    sample_value = int(sample) if role == "hitter" else round(sample, 1)
    out = {
        "level": level,
        "sample": sample_value,
        "sample_unit": "PA" if role == "hitter" else "IP",
        "reason": _BEST_SINGLE_LEVEL_REASON,
    }
    sample_key = "pa" if role == "hitter" else "ip"
    out.update({key: value for key, value in line.items() if key != sample_key})
    return out
