# Prospect Rank vNext Current-Board Design

**Status:** OWNER-APPROVED DIRECTION - option 1, 2026-08-20

**Baseline:** `e48360faddab5504638324f70cddae25f7b7bc65`

**Supersedes:** the unmerged policy-only proposal at `411a3d6a`. That proposal
would have retained Prospect Rank v1 and made its pitcher-count check
observe-only. It will not be implemented.

## Decision

Replace Prospect Rank v1 with a materially better combined hitter/pitcher
board. A successor may become the current public board after it passes a
predeclared known-data combined-board screen, passes the complete publication
pipeline, receives independent review, and receives explicit owner approval.

Passing a pitcher-only test, satisfying a pitcher quota, or receiving owner
approval cannot substitute for the combined-board evidence. "No matter what"
governs release: v1 is temporary, but a failed candidate cannot replace it.

## Evidence and product status

These are separate facts:

- `development_qualified` is a field in the frozen candidate receipt. It means
  every known-data gate below passed. It is not a new site badge or a registry
  verdict.
- `CURRENT` means the daily build and product routes use that exact lineage.
- `PROVISIONAL` is the scientific registry verdict while forward confirmation
  is pending.
- `VALIDATED` is reserved for the separately registered finalized-2022
  confirmation.

A development-qualified board may be current before it is validated. Public
methodology must name the known-data evidence and the pending confirmation. A
passing board must not be mislabeled `Preliminary`, but it also must not be
called `VALIDATED` early.

## Temporary incumbent and cutover

V1 remains the current board only while its replacement is developed. It gets
no policy-only promotion and no relaxed accuracy gate. At cutover:

- v1 becomes immutable, reproducible history and stops feeding current rank;
- every production current-rank consumer moves atomically to vNext;
- v1 and vNext histories remain separate; and
- vNext movement, buy, streak, and receipt claims start from a new epoch.

If a candidate fails, its result is frozen and that candidate stops. V1 remains
the temporary incumbent while a separately designed candidate is considered.

## First candidate: v2.3

V2.3 tests the narrow hypothesis left by v2.2:

- preserve the supported v1 hitter ladder exactly;
- use the exact frozen v0.9 pitcher ladder;
- discard v2.2's failed shared-slope cross-role map; and
- fit one monotone joint Bust/Role/Star calibration with shared thresholds,
  separate positive hitter and pitcher slopes, and one finite pitcher offset.

There is no role quota, player name, player identity, market rank, consensus
rank, current public rank, fantasy value, or governor result in fitting.

The local research commits `027a6efa` and `1201b799` are design inputs, not
release authority. Their 40-commit branch must never be merged or replayed
wholesale. Implementation may transplant only the reviewed frozen dependency
closure and terminal receipts onto current master, reusing current-master
helpers. Every transplanted source and artifact is hash-bound.

Before any v2.3 execution, the exact amended contract must be merged to master.
It preserves the old five-parameter hypothesis and three folds but supersedes
the role quota as an accuracy gate, the pre-2027 publication ban, and the old
crash-spend wording. It also adds direct v1 product-logic ordering and top-25 checks
plus predeclared pooled uncertainty bounds.

## Fixed calibration family

Reuse `_fit_ordered_logit`, `_ordered_probabilities`, and `_expected_tier` from
`prospects/ordinal_calibration_power.py`. Do not add another optimizer.

For each role `r`, fit a training-only mean `mu_r` and strictly positive
standard deviation `sigma_r`. For row `i`:

```text
z_i = (ladder_score_i - mu_role(i)) / sigma_role(i)

eta_i = beta_hitter * z_i * is_hitter_i
      + beta_pitcher * z_i * is_pitcher_i
      + gamma * is_pitcher_i

tau_role_star = tau_bust_role + exp(log_gap)
params = [tau_bust_role, log_gap, beta_hitter, beta_pitcher, gamma]

expected_tier = 0.5 * P(Role) + P(Star)
```

The objective, bounds, optimizer, tolerance, initialization, and maximum
iterations are exactly those of the reused ordered-logit helpers. Both slopes
are fitted under the helper's existing unconstrained slope bounds; there is no
positive transform or alternate search. Qualification then requires both
fitted slopes to be finite and strictly positive. The offset, thresholds, role
centers, and role scales must be finite; every role scale must be greater than
zero.

The combined board sorts by unrounded expected tier descending, source-ladder
position ascending, then numeric MLBAM id ascending. Any identity mismatch or
within-role inversion fails closed.

