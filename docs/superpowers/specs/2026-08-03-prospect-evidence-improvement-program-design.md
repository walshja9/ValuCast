# Prospect Evidence Improvement Program Design

**Date:** 2026-08-03
**Status:** Approved concept; written specification awaiting owner review
**Scope:** Prospect Stage 1 evidence, research-only challengers, and model-independence guards

## Goal

Improve ValuCast's prospect forecasts without moving the live board toward
consensus by construction. Repair factual coverage first, then test whether
better translations, development context, and ValuCast-owned pitch evidence
improve out-of-sample baseball forecasts. Only a promoted Stage 1 forecast may
flow through the existing deterministic Stage 2 fantasy translation.

The current lower-than-consensus cohort motivates the work but does not select
player-specific fixes. Of 40 current lower-side disagreements, 13 carry missing
investment context, 13 carry an explicit evidence/calibration adjustment, and
7 carry an availability adjustment. These groups overlap. The field comparison
is diagnostic only and never becomes a training target.

## Standing boundaries

- Prospect Rank v1 remains frozen at bucket calibration `0.3.2`.
- The failed pitcher-decay flag remains disabled.
- The pitcher publication veto, pitcher cap, Role Watch, holds, ranks, values,
  buy signals, and public claims remain unchanged during this program.
- External rankings, scouting grades, market prices, competitor outputs, and
  current ValuCast rank are prohibited model inputs.
- Raw challenger features may enter only Stage 1. Stage 2 consumes only a
  promoted Stage 1 contract plus timestamped opportunity and league rules.
- No Plan 033 rerun is authorized. Plan 034 remains blocked until its registered
  post-2026 trigger and reviewed pre-look amendment.
- No Stockyard code, score, private data, formula, label, or branded metric is
  copied. Public baseball concepts may be implemented independently from
  public factual data under ValuCast-owned names, code, targets, and validation.
- A negative, inconclusive, or underpowered result is a completed result.

## Approaches considered

### 1. Modular evidence repair plus registered challengers — selected

Keep the incumbent live. Ship factual corrections only after exact board
previews and explicit approval. Build translation, context, and pitch-evidence
work as isolated shadow challengers that must beat the incumbent on untouched
outcomes before promotion.

This preserves attribution: we can tell whether a change came from better data,
better baseball forecasting, or fantasy translation.

### 2. Add every promising signal to Rank v1 — rejected

This would double-count production and investment, mix missingness with talent,
and let current disagreements choose the formula. It would also bypass the
Stage 1/Stage 2 contract and invalidate existing evidence.

### 3. Blend ValuCast with consensus or scouting grades — rejected

This would mechanically reduce disagreements while destroying the independent
opinion ValuCast is trying to prove. Consensus and scouting remain comparison
baselines and display context only.

## Workstream 1 — factual coverage and opportunity repair

### 1A. Investment coverage

Reuse the existing verified-investment contract and coverage audit. Add a
deterministic missing-evidence queue keyed by `mlbam_id:role` with acquisition
type, known draft facts, current source coverage, and the reason evidence is
missing. The queue contains no inferred dollar values.

New facts must include source URL, source name, checked date, acquisition type,
and a positive verified amount or draft slot. Duplicate, conflicting,
unmatched, or unsupported facts fail closed. Source-backed corrections produce
a rank-local candidate preview using the existing formula; they do not retrain
v0.6 or the universal model.

The preview must report:

- identities corrected and still missing;
- direct score/value changes and ordinary displacement effects;
- top-25, top-50, and top-100 composition changes;
- exact byte parity for v0.6 and universal artifacts; and
- whether any corrected player was in the current disagreement cohort.

Publication of a factual correction requires a separate owner approval after
independent review. Any change to the missing-evidence fallback or its weight is
a model change reserved for Plan 034, not a factual correction.

### 1B. Availability, role, and current evidence

Extend the existing coverage audit rather than add a second availability
system. For every adjusted lower-side disagreement, record the timestamped
status source, current-season sample, chosen display row, adjustment reason,
and whether the condition is missing evidence, stale evidence, managed return,
injury/inactivity, or genuine limited workload.

The audit must distinguish `unknown` from `negative`. It may correct a factual
status or stale join. It may not change a penalty, threshold, precedence rule,
or score. A counterfactual table may show the isolated adjustment magnitude,
but it remains internal and cannot feed publication.

## Workstream 2 — translation readiness for the next prospect epoch

Do not reopen the invalid and spent Plan 033 normalized-production look.
Instead, prepare Plan 034's pre-look implementation boundary without scoring an
outer cohort:

- retain factual raw-unit fields for every heuristic and guard;
- expose normalized or linked features only to the fitted model interface;
- fit every reference, imputation, shrinkage rule, and transform on training
  identities inside each fold;
- preserve exact `mlbam_id:role` identities, including two-way players;
- keep hitter and pitcher results separate; and
- report AAA Statcast coverage and missingness without zero filling.

The readiness artifact may validate schemas, identities, coverage, and
reconstructability. It must refuse to calculate comparative outer-fold
outcomes before Plan 034's `2027-01-01` trigger and reviewed amendment.

Current AAA Statcast evidence may support display and future archival coverage.
It cannot be projected backward into historical seasons where it did not exist,
and it cannot rescue a failed historical gate.

## Workstream 3 — registered development-context challengers

Implement only the two definitions frozen in
`docs/registration-2026-07-29-outcome-feature-challengers.md`:

- `development_density`: hitter PA/game and season share; pitcher IP/game; and
- `position_value_x`: the registered hitter position, youth, and level
  interactions.

