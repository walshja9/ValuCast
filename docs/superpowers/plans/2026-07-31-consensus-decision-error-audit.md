# Consensus Decision Error Audit Implementation Plan

> **For Codex:** Execute this plan in the isolated
> `codex/decision-error-audit` worktree. Stop if the 151-decision population
> does not reconcile exactly. Do not edit scoring, publication, workflow, or
> frozen forward-evidence files.

**Goal:** Build a deterministic, claim-time error audit for the matured
Ahead-of-the-Curve decisions and map any credible concentration to existing
registered research without changing the model.

**Architecture:** A standalone script reads the committed scorecard and the
dated claim-time rank archives, validates a one-to-one identity/role join, and
emits an internal JSON validation artifact. Pure helper functions own all bins,
Wilson intervals, and reconciliations so tests can lock the contract. A dated
Markdown report summarizes the generated evidence and research disposition.

**Tech stack:** Python standard library, pytest, committed JSON artifacts.

---

### Task 1: Lock cohort, join, and binning behavior with tests

**Files:**
- Create: `tests/test_consensus_decision_error_audit.py`
- Create: `scripts/audit_consensus_decisions.py`

1. Add fixture helpers for a scorecard and dated rank archives.
2. Add failing tests for:
   - filtering to matured decided statuses;
   - exact claim-date identity and role joins;
   - fail-closed behavior for a missing or duplicate join;
   - every predefined bin boundary;
   - availability mapping;
   - Wilson interval bounds and small-cell labels;
   - exact overall and per-dimension reconciliation;
   - absence of source names, source ranks, and model-feed authorization.
3. Run:
   `python -m pytest tests/test_consensus_decision_error_audit.py -q`
   and confirm the expected failures.
4. Implement the minimum pure helpers and builder needed to pass.
5. Re-run the focused test file until green.

### Task 2: Build and validate the committed audit artifact

**Files:**
- Modify: `scripts/audit_consensus_decisions.py`
- Create: `data/validation/valucast_consensus_decision_error_audit.json`
- Modify: `tests/test_consensus_decision_error_audit.py`

1. Add a CLI with overridable root/input/output paths for tests.
2. Record scorecard and ordered archive-manifest SHA-256 hashes.
3. Require exact agreement with the scorecard's `decided_count`, `wins`, and
   `decided_rate`.
4. Build the artifact against committed July 31 inputs.
5. Add a committed-artifact test that rebuilds in memory and compares the
   stable payload after excluding `generated_at`.
6. Run the focused tests and inspect the artifact for forbidden source keys or
   model/publication authorization.

### Task 3: Interpret evidence without selecting a model on the audit sample

**Files:**
- Create: `docs/audit-2026-07-31-consensus-decision-errors.md`

1. Identify only segments with at least 20 decisions; retain all smaller cells
   in the JSON but label them insufficient in prose.
2. Keep wins, moved-away calls, and retractions separate.
3. State the matched-control result only at the frozen overall level.
4. Map supported themes to the existing development-density,
   position-by-youth, or post-2026 registrations.
5. Record unsupported themes and any tempting player-specific explanation as
   explicit non-actions.
6. If no genuinely distinct cohort-wide hypothesis survives, register nothing
   new. If one does survive, document it as exploratory and future-only; do not
   run it in this plan.

### Task 4: Verify invariants and prepare review

**Files:**
- Verify only: `prospects/rank_v1.py`, `prospects/pitcher_features.py`, frozen
  forward-evidence files, workflows, and public templates remain unchanged.

1. Run:
   `python -m pytest tests/test_consensus_decision_error_audit.py tests/test_aotc_scorecard.py -q`
2. Run the most relevant frozen/governance contract tests identified by `rg`.
3. Run `git diff --check` and inspect `git diff --stat` plus `git status`.
4. Confirm no scoring, rank, value, cap, Role Watch, publication, workflow, or
   public-surface file changed.
5. Commit in logical units and push the review branch only outside restricted
   operational windows. Do not dispatch a workflow.
