# ValuCast Stage 1 Outcome Proof

**Generated:** 2026-08-14T03:38:46.947576+00:00
**Stage 1 model:** 0.4.0
**Backtest:** 0.1.0
**Mature through cohort:** 2021
**Bootstrap:** 10,000 player-clustered resamples; seed 36061
**Status:** Research-only retrospective evidence
Public superiority authorized: **No**

Contributor means a factual Role or Star outcome within the fixed four-year horizon. All historical rows are mature; open, censored, and retracted claim-time disagreements remain visible in their full funnel. These ordinal outcomes are not realized WAR.
Historical outcomes: **3,652 resolved**, **0 unresolved**, **0 censored**.

## Contributor discrimination and ordering

### Closed-cohort detail

| Role | Cohort | N | Contributor rate | Spearman | Kendall tau-b | ROC AUC |
|---|---:|---:|---:|---:|---:|---:|
| Hitter | 2016 | 336 | 17.3% | 0.425 | 0.349 | 0.821 |
| Hitter | 2017 | 338 | 19.8% | 0.458 | 0.375 | 0.826 |
| Hitter | 2018 | 345 | 18.3% | 0.512 | 0.419 | 0.882 |
| Hitter | 2019 | 360 | 15.3% | 0.444 | 0.365 | 0.852 |
| Hitter | 2021 | 386 | 19.7% | 0.469 | 0.386 | 0.837 |
| Pitcher | 2016 | 382 | 17.0% | 0.368 | 0.301 | 0.778 |
| Pitcher | 2017 | 378 | 17.2% | 0.397 | 0.325 | 0.801 |
| Pitcher | 2018 | 352 | 19.0% | 0.282 | 0.239 | 0.703 |
| Pitcher | 2019 | 410 | 16.3% | 0.340 | 0.285 | 0.758 |
| Pitcher | 2021 | 365 | 15.3% | 0.452 | 0.371 | 0.860 |

### Pooled role results

Each estimate is followed by its 95% player-cluster bootstrap interval. Baseline deltas remain descriptive unless their evidence status is `supported_retrospective`.

| Role | Metric | ValuCast | Level/age prior | Historical neighbors (25) | vs prior | Evidence | vs neighbors | Evidence |
|---|---|---:|---:|---:|---:|:---:|---:|:---:|
| Hitter (n=1765, 5 cohorts) | Spearman rho | 0.462 [0.426, 0.496] | 0.266 [0.224, 0.306] | 0.418 [0.380, 0.456] | 0.196 [0.162, 0.230] | supported_retrospective | 0.044 [0.025, 0.063] | supported_retrospective |
| Hitter (n=1765, 5 cohorts) | Kendall tau-b | 0.379 [0.349, 0.407] | 0.217 [0.183, 0.250] | 0.353 [0.321, 0.384] | 0.161 [0.134, 0.190] | supported_retrospective | 0.026 [0.010, 0.043] | supported_retrospective |
| Hitter (n=1765, 5 cohorts) | ROC AUC | 0.843 [0.820, 0.866] | 0.698 [0.667, 0.728] | 0.810 [0.784, 0.835] | 0.146 [0.120, 0.171] | supported_retrospective | 0.034 [0.019, 0.048] | supported_retrospective |
| Pitcher (n=1887, 5 cohorts) | Spearman rho | 0.353 [0.311, 0.394] | 0.262 [0.221, 0.302] | 0.360 [0.320, 0.399] | 0.091 [0.052, 0.130] | supported_retrospective | -0.008 [-0.041, 0.024] | descriptive |
| Pitcher (n=1887, 5 cohorts) | Kendall tau-b | 0.291 [0.257, 0.325] | 0.214 [0.181, 0.248] | 0.301 [0.269, 0.333] | 0.077 [0.045, 0.109] | supported_retrospective | -0.010 [-0.038, 0.016] | descriptive |
| Pitcher (n=1887, 5 cohorts) | ROC AUC | 0.768 [0.738, 0.797] | 0.700 [0.670, 0.730] | 0.774 [0.745, 0.802] | 0.068 [0.039, 0.097] | supported_retrospective | -0.006 [-0.031, 0.019] | descriptive |

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
| 1 | 176 | 0.000-0.000 | 98.3% | 1.7% | 0.0% | 1.7% | 0.6%-4.9% | observed |
| 2 | 177 | 0.000-0.009 | 98.9% | 1.1% | 0.0% | 1.1% | 0.3%-4.0% | observed |
| 3 | 176 | 0.009-0.031 | 97.7% | 2.3% | 0.0% | 2.3% | 0.9%-5.7% | observed |
| 4 | 177 | 0.031-0.057 | 92.7% | 7.3% | 0.0% | 7.3% | 4.3%-12.2% | observed |
| 5 | 176 | 0.057-0.083 | 93.2% | 6.8% | 0.0% | 6.8% | 3.9%-11.5% | observed |
| 6 | 177 | 0.083-0.111 | 87.6% | 11.3% | 1.1% | 12.4% | 8.4%-18.1% | observed |
| 7 | 176 | 0.111-0.143 | 83.5% | 15.3% | 1.1% | 16.5% | 11.7%-22.7% | observed |
| 8 | 177 | 0.143-0.190 | 71.2% | 23.2% | 5.6% | 28.8% | 22.6%-35.9% | observed |
| 9 | 176 | 0.190-0.266 | 61.9% | 32.4% | 5.7% | 38.1% | 31.2%-45.4% | observed |
| 10 | 177 | 0.267-0.956 | 34.5% | 49.7% | 15.8% | 65.5% | 58.3%-72.1% | observed |

