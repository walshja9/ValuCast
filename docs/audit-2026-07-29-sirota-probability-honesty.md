# Sirota Case Review and Probability-Honesty Audit

**Date:** 2026-07-29

**Base commit:** `931c9168155af9705927a5baab9fe796178dbaf0`

**Decision:** No player-specific correction. Remove the one uncalibrated
probability-to-copy path, expand the context-only disagreement watchlist, and
reserve the two promising feature ideas for a new-vintage registered study.

## Answer first

Mike Sirota is not evidence that the whole model is blind. The frozen board sees
an elite current statistical line and then discounts it for older age at level,
sample shrinkage, the single-level serving input, and the existing
within-role-to-pooled normalization. The public field appears to put more weight
on tools, athleticism, defense, development history, and the full two-level
season than the live score does.

The disagreement is real and should be visible to reviewers, but the historical
evidence does not authorize a Sirota override or a probability recalibration:

- Sirota's displayed model signal is `27.68%` role-or-better.
- In the exact fixed-horizon out-of-fold replay, hitters in the broad
  `20%-30%` band reached role-or-better `25.0%` of the time (`16/64`; Wilson 95%
  interval `16.0%-36.8%`).
- The narrower `25%-30%` slice reached `50.0%`, but it contains only `10`
  hitters and its Wilson interval is `23.7%-76.3%`. That is not enough evidence
  to relabel Sirota or change the model.

The earlier claim that the Sirota case exposed a sharp probability
contradiction was therefore too strong. It was a narrow-bin, small-sample
observation inside a broad bin that is aligned with realized outcomes.

## Current case anatomy

The committed 2026-07-29 rank row reports:

| Evidence | Committed value |
|---|---:|
| Prospect rank | 177 |
| ValuCast score | 28.04 |
| Raw outcome role percentile | 92.01st |
| Raw impact role percentile | 90.18th |
| Normalized outcome component | 0.276247 |
| Normalized impact component | 0.264369 |
| Role-or-better signal | 27.68% |
| Star signal | 4.00% |
| Field ranks already in context | 12, 13, 31, 43 |
| Existing four-board median | 22 |

The score input and the public stat card are not currently using the same
season slice. The rank row's factual current context is the `242 PA` Double-A
slice, while the card's owned translation shows the combined `401 PA` Double-A
and High-A season. The rank row also records that role-percentile evidence is
mapped into the pooled distribution, materially compressing a top-decile hitter
signal. Both are cohort-wide model questions, not permission to patch Sirota.

## Coverage map

| Candidate explanation | Current coverage | Audit reading |
|---|---|---|
| Defensive floor | Position only; no defensive-value feature | A real missing axis, but no historical defensive metric is presently bound to the model contract. |
| Athleticism | Stolen bases weakly proxy it | The exploratory athleticism proxy was inert; historical MiLB sprint speed is not reconstructable. |
| Injury-adjusted development | Not modeled | Exposure proxies are committed; verified historical IL transactions require a bounded collection. This is a registered challenger candidate, not a correction. |
| Contact quality | Not modeled below supported Statcast levels | Historical AA contact quality is not reconstructable across the required cohorts. Do not backfill it with present-day-only data. |
| Organizational investment | Modeled | Sirota's investment score is `66.69`. Richer investment variants did not earn a new look in the exploratory screen. |
| Full-season pooled production | Observe-only shadow exists | The live input still serves the single-level slice. Keep the pooled alternative on its separately registered research track. |
| Cross-role normalization | Known research issue | The prior ordinal cross-role study was underpowered for its intercept and did not authorize a change. |

## Probability audit

### What is validated today

`data/models/valucast_prospect_dynasty_backtest.json` validates the coherent
bust/role/star distribution against a level-age prior with nested,
fixed-horizon, cohort walk-forward evaluation:

| Role | n | Candidate multiclass Brier | Prior Brier | Registered improvement |
|---|---:|---:|---:|---:|
| Hitter | 1,091 | 0.157715 | 0.167698 | 5.95% |
| Pitcher | 1,127 | 0.221842 | 0.227713 | 2.58% |

The hitter interval excludes zero. The pitcher interval includes zero, so its
improvement is directional, not conclusive.

### What was missing

