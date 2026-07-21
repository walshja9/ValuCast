# Analytics Proof Integrity Implementation Plan

> **Execution:** Use the test-driven-development and verification-before-completion workflows. Complete Tasks 1-3 before the review checkpoint. Task 4 is a separately reviewed research artifact.

**Goal:** Repair misleading evidence metadata and strengthen evaluation diagnostics without changing any live score, rank, value, cap, or publication decision.

**Architecture:** Keep serving functions untouched. Add explicit contracts to existing generated artifacts, preserve compatibility-gate behavior under honest names, and add only reporting fields or research-only evaluators.

**Tech Stack:** Python 3.11+, pytest, JSON artifacts.

## Global Constraints

- Preserve the prospect-model freeze and failed pedigree-decay flag.
- Do not change model coefficients, score blends, current values, ranks, pitcher caps, Role Watch, or publication behavior.
- Do not rerun plan 033 or reuse any spent seed.
- Write the regression test first and observe RED before implementation.
- Never stage user-owned files or use `git add -A`.

### Task 1: Prospect model release contract

**Files:**
- Modify: `prospects/model.py`
- Modify: `tests/test_prospect_model.py`
- Modify: `tests/test_prospect_model_contract.py`
- Regenerate metadata only: `data/models/valucast_prospect_model.json`

**Steps:**

1. Add a test asserting `release_contract.feeds_live_valucast_rank == true`, consumer `prospect_rank_v1`, and model-score weight `0.76`.
2. Assert the false "never consumed" limitation is absent and the partial-impact reference limitation is present.
3. Run `python -m pytest tests/test_prospect_model.py tests/test_prospect_model_contract.py -q` and capture RED.
4. Add the release contract and honest limitations without touching scoring code.
5. Update only the committed artifact metadata to match the builder.
6. Re-run the focused tests and capture GREEN.

### Task 2: Cross-universe compatibility contract

**Files:**
- Modify: `scripts/build_public_dynasty_snapshot.py`
- Modify: `tests/test_public_dynasty_snapshot.py`

**Steps:**

1. Change tests to require compatibility certification, `unit_mapping_applied == false`, `value_units_calibrated == false`, and the legacy calibrated flag to remain false.
2. Add a before/after invariant assertion for player values, ordering, and readiness.
3. Run `python -m pytest tests/test_public_dynasty_snapshot.py -q` and capture RED.
4. Rename the method to compatibility certification, add the new fields, and keep readiness keyed to the passed compatibility check.
5. Replace per-player `calibrated_value` semantics with an unchanged display value plus explicit no-mapping metadata.
6. Re-run the focused tests and capture GREEN.

### Task 3: H+P suitability diagnostics

**Files:**
- Modify: `scripts/build_valucast_hp_run.py`
- Modify: `tests/test_build_valucast_hp_run.py`

**Steps:**

1. Add tests that role diagnostics include exact counts and rates for actuals matching, positive opportunity, zero opportunity, and clamping.
2. Add reconciliation assertions that positive plus zero equals rows and every rate equals count divided by rows.
3. Assert the public Skill+ gate remains held and `affects_live_outputs` remains false when any zero/clamp condition exists.
4. Run `python -m pytest tests/test_build_valucast_hp_run.py -q` and capture RED.
5. Implement the minimal derived diagnostics and explicit blocker list.
6. Re-run the focused tests and capture GREEN.

### Task 4: Fold-local impact evidence

**Files:**
- Modify: `prospects/model.py`
- Create: `prospects/impact_oof.py`
- Create: `scripts/build_impact_oof_scores.py`
- Create: `scripts/validate_impact_oof_scores.py`
- Create: `tests/test_impact_oof.py`
- Create: `data/models/valucast_impact_oof_scores.json`

**Steps:**

1. Add synthetic tests proving test/future identities cannot enter a fold's reference distribution and outcome mutations outside the training reference pool cannot alter its hash.
2. Add tests for exact `(mlbam_id, role, test_cohort)` identity preservation and deterministic cohort-then-player bootstrap intervals.
3. Run `python -m pytest tests/test_impact_oof.py -q` and capture RED.
4. Implement a reporting-only fold-local impact OOF helper using the incumbent features, model kind, and baselines.
5. Emit source hashes, fold reference counts/hashes, per-player paired errors, role/combined intervals, and `claim_authorized: false`.
6. Add a validator that recomputes metrics and rejects any serving/import flag.
7. Build and validate the artifact without wiring it into ranks or publication.
8. Re-run tests and inspect the result before any workflow integration.

### Task 5: Verification and review checkpoint

1. Run the focused suite:

   `python -m pytest tests/test_prospect_model.py tests/test_prospect_model_contract.py tests/test_public_dynasty_snapshot.py tests/test_build_valucast_hp_run.py tests/test_impact_oof.py -q`

2. Run `python -m pytest -q`.
3. Run `git diff --check`.
4. Prove frozen output invariants with tests and a targeted artifact comparison.
5. Review Task 4 results before deciding whether to wire its build/validator into the daily workflow.

### Deferred registration: post-2026 challenger batch

After Task 5 review, write one fresh registration covering ridge tuning, stronger neighbor baselines, rank-component de-correlation, investment blending, target scaling, train/serve shrinkage alignment, multiplicative confidence haircuts, uncertainty-aware regression guards, buy-momentum asymmetry, and genuine cross-universe mapping. Do not implement or score those variants in this plan.

