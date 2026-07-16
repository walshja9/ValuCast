"""Fitted level-translation challenger — model-supremacy lane #2 (dark parallel path).

Research-only. Nothing here changes ANY served score until the flags in
prospects/model.py (LEVEL_TRANSLATION_FITTED_ENABLED, PITCHER_STRIKE_PCT_ENABLED,
both default False) are flipped by a research replay's `model_flags` variant —
the exact mechanism prospects/pitcher_challenger.py (E1) uses. Two levers:

  (a) FITTED LEVEL TRANSLATION. The incumbent feature spaces feed RAW per-level
      MiLB rates plus a hand-set linear level code (model.LEVEL_CODE /
      universal.LEVEL_CODE), so a 0.850 OPS at A-ball and a 0.850 OPS at AAA
      enter the same rate column and the ridge must untangle level entirely
      through the linear code and the *_x_level interactions. (The hand-set
      multipliers in prospects/milb_translation.py are display-only and never
      feed a feature.) This lever replaces the raw rates with FOLD-FITTED
      MLB-equivalent rates: per-stat-by-level additive equivalency deltas
      estimated ONLY from the fold's training window, anchored on players who
      later reached the SAME MLB volume threshold the existing backtest targets
      already define (universal.ROLE_THRESHOLDS "established": 300 PA / 50 IP,
      representative season = highest-volume post-cohort season inside the
      4-year horizon — no new label is invented). Thin level cells shrink
      toward a per-stat global linear-in-level curve with an
      empirical-Bayes-style weight (EB_K below). Fully deterministic given the
      training rows. Only stats whose MLB value the existing representative-
      target derivations already define are translated:
      hitters {avg, ops, k_pct}; pitchers {era, whip, k_per_9}.

  (b) PITCHER STRIKE%. strike_pct = strikes / pitches on pitcher season rows
      (raw dataset fields added 2026-07-15, additive-only). None-safe encoding:
      value feature = known * (strike_pct - STRIKE_PCT_REF), plus a known flag.
      When counts are absent both features are exactly 0.0 and the known flag
      carries the missingness — with the indicator present the REF choice is
      mathematically absorbed by the intercept + indicator coefficient, so the
      centering constant cannot fabricate command. Pitcher-only.

The fitted table travels through a module-level context (`active_translation`)
installed only by research replays; with the model.py flag off OR no table
active, `maybe_translate` is an identity function, so the served path is
byte-identical by construction. Stdlib-only: this module is imported by
prospects/model.py, which is reachable from CI-wired nightly code.
"""
from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager

# ---- Lever (a): fitted per-stat-by-level equivalency table --------------------
# Level vocabulary shared by both feature spaces (model.LEVEL_CODE and
# universal.LEVEL_CODE key the same four levels).
LEVEL_RANK = {"A": 1.0, "A+": 2.0, "AA": 3.0, "AAA": 4.0}

# Stats with an MLB-side anchor already defined by the existing backtest target
# machinery (universal TARGET_SPECS representative fields/derivations):
# hitter avg/ops are direct season fields, k_pct = so/pa*100 (the
# representative_k_pct derivation); pitcher era/whip direct, k_per_9 = so/ip*9
# (the representative_k_per_9 derivation). iso/bb_pct/k_bb_pct/bb_per_9 have no
# MLB-side value in historical_mlb_seasons, so they are NOT translated.
TRANSLATED_STATS = {
    "hitter": ("avg", "ops", "k_pct"),
    "pitcher": ("era", "whip", "k_per_9"),
}

# Anchor definition mirrors the existing labels, deliberately not re-tuned:
# universal.ROLE_THRESHOLDS["established"] volume on the representative
# (highest-volume) post-cohort season inside the fixed 4-year horizon.
ANCHOR_MIN_SAMPLE = {"hitter": 300.0, "pitcher": 50.0}
HORIZON_YEARS = 4
MAX_AGE = 25  # mirrors model.MAX_AGE eligibility

# Empirical-Bayes-style shrink weight: a level cell with n anchors gets weight
# n / (n + EB_K) on its own mean, remainder on the global per-stat
# linear-in-level curve. Fixed and documented, NOT tuned on evaluation folds.
EB_K = 25.0

