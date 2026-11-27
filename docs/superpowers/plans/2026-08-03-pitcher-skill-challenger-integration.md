# Pitcher Skill Challenger Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the already-registered ValuCast pitcher-skill challenger onto current master while preserving its unspent look and proving it is unreachable from production.

**Architecture:** Rebase the existing `codex/mlb-pitcher-skill-challenger` branch, verify its commit chronology and research boundary, then merge it into the program branch. Do not run the registered result command.

**Tech Stack:** Git, Python 3, pytest.

## Global Constraints

- Do not copy Stockyard code, formulas, labels, private data, or brand names.
- Keep the frozen incumbent projection, opportunity, role, cap, veto, Rank v1, values, Role Watch, and failed-decay flag unchanged.
- Do not create `data/validation/mlb_pitcher_skill_challenger_result.json`.
- Do not invoke the registered outer scorer.
- The existing registration commit must remain earlier than acquisition and evaluator commits.

---

### Task 1: Rebase and chronology verification

**Files:**
- Existing worktree: `.worktrees/mlb-pitcher-skill-challenger`
- Existing branch: `codex/mlb-pitcher-skill-challenger`

- [ ] **Step 1: Prove the worktree is clean and the look unspent**

Run:

```powershell
git status --short --branch
Test-Path data/validation/mlb_pitcher_skill_challenger_result.json
git log --reverse --format="%H %s" origin/master..HEAD
```

Expected: clean worktree; result path is `False`; design, plan, and registration commits precede acquisition/evaluator commits.

- [ ] **Step 2: Rebase on current master**

Run:

```powershell
git fetch origin
git rebase origin/master
```

Expected: rebase completes without inventing substantive conflict resolutions. If model or registration content conflicts, stop and report instead of guessing.

- [ ] **Step 3: Re-run chronology and unspent checks**

Run the commands from Step 1 again. Expected: same semantic order and absent result artifact.

- [ ] **Step 4: Push the rebased candidate safely**

Run:

`git push --force-with-lease origin codex/mlb-pitcher-skill-challenger`

Expected: push succeeds without overwriting unexpected remote work.

### Task 2: Research-boundary and data-provenance verification

**Files:**
- Verify: `projections/data/pitching_statcast.py`
- Verify: `projections/models/pitcher_skill_challenger.py`
- Verify: `projections/backtest/pitcher_skill_challenger_harness.py`
- Verify: `scripts/fetch_mlb_pitcher_statcast.py`
- Verify: `scripts/run_mlb_pitcher_skill_challenger.py`
- Test: `tests/test_pitching_statcast.py`
- Test: `tests/test_pitcher_skill_challenger.py`
- Test: `tests/test_mlb_pitcher_skill_challenger_runner.py`
- Test: `tests/test_mlb_pitcher_skill_registration.py`

- [ ] **Step 1: Run the four focused suites without the outer result command**

Run:

```powershell
python -m pytest tests/test_pitching_statcast.py tests/test_pitcher_skill_challenger.py tests/test_mlb_pitcher_skill_challenger_runner.py tests/test_mlb_pitcher_skill_registration.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Prove no production importer exists**

Run:

```powershell
rg -n "pitcher_skill_challenger|mlb_pitcher_skill_challenger" app.py prospects projections scripts .github templates web
```

Expected: matches only inside the research module/runner and tests; no import from served projections, app, Rank v1, workflows, templates, or web stores.

- [ ] **Step 3: Prove the registration boundaries mechanically**

Run:

```powershell
python -m pytest tests/test_mlb_pitcher_skill_registration.py -q
git diff --check origin/master...HEAD
```

Expected: registration hashes/order/frozen values pass; diff check is clean.

- [ ] **Step 4: Review exact fallback and fold tests**

Confirm the focused suites contain and pass assertions for:

```python
assert candidate == control  # when Statcast coverage is unavailable
assert max(train_seasons) < test_season
assert report["feeds_live_projection"] is False
assert report["feeds_rank_or_value"] is False
assert report["claim_eligible"] is False
```

If any assertion is absent, add the smallest failing regression test, run it red, add the minimum guard in the shared research function, and rerun green before continuing.

### Task 3: Merge the candidate into the program branch without spending the look

**Files:**
- Target worktree: `.worktrees/hkb-daily-refresh`
- Target branch: `codex/prospect-evidence-improvement`

- [ ] **Step 1: Merge the rebased branch**

Run:

```powershell
git merge --no-ff codex/mlb-pitcher-skill-challenger -m "merge: add registered pitcher skill challenger"
```

Expected: merge succeeds; no result artifact is created.

- [ ] **Step 2: Run focused suites on the combined branch**

Run the four-suite command from Task 2. Expected: all tests pass.

- [ ] **Step 3: Verify the look remains unspent**

Run:

```powershell
Test-Path data/validation/mlb_pitcher_skill_challenger_result.json
git status --short
```

Expected: `False`; only intentional program changes are present.
