# Prospect Cross-Role Calibration Repair Implementation Plan

> **For Codex:** Execute task-by-task with test-driven development. Do not
> acquire, parse, or score the registered outer-cohort outcomes until Tasks 1-5
> are committed and the single-use result path is reserved.

**Goal:** Replace the structurally incompatible pitcher feature/role-normalization pair with a source-reproducible, fold-trained common-target calibration that must beat the incumbent before it can serve.

**Architecture:** Build a research-only extended historical contract from MLB
StatsAPI using the recovered upstream cohort rules, train a fixed
no-raw-pick-value challenger plus monotone role/head calibrators, and adjudicate
it once after reserving the result path and strictly reacquiring every target
identity's outcome receipt. Keep production behind the incumbent until the
sealed gate passes; then promote the exact tested code path and rebuild through
the unchanged governor.

**Tech stack:** Python standard library, NumPy, pytest, MLB StatsAPI, existing ValuCast model/rank/governor builders.

---

## Task 1: Add the source-compatible historical cohort producer

**Files:**

- Create: `prospects/extended_history.py`
- Create: `scripts/build_extended_prospect_history.py`
- Create: `scripts/backfill_extended_prospect_outcomes.py`
- Create: `tests/test_extended_prospect_history.py`
- Create: `tests/test_backfill_extended_prospect_outcomes.py`

**Steps:**

1. Write failing tests for the frozen qualification rules, earliest-season/highest-level selection, innings parsing, four-year forward-only label thresholds, cohort-date draft masking, duplicate/two-way preservation, and fail-closed incomplete outcome requests.
2. Add a fixture-backed 2014 identity-parity test. The producer must emit the same 1,559 `(mlbam_id, role)` identities as the committed 2014 cohort when given the recorded 2014 raw splits.
3. Implement pure parsing and selection functions. Network functions must be injectable and must never run during unit tests.
4. Implement checkpointed StatsAPI pulls for MiLB season totals and batched
   factual draft records. Preserve raw provider responses and deterministically
   rebuild each transformed checkpoint from its bound response. Writes use
   temporary files plus `os.replace`.
5. Give the history CLI only the prepare-only path. It may fetch raw MiLB/draft
   facts and write a source manifest, but it has no outcome or sealed-look
   execution mode. Keep outcome backfill as an injected pure helper called only
   by the hardwired runner after reservation.
6. Run `python -m pytest -q tests/test_extended_prospect_history.py`.

## Task 2: Add the fixed investment feature contract

**Files:**

- Create: `prospects/investment_challenger.py`
- Modify: `prospects/model.py`
- Create: `tests/test_prospect_investment_challenger.py`
- Modify: `tests/test_prospect_model.py`

**Steps:**

1. Write failing tests proving the candidate omits raw `pick_value`, leaves hitters byte-identical, retains all other pitcher pedigree fields, keeps names/vector widths aligned, and cannot mutate the factual input row.
2. Implement `investment_feature_names(role, mode)` and `investment_feature_vector(names, values, mode)` with exactly two modes: `incumbent` and `drop_raw_pick_value`.
3. Add `PITCHER_INVESTMENT_FEATURE_MODE = "incumbent"` to `prospects/model.py`. Thread it through training and scoring using the existing `_model_flags` research harness. The default path must remain byte-identical.
4. Preserve `pick_value` in `raw_input_builder.py`; no input-schema change is allowed.
5. Run `python -m pytest -q tests/test_prospect_investment_challenger.py tests/test_prospect_model.py tests/test_prospect_rank_backtest.py`.

## Task 3: Add deterministic common-target calibration

**Files:**

- Create: `prospects/common_target_calibration.py`
- Modify: `prospects/model.py`
- Modify: `prospects/rank_v1.py`
- Create: `tests/test_common_target_calibration.py`
- Modify: `tests/test_prospect_rank_v1.py`

**Steps:**

