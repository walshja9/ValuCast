# Refresh Deploy-Key Protection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require pull requests and the existing `pytest` check on `master` while preserving the three scheduled workflows that publish generated artifacts directly.

**Architecture:** The three master-writing workflows authenticate checkout with one repository-scoped SSH deploy key and retain only read access on the built-in token. After that code is merged, one repository ruleset requires pull requests and `pytest`, blocks deletion and force pushes, and permits deploy-key writes as the sole automation bypass.

**Tech Stack:** GitHub Actions YAML, Python/pytest workflow contract tests, GitHub CLI, PowerShell, GitHub repository rulesets, Ed25519 SSH.

## Global Constraints

- Do not change models, rankings, values, data construction, refresh schedules, generated-artifact allowlists, or production deployment.
- Do not add scripts, dependencies, accounts, GitHub Apps, or additional branch rules.
- Keep `tests.yml` and every non-writing workflow keyless.
- Keep exactly one repository deploy key while the deploy-key bypass exists.
- Never print, commit, or persist the private key outside the encrypted `REFRESH_DEPLOY_KEY` Actions secret.
- Do not dispatch a refresh solely to test authentication.
- Preserve the model freeze, failed-decay flag, and pitcher publication policy.

---

### Task 1: Enforce the writer-workflow credential contract

**Files:**
- Modify: `tests/test_daily_workflow_wiring.py`
- Modify: `.github/workflows/daily-public-data.yml`
- Modify: `.github/workflows/prospect-shadow.yml`
- Modify: `.github/workflows/roster-pulse.yml`

**Interfaces:**
- Consumes: workflow files under `.github/workflows/*.yml`
- Produces: one contract requiring exactly the three `git push origin master` workflows to use `secrets.REFRESH_DEPLOY_KEY` and `contents: read`

- [ ] **Step 1: Add the failing contract test**

Append this test before the AAA-Statcast section in
`tests/test_daily_workflow_wiring.py`:

```python
def test_master_writers_use_only_the_refresh_deploy_key():
    expected_writers = {
        "daily-public-data.yml",
        "prospect-shadow.yml",
        "roster-pulse.yml",
    }
    workflows = {
        path.name: path.read_text(encoding="utf-8")
        for path in Path(".github/workflows").glob("*.yml")
    }
    writers = {
        name for name, workflow in workflows.items() if "git push origin master" in workflow
    }
    assert writers == expected_writers

    key = "ssh-key: ${{ secrets.REFRESH_DEPLOY_KEY }}"
    for name, workflow in workflows.items():
        assert (key in workflow) == (name in expected_writers)
        if name in expected_writers:
            assert "permissions:\n  contents: read" in workflow
            assert "permissions:\n  contents: write" not in workflow
```

- [ ] **Step 2: Run the focused test and capture RED**

Run:

```powershell
python -m pytest tests/test_daily_workflow_wiring.py::test_master_writers_use_only_the_refresh_deploy_key -q
```

Expected: FAIL because the three writer workflows do not yet reference
`REFRESH_DEPLOY_KEY` and still request `contents: write`.

- [ ] **Step 3: Make the minimum workflow edits**

In each of the three writer workflows, replace:

```yaml
permissions:
  contents: write
```

with:

```yaml
permissions:
  contents: read
```

In each writer workflow's existing pinned `actions/checkout` `with:` block,
add the key without changing `fetch-depth`:

```yaml
          ssh-key: ${{ secrets.REFRESH_DEPLOY_KEY }}
```

Do not edit `.github/workflows/tests.yml`.

- [ ] **Step 4: Run the focused test and capture GREEN**

Run:

```powershell
python -m pytest tests/test_daily_workflow_wiring.py::test_master_writers_use_only_the_refresh_deploy_key -q
```

Expected: `1 passed`.

- [ ] **Step 5: Run the complete workflow contract file**

Run:

