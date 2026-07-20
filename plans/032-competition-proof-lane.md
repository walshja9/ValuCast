# Plan 032: Registered ValuCast Competition Proof Lane

## Status

- **Registered:** 2026-07-19, before either registered outcome horizon is known.
- **State:** dark, comparison-only, collecting.
- **Purpose:** determine whether ValuCast outperforms public baselines on the same players, cutoff, horizon, and fantasy decision task.

This registration cannot prove that ValuCast is universally "better." It can support only a scoped statement about one registered task, public baseline class, cohort set, and horizon after every claim gate passes.

## Frozen tracks

### Track A: Four-year prospect fantasy value versus a public prospect-board baseline

- Entrants: the MLBAM-identified intersection of ValuCast Prospect Rank v1 and the captured public prospect-board snapshot. The private registry is the sole authority for source identity and capture hashes.
- First cutoff: 2026-07-19.
- Prediction: each system's frozen ordinal within the matched cohort.
- Primary outcome: realized format-specific MLB fantasy value accumulated during the four seasons after registration.
- Secondary interpretation: fixed role-attainment outcomes may be shown, but reaching 300 PA or 50 IP is not itself labeled fantasy success.
- Minimum evidence: three independent registered cohorts and 250 unique players with completed outcomes.
- First registered sample and state: 2,611 matched players, 0 matured outcomes, `collecting`.

### Track B: Rest-of-season pitcher fantasy usefulness versus a public pitcher-skill baseline

- Entrants: the 12 starting pitchers in a public 2026-07-17 pitcher-skill list, matched by MLBAM identity to ValuCast's dated 2026-07-17 MLB projection archive. The private registry is the sole authority for source identity and capture hashes.
- Prediction: the baseline's published order versus ValuCast's 2026 season-category projection order inside the identical 12-player set.
- Primary outcome: realized rest-of-season 7x7 fantasy category value beginning on the 2026-07-19 registration date. Results from the post's 2026-07-17 publication through 2026-07-18 are excluded so the cohort is never backdated.
- Interpretation limit: this tests fantasy decision usefulness. It does not claim that ValuCast estimates pure pitcher skill better than the baseline.
- Minimum evidence: three independent public-list captures and 30 unique pitchers with completed outcomes.
- First registered sample and state: 12/12 published starters, 0 matured outcomes, `collecting`.

## Frozen metrics

1. **Primary:** mean absolute percentile-rank error against realized fantasy-value order; lower is better.
2. **Uncertainty:** paired hierarchical bootstrap that resamples completed cohorts first and matched players within each sampled cohort; deterministic seed 32019, 10,000 resamples, and a two-sided 95% percentile interval on competitor error minus ValuCast error.
3. **Confirmers:** pairwise rank concordance and top-k realized-value regret, using k=25 for prospects and k=5 for pitcher lists or the largest valid k below the cohort size.
4. **Coverage:** resolved outcomes divided by registered common-player rows. Unresolved and unmatched rows remain in the published denominator.

## Frozen decision rule

`validated_superiority` requires all of the following:

- minimum cohort and unique-player counts are met;
- at least 90% outcome coverage;
- the 95% interval's lower bound for competitor-minus-ValuCast error is above zero;
- relative improvement is at least 5%;
- ValuCast is not worse by more than 5% relative MAE in any completed cohort;
- ValuCast is not worse by more than 5% relative MAE in any completed role segment;
- ValuCast top-k regret is no worse than the comparator's.

If the interval's upper bound is below zero, the verdict is `validated_underperformance`. Otherwise it is `no_significant_difference`. Before evidence thresholds mature, it is `collecting`. No copy may collapse these states into “winning.”

- A narrow track may report statistical results at its registered exploratory sample, but no industry-standard superiority claim is authorized below 150 unique matched players.
- Superiority also requires at least 5% relative improvement and no role or completed cohort more than 5% worse on the primary metric.
- Public artifacts use anonymous source classes; named evidence remains private.

## Source and immutability rules

- Every capture records its observation date, source label, source location, input content hashes, and matched/unmatched counts in the private registry.
- A committed cohort is immutable. Corrections create a new dated registration with a reason; they never overwrite the old prediction.
- No competitor value or rank may feed ValuCast scoring, ranking, values, Role Watch, pitcher caps, or publication.
- Public results must name the task, horizon, cohort count, sample, coverage, point estimate, interval, and losses as well as wins.
- Model, metric, and gate changes require a new numbered registration before another look.

## Retrospective research lane

The 2026-07-19 source audit found no contemporaneous ValuCast snapshot for the
dated August/October 2025 prospect boards and no older captured pitcher-skill
list. Those sources cannot support an honest direct historical head-to-head.

Plan 032 therefore permits one clearly separate research replay against
dated public preseason prospect boards from 2019, 2020, and 2022. ValuCast uses
the already-registered neutralized 2018, 2019, and 2021 walk-forward folds, and
the outcome is the existing factual four-year MLB tier. The replay must always
emit `research_only`, must never authorize a public superiority claim, and must
write outside `data/models/`. It is diagnostic evidence, not a substitute for
the two forward tracks. The private registry remains the sole authority for
source identity and capture hashes.

### First descriptive estimates: 2026-07-19

- Common eligible players: 91 total (30, 26, and 35 by cohort), all resolved.
- Combined: ValuCast MAE 0.306106, baseline 0.277446; baseline-minus-ValuCast
  delta -0.028661, 95% CI [-0.088668, 0.022223].
- Hitters: ValuCast MAE 0.313697, baseline 0.279752; delta -0.033946, 95% CI
  [-0.091995, 0.020214].
- Pitchers: ValuCast MAE 0.268519, baseline 0.277189; delta +0.008670, 95% CI
  [-0.120880, 0.120802].
- All three underlying evaluator views remain `collecting` under the current
  150-unique-player claim floor. The 2019 ValuCast fold was 28.4% worse than
  the 2020 public-board baseline on combined MAE, so the single-cohort
  non-regression rule also blocks superiority.
- These are descriptive historical estimates from an underpowered 91-player
  sample, not a superiority verdict. The replay wrapper remains `research_only`
  with `claim_authorized: false`; no public claim is authorized.
- The sanitized public artifact remains empty until approved future primary evidence authorizes a claim.
