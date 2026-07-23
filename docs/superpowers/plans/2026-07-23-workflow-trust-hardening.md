# Workflow Trust Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make pull-request CI validate committed artifacts and pin every existing first-party GitHub Action reference to an immutable commit.

**Architecture:** Reuse `scripts/run_daily_public_build.py --only validate`, which is already the daily refresh's canonical validation gate. Extend the existing workflow-wiring contract test, then make only the YAML edits required to satisfy it.

**Tech Stack:** GitHub Actions YAML, Python standard library, pytest.

## Global Constraints

- Add no scripts or dependencies.
- Add no branch protection or repository rules.
- Do not rebuild data, dispatch workflows, deploy, or change production.
- Do not change models, rankings, values, caps, Role Watch, or publication.
- Preserve the user's unrelated untracked files.

---

### Task 1: Enforce committed-artifact validation and immutable Action pins

**Files:**
- Modify: `tests/test_daily_workflow_wiring.py`
- Modify: `.github/workflows/tests.yml`
- Modify: `.github/workflows/daily-public-data.yml`
- Modify: `.github/workflows/prospect-shadow.yml`
- Modify: `.github/workflows/roster-pulse.yml`
- Modify: `tests/test_public_data_refresh.py`

**Interfaces:**
- Consumes: `scripts/run_daily_public_build.py --only validate`
- Produces: PR CI that fails on an invalid committed artifact and workflow files whose existing `actions/checkout` and `actions/setup-python` references are fixed to verified 40-character commits.

- [ ] **Step 1: Add the failing workflow contract test**

Add `import re` beside the existing imports in
`tests/test_daily_workflow_wiring.py`, then add:

```python
def test_pr_ci_validates_artifacts_and_pins_first_party_actions():
    expected_pins = {
        "checkout": "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
        "setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
    }
    tests_workflow = Path(".github/workflows/tests.yml").read_text(encoding="utf-8")
    validate = "run: python scripts/run_daily_public_build.py --only validate"
    pytest = "run: python -m pytest -q"
    assert validate in tests_workflow
    assert tests_workflow.index(validate) < tests_workflow.index(pytest)

    action_ref = re.compile(
        r"uses:\s+actions/(checkout|setup-python)@([0-9a-f]{40})\s+#\s+(v5|v6)$"
    )
    found: set[str] = set()
    for workflow in Path(".github/workflows").glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses: actions/checkout@" not in line and (
                "uses: actions/setup-python@" not in line
            ):
                continue
            match = action_ref.search(line)
            assert match, f"{workflow}: mutable or unlabeled action reference: {line}"
            action, sha, version = match.groups()
            assert sha == expected_pins[action]
            assert version == ("v5" if action == "checkout" else "v6")
            found.add(action)
    assert found == set(expected_pins)
```

- [ ] **Step 2: Run the focused test and capture RED**

Run:

```powershell
python -m pytest tests/test_daily_workflow_wiring.py::test_pr_ci_validates_artifacts_and_pins_first_party_actions -q
```

Expected: FAIL because `.github/workflows/tests.yml` lacks the validation step.
The action references are also still mutable major-version tags.

- [ ] **Step 3: Add the canonical validation gate to PR CI**

In `.github/workflows/tests.yml`, insert this step after dependency
installation and before `Run test suite`:

```yaml
      - name: Validate committed artifacts
        run: python scripts/run_daily_public_build.py --only validate
```

- [ ] **Step 4: Pin the existing first-party Action references**

Replace every existing checkout reference in `.github/workflows/*.yml` with:

```yaml
      - uses: actions/checkout@fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09 # v5
```

Replace every existing setup-python reference with:

```yaml
      - uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1 # v6
```

The digests were resolved directly from the official
`actions/checkout` `v5` and `actions/setup-python` `v6` tag refs on
2026-07-23.

- [ ] **Step 4a: Keep the synchronization test focused on synchronization**

In `tests/test_public_data_refresh.py`, replace the two mutable-tag assertions
with action-presence assertions:

```python
    assert "uses: actions/checkout@" in workflow
    assert "uses: actions/setup-python@" in workflow
```

The new workflow contract test owns exact pin enforcement; this existing test
continues to own checkout, concurrency, and master-synchronization wiring.

- [ ] **Step 5: Run the focused test and capture GREEN**

Run:

```powershell
python -m pytest tests/test_daily_workflow_wiring.py::test_pr_ci_validates_artifacts_and_pins_first_party_actions -q
```

Expected: `1 passed`.

- [ ] **Step 6: Run workflow and artifact verification**

Run:

```powershell
python -m pytest tests/test_daily_workflow_wiring.py -q
python scripts/run_daily_public_build.py --only validate
python -m pytest -q
git diff --check
```

Expected: every command exits `0`.

- [ ] **Step 7: Confirm scope and commit**

Run:

```powershell
git status --short
git diff -- .github/workflows tests/test_daily_workflow_wiring.py
```

Confirm that only `tests.yml`, the other three workflows containing existing
Action references, and the two workflow test files changed. Leave all unrelated
untracked files untouched.

Commit:

```powershell
git add -- .github/workflows/tests.yml .github/workflows/daily-public-data.yml .github/workflows/prospect-shadow.yml .github/workflows/roster-pulse.yml tests/test_daily_workflow_wiring.py tests/test_public_data_refresh.py
git commit -m "Harden workflow trust checks"
```
