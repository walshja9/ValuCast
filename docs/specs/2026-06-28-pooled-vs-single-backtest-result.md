# Pooled-multi-level vs single-level prospect backtest — result

**Status: built and RUN (the 6/27 no-go is now a TESTED result, not a blocked one).
Pooling helps on the only fold that can test it, but it is one discriminating fold,
not two — do NOT flip pooling to live yet. Re-run when the 2022 cohort matures
(~Q4 2026); the data + harness are already built.**

Companion to `2026-06-27-w21-mle-backtest-gate.md`. Observe-only; nothing served.

## What changed since 6/27
The 6/27 memo said the pooled INPUT was non-constructible because by-level history was
absent for the mature folds. That was true of the *committed* data. **MLB StatsAPI
returns historical MiLB season totals by level back to 2014** (verified: Franco 2019
A+/A, Witt 2021 AAA/AA, Grayson Rodriguez 2019 across three levels; full stat fields).
So we backfilled it:
- `scripts/build_historical_by_level_lines.py` — one-time out-of-band pull (~80 requests
  to `/stats?stats=season`, joined to the universe cohorts by mlbam_id). Network; NOT in
  the network-free daily build.
- `data/prospects/raw/historical_by_level_lines.json` — **6756/6756 universe pairs
  matched, 2528 (37.4%) multi-level.** Rates recomputed from summed counts.

## The backtest
`scripts/run_pooled_vs_single_backtest.py` reuses the committed `dynasty_backtest`
folding + gate. Same trained models per fold; only the TEST-TIME feature vector differs
— **pooled candidate vs single-level baseline**, both scored against the realized
`_raw_target` labels (non-circular). Run on the multi-level discriminating subset so the
63% single-level rows don't dilute the signal; aggregate sample clears `MIN_GATE_SAMPLE`.

## Result
| role | sample | pooled Brier | single Brier | impr. | pooled rank | single rank | gate |
|------|-------:|------:|------:|------:|------:|------:|:----:|
| hitter  | 411 | 0.26022 | 0.26575 | +2.08% | 0.7607 | 0.7544 | active* |
| pitcher | 468 | 0.29042 | 0.29734 | +2.33% | 0.7299 | 0.7080 | active* |

\*active is **misleading** — it is carried by one fold:

| fold | train rows | model source | pooled vs single |
|------|-----------:|--------------|------------------|
| 2018 | 1559 | `level_age_prior` | **identical** (feature-independent) |
| 2019 | 2332 | `level_age_prior` | **identical** |
| 2021 | 3766 | `historical_neighbors_25` | **pooled < single** (both roles) |

## Read
- **Pooling genuinely helps where the model uses features (2021): both roles, lower
  Brier AND higher rank concordance.** Directionally confirms the Sirota thesis (scoring
  the single slice under-credits multi-level performers).
- **But it is ONE discriminating fold, not two.** 2018/2019 have too little training data
  (1–2 cohorts), so the gate falls back to a level-age prior that uses only level+age —
  unchanged by pooling — so pooled == single by construction. The aggregate "active /
  +2%" is the same tied-folds-pass-the-non-strict-guard-for-free artifact as W2.1; the
  whole verdict rests on 2021.
- **The wall is training-data VOLUME in the early folds, not data-input (backfill solved
  that) and not feature quality.** This is the same root cause that blocks W2.1, so:
  **the backfill does NOT rescue W2.1** — richer pooled features cannot make a
  level-age-prior fold discriminate.

## Recommendation
- **Do not flip pooled scoring to live.** One discriminating fold is a warning label, not
  a validation (the program's standing discipline).
- **Keep `pooled_shadow` observe-only.**
- **Revisit ~Q4 2026** when the 2022 cohort's 4-year outcomes complete: bump
  `OUTCOME_COMPLETE_THROUGH` → 2026 and re-run `run_pooled_vs_single_backtest.py`. 2022
  trains on cohorts ≤2018 (~past the fallback threshold that 2021 cleared at 3766 rows),
  so it should be a 2nd discriminating fold. 2021 + 2022 = the ≥2 the gate needs for a
  real verdict. **The backfill already includes 2022 and the harness is built — the
  revisit is a one-command rerun.**
- **Forward-retention still applies**: the committed `historical_by_level_lines.json` is
  the seed; keep it fresh so later cohorts stay poolable.
