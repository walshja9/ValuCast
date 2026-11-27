# ValuCast-owned MiLB translation + best-single-level — design

Date: 2026-06-17
Status: spec (ValuCast Independence Foundation, P0 — build in ValuCast repo)

## Goal

Cut the last DD read in the **factual** prospect path. Today `stat_line_translated`
(MLB-equivalent peripherals) and `mlb_stat_line` are computed by DD's `milb_translation.py`
and baked into the snapshot via the DD feed (`prospects/rank_v1.py:1094-1095`,
`prospects/universe.py:214-215` read `dd_row`). Move that computation into a ValuCast-owned
module fed by ValuCast's already-owned raw MiLB data. Also emit `best_single_level_stat_line`
(per the 2026-06-17 best-single-level spec) ValuCast-side.

## Approach: PORT VERBATIM first

DD's `milb_translation.py` (in the DD repo) is a 144-line pure function with **hardcoded,
research-grounded constants — no external tables, park factors, or league factors.** Port it
verbatim into ValuCast so the owned output **matches DD's current card values** (an ownership
move with zero visual change, independently verifiable). Improving the translation math is a
SEPARATE later quality pass — not this build.

## New module: `prospects/milb_translation.py` (ValuCast-owned)

Port `translate_peripherals(rows, role)` and `_best_single_level_stat_line(...)` from DD. Pure
functions, no I/O. Constants to port verbatim:

```
# (key, label, fmt, mlb_mean, {level: retention_mult}, (lo_clamp, hi_clamp))
_HITTER  = [
  ("k_pct",  "K%",  "pct", 22.0,  {"AAA":1.08,"AA":1.15,"A+":1.25,"A":1.35}, (8.0, 45.0)),
  ("bb_pct", "BB%", "pct", 8.5,   {"AAA":0.92,"AA":0.88,"A+":0.82,"A":0.78}, (2.0, 22.0)),
  ("iso",    "ISO", "iso", 0.150, {"AAA":0.80,"AA":0.76,"A+":0.68,"A":0.60}, (0.030, 0.350)),
]
_PITCHER = [
  ("k_per_9",  "K/9",   "rate", 8.6,  {"AAA":0.88,"AA":0.82,"A+":0.74,"A":0.66}, (3.0, 16.0)),
  ("bb_per_9", "BB/9",  "rate", 3.2,  {"AAA":1.06,"AA":1.12,"A+":1.20,"A":1.30}, (1.0, 9.0)),
  ("k_bb_pct", "K-BB%", "pct",  13.5, {"AAA":0.80,"AA":0.72,"A+":0.62,"A":0.52}, (-5.0, 35.0)),
]
_REG_K        = {"hitter": 200.0, "pitcher": 50.0}   # regression-to-mean strength
_SAMPLE_FLOOR = {"hitter": 120.0, "pitcher": 40.0}   # below = low confidence
_FMT_DP       = {"pct": 1, "rate": 1, "iso": 3}
_LEVEL_RANK   = {"AAA":7,"AA":6,"A+":5,"HIGH-A":5,"A":4,"LOW-A":3,"ROK":2,"ROOKIE":2,"CPX":2,"DSL":1}
# _mult_key: AAA/AA/A+/A -> self; HIGH-A -> A+; everything else -> "A" (conservative)
```

Translation algorithm (per stat, over latest-season rows, may span levels):
1. per-level translate then PA/IP-weight-blend: `weighted_equiv += (v*mult)*s`, `wt += s`, `translated = weighted_equiv/wt` (also track `milb_raw = weighted_milb/wt`).
2. shrink to MLB mean by sample: `shrink = wt/(wt+_REG_K[role])`; `mlb_equiv = mean + (translated-mean)*shrink`.
3. clamp to `(lo, hi)`; round to `_FMT_DP[fmt]`.
- Only sticky rates translate (hitters k_pct/bb_pct/iso; pitchers k_per_9/bb_per_9/k_bb_pct).
  AVG/OBP/SLG/OPS/ERA/WHIP/counting stats are deliberately NOT translated.