## Frozen inputs and comparators

Candidate and controlled comparator use identical held-out identities:

- candidate: v1 hitter ladder plus frozen v0.9 pitcher ladder;
- controlled comparator: v1 hitter and pitcher ladders, calibrated with the
  same five-parameter family; and
- product comparator: v1 product logic reconstructed on each historical fold,
  using its emitted two-decimal final `score` and emitted `rank` after the exact
  production tie order: score descending, score-source order, role, name, then
  numeric MLBAM id.

Candidate and controlled comparator independently fit their own five-parameter
map on the same training folds, including their own role means and standard
deviations. The controlled comparator isolates the pitcher-ladder
substitution. The product comparator tests the v1 ranking logic used by the
product; these reconstructed historical cohort boards were not themselves
served. Its scores are not probabilities, so no MAE comparison is made against
them. The master-merged registration binds the exact
`prospects.rank_v2.reconstruct_fold_ladders` transplant and its source hash.
That helper preserves each incumbent row's emitted two-decimal `score` and
original emitted `rank`; the recombined incumbent rows must reproduce ranks
`1..n` under the stated production sort. Concordance uses the emitted score;
product-comparator top-25 uses original ranks `1..25`.

The v0.9 and v2.2 receipts are verified by exact file and internal hashes. The
existing pitcher-only result is provenance for the frozen ladder, not a new
v2.3 decision gate. V2.3 does not retune or re-adjudicate that model.

Combined MAE is the arithmetic mean of `abs(expected_tier - target)` across the
exact held-out identity universe. Cross-role concordance evaluates only
hitter-pitcher pairs whose targets differ: a score ordering that agrees with
the target ordering counts `1`, the reverse counts `0`, and an exact score tie
counts `.5`; equal-target pairs are excluded. It is the sum divided by the
number of eligible hitter-pitcher pairs and is undefined if there are none.

## Known-data development screen

Use exactly three leave-one-cohort-out rounds:

- fit on 2019 and 2021, score 2018;
- fit on 2018 and 2021, score 2019; and
- fit on 2018 and 2019, score 2021.

For every held-out fold, all rules must pass:

1. candidate combined expected-tier MAE minus the controlled comparator MAE is
   strictly less than zero;
2. candidate cross-role concordance minus controlled-comparator concordance is
   strictly greater than zero, and candidate concordance is greater than
   `0.5`;
3. candidate cross-role concordance minus the v1 product-logic comparator's
   concordance is strictly
   greater than zero;
4. candidate top-25 target sum is at least the controlled-comparator top-25
   target sum and at least the v1 product-logic comparator's top-25 target sum;
5. candidate and both comparators use the exact same held-out identity set and
   target per identity; and
6. all finite-value, probability, role-order, identity, leakage, and forbidden-
   input checks pass.

No pooled average or majority can rescue a failed fold.

Top-25 mechanics are deterministic. Each held-out universe must contain at
least 25 players. Candidate and controlled comparator take the first 25 under
their predeclared unrounded expected-tier orders; the product comparator takes
emitted ranks `1..25`. The gate compares the sum of the same `0/.5/1` targets
on those selected identities; otherwise it fails closed. The equivalent
oracle-regret subtraction cancels and is not separately fitted.

## Pooled confidence contract

The following procedure is registered before execution:

- one `numpy.random.default_rng(39017)` stream and `10,000` replicates;
- paired resampling: within each fold, resample hitter MLBAM ids with
  replacement and pitcher MLBAM ids with replacement, applying identical
  sampled identities and multiplicities to candidate and comparators;
- build each replicate's sample plan once in fold order
  `[2018, 2019, 2021]`, role order `[hitter, pitcher]`, and ascending numeric
  MLBAM-id input order, then reuse that sample plan for every metric and
  comparator;
- do not refit maps inside bootstrap replicates;
- compute fold metrics from each sampled union, rebuild cross-role pairs from
  the sampled hitter and pitcher identities, then equal-weight the three fold
  deltas;
- use NumPy's linear two-sided percentile interval at `[2.5, 97.5]`; and
- discard an undefined replicate, but fail the screen unless at least `9,900`
  valid replicates remain for every metric.

The pooled candidate-minus-controlled MAE interval must be entirely below
zero. Both pooled cross-role-concordance intervals - versus the controlled
comparator and versus the v1 product-logic comparator - must be entirely above
zero. The bootstrap implementation and its hash are frozen in the merged
registration before the outcome-bearing run.

## Outcome target