That artifact grades aggregate distributions and ordering. The existing
`valucast_probability_reliability.json` grades a different quantity: the
out-of-fold ordinal outcome score (`bust=0`, `role=0.5`, `star=1`). It does not
calibrate the `role_or_better_probability` value carried by `dynasty_signal`.

This audit reconstructed the exact candidate distributions inside the existing
walk-forward folds, then binned the role-or-better probabilities in fixed
10-point bands. No model was refit outside the existing fold procedure.

| Role | n | Binary role+ Brier | Fixed-band ECE |
|---|---:|---:|---:|
| Hitter | 1,091 | 0.075082 | 0.01325 |
| Pitcher | 1,127 | 0.106295 | 0.02254 |

The relevant bands are:

| Role and predicted band | n | Mean prediction | Realized role+ | Wilson 95% interval |
|---|---:|---:|---:|---:|
| Hitter 20%-30% | 64 | 22.87% | 25.00% | 16.01%-36.82% |
| Hitter 25%-30% | 10 | 27.83% | 50.00% | 23.66%-76.34% |
| Pitcher 20%-30% | 150 | 23.02% | 25.33% | 19.05%-32.85% |
| Pitcher 25%-30% | 32 | 27.59% | 34.38% | 20.41%-51.69% |

Interpretation: broad-band reliability is reasonable. The tails become sparse,
and narrow slices are too unstable to support player-level probability claims.
These are audit statistics, not a new calibration layer.

## Public-surface trace

The raw `dynasty_signal` remains in the committed public snapshot and the
`outcome_mix()` model helper can turn it into three percentages, but no current
template renders those percentages. The peak artifact also labels its
probability distribution `cumulative_uncalibrated_outcome_distribution` and
`shadow_observe_only`.

One indirect display consumer did survive: `value_suppressor_note()` treated
`bust_risk >= 0.70` as proof that a projection capped at a bench/depth role.
That prose can reach the player card and share-card read. This branch removes
that uncalibrated threshold. The same qualitative sentence remains available
when the separate peak-role label itself is `bench_or_platoon_bat`,
`depth_arm`, `organizational_depth`, or `multi_inning_or_setup_arm`.

No rank, value, buy score, pitcher cap, Role Watch result, or publication gate
reads the new audit output.

## Context watchlist

The existing calibration report inspected external-rank disagreements only
inside ValuCast's top 50. It could see cases where ValuCast was high, but it
could not see consensus-elite players ranked deep by ValuCast.

Report version `0.2.1` adds a context-only watchlist with these fixed guards:

- existing public-board context only;
- at least three eligible public boards;
- existing aggregate median rank at or inside 50;
- ValuCast rank outside 50; and
- at least a 30-rank gap.

On the 2026-07-29 board it finds 14 cases, including Sirota (`#177` versus the
existing four-board median `#22`). This is a review queue, never a tuning flag
or scoring input.

## Decisions and non-actions

1. **No Sirota correction.**
2. **No probability recalibration or public probability claim.**
3. **Remove uncalibrated probability from qualitative card/share prose.**
4. **Add the symmetric, context-only disagreement watchlist.**
5. **Register injury-adjusted development density and position-by-youth as
   data-informed hitter challengers against a new vintage.**
6. **Do not reopen pooled normalization, contact quality, athleticism, or
   investment from this case.**
7. **Preserve the live-model freeze and the failed-decay flag.**

## Reproducibility

Inputs:

- `data/models/valucast_prospect_rank_v1.json`
  SHA-256 `50359f43210becb1e2850a482d42d7edd2a7c5afebaf373d66c15d3b0e041d7e`
- `data/models/valucast_prospect_dynasty_backtest.json`
  SHA-256 `4ec11d56bde5d8d47a0f67ed3c85643579361d2777836f7b4bdbcaf2cdd0650f`
- `data/models/valucast_probability_reliability.json`
  SHA-256 `823f4c1d260f82794aba76154668954ad43c36a2ff84d57e96e4fe23558e3a6f`
- `data/prospects/prospect_model_inputs.json`
  SHA-256 `19ed7044304b72e763d81f2d01fe80b55f3c176eca4d180e1b15a3f57c441e22`

Focused pre-change verification:

```text
python -m pytest -q tests/test_probability_reliability.py \
  tests/test_prospect_dynasty_backtest.py \
  tests/test_prospect_dynasty_layer.py \
  tests/test_prospect_calibration_report.py

34 passed
```
