# Opportunity Clamp Honesty Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fail closed when an H+P opportunity projection was clamped instead of publishing a false role and zero-volume judgment.

**Architecture:** Reuse the existing role-contract blocker list at the artifact boundary and the existing `_artifact_context_for_row` mapper at the public boundary. No template-specific patch is needed because web and share-card consumers already share that mapper.

**Tech Stack:** Python, Flask/Jinja, pytest, JSON artifacts.

## Global Constraints

- Preserve rankings, values, scoring, projection math, the model freeze, and the failed-decay flag.
- Add no dependencies, workflows, or new public artifacts.
- Keep active-roster and availability context visible.

---

### Task 1: Block and suppress clamped opportunity

**Files:**
- Modify: `mlb/playing_time_role.py`
- Modify: `app.py`
- Modify: `scripts/validate_playing_time_role_tracker.py`
- Test: `tests/test_playing_time_role_tracker.py`
- Test: `tests/test_redraft_player_card.py`

**Interfaces:**
- Consumes: projection metadata field `remaining_opportunity_clamped: bool`.
- Produces: `role_context_status="blocked"`, blocker `remaining_opportunity_clamped`, and public role context with `Not rated` plus no volume.

- [ ] **Step 1: Write failing contract and public-mapper tests**

Add one tracker test that builds an active hitter with clamped opportunity and
asserts a blocked status/blocker. Add one mapper test that supplies such a
profile and asserts `Not rated`, hidden volume, retained roster context, and
the clamp explanation.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest tests/test_playing_time_role_tracker.py -k clamped tests/test_redraft_player_card.py -k clamped -q
```

Expected: failures because the clamp is ignored and zero remains public.

- [ ] **Step 3: Implement the minimal shared guards**

In `_role_contract_fields`, add `remaining_opportunity_clamped` to blockers.
Include the boolean on each profile. In `_artifact_context_for_row`, when the
status is blocked, set `projected_role_label` to `Not rated`, set
`projected_volume` to `None`, and replace the basis with the honest clamp copy.
Teach the validator to reject a clamped profile marked ready.

- [ ] **Step 4: Run focused and neighboring tests**

Run:

```powershell
python -m pytest tests/test_playing_time_role_tracker.py tests/test_redraft_player_card.py tests/test_scouting_page.py tests/test_card_intelligence.py -q
```

Expected: all pass.

- [ ] **Step 5: Verify scope**

Run:

```powershell
git diff --check
git diff --name-only
```

Expected: only the documented code, tests, spec, and plan files change; no
generated artifacts or scoring files.