The corrected four-year factual MLB target is fixed:

- hitter Role: at least 300 PA in any one MLB season from cohort year + 1
  through cohort year + 4;
- hitter Star: at least 450 PA and `.800` OPS in any one such season;
- pitcher Role: at least 50 IP in any one such season; and
- pitcher Star: at least 120 IP and ERA no higher than `3.75` in any one such
  season.

Targets are `0` Bust, `.5` Role, and `1` Star. The screen tests known-data
combined outcome ordering. It does not establish format-specific fantasy
dollars or MLB/prospect value-unit equivalence.

## Execution and terminality

The master-merged registration binds the code, inputs, folds, identities,
comparators, metrics, thresholds, bootstrap contract, output paths, and frozen
dependency hashes before execution.

The runner first reserves the canonical receipt while no outcome source is
open. Immediately before opening an outcome-bearing source, it atomically
marks the receipt `outcome_access_spent`. A failure while still in the earlier
reserved phase may retry only with every bound hash unchanged. Any failure
after the spent marker is terminal `spent_error`; it cannot be relabeled as a
write failure and rerun. A completed metric pass or failure is also terminal.

Pure reproduction of a completed receipt from its frozen inputs is allowed and
cannot select or modify a candidate. Before a canonical run may record
`development_qualified: true`, it must fit the same fixed architecture once on
pooled 2018/2019/2021 data and freeze the non-serving pooled-development map.
Final-fit failure is terminal and nonqualified. Staging and daily builds apply
that exact map, including its frozen role centers and scales, to the frozen or
current ladder snapshot without refitting.

## Product prerequisites after a pass

Development success writes only inert, hash-bound evidence. It does not route,
publish, register, or value a board. Product work begins only after a pass and
must satisfy every item below.

### One lineage seam

Add the minimal compile-time `prospects/current_rank.py` constants for the
current artifact, archive, rank id/version, model score source, epoch id, and
epoch start date. Every production current-rank consumer imports those
constants. Current snapshot and downstream metadata use version-neutral keys,
not `valucast_rank_v1` or `prospect_rank_v1_*`. Explicit historical and
research readers remain pinned to their versioned v1 artifacts.

A lock test rejects any production current consumer that still hardcodes v1.
There is no runtime feature flag or second resolver.

### New history epoch

VNext writes only to a versioned vNext archive. It must accumulate at least two
successful daily shadow vintages before routing so Recent Signal can evaluate
without a cold-start blocker. Buys, Movers, Recent Signal, ahead-of-consensus,
call-up receipts, gaps/claim ledgers, forward scoreboards, value history, and
Time Machine must either read the vNext epoch or show explicit versioned
history. No consumer may compare a v1 vintage with a vNext vintage.

### R1 mixed-universe suppression

Plan 036 R1 is a cutover prerequisite and still requires explicit served-output
authorization. Before vNext routes, a versioned public-schema change removes
generic cross-universe `rank`, `value`, and dollar fields. MLB rows expose only
MLB rank/value fields; prospect rows expose only prospect rank/score fields.
CSV, API, validators, stores, and trade code consume the same per-universe
contract. Mixed MLB/prospect trades emit no summed winner verdict. Keep both
player populations, the prospect board, and factual/player pages visible.

After suppression is verified, the uncalibrated cross-universe compatibility
check no longer blocks the prospect-only surface. It remains a visible failed
or unsupported diagnostic until a real MLB/prospect unit mapping exists.

### One governor and one finished snapshot

Reuse PR #60's pipeline unchanged in principle: build the pending snapshot,
build snapshot-reading audits, run the authoritative governor exactly once,
and inject its artifact through the existing pure merge function. Do not add a
second evaluator or staging pipeline.

`prospect_top_board_role_shape` remains visible with `blocking: false`.
Front Office ignores only checks explicitly marked nonblocking; every other
failed check remains blocking.

Cutover requires both the governor result and the finished product result:

- the injected snapshot has `validation.surface_readiness.prospects == true`;
- `validate_public_dynasty_snapshot.py` passes against the committed governor;
- a cutover-only validator assertion requires prospect readiness to be true;
  this is not a second governor;
- every other build/freshness/identity/audit check passes; and
- the two shadow vintages remain internally consistent.

### R4 registry separation

