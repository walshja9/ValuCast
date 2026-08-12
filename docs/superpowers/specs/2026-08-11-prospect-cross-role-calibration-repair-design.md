# Prospect Cross-Role Calibration Repair Design

**Date:** 2026-08-11

**Status:** Approved for implementation by the owner

**Production rule:** No score, rank, governor threshold, or hold flag changes until the registered replacement gate passes.

## Problem

The public prospect board has been governor-blocked for pitcher concentration on nearly every build since the current cross-role normalization shipped. The block is not a transient data-refresh failure.

Two mechanisms interact:

1. The pitcher model includes raw MLB draft slot dollars as `pick_value`. Only 7.23% of mature pitcher training rows have a positive value, versus 25.65% of current scored pitchers. Current first-round values sit as far as 24.64 training standard deviations above the zero-filled training mean. The field is also redundant with inverse pick, inverse round, and log signing bonus.
2. Rank v1 independently rank-normalizes hitters and pitchers and maps both roles onto the same pooled marginal distribution. With pitchers making up about 52.6% of the normalization pool, this makes roughly half of the model-score tail pitchers by construction. The governor permits at most seven pitchers in the top 25 and 30% in the top 50.

The governor is doing its job: it prevents an unvalidated cross-role scale from becoming a public buy signal. Changing its thresholds or applying a fixed pitcher penalty would conceal the defect.

## Evidence boundary

Plan 034 remains sealed and cannot run before the completed 2026 season. It must not be rewritten.

This repair uses a separately named pre-2014 protocol. MLB StatsAPI returns
affiliated A through Triple-A season totals for the registered 2009-2019 and
2021-2022 cohorts. The existing upstream cohort producer and outcome-label
functions were recovered from the Diamond Dynasties repository. A read-only
reconstruction of 2014 reproduced all 1,559 committed cohort identities exactly,
including the role split. That establishes a source-compatible way to rebuild
the full registered history and create the previously unused pre-2014 cohorts.

The implementation commit `I` and its exact direct-child registration commit `R`
must both be pushed before any registered outcome byte is opened or any candidate
outcome score is calculated. `R` may change only the four registered
plan/readiness/test files. The result is single-use. A failure leaves production
unchanged. Terminal artifacts are first validated as the only untracked files,
then committed unchanged in the exact artifact-only direct child `S` of `R`, and
validated again from a clean checkout at `S`. Any later production descendant
must validate the seal from a detached clean `S` checkout rather than treating
the production tree as the sealed execution tree.

The prepare-only builder may compare against only the committed, identity-only
2014 parity artifact (`mlbam_id` plus role). It must reject outcome labels or
MLB-season payloads anywhere in that parity input. Before reservation, the
outcome-bearing current prospect contract is bound only by its committed Git
path and blob object id: no process may open, hash, parse, or retain its bytes.
The hardwired runner may read and verify those bytes only after it has installed
the single-use result reservation.

## Design

### 1. Reproducible extended research contract

Add a ValuCast-owned builder that:

- fetches MLB StatsAPI season totals for A, A+, AA, and AAA;
- applies the frozen cohort rules: age at most 24, at least 250 PA for hitters or 50 IP for pitchers, earliest qualifying season, highest qualifying level within that season;
- validates the producer against the committed 2014 identity set before older data is accepted;
- freezes role and MLBAM identity at the cohort cutoff;
- exposes a pure outcome-backfill helper that the hardwired sealed runner may
  invoke only after reserving the result path; the runner strictly reacquires
  every registered identity from raw provider responses, then applies
  corrected, fixed-horizon labels
  using only seasons `cohort_year + 1` through `cohort_year + 4`:
  - bust: never reaches 150 PA or 50 IP inside that four-year horizon;
  - hitter star: a horizon season with at least 450 PA and .800 OPS;
  - pitcher star: a horizon season with at least 120 IP and ERA at most 3.75;
  - otherwise role;
- fetches only factual Rule 4 draft/signing fields known by the cohort date;
- writes a separate research contract and source manifest. It does not replace the production input contract.

The initial extension is 2009-2013. Existing 2014-2022 rows are regenerated through the same producer so a player remains assigned to the earliest credible cohort; old and new identity sets are never concatenated opportunistically.

### 2. One fixed challenger

There is one candidate, not a tuning grid:

- preserve raw `pick_value` in the factual contract for provenance;
- omit `pick_value` from the pitcher model features;
- retain inverse draft pick, inverse draft round, log signing bonus, draft flags, school type, and handedness;
- replace live-population role-quantile normalization with fold-trained calibration from each role-specific model output to its shared realized target;
- fit calibration using only outcome-mature rows available at the outer
  pseudo-date: each mature source cohort is held out once while its prediction
  model is trained on every other cohort in that outer fold's mature pool;