```powershell
python -m pytest tests/test_daily_workflow_wiring.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit the tested workflow change**

Run:

```powershell
git add -- tests/test_daily_workflow_wiring.py .github/workflows/daily-public-data.yml .github/workflows/prospect-shadow.yml .github/workflows/roster-pulse.yml
git diff --cached --check
git commit -m "Authenticate refresh writers with deploy key"
```

Expected: one commit containing only the test and three workflow files.

---

### Task 2: Verify the branch and open the pull request

**Files:**
- Verify only: repository tracked files and committed artifacts

**Interfaces:**
- Consumes: Task 1 commit
- Produces: a reviewed branch with successful local and GitHub checks

- [ ] **Step 1: Run the committed-artifact validator**

Run:

```powershell
python scripts/run_daily_public_build.py --only validate
```

Expected: exit code `0`. Existing publication holds may be reported, but no
validator may fail.

- [ ] **Step 2: Run the full local test suite**

Run:

```powershell
python -m pytest -q
```

Expected: exit code `0` with no failed tests.

- [ ] **Step 3: Confirm scope and branch cleanliness**

Run:

```powershell
git status --short --branch
git diff master...HEAD --stat
git diff master...HEAD -- .github/workflows tests/test_daily_workflow_wiring.py docs/superpowers/specs/2026-07-23-refresh-deploy-key-protection-design.md docs/superpowers/plans/2026-07-23-refresh-deploy-key-protection.md
```

Expected: only the design, plan, three workflows, and one test file differ from
`master`; the three known user-owned untracked files remain untouched.

- [ ] **Step 4: Push and open a draft pull request**

Run:

```powershell
git push -u origin codex/refresh-deploy-key-protection
gh pr create --draft --base master --head codex/refresh-deploy-key-protection --title "Protect refresh writers with deploy key" --body "## Summary`n- authenticate only the three master-writing refresh workflows with a repository deploy key`n- reduce their built-in token to read-only`n- add a workflow contract preventing secret spread`n`n## Verification`n- committed-artifact validator`n- full pytest suite"
```

Expected: a draft pull-request URL.

- [ ] **Step 5: Wait for and verify GitHub CI**

Run:

```powershell
gh pr checks --watch
```

Expected: `pytest` succeeds.

---

### Task 3: Provision the repository-scoped credential

**Files:**
- Create remotely: deploy key titled `ValuCast scheduled refresh writer`
- Create remotely: Actions secret `REFRESH_DEPLOY_KEY`
- Create temporarily: `%TEMP%\valucast-refresh-key-*\id_ed25519`

**Interfaces:**
- Consumes: GitHub CLI authentication with repository administration access
- Produces: one write-enabled repository deploy key and one encrypted Actions secret

- [ ] **Step 1: Confirm the credential names are unused**

Run:

```powershell
$existingKeys = gh api repos/walshja9/ValuCast/keys | ConvertFrom-Json
if ($existingKeys.Count -ne 0) { throw "Expected zero deploy keys before provisioning." }
$existingSecret = gh secret list --repo walshja9/ValuCast | Select-String '^REFRESH_DEPLOY_KEY\s'
if ($existingSecret) { throw "REFRESH_DEPLOY_KEY already exists." }
```

Expected: no output and no exception.

- [ ] **Step 2: Generate, upload, verify, and remove the key material**

Run this block as one PowerShell operation:

```powershell
$repo = "walshja9/ValuCast"
$title = "ValuCast scheduled refresh writer"
$tempRoot = [System.IO.Path]::GetTempPath()
$tempDir = Join-Path $tempRoot ("valucast-refresh-key-" + [guid]::NewGuid().ToString("N"))
$keyPath = Join-Path $tempDir "id_ed25519"
$deployKeyId = $null
New-Item -ItemType Directory -Path $tempDir | Out-Null
try {
  ssh-keygen -q -t ed25519 -N '""' -C "valucast-refresh-writer" -f $keyPath
  if ($LASTEXITCODE -ne 0) { throw "ssh-keygen exited $LASTEXITCODE" }

  $publicKey = (Get-Content -LiteralPath "$keyPath.pub" -Raw).Trim()
  $created = gh api --method POST "repos/$repo/keys" -f title="$title" -f key="$publicKey" -F read_only=false | ConvertFrom-Json
  if ($LASTEXITCODE -ne 0) { throw "Deploy-key creation failed." }
  $deployKeyId = $created.id

  Get-Content -LiteralPath $keyPath -Raw | gh secret set REFRESH_DEPLOY_KEY --repo $repo
  if ($LASTEXITCODE -ne 0) { throw "Actions-secret creation failed." }

  $keys = gh api "repos/$repo/keys" | ConvertFrom-Json
  if ($keys.Count -ne 1 -or $keys[0].title -ne $title -or $keys[0].read_only) {
    throw "Deploy-key verification failed."
  }
  if (-not (gh secret list --repo $repo | Select-String '^REFRESH_DEPLOY_KEY\s')) {
    throw "Actions-secret verification failed."
  }
} catch {
  if ($deployKeyId) {
    gh api --method DELETE "repos/$repo/keys/$deployKeyId" | Out-Null
  }
  gh secret delete REFRESH_DEPLOY_KEY --repo $repo 2>$null
  throw
} finally {
  $resolved = [System.IO.Path]::GetFullPath($tempDir)
  $resolvedRoot = [System.IO.Path]::GetFullPath($tempRoot)
  if (-not $resolved.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove non-temp path: $resolved"
  }
  Remove-Item -LiteralPath $resolved -Recurse -Force
}
```

Expected: no private key content in output; one write-enabled deploy key and
the `REFRESH_DEPLOY_KEY` secret exist; the temporary directory is gone.

---

### Task 4: Merge the key-aware workflows

**Files:**
- Merge remotely: pull request from `codex/refresh-deploy-key-protection`

**Interfaces:**
- Consumes: successful Task 2 CI and Task 3 credential
- Produces: key-aware writer workflows on `master`

- [ ] **Step 1: Mark the pull request ready and merge**

Run:

```powershell
gh pr ready
gh pr checks --watch
gh pr merge --merge --delete-branch
```

Expected: the pull request merges only after `pytest` succeeds.

- [ ] **Step 2: Synchronize and verify local `master`**

Run:

```powershell
git switch master
git pull --ff-only origin master
git status --short --branch
```

Expected: local `master` equals `origin/master`; only the three known user-owned
untracked files remain.

- [ ] **Step 3: Verify key wiring from merged GitHub content**

Run:

```powershell
foreach ($workflow in @("daily-public-data.yml", "prospect-shadow.yml", "roster-pulse.yml")) {
  $content = gh api "repos/walshja9/ValuCast/contents/.github/workflows/$workflow" --jq .content
  $text = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String(($content -replace '\s', '')))
  if ($text -notmatch [regex]::Escape('ssh-key: ${{ secrets.REFRESH_DEPLOY_KEY }}')) {
    throw "$workflow is not key-aware on master."
  }
}
```

Expected: no exception.

---

### Task 5: Activate and verify default-branch protection

**Files:**
- Create remotely: repository ruleset `Protect default branch`

**Interfaces:**
- Consumes: key-aware workflows on `master`, deploy key, Actions secret, GitHub Actions integration ID `15368`
- Produces: active pull-request and `pytest` protection with deploy-key bypass

- [ ] **Step 1: Confirm no ruleset exists**

Run:

```powershell
$rulesets = gh api repos/walshja9/ValuCast/rulesets | ConvertFrom-Json
if ($rulesets.Count -ne 0) { throw "Expected zero rulesets before activation." }
```

Expected: no output and no exception.

- [ ] **Step 2: Create the active ruleset**

Run:

```powershell
$ruleset = @{
  name = "Protect default branch"
  target = "branch"
  enforcement = "active"
  bypass_actors = @(
    @{
      actor_id = $null
      actor_type = "DeployKey"
      bypass_mode = "always"
    }
  )
  conditions = @{
    ref_name = @{
      include = @("~DEFAULT_BRANCH")
      exclude = @()
    }
  }
  rules = @(
    @{ type = "deletion" }
    @{ type = "non_fast_forward" }
    @{
      type = "pull_request"
      parameters = @{
        allowed_merge_methods = @("merge", "squash", "rebase")
        dismiss_stale_reviews_on_push = $false
        require_code_owner_review = $false
        require_last_push_approval = $false
        required_approving_review_count = 0
        required_review_thread_resolution = $false
      }
    }
    @{
      type = "required_status_checks"
      parameters = @{
        do_not_enforce_on_create = $true
        required_status_checks = @(
          @{
            context = "pytest"
            integration_id = 15368
          }
        )
        strict_required_status_checks_policy = $true
      }
    }
  )
}
$headers = @{
  Accept = "application/vnd.github+json"
  Authorization = "Bearer $(gh auth token)"
  "X-GitHub-Api-Version" = "2022-11-28"
}
$createdRuleset = Invoke-RestMethod -Method Post -Uri "https://api.github.com/repos/walshja9/ValuCast/rulesets" -Headers $headers -ContentType "application/json" -Body ($ruleset | ConvertTo-Json -Depth 10)
if ($createdRuleset.enforcement -ne "active") { throw "Ruleset was not activated." }
```

Expected: one active ruleset is created.

- [ ] **Step 3: Read back and assert the final security state**

Run:

```powershell
$rulesets = gh api repos/walshja9/ValuCast/rulesets | ConvertFrom-Json
if ($rulesets.Count -ne 1) { throw "Expected exactly one ruleset." }
$ruleset = gh api "repos/walshja9/ValuCast/rulesets/$($rulesets[0].id)" | ConvertFrom-Json
$keys = gh api repos/walshja9/ValuCast/keys | ConvertFrom-Json
$secret = gh secret list --repo walshja9/ValuCast | Select-String '^REFRESH_DEPLOY_KEY\s'

