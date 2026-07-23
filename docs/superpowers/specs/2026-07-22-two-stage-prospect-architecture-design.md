# Two-Stage Prospect Architecture Design

Date: 2026-07-22
Status: approved design; implementation not started

## Decision

Expand the existing prospect architecture into two explicit layers. Do not
replace the current models and do not introduce a second fitted fantasy model.

1. **Stage 1 — real baseball outcomes:** predict MLB arrival, sustained
   opportunity, role, and realized production.
2. **Stage 2 — fantasy translation:** translate promoted Stage 1 forecasts plus
   current opportunity into format-specific ranks and values.

Research artifacts cannot affect either live layer. A challenger must earn
promotion through the registered Stage 1 process before Stage 2 can consume it.

## Existing seams to reuse

- `prospects/universal.py` already defines role-specific outcome targets:
  established, regular/rotation, star, representative playing time, and
  representative production.
- `prospects/model.py` already produces the incumbent v0.6 player profiles.
- `prospects/dynasty.py` already translates universal outcome distributions
  into rank-free, value-free decision signals.
- `prospects/rank_v1.py` already combines model outcomes, category impact,
  opportunity context, reliability, and deterministic ranking inputs.
- Existing walk-forward, cluster-bootstrap, coverage-gate, archive, and
  fail-closed governance utilities remain authoritative.

The first implementation slice adds a validated contract over these seams. It
does not create another prediction system or duplicate their calculations.

## Architecture

```text
MiLB evidence + cutoff-safe context
                |
                v
     Stage 1 real-baseball profile
                |
       promoted artifact only
                |
                v
 Stage 2 deterministic fantasy translation
                |
                v
       format-specific ranks/values
```

Stage 1 owns baseball forecasts. Stage 2 owns league and fantasy decisions.
Raw challenger features cannot bypass Stage 1 and enter Stage 2.

## Stage 1 contract

Each profile is keyed by `(mlbam_id, role)` and includes:

- identity and role;
- evidence cutoff and generated timestamp;
- source model and artifact versions;
- established and star probabilities;
- regular probability for hitters or rotation probability for pitchers;
- representative PA/IP and role-appropriate production rates;
- confidence, sample reliability, coverage, and provenance; and
- promotion state: incumbent, research, shadow, or promoted.

The contract initially adapts the existing v0.6 and universal/dynasty outputs.
It should not persist a third duplicate model artifact unless implementation
proves that a materialized boundary is required. Schema validation belongs at
the adapter boundary.

### Role meanings

For hitters:

- established: at least one post-cohort 300-PA MLB season;
- regular: at least one post-cohort 450-PA MLB season;
- star: at least one post-cohort 450-PA, .800-OPS MLB season; and
- production: representative PA, AVG, OPS, HR, R, RBI, SB, and K rate.

For pitchers:

- established: at least one post-cohort 50-IP MLB season;
- rotation: at least one post-cohort 120-IP MLB season;
- star: at least one post-cohort 120-IP season with a 3.75 ERA or better; and
- production: representative IP, ERA, WHIP, strikeout, walk, and workload
  outcomes already registered in the universal target contract.

These definitions remain unchanged in the architecture migration. Any target
revision is a separately registered challenger.

## Stage 2 contract

Stage 2 consumes only:

- a promoted Stage 1 profile;
- timestamped current role, availability, and expected opportunity;
- league categories and format;
- replacement level and positional scarcity; and
- deterministic auction/value rules.

Stage 2 may remain deterministic. It does not need a fitted model unless a
future registered study proves that one improves realized fantasy decisions.

The existing direct investment component remains frozen during the contract
migration. It receives a separate Stage 2 ablation before it may be retained,
moved into Stage 1, or removed. The migration itself must produce no ranking or
value changes.

## Front-office baselines

Stage 1 challengers are compared with four reconstructable alternatives:

1. the current Stage 1 incumbent;
2. acquisition investment alone, including draft position or international
   signing bonus when contemporaneously known;
3. organizational decisions known at the evidence cutoff, including current
   level, promotion pace, assignment, and roster protection; and
4. a combined acquisition-and-organizational baseline.

There is no opaque aggregate "front-office score." Each baseline remains
separately reported so its contribution is measurable.

Only facts available at the prediction cutoff are eligible. A promotion,
roster decision, assignment, injury update, or signing fact first known after
that cutoff is future information and must be excluded from the fold.

## Validation and promotion

Hitters and pitchers are evaluated separately using walk-forward cohort folds.
Each challenger receives one registered primary look and the existing
role-specific coverage gates. Secondary production targets do not influence a
role decision when their aligned sample is below the registered minimum.

Allowed statuses are:

- `insufficient_data`;
- `validated_underperformance`;
- `no_clear_improvement`;
- `shadow_candidate`; and
- `promotion_eligible`.

A challenger becomes `shadow_candidate` only when it:

- clears every coverage and reconstructability gate;
- improves aggregate primary arrival/role error versus the incumbent;
- adds value beyond the combined front-office baseline; and
- causes no material regression in any registered development fold.

Promotion additionally requires stable dated shadow evidence and a favorable
cluster-bootstrap interval on the primary outcomes. Promotion changes only the
Stage 1 artifact. Stage 2 then rebuilds through its existing deterministic
path. Public superiority claims use the separate claim-governance threshold
and are never implied by model promotion.

## Failure behavior

- An invalid, stale, identity-conflicted, or wrong-role Stage 1 profile cannot
  enter Stage 2.
- Stage 2 falls back to the last promoted Stage 1 artifact, never a research
  artifact and never a zero-filled profile.
- Missing coverage produces an explicit hold; it is not treated as evidence of
  failure or success.
- Hitter evidence cannot satisfy a pitcher gate, or vice versa.
- Sealed cohort outcomes remain inaccessible during development evaluation.
- Current availability remains separately timestamped so it cannot rewrite the
  historical evidence cutoff.

## Delivery sequence

1. Add the Stage 1 adapter and schema validator around existing artifacts.
2. Route Stage 2 through the adapter without changing calculations.
3. Prove exact per-player rank, score, and value parity.
4. Add acquisition-only, organization-only, and combined baseline evaluators by
   reusing the current walk-forward harness.
5. Add challenger registration and research-only result artifacts.
6. Run the direct-investment Stage 2 ablation as an independent study.
7. Consider promotion only after the registered development and shadow gates.

## Verification

The first slice must demonstrate:

- exact pre/post migration parity for every published rank and value;
- deterministic Stage 1 contract output;
- complete MLBAM-plus-role identity reconciliation;
- rejection of wrong-role, stale, malformed, and post-cutoff inputs;
- fail-closed fallback to the last promoted artifact;
- sealed-cohort and feature-path isolation;
- unchanged model-freeze and failed-decay flags; and
- the complete automated regression suite passing.

No browser or public-copy work is required because this scope changes no live
surface.

## Non-goals

- No replacement prospect model.
- No fitted Stage 2 model.
- No live ranking, value, cap, Role Watch, or publication change.
- No relaxed sample, power, or claim threshold.
- No competitor-specific optimization or public comparison language.
- No League Connect work.

## Success condition

The architecture is complete when Stage 2 receives the same information and
produces byte-equivalent decisions through a validated Stage 1 boundary, while
registered challengers can be evaluated and promoted without any research path
reaching live ranks or values.