- use a monotone piecewise-linear calibrator with deterministic pooling of adjacent violators;
- calibrate the ordinal outcome and partial-impact heads separately, then retain the existing 58/42 head blend and all downstream weights;
- use no role count, governor threshold, external ranking, or current-board composition as an input.

For current serving, calibration is trained only from mature historical out-of-fold predictions. Missing or invalid calibration fails closed to the incumbent; it never falls back to a role quota.

### 3. Single-use gate

The protocol freezes the data hashes, source code hashes, seed, folds, metrics, and thresholds before scoring.

The production-review primary is percentile-rank MAE against
`canonical_dd_7x7_best_season_impact` at the registered
cohort-season-completion cutoff. The target uses the same four-year forward
horizon and fold-local category references, including a separately rebuilt and
hash-bound quality-start sidecar. Hitter value is the equal-weight percentile
mean of R, HR, RBI, SB, AVG, OPS, and inverse SO. Pitcher value is the better of
the registered starter group (K, QS, inverse ERA/WHIP/L, K/BB) and reliever
group (K, SV+HLD, inverse ERA/WHIP/L, K/BB). Each identity receives its best
qualifying horizon season; genuine zero opportunity is zero, while a qualifying
season with a missing category is unresolved and blocks the look.

The fold-local reference builder is equally strict: a qualifying training
season missing any canonical 7x7 category blocks the look rather than silently
changing one category's percentile denominator. For outer cohort `Y`, no
calibration source cohort later than `Y-4` may be scored or labeled.

Top-25 regret is `oracle@25 - selected@25`, where each mean uses that same
direct target. Shared-outcome cross-role ordering is a diagnostic secondary
endpoint: it can reject a calibration but cannot authorize a production review
on its own. Additional secondary evidence covers ordinal calibration,
within-role safety, and fold-level stability.

Promotion requires all of the following:

- at least four complete outer cohorts;
- at least 250 unique players in each role;
- at least 90% identity/outcome coverage in every fold-role;
- direct 7x7 realized-value coverage is complete for every scored opportunity
  season;
- direct-target percentile-rank MAE improves by at least 2%, with the paired
  player-within-cohort hierarchical-bootstrap 95% lower bound above zero;
- candidate top-25 direct regret is no worse than the incumbent;
- at least 2% relative improvement in cross-role discordance versus the frozen incumbent;
- paired hierarchical-bootstrap 95% lower bound above zero for concordance improvement;
- no outer fold worse by more than 5%;
- neither role's concordance worse by more than 1%;
- top-25 realized ordinal regret no worse;
- candidate current board independently passes the unchanged
  `prospect_top_board_role_shape` governor check;
- all existing model, rank, governor, and public-snapshot tests pass.

Board pitcher counts are reported only after the candidate is fixed and scored. They cannot select parameters.

### 4. Promotion mechanics

If and only if the gate passes, it authorizes an explicit production review,
not an automatic flip or a public superiority claim. The sealed gate checks
the prospect role-shape condition it was designed to repair; it does not call
that one check the full governor. If review verifies the exact registered
code/data hashes and the limitations of cohort-completion pseudo-replay, the
owner may authorize a production build that must:

- set the production pitcher feature contract to omit raw `pick_value`;
- make the fold-trained common-target calibrator the Rank v1 model-score input;
- retain raw model outputs and calibration metadata in each row for auditability;
- remove the live-population role-quantile remap from the serving path while leaving a compatibility reader for archived artifacts;
- bump model/calibration versions and the prospect buy epoch;
- rebuild all dependent artifacts atomically;
- run the full unchanged quality governor last and refuse publication unless
  the prospect surface passes every applicable check.

If any gate fails, only the reproducible data builder, readiness audit, and sealed result remain. Production stays exactly byte-compatible with the incumbent.

## Failure handling

- Network pulls are checkpointed and content-hashed.
- Empty, partial, duplicate, or role-conflicting cohorts fail before model scoring.
- The result path is reserved atomically before the first outer outcome is read.
- Provider/transport gaps and process interruption preserve the same bound
  reservation and checkpoint; they never create a second look. A deterministic
  adjudication failure consumes the reservation as `spent_error`.
- One live invocation holds an operating-system-released lease from reservation
  through terminal finalization; a concurrent invocation cannot touch evidence
  or checkpoints, while a crashed owner leaves the same reservation resumable.
- A spent result cannot be overwritten, and reservation/finalization residue is
  recoverable only when it is exactly bound to the active reservation.
- The daily build never performs historical network work.

## Non-goals

- No fixed hitter/pitcher quota.
- No governor relaxation.
- No external prospect rank in the model.
- No claim of direct 7x7 superiority from the ordinal bridge; only the separate
  direct category endpoint may adjudicate production value.
- No mutation of the existing Plan 028, 033, or 034 results.