if ($ruleset.name -ne "Protect default branch" -or $ruleset.enforcement -ne "active") {
  throw "Ruleset identity or enforcement is wrong."
}
if ($ruleset.conditions.ref_name.include -notcontains "~DEFAULT_BRANCH") {
  throw "Ruleset does not target the default branch."
}
if ($ruleset.bypass_actors.Count -ne 1 -or $ruleset.bypass_actors[0].actor_type -ne "DeployKey") {
  throw "DeployKey is not the sole bypass actor."
}
$ruleTypes = @($ruleset.rules | ForEach-Object type)
foreach ($requiredType in @("deletion", "non_fast_forward", "pull_request", "required_status_checks")) {
  if ($ruleTypes -notcontains $requiredType) { throw "Missing $requiredType rule." }
}
$pullRequestRule = $ruleset.rules | Where-Object type -eq "pull_request"
if ($pullRequestRule.parameters.required_approving_review_count -ne 0) {
  throw "Pull-request rule unexpectedly requires an approval."
}
$statusRule = $ruleset.rules | Where-Object type -eq "required_status_checks"
if (
  $statusRule.parameters.required_status_checks.Count -ne 1 -or
  $statusRule.parameters.required_status_checks[0].context -ne "pytest" -or
  $statusRule.parameters.required_status_checks[0].integration_id -ne 15368 -or
  -not $statusRule.parameters.strict_required_status_checks_policy
) {
  throw "Required pytest status is misconfigured."
}
if ($keys.Count -ne 1 -or $keys[0].title -ne "ValuCast scheduled refresh writer" -or $keys[0].read_only) {
  throw "Deploy-key state is wrong."
}
if (-not $secret) { throw "REFRESH_DEPLOY_KEY is missing." }
```

Expected: no output and no exception.

- [ ] **Step 4: Record the deferred integration proof**

Do not dispatch a refresh. Record that the next scheduled run that produces a
commit is the first end-to-end authentication proof. If it fails, disable the
ruleset before changing credentials or workflow code; do not weaken data or
model validators.
