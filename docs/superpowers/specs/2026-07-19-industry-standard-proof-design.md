# ValuCast Industry-Standard Proof Design

## Objective

Make ValuCast the default dynasty and prospect valuation reference by combining
three capabilities: independently defensible evidence, stronger challenger
models, and useful distribution. Accuracy claims must be earned by untouched
forward evidence. Product reach cannot substitute for model evidence, and a
model win cannot substitute for a useful fantasy decision product.

The first market is dynasty and prospect valuation. Broader dynasty and redraft
claims are outside this design.

## Current evidence and constraints

- The completed historical prospect replay is diagnostic only. Across 91 matched
  players, ValuCast did not significantly outperform the dated public boards,
  and the hitter result was directionally worse.
- Direct public-source prospect and pitcher cohorts are collecting. They are not
  mature enough to support a claim.
- The current live model remains frozen. The failed decay flag remains preserved.
- Competitor data must never affect production ranks, values, Role Watch,
  pitcher caps, or publication decisions.
- No universal "best model" claim is authorized. Each claim is limited to its
  registered population, task, format, horizon, and outcome.

## Operating model

### 1. Proof engine

Capture ValuCast and comparison predictions before outcomes, freeze the eligible
population and evaluation contract, and publish complete results only after the
claim gate passes. Losses, coverage, uncertainty, and failed cohorts remain in
the evidence record.

### 2. Model laboratory

Evaluate decision-value, hitter-skill, pitcher-skill, and long-horizon prospect
challengers outside production. A challenger may be researched without changing
the live model. Promotion requires a new registered test and untouched forward
evidence; retrospective improvement alone is insufficient.

### 3. Product and distribution

Keep shipping timely cards, explanations, alerts, and decision tools. Add
freshness, sample quality, and methodology receipts where useful. Product copy
may describe observed evidence but cannot outrun the proof engine's authorized
claim state.

The governing flow is:

`capture -> freeze -> score -> validate -> authorize claim -> publish`

## Superiority contracts

The tracks stay separate. Results may not be combined into a universal score.

### Fantasy decision value

- **Question:** Does ValuCast produce better dynasty draft and roster decisions
  in a specified league format?
- **Primary measure:** realized-value regret from following each frozen ordering
  on the identical eligible player pool; lower is better.
- **Horizons:** one, two, and four years, reported separately.
- **Outcome:** realized, format-specific fantasy value using the scoring contract
  frozen at registration.
- **Secondary measures:** percentile-rank error, pairwise concordance, top-k
  regret, and coverage.

### Player-skill forecasting

- **Question:** Does a registered ValuCast challenger forecast future player
  skill more accurately than comparable public skill baselines?
- **Primary measure:** forward error for the rate statistic registered for the
  test.
- **Segmentation:** hitters and pitchers are separate claims. Opportunity and
  availability are reported separately from rate skill.
- **Guardrail:** a strong pitcher result cannot conceal a weak hitter result, or
  vice versa.

### Prospect ranking

- **Question:** Does ValuCast identify the prospects who create the most
  format-specific fantasy value over four years?
- **Primary measure:** top-pick realized-value regret on the common pool.
- **Secondary measures:** ordering error, pairwise concordance, useful-player hit
  rate, and outcome calibration.
- **Guardrail:** reaching MLB or crossing a playing-time threshold is an outcome
  component, not a synonym for fantasy success.

## Claim gate

An industry-standard superiority claim requires all of the following:

- the prediction cutoff, eligible pool, outcome, primary metric, horizon, and
  analysis code were registered before outcomes;
- at least three independent completed cohorts and 150 unique matched players;
- at least 90% outcome coverage among eligible common-pool players;
- at least 5% relative improvement on the registered primary error or regret,
  calculated as `(baseline - ValuCast) / baseline`;
- a paired, cohort-aware 95% confidence interval that excludes no difference;
- no registered role segment or completed cohort that is more than 5% worse on
  the primary metric;
- no metric, population, horizon, or exclusion change after the first outcome
  look; and
- publication of every registered cohort, including losses and inconclusive
  results.

