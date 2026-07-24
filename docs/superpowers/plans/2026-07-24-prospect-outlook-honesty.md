# Prospect Outlook Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the contradictory uncalibrated Peak Outlook from public prospect cards and make the Salas-style deterministic read describe present statistical shape.

**Architecture:** Keep every model and stored peak field unchanged. Stop consuming the peak fields in the two public renderers, and correct the one deterministic text family that produced the reported contradiction.

**Tech Stack:** Python, Flask/Jinja, Pillow, pytest

## Global Constraints

- Do not change ranks, values, model inputs, model outputs, pitcher publication decisions, the model freeze, or the failed-decay flag.
- Keep the underlying peak artifact available for shadow research.
- Add no dependency or new abstraction.

---

### Task 1: Remove the unsupported public Peak Outlook

**Files:**
- Modify: `templates/partials/player_detail_dynasty.html`
- Modify: `app.py`
- Test: `tests/test_player_card_display_additions.py`
- Test: `tests/test_card_intelligence.py`

**Interfaces:**
- Consumes: existing `row.has_peak_projection` and peak-label properties.
- Produces: public HTML and PNG that no longer consume those fields.

- [ ] **Step 1: Write failing render tests**

Add assertions that a prospect with peak data retains that data on the row but
renders neither `Peak Outlook` nor `Ceiling scenario` in HTML. Patch the PNG
text-drawing spy and assert neither label is drawn.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest -q tests/test_player_card_display_additions.py tests/test_card_intelligence.py
```

Expected: failures because both public renderers still consume Peak Outlook.

- [ ] **Step 3: Remove the two render blocks**

Delete the `row.has_peak_projection` block from
`templates/partials/player_detail_dynasty.html`. In `app.py`, remove
`peak_outlook`, its layout reservation, and its drawing block; retain the normal
read and projected-shape layout.

- [ ] **Step 4: Run the tests and verify GREEN**

Run the command from Step 2.

Expected: all tests pass.

### Task 2: Correct the deterministic contact/light-power read

**Files:**
- Modify: `web/prospect_percentiles.py`
- Test: `tests/test_card_intelligence.py`

**Interfaces:**
- Consumes: the existing `hitter-contact-light-power` thresholds.
- Produces: present-shape copy with no ceiling or floor claim.

- [ ] **Step 1: Write the failing Salas-style regression**

Create a 285-PA hitter row with 15.1 K% and .137 ISO. Assert its deterministic
read includes `contact-first table-setter shape` and excludes `ceiling` and
`floor`.

- [ ] **Step 2: Run the regression and verify RED**

Run:

```powershell
python -m pytest -q tests/test_card_intelligence.py -k contact_light_power
```

Expected: failure because the current template says `Table-setter ceiling` and
`floor`.

- [ ] **Step 3: Make the minimal copy correction**

Replace the two `hitter-contact-light-power` role variants with present-shape
language. Do not change thresholds or any numeric field.

- [ ] **Step 4: Run the regression and verify GREEN**

Run the command from Step 2.

Expected: pass.

### Task 3: Verify the public boundary

**Files:**
- Verify only

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: evidence that the display-only fix is safe.

- [ ] **Step 1: Run focused tests**

```powershell
python -m pytest -q tests/test_card_intelligence.py tests/test_scouting_repository.py tests/test_player_card_display_additions.py
```

- [ ] **Step 2: Run the full suite**

```powershell
python -m pytest -q
```

- [ ] **Step 3: Check scope**

```powershell
git diff --check
git status --short
git diff --stat origin/master...
```

Expected: only the spec, plan, two renderers, deterministic copy, and focused
tests differ; no model or generated data artifact changes.

