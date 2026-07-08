"""Measured MLB shape comps for hitter prospects, with historical outcomes.

For every eligible hitter prospect the model publishes a translated
MLB-equivalent line (K%, BB%, ISO). This module matches that shape against
real MLB hitting seasons (2000-2025, committed statsapi cache) and reports:

- "shape twins": the nearest young-MLB seasons by era-relative distance, and
- an OUTCOME cohort: what the nearest RESOLVED matches (seasons old enough to
  observe five full follow-up years) actually did afterwards.

Honesty rules baked in, not bolted on:
- Era-relative matching: rates are z-scored within each season's population of
  400+ PA regulars, so a 21.8 K% in 2005 and 2024 mean what they meant then.
  The prospect's translated line is z-scored against the latest cached season
  (the translation targets today's run environment).
- The outcome cohort only counts matches with a complete 5-season follow-up
  window, and it dedupes by player so one career can't vote twice.
- This is a DESCRIPTIVE lens (what similar shapes did), never a probability;
  the model's role/star probabilities remain the only forecast on the card.
- Display-only: nothing here feeds any ValuCast score or rank.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORY_PATH = ROOT / "data" / "mlb" / "mlb_history_hitting_seasons.json"
SNAPSHOT_PATH = ROOT / "data" / "public" / "public_dynasty_snapshot.json"
ARTIFACT_PATH = ROOT / "data" / "models" / "valucast_prospect_comps.json"

ARTIFACT_NAME = "valucast_prospect_comps"
SHAPE_KEYS = ("k_pct", "bb_pct", "iso")
MATCH_MIN_PA = 400
MATCH_MAX_AGE = 26
OUTCOME_HORIZON = 5  # seasons after the match season
COHORT_SIZE = 25
TWIN_COUNT = 3
MAX_PROSPECT_RANK = 500
# 2020 played 60 of 162 games; outcome windows crossing it must pro-rate PA
# or real everyday players get mis-tiered as part-time. Rates are unaffected.
SHORT_SEASON_PA_SCALE = {2020: 162 / 60}

# Outcome tiers over the 5 seasons AFTER the match season. PA/yr measures the
# playing time the league kept giving the player; era-relative OPS measures
# what he did with it (PA-weighted, vs the league mean of each season).
# Labels describe the MEASUREMENT (playing time + bat), never a role verdict:
# "platoon"-style language would blame the player for PA lost to injuries or a
# catcher's workload (7/8 review: Wilson Ramos '11 — everyday All-Star catcher,
# ACL year in his window — must not be published as a platoon guy).
TIER_ORDER = ("impact_regular", "everyday", "part_time", "faded")
TIER_LABELS = {
    "impact_regular": "regular with an above-average bat",
    "everyday": "everyday regular",
    "part_time": "limited playing time",
    "faded": "faded out",
}
TIER_THRESHOLDS = {
    "impact_regular": ">=450 PA/yr and >=1.10x league OPS",
    "everyday": ">=400 PA/yr",
    "part_time": ">=150 PA/yr",
    "faded": "<150 PA/yr",
}


def _tier(pa_per_year: float, rel_ops: float | None) -> str:
    if pa_per_year >= 450 and rel_ops is not None and rel_ops >= 1.10:
        return "impact_regular"
    if pa_per_year >= 400:
        return "everyday"
    if pa_per_year >= 150:
        return "part_time"
    return "faded"


def _rates(row: dict) -> dict | None:
    pa = row.get("pa") or 0
    if pa <= 0:
        return None
    try:
        return {
            "k_pct": 100.0 * row["so"] / pa,
            "bb_pct": 100.0 * row["bb"] / pa,
            "iso": float(row["slg"]) - float(row["avg"]),
        }
    except (KeyError, TypeError, ValueError):
        return None


class CompPool:
    """Historical season pool with per-season era normalization."""

    def __init__(self, history_rows: list[dict]):
        self.rows = [r for r in history_rows if r.get("season") and r.get("id")]
        self.latest_season = max(r["season"] for r in self.rows) if self.rows else None
        self._by_player: dict[int, dict[int, dict]] = {}
        for row in self.rows:
            self._by_player.setdefault(row["id"], {})[row["season"]] = row
        self._season_z = self._era_stats()
        self._league_ops = self._league_ops_by_season()
        self.match_rows = self._match_rows()

    def _era_stats(self) -> dict[int, dict[str, tuple[float, float]]]:
        by_season: dict[int, list[dict]] = {}
        for row in self.rows:
            if (row.get("pa") or 0) >= MATCH_MIN_PA:
                rates = _rates(row)
                if rates:
                    by_season.setdefault(row["season"], []).append(rates)
        stats: dict[int, dict[str, tuple[float, float]]] = {}
        for season, rate_rows in by_season.items():
            season_stats = {}
            for key in SHAPE_KEYS:
                vals = [r[key] for r in rate_rows]
                mean = sum(vals) / len(vals)
                var = sum((v - mean) ** 2 for v in vals) / len(vals)
                std = var ** 0.5
                if std <= 0:
                    continue
                season_stats[key] = (mean, std)
            if len(season_stats) == len(SHAPE_KEYS):
                stats[season] = season_stats
        return stats

    def _league_ops_by_season(self) -> dict[int, float]:
        totals: dict[int, list[float]] = {}
        for row in self.rows:
            pa = row.get("pa") or 0
            try:
                ops = float(row["obp"]) + float(row["slg"])
            except (KeyError, TypeError, ValueError):
                continue
            if pa > 0:
                acc = totals.setdefault(row["season"], [0.0, 0.0])
                acc[0] += pa * ops
                acc[1] += pa
        return {s: w / p for s, (w, p) in totals.items() if p > 0}

    def _match_rows(self) -> list[dict]:
        out = []
        for row in self.rows:
            if (row.get("pa") or 0) < MATCH_MIN_PA:
                continue
            age = row.get("age")
            if age is None or age > MATCH_MAX_AGE:
                continue
            z_stats = self._season_z.get(row["season"])
            rates = _rates(row)
            if not z_stats or not rates:
                continue
            out.append({
                **row,
                "rates": rates,
                "z": tuple(
                    (rates[k] - z_stats[k][0]) / z_stats[k][1] for k in SHAPE_KEYS
                ),
            })
        return out

    @property
    def resolved_through(self) -> int | None:
        if self.latest_season is None:
            return None
        return self.latest_season - OUTCOME_HORIZON

    def target_z(self, translated: dict) -> tuple | None:
        """Z-score a prospect's translated rates against the latest era."""
        z_stats = self._season_z.get(self.latest_season)
        if not z_stats:
            return None
        try:
            return tuple(
                (float(translated[k]) - z_stats[k][0]) / z_stats[k][1]
                for k in SHAPE_KEYS
            )
        except (KeyError, TypeError, ValueError):
            return None

    def outcome(self, player_id: int, season: int) -> dict | None:
        """Next-5-season outcome; None when the window isn't complete yet."""
        if self.resolved_through is None or season > self.resolved_through:
            return None
        seasons = self._by_player.get(player_id, {})
        pa_total = 0.0
        weighted_rel_ops = 0.0
        for offset in range(1, OUTCOME_HORIZON + 1):
            follow_season = season + offset
            row = seasons.get(follow_season)
            if not row:
                continue
            pa = row.get("pa") or 0
            league_ops = self._league_ops.get(follow_season)
            try:
                ops = float(row["obp"]) + float(row["slg"])
            except (KeyError, TypeError, ValueError):
                continue
            if pa > 0 and league_ops:
                pa_scaled = pa * SHORT_SEASON_PA_SCALE.get(follow_season, 1.0)
                pa_total += pa_scaled
                weighted_rel_ops += pa_scaled * (ops / league_ops)
        pa_per_year = pa_total / OUTCOME_HORIZON
        rel_ops = round(weighted_rel_ops / pa_total, 3) if pa_total else None
        return {
            "pa_per_year": round(pa_per_year, 1),
            "rel_ops": rel_ops,
            "tier": _tier(pa_per_year, rel_ops),
        }


