# Fold-Local Prospect Impact Audit

**Date:** 2026-07-21
**Status:** Research only; no public claim authorized
**Artifact:** `data/models/valucast_impact_oof_scores.json`

## Decision

The fold-local replay preserves evidence of a useful pitcher impact signal, but
does not support a general claim that the incumbent impact model beats its
strongest historical-neighbor baseline for both roles.

Keep the live prospect model, ranks, values, and publication rules frozen.
Treat the served partial-impact gate as uncertified until its full-store
percentile references are replaced through a separately registered model
change. The audit itself must remain reporting-only.

## What Was Tested

- Four cohort-generalization folds: 2016, 2017, 2018, and 2019.
- Separate hitter and pitcher models.
- 2,901 player-fold predictions: 1,379 hitters and 1,522 pitchers.
- Impact percentile references built only from eligible training identities in
  each fold.
- Fixed four-year outcome horizons.
- Absolute-error comparisons against the level-age prior, rich historical
  25-neighbor baseline, and canonical historical 25-neighbor baseline.
- Equal-weight cohort-then-player bootstrap with 5,000 resamples and research
  seed 72127.

All eight role-folds scored. Every reference identity is disjoint from its test
cohort, and the artifact validator recomputes player errors and summary
intervals.

## Results

Positive deltas mean the incumbent model had lower error.

| Segment | Comparison | Model MAE | Baseline MAE | Baseline minus model | 95% interval | Read |
|---|---:|---:|---:|---:|---:|---|
| Combined | Rich 25-neighbor | 0.131585 | 0.135890 | +0.004348 | +0.001674 to +0.007381 | Aggregate win |
| Hitters | Rich 25-neighbor | 0.094541 | 0.093017 | -0.001544 | -0.004312 to +0.001173 | No win; point estimate favors neighbors |
| Pitchers | Rich 25-neighbor | 0.165149 | 0.174735 | +0.009778 | +0.004442 to +0.015830 | Clear internal-baseline win |
| Combined | Canonical 25-neighbor | 0.131585 | 0.139034 | +0.007465 | +0.004606 to +0.010481 | Aggregate win |
| Hitters | Canonical 25-neighbor | 0.094541 | 0.095771 | +0.001222 | -0.002425 to +0.004718 | Inconclusive |
| Pitchers | Canonical 25-neighbor | 0.165149 | 0.178232 | +0.013221 | +0.008557 to +0.019052 | Clear internal-baseline win |

The incumbent also beat the level-age prior in both roles, but that is the
weakest comparator and is not a product-superiority standard.

## Interpretation

The aggregate result is driven by pitchers. Publishing it without the role
split would overstate the evidence. The most defensible internal conclusion is:

- pitcher impact modeling has survived this leakage repair against the current
  internal baselines;
- hitter impact modeling has not shown an advantage over rich statistical
  neighbors; and
- neither result compares ValuCast with an external product or authorizes a
  market-superiority claim.

This is a cohort-generalization audit using matured outcomes for earlier
cohorts. It is not a point-in-time deployment replay. The target also remains a
partial-category impact construct rather than direct 7x7 realized fantasy
value.

## Next Decision

Use the hitter result to prioritize the registered post-2026 challenger queue:
ridge tuning, stronger neighbor baselines, target scaling, and train/serve
shrinkage alignment. Preserve separate hitter and pitcher verdicts. Do not
promote, retune, or publish from this audit.