- Output shape (must match DD's `stat_line_translated` exactly): `{role, season, level, levels,
  level_label, sample, sample_unit, low_sample, confidence, stats:[{key,label,fmt,milb,mlb,mlb_avg}]}`.
- Confidence: `low` if total_sample < floor; `high` if top level AAA(rank>=7) AND sample>=floor*1.5;
  `moderate` if top level >= AA(6); else `low`.
- Guards (port): return None on no rows / bad role / total_sample<=0 / no stat produced.

`best_single_level_stat_line` (port `_best_single_level_stat_line`): threshold hitter>=100 PA /
pitcher>=20 IP (== existing `prospect_percentiles.MIN_PA/MIN_IP`); emit only when current level
is thin AND another single level clears; pick largest qualifying OTHER level by `(sample,
level_rank)`; shape `{level, sample, sample_unit, reason:"current_level_too_thin_best_prior_level",
+ rate keys}` with rate keys hitters `avg/obp/slg/ops/iso/k_pct/bb_pct`, pitchers
`era/whip/k_per_9/bb_per_9/k_bb_pct`.

## Inputs (ValuCast already owns — confirmed)

- Translation: `data/prospects/raw/milb_card_history.json` (multi-season, newest-first rows,
  `season/level/age/mlbam_id/role` + rate fields — the exact shape `translate_peripherals` wants).
- best_single_level: `data/prospects/raw/milb_season_stats.json` — the **un-slimmed** per-level
  current-season file (retains every level; 400 hitters / 538 pitchers have >1 level). Use THIS,
  NOT card-history (card-history is slimmed to one row per (mlbam_id, role) and loses the multi-level
  signal). Built by `scripts/refresh_milb_season_stats.py` (StatsAPI sport ids 11/12/13/14).

## Wiring (repoint off DD)

- Compute translation + best_single_level in the ValuCast input pipeline (`prospects/raw_input_builder.py`,
  which already loads both raw files: `CURRENT_STATS_PATH`, `MILB_CARD_HISTORY_PATH` at `:25-26`),
  keyed by `(mlbam_id, role)`. Carry both into the contract and through to the snapshot.
- Repoint `prospects/rank_v1.py:1094-1095` and `prospects/universe.py:214-215`: `stat_line_translated`
  (and `mlb_stat_line` where applicable) come from the ValuCast translation, NOT `dd_row`. Keep the
  DD value as a dormant fallback only if trivially safe; otherwise drop the DD read for these two fields.
- `web/dynasty_models.py`: add `best_single_level_stat_line: dict | None = None` (`:70-74`) + coercion
  in `from_feed` (`~:298-301`). (`stat_line_translated` field already exists.)
- `mlb_stat_line`: currently empty for prospects; out of scope to fully own here (it's a call-up MLB
  line, separate source). Leave its current behavior; do NOT introduce a new DD read for it.

## Validators (ValuCast-owned, fail-loud)

- MLBAM-keyed only; never name-keyed (reuse the existing `(mlbam_id, role)` selection / twin guard).
- Fail loud at snapshot build if a prospect that HAS qualifying MiLB rate rows produces no translation
  (regression detector — "stat lines vanished"). A genuinely sample-less prospect yielding None is fine.
- Same-day freshness on `milb_season_stats.json` (extend `prospects/milb_stat_freshness.py` or the
  freshness validator) — the owned artifact, not the DD feed.
- No DD path / DD feed read in the new module or its wiring.

## Verification (ownership = no card change)

- Unit tests on the ported math: a known hitter row set and pitcher row set → assert exact
  translated `mlb` values + confidence + level_label against hand-computed expectations from the
  constants. best_single_level: A.J. Ewing (mlbam 805999, AAA 51 PA + AA 81 PA) → returns the AA
  line (81 PA clears, AAA thin). Thresholds, reason string, rate-key set.
- Parity check: for prospects that currently carry a DD `stat_line_translated`, the ValuCast-computed
  values match DD's within rounding (the port is verbatim). Log/assert any divergence.
- `python -m pytest -q` green; `python -m ruff check` clean on touched files.

## Non-goals (separate slices)

- NOT improving the translation math (later quality pass).
- NOT cutting the deploy gates (`/health/ready` dd, `VALUCAST_REQUIRE_DD`, freshness re-key) — separate
  slice once the snapshot build no longer reads the DD feed for factual fields.
- NOT the best_single_level CONSUMER display (use the 2026-06-17 best-single-level spec; consumer is
  unblocked once ValuCast emits the field).
- NOT the display-only DD context decision (source_ranks / dd ranks / value_history) — product call.