1. Write failing tests for deterministic pooled-adjacent-violators fitting, monotonic prediction, bounded interpolation, constant-input behavior, serialization round trips, and outcome invariance.
2. Implement a dependency-free weighted isotonic fit that returns versioned knots. Prediction uses clamped piecewise-linear interpolation.
3. Add helpers that construct role/head calibrators only from out-of-fold predictions and their factual targets. Reject in-sample rows, duplicate identities, future cohorts, non-finite values, fewer than 250 rows per role, or fewer than four source folds.
4. Add optional calibrated fields to model rows: `expected_outcome_score_common_target` and `expected_category_impact_score_common_target`, plus an audit object naming the calibrator hash and source folds.
5. Add a Rank v1 keyword `model_score_mode` with exactly `incumbent_role_quantile` and `common_target`. The default remains incumbent. `common_target` reads only the two calibrated fields and fails closed if either is missing; it must never fall back to raw or role-quantile values.
6. Run `python -m pytest -q tests/test_common_target_calibration.py tests/test_prospect_rank_v1.py tests/test_valucast_quality_governor.py`.

## Task 4: Add the single-use adjudicator

**Files:**

- Create: `prospects/pre2014_cross_role_gate.py`
- Create: `scripts/run_pre2014_cross_role_gate.py`
- Create: `scripts/validate_pre2014_cross_role_gate.py`
- Create: `tests/test_pre2014_cross_role_gate.py`

**Steps:**

1. Write failing tests for readiness stops, source/hash enforcement, result-path reservation, no-overwrite semantics, exact fold derivation, player/cohort hierarchical bootstrap determinism, and every promotion gate.
2. Freeze seed `35011`, 10,000 bootstrap resamples, outer folds derived as all complete cohorts with four years of earlier source history, and the thresholds from the design document.
3. For each outer cohort `Y`, train its scored model on cohorts through `Y-4`.
   Build calibration rows by leave-one-cohort-out cross-fitting wholly inside
   that same mature pool: hold out each source cohort through `Y-4`, train on
   every other mature cohort, and reject any target whose four-year horizon is
   not complete by `Y`. Do not read the outer target until both score paths
   have identical identity coverage.
4. Score the incumbent and the one fixed candidate through the same production scoring core. Confirm identical eligible identity sets before reading outer outcomes.
5. Compute direct Diamond Dynasties 7x7 realized value with strict fold-local
   category references (including QS); reject a qualifying reference season
   missing any canonical category rather than dropping it from one denominator.
   Compute candidate-versus-incumbent top-k realized-value
   regret, cross-role concordance/discordance, per-role concordance, calibration
   MAE, top-25 ordinal regret, partial-impact diagnostics, and fold-level deltas.
6. Reserve the final artifact atomically before the first outer target access.
   Provider/transport gaps and process interruption preserve the exact same
   reservation and checkpoint for resumption. Deterministic adjudication errors
   write `spent_error`; no path may create a second look. Hold one exclusive,
   crash-released run lease across acquisition, evidence writes, scoring, and
   finalization so concurrent invocations cannot race the registered look.
7. Emit `data/validation/valucast_pre2014_cross_role_gate.json` with
   `claim_authorized=false` and a separate `production_review_authorized`
   boolean derived only from the frozen gates. The artifact never flips a
   production default itself.
8. Run `python -m pytest -q tests/test_pre2014_cross_role_gate.py`.

## Task 5: Register and independently review the look

**Files:**

- Create: `plans/036-pre2014-cross-role-calibration-gate.md`
- Modify: `plans/README.md`
- Create: `data/validation/valucast_pre2014_cross_role_readiness.json`
- Create: `tests/test_pre2014_cross_role_registration.py`

**Steps:**

1. Run the history CLI in `--prepare-only` mode for the registered 2009-2019
   and 2021-2022 cohorts, using only the label-free 2014 identity-role parity
   artifact for producer validation.
   Reject any parity input containing outcome labels or MLB seasons; do not
   parse the outcome-bearing production contract or fetch outcomes.
2. Record the base commit, Git blob hashes for every implementation file,
   source response hashes, the outcome-bearing current contract's Git blob id
   without reading its bytes, the 2014 parity result, candidate identity counts,
   exact seed, folds, metrics, thresholds, and result path.
