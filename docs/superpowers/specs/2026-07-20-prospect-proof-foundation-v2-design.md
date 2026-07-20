# Prospect Proof Foundation v2 Design

## Goal

Make future ValuCast prospect-model wins reproducible and claim-grade without
changing the live model, ranks, values, pitcher publication limits, Role Watch,
or any frozen experiment flag.

This design implements only work supported by the data available today. It
does not fit a promotion-resilience model from undated season totals, train on
the single current AAA Statcast vintage, or present a historical pseudo-board
as an exact replay.

## Existing systems to reuse

The repository already has the necessary proof and archive primitives:

- `prospects/competition_benchmark.py` seals cohorts, evaluates identical
  matched populations, calculates cohort-aware uncertainty, enforces sample,
  coverage, effect, cohort, and role guardrails, and fails closed.
- `scripts/archive_aaa_statcast_features.py` writes immutable dated AAA
  Statcast snapshots and is already called by the daily build.
- dated rank, availability, roster, actuals, and model artifacts already live
  under `data/prediction_archive/`.
- `prospects/dynasty_backtest.py` already reports temporal fold stability and
  confidence intervals for its ordinal outcome task.

No database, service, queue, new public scoreboard, or second claim engine is
needed.

## Workstreams

### 1. Reconcile the public model contract

Update `docs/prospect-model.md` to match the artifacts actually consumed:

- Prospect Rank v1 feeds the live prospect ordering.
- The model has an ordinal outcome head and a partial-category impact head.
- The impact target is not direct 7x7 because pitcher QS is unavailable.
- The impact target describes the best qualifying future season, not
  cumulative dynasty value.
- Current backtest improvements are retrospective evidence and do not
  authorize a superiority claim.

Add a small contract test that compares the documentation's machine-readable
status block with the rank and model artifacts. The test must fail if live
consumption, target kind, direct-7x7 status, or missing-category disclosure
drifts again.

### 2. Build a shadow-only realized-value readiness audit

Before implementing a realized-value or regret evaluator, add a pure audit that
reports whether the historical outcome store can support the registered
format, categories, horizons, and matched population.

The audit reports separately by role and cohort:

- eligible and resolved players;
- category coverage;
- missing QS or other required categories;
- duplicate identities and role changes;
- zero-opportunity outcomes;
- cohort and role sample sizes; and
- whether an exact or pseudo replay is possible.

This workstream also creates the two-way-player identity policy; it does not
cite one as if it already exists. The policy must freeze the identity key,
cohort-cutoff role assignment, later role-change treatment, duplicate handling,
and common-pool counting rule before the readiness audit can pass. Until that
policy is registered, a player with conflicting hitter and pitcher rows blocks
the affected cohort rather than being silently duplicated or assigned.

Any missing required category, insufficient coverage, current-state input, or
unknown status blocks `realized_value_regret`. It does not silently substitute
an ordinal outcome or partial-category score.

Output is a validation artifact only. It cannot be imported by production
scoring code.

### 3. Correct target construction in the challenger evaluator

Do not modify the frozen incumbent model. Its ordinary outcome walk-forward,
feature scaling, neighbor model, prior, and universal target constants already
respect the training boundary; this work must not describe that path as leaky.
The narrower partial-category impact path is different: it builds outcome
percentile references once from the full historical MLB-season store before
walk-forward target rows are labeled. The challenger evaluator must calculate
those partial-impact outcome references from the training fold only, then apply
the frozen references to the test cohort. This corrects the confirmed target
reference issue without making a false claim about the entire incumbent.

The evaluator records, for every fold:

- training and test cohort years;
- input and reference hashes;
- fitted reference counts;
- missing-category counts;
- eligible and scored identities; and
- the exact reason a row was excluded.

The current best-single-season partial-category target remains a declared
secondary endpoint. It cannot authorize a format-specific fantasy-value claim.

