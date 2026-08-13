# Stage 1 Outcome Proof Design

**Date:** 2026-08-04
**Status:** Approved
**Scope:** Evaluation and reporting only. No scoring, ranking, value, publication-cap, Role Watch, or pitcher-veto change.

## Goal

Turn ValuCast's existing real-baseball prospect model into an inspectable,
versioned proof surface without creating a new model or borrowing another
product's branding.

The scorecard must answer four questions:

1. Does Stage 1 order prospects by later MLB outcome?
2. Does Stage 1 distinguish players who become MLB contributors?
3. What MLB outcomes actually occur in each Stage 1 evidence band?
4. Do ValuCast's largest frozen disagreements perform differently from its
   ordinary calls?

Stage 2 remains the separate league-specific fantasy translation. Nothing in
this scorecard feeds Stage 2.

## Selected Approach

Extend the existing Stage 1 and Forward Ledger evidence contracts.

Rejected alternatives:

- A new public 20-80 grade: duplicates an established scouting convention and
  adds no evidence.
- A separate retrospective benchmark system: duplicates the committed OOF,
  reliability, and claim-time audit machinery.
- Competitor-named comparisons: depend on unavailable calculation details and
  weaken the source-neutral proof standard.

## Existing Evidence Reused

- `data/models/valucast_outcome_oof_scores.json`: fold-trained, out-of-fold
  Stage 1 predictions, factual outcomes, level-age prior, and historical-neighbor
  baseline.
- `data/models/valucast_probability_reliability.json`: within-role equal-count
  score bands and Wilson intervals.
- `data/models/valucast_prospect_dynasty_backtest.json`: versioned historical
  gate and cohort contract.
- `data/models/valucast_forward_cohort_registry.json`: append-only forward
  cohorts.
- `scripts/audit_consensus_decisions.py`: exact claim-time joins and the frozen
  disagreement bins `25-49`, `50-99`, `100-199`, and `200+` ranks.

No historical result is recomputed with today's model. No current rank may
replace a claim-time rank.

## Outcome Contract

The fixed horizon is four years after the cohort season.

| Actual outcome | Hitter | Pitcher |
|---|---|---|
| Star | Any season with at least 450 PA and .800 OPS | Any season with at least 120 IP and ERA at most 3.75 |
| Role | Any season with at least 300 PA, without a Star season | Any season with at least 50 IP, without a Star season |
| Bust | Neither threshold reached | Neither threshold reached |

For contributor discrimination, `contributor = Role or Star`. This is a
factual horizon outcome, not a scouting label or published player probability.

## Scorecard Metrics

### 1. Ordering skill

Report Spearman rho and Kendall tau-b between the frozen Stage 1 score and the
realized ordinal outcome (`Bust=0`, `Role=0.5`, `Star=1`). Report the same
metrics for the level-age prior and historical-neighbor baseline on the exact
matched rows.

Realized WAR ordering remains reserved until the already-registered WAR
ingestion path exists. No WAR-accuracy claim may use the ordinal target as a
substitute.

### 2. Contributor discrimination

Report ROC AUC for the frozen Stage 1 score against `Role or Star`. AUC measures
ordering discrimination; it must never be described as probability
calibration. Report the contributor base rate beside it.

### 3. Stage 1 evidence bands

Reuse the existing within-role equal-count deciles. Do not invent a 20-80
scale, public per-player probability, or new player grade.

For each decile report:

- sample size;
- observed Bust, Role, and Star shares;
- observed contributor rate with Wilson 95% interval; and
- score range.

These tables define what each Stage 1 evidence band has historically implied.
The band number is an ordering bucket, not a probability.

### 4. Frozen disagreements

Use only registered claims joined to their dated claim-time archive. Preserve
the existing initial-gap bins: `25-49`, `50-99`, `100-199`, and `200+` ranks.

Report the whole funnel for each eligible bin: open, resolved, censored,
retracted, moved toward ValuCast, and moved away. Cells below 10 remain
insufficient; cells from 10 through 19 remain descriptive only. This view is a
diagnostic slice and cannot change score thresholds, public claim eligibility,
or model features.

## Required Splits

Every historical metric is reported for hitters and pitchers separately.
An optional combined row may appear only after both role rows and must carry
their sample sizes.

Pitcher starter/reliever role, conversion probability, availability, and
volatility remain outside this scorecard. They stay in the existing
pitcher-role research lane and cannot be blended into a flattering combined
number.

## Uncertainty and Censoring

- Report raw cohort counts and resolved/unresolved/censored counts.
- Use 10,000 player-clustered bootstrap resamples for 95% intervals on rho,
  tau-b, and AUC. The seed and model/input hashes are serialized.
- Report every closed test cohort separately before the pooled result.
- Never publish a resolved-only headline without the whole-funnel denominator.
- No comparative superiority wording is authorized unless the matched delta's
  95% interval excludes zero, at least three closed test cohorts are present,
  and the minimum matched sample is 250 for the reported role.
- Otherwise label the result `descriptive` or `collecting`.

## Version and Provenance

Each result records:

- Stage 1 model version;
- rank/calibration version when applicable;
- outcome-contract version;
- input artifact paths and SHA-256 hashes;
- evaluation date and mature-through cohort;
- metric definitions, bootstrap seed, and censoring counts.

Existing forward cohort `2026-07-16` remains governed by Plan 030 and is not
backfilled or role-sliced. A new registration is required before any future
forward cohort freezes Stage 1 scores, roles, or evidence bands. Registrations
are append-only; daily builds must not create them automatically.

## Output Boundary

The first implementation produces one research artifact and one human-readable
report from the same payload. Public presentation, if later authorized, is a
source-neutral Stage 1 scorecard with no competitor names and no individual
public-source ranks.

The artifact is fail-closed when inputs, hashes, cohort coverage, or outcome
resolution do not reconcile. It is forbidden from serving imports and must
declare that it feeds no score, rank, value, buy signal, Role Watch output, or
pitcher publication decision.

## Tests

Minimum contract checks:

- exact reproduction from committed inputs;
- no current-model or current-rank substitution;
- AUC target is exactly `actual outcome > Bust`;
- evidence bands cover every matched row exactly once within role;
- hitter and pitcher counts reconcile to the full matched population;
- disagreement rows join exactly once to claim-time archives;
- censored and unresolved rows remain in the funnel;
- no per-source rank or competitor name enters the result; and
- mutation of the result cannot change any production score, rank, or value.

## Non-Goals

- No eFV, FV, WAG, or 20-80 clone.
- No new prediction model or feature.
- No Plan 034 execution or outcome look.
- No Plan 035 pitcher-skill look.
- No historical backfill of frozen forward cohorts.
- No public superiority claim from retrospective evidence alone.
- No change to the model freeze or failed-decay flag.

## Delivery Order

1. Build and validate the retrospective scorecard only from committed OOF and
   reliability artifacts.
2. Review the numbers and wording before exposing any public surface.
3. Draft a separate prospective registration for future Stage 1 cohort fields.
4. Let the first prospective proof mature under its frozen rules.
