# Prospect Investment Coverage Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing prospect coverage artifact with observational investment-data completeness and direct score-sensitivity evidence.

**Architecture:** Reuse `prospects.coverage_audit`; do not create a second pipeline. Keep the existing root `status` and governor behavior unchanged. Add a nested `investment_context` section that reports top-N coverage by role and a direct-component upper bound while holding the frozen model score fixed.

**Tech Stack:** Python standard library, pytest, committed JSON artifacts.

## Global Constraints

- No model, rank, value, governor, publication, or workflow behavior changes.
- Do not impute a neutral investment value or publish counterfactual ranks.
- Label sensitivity as direct Rank-v1 contribution only; upstream model effects remain unmeasured.
- Preserve the failed pedigree-decay flag and every existing freeze.

---

### Task 1: Add investment coverage and sensitivity evidence

**Files:**
- Modify: `tests/test_prospect_coverage_audit.py`
- Modify: `prospects/coverage_audit.py`
- Modify: `scripts/validate_prospect_coverage_audit.py`
- Modify: `scripts/build_prospect_coverage_audit.py`

**Interfaces:**
- Consumes: `rank_payload["board"]`, `SCORE_WEIGHTS`, and `MISSING_INVESTMENT_CONTEXT_SCORE`.
- Produces: `payload["investment_context"]` with top-25/50/100/200 role coverage and top-50 direct sensitivity rows.

- [x] **Step 1: Write the failing coverage test**

Add a fixture with covered and missing investment rows across both roles. Assert that top-N denominators, missing rates, `status="incomplete"`, and the v0.6 maximum direct delta of `4.5` are emitted without changing root `status`.

- [x] **Step 2: Run the test to verify RED**

Run: `python -m pytest -q tests/test_prospect_coverage_audit.py`

Expected: failure because `investment_context` does not exist.

- [x] **Step 3: Implement the minimum artifact extension**

Add one coverage summarizer and one sensitivity-row helper. Use the configured score-source weight and `100 - MISSING_INVESTMENT_CONTEXT_SCORE`; do not recompute model scores or ranks.

- [x] **Step 4: Strengthen the validator and CLI receipt**

Require the nested section and print the top-50 hitter missing count and rate.

- [x] **Step 5: Run the focused tests**

Run: `python -m pytest -q tests/test_prospect_coverage_audit.py tests/test_valucast_quality_governor.py`

Expected: all pass; existing governor assertions remain unchanged.

### Task 2: Rebuild and document the current evidence

**Files:**
- Modify: `data/models/valucast_prospect_coverage_audit.json`
- Create: `docs/audit-2026-07-21-prospect-investment-coverage.md`

**Interfaces:**
- Consumes: the rebuilt audit artifact and the current prospect rank artifact.
- Produces: a dated internal decision record; no public surface.

- [x] **Step 1: Rebuild and validate**

Run: `python scripts/build_prospect_coverage_audit.py`

Run: `python scripts/validate_prospect_coverage_audit.py`

Expected: valid artifact with unchanged root readiness status and populated investment coverage.

- [x] **Step 2: Write the audit report**

Document top-N rates by role, the four-player comparison case, the direct-only sensitivity limit, and the comparison-surface recommendation. State explicitly that the audit cannot identify the upstream v0.6 investment effect or authorize a model change.

- [x] **Step 3: Verify the delivery**

Run: `python -m pytest -q tests/test_prospect_coverage_audit.py tests/test_valucast_quality_governor.py tests/test_public_surfaces_smoke.py`

Run: `git diff --check`

Expected: green tests, no whitespace errors, and no files outside the listed scope.
