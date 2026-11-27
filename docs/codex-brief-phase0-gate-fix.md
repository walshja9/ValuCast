# Codex Brief — Phase 0: Fix the Gate (the keystone)

Status: **STAGED. Do not execute until after the 2026-07-13 scorecard unlock**
(rides the plan-028 epoch bump; Fable gates the push). This is the first unit of
the model-core accuracy program (`docs/model-core-program-2026-07-13.md`).

## Why this is first

Every model change is judged by the backtest harness. Tonight's audits proved
the harness lies in two ways — it validates against a truncated cohort and calls
an in-sample number "out-of-sample." Until it's honest, no downstream model work
(028's pitcher fix included) can be trusted. Fix the ruler before measuring.

The acceptance gate for this work is the honest backtest itself: Fable reviews
the diff and re-runs the harness. Do not self-certify.

## Task 1 — F5: un-truncate the pitcher cohort

`prospects/adapter_backtest.py`, `_actual_row` (~line 142): pitcher categories
build `QS` from `season.get("qs")`, and the `if any(value is None ...): return
None` check (~line 155) drops the ENTIRE row when QS is missing. This silently
removes 58 established pitchers (1069 obs instead of 1127) — and the dropped
pitchers are outcome-correlated (all cleared the established-IP threshold), so
the exclusion biases the metric.

Fix: stop dropping a pitcher for a missing `QS` alone. Preferred approach:
impute `QS = 0` when absent (pre-QS-era / missing feeds), so the row scores on
its remaining categories. If you instead score pitchers on the QS-free category
subset, state that choice in the diff. Hitters are unaffected (0 rows dropped
for missing categories) — verify they stay at n=1091 / 0.7791.

Re-emit `data/models/valucast_prospect_adapter_backtest.json`.

**Restate the acceptance baseline in the same PR.** The corrected pitcher
concordance baseline is ~**0.4692 on n=1127** (verified: imputing QS=0 reproduces
the committed artifact before correction, then shifts to 0.4692). The old 0.4903
figure is dead — 028's gate ("pitcher concordance improved over 0.4903") must be
updated to target the corrected baseline. Update the number in
`plans/028-pitcher-lean-model-fix.md` (the acceptance-gate restatement section
already flags this).

## Task 2 — F4: clip the category-impact label window

`prospects/model.py`, `_impact_target` (~lines 476-517): the season loop has a
lower guard (`if year <= cohort_year: continue`) but NO upper clip, so
walk-forward folds train on outcomes from years AFTER the fold — e.g. the 2019
fold's labels are sealed with 2020-2026 results. The shadow artifact's gate
reason then calls a `4.15% OOS` improvement that is actually in-sample.

Fix: add the upper clip, mirroring the closure `prospects/dynasty_backtest.py`
already uses (`OUTCOME_HORIZON_YEARS = 4`):
`if year <= cohort_year or year > cohort_year + OUTCOME_HORIZON_YEARS: continue`.
This lands inside the retrain 028 already schedules (fix 3c reopens the same
function) — do it there, one edit, one retrain. Expect the reported
category-impact MAE to rise (labels get honestly harder) and the "OOS" reason to
become truthful; that is the correct direction, not a regression.

## Task 3 — assess the universal-model lead (verify, then fix if confirmed)

`prospects/universal.py`, `_future_seasons` (~lines 548-554) reportedly uses the
same unbounded `year > cohort_year` window with no closure — and universal is
the SERVED model (app.py serves `valucast_universal_prospect_model.json`), so
this leak, if real, is higher-stakes than the shadow F4 one. Trace it; if it
lacks the four-year clip, apply the same fix and re-emit. If it's already
clipped, say so and move on.

## Task 4 — regression locks

Add two harness self-checks so neither defect class can recur silently:
1. **Cohort-cardinality:** assert the pitcher backtest cohort is within a small
   tolerance of the fixed-horizon count (would have caught the QS truncation:
   1069 vs 1127).
2. **Label-window:** assert no training label consumes a season beyond
   `cohort_year + OUTCOME_HORIZON_YEARS` in the category-impact / universal
   walk-forwards (would have caught F4).

These are cheap and they are the durable payoff — the audits become permanent
guards instead of one-time finds.

## Constraints (project invariants)

- Targeted suites only during iteration; Fable runs the single full gate.
- pytest dirties
  `data/prediction_archive/valucast_prospect_peak_projection_v1/2026-06-15.json`
  — never commit it; restore with `git checkout --`.
- Do NOT push. Return the diff for review. The epoch bump (`PROSPECT_BUYS_EPOCH`)
  must be bumped in the same batch as any score-moving change so movers/buys
  report the re-score as a re-baseline, not player movement.
- Everything here rides ONE board re-baseline with 028 — do not ship the gate
  fix on its own epoch.

## Definition of done

Harness passes its own new self-checks; the corrected pitcher baseline (~0.4692,
n=1127) and honest category-impact MAE are re-emitted and documented; 028's
acceptance gate references the corrected number; hitter metrics unchanged. Then
028's pitcher surgery can be judged against a ruler we trust.
