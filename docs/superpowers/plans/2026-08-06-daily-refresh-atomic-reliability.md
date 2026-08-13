# Daily Refresh Atomic Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep daily publication atomic while preserving completed LLM scouting work across interrupted runs and retrying transient GitHub runner failures later the same day.

**Architecture:** Reuse the existing atomic JSON cache writer and GitHub Actions cache pattern. Checkpoint only newly generated LLM reports, restore/save that file around the existing build step, and replace three morning cron entries with one hourly recovery window guarded by the existing same-day marker preflight.

**Tech Stack:** Python 3.11, pytest, GitHub Actions YAML, existing `actions/cache` v4 pin.

## Global Constraints

- Every build and validator must succeed before the workflow commits or deploys.
- Do not add a dependency, service, workflow, or partial-publication path.
- Keep `timeout-minutes: 120`, `cancel-in-progress: false`, the deploy-key writer, and the fail-loud single push unchanged.
- Preserve the user-owned modification in the original checkout; work only in `D:\CodexWorktrees\ValuCast\refresh-reliability`.

---

### Task 1: Checkpoint successful LLM generations

**Files:**
- Modify: `tests/test_scouting_repository.py`
- Modify: `scouting/repository.py`

**Interfaces:**
- Consumes: existing `_save_llm_cache(entries: dict) -> None` atomic writer and `LLM_CACHE_PATH`.
- Produces: an on-disk cache containing every successful new generation before the next API call begins.

- [ ] **Step 1: Write the failing interruption test**

Add this test after the existing LLM publication tests:

```python
def test_scouting_repository_checkpoints_llm_before_later_interruption(
    tmp_path, monkeypatch
):
    from scouting import report_generator, repository

    calls = 0

    def generate(_grounding, *, client):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        return {
            "text": "A checkpointed model-written read.",
            "model": report_generator.DEFAULT_MODEL,
            "valid": True,
            "hard_ok": True,
            "problems": {"ok": True, "hard_ok": True},
        }

    snapshot_path = _write_snapshot(tmp_path)
    cache_path = Path(tmp_path) / "llm_cache.json"
    monkeypatch.setenv("VALUCAST_SCOUTING_LLM", "1")
    with (
        patch.object(report_generator, "default_client", return_value=object()),
        patch.object(report_generator, "generate_report", side_effect=generate),
        patch.object(repository, "LLM_CACHE_PATH", cache_path),
    ):
        try:
            build_scouting_repository(
                snapshot_path=snapshot_path,
                generated_at="2026-06-16T00:00:00+00:00",
            )
        except KeyboardInterrupt:
            pass
        else:
            raise AssertionError("second generation should interrupt the build")

    assert calls == 2
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(cache["entries"]) == {"1_hitter"}
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```powershell
.\.venv\Scripts\python -m pytest -q tests\test_scouting_repository.py -k checkpoints_llm_before_later_interruption
```

Expected: FAIL because `llm_cache.json` does not exist; the current writer runs only after the entire loop returns.

- [ ] **Step 3: Add the minimal checkpoint**

In `_attach_llm_reports`, track whether the current result came from a new API generation and reuse the existing writer:

```python
        generated_now = False
        if result is None:
            # existing budget and API handling
            result = {
                # existing result fields
            }
            generated += 1
            generated_now = True
        fresh[key] = result
        if generated_now:
            _save_llm_cache(fresh)