_SENTINEL = "_level_translation_applied"
_ACTIVE_TABLE: dict | None = None


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mlb_stat(season: dict, role: str, stat: str) -> float | None:
    """MLB-side value for one translated stat, mirroring the existing
    representative-target field/derivation definitions in prospects.universal."""
    if role == "hitter":
        if stat in ("avg", "ops"):
            return _num(season.get(stat))
        if stat == "k_pct":
            so = _num(season.get("so"))
            pa = _num(season.get("pa")) or 0.0
            return so / pa * 100.0 if so is not None and pa else None
    else:
        if stat in ("era", "whip"):
            return _num(season.get(stat))
        if stat == "k_per_9":
            so = _num(season.get("so"))
            ip = _num(season.get("ip")) or 0.0
            return so / ip * 9.0 if so is not None and ip else None
    return None


def _anchor_rows(historical_rows: list[dict], role: str, train_through: int) -> list[dict]:
    """One row per player from the training window, mirroring
    universal._base_historical_rows selection (earliest cohort, highest level,
    A..AAA, age <= MAX_AGE). Rows with cohort_year > train_through NEVER enter —
    the fold-hygiene contract of this module."""
    eligible = []
    for record in historical_rows:
        if record.get("role") != role:
            continue
        try:
            cohort = int(record.get("cohort_year"))
        except (TypeError, ValueError):
            continue
        if cohort > int(train_through):
            continue
        mlbam_id = record.get("mlbam_id")
        if not mlbam_id:
            continue
        age = _num(record.get("age"))
        if age is None or age > MAX_AGE:
            continue
        level = str(record.get("level") or "").upper()
        if level not in LEVEL_RANK:
            continue
        eligible.append((cohort, -LEVEL_RANK[level], int(mlbam_id), record))
    eligible.sort(key=lambda item: item[:3])
    by_player: dict[int, tuple[int, dict]] = {}
    for cohort, _neg_rank, mlbam_id, record in eligible:
        by_player.setdefault(mlbam_id, (cohort, record))
    return [
        {"mlbam_id": mlbam_id, "cohort_year": cohort, "record": record}
        for mlbam_id, (cohort, record) in sorted(by_player.items())
    ]


def _representative_season(
    seasons: list[dict], role: str, cohort_year: int
) -> dict | None:
    """Highest-volume post-cohort season inside the fixed horizon, at or above
    the established threshold — the anchor the existing conditional targets use."""
    sample_key = "pa" if role == "hitter" else "ip"
    best = None
    best_key = None
    for season in seasons or []:
        year = int(season.get("year") or 0)
        if year <= cohort_year or year > cohort_year + HORIZON_YEARS:
            continue
        sample = _num(season.get(sample_key)) or 0.0
        key = (sample, -year)
        if best_key is None or key > best_key:
            best, best_key = season, key
    if best is None:
        return None
    if (_num(best.get(sample_key)) or 0.0) < ANCHOR_MIN_SAMPLE[role]:
        return None
    return best


def _fit_stat(pairs: list[tuple[str, float]]) -> dict:
    """Fit one stat's per-level equivalency deltas from (level, mlb - milb) pairs.

    Global curve: OLS of delta on LEVEL_RANK (flat pooled mean when degenerate).
    Per-level: EB shrink of the level-cell mean toward the curve at that level.
    Levels with zero anchors take the curve value outright."""
    deltas = [delta for _level, delta in pairs]
    n_total = len(deltas)
    pooled = sum(deltas) / n_total if n_total else 0.0
    ranks = [LEVEL_RANK[level] for level, _delta in pairs]
    slope, intercept = 0.0, pooled
    if n_total >= 2:
        mean_rank = sum(ranks) / n_total
        var_rank = sum((rank - mean_rank) ** 2 for rank in ranks)
        if var_rank > 0:
            cov = sum(
                (rank - mean_rank) * (delta - pooled)
                for rank, delta in zip(ranks, deltas)
            )
            slope = cov / var_rank
            intercept = pooled - slope * mean_rank
    cells: dict[str, list[float]] = {}
    for level, delta in pairs:
        cells.setdefault(level, []).append(delta)
    levels = {}
    for level in LEVEL_RANK:
        curve_value = intercept + slope * LEVEL_RANK[level]
        cell = cells.get(level) or []
        n_cell = len(cell)
        cell_mean = sum(cell) / n_cell if n_cell else None
        if n_cell:
            weight = n_cell / (n_cell + EB_K)
            delta_hat = weight * cell_mean + (1.0 - weight) * curve_value
        else:
            delta_hat = curve_value
        levels[level] = {
            "n": n_cell,
            "cell_mean": round(cell_mean, 6) if cell_mean is not None else None,
            "curve": round(curve_value, 6),
            "delta_hat": round(delta_hat, 6),
        }
    return {
        "anchor_count": n_total,
        "curve": {"intercept": round(intercept, 6), "slope": round(slope, 6)},
        "levels": levels,
    }