### 4. Capture only the missing prospective MiLB evidence

Add one compact daily observation archive derived from the canonical current
MiLB inputs. Each dated row contains only fields needed for future evaluation:

- `mlbam_id`, role, organization, level, source kind, and observation date;
- age and sample size;
- the factual hitter or pitcher rate fields already accepted by the input
  contract; and
- an artifact/input content hash.

Files are immutable by date. Re-running the same date with identical content
is a no-op; changed content for a sealed date fails. No historical promotion
dates are inferred from season totals.

This archive is sufficient to identify future observed level changes between
snapshots. It is not sufficient to infer the exact transaction date, demotion
reason, injury status, or pre/post-promotion split until those facts are
captured directly.

AAA Statcast, rank, availability, roster, and actuals archives remain in their
existing systems and are referenced by hash rather than copied.

The new dated archive directory must be added to the explicit guarded `git add`
allow-list in `.github/workflows/daily-public-data.yml`, following the existing
`aaa_statcast_archive` pattern. The user has explicitly authorized this narrow
one-time edit to the conventionally frozen workflow file. It does not authorize
other workflow changes. The workflow must pass its CI shakedown before this
delivery can be called shipped.

### 5. Register one shadow breakout-ranking challenger

The challenger is private, research-only, and has no production importer. It
uses the same eligible players and outcome rows as the incumbent comparison.
Hitters and pitchers are fitted and reported separately.

Registered variants are deliberately limited:

1. **Control:** incumbent historical feature contract and evaluator.
2. **Normalized production:** a nonlinear, cutoff-available quantile
   representation of the existing component rates. For each historical cutoff,
   each rate is transformed against the leave-one-out empirical distribution
   of same-role, same-level, same-season input peers available at that cutoff.
   For this study, the reconstructable historical cutoff is cohort-season
   completion; the historical store does not support an earlier intra-season
   cutoff.
   No future outcome or post-cutoff observation may enter the reference pool.
   A same-level cell requires at least 25 other peers. Sparse cells back off to
   the same-role, same-season pool, which requires at least 250 other peers. If
   that pool also misses its minimum, the normalized variant is unavailable for
   the row rather than silently substituting the Control representation. The
   historical row therefore carries a season-relative input value that exists
   on both sides of a cohort-year boundary; it never looks up a test calendar
   year in the training fold. This nonlinear quantile form is genuinely distinct
   from the failed additive fitted-level translation documented in plan 031.
3. **Combined:** normalized production plus promotion information, but this
   variant remains unavailable until the prospective archive contains enough
   dated transitions for the registered sample and cohort floors.

The 25- and 250-peer minimums above are frozen before the first result look.
The registration must also require the normalized representation to be
exercised for at least 90% of the common-pool rows in every reported role and
fold. Falling below that floor invalidates the variant; it is not scored as a
tie with the Control. Reference counts, backoffs, unavailable rows, and
exercised coverage are reported for every fold.

The following are reports or ablations, not bundled scoring features, and all
are computed inside the single registered look rather than treated as free
additional looks:

- an under-19/full-season-minors subset report;
- hitter position only if historical position semantics pass their own data
  audit; and
- AAA Statcast disagreement on the same eligible current AAA population.

AAA Statcast is never filled with zero when missing, extrapolated below AAA,
or trained against outcomes until multiple dated vintages have matured. The
first version uses measured components rather than a hand-built Stuff or Skill
index.

The existing v0.7 preview is a feature-readiness and coverage shadow, not a
scoring model. It is excluded as a baseline unless a pre-registration contract
first demonstrates that it emits a stable ranking prediction for the identical
eligible population. It is never a second promotion candidate.

## Evaluation and claim rules

- Primary future prospect-ranking endpoint: fixed-horizon, format-specific
  realized-value regret on a common pool, once the readiness audit passes.
- Secondary endpoints: partial-category best-season impact, ordinal outcome,
  pairwise concordance, top-k regret, calibration, coverage, and stability.