Plan 036 R4 is also a cutover prerequisite and requires owner design approval.
The registry must separate scientific claim rows from operational component
state. Preserve the existing universal-pitcher beyond-neighbors `REJECTED`
claim byte-for-byte as a claim row. A vNext component row records only
`lifecycle: current` and feeding state. A separate vNext combined-board claim
row records scientific verdict `PROVISIONAL`, references the exact development
receipt and its evidence class, and names the finalized-2022 resolution
condition. The pass boolean lives only in the receipt. A v1 component row is
historical/nonfeeding. Registry validation must pass before routing.

## Cutover and rollback

The atomic cutover requires:

1. the terminal `development_qualified: true` receipt;
2. the exact frozen pooled-development map and hash-bound current vNext board;
3. at least two successful shadow vintages in the isolated vNext epoch;
4. R1 suppression and R4 registry separation;
5. a passing injected snapshot and all validators;
6. independent code, artifact, and arithmetic review;
7. explicit owner authorization against exact candidate bytes; and
8. one commit that switches the current pointer, all production consumers,
   registry state, snapshot, workflow, and public copy together.

V1 does not continue as a daily hidden fallback after cutover. Once the current
pointer is vNext, a snapshot with prospect readiness false serves an honest
prospects-unavailable state with zero ranked rows; it never serves a
`Preliminary` board. Dynasty and other independently ready surfaces may still
refresh. Rollback restores the last complete known-good vNext release only if
it still passes current validation; otherwise the prospect surface remains
unavailable. It must never silently revive stale v1 or mix lineages.

## Public behavior

After cutover, every prospect surface and prospect-only export uses the same
vNext lineage. The prospect score column is labeled `ValuCast Score` and
described as an outcome-order score, never `Dynasty Value` or dollars. Those
labels remain available only where their valuation evidence supports them.
Methodology may say:

> ValuCast Prospect Rank vNext is the current combined board. On known-data
> development backtests, it improved calibrated outcome error versus the same-
> family v1-ladder comparator and beat reconstructed v1 product logic on cross-
> role concordance while matching or exceeding its top-25 realized outcomes in
> the 2018, 2019, and 2021 folds.
> Finalized-2022 confirmation is pending, so its scientific verdict remains
> PROVISIONAL.

This copy is allowed only if the exact registered tests support every clause.
There is no public `DEVELOPMENT_QUALIFIED` badge and no `VALIDATED` claim before
confirmation.

## Future confirmation

The finalized-2022 confirmation is separately registered and globally
single-use. It binds the frozen current candidate with no refit. A pass may
upgrade the scientific verdict to `VALIDATED`; a failure changes the scientific
claim but does not silently alter scores or routing. Any operational decision
after that result requires a new explicit owner authorization.

## Failure behavior

- Development failure: freeze the exact result, stop v2.3, and keep v1 current.
- Staging failure: keep the scientific receipt inert and do not route it.
- Cutover-build failure: publish no partial state and retain the last complete
  current release.
- Post-cutover failure: serve the last known-good vNext state or hold the
  prospect surface unavailable; never fall back across lineages.

## Verification contract

Implementation must prove:

1. every per-fold rule and each pooled bound fails independently;
2. top-25 selection, tie order, identities, and targets are deterministic;
3. the exact formula, optimizer, frozen input hashes, and forbidden-input
   boundary cannot drift;
4. candidate and comparator identities align exactly;
5. no 2022 outcome, governor count, market rank, or player-name feature reaches
   fitting;
6. v1, v0.9, v2.1, and v2.2 frozen dependencies remain byte-exact;
7. no whole research-branch merge or unrelated data refresh enters the diff;
8. the role-shape diagnostic cannot alter readiness or Front Office status,
   while every other prospect check remains blocking;
9. R1 removes only unsupported mixed-universe outputs and leaves both player
   populations and the combined prospect board visible;
10. every production current consumer follows the compile-time pointer and no
    history claimant crosses epochs;
11. the two-vintage shadow burn-in, injected snapshot readiness, validators,
    browser surface, and live health checks agree on one lineage;
12. registry claim/component separation preserves the existing rejected claim;
    and
13. rollback restores one internally consistent vNext state or an honest held
    surface, never v1 under vNext history.

## Phase boundary

This document authorizes implementation planning only. It authorizes no model
execution, R1 output change, R4 schema change, publication, or deployment.

- Phase A transplants the minimal frozen research dependency closure onto
  current master and executes the fixed v2.3 development screen.
- Phase B exists only after a pass and separately requires owner authorization
  for R1, R4, staging, shadow burn-in, consumer migration, and cutover.
- Phase C is the later finalized-2022 confirmation.

No phase may borrow authority from a later phase.