```

Do not write after exact cache reuse; only expensive new generations need interruption durability.

- [ ] **Step 4: Run the test to verify GREEN**

Run the Step 2 command. Expected: `1 passed`.

- [ ] **Step 5: Run the focused scouting file**

Run:

```powershell
.\.venv\Scripts\python -m pytest -q tests\test_scouting_repository.py
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add scouting/repository.py tests/test_scouting_repository.py
git commit -m "fix: checkpoint daily scouting generations"
```

---

### Task 2: Restore progress and extend automatic attempts

**Files:**
- Modify: `tests/test_public_data_refresh.py`
- Modify: `.github/workflows/daily-public-data.yml`

**Interfaces:**
- Consumes: existing `actions/cache/restore` and `actions/cache/save` SHA `0400d5f644dc74513175e3cd8d07132dd4860809`, workflow concurrency group, and preflight marker.
- Produces: hourly scheduled attempts from 11:30 through 19:30 UTC and cross-run recovery for `data/models/valucast_scouting_llm_cache.json`.

- [ ] **Step 1: Write the failing workflow contract test**

Add:

```python
def test_daily_public_workflow_retries_and_preserves_scouting_progress():
    workflow = Path(".github/workflows/daily-public-data.yml").read_text(
        encoding="utf-8"
    )
    cache_sha = "0400d5f644dc74513175e3cd8d07132dd4860809"
    cache_path = "data/models/valucast_scouting_llm_cache.json"
    restore_name = "- name: Restore LLM scouting cache"
    build_name = "- name: Build ValuCast public snapshot gate"
    save_name = "- name: Save LLM scouting cache"

    assert '- cron: "30 11-19 * * *"' in workflow
    assert workflow.count("- cron:") == 1
    assert workflow.count(cache_path) >= 2
    assert f"uses: actions/cache/restore@{cache_sha} # v4.2.4" in workflow
    assert f"uses: actions/cache/save@{cache_sha} # v4.2.4" in workflow
    assert "scouting-llm-v1-${{ runner.os }}-${{ github.run_id }}" in workflow
    assert "key: ${{ steps.scouting-llm-cache.outputs.cache-primary-key }}" in workflow

    restore = workflow.index(restore_name)
    build = workflow.index(build_name)
    save = workflow.index(save_name)
    assert restore < build < save
    save_step = workflow[save : workflow.find("\n      - name:", save + 1)]
    assert "if: always()" in save_step
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```powershell
.\.venv\Scripts\python -m pytest -q tests\test_public_data_refresh.py -k retries_and_preserves_scouting_progress
```

Expected: FAIL because the hourly cron and scouting Actions cache steps do not exist.

- [ ] **Step 3: Replace the schedule**

Keep the existing explanatory comment but replace the three cron entries with:

```yaml
    # Hourly recovery window: the preflight marker skips remaining attempts after
    # today's atomic refresh commit exists. Later slots recover runner congestion
    # or a failed attempt without human dispatch.
    - cron: "30 11-19 * * *"
```

- [ ] **Step 4: Restore the scouting cache before the build**

Add after the existing AAA-Statcast restore:

```yaml
      - name: Restore LLM scouting cache
        id: scouting-llm-cache
        uses: actions/cache/restore@0400d5f644dc74513175e3cd8d07132dd4860809 # v4.2.4
        with:
          path: data/models/valucast_scouting_llm_cache.json
          key: scouting-llm-v1-${{ runner.os }}-${{ github.run_id }}
          restore-keys: |
            scouting-llm-v1-${{ runner.os }}-
```

- [ ] **Step 5: Save the scouting cache after the build**

Add after the existing AAA-Statcast save:

```yaml
      - name: Save LLM scouting cache
        if: always()
        uses: actions/cache/save@0400d5f644dc74513175e3cd8d07132dd4860809 # v4.2.4
        with:
          path: data/models/valucast_scouting_llm_cache.json
          key: ${{ steps.scouting-llm-cache.outputs.cache-primary-key }}
```

- [ ] **Step 6: Run the workflow test to verify GREEN**

Run the Step 2 command. Expected: `1 passed`.

- [ ] **Step 7: Run focused workflow tests**

Run:

```powershell
.\.venv\Scripts\python -m pytest -q tests\test_public_data_refresh.py tests\test_daily_workflow_wiring.py
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```powershell
git add .github/workflows/daily-public-data.yml tests/test_public_data_refresh.py
git commit -m "ci: retry atomic refresh and preserve scouting progress"
```

---

### Task 3: Verify the complete change

**Files:**
- Verify only; no production files added.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: fresh evidence that the branch is safe to publish.

- [ ] **Step 1: Run all directly affected tests**

```powershell
.\.venv\Scripts\python -m pytest -q tests\test_scouting_repository.py tests\test_public_data_refresh.py tests\test_daily_workflow_wiring.py
```

Expected: all tests pass.

- [ ] **Step 2: Run the repository PR suite**

```powershell
.\.venv\Scripts\python -m pytest -q
```

Expected: zero failures.

- [ ] **Step 3: Re-sync and inspect**

```powershell
git fetch origin master
git rebase origin/master
git diff --check origin/master...HEAD
git diff --stat origin/master...HEAD
git status --short --branch
gh pr list --state open --limit 100
```

Expected: clean rebase, no whitespace errors, only the approved design/plan plus four implementation/test files, and no overlapping open PR.
