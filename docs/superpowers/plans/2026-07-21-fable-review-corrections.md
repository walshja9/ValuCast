# Fable Review Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Correct the six reproduced review defects while preserving every frozen model and ranking boundary.

**Architecture:** Reuse the existing signed-value transformation, keep source-data fallbacks honest, centralize scoreboard verdict semantics, and make validators/contracts fail closed. No new dependency or public surface is introduced.

**Tech Stack:** Python 3.11+, pytest, GitHub Actions YAML.

## Global Constraints

- Do not change model weights, prospect scores, ranks, pitcher caps, Role Watch, or publication thresholds.
- Preserve the model freeze and failed decay flag.
- Write and run each regression test before its implementation change.

---

### Task 1: Signed dynasty horizon

**Files:**
- Modify: `src/league_values/post_processors.py`
- Modify: `mlb/dynasty.py`
- Test: `tests/test_mlb_dynasty_layer.py`

**Interfaces:**
- Produces: `_apply_multiplier(value: float, multiplier: float, baseline: float) -> float`

- [ ] Add a regression test proving a negative player cannot improve when future factors are below one.
- [ ] Run `python -m pytest tests/test_mlb_dynasty_layer.py -q` and confirm the new assertion fails.
- [ ] Route the horizon calculation through the shared pool-floor-shifted scalar helper.
- [ ] Re-run the test and confirm it passes.

### Task 2: Honest hitter slash reconstruction

**Files:**
- Modify: `prospects/milb_translation.py`
- Test: `tests/test_milb_translation.py`

**Interfaces:**
- Consumes: supplied per-level OBP when HBP counts are unavailable.
- Produces: exact component-derived AVG/SLG/ISO and non-fabricated OBP/OPS.

- [ ] Add a regression test with missing HBP and a supplied OBP.
- [ ] Run `python -m pytest tests/test_milb_translation.py -q` and confirm it fails.
- [ ] Reconstruct OBP only with complete HBP data; otherwise use the supplied rate.
- [ ] Re-run the test and confirm it passes.

### Task 3: Scoreboard verdict and validator

**Files:**
- Modify: `prospects/forward_scoreboard.py`
- Modify: `scripts/validate_forward_scoreboard.py`
- Modify: `app.py`
- Test: `tests/test_forward_scoreboard.py`
- Test: `tests/test_forward_scoreboard_page.py`

**Interfaces:**
- Produces: one canonical verdict label from sign counts, p-value, median, and provisional state.

- [ ] Add regressions for even direction, significant-behind display, zero-dominated medians, and malformed sign-test artifacts.
- [ ] Run the two scoreboard test files and confirm the new assertions fail.
- [ ] Centralize verdict interpretation and validate the complete sign-test block by recomputation.
- [ ] Re-run the tests and confirm they pass.

### Task 4: Governance and context contracts

**Files:**
- Modify: `.github/workflows/tests.yml`
- Modify: `tests/test_prospect_normalized_production_registration.py`
- Modify: `prospects/rank_v1.py`
- Test: `tests/test_prospect_rank_v1.py`

**Interfaces:**
- CI checkout must contain the registered base commit.
- `rank_contract.factual_current_context` must exactly describe emitted fields.

- [ ] Add assertions for full-history CI checkout and the exact hitter context contract.
- [ ] Run the two focused test files and confirm the new assertions fail.
- [ ] Set checkout `fetch-depth: 0`, replace the registration skip with a hard assertion, and correct the rank contract.
- [ ] Re-run the tests and confirm they pass.

### Task 5: Verification

- [ ] Run the affected test suite.
- [ ] Run `python -m pytest -q`.
- [ ] Run `git diff --check` and review the complete diff for scope.
