# ValuCast Stage 1 Outcome Proof

**Generated:** 2026-08-13T12:45:34.948241+00:00
**Stage 1 model:** 0.4.0
**Backtest:** 0.1.0
**Mature through cohort:** 2019
**Bootstrap:** 10,000 player-clustered resamples; seed 34041
**Status:** Research-only retrospective evidence
Public superiority authorized: **No**

Contributor means a factual Role or Star outcome within the fixed four-year horizon. All historical rows are mature; open, censored, and retracted claim-time disagreements remain visible in their full funnel. These ordinal outcomes are not realized WAR.
Historical outcomes: **2,901 resolved**, **0 unresolved**, **0 censored**.

## Contributor discrimination and ordering

### Closed-cohort detail

| Role | Cohort | N | Contributor rate | Spearman | Kendall tau-b | ROC AUC |
|---|---:|---:|---:|---:|---:|---:|
| Hitter | 2016 | 336 | 17.3% | 0.425 | 0.349 | 0.821 |
| Hitter | 2017 | 338 | 19.8% | 0.458 | 0.375 | 0.826 |
| Hitter | 2018 | 345 | 18.3% | 0.512 | 0.419 | 0.882 |
| Hitter | 2019 | 360 | 15.3% | 0.444 | 0.365 | 0.852 |
| Pitcher | 2016 | 382 | 17.0% | 0.368 | 0.301 | 0.778 |
| Pitcher | 2017 | 378 | 17.2% | 0.397 | 0.325 | 0.801 |
| Pitcher | 2018 | 352 | 19.0% | 0.282 | 0.239 | 0.703 |
| Pitcher | 2019 | 410 | 16.3% | 0.340 | 0.285 | 0.758 |

### Pooled role results

Each estimate is followed by its 95% player-cluster bootstrap interval. Baseline deltas remain descriptive unless their evidence status is `supported_retrospective`.

| Role | Metric | ValuCast | Level/age prior | Historical neighbors (25) | vs prior | Evidence | vs neighbors | Evidence |
|---|---|---:|---:|---:|---:|:---:|---:|:---:|
| Hitter (n=1379, 4 cohorts) | Spearman rho | 0.459 [0.418, 0.497] | 0.306 [0.263, 0.349] | 0.411 [0.367, 0.452] | 0.153 [0.117, 0.189] | supported_retrospective | 0.048 [0.026, 0.071] | supported_retrospective |
| Hitter (n=1379, 4 cohorts) | Kendall tau-b | 0.376 [0.343, 0.408] | 0.251 [0.216, 0.286] | 0.347 [0.310, 0.382] | 0.125 [0.096, 0.155] | supported_retrospective | 0.029 [0.011, 0.049] | supported_retrospective |
| Hitter (n=1379, 4 cohorts) | ROC AUC | 0.845 [0.817, 0.870] | 0.731 [0.700, 0.762] | 0.808 [0.777, 0.836] | 0.114 [0.087, 0.141] | supported_retrospective | 0.037 [0.021, 0.055] | supported_retrospective |
| Pitcher (n=1522, 4 cohorts) | Spearman rho | 0.335 [0.287, 0.381] | 0.268 [0.222, 0.314] | 0.355 [0.311, 0.398] | 0.067 [0.022, 0.109] | supported_retrospective | -0.020 [-0.059, 0.019] | descriptive |
| Pitcher (n=1522, 4 cohorts) | Kendall tau-b | 0.277 [0.238, 0.315] | 0.221 [0.183, 0.258] | 0.298 [0.261, 0.334] | 0.056 [0.020, 0.092] | supported_retrospective | -0.021 [-0.053, 0.012] | descriptive |
| Pitcher (n=1522, 4 cohorts) | ROC AUC | 0.751 [0.717, 0.785] | 0.703 [0.669, 0.737] | 0.766 [0.735, 0.798] | 0.049 [0.015, 0.081] | supported_retrospective | -0.015 [-0.045, 0.014] | descriptive |

## Metric definitions

- **Spearman rho:** rank correlation between frozen Stage 1 score and ordinal outcome.
- **Kendall tau-b:** tie-adjusted rank correlation between frozen Stage 1 score and ordinal outcome.
- **ROC AUC:** ordering discrimination for contributor (Role or Star), not probability calibration.
- **Intervals:** two-sided 95% percentile interval from player-clustered resamples.

## Stage 1 evidence bands

Bands are within-role score deciles, not probabilities or public player grades.

### Hitters