def fit_translation_table(
    historical_rows: list[dict],
    seasons_by_player: dict,
    train_through: int,
) -> dict:
    """Fit the full per-role, per-stat, per-level equivalency table from ONE
    fold's training window. Deterministic given the inputs. The caller must pass
    train_through = test_year - HORIZON_YEARS (the same training cut the
    existing walk-forward uses); rows past it never contribute."""
    roles: dict[str, dict] = {}
    for role, stats in TRANSLATED_STATS.items():
        pairs: dict[str, list[tuple[str, float]]] = {stat: [] for stat in stats}
        for anchor in _anchor_rows(historical_rows, role, train_through):
            record = anchor["record"]
            seasons = seasons_by_player.get(f"{anchor['mlbam_id']}_{role}") or []
            season = _representative_season(seasons, role, anchor["cohort_year"])
            if season is None:
                continue
            level = str(record.get("level") or "").upper()
            for stat in stats:
                milb = _num(record.get(stat))
                mlb = _mlb_stat(season, role, stat)
                if milb is None or mlb is None:
                    continue
                pairs[stat].append((level, mlb - milb))
        roles[role] = {stat: _fit_stat(pairs[stat]) for stat in stats}
    table = {"train_through": int(train_through), "eb_k": EB_K, "roles": roles}
    table["fingerprint"] = hashlib.sha256(
        json.dumps(roles, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return table


@contextmanager
def active_translation(table: dict | None):
    """Install a fitted table for one fold (training AND scoring), restored after.

    Research replays only. With no table active, maybe_translate is an identity
    function regardless of the model.py flag, so serving can never translate."""
    global _ACTIVE_TABLE
    saved = _ACTIVE_TABLE
    _ACTIVE_TABLE = table
    try:
        yield
    finally:
        _ACTIVE_TABLE = saved


def active_table() -> dict | None:
    return _ACTIVE_TABLE


def maybe_translate(record: dict, role: str) -> dict:
    """Return the record with translated rate stats, or the record unchanged.

    Identity when: no active table, unknown role/level, already-translated
    record (idempotence sentinel — feature builders call this at more than one
    entry point), or no translatable non-None stat. Never mutates the input."""
    table = _ACTIVE_TABLE
    if table is None or record.get(_SENTINEL):
        return record
    stats = table.get("roles", {}).get(role)
    if not stats:
        return record
    level = str(record.get("level") or "").upper()
    if level not in LEVEL_RANK:
        return record
    out = None
    for stat, fit in stats.items():
        value = _num(record.get(stat))
        if value is None:
            continue
        level_fit = fit["levels"].get(level)
        if level_fit is None:
            continue
        if out is None:
            out = dict(record)
            out[_SENTINEL] = True
        out[stat] = value + level_fit["delta_hat"]
    return out if out is not None else record


# ---- Lever (b): pitcher strike% (None-safe) ------------------------------------
# Appended AFTER every incumbent (and E1 role-split, when on) pitcher feature so
# turning the flag off leaves every incumbent index untouched.
STRIKE_PCT_FEATURE_NAMES = ("strike_pct_dev", "strike_pct_known")
# strike_pct_dev is a performance rate: it must shrink with sample reliability.
# strike_pct_known is a structural missingness flag: it must NOT shrink.
STRIKE_PCT_SHRINK = frozenset({"strike_pct_dev"})
STRIKE_PCT_NON_SHRINK = frozenset({"strike_pct_known"})
# Centering reference (league strike% mean, verified against live StatsAPI on
# the 2026-07-15 data add). With the known indicator present, any REF choice is
# absorbed by intercept + indicator coefficient — documented, not tuned.
STRIKE_PCT_REF = 0.658


def strike_pct_extra(record: dict) -> list[float]:
    """(strike_pct_dev, strike_pct_known) for a pitcher season row.

    None-safe: absent/zero pitches, absent strikes, or strikes > pitches (a
    corrupt count) all yield (0.0, 0.0) — the feature is ABSENT, never imputed
    to a fabricated command value."""
    pitches = _num(record.get("pitches"))
    strikes = _num(record.get("strikes"))
    if pitches is None or strikes is None or pitches <= 0 or strikes > pitches:
        return [0.0, 0.0]
    return [strikes / pitches - STRIKE_PCT_REF, 1.0]