3. Commit the complete implementation as `I`, then build the machine-readable
   readiness artifact from that clean commit. Set `look_spent=false` and
   `execution_authorized=true` only when every no-outcome readiness check passes.
4. Write the immutable Plan 036 registration and add tests that parse its block,
   verify hashes and paths, reject any unknown candidate, and prove Plan
   028/033/034 artifacts are untouched.
5. Commit a direct child `R` of `I` containing exactly the Plan 036 document,
   `plans/README.md`, the readiness artifact, and its registration test. Run the
   full no-outcome suite and obtain a separate code/protocol review.
6. Push `R` before any registered outcome byte is opened. No uncommitted code or
   data change may accompany the execution.

## Task 6: Execute the sealed look exactly once

**Files:**

- Generate/update resumable checkpoint:
  `data/research/extended_prospect_history/sealed-acquisition-checkpoint.json`
- Generate: `data/validation/valucast_pre2014_cross_role_evidence.json`
- Generate: `data/validation/valucast_pre2014_cross_role_gate.json`

**Steps:**

1. Confirm the worktree is clean and HEAD is the exact direct registration child
   `R` of the registered implementation commit `I`.
2. Run the hardwired no-argument command
   `python scripts/run_pre2014_cross_role_gate.py` once. It reserves the result
   before strict provider acquisition and resumes only the same registered
   reservation/checkpoint after interruption.
3. Run `python scripts/validate_pre2014_cross_role_gate.py` while the exact
   runtime artifacts are untracked. The validator must see only the registered
   artifact paths with exact `??` worktree status.
4. Commit the exact terminal artifact set as the artifact-only direct child `S`
   of `R`. A passed/failed result requires result, evidence, and checkpoint; a
   spent result requires result and evidence and includes the checkpoint only
   when acquisition created it. No artifact may be modified from its validated
   untracked bytes before the commit.
5. From a clean checkout at `HEAD=S`, rerun
   `python scripts/validate_pre2014_cross_role_gate.py`. This post-commit
   validation is the durable seal and is mandatory before any promotion work.
6. If status is not `passed`, stop all production work, push `S`, and report the
   failed gate. If status is `passed`, push `S` and continue to Task 7 without
   changing the candidate or thresholds. Later production commits validate the
   sealed look from a detached clean checkout at `S`; the validator does not
   treat a descendant production checkout as the sealed evidence tree.

## Task 7: Promote the exact tested path conditionally

**Files:**

- Modify: `prospects/model.py`
- Modify: `prospects/rank_v1.py`
- Modify: `prospects/stage1_contract.py`
- Modify: `prospects/calibration_report.py`
- Modify: `quality/valucast_governor.py`
- Modify generated model/rank/governor/public artifacts through existing builders only
- Modify relevant model, rank, stage-contract, governor, and snapshot tests

**Steps:**

1. Add a failing integration test that requires the production model artifact to carry the exact passed gate hash and common-target calibrator hashes.
2. Change the production defaults to `drop_raw_pick_value` and `common_target`; do not alter score weights or governor thresholds.
3. Preserve incumbent/raw fields and add explicit calibration audit metadata to every scored row.
4. Bump model and normalization versions and the prospect buys epoch.
5. Rebuild in canonical daily-build order, ending with the full unchanged
   quality governor; refuse publication unless every applicable prospect
   surface check passes, then build the public snapshot.
6. Verify top-25/top-50 role shape, identity continuity, score separation, source independence, and public surface readiness from regenerated artifacts.

## Task 8: Verification, review, and publication

**Steps:**

1. Run targeted suites for history, model, calibration, rank, gate, governor, snapshot, and refresh.
2. Run `python -m pytest -q`.
3. Run every repository validator used by `scripts/run_daily_public_build.py` without network refresh.
4. Run `git diff --check`, inspect generated-artifact scope, and verify the original dirty checkout was never changed.
5. Request an adversarial code review focused on leakage, hash seals, gate semantics, default-path changes, and governor integrity.
6. Commit intentional files only, push `codex/pitcher-model-repair`, and merge only after all required GitHub checks pass.