| Decile | N | Score range | Bust | Role | Star | Contributor | 95% CI | Evidence |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 137 | 0.000-0.000 | 98.5% | 1.5% | 0.0% | 1.5% | 0.4%-5.2% | observed |
| 2 | 138 | 0.000-0.008 | 97.8% | 2.2% | 0.0% | 2.2% | 0.7%-6.2% | observed |
| 3 | 138 | 0.008-0.028 | 99.3% | 0.7% | 0.0% | 0.7% | 0.1%-4.0% | observed |
| 4 | 138 | 0.028-0.053 | 92.0% | 8.0% | 0.0% | 8.0% | 4.5%-13.7% | observed |
| 5 | 138 | 0.053-0.078 | 93.5% | 6.5% | 0.0% | 6.5% | 3.5%-11.9% | observed |
| 6 | 138 | 0.078-0.107 | 91.3% | 8.0% | 0.7% | 8.7% | 5.0%-14.6% | observed |
| 7 | 138 | 0.107-0.139 | 80.4% | 17.4% | 2.2% | 19.6% | 13.8%-27.0% | observed |
| 8 | 138 | 0.139-0.181 | 75.4% | 20.3% | 4.3% | 24.6% | 18.2%-32.4% | observed |
| 9 | 138 | 0.181-0.248 | 61.6% | 31.2% | 7.2% | 38.4% | 30.7%-46.7% | observed |
| 10 | 138 | 0.248-0.956 | 34.1% | 51.4% | 14.5% | 65.9% | 57.7%-73.3% | observed |

### Pitchers

| Decile | N | Score range | Bust | Role | Star | Contributor | 95% CI | Evidence |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 152 | 0.000-0.000 | 92.8% | 5.3% | 2.0% | 7.2% | 4.1%-12.5% | observed |
| 2 | 152 | 0.000-0.000 | 93.4% | 5.3% | 1.3% | 6.6% | 3.6%-11.7% | observed |
| 3 | 152 | 0.000-0.017 | 95.4% | 4.6% | 0.0% | 4.6% | 2.2%-9.2% | observed |
| 4 | 152 | 0.018-0.039 | 93.4% | 6.6% | 0.0% | 6.6% | 3.6%-11.7% | observed |
| 5 | 153 | 0.039-0.064 | 88.2% | 11.8% | 0.0% | 11.8% | 7.6%-17.8% | observed |
| 6 | 152 | 0.064-0.096 | 89.5% | 9.2% | 1.3% | 10.5% | 6.6%-16.4% | observed |
| 7 | 152 | 0.096-0.132 | 80.9% | 17.1% | 2.0% | 19.1% | 13.6%-26.1% | observed |
| 8 | 152 | 0.132-0.180 | 74.3% | 21.1% | 4.6% | 25.7% | 19.4%-33.1% | observed |
| 9 | 152 | 0.181-0.248 | 71.1% | 21.1% | 7.9% | 28.9% | 22.3%-36.6% | observed |
| 10 | 153 | 0.249-0.794 | 47.7% | 39.2% | 13.1% | 52.3% | 44.4%-60.0% | observed |

## Frozen disagreements

Initial-gap bins use frozen claim-time ranks. Open, resolved, censored, and retracted calls remain in the denominator.

| Scope | Initial gap | Total | Open | Resolved | Censored | Retracted | Toward | Away | Evidence |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Overall | 25-49 | 57 | 15 | 14 | 2 | 26 | 16 | 9 | observed |
| Overall | 50-99 | 70 | 38 | 12 | 2 | 18 | 21 | 12 | observed |
| Overall | 100-199 | 54 | 27 | 2 | 5 | 20 | 13 | 7 | observed |
| Overall | 200+ | 57 | 33 | 4 | 6 | 14 | 21 | 5 | observed |
| Hitter | 25-49 | 41 | 7 | 10 | 1 | 23 | 11 | 4 | observed |
| Hitter | 50-99 | 36 | 18 | 8 | 0 | 10 | 12 | 4 | observed |
| Hitter | 100-199 | 27 | 10 | 2 | 1 | 14 | 4 | 3 | observed |
| Hitter | 200+ | 30 | 19 | 2 | 1 | 8 | 15 | 2 | observed |
| Pitcher | 25-49 | 16 | 8 | 4 | 1 | 3 | 5 | 5 | descriptive |
| Pitcher | 50-99 | 34 | 20 | 4 | 2 | 8 | 9 | 8 | observed |
| Pitcher | 100-199 | 27 | 17 | 0 | 4 | 6 | 9 | 4 | observed |
| Pitcher | 200+ | 27 | 14 | 2 | 5 | 6 | 6 | 3 | observed |

## Provenance

| Input | Path | LF-normalized SHA-256 |
|---|---|---|
| backtest | `data/models/valucast_prospect_dynasty_backtest.json` | `ee315469309fbf82233885e9b5ca973a745eaf478203580a49961fc410e70535` |
| oof | `data/models/valucast_outcome_oof_scores.json` | `6d661c72bd1eecbf61f8458f4d068a635bca648ef7d4245e0686d911f93cd1d5` |
| reliability | `data/models/valucast_probability_reliability.json` | `9fc668efb2ce603aa2600fcd5540e9d6e3b7ab39a78b1d159f4c4a6d0a92fb1b` |
| scorecard | `data/models/valucast_ahead_of_consensus_scorecard.json` | `99fd9b62492ffe0664c39595fa3352238d85c4ff7aef9481588068d1d93fd03a` |

## Boundaries

This report feeds no model score, rank, value, buy signal, Role Watch output, or pitcher publication decision.
It does not claim WAR accuracy, probability calibration, or public superiority.
