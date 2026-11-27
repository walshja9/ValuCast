# Forward Ledger Plain-Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the current Forward Ledger result in plain English before its statistical detail without weakening any disclosure.

**Architecture:** Reuse the existing server-rendered scoreboard view and its artifact fields. Add sign-aware Jinja copy in the existing template; do not create a helper, JavaScript, dependency, or new data field.

**Tech Stack:** Flask, Jinja, pytest.

## Global Constraints

- Display/copy only; all scoring and artifacts are frozen.
- Keep the confidence interval, sample size, provisional warning, one-board comparison, registration metadata, and funnel accounting visible.
- Do not change the share-card renderer, hold gates, Role Watch, League Connect, or model flags.
- Keep `PITCHER_STALE_PEDIGREE_DECAY_ENABLED = False`.

---

### Task 1: Translate the live page

**Files:**
- Modify: `tests/test_forward_scoreboard_page.py`
- Modify: `templates/forward_scoreboard.html`

**Interfaces:**
- Consumes: existing `sc.median_lead_days`, `sc.pool_size`, funnel counts, cohort count, CI, and provisional fields.
- Produces: the same `/scoreboard` response and URLs with plain-language HTML copy.

- [ ] **Step 1: Write the failing page contract**

In `test_scoreboard_renders_artifact_numbers`, replace the old hero assertion and add assertions for:

```python
assert "EARLY RESULTS: 2 DAYS AHEAD" in html
assert "Across 59 settled calls" in html
assert "too early to declare a win" in html
assert "Moved our way" in html
assert "Moved against us" in html
assert "Calls we changed" in html
assert "Still waiting" in html
assert "Anticipation Score" in html
```

Retain the existing CI, provisional, registration, cohort, and funnel assertions.

- [ ] **Step 2: Verify the contract fails for the missing plain-language copy**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_forward_scoreboard_page.py::test_scoreboard_renders_artifact_numbers
```

Expected: FAIL on `EARLY RESULTS: 2 DAYS AHEAD`.

- [ ] **Step 3: Implement the minimal template copy**

In `templates/forward_scoreboard.html`:

- derive a rounded `lead_days` Jinja variable from `sc.median_lead_days`;
- render the three sign-aware hero states;
- translate the hero explanation and provisional warning;
- retain `Anticipation Score` as the formal metric label above the existing score/CI;
- rename the four funnel labels and their one-line explanations;
- leave all data fields and technical numbers unchanged.

- [ ] **Step 4: Verify focused behavior**

Run:

```powershell
python -m pytest -q -p no:cacheprovider tests/test_forward_scoreboard_page.py
```

Expected: all tests pass.

- [ ] **Step 5: Verify the full application and responsive page**

Run:

```powershell
python -m pytest -q -p no:cacheprovider
```

Expected: all tests and subtests pass.

Serve with `SCOREBOARD_HOLD=0`, inspect at 1440x1100 and 390x844, and require: HTTP 200, no horizontal overflow, no clipped elements, no broken images, zero console errors, and the technical CI/provisional copy still present.

- [ ] **Step 6: Commit**

```powershell
git add docs/superpowers/specs/2026-07-18-forward-ledger-plain-language-design.md docs/superpowers/plans/2026-07-18-forward-ledger-plain-language.md tests/test_forward_scoreboard_page.py templates/forward_scoreboard.html
git commit -m "copy: explain Forward Ledger plainly"
```