No new variant, position table, missing-value rule, or feature order is allowed.
The implementation initially runs in readiness mode only. Before any
confirmatory outcome scoring, an independent review must verify that the
registered fresh-cohort condition is genuinely untouched and mature. If it is
not, the challenger remains implemented but unspent.

Real injury-adjusted development time is a later replacement challenger, not
an alias for density. It requires cutoff-safe historical IL transactions and a
new registration before use. Defense and athleticism remain unmodeled unless a
reconstructable historical source and separate registered hypothesis exist.

## Workstream 4 — ValuCast pitcher-skill challenger

Use the existing `codex/mlb-pitcher-skill-challenger` branch as the candidate
implementation. Do not rewrite it and do not merge it directly.

The branch independently implements public MLB Statcast pitch evidence as a
fold-local correction to the frozen pitcher projection. It predicts next-season
K/BF and BB/BF at fixed opportunity and reconstructs ERA/WHIP only inside the
research evaluator. Shape, location/execution, and arsenal are descriptive
feature families inside one registered look, not three marketable models.

Before integration:

1. rebase it onto current `origin/master` without resolving substantive model
   conflicts by guesswork;
2. verify registration commit precedes acquisition and all result inspection;
3. verify compact source provenance, MLBAM identity, position-player pitching
   exclusion, pitch-label mapping, location geometry, fold-local transforms,
   exact incumbent fallback, target alignment, role slicing, and gate math;
4. prove no result artifact exists and the registered look remains unspent;
5. prove no serving, projection, rank, value, workflow, or publication importer
   can reach the challenger; and
6. obtain an independent Fable review before any look is spent or branch is
   merged.

The work is methodology-inspired only. Public naming, if later earned, will be
ValuCast terminology rather than Stockyard terminology. A retrospective pass
would authorize only a 2026 prospective shadow; it would not authorize a live
projection, public metric, or superiority claim.

## Workstream 5 — independence enforcement

Reuse the existing prohibited-input and artifact validators. Add the smallest
contract coverage needed to prove that these fields cannot reach Stage 1
training, Stage 2 scoring, ranks, values, or challenger targets:

- source-level and aggregate consensus ranks;
- public scouting/FV/tool grades;
- competitor model names, scores, labels, and outputs;
- market/dynasty values; and
- current ValuCast order.

Consensus remains eligible for three uses only: aggregate display context,
claim-time accountability, and source-neutral evaluation after a prediction is
frozen. Scouting grades may be reported as a benchmark but never used to rescue
a challenger gate.

## Data flow

```text
verified factual evidence
        |
        +--> rank-local factual preview (owner-approved corrections only)
        |
        v
historical cutoff-safe Stage 1 inputs
        |
        +--> incumbent Stage 1 -------------------------+
        |                                               |
        +--> translation/context/pitch challengers      |
                         |                              |
                  research artifacts only               |
                         |                              |
             registered promotion review                |
                         |                              |
                         +--> promoted Stage 1 contract-+
                                                        |
                                                        v
                              deterministic Stage 2 league value

consensus/scouting/competitor outputs --> display and evaluation only
```

## Error handling and auditability

- Missing or conflicting factual evidence stays missing and is disclosed.
- Stale status data cannot silently become an injury or talent penalty.
- Missing challenger coverage falls back exactly to the incumbent.
- Invalid identities, future information, test-fold references, changed
  registrations, or result-path reuse stop the research run.
- Every research artifact carries `research_only: true`,
  `feeds_rank_or_value: false`, `feeds_pitcher_publication: false`, and
  `claim_eligible: false` unless a later protocol explicitly changes them.
- No raw third-party ranking rows, proprietary formulas, or player-level
  challenger predictions are published.

## Delivery sequence

1. Build the combined coverage/availability diagnostic and source-backed
   investment queue.
2. Produce any factual-correction preview; hold publication for approval.
3. Add the no-outcome Plan 034 translation-readiness validator.
4. Implement the already-registered development-context features behind a
   readiness-only runner; do not score outcomes before independent review.
5. Rebase and adversarially review the existing pitcher-challenger branch;
   repair defects test-first while keeping the look unspent.
6. Add/verify model-independence contract tests across all new paths.
7. Run focused and full regression tests and generate a Fable review packet.

Each numbered step is independently reviewable. Failure in one challenger does
not block factual repairs or authorize another challenger look.

## Testing contract

Tests must prove:

1. verified investment facts are deterministic, idempotent, conflict-failing,
   and isolated from trained model artifacts;
2. opportunity diagnostics preserve timestamps and distinguish missing, stale,
   limited, unavailable, and available states;
3. translation readiness performs no outer scoring and keeps raw-unit guards
   separate from model transforms;
4. development-context features exactly match their frozen registration and
   cannot run an unreviewed confirmatory look;
5. pitcher challenger preprocessing, targets, folds, fallback, gate, and result
   boundaries match its registration;
6. prohibited external fields cannot enter any scoring or training interface;
7. the current live rank, value, cap, Role Watch, failed-decay flag, and pitcher
   publication behavior remain unchanged; and
8. full repository tests and `git diff --check` pass before handoff.

## Success condition

The program succeeds when ValuCast has:

- a source-backed path to eliminate avoidable factual gaps;
- an auditable explanation for every evidence-driven lower-side adjustment;
- implementation-ready, leakage-safe translation and development challengers
  that have not spent unavailable future evidence;
- an independently reviewed ValuCast pitcher-skill challenger with its
  retrospective look still unspent until separately authorized; and
- executable proof that consensus, scouting grades, and competitor outputs
  remain score-inert.

No live ranking change is required for this program to succeed. A model change
occurs only after the relevant registered evidence and separate promotion
decision support it.
