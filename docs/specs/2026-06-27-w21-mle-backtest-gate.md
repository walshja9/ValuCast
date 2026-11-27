# W2.1 — MLE rewrite backtest-buildability gate

**Status: no-go on the out-of-sample outcome backtest. Near-path revisit is real
but too thin to render a gated verdict; forward-retention is the actual unblock.**

Companion to `w21-blocked-on-data.md`. Observe-only; nothing here is served. All
numbers measured on committed, network-free data.

## Question (the gate, not the method)
Is the committed historical data sufficient to validate MLE-pooled multi-level
valuation against single-best-line **out-of-sample, against realized outcomes**?

## Verdict
1. **Single-best-line outcome backtest: 3 mature folds (W2.1).** Horizon 4y,
   `OUTCOME_COMPLETE_THROUGH=2025`, cohorts 2014–2022 (2020 absent). Walk-forward
   (train_through = test − 4, non-empty train required) yields valid folds at test
   years **2018, 2019, 2021 only** → 3 folds (clears `MIN_FOLD_COUNT=2`, thin).
2. **Pooled-vs-single on that target: not constructible.** The pooled historical
   *input* for cohorts ≤2021 cannot be built — those by-level lines were never
   retained (universal dataset selects "earliest credible season, highest level
   within season", `player_grouped`; `_base_historical_rows` dedups to one row per
   player; 6756/6756 single-level). By-level history exists only 2022→present
   (`milb_card_history.json`, 35.5% multi-level), disjoint from the mature window.
   The brief's hypothesis (pooling *more* testable) is **false on committed data**
   for the outcome target.

## Join confirmation (the near-path revisit, 2022 cohort)

**(a) The revisit trigger is a manual constant bump, not an automatic tick.**
`OUTCOME_COMPLETE_THROUGH = 2025` is a **hardcoded constant** (dynasty_backtest.py:28),
not derived from the data or the calendar. The 2022 cohort matures at 2022+4 = 2026,
so the revisit requires manually advancing the constant to **2026**, valid only once
the 2026 season's outcomes are complete (~Q4 2026 / post-season). It will not happen
on its own.

**(b) The 2022 cohort joins across both stores — but thinly, and as a single fold.**
Join on `mlbam_id`, 2022 cohort:
- Single-best store (universal dataset), cohort 2022: **772** rows (385 H / 387 P).
- By-level store (card history), season 2022: **598** players.
- **Joined: 142 (18.4% of single-best).** Of those, **75 are genuinely poolable**
  (>1 level, so a pooled input differs from the single-best line), split **32 H / 43 P**.
  Card-history lines carry full stat fields (PA/IP, rate stats), so the pooled input
  is constructible for these 75 — buildability isn't blocked by missing fields.

**Why that is not yet a gated verdict:**
- **One fold.** Only 2022 has *both* a by-level input (card history starts 2022) and
  a maturing 4-year outcome at the revisit. 2023 matures ~Q4 2027, 2024 ~2028, etc.
  So Q4 2026 yields exactly **one** pooled-vs-single fold — below `MIN_FOLD_COUNT=2`;
  the gate cannot render a verdict from it.
- **Thin.** ~75 discriminating players (32 H / 43 P) is far under `MIN_GATE_SAMPLE=250`
  per role and `MIN_REALIZED_OUTCOME_SAMPLE=2000`. A directional peek, not a powered test.
- **Survivorship skew.** Only 18.4% of the 2022 single-best cohort appears in card
  history; the joinable subset is biased toward players still tracked through 2022–2026
  (i.e., who persisted), so even the 75 are not a representative sample of the cohort.

A 2-fold gated verdict needs 2023 to also mature (~Q4 2027), and both folds stay thin.

## Bottom line
- **STOP on the outcome head-to-head — no-go, W2.1.** Do not design pooled scoring
  as an outcome-validated method on committed data.
- **The near-path is real but not gate-grade.** The 2022 join exists (75 poolable),
  but the Q4 2026 revisit produces a single sub-gate, survivorship-skewed fold — a
  directional read at best, not a verdict. Do not bank it as a buildable validation.
- **Forward-retention is the actual unblock (free, do now).** Stop collapsing —
  retain by-level lines in the historical dataset builder from now on (a one-line
  policy change in the selection step, no network) so 2026+ cohorts mature into
  multi-fold, full-sample pooled-vs-single backtests (≈2030+). Pre-2022 backfill
  needs an external MiLB feed (FanGraphs Cloudflare-blocked; loaders network-free),
  so it is a data-acquisition task, not a same-session build.

## Revisit checklist (when 2026 outcomes complete)
- Bump `OUTCOME_COMPLETE_THROUGH` → 2026 (manual).
- Re-run the join; confirm the 2022 poolable count and its survivorship profile.
- Treat the single 2022 fold as directional only until 2023 matures (2-fold floor).
- Independent of the revisit: land forward-retention now so the fold supply grows.
