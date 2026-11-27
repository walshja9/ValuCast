# Competition Historical Replay Design

## Decision

Add one retrospective, research-only benchmark against dated public preseason
prospect boards from 2019, 2020, and 2022. Do not backcast ValuCast against the
2025 prospect boards or the 2026 pitcher-skill list: ValuCast has no prediction
snapshot from those earlier dates, so that comparison would be built after some
outcomes were visible.

## Cohorts and cutoffs

- ValuCast uses the existing neutralized walk-forward folds for 2018, 2019,
  and 2021. Each fold trains only through four years before its test cohort.
- The public-board baseline uses the following preseason report, published
  before the outcome window: 2019 for the 2018 fold, 2020 for the 2019 fold,
  and 2022 for the 2021 fold.
- Evaluation keeps only uniquely name-matched players present in both systems.
  Hitter and pitcher results are reported separately as well as combined.
- The outcome is the existing factual four-year MLB tier used by ValuCast's
  registered rank backtest. It is not labeled fantasy value.

## Metrics and claim policy

Reuse the competition benchmark's percentile-rank MAE, paired hierarchical bootstrap
that resamples completed cohorts first and matched players within each sampled cohort,
pairwise concordance, and top-k regret. The artifact may report the statistical
winner, losses, coverage, and uncertainty, but its public status is always
`research_only` and `claim_authorized` is always false. The later model-design
and selection process could have learned from these historical outcomes, so
this replay can inform confidence and failure analysis but cannot prove forward
superiority.

## Data and isolation

The private registry is the sole authority for source identity and capture
hashes. Public documentation and artifacts expose only anonymous source classes
and aggregate results. The replay reads the existing historical input contract
and rank-backtest functions. It writes only to the private evidence lane and a
sanitized public artifact, which remains empty because this evidence is
`research_only`; it cannot feed ranks, values, Role Watch, pitcher caps,
publication, or any model gate. The model freeze and failed decay flag remain
unchanged.

## Current evidence state

The 2026-07-19 replay resolves all 91 matched players (30, 26, and 35 by
cohort). Combined MAE is 0.306106 for ValuCast and 0.277446 for the baseline,
with a baseline-minus-ValuCast delta of -0.028661 and 95% CI
[-0.088668, 0.022223]. Hitter MAE is 0.313697 versus 0.279752, delta
-0.033946, 95% CI [-0.091995, 0.020214]. Pitcher MAE is 0.268519 versus
0.277189, delta +0.008670, 95% CI [-0.120880, 0.120802].

These are descriptive historical estimates, not a superiority verdict. All
three underlying evaluator views remain `collecting` because the underpowered
91-player replay is below the current 150-unique-player claim floor. The replay
wrapper remains `research_only` with `claim_authorized: false`, and the public
artifact remains empty.

## Verification

Tests must prove that ambiguous names stay unmatched, source captures are
sealed, all three folds are evaluated, and even a statistically favorable
result remains claim-blocked. The builder must be deterministic and the full
test suite must pass before the result is reported.
