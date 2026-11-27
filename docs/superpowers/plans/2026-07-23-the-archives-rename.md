# The Archives Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the public Board Time Machine surface to **The Archives** without changing its route, data, or behavior.

**Architecture:** Change only user-facing strings in the shared navigation, archived-board template, and methodology. Update the existing route assertions first to prove the old copy fails, then make the smallest template edit that passes.

**Tech Stack:** Flask/Jinja templates, Python `unittest` assertions run through pytest.

## Global Constraints

- Keep `/board`, `/board/<date>`, `#board-time-machine`, Python names, filenames, CSS selectors, and archive behavior unchanged.
- Do not change models, rankings, values, data, workflows, schedules, or deployment.
- Do not edit historical plan documents.
- Preserve the user's three untracked files.

---

### Task 1: Rename the public surface

**Files:**
- Modify: `tests/test_app.py`
- Modify: `templates/base.html`
- Modify: `templates/board_time_machine.html`
- Modify: `templates/methodology.html`

**Interfaces:**
- Consumes: existing `/board` and `/methodology` rendered HTML
- Produces: public label `The Archives` with unchanged URLs and internal identifiers

- [ ] **Step 1: Change the existing assertions first**

In `tests/test_app.py`, keep the existing test function names but require the new
copy:

```python
def test_methodology_has_board_time_machine_section(self):
    response, html = self._get("/methodology")
    self.assertEqual(response.status_code, 200)
    self.assertIn('id="board-time-machine"', html)
    self.assertIn("<h3>The Archives: committed boards, replayed</h3>", html)
    self.assertIn('href="/board">The Archives</a>', html)
    self.assertNotIn("Board Time Machine", html)
    self.assertIn("re-baseline", html)

def test_site_nav_links_time_machine(self):
    _, html = self._get("/board")
    self.assertIn('href="/board" aria-current="page">The Archives</a>', html)
    self.assertIn("<title>The Archives | ValuCast</title>", html)
    self.assertIn("THE ARCHIVES", html)
    self.assertNotIn("Time Machine", html)
```

- [ ] **Step 2: Run the two tests and capture RED**

Run:

```powershell
python -m pytest tests/test_app.py::TestBoardTimeMachineRoute::test_methodology_has_board_time_machine_section tests/test_app.py::TestBoardTimeMachineRoute::test_site_nav_links_time_machine -q
```

Expected: both tests fail because the rendered templates still say Time
Machine.

- [ ] **Step 3: Make the public-copy edits**

Use these exact replacements:

```text
templates/base.html
Time Machine -> The Archives

templates/board_time_machine.html
Board Time Machine | ValuCast -> The Archives | ValuCast
TIME MACHINE -> THE ARCHIVES
BOARD TIME MACHINE -> THE ARCHIVES
How the Time Machine works -> How The Archives works

templates/methodology.html
Board Time Machine: the committed board, replayed
  -> The Archives: committed boards, replayed
Board Time Machine
  -> The Archives
```

Do not rename the `#board-time-machine` anchor.

- [ ] **Step 4: Run the two tests and capture GREEN**

Run:

```powershell
python -m pytest tests/test_app.py::TestBoardTimeMachineRoute::test_methodology_has_board_time_machine_section tests/test_app.py::TestBoardTimeMachineRoute::test_site_nav_links_time_machine -q
```

Expected: `2 passed`.

- [ ] **Step 5: Run all archived-board tests**

Run:

```powershell
python -m pytest tests/test_board_time_machine_store.py tests/test_app.py::TestBoardTimeMachineRoute -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the rename**

Run:

```powershell
git add -- tests/test_app.py templates/base.html templates/board_time_machine.html templates/methodology.html
git diff --cached --check
git commit -m "Rename Board Time Machine to The Archives"
```

Expected: one implementation commit containing only the four named files.

---

### Task 2: Verify and publish

**Files:**
- Verify only: the committed branch

**Interfaces:**
- Consumes: Task 1 commit
- Produces: a pull request with successful local and GitHub checks

- [ ] **Step 1: Run the full suite**

Run:

```powershell
python -m pytest -q
```

Expected: exit code `0` with no failures.

- [ ] **Step 2: Verify exact scope**

Run:

```powershell
git status --short --branch
git diff --check master...HEAD
git diff --name-status master...HEAD
```

Expected: only the design, plan, three templates, and `tests/test_app.py`
differ from `master`.

- [ ] **Step 3: Push and open a draft pull request**

Run:

```powershell
git push -u origin codex/the-archives-rename
gh pr create --draft --base master --head codex/the-archives-rename --title "Rename Board Time Machine to The Archives" --body "## Summary`n- rename the public historical-board surface to The Archives`n- preserve routes, data, and behavior`n- update the existing copy assertions`n`n## Verification`n- focused archived-board tests`n- full pytest suite"
```

Expected: a draft pull-request URL.

- [ ] **Step 4: Verify GitHub CI before merge**

Run:

```powershell
gh pr checks --watch
```

Expected: `pytest` passes before the PR is merged.
