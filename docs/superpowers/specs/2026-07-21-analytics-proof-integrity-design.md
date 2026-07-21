# Analytics Proof Integrity Design

**Date:** 2026-07-21  
**Status:** Approved direction; implementation may proceed  
**Scope:** Truth contracts and research-only evaluation hardening

## Objective

Make ValuCast's evidence layer as credible as its product layer without changing
the frozen prospect model, live ranks, dynasty values, pitcher caps, Role Watch,
publication decisions, or the failed pedigree-decay flag.

This design adds the senior-statistical findings to the existing proof roadmap.
It does not reopen formula defects already fixed on `master`.

## Reconciliation With Completed Work

The following 2026-07-21 audit findings are already shipped and are not part of
this implementation:

- signed dynasty multipliers no longer improve negative values;
- playing-time reliability is no longer compounded as annual talent decline;
- card skill grades use MLB-equivalent sticky peripherals;
- combined hitter slash lines reconstruct rates honestly;
- even-sized comp cohorts use the true median;
- 2020 PA scaling affects opportunity tiers but not rate weights;
- scoreboard verdicts use the exact sign test and fail closed; and
- Front Office next-build guidance is computed from current evidence.

## Immediate Workstream 1: Prospect Artifact Truth Contract

The incumbent model keeps `status: shadow_only` because that status is an
established provenance convention. The generated artifact must nevertheless
state how it is actually consumed:

- Prospect Rank v1 consumes `model_score` from this artifact;
- the live blend weight is `0.76`;
- the artifact itself is not the final public board; and
- pooled-line shadows and v0.7 remain non-live.

Replace the false limitation, "never consumed by the live prospect board," with
an explicit `release_contract`. Add a limitation stating that the current
partial-impact walk-forward gate used full-store percentile references and is
therefore descriptive until a fold-local replay is completed. This is metadata
only; all scores, predictions, gates, and ranks remain unchanged.

## Immediate Workstream 2: Honest Cross-Universe Semantics

The snapshot currently labels a no-mutation compatibility check as
"calibration." That overstates what happened. MLB and prospect values remain
independently normalized inputs displayed on one 0-100 axis.

The corrected contract will distinguish:

- `compatibility_certified`: the current freshness, identity, coverage, and
  top-prospect rank-band checks passed;
- `unit_mapping_applied: false`: no transformation reconciled the two source
  distributions; and
- `value_units_calibrated: false`: equal numeric values are not empirically
  proven to represent equal dynasty value across the two universes.

The existing compatibility check may continue to gate snapshot readiness. The
legacy validation field `cross_universe_value_scale_calibrated` becomes false,
while a new `cross_universe_value_scale_compatibility_certified` field carries
the readiness fact. Player values, ordering, dollars, and surface readiness must
be byte-for-byte unchanged.

## Immediate Workstream 3: H+P Suitability Diagnostics

The forward Steamer comparison is already repaired and must not be rewritten.
It currently trails Steamer and correctly holds publication. The H+P run also
correctly holds a public Skill+ metric when remaining opportunity reaches zero
or is clamped.

Strengthen the manifest by reporting, separately for hitters and pitchers:

- actuals match count and rate;
- positive remaining-opportunity count and rate;
- zero remaining-opportunity count and rate; and
- clamped-to-zero count and rate.

The public Skill+ gate remains fail-closed if any zero or clamp condition is
present. It stays display-only and cannot affect live outputs.

## Research Workstream 4: Fold-Local Impact Evidence

Do not alter the live impact model or rerun spent plan 033. Build a separate,
research-only incumbent audit that:

- constructs impact percentile references from training identities in each
  walk-forward fold only;
- applies each frozen reference set to that fold's training and test targets;
- records reference counts, categories, hashes, player identities, and fold
  boundaries;
- publishes paired model-versus-baseline errors by player and cohort; and
- attaches a deterministic cohort-then-player bootstrap interval.

The report is descriptive and cannot promote a model or authorize a public
claim. If it disagrees with the served impact gate, the served gate is labeled
uncertified; no score or rank is changed.

## Registered Post-2026 Queue

The remaining formula findings are challenger hypotheses, not bug-fix license.
They enter one post-2026 epoch registration with fresh seeds and a declared
multiplicity plan:

- tune ridge regularization within training folds;
- replace or strengthen the high-dimensional unweighted k=25 gate baseline;
- test residualized or out-of-fold stacked rank components;
- test a corroborating investment blend instead of `max(draft, bonus)`;
- test training-fold quantile or link-function target scaling;
- align train-time and serve-time shrinkage;
- compare multiplicative confidence haircuts with the incumbent;
- use uncertainty-aware cohort/segment regression guards;
- audit the asymmetric buy-momentum prior; and
- test a genuine cross-universe value mapping against the current
  compatibility-only display.

No result from this queue may be run before registration. Pitcher and hitter
results remain separate. The existing pitcher-publication veto remains intact.

## Verification Contract

The implementation must prove:

- prospect model predictions and every live rank input are unchanged;
- public snapshot player values, ranks, dollars, and readiness are unchanged;
- cross-universe metadata no longer claims calibrated units;
- H+P diagnostics reconcile exactly to role row counts;
- all new evidence artifacts are research-only and have no production importer;
- frozen flags and publication thresholds are unchanged; and
- focused and full automated suites pass.

## Delivery Order

1. Prospect artifact truth contract.
2. Cross-universe compatibility semantics.
3. H+P suitability diagnostics.
4. Fold-local impact audit in a separate commit and review checkpoint.
5. Register post-2026 challengers only after the impact audit is reviewed.

