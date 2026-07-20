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

Any missing required category, insufficient coverage, current-state input, or
unknown status blocks `realized_value_regret`. It does not silently substitute
an ordinal outcome or partial-category score.

Output is a validation artifact only. It cannot be imported by production
scoring code.

### 3. Correct target construction in the challenger evaluator

Do not modify the frozen incumbent model. The registered challenger evaluator
must calculate every normalization and target reference from the training
fold only, then apply those frozen references to the test cohort.

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

### 5. Register one shadow breakout-ranking challenger

The challenger is private, research-only, and has no production importer. It
uses the same eligible players and outcome rows as the incumbent comparison.
Hitters and pitchers are fitted and reported separately.

Registered variants are deliberately limited:

1. **Control:** incumbent historical feature contract and evaluator.
2. **Normalized production:** training-fold-only level-by-season residuals for
   the existing component rates. This is structurally different from the
   failed additive fitted-level translation and must not rerun that dead form.
3. **Combined:** normalized production plus promotion information, but this
   variant remains unavailable until the prospective archive contains enough
   dated transitions for the registered sample and cohort floors.

The following are reports or ablations, not bundled scoring features:

- an under-19/full-season-minors subset report;
- hitter position only if historical position semantics pass their own data
  audit; and
- AAA Statcast disagreement on the same eligible current AAA population.

AAA Statcast is never filled with zero when missing, extrapolated below AAA,
or trained against outcomes until multiple dated vintages have matured. The
first version uses measured components rather than a hand-built Stuff or Skill
index.

The existing v0.7 heuristic preview may be reported as a baseline. It is not a
second promotion candidate.

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
- Public superiority remains governed by plan 032: at least three completed
  cohorts, 150 unique players, 90% coverage, 5% relative improvement, a
  cohort-aware paired 95% interval excluding no difference, and no cohort or
  role segment more than 5% worse.

## Edge cases and failure behavior

- Two-way players are evaluated once per registered identity policy; role
  changes are disclosed rather than silently duplicated.
- Promotion and demotion are distinct observations. Direction cannot be
  inferred when dated ordering is unavailable.
- The 2020 season remains a declared exceptional cohort; results are reported
  with and without it when the registered test permits that sensitivity view.
- Post-2021 level reorganization prevents a single timeless level coefficient.
- Small level-season cells fall back to the incumbent rate representation; the
  fallback count is reported.
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
3. Fold-local shadow evaluator contract.
4. Compact dated MiLB observation archive and daily-build integration.
5. Registered control and normalized-production challenger.
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
