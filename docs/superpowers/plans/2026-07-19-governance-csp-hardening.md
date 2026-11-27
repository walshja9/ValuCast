# Governance and CSP Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Peak Projection's public governance match its display-only evidence and remove the CSP-incompatible HTMX trigger filter.

**Architecture:** Keep both fixes at their existing policy boundaries. The registry validator enforces evidence consistency; public status copy reads honestly; the existing board form keeps its change trigger while the one excluded input stops propagation locally.

**Tech Stack:** Python 3, Flask/Jinja, HTMX 2.0.4, unittest/pytest, Playwright.

## Global Constraints

- Do not change ranks, values, model inputs, caps, publication decisions, or held-feature flags.
- Preserve the model freeze and failed decay flag.
- Do not weaken the Content Security Policy.
- Add no dependency and no new abstraction.
- Do not push or deploy.

---

### Task 1: Align Peak public governance with its evidence

**Files:**
- Modify: `data/models/valucast_model_registry.json`
- Modify: `scripts/validate_model_registry.py`
- Modify: `app.py`
- Modify: `templates/scouting.html`
- Test: `tests/test_app.py`
- Test: `tests/test_scouting_page.py`

**Interfaces:**
- Consumes: registry entry `feeds_value`; evidence `source_policy.feeds_live_value`; calibration `validation.ready_for_review`.
- Produces: validator error for contradictory policy; `Display only` public status.

- [ ] **Step 1: Write failing governance tests**

```python
def test_display_only_evidence_cannot_claim_to_feed_value(self):
    # A temporary registry points at the committed display-only Peak evidence.
    # validate(...) must report the contradiction.

def test_peak_public_surfaces_are_display_only():
    # /models omits Peak's feeds-value badge; /intelligence and /scouting say Display only.
```

- [ ] **Step 2: Run the tests and verify the expected failures**

Run: `python -m pytest tests/test_app.py::TestModelRegistryValidator tests/test_scouting_page.py -q`

Expected: FAIL because the validator permits the contradiction and public copy says `Ready`/`Live`.

- [ ] **Step 3: Apply the minimum policy and copy changes**

```python
policy = evidence_payload.get("source_policy") or {}
if entry.get("feeds_value") and policy.get("feeds_live_value") is False:
    errs.append(f"{eid}: feeds_value contradicts display-only evidence")
```

Set Peak's registry `feeds_value` to `false`; change only the Peak status labels and explanatory copy to `Display only`.

- [ ] **Step 4: Run the targeted tests and verify they pass**

Run: `python -m pytest tests/test_app.py::TestModelsRegistryPage tests/test_app.py::TestModelRegistryValidator tests/test_scouting_page.py -q`

Expected: PASS.

### Task 2: Remove the CSP-incompatible HTMX filter

**Files:**
- Modify: `templates/index.html`
- Modify: `templates/partials/setup_dynasty.html`
- Create: `tests/test_ui_htmx_csp.py`

**Interfaces:**
- Consumes: board form `change` events and `#league-url-input`.
- Produces: normal HTMX refreshes for board controls; no refresh for league URL edits; no CSP console error.

- [ ] **Step 1: Write the failing browser regression**

```python
def test_league_url_change_is_csp_clean_and_does_not_refresh_rankings():
    # Start the Flask app, capture console errors and /rankings requests,
    # open the dynasty board, edit the league URL, and assert both lists are empty.
```

- [ ] **Step 2: Run it and verify the expected failure**

Run: `python -m pytest tests/test_ui_htmx_csp.py -q`

Expected: FAIL with the HTMX CSP `EvalError` and an unintended `/rankings` request.

- [ ] **Step 3: Apply the minimum declarative fix**

```html
hx-trigger="change delay:100ms, keyup changed delay:300ms from:#search-input"
```

Add `onchange="event.stopPropagation()"` to the existing league URL input.

- [ ] **Step 4: Run the browser test and targeted app tests**

Run: `python -m pytest tests/test_ui_htmx_csp.py tests/test_ui_sort_interaction.py tests/test_app_source.py -q`

Expected: PASS with zero browser console errors.

- [ ] **Step 5: Run full verification and inspect scope**

Run: `python -m pytest -q`

Run: `git diff --check && git status --short && git diff --stat`

Expected: all tests pass; only the planned files and documentation are modified.