Track-specific registrations may require larger samples or stricter guardrails.
A smaller exploratory track may report `collecting`, `research_only`,
`no_significant_difference`, or `validated_underperformance`, but it cannot
authorize an industry-standard superiority claim.

The claim gate defaults to `research_only`. Failure to prove superiority is not
proof of equality. Any unplanned additional look requires a newly registered
design with an appropriate repeated-testing correction.

## Source identity and public communication

Comparison sources are named only inside the private evidence registry. The app,
share cards, social posts, public reports, and marketing must not identify,
tag, imitate, or promote individual competitors.

Public artifacts may use category labels such as:

- leading public prospect boards;
- public pitcher-skill benchmarks; and
- public dynasty-market alternatives.

The private registry retains the source identity, URL, observation timestamp,
raw capture, content hash, eligibility resolution, and correction history so an
independent reviewer can reproduce the comparison. It must remain outside every
public asset and deployment bundle. The public artifact contains only the
anonymized source class, registered method, aggregate evidence, and claim state.

Authorized copy must remain scoped. Example:

> In a preregistered forward evaluation, ValuCast reduced four-year
> prospect-selection regret by X% against comparable public-board baselines.

That copy is forbidden until the claim gate passes.

## Minimal technical design

Extend the existing file-based competition benchmark lane. Do not add a service,
database, or real-time comparison system.

1. **Private source registry:** append-only dated captures with identity and
   content hashes. This registry is never a public build input.
2. **Frozen registration artifact:** the ValuCast prediction, eligible population,
   league format, horizons, metrics, code version, and input hashes.
3. **Scoring runner:** matched coverage, primary metric, effect size, uncertainty,
   cohort results, segment results, and guardrail failures.
4. **Claim gate:** deterministic status calculation with `research_only` as the
   safe default.
5. **Private model-lab outputs:** challenger results stored outside production
   model inputs.
6. **Sanitized public artifact:** anonymous source classes and authorized results
   only.
7. **Product consumer:** reads only the sanitized artifact and renders nothing
   when no public claim is authorized.

Corrections never overwrite a frozen cohort. They create a new dated record that
links to the original and explains the change. Missing inputs, failed hashes,
weak coverage, inadequate sample size, or an unknown status fail closed and
block publication.

## Verification

The smallest sufficient automated suite must prove:

- deterministic rebuilds and stable content hashes;
- predictions precede outcomes and use the registered code and inputs;
- comparison metrics use identical matched populations;
- insufficient sample, coverage, effect size, uncertainty, or cohort performance
  blocks the claim;
- retrospective and exploratory results cannot authorize public copy;
- competitor identities cannot enter public artifacts or deployment roots;
- model-lab artifacts cannot affect production ranks, values, caps, Role Watch,
  or publication; and
- public evidence views remain understandable and usable in staged desktop and
  mobile browser checks.

The full automated regression suite must pass before any evidence surface ships.

## Release sequence

1. Audit the existing benchmark lane for source leakage, reproducibility, and
   claim-state consistency. Freeze the three superiority protocols and begin
   complete forward cohorts.
2. Test decision-value challengers first, then separate hitter and pitcher skill
   challengers, then long-horizon prospect challengers. Keep all challengers
   isolated until promotion evidence matures.
3. Continue distributing useful analysis without superiority language. After a
   gate passes, add a plain-language, anonymized ValuCast Proof result backed by
   the complete evidence record.

## Industry-standard operating KPIs

- **Evidence:** number and scope of authorized wins with complete cohort
  disclosure.
- **Use:** returning decision users and externally shared ValuCast evidence.
- **Trust:** data freshness, eligible-player coverage, correction rate, and
  explanation completeness.
- **Guardrail:** zero unsupported public claims, source-identity leaks, or model
  isolation failures.

These KPI families are reported separately. Adoption does not authorize an
accuracy claim, and accuracy does not establish adoption.

## Non-goals

- No production model, rank, value, cap, Role Watch, or publication change.
- No new public proprietary skill index in this phase.
- No competitor-branded scoreboard or public head-to-head page.
- No backcast presented as untouched evidence.
- No promise that a favorable result will occur on a fixed schedule.