def _distance(a: tuple, b: tuple) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def comp_for_target(pool: CompPool, translated: dict) -> dict | None:
    target = pool.target_z(translated)
    if target is None or not pool.match_rows:
        return None
    ranked = sorted(pool.match_rows, key=lambda r: _distance(target, r["z"]))

    twins, seen_players = [], set()
    for row in ranked:
        if row["id"] in seen_players:
            continue
        seen_players.add(row["id"])
        outcome = pool.outcome(row["id"], row["season"])
        twins.append({
            "name": row.get("name"),
            "season": row["season"],
            "age": row.get("age"),
            "pos": row.get("pos"),
            "bats": row.get("bats"),
            "pa": row.get("pa"),
            "hr": row.get("hr"),
            "avg": row.get("avg"),
            "k_pct": round(row["rates"]["k_pct"], 1),
            "bb_pct": round(row["rates"]["bb_pct"], 1),
            "iso": round(row["rates"]["iso"], 3),
            "distance": round(_distance(target, row["z"]), 3),
            "outcome": outcome,
        })
        if len(twins) >= TWIN_COUNT:
            break

    cohort_rows, cohort_players = [], set()
    for row in ranked:
        if row["season"] > (pool.resolved_through or -1):
            continue
        if row["id"] in cohort_players:
            continue
        cohort_players.add(row["id"])
        outcome = pool.outcome(row["id"], row["season"])
        if outcome is None:
            continue
        cohort_rows.append(outcome)
        if len(cohort_rows) >= COHORT_SIZE:
            break

    tiers = {tier: 0 for tier in TIER_ORDER}
    for outcome in cohort_rows:
        tiers[outcome["tier"]] += 1
    pa_values = sorted(o["pa_per_year"] for o in cohort_rows)
    median_pa = pa_values[len(pa_values) // 2] if pa_values else None

    return {
        "target": {
            "k_pct": round(float(translated["k_pct"]), 1),
            "bb_pct": round(float(translated["bb_pct"]), 1),
            "iso": round(float(translated["iso"]), 3),
        },
        "twins": twins,
        "cohort": {
            "size": len(cohort_rows),
            "resolved_through": pool.resolved_through,
            "tiers": tiers,
            "median_pa_per_year": median_pa,
        },
    }


def _translated_rates(row: dict) -> dict | None:
    translated = row.get("stat_line_translated") or {}
    if translated.get("role") != "hitter":
        return None
    if translated.get("low_sample") or translated.get("confidence") != "high":
        return None
    rates = {}
    for stat in translated.get("stats") or []:
        key = stat.get("key")
        if key in SHAPE_KEYS and stat.get("mlb") is not None:
            rates[key] = stat["mlb"]
    return rates if len(rates) == len(SHAPE_KEYS) else None


def eligible_prospects(snapshot: dict) -> list[dict]:
    out = []
    for row in snapshot.get("players") or []:
        if row.get("player_type") != "prospect":
            continue
        rank = row.get("prospect_rank")
        if not rank or rank > MAX_PROSPECT_RANK:
            continue
        rates = _translated_rates(row)
        if not rates or not row.get("mlbam_id"):
            continue
        out.append({
            "mlbam_id": str(row["mlbam_id"]),
            "name": row.get("name"),
            "prospect_rank": rank,
            "translated": rates,
        })
    return out


def build_prospect_comps(
    history: dict,
    snapshot: dict,
    generated_at: str | None = None,
) -> dict:
    pool = CompPool(history.get("rows") or [])
    players = {}
    for prospect in eligible_prospects(snapshot):
        comp = comp_for_target(pool, prospect["translated"])
        if comp is None:
            continue
        players[prospect["mlbam_id"]] = {
            "name": prospect["name"],
            "prospect_rank": prospect["prospect_rank"],
            **comp,
        }
    seasons = history.get("seasons") or [None, None]
    return {
        "artifact": ARTIFACT_NAME,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(),
        "source_policy": {
            "display_only": True,
            "feeds_live_valucast_rank": False,
            "feeds_model_score": False,
        },
        "method": {
            "axes": list(SHAPE_KEYS),
            "pool": (
                f"MLB hitting seasons {seasons[0]}-{seasons[1]}, PA>={MATCH_MIN_PA}, "
                f"age<={MATCH_MAX_AGE}, pitchers excluded"
            ),
            "era_normalization": (
                "rates z-scored within each season's 400+ PA population; the "
                "prospect's translated line is z-scored against the latest season"
            ),
            "outcome": (
                f"PA/yr and PA-weighted era-relative OPS over the {OUTCOME_HORIZON} "
                "seasons after the match season; cohort counts only matches with a "
                "complete follow-up window, deduped by player"
            ),
            "cohort_size": COHORT_SIZE,
            "match_pool_rows": len(pool.match_rows),
            "resolved_through": pool.resolved_through,
            "tier_thresholds": dict(TIER_THRESHOLDS),
        },
        "tier_labels": dict(TIER_LABELS),
        "players": players,
    }