- Hitters and pitchers receive separate estimates, intervals, and verdicts.
- Thresholds use continuous shrinkage and reliability; no imported 60-AB or
  40-IP cliff determines eligibility by itself.
- Missing values remain missing. They are never encoded as league average or
  zero without an explicit registered imputation study.
- All variants and one primary endpoint are registered before the first result
  look. Additional variants require a new registration and multiplicity plan.
- Public superiority remains governed by plan 032's global hard floor: at least
  three completed cohorts, 150 unique players, 90% coverage, 5% relative
  improvement, a cohort-aware paired 95% interval excluding no difference, and
  no cohort or role segment more than 5% worse. The registered prospect track is
  stricter at 250 unique players. The registered pitcher track requires only 30
  players for its research result, so it cannot authorize a public
  industry-standard claim under the current 150-player global floor. A pitcher
  claim remains impossible unless a future pre-registered track raises its
  common-pool floor to at least 150 and satisfies every other gate.
- The challenger registration uses fresh seed `33021`. It must never reuse the
  burned or held seeds `28013`, `28017`, `29001`, `31013`, or `31017`.
  Any later re-registration requires another previously unused seed.

## Edge cases and failure behavior

- Two-way players are not evaluated until workstream 2's identity policy is
  registered. Conflicting role rows fail the affected cohort closed; later role
  changes are disclosed rather than silently duplicated.
- Promotion and demotion are distinct observations. Direction cannot be
  inferred when dated ordering is unavailable.
- The input contract records 2020 as omitted because there was no affiliated
  Minor League Baseball season; the evaluator therefore has no 2020 fold. That
  is a data-contract fact, not a registered sensitivity exception. The study
  does not promise a free with/without-2020 view; adding such a view requires
  registration inside the same multiplicity budget before any result look.
- Post-2021 level reorganization prevents a single timeless level coefficient.
- Small same-level cells back off only to the registered same-role,
  same-season input pool. If that pool is also too small, the normalized row is
  unavailable and the coverage gate decides whether the variant can be scored.
- Pitcher skill and opportunity remain separate. Strong AAA pitch traits do
  not imply starter volume, health, or MLB innings.
- Max exit velocity and rare pitch-shape observations require reliability
  disclosure and cannot dominate a score from one observation.
- An unavailable required archive, hash mismatch, altered sealed file, or
  incomplete test population fails the run closed.

## Verification

The minimum sufficient automated checks prove:

- documentation and live artifact contracts cannot drift silently;
- readiness blocks when QS, coverage, cohort, role, or replay requirements are
  not met;
- test-cohort outcomes cannot affect training-fold references;
- the dated MiLB archive is deterministic and immutable;
- missing AAA Statcast values never become zero;
- starter and reliever reports remain separated;
- no challenger or audit artifact is imported by ranks, values, caps, Role
  Watch, or publication decisions;
- all frozen flags retain their existing values; and
- the full repository suite passes before any branch is proposed for merge.

## Delivery order

1. Documentation contract reconciliation.
2. Realized-value readiness audit.
3. Fold-local partial-impact evaluator contract and registered two-way identity
   policy.
4. Compact dated MiLB observation archive and explicitly authorized
   daily-build allow-list integration.
5. Register seed `33021`, the Control, the cutoff-available quantile challenger,
   all ablations, and the single-look multiplicity contract before execution.
6. AAA current-population disagreement report.
7. Promotion and realized-value variants only after their data gates pass.

Each deliverable is a separate logical commit. No deploy is dispatched by this
work.

## Non-goals

- No live model retrain or rank/value change.
- No pitcher publication-cap change.
- No change to the failed pedigree-decay or cross-role flags.
- No proprietary public Skill+ metric.
- No exact historical-board claim from a pseudo-universe.
- No public competitor names or source identities.
- No feature added solely because another product displays it.