### Pitchers

| Decile | N | Score range | Bust | Role | Star | Contributor | 95% CI | Evidence |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 188 | 0.000-0.000 | 93.1% | 5.3% | 1.6% | 6.9% | 4.1%-11.5% | observed |
| 2 | 189 | 0.000-0.000 | 94.7% | 4.2% | 1.1% | 5.3% | 2.9%-9.5% | observed |
| 3 | 189 | 0.000-0.022 | 94.7% | 5.3% | 0.0% | 5.3% | 2.9%-9.5% | observed |
| 4 | 188 | 0.022-0.043 | 92.6% | 7.4% | 0.0% | 7.4% | 4.5%-12.1% | observed |
| 5 | 189 | 0.043-0.067 | 92.1% | 7.9% | 0.0% | 7.9% | 4.9%-12.7% | observed |
| 6 | 189 | 0.067-0.099 | 88.9% | 10.1% | 1.1% | 11.1% | 7.4%-16.4% | observed |
| 7 | 188 | 0.099-0.135 | 85.1% | 12.8% | 2.1% | 14.9% | 10.5%-20.7% | observed |
| 8 | 189 | 0.135-0.182 | 74.1% | 22.2% | 3.7% | 25.9% | 20.2%-32.6% | observed |
| 9 | 189 | 0.182-0.252 | 69.8% | 23.3% | 6.9% | 30.2% | 24.1%-37.0% | observed |
| 10 | 189 | 0.252-0.895 | 45.5% | 41.3% | 13.2% | 54.5% | 47.4%-61.4% | observed |

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
| backtest | `data/validation/valucast_prospect_dynasty_backtest_maturation2021.json` | `ee315469309fbf82233885e9b5ca973a745eaf478203580a49961fc410e70535` |
| oof | `data/validation/valucast_outcome_oof_scores_maturation2021.json` | `5339ca75a85f29812d1106b6ae38bbe1bea1f395a20c70b29035d99983991c7c` |
| reliability | `data/validation/valucast_probability_reliability_maturation2021.json` | `e22eb9fd50249170e073746e97cf089f5ebbcd659a0355f6de60ce67c3949313` |
| scorecard | `data/validation/valucast_ahead_of_consensus_scorecard_maturation2021.json` | `99fd9b62492ffe0664c39595fa3352238d85c4ff7aef9481588068d1d93fd03a` |

## Boundaries

This report feeds no model score, rank, value, buy signal, Role Watch output, or pitcher publication decision.
It does not claim WAR accuracy, probability calibration, or public superiority.
